"""Download official A-share index weights used by ETFs with material flows."""

from __future__ import annotations

import concurrent.futures
import io
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd
import random


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / ".deps"))
# Preload the legacy XLS reader before concurrent downloads. Importing it for
# the first time from several worker threads can expose a partially initialized
# module to pandas.
import xlrd  # noqa: E402,F401
OUT = ROOT / "data" / "index_weights.json"
FLOW_FILE = ROOT / "data" / "etf_flow_periods.json"
LIVE_FILE = ROOT / "data" / "latest_live_payload.json"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
MAX_DYNAMIC_INDEXES = 120
INDEX_ALIASES = {
    "399300": "000300",
    "399905": "000905",
    "399852": "000852",
    "399510": "000510",
}
INDEXES = {
    "000300": "沪深300",
    "000016": "上证50",
    "000905": "中证500",
    "000852": "中证1000",
    "000510": "中证A500",
    "000688": "科创50",
    "399001": "深证成指",
    "399006": "创业板指",
    "399673": "创业板50",
    "399850": "深证50",
    "930050": "中证A50",
    "931643": "科创创业50",
}


def fetch(url: str, timeout: int = 30, retries: int = 2) -> bytes:
    error = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.read()
        except Exception as exc:
            error = exc
            time.sleep(0.8 * (attempt + 1))
    raise RuntimeError(url) from error


def csindex_weight(code: str) -> list[dict]:
    url = f"https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/autofile/closeweight/{code}closeweight.xls"
    df = pd.read_excel(io.BytesIO(fetch(url)))
    df = df.iloc[:, :10]
    df.columns = ["date", "index_code", "index_name", "index_name_en", "stock_code", "stock_name", "stock_name_en", "exchange", "exchange_en", "weight"]
    df["stock_code"] = df["stock_code"].astype(str).str.extract(r"(\d+)", expand=False).str.zfill(6)
    df["weight"] = pd.to_numeric(df["weight"], errors="coerce")
    df = df.dropna(subset=["stock_code", "weight"])
    return [{"code": r.stock_code, "name": str(r.stock_name), "weight": float(r.weight)} for r in df.itertuples()]


def cni_weight(code: str = "399006") -> list[dict]:
    # 国证指数站点对高频下载限流，连续请求会返回“暂无数据”；这里加节流与重试
    time.sleep(random.uniform(0.4, 0.9))
    url = "https://www.cnindex.com.cn/sample-detail/download?" + urllib.parse.urlencode({"indexcode": code})
    raw = fetch(url, timeout=40, retries=3)
    if len(raw) < 100:
        raise RuntimeError(raw.decode("utf-8", errors="ignore")[:20] or "empty payload")
    df = pd.read_excel(io.BytesIO(raw))
    # 国证当前下载文件列：日期 / 样本代码 / 样本简称 / 所属行业 / 权重（%）
    if df.shape[1] >= 5:
        df = df.iloc[:, :5].copy()
        df.columns = ["date", "stock_code", "stock_name", "industry", "weight"]
    else:
        df = df.iloc[:, :6].copy()
        df.columns = ["date", "stock_code", "stock_name", "unused", "market_cap", "weight"]
    df["stock_code"] = df["stock_code"].astype(str).str.extract(r"(\d+)", expand=False).str.zfill(6)
    df["weight"] = pd.to_numeric(df["weight"], errors="coerce").fillna(0.0)
    df = df[df["stock_code"].notna()]
    return [{"code": r.stock_code, "name": str(r.stock_name), "weight": float(r.weight)} for r in df.itertuples()]


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def normalize_index_code(code: str) -> str:
    code = str(code or "").strip().upper()
    return INDEX_ALIASES.get(code, code)


def dynamic_index_candidates() -> tuple[list[str], dict[str, str], dict[str, float]]:
    """Rank official ETF tracking indexes by absolute flow across all periods."""
    flow = read_json(FLOW_FILE, {"items": []})
    live = read_json(LIVE_FILE, {"items": []})
    flow_by_code = {row["code"]: row for row in flow.get("items", [])}
    scores: dict[str, float] = {}
    names: dict[str, str] = {}
    for quote in live.get("items", []):
        index_code = normalize_index_code(quote.get("index_code"))
        item = flow_by_code.get(quote.get("code"))
        price = quote.get("price")
        if not index_code or not item or not isinstance(price, (int, float)):
            continue
        score = 0.0
        for period in item.get("periods", {}).values():
            if period and isinstance(period.get("delta_shares"), (int, float)):
                score += abs(period["delta_shares"] * price)
        if not score:
            continue
        scores[index_code] = scores.get(index_code, 0.0) + score
        names.setdefault(index_code, quote.get("index_name") or index_code)
    ordered = sorted(scores, key=scores.get, reverse=True)
    return ordered[:MAX_DYNAMIC_INDEXES], names, scores


