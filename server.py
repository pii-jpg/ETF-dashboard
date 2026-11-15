from __future__ import annotations

import concurrent.futures
import datetime as dt
import html
import json
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from socketserver import TCPServer
from pathlib import Path

import static_files

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
UNIVERSE_FILE = DATA_DIR / "etf_universe.json"
LIVE_CACHE_FILE = DATA_DIR / "latest_live_payload.json"
STOCK_PRICE_HISTORY_FILE = DATA_DIR / "stock_price_history.json"
SSE_SHARE_HISTORY_FILE = DATA_DIR / "sse_share_history.json"
SZSE_SHARE_HISTORY_FILE = DATA_DIR / "szse_share_history.json"
HOST, PORT = "127.0.0.1", 8765
QUOTE_TTL = 12
SSE_SUBCLASSES = ("01", "02", "03", "05", "06", "08", "09")
INDEX_SYMBOLS = {
    "000016": "sh000016",
    "000300": "sh000300",
    "000510": "sh000510",
    "000688": "sh000688",
    "000852": "sh000852",
    "000905": "sh000905",
    "399001": "sz399001",
    "399006": "sz399006",
}

_lock = threading.Lock()
_stock_price_lock = threading.Lock()
_quote_cache: dict = {"at": 0.0, "payload": None}
_share_history_cache: dict = {}
_share_history_lock = threading.Lock()


def fetch(url: str, referer: str = "", timeout: int = 25, retries: int = 4) -> bytes:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "*/*",
    }
    if referer:
        headers["Referer"] = referer
    last_error = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.read()
        except Exception as exc:
            last_error = exc
            # A partially updated bundled Python can temporarily fail to load
            # the IDNA codec. Retrying every quote batch only delays the local
            # cached-dashboard fallback by tens of seconds.
            if isinstance(exc, LookupError) and "idna" in str(exc).lower():
                break
            if attempt + 1 < retries:
                time.sleep(1.2 * (attempt + 1))
    raise last_error


def fetch_json(url: str, referer: str) -> dict | list:
    return json.loads(fetch(url, referer).decode("utf-8"))


