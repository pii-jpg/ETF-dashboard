#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同步东方财富行业板块日频资金流数据。

板块清单来自 data/blocks_seed.json —— 东方财富行业板块（fs=m:90+t:2）的全量快照，
属于准静态字典数据。名称在拉取时由 daykline 返回补全。

为什么清单随项目保存、而不是每次枚举：
    本机到 push2（板块列表接口所在域）的 TLS 连接会被服务端在重新协商阶段直接断开，
    curl 与 Python urllib 均复现；只有 push2his 的 daykline 接口稳定可用。
    而枚举 BK0001..BK1800 会把概念板块一并扫进来，无法区分行业与概念。

用法：
    python sync_data.py               按种子清单拉取并合并新交易日
    python sync_data.py --workers 3   调整并发（默认 3）
    python sync_data.py --scan        枚举 BK0001..BK1800 发现新增板块（低频、慢）

落盘 data/daily_flows.jsonl，一行一个交易日：
    {"date":"2026-11-13","rows":{"BK0475":[1225672704,1.43]}}
    rows[代码] = [主力净流入(元), 当日涨跌幅(%)]

合并规则：只补缺失的日期与板块，不覆盖本地已有值。接口只保留最近约 120 个
交易日，本地长期积累的序列不能被这个窗口侵蚀。
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
SEED_FILE = DATA_DIR / "blocks_seed.json"
BLOCKS_FILE = DATA_DIR / "blocks.json"
DAILY_FILE = DATA_DIR / "daily_flows.jsonl"

DAYKLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "*/*",
}

SCAN_CODE_MAX = 1800
RETRIES = 2
REQUEST_TIMEOUT = 6
# 服务端按频率限流：超过阈值会临时拒绝连接。实测 1800 个请求并发 8 会触发，
# 且封禁可持续十余小时。这里按每分钟 60 个的节奏走，宁可慢也不触发。
BATCH_SIZE = 100
BATCH_PAUSE = 60.0
# 连续这么多个请求都失败，判定站点不可达，立即中止（被封时每个请求要重试 4 次，不等整批跑完）
ABORT_AFTER = 3


def block_code(number: int) -> str:
    return f"BK{number:04d}"


def fetch_json(url: str) -> dict:
    """走系统 curl 取数。

    Python 的 OpenSSL TLS 栈会被服务端直接断开（RemoteDisconnected），而 Windows 自带
    的 curl 用 schannel，能正常拿到响应。实测同一 URL、同一时刻：curl 返回 200，
    urllib 反复 RemoteDisconnected。因此抓取统一走 curl 子进程。
    """
    last_error: Exception | None = None
    for attempt in range(RETRIES):
        try:
            result = subprocess.run(
                ["curl", "-s", "-m", str(REQUEST_TIMEOUT), url],
                capture_output=True,
                timeout=REQUEST_TIMEOUT + 5,
                check=False,
            )
            if result.returncode != 0:
                raise RuntimeError(f"curl 退出码 {result.returncode}")
            text = result.stdout.decode("utf-8", "replace").strip()
            if not text:
                raise RuntimeError("空响应")
            return json.loads(text)
        except Exception as exc:  # noqa: BLE001 - 网络抖动统一重试
            last_error = exc
            if attempt + 1 < RETRIES:
                time.sleep(1.2 * (attempt + 1))
    raise RuntimeError(f"请求失败：{last_error}")


def to_float(value) -> float | None:
    if value is None or value == "-" or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_block_series(code: str) -> tuple[str | None, dict[str, list]]:
    """取单个板块的名称与日频序列。无效代码返回 (None, {})。"""
    query = (
        f"lmt=0&klt=101&secid=90.{code}"
        "&fields1=f1,f2,f3,f7"
        "&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63"
    )
    payload = fetch_json(f"{DAYKLINE_URL}?{query}")
    data = payload.get("data")
    if not isinstance(data, dict):
        return None, {}
    name = data.get("name")
    if not name:
        return None, {}

    series: dict[str, list] = {}
    for line in data.get("klines") or []:
        parts = line.split(",")
        if len(parts) < 13:
            continue
        net = to_float(parts[1])
        change = to_float(parts[12])
        if net is None or change is None:
            continue
        series[parts[0]] = [net, change]
    return name, series


def load_seed_codes() -> list[str]:
    if not SEED_FILE.exists():
        return []
    payload = json.loads(SEED_FILE.read_text(encoding="utf-8"))
    return payload.get("codes") or []


