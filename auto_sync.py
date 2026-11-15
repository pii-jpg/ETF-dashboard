#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""挂着等网络恢复，一旦可用就自动补齐板块数据。

适用场景：本机 IP 被目标站点临时封禁，不想一直手动重试。
脚本每 10 分钟探测一次，通则依次运行 sync_data.py 与 build_weekly.py，跑完退出。

用法：
    双击运行，或 python auto_sync.py
    保持窗口开着即可，可以去做别的事
"""

from __future__ import annotations

import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROBE_URL = (
    "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
    "?lmt=0&klt=101&secid=90.BK0475&fields1=f1,f2,f3&fields2=f51,f52"
)
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
INTERVAL_SECONDS = 600
MAX_ROUNDS = 144  # 24 小时


def reachable() -> bool:
    try:
        request = urllib.request.Request(PROBE_URL, headers=HEADERS)
        with urllib.request.urlopen(request, timeout=8) as response:
            return response.status == 200
    except Exception:  # noqa: BLE001 - 任何失败都按不可达处理
        return False


def run(script: str) -> int:
    print(f"[auto] 运行 {script} ...", flush=True)
    result = subprocess.run([sys.executable, script], cwd=str(ROOT), check=False)
    print(f"[auto] {script} 退出码 {result.returncode}", flush=True)
    return result.returncode


def main() -> int:
    for round_index in range(1, MAX_ROUNDS + 1):
        if reachable():
            print(f"[auto] 第 {round_index} 轮探测：目标站点可达，开始补齐", flush=True)
            if run("sync_data.py") != 0:
                print("[auto] 同步失败，稍后重试", flush=True)
                time.sleep(INTERVAL_SECONDS)
                continue
            run("build_weekly.py")
            print("[auto] 补齐完成，刷新看板即可看到全量数据", flush=True)
            return 0

        if round_index == 1 or round_index % 6 == 0:
            waited = round_index * INTERVAL_SECONDS // 60
            print(f"[auto] 第 {round_index} 轮：仍不可达（已等待约 {waited} 分钟）", flush=True)
        time.sleep(INTERVAL_SECONDS)

    print("[auto] 等待 24 小时后仍未恢复，退出。可换网络后直接双击 启动看板.bat", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