def clean_html(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", value or "")).strip()


def sync_sse() -> list[dict]:
    base = "https://query.sse.com.cn/commonQuery.do"
    referer = "https://www.sse.com.cn/assortment/fund/etf/list/"

    params = {
        "isPagination": "true",
        "sqlId": "COMMON_JJZWZ_JJLB_L",
        "pageHelp.cacheSize": "1",
        "pageHelp.pageSize": "2000",
        "pageHelp.pageNo": "1",
        "pageHelp.beginPage": "1",
        "pageHelp.endPage": "1",
        "FUND_CODE": "",
        "COMPANY_NAME": "",
        "INDEX_NAME": "",
        "START_DATE": "",
        "END_DATE": "",
        "CATEGORY": "F100",
        "SUBCLASS": "",
        "SWING_TRADE": "",
        "type": "inParams",
        "FUND_CODE_ASC": "1",
    }
    obj = fetch_json(base + "?" + urllib.parse.urlencode(params), "https://etf.sse.com.cn/fundlist/")
    rows = obj.get("result", [])
    expected = int(obj.get("pageHelp", {}).get("total") or len(rows))
    if len(rows) != expected or len(rows) < 800:
        raise RuntimeError(f"上交所 ETF 总清单不完整：期望 {expected}，实际 {len(rows)}")

    # The current all-ETF endpoint is complete but does not expose index codes.
    # Retain codes from the legacy category endpoint as optional enrichment.
    legacy_base = "https://query.sse.com.cn/commonSoaQuery.do"

    def legacy_one(subclass: str) -> list[dict]:
        params = {
            "isPagination": "true",
            "pageHelp.pageSize": "2000",
            "pageHelp.pageNo": "1",
            "pageHelp.beginPage": "1",
            "pageHelp.cacheSize": "1",
            "pageHelp.endPage": "1",
            "pagecache": "false",
            "sqlId": "FUND_LIST",
            "fundType": "00",
            "subClass": subclass,
        }
        obj = fetch_json(legacy_base + "?" + urllib.parse.urlencode(params), referer)
        rows = obj.get("pageHelp", {}).get("data", [])
        return [row for row in rows if str(row.get("fundCode", "")).isdigit()]

    legacy: dict[str, dict] = {}
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            for legacy_rows in pool.map(legacy_one, SSE_SUBCLASSES):
                for row in legacy_rows:
                    legacy[str(row.get("fundCode", ""))] = row
    except Exception as exc:
        print(f"上交所旧版指数代码补充失败：{type(exc).__name__}: {exc}")

    result = []
    for row in rows:
        code = str(row.get("FUND_CODE", ""))
        if not code.isdigit():
            continue
        detail = legacy.get(code, {})
        result.append({
            "code": code,
            "name": row.get("FUND_ABBR") or row.get("FUND_EXPANSION_ABBR") or "",
            "manager": row.get("COMPANY_NAME") or detail.get("companyName") or "",
            "index_name": row.get("INDEX_NAME") or detail.get("INDEX_NAME") or "",
            "index_code": str(detail.get("INDEX_CODE") or "").strip(),
            "exchange": "SH",
            "listing_date": row.get("LISTING_DATE") or detail.get("listingDate") or "",
            "official_scale_shares_10k": None,
        })
    return result


def parse_szse_row(row: dict) -> dict | None:
    code_match = re.search(r"(\d{6})", row.get("sys_key", ""))
    if not code_match:
        return None
    code = code_match.group(1)
    name_match = re.search(r"<u>(.*?)</u>", row.get("kzjcurl", ""), re.S)
    name = clean_html(name_match.group(1) if name_match else row.get("kzjcurl", ""))
    scale_raw = clean_html(row.get("dqgm", "")).replace(",", "")
    try:
        scale = float(scale_raw)
    except ValueError:
        scale = None
    index_text = clean_html(row.get("nhzs", ""))
    index_match = re.match(r"\s*([0-9A-Za-z]+)", index_text)
    return {
        "code": code,
        "name": name,
        "manager": clean_html(row.get("glrmc", "")),
        "index_name": index_text,
        "index_code": index_match.group(1) if index_match else "",
        "exchange": "SZ",
        "listing_date": "",
        "official_scale_shares_10k": scale,
    }


def scan_szse_etf_codes() -> list[dict]:
    """Fallback for SZSE WAF outages: 159xxx is the exchange ETF code segment."""
    codes = [f"159{i:03d}" for i in range(1000)]
    batches = [codes[i:i + 60] for i in range(0, len(codes), 60)]

    def one(batch: list[str]) -> list[dict]:
        symbols = ",".join("sz" + code for code in batch)
        raw = fetch("https://qt.gtimg.cn/q=" + symbols, timeout=25).decode("gbk", errors="replace")
        rows = []
        for match in re.finditer(r'v_sz(159\d{3})="([^"]*)"', raw):
            code, body = match.groups()
            fields = body.split("~")
            name = fields[1].strip() if len(fields) > 1 else ""
            try:
                last_price = float(fields[3])
            except (IndexError, ValueError):
                last_price = 0
            # 159xxx also contains paired subscription/redemption helper codes.
            # They may have a name but no tradable price, so they are not ETFs.
            if not name or len(fields) < 31 or last_price <= 0:
                continue
            rows.append({
                "code": code, "name": name, "manager": "", "index_name": "", "index_code": "",
                "exchange": "SZ", "listing_date": "", "official_scale_shares_10k": None,
            })
        return rows

    result: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for rows in pool.map(one, batches):
            result.extend(rows)
    if len(result) < 500:
        raise RuntimeError(f"深市 ETF 代码扫描结果异常：仅返回 {len(result)} 只")
    return result


def sync_szse() -> tuple[list[dict], str]:
    base = "https://www.szse.cn/api/report/ShowReport/data"
    referer = "https://www.szse.cn/market/product/list/etfList/"

    def page_url(page: int) -> str:
        params = {"SHOWTYPE": "JSON", "CATALOGID": "1945", "TABKEY": "tab1", "PAGENO": str(page)}
        if page == 1:
            params["loading"] = "first"
        return base + "?" + urllib.parse.urlencode(params)

    try:
        first = fetch_json(page_url(1), referer)[0]
    except Exception:
        return scan_szse_etf_codes(), "Tencent quote scan (SZSE 159xxx ETF segment)"
    page_count = int(first["metadata"]["pagecount"])
    pages: list[list[dict] | None] = [None] * page_count
    pages[0] = first.get("data", [])

    def one(page: int) -> tuple[int, list[dict]]:
        obj = fetch_json(page_url(page), referer)[0]
        return page, obj.get("data", [])

    try:
        for page in range(2, page_count + 1):
            _, rows = one(page)
            pages[page - 1] = rows
            time.sleep(0.16)
    except Exception:
        return scan_szse_etf_codes(), "Tencent quote scan (SZSE 159xxx ETF segment)"

    result = []
    for rows in pages:
        for row in rows or []:
            parsed = parse_szse_row(row)
            if parsed:
                result.append(parsed)
    expected = int(first["metadata"]["recordcount"])
    if len(result) != expected:
        raise RuntimeError(f"深交所 ETF 清单不完整：期望 {expected}，实际 {len(result)}")
    return result, "SZSE official ETF list"


def sync_universe() -> dict:
    DATA_DIR.mkdir(exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        sse_future = pool.submit(sync_sse)
        szse_future = pool.submit(sync_szse)
        sse = sse_future.result()
        szse, szse_source = szse_future.result()
    merged = {row["code"]: row for row in [*sse, *szse]}
    payload = {
        "synced_at": dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat(timespec="seconds"),
        "source_counts": {"SSE": len(sse), "SZSE": len(szse), "unique": len(merged)},
        "universe_sources": {"SSE": "SSE official ETF list", "SZSE": szse_source},
        "items": sorted(merged.values(), key=lambda row: row["code"]),
    }
    UNIVERSE_FILE.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return payload


def load_universe() -> dict:
    if not UNIVERSE_FILE.exists():
        return sync_universe()
    return json.loads(UNIVERSE_FILE.read_text(encoding="utf-8"))


def number(values: list[str], index: int) -> float | None:
    try:
        value = values[index].strip()
        return float(value) if value not in ("", "--") else None
    except (IndexError, ValueError):
        return None


def quote_batch(items: list[dict]) -> list[dict]:
    symbols = ",".join(("sh" if row["exchange"] == "SH" else "sz") + row["code"] for row in items)
    raw = fetch("https://qt.gtimg.cn/q=" + symbols, timeout=20).decode("gbk", errors="replace")
    by_code = {row["code"]: row for row in items}
    result = []
    for match in re.finditer(r'v_(?:sh|sz)(\d{6})="([^"]*)"', raw):
        code, body = match.groups()
        fields = body.split("~")
        base = by_code.get(code)
        if not base or len(fields) < 45:
            continue
        price = number(fields, 3)
        quote_scale = number(fields, 44)
        official_shares = base.get("official_scale_shares_10k")
        disclosed_scale = official_shares * price / 10000 if official_shares and price else None
        result.append({
            **base,
            "name": fields[1] or base["name"],
            "price": price,
            "prev_close": number(fields, 4),
            "open": number(fields, 5),
            "change": number(fields, 31),
            "pct": number(fields, 32),
            "high": number(fields, 33),
            "low": number(fields, 34),
            "volume_100m_shares": (number(fields, 36) or 0) / 1_000_000,
            "amount_100m": (number(fields, 37) or 0) / 10_000,
            "turnover": number(fields, 38),
            "scale_100m": quote_scale or disclosed_scale,
            "quote_time": fields[30] if len(fields) > 30 else "",
            "currency": fields[84] if len(fields) > 84 else "CNY",
        })
    return result


def build_live_payload(force: bool = False) -> dict:
    now = time.time()
    with _lock:
        if not force and _quote_cache["payload"] and now - _quote_cache["at"] < QUOTE_TTL:
            return _quote_cache["payload"]
        universe = load_universe()
        items = universe["items"]
        batches = [items[i:i + 60] for i in range(0, len(items), 60)]
        records: list[dict] = []
        errors: list[str] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(quote_batch, batch) for batch in batches]
            for future in concurrent.futures.as_completed(futures):
                try:
                    records.extend(future.result())
                except Exception as exc:
                    errors.append(str(exc))
        if not records:
            raise RuntimeError("实时行情接口未返回任何 ETF 数据")
        records.sort(key=lambda row: row["code"])
        timestamps = [row["quote_time"] for row in records if row["quote_time"]]
        summary = {
            "universe_count": len(items),
            "quote_count": len(records),
            "coverage": round(len(records) / len(items) * 100, 2) if items else 0,
            "up": sum(1 for row in records if (row["pct"] or 0) > 0),
            "down": sum(1 for row in records if (row["pct"] or 0) < 0),
            "flat": sum(1 for row in records if (row["pct"] or 0) == 0),
            "amount_100m": round(sum(row["amount_100m"] or 0 for row in records), 2),
            "scale_100m": round(sum(row["scale_100m"] or 0 for row in records), 2),
            "as_of": max(timestamps) if timestamps else "",
            "batch_errors": len(errors),
        }
        universe_detail = universe.get("universe_sources", {})
        source_labels = {
            "SSE official ETF list": "上交所官方 ETF 列表",
            "SZSE official ETF list": "深交所官方 ETF 列表",
            "Tencent quote scan (SZSE 159xxx ETF segment)": "深市 ETF 专用代码段实时行情扫描",
        }
        payload = {
            "generated_at": dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat(timespec="seconds"),
            "universe_synced_at": universe["synced_at"],
            "sources": {
                "universe": "；".join(source_labels.get(v, v) for v in universe_detail.values()),
                "universe_detail": universe_detail,
                "quotes": "腾讯证券行情接口",
                "quote_refresh_seconds": QUOTE_TTL,
                "disclosure_note": "价格与成交为最新行情；ETF规模按行情或交易所最近披露值，非盘中申赎份额。",
            },
            "summary": summary,
            "items": records,
        }
        DATA_DIR.mkdir(exist_ok=True)
        cache_tmp = LIVE_CACHE_FILE.with_suffix(".tmp")
        cache_tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        cache_tmp.replace(LIVE_CACHE_FILE)
        _quote_cache.update(at=now, payload=payload)
        return payload


def load_last_live_payload(error: Exception) -> dict | None:
    if not LIVE_CACHE_FILE.exists():
        return None
    try:
        payload = json.loads(LIVE_CACHE_FILE.read_text(encoding="utf-8"))
        payload["stale"] = True
        payload["live_error"] = str(error)
        payload["sources"]["quotes"] += "（实时连接中，当前显示最近成功快照）"
        return payload
    except Exception:
        return None


def stock_symbol(code: str, is_index: bool = False) -> str:
    if is_index:
        return INDEX_SYMBOLS[code]
    if code.startswith(("6", "9")):
        return "sh" + code
    if code.startswith(("0", "3")):
        return "sz" + code
    return "bj" + code


def read_stock_price_cache() -> dict:
    try:
        payload = json.loads(STOCK_PRICE_HISTORY_FILE.read_text(encoding="utf-8"))
        if payload.get("schema_version") == 1 and isinstance(payload.get("items"), dict):
            return payload
    except Exception:
        pass
    return {"schema_version": 1, "items": {}}


def write_stock_price_cache(payload: dict) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    tmp = STOCK_PRICE_HISTORY_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(STOCK_PRICE_HISTORY_FILE)


def fetch_stock_price_history(code: str, start: dt.date, end: dt.date, is_index: bool = False) -> dict:
    # Include a buffer so suspended stocks can use the most recent prior close.
    fetch_start = start - dt.timedelta(days=20)
    symbol = stock_symbol(code, is_index)
    params = f"{symbol},day,{fetch_start.isoformat()},{end.isoformat()},800"
    url = "https://web.ifzq.gtimg.cn/appstock/app/kline/kline?" + urllib.parse.urlencode({"param": params})
    payload = json.loads(fetch(url, timeout=30, retries=3).decode("utf-8"))
    rows = payload.get("data", {}).get(symbol, {}).get("day", [])
    prices = []
    for row in rows:
        try:
            date_text, close = str(row[0]), float(row[2])
        except (IndexError, TypeError, ValueError):
            continue
        if close > 0 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_text):
            prices.append([date_text, close])
    return {"start": start.isoformat(), "end": end.isoformat(), "prices": prices}


