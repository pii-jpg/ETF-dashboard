"""Build multi-period SSE ETF share-change snapshot for the web dashboard."""

from __future__ import annotations

import concurrent.futures
import datetime as dt
import io
import json
import random
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "etf_flow_periods.json"
URL = "https://query.sse.com.cn/commonQuery.do"
SZSE_REPORT_URL = "https://www.szse.cn/api/report/ShowReport"
SZSE_REPORT_REFERER = "https://www.szse.cn/market/fund/volume/etf/index.html"
# 不得晚于最早周期的基准日（2024-01-01 → 2024-01-02），也不得晚于 SSE 缓存的起点（基准日 - 7 天 = 2023-12-25）
SZSE_HISTORY_START = dt.date(2023, 12, 29)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/132 Safari/537.36"

PERIODS = [
    ("day", "日", lambda d: d - dt.timedelta(days=1)),
    ("week", "周", lambda d: d - dt.timedelta(days=7)),
    ("1m", "1个月", lambda d: add_months(d, -1)),
    ("2m", "2个月", lambda d: add_months(d, -2)),
    ("3m", "3个月", lambda d: add_months(d, -3)),
    ("6m", "6个月", lambda d: add_months(d, -6)),
    ("12m", "12个月", lambda d: add_months(d, -12)),
    ("ytd", "今年以来", lambda d: dt.date(d.year - 1, 12, 31)),
    ("range20240924_20260630", "20240924-20260630", lambda d: (dt.date(2024, 9, 24), dt.date(2026, 6, 30))),
]


def add_months(day: dt.date, months: int) -> dt.date:
    month0 = day.year * 12 + day.month - 1 + months
    year, month_index = divmod(month0, 12)
    month = month_index + 1
    if month == 12:
        next_month = dt.date(year + 1, 1, 1)
    else:
        next_month = dt.date(year, month + 1, 1)
    last = (next_month - dt.timedelta(days=1)).day
    return dt.date(year, month, min(day.day, last))


def fetch_bytes(url: str, params: dict[str, str], retries: int = 4) -> bytes:
    full = url + "?" + urllib.parse.urlencode(params)
    error: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(full, headers={"User-Agent": UA, "Referer": "https://www.sse.com.cn/"})
            with urllib.request.urlopen(req, timeout=30) as response:
                return response.read()
        except Exception as exc:
            error = exc
            time.sleep(0.8 * (attempt + 1) + random.random() * 0.4)
    raise RuntimeError(f"Failed to fetch {full}") from error


def fetch_sse_date(day: dt.date) -> list[dict]:
    params = {
        "isPagination": "true", "pageHelp.pageSize": "10000", "pageHelp.pageNo": "1",
        "pageHelp.beginPage": "1", "pageHelp.cacheSize": "1", "pageHelp.endPage": "1",
        "sqlId": "COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L",
        "STAT_DATE": day.isoformat(),
    }
    obj = json.loads(fetch_bytes(URL, params))
    rows = obj.get("result") or []
    result = []
    for row in rows:
        try:
            shares = float(row.get("TOT_VOL")) * 10000
        except (TypeError, ValueError):
            continue
        result.append({
            "code": str(row.get("SEC_CODE", "")).zfill(6),
            "name": row.get("SEC_NAME") or "",
            "etf_type": row.get("ETF_TYPE") or "",
            "shares": round(shares),
        })
    return result


def fetch_szse_range(start: dt.date, end: dt.date) -> dict[str, dict[str, dict]]:
    """Download official SZSE ETF outstanding shares for an inclusive date range."""
    params = {
        "SHOWTYPE": "xlsx",
        "CATALOGID": "scsj_fund_jjgm",
        "jjlb": "ETF",
        "txtStart": start.isoformat(),
        "txtEnd": end.isoformat(),
    }
    full = SZSE_REPORT_URL + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(
        full,
        headers={"User-Agent": UA, "Referer": SZSE_REPORT_REFERER},
    )
    error: Exception | None = None
    raw = b""
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                raw = response.read()
            if not raw.startswith(b"PK"):
                raise RuntimeError("SZSE scale download did not return an XLSX file")
            break
        except Exception as exc:
            error = exc
            time.sleep(1.2 * (attempt + 1) + random.random() * 0.4)
    else:
        raise RuntimeError(f"Failed to download SZSE ETF shares {start} to {end}") from error

    frame = pd.read_excel(io.BytesIO(raw))
    if frame.shape[1] < 4:
        raise RuntimeError(f"Unexpected SZSE ETF scale columns: {list(frame.columns)}")
    frame = frame.iloc[:, :4].copy()
    frame.columns = ["date", "code", "name", "shares"]
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.date
    frame["code"] = frame["code"].astype(str).str.extract(r"(\d{6})", expand=False)
    frame["shares"] = pd.to_numeric(frame["shares"], errors="coerce")
    frame = frame.dropna(subset=["date", "code", "shares"])
    snapshots: dict[str, dict[str, dict]] = {}
    for row in frame.itertuples(index=False):
        day = row.date.isoformat()
        snapshots.setdefault(day, {})[row.code] = {
            "name": str(row.name or ""),
            "shares": round(float(row.shares)),
        }
    return snapshots


