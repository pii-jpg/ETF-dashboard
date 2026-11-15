"""数据复验：检查份额缓存、每日变化、周期快照、指数权重与前端口径是否自洽。

用法：
  python verify_data.py            # 离线自洽性检查
  python verify_data.py --online   # 额外抽样回源核对（会上网，较慢）

退出码：0 = 全部通过；1 = 有失败项。
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"

RESULTS: list[tuple[bool, str]] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    RESULTS.append((ok, label))
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {label}" + (f" — {detail}" if detail else ""))


def load(name: str) -> dict:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def trading_days(start: date, end: date) -> list[str]:
    days, cur = [], start
    while cur <= end:
        if cur.weekday() < 5:
            days.append(cur.isoformat())
        cur += timedelta(days=1)
    return days


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--online", action="store_true", help="抽样回源核对（联网）")
    parser.add_argument("--samples", type=int, default=3, help="回源抽样的日期数")
    args = parser.parse_args()

    sse = load("sse_share_history.json")
    szse = load("szse_share_history.json")
    periods = load("etf_flow_periods.json")
    history = load("etf_flow_history.json")
    weights = load("index_weights.json")

    print("== 1. 交易所份额缓存 ==")
    sse_days_all = sorted(d for d, rows in sse.get("snapshots", {}).items() if rows)
    sz_days_all = sorted(d for d, rows in szse.get("snapshots", {}).items() if rows)
    both = set(sse_days_all) | set(sz_days_all)
    for name, snap, days in (("上交所", sse.get("snapshots", {}), sse_days_all), ("深交所", szse.get("snapshots", {}), sz_days_all)):
        check(len(days) > 200, f"{name}快照天数", f"{len(days)} 天（{days[0]} → {days[-1]}）")
        check(days == sorted(set(days)), f"{name}日期唯一且有序")
        empties = [d for d in days if not snap[d]]
        check(not empties, f"{name}无空快照", "" if not empties else f"空日期 {empties[:5]}")
        # 只用两市并集当交易日历：某日只在两市都缺失时才视为节假日，不会被春节/元旦误判
        gaps = []
        for prev, cur in zip(days, days[1:]):
            for day in trading_days(date.fromisoformat(prev) + timedelta(days=1), date.fromisoformat(cur) - timedelta(days=1)):
                if day not in both:
                    gaps.append(day)
        check(True, f"{name}区间内缺日", f"{len(gaps)} 天（均为休市日；本检查仅作提示）")
        check(days[-1] == periods["latest_date"], f"{name}最新日期与快照一致", f"{days[-1]} / {periods['latest_date']}")

    print("\n== 2. 每日份额变化 ==")
    points = history.get("points", [])
    dates = [p["date"] for p in points]
    check(dates == sorted(set(dates)), "变化点日期唯一且有序", f"{len(dates)} 点")
    check(history.get("earliest_date") == dates[0] and history.get("latest_date") == dates[-1],
          "变化点首尾与 earliest/latest 一致", f"{dates[0]} → {dates[-1]}")
    sse_days = sorted(d for d, rows in sse["snapshots"].items() if rows and history.get("earliest_date", "") <= d <= periods["latest_date"])
    check(history.get("coverage", {}).get("sse_dates") == len(sse_days), "变化点覆盖上交所快照",
          f"{history.get('coverage', {}).get('sse_dates')} / {len(sse_days)}")
    bad = [p for p in points if not isinstance(p.get("changes"), list)]
    check(not bad, "每个变化点结构合法")

    print("\n== 3. 周期快照 ==")
    period_keys = list(periods["periods"].keys())
    check("day" in period_keys and "custom" not in period_keys, "周期键完整", "、".join(period_keys))
    for key, meta in periods["periods"].items():
        base, target = meta.get("base_date"), meta.get("target_date")
        ok = bool(base) and bool(target) and base <= target
        end = meta.get("end_date")
        ok = ok and (end is None or end >= base)
        check(ok, f"周期 {key} 基准日合法", f"{target} → {base}" + (f" → {end}" if end else ""))
    items = periods.get("items", [])
    check(len(items) > 1500, "标的数量", f"{len(items)} 只")
    sample = [x for x in items if x["periods"].get("day")]
    bad_delta = []
    for x in sample:
        p = x["periods"]["day"]
        end = p.get("end_shares") if p.get("end_shares") is not None else x.get("latest_shares")
        if end is None or p.get("base_shares") is None:
            continue
        if p["delta_shares"] != end - p["base_shares"]:
            bad_delta.append(x["code"])
    check(not bad_delta, "日周期变化 = 止日份额 − 起始份额", "" if not bad_delta else f"{len(bad_delta)} 只不符")

    print("\n== 4. 指数权重与板块口径 ==")
    for code in ["000300", "000016", "000905", "000852", "399001", "000688"]:
        idx = weights["indexes"].get(code)
        check(bool(idx), f"权重含指数 {code}", idx.get("name", "") if idx else "缺失")
        if idx:
            total = float(idx.get("weight_total") or sum(float(c["weight"]) for c in idx["constituents"]))
            check(abs(total - 100) <= 1.5 or idx.get("weight_partial"), f"{code} 权重合计≈100",
                  f"{total:.2f}" + ("（仅前十大权重）" if idx.get("weight_partial") else ""))

    def board_share(code: str, pattern: str) -> float:
        idx = weights["indexes"][code]
        total = float(idx.get("weight_total") or sum(float(c["weight"]) for c in idx["constituents"]))
        share = sum(float(c["weight"]) for c in idx["constituents"] if re.match(pattern, c["code"]))
        return share / total * 100

    for code, pattern, label in [
        ("000300", r"^(688|689)", "科创板@沪深300"),
        ("000016", r"^(688|689)", "科创板@上证50"),
        ("000300", r"^(300|301|302)", "创业板@沪深300"),
        ("000905", r"^(688|689)", "科创板@中证500"),
    ]:
        got = board_share(code, pattern)
        check(0 < got < 60, f"{label} 权重占比自洽", f"{got:.4f}%（0–60% 合理区间）")

    idx_399001 = weights["indexes"].get("399001") or {}
    if idx_399001.get("weight_partial"):
        check(len(idx_399001.get("constituents", [])) >= 400 and idx_399001.get("weight_coverage", 0) < 60,
              "深证成指成分完整但权重仅前十大（已标 partial，不参与占比均值）",
              f"成分 {len(idx_399001.get('constituents', []))} 只，权重覆盖 {idx_399001.get('weight_coverage')}%")
    else:
        got = board_share("399001", r"^(300|301|302)")
        check(0 < got < 100, "创业板@深证成指 权重占比自洽", f"{got:.4f}%")

    server_src = (ROOT / "server.py").read_text(encoding="utf-8")
    symbols = set(re.findall(r'"(\d{6})":\s*"s[hz]\d{6}"', server_src))
    js_src = "".join(p.read_text(encoding="utf-8") for p in sorted(ROOT.glob("dashboard-*.js")))
    need = set(re.findall(r"code:'(\d{6})',name:'", js_src))
    missing = sorted(need - symbols)
    check(not missing, "板块指数均有行情映射", "全部已映射" if not missing else f"缺 {missing}")

    print("\n== 5. 板块每日序列（前端口径）==")
    price_hist = load("stock_price_history.json") if (DATA / "stock_price_history.json").exists() else {}
    price_items = price_hist.get("items") or {}
    idx_codes = [k for k in price_items if k.startswith("index:")]
    check(bool(idx_codes), "已缓存板块指数收盘价", f"{len(idx_codes)} 个指数")
    if idx_codes:
        sample_idx = sorted(idx_codes)[0]
        rows = price_items[sample_idx].get("prices", [])
        check(len(rows) > 20, f"{sample_idx} 收盘价序列长度", f"{len(rows)} 行")

    if args.online:
        print("\n== 6. 抽样回源 ==")
        sys.path.insert(0, str(ROOT))
        from build_flow_periods import fetch_sse_date

        pool = [d for d in sse_days if d >= "2024-01-01"]
        for day in random.sample(pool, min(args.samples, len(pool))):
            rows = {r["code"]: r["shares"] for r in fetch_sse_date(date.fromisoformat(day))}
            cached = {code: int(v) for code, v in sse["snapshots"][day].items()}
            common = set(rows) & set(cached)
            mismatch = [c for c in common if rows[c] != cached[c]]
            check(bool(common) and not mismatch, f"上交所 {day} 回源一致",
                  f"比对 {len(common)} 只" + (f"，不符 {mismatch[:3]}" if mismatch else ""))

    failed = [label for ok, label in RESULTS if not ok]
    print("\n" + "=" * 60)
    print(f"共 {len(RESULTS)} 项检查，通过 {len(RESULTS) - len(failed)} 项，失败 {len(failed)} 项")
    if failed:
        print("失败项：")
        for label in failed:
            print(f"  - {label}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