def build_stock_price_history(codes: list[str], start: dt.date, end: dt.date, index_codes: list[str] | None = None) -> dict:
    with _stock_price_lock:
        cache = read_stock_price_cache()
        items = cache["items"]
        cache_changed = False
        requests = [(code, code, False) for code in codes]
        requests.extend((f"index:{code}", code, True) for code in (index_codes or []))
        missing = []
        for key, code, is_index in requests:
            item = items.get(key, {})
            if not (
                item.get("start", "9999-12-31") <= start.isoformat()
                and item.get("end", "0000-01-01") >= end.isoformat()
                and item.get("prices")
            ):
                missing.append((key, code, is_index))

        def one(request: tuple[str, str, bool]) -> tuple[str, dict]:
            key, code, is_index = request
            previous = items.get(key, {})
            previous_start = dt.date.fromisoformat(previous["start"]) if previous.get("start") else None
            previous_end = dt.date.fromisoformat(previous["end"]) if previous.get("end") else None
            requested_start = min(start, previous_start) if previous_start else start
            requested_end = max(end, previous_end) if previous_end else end
            gaps: list[tuple[dt.date, dt.date]] = []
            if previous_start is None or previous_end is None or not previous.get("prices"):
                gaps.append((start, end))
            else:
                if start < previous_start:
                    gaps.append((start, previous_start - dt.timedelta(days=1)))
                if end > previous_end:
                    gaps.append((previous_end + dt.timedelta(days=1), end))
            try:
                new_prices = []
                for gap_start, gap_end in gaps:
                    if gap_start <= gap_end:
                        row = fetch_stock_price_history(code, gap_start, gap_end, is_index)
                        new_prices.extend(row["prices"])
                # Existing dates win on overlap, so an incremental refresh never
                # rewrites already cached historical closes.
                merged = {price_row[0]: price_row for price_row in new_prices}
                merged.update({price_row[0]: price_row for price_row in previous.get("prices", [])})
                return key, {
                    "start": requested_start.isoformat(),
                    "end": requested_end.isoformat(),
                    "prices": [merged[date_key] for date_key in sorted(merged)],
                }
            except Exception as exc:
                return key, {
                    "start": previous.get("start", start.isoformat()),
                    "end": previous.get("end", end.isoformat()),
                    "prices": previous.get("prices", []),
                    "error": str(exc),
                }

        if missing:
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                for key, row in pool.map(one, missing):
                    items[key] = row
            cache_changed = True

        if cache_changed:
            cache["updated_at"] = dt.datetime.now().astimezone().isoformat(timespec="seconds")
            cache["source"] = "腾讯证券未复权日线收盘价"
            write_stock_price_cache(cache)

        selected = {key: items[key] for key, _, _ in requests if key in items}
        return {
            "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "source": "腾讯证券未复权日线收盘价",
            "items": selected,
        }