def fetch_index_weight(code: str) -> tuple[list[dict], str, bool]:
    """Try both official index-company download formats and keep A-share baskets.

    返回 (rows, source, partial)。partial=True 表示官方只公开了前十大权重
    （如国证指数的 399001/399006），权重合计远小于 100，不能据此算占比。
    """
    errors = []
    for source, getter in (("中证指数有限公司", csindex_weight), ("国证指数", cni_weight)):
        try:
            rows = getter(code)
            all_rows = [row for row in rows if row["code"].startswith(("0", "3", "4", "6", "8"))]
            weighted = [row for row in all_rows if row.get("weight", 0) > 0]
            total = sum(row["weight"] for row in weighted)
            if len(weighted) >= 5 and total >= 95:
                return weighted, source, False
            if len(weighted) >= 5:
                # 官方只公开部分权重（如国证指数仅前十大）：保留全量成分，未公开的权重为 0
                return all_rows, source, True
        except Exception as exc:
            errors.append(f"{source}: {type(exc).__name__}")
    raise RuntimeError("; ".join(errors) or "no A-share constituents")


def symbol(code: str) -> str:
    if code.startswith(("6", "9")):
        return "sh" + code
    if code.startswith(("0", "3")):
        return "sz" + code
    return "bj" + code


def price_batch(codes: list[str]) -> dict[str, dict]:
    url = "https://qt.gtimg.cn/q=" + ",".join(symbol(c) for c in codes)
    raw = fetch(url, timeout=25).decode("gbk", errors="replace")
    out = {}
    for match in re.finditer(r'v_(?:sh|sz|bj)(\d{6})="([^"]*)"', raw):
        code, body = match.groups()
        fields = body.split("~")
        try:
            price = float(fields[3])
        except (IndexError, ValueError):
            price = None
        out[code] = {"name": fields[1] if len(fields) > 1 else "", "price": price, "quote_time": fields[30] if len(fields) > 30 else ""}
    return out


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="下载指数成分权重")
    parser.add_argument("--retry-failed", action="store_true", help="重试上次失败的指数（默认跳过）")
    args = parser.parse_args()

    candidates, official_names, scores = dynamic_index_candidates()
    required = list(dict.fromkeys([*INDEXES, "399006", *candidates]))
    previous_payload = read_json(OUT, {"indexes": {}, "coverage": {}})
    if previous_payload.get("schema_version") != 2:
        previous_payload = {"indexes": {}, "coverage": {}}
    previous = previous_payload.get("indexes", {})
    previous_failed = set(previous_payload.get("coverage", {}).get("failed_index_codes", []))
    if args.retry_failed:
        previous_failed = set()
    indexes = {code: previous[code] for code in required if code in previous and previous[code].get("constituents")}
    failed: dict[str, str] = {code: "previously confirmed non-A-share or unavailable" for code in required if code in previous_failed}

    def one(code: str):
        rows, source, partial = fetch_index_weight(code)
        return code, rows, source, partial

    missing = [code for code in required if code not in indexes and code not in previous_failed]
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        future_map = {pool.submit(one, code): code for code in missing}
        for future in concurrent.futures.as_completed(future_map):
            code = future_map[future]
            try:
                _, rows, source, partial = future.result()
                indexes[code] = {
                    "name": INDEXES.get(code) or official_names.get(code) or code,
                    "source": source,
                    "constituents": rows,
                    "flow_score_100m": round(scores.get(code, 0) / 1e8, 4),
                    "weight_partial": partial,
                    "weight_coverage": round(sum(x["weight"] for x in rows), 2),
                }
                tag = "（仅前十大权重）" if partial else ""
                print(f"Loaded {code}: {len(rows)} constituents{tag}")
            except Exception as exc:
                failed[code] = str(exc)
                print(f"Skipped {code}: {exc}")

    codes = sorted({x["code"] for idx in indexes.values() for x in idx["constituents"]})
    batches = [codes[i:i + 60] for i in range(0, len(codes), 60)]
    prices = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for part in pool.map(price_batch, batches):
            prices.update(part)
    for idx in indexes.values():
        total = sum(x["weight"] for x in idx["constituents"])
        for x in idx["constituents"]:
            q = prices.get(x["code"], {})
            x["price"] = q.get("price")
            if q.get("name"):
                x["name"] = q["name"]
        idx["weight_total"] = total

    payload = {
        "schema_version": 2,
        "generated_at": pd.Timestamp.now(tz="Asia/Shanghai").isoformat(timespec="seconds"),
        "indexes": indexes,
        "coverage": {
            "requested_indexes": len(required),
            "loaded_indexes": len(indexes),
            "failed_indexes": len(failed),
            "candidate_limit": MAX_DYNAMIC_INDEXES,
            "failed_index_codes": sorted(failed),
        },
        "sources": {
            "csindex": "https://www.csindex.com.cn/",
            "cni": "https://www.cnindex.com.cn/",
            "prices": "腾讯证券行情接口",
            "method": "个股估算金额=ETF估算净申购/赎回金额×交易所披露跟踪指数的最新成分股权重；仅穿透能取得官方A股成分权重的指数，债券、商品、境外指数不映射为A股。",
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(json.dumps({"indexes": len(indexes), "failed": len(failed), "stocks": len(codes), "prices": len(prices)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
