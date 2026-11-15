"""一键重建看板数据。

流程（顺序固定，后一步依赖前一步的产物）：
  1. build_flow_periods.py  生成周期基准快照（etf_flow_periods.json），并按需补齐深交所份额历史
  2. build_flow_history.py  生成每日份额变化（etf_flow_history.json），按需补齐上交所份额历史
  3. build_index_weights.py 生成重点指数成分权重（index_weights.json）

用法：
  python rebuild.py                # 全量重建
  python rebuild.py --only periods # 只跑某一步（periods / history / weights）
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STEPS = [
    ("live", "", "实时行情快照（供指数候选排序使用）"),
    ("periods", "build_flow_periods.py", "周期基准快照 + 深交所份额历史"),
    ("history", "build_flow_history.py", "每日份额变化 + 上交所份额历史"),
    ("weights", "build_index_weights.py", "重点指数成分权重"),
]


def run(script: str) -> None:
    started = time.time()
    if not script:
        # live 步：直接构建实时行情快照，供 build_index_weights 的指数重要性排序使用
        import server
        server.build_live_payload(force=True)
        print(f"----- 实时行情快照完成，用时 {time.time() - started:.1f}s", flush=True)
        return
    print(f"\n===== {script} =====", flush=True)
    result = subprocess.run([sys.executable, str(ROOT / script)], cwd=ROOT)
    elapsed = time.time() - started
    if result.returncode != 0:
        raise SystemExit(f"{script} 失败（exit {result.returncode}），已中止后续步骤")
    print(f"----- {script} 完成，用时 {elapsed:.1f}s", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="重建 etf-dashboard 数据")
    parser.add_argument("--only", choices=[key for key, _, _ in STEPS], help="只运行指定步骤")
    args = parser.parse_args()

    started = time.time()
    for key, script, desc in STEPS:
        if args.only and args.only != key:
            continue
        print(f"[{key}] {desc}")
        run(script)

    print(f"\n全部完成，总用时 {time.time() - started:.1f}s")
    print("下一步：python verify_data.py 复查数据，或双击 启动实时看板.bat 打开看板")


if __name__ == "__main__":
    main()