def load_share_history(path: Path, nested: bool = False) -> dict[str, dict]:
    """Return ``{date: {code: shares}}`` for one exchange, re-parsed only when the file changes.

    The two history files total ~22 MB; parsing them per request would stall the
    dashboard, so the compact form (names dropped) is kept until mtime or size move.
    """
    try:
        stat = path.stat()
    except OSError:
        return {}
    stamp = (stat.st_mtime, stat.st_size)
    with _share_history_lock:
        cached = _share_history_cache.get(str(path))
    if cached and cached[0] == stamp:
        return cached[1]
    try:
        raw = json.loads(path.read_text(encoding="utf-8")).get("snapshots") or {}
    except Exception:
        return cached[1] if cached else {}
    snapshots: dict[str, dict] = {}
    for date, rows in raw.items():
        if not rows:
            continue
        if nested:
            snapshots[date] = {code: row.get("shares") for code, row in rows.items() if row and row.get("shares") is not None}
        else:
            snapshots[date] = dict(rows)
    with _share_history_lock:
        _share_history_cache[str(path)] = (stamp, snapshots)
    return snapshots


def snapshot_shares(target: dt.date, sse: dict, szse: dict, sse_dates: list, szse_dates: list) -> dict:
    """Every ETF's official share count at the last snapshot on or before ``target``."""
    wanted = target.isoformat()
    sse_anchor = ([date for date in sse_dates if date <= wanted] or [None])[-1]
    shares: dict[str, dict] = {}
    if sse_anchor:
        for code, value in sse[sse_anchor].items():
            shares[code] = {"date": sse_anchor, "shares": int(value)}
    szse_shares: dict[str, dict] = {}
    eligible_szse = [date for date in szse_dates if date <= wanted]
    if not eligible_szse and szse_dates:
        # 目标日早于深交所本地历史起点时退回到最早可用快照，
        # 否则深市 ETF（如创业板指成分 ETF）在区间起点全部缺失，整组统计会显示为 0。
        eligible_szse = [szse_dates[0]]
    for date in reversed(eligible_szse):
        for code, value in szse[date].items():
            if code not in szse_shares:
                szse_shares[code] = {"date": date, "shares": int(value)}
    shares.update(szse_shares)
    return {
        "requested": wanted,
        "date": sse_anchor or (eligible_szse[-1] if eligible_szse else None),
        "sse_date": sse_anchor,
        "szse_date": eligible_szse[-1] if eligible_szse else None,
        "shares": shares,
    }