def load_blocks() -> dict[str, str]:
    if not BLOCKS_FILE.exists():
        return {}
    try:
        return json.loads(BLOCKS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_blocks(blocks: dict[str, str]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(dict(sorted(blocks.items())), ensure_ascii=False, indent=1)
    BLOCKS_FILE.write_text(payload, encoding="utf-8")


def load_daily() -> dict[str, dict[str, list]]:
    days: dict[str, dict[str, list]] = {}
    if not DAILY_FILE.exists():
        return days
    with DAILY_FILE.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("date"):
                days[obj["date"]] = obj.get("rows") or {}
    return days


def save_daily(days: dict[str, dict[str, list]]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    lines = []
    for date in sorted(days):
        payload = json.dumps(
            {"date": date, "rows": days[date]},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        lines.append(payload)
    DAILY_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def merge_history(days: dict[str, dict[str, list]], code: str, series: dict[str, list]) -> int:
    """只补缺失单元，已有值不动。返回新增单元数。"""
    added = 0
    for date, values in series.items():
        bucket = days.setdefault(date, {})
        if code not in bucket:
            bucket[code] = values
            added += 1
    return added


def sync_codes(
    days: dict[str, dict[str, list]],
    codes: list[str],
    workers: int,
) -> tuple[dict[str, str], list[str]]:
    """分批并发拉取，返回 ({代码: 名称}, 失败列表)。批间休眠以避开服务端限流。"""
    found: dict[str, str] = {}
    failures: list[str] = []
    added = 0
    done = 0
    total = len(codes)
    batches = [codes[i:i + BATCH_SIZE] for i in range(0, total, BATCH_SIZE)]

    consecutive_failures = 0
    for index, batch in enumerate(batches, start=1):
        batch_failed = 0
        aborted = False
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(fetch_block_series, code): code for code in batch}
            for future in concurrent.futures.as_completed(futures):
                code = futures[future]
                done += 1
                try:
                    name, series = future.result()
                except Exception as exc:  # noqa: BLE001 - 单个板块失败不影响整体
                    failures.append(f"{code}:{exc}")
                    batch_failed += 1
                    consecutive_failures += 1
                    if consecutive_failures >= ABORT_AFTER:
                        aborted = True
                        break
                else:
                    consecutive_failures = 0
                    if name:
                        found[code] = name
                        added += merge_history(days, code, series)
        if aborted:
            print(
                f"[sync] 连续 {ABORT_AFTER} 个请求失败，判定目标站点不可达（限流或封禁），中止同步",
                flush=True,
            )
            break
        print(
            f"[sync] batch {index}/{len(batches)} done={done}/{total} "
            f"blocks={len(found)} added_cells={added} failed={len(failures)}",
            flush=True,
        )
        if batch_failed >= len(batch):
            print("[sync] 本批全部失败，中止同步", flush=True)
            break
        if index < len(batches):
            time.sleep(BATCH_PAUSE)

    return found, failures


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="同步行业板块日频资金流")
    parser.add_argument("--workers", type=int, default=1, help="并发数，默认 1（高速并发会触发限流）")
    parser.add_argument("--scan", action="store_true", help=f"枚举 BK0001..BK{SCAN_CODE_MAX:04d} 发现新板块")
    args = parser.parse_args(argv)

    seed = load_seed_codes()
    blocks = load_blocks()

    if args.scan:
        codes = [block_code(n) for n in range(1, SCAN_CODE_MAX + 1)]
        print(f"[sync] 扫描 {codes[0]}..{codes[-1]}，共 {len(codes)} 个候选（较慢）")
    else:
        if not seed:
            print("[sync] data/blocks_seed.json 缺失或为空，无法确定板块清单")
            return 1
        codes = list(dict.fromkeys(seed))
        print(f"[sync] 按种子清单拉取 {len(codes)} 个行业板块")

    days = load_daily()
    found, failures = sync_codes(days, codes, max(1, args.workers))

    if args.scan:
        seed_set = set(seed)
        merged = dict(blocks)
        merged.update(found)
        if seed_set:
            merged = {code: name for code, name in merged.items() if code in seed_set}
        blocks = merged
    else:
        blocks.update(found)

    save_blocks(blocks)
    save_daily(days)

    dates = sorted(days)
    span = f"{dates[0]} ~ {dates[-1]}" if dates else "无"
    print(f"[sync] 完成 blocks={len(blocks)} dates={len(dates)} span={span} failed={len(failures)}")
    for item in failures[:8]:
        print(f"[sync] failed {item}")
    if failures:
        print("[sync] 有失败项，重新运行本脚本会只补缺失的交易日")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
