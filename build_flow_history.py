"""Build cached daily ETF share changes for trend and daily dashboard charts."""

from __future__ import annotations

import concurrent.futures
import datetime as dt
import json
import threading
from pathlib import Path

from build_flow_periods import fetch_sse_date


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
FLOW_FILE = DATA / "etf_flow_periods.json"
SSE_CACHE = DATA / "sse_share_history.json"
SZ_CACHE = DATA / "szse_share_history.json"
OUT = DATA / "etf_flow_history.json"
WRITE_LOCK = threading.Lock()
HISTORY_FLOOR = dt.date(2024, 1, 1)


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, value) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


def main() -> None:
    flow = read_json(FLOW_FILE, {})
    if not flow.get("latest_date"):
        raise RuntimeError("请先运行 build_flow_periods.py")
    latest = dt.date.fromisoformat(flow["latest_date"])
    base_dates = [dt.date.fromisoformat(v["base_date"]) for v in flow.get("periods", {}).values() if v.get("base_date")]
    # 历史时间线起点固定为 2024-01-01（自选区间可回溯到这里），不随周期增减而变化
    earliest = min(min(base_dates or [latest - dt.timedelta(days=370)]) - dt.timedelta(days=7), HISTORY_FLOOR - dt.timedelta(days=7))

    cache = read_json(SSE_CACHE, {"snapshots": {}})
    snapshots = cache.setdefault("snapshots", {})
    weekdays = []
    day = earliest
    while day <= latest:
        if day.weekday() < 5:
            weekdays.append(day)
        day += dt.timedelta(days=1)
    missing = [day for day in weekdays if day.isoformat() not in snapshots]

    completed = 0
    def fetch_one(day: dt.date):
        rows = fetch_sse_date(day)
        return day.isoformat(), {row["code"]: row["shares"] for row in rows}

    if missing:
        print(f"正在补充上交所日频份额：{len(missing)} 个工作日")
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            futures = {pool.submit(fetch_one, day): day for day in missing}
            for future in concurrent.futures.as_completed(futures):
                date_text, rows = future.result()
                with WRITE_LOCK:
                    snapshots[date_text] = rows
                    completed += 1
                    if completed % 12 == 0:
                        cache["updated_at"] = dt.datetime.now().astimezone().isoformat(timespec="seconds")
                        write_json(SSE_CACHE, cache)
                if completed % 24 == 0 or completed == len(missing):
                    print(f"已完成 {completed}/{len(missing)}")
        cache["updated_at"] = dt.datetime.now().astimezone().isoformat(timespec="seconds")
        write_json(SSE_CACHE, cache)

    sse_dates = sorted(date for date, rows in snapshots.items() if rows and earliest.isoformat() <= date <= latest.isoformat())
    changes_by_date: dict[str, list[list]] = {date: [] for date in sse_dates}
    for previous_date, current_date in zip(sse_dates, sse_dates[1:]):
        previous, current = snapshots[previous_date], snapshots[current_date]
        changes_by_date[current_date].extend([[code, shares - previous[code]] for code, shares in current.items() if code in previous and shares != previous[code]])

    sz = read_json(SZ_CACHE, {"snapshots": {}}).get("snapshots", {})
    sz_dates = sorted(date for date, rows in sz.items() if rows and earliest.isoformat() <= date <= latest.isoformat())
    for previous_date, current_date in zip(sz_dates, sz_dates[1:]):
        previous, current = sz[previous_date], sz[current_date]
        point = changes_by_date.setdefault(current_date, [])
        for code, row in current.items():
            if code not in previous:
                continue
            delta = row["shares"] - previous[code]["shares"]
            if delta:
                point.append([code, delta])

    points = [{"date": date, "changes": changes_by_date[date]} for date in sorted(changes_by_date)]
    payload = {
        "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "latest_date": latest.isoformat(),
        "earliest_date": points[0]["date"] if points else None,
        "points": points,
        "coverage": {"sse_dates": len(sse_dates), "sz_dates": len(sz_dates)},
        "method": "每日份额变化=当日份额-上一可用交易日份额；趋势=所选周期内每日变化累计。金额按网页当前盘中价格动态估算。",
    }
    write_json(OUT, payload)
    print(json.dumps({"points": len(points), "coverage": payload["coverage"], "output": str(OUT)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