def build_shares_range(start: dt.date, end: dt.date) -> dict:
    """Official share counts for every ETF at both ends of a custom period."""
    sse = load_share_history(SSE_SHARE_HISTORY_FILE)
    szse = load_share_history(SZSE_SHARE_HISTORY_FILE, nested=True)
    if not sse and not szse:
        raise ValueError("本地没有ETF份额历史缓存，请先运行 build_flow_history.py")
    if end < start:
        raise ValueError("自选止日不能早于起日")
    sse_dates = sorted(date for date, rows in sse.items() if rows)
    szse_dates = sorted(date for date, rows in szse.items() if rows)
    earliest = min(sse_dates[0] if sse_dates else end.isoformat(), szse_dates[0] if szse_dates else end.isoformat())
    if start.isoformat() < earliest:
        raise ValueError(f"自选起日早于本地历史起点 {earliest}")
    return {
        "earliest": earliest,
        "latest": max(sse_dates[-1] if sse_dates else end.isoformat(), szse_dates[-1] if szse_dates else end.isoformat()),
        "start": snapshot_shares(start, sse, szse, sse_dates, szse_dates),
        "end": snapshot_shares(end, sse, szse, sse_dates, szse_dates),
    }


class Handler(SimpleHTTPRequestHandler):
    # HTTP/1.1 才能让浏览器对带 ETag 的响应做协商缓存与连接复用；
    # 每个响应的 Content-Length 都完整给出，不靠关闭连接标定正文长度
    protocol_version = "HTTP/1.1"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/etfs":
            # try 只包「取数与降级」：响应一旦开始写，写出失败就不能再发第二个响应
            status, stale = 200, False
            try:
                force = urllib.parse.parse_qs(parsed.query).get("force", ["0"])[0] == "1"
                payload = build_live_payload(force)
            except Exception as exc:
                payload = load_last_live_payload(exc)
                if payload is None:
                    payload = {"error": str(exc)}
                    status = 502
                else:
                    stale = True
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            body, encoding = static_files.compress_body(self, body)
            self.send_response(status)
            if stale:
                self.send_header("X-Data-Stale", "1")
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            if encoding:
                self.send_header("Content-Encoding", encoding)
                self.send_header("Vary", "Accept-Encoding")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/api/stock-price-history":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                codes = list(dict.fromkeys(code for code in query.get("codes", [""])[0].split(",") if re.fullmatch(r"\d{6}", code)))
                index_codes = list(dict.fromkeys(code for code in query.get("indexes", [""])[0].split(",") if code in INDEX_SYMBOLS))
                start = dt.date.fromisoformat(query.get("start", [""])[0])
                end = dt.date.fromisoformat(query.get("end", [""])[0])
                if (not codes and not index_codes) or len(codes) > 60 or len(index_codes) > 10:
                    raise ValueError("股票代码数量必须为 0 至 60，指数代码数量必须为 0 至 10，且至少提供一种代码")
                if end < start or (end - start).days > 900:
                    raise ValueError("历史价格日期区间无效")
                payload = build_stock_price_history(codes, start, end, index_codes)
                body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                self.send_response(200)
            except Exception as exc:
                body = json.dumps({"error": str(exc)}, ensure_ascii=False).encode("utf-8")
                self.send_response(400)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/api/shares-range":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                try:
                    start = dt.date.fromisoformat(query.get("start", [""])[0])
                    end = dt.date.fromisoformat(query.get("end", [""])[0])
                except ValueError:
                    raise ValueError("自选区间格式应为 YYYY-MM-DD")
                payload = build_shares_range(start, end)
                body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                self.send_response(200)
            except Exception as exc:
                body = json.dumps({"error": str(exc)}, ensure_ascii=False).encode("utf-8")
                self.send_response(400)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/":
            self.path = "/index.html"
        if static_files.try_serve(self, ROOT, urllib.parse.unquote(self.path.split("?", 1)[0])):
            return
        super().do_GET()

    def log_message(self, fmt, *args):
        print("[%s] %s" % (self.log_date_time_string(), fmt % args))


class DashboardHTTPServer(ThreadingHTTPServer):
    """Bind directly to the numeric loopback address.

    Python's HTTPServer normally performs a reverse DNS lookup while binding.
    The bundled desktop Python can temporarily have an unusable ``idna``
    codec after a runtime update, even though numeric-address sockets work.
    The dashboard is local-only, so a DNS-derived server name is unnecessary.
    """

    def server_bind(self) -> None:
        TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = int(port)


def main() -> None:
    if "--sync" in sys.argv:
        payload = sync_universe()
        print(json.dumps({"synced_at": payload["synced_at"], **payload["source_counts"]}, ensure_ascii=False))
        return
    try:
        server = DashboardHTTPServer((HOST, PORT), Handler)
    except OSError as exc:
        print(f"无法监听 {HOST}:{PORT}：{exc}")
        print("可能已有看板正在运行，请打开 http://127.0.0.1:8765")
        raise SystemExit(1)
    url = f"http://{HOST}:{PORT}"
    print(f"ETF 实时看板：{url}")
    print("关闭此窗口即可停止服务。")
    if "--open" in sys.argv:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    server.serve_forever()


if __name__ == "__main__":
    main()