def update_szse_history(latest: dt.date) -> dict:
    """Maintain a complete official SZSE history from SZSE_HISTORY_START onward."""
    history_file = ROOT / "data" / "szse_share_history.json"
    try:
        history = json.loads(history_file.read_text(encoding="utf-8"))
    except Exception:
        history = {"snapshots": {}}
    if not history.get("official"):
        # Discard the former market-cap/price-derived snapshots during migration;
        # mixing inferred and official shares would create artificial daily jumps.
        history = {"snapshots": {}}
    snapshots = history.setdefault("snapshots", {})
    present = sorted(day for day, rows in snapshots.items() if rows)
    ranges: list[tuple[dt.date, dt.date]] = []
    if not present:
        ranges.append((SZSE_HISTORY_START, latest))
    else:
        first = dt.date.fromisoformat(present[0])
        last = dt.date.fromisoformat(present[-1])
        if first > SZSE_HISTORY_START:
            ranges.append((SZSE_HISTORY_START, first - dt.timedelta(days=1)))
        if last < latest:
            ranges.append((last + dt.timedelta(days=1), latest))

    # The exchange validates a maximum six-month range. Five-month chunks leave
    # a safety margin and keep each workbook small enough to parse quickly.
    for range_start, range_end in ranges:
        cursor = range_start
        while cursor <= range_end:
            end = min(add_months(cursor, 5) - dt.timedelta(days=1), range_end)
            print(f"Downloading official SZSE ETF shares: {cursor} to {end}")
            snapshots.update(fetch_szse_range(cursor, end))
            cursor = end + dt.timedelta(days=1)

    history.update({
        "updated_at": dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat(timespec="seconds"),
        "source": SZSE_REPORT_REFERER,
        "official": True,
        "range_start": min(snapshots) if snapshots else None,
        "range_end": max(snapshots) if snapshots else None,
    })
    history_file.parent.mkdir(parents=True, exist_ok=True)
    history_file.write_text(json.dumps(history, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return history


def nearest_available(target: dt.date, max_back: int = 12) -> tuple[dt.date, list[dict]]:
    for offset in range(max_back + 1):
        day = target - dt.timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        rows = fetch_sse_date(day)
        if rows:
            return day, rows
    raise RuntimeError(f"No SSE ETF share data near {target}")


def main() -> None:
    today = dt.date.today()
    latest_date, latest_rows = nearest_available(today)
    targets = []
    for key, label, fn in PERIODS:
        spec = fn(latest_date)
        if isinstance(spec, tuple):
            targets.append((key, label, spec[0], spec[1]))
        else:
            targets.append((key, label, spec, None))

    def one(item):
        key, label, target, end = item
        actual, rows = nearest_available(target)
        if end is None:
            return key, label, target, actual, rows, None, None, None
        end_actual, end_rows = nearest_available(end)
        return key, label, target, actual, rows, end, end_actual, end_rows

    history = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for key, label, target, actual, rows, end, end_actual, end_rows in pool.map(one, targets):
            history[key] = {
                "label": label,
                "target_date": target.isoformat(),
                "base_date": actual.isoformat(),
                "end_target": end.isoformat() if end else None,
                "end_date": end_actual.isoformat() if end_actual else None,
                "rows": rows,
                "end_rows": end_rows,
            }

    latest_by_code = {r["code"]: r for r in latest_rows}
    items = []
    focus_tokens = ("300", "50ETF", "500ETF", "1000ETF", "A500", "科创50", "创业板")
    for code, current in latest_by_code.items():
        periods = {}
        for key, _, _, _ in targets:
            base_map = {r["code"]: r for r in history[key]["rows"]}
            base = base_map.get(code)
            if not base:
                periods[key] = None
                continue
            if history[key].get("end_rows") is not None:
                end_base = {r["code"]: r for r in history[key]["end_rows"]}.get(code)
                if not end_base:
                    periods[key] = None
                    continue
                delta = end_base["shares"] - base["shares"]
                periods[key] = {
                    "base_date": history[key]["base_date"],
                    "end_date": history[key]["end_date"],
                    "base_shares": base["shares"],
                    "end_shares": end_base["shares"],
                    "delta_shares": delta,
                    "delta_pct": delta / base["shares"] if base["shares"] else None,
                }
                continue
            delta = current["shares"] - base["shares"]
            periods[key] = {
                "base_date": history[key]["base_date"],
                "base_shares": base["shares"],
                "delta_shares": delta,
                "delta_pct": delta / base["shares"] if base["shares"] else None,
            }
        items.append({
            "code": code, "name": current["name"], "exchange": "SH", "etf_type": current["etf_type"],
            "focus": any(token in current["name"] for token in focus_tokens),
            "latest_shares": current["shares"], "periods": periods,
        })

    # Deep-market shares come from the SZSE official ETF-scale report. Unlike the
    # old quote-scale approximation, this supplies actual daily outstanding shares
    # and supports every dashboard period and trend point.
    sz_history = update_szse_history(latest_date)
    sz_snapshots = sz_history.get("snapshots", {})
    snapshot_dates = sorted(day for day, rows in sz_snapshots.items() if rows and day <= latest_date.isoformat())
    if not snapshot_dates:
        raise RuntimeError("SZSE official ETF share history is empty")
    latest_sz_date = snapshot_dates[-1]
    current_sz = sz_snapshots[latest_sz_date]
    target_map = {key: target for key, _, target, _ in targets}
    end_map = {key: end for key, _, _, end in targets}
    for code, current in current_sz.items():
        periods = {}
        for key, _, _, _ in targets:
            candidates = [d for d in snapshot_dates if d <= target_map[key].isoformat() and code in sz_snapshots.get(d, {})]
            if not candidates:
                periods[key] = None
                continue
            base_date = candidates[-1]
            base_shares = sz_snapshots[base_date][code]["shares"]
            if end_map.get(key):
                end_candidates = [d for d in snapshot_dates if d <= end_map[key].isoformat() and code in sz_snapshots.get(d, {})]
                if not end_candidates:
                    periods[key] = None
                    continue
                end_date = end_candidates[-1]
                end_shares = sz_snapshots[end_date][code]["shares"]
                delta = end_shares - base_shares
                periods[key] = {"base_date": base_date, "end_date": end_date, "base_shares": base_shares, "end_shares": end_shares, "delta_shares": delta, "delta_pct": delta / base_shares if base_shares else None}
                continue
            delta = current["shares"] - base_shares
            periods[key] = {"base_date": base_date, "base_shares": base_shares, "delta_shares": delta, "delta_pct": delta / base_shares if base_shares else None}
        items.append({
            "code": code, "name": current["name"], "exchange": "SZ", "etf_type": "ETF",
            "focus": any(token in current["name"] for token in focus_tokens),
            "latest_shares": current["shares"], "periods": periods,
        })

    payload = {
        "generated_at": dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat(timespec="seconds"),
        "latest_date": latest_date.isoformat(),
        "periods": {key: {k: v for k, v in history[key].items() if k not in ("rows", "end_rows", "end_target")} for key, _, _, _ in targets},
        "items": sorted(items, key=lambda x: (x["exchange"], x["code"])),
        "sources": {
            "sse": "https://www.sse.com.cn/assortment/fund/etf/list/scale/",
            "szse": SZSE_REPORT_REFERER,
            "method": "ETF基金份额变化=最新披露份额-周期起点最近可用交易日份额；估算金额=份额变化×盘中最新价。",
            "coverage": "上交所、深交所均使用交易所官方日频ETF基金份额；缺失日期不补零、不插值。",
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(json.dumps({"latest_date": payload["latest_date"], "items": len(items), "periods": payload["periods"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
