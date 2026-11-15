#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""列出尚未同步的板块清单。

用东财搜索接口（searchapi，不受行情接口封禁影响）按代码反查名称，
对比种子清单与已落盘板块，输出缺口。
"""

from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
SEED_FILE = DATA / "blocks_seed.json"
BLOCKS_FILE = DATA / "blocks.json"

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
TOKEN = "D43BF722C8E33BDC906FB84D85E326E8"


def lookup(code: str) -> str | None:
    url = (
        "https://searchapi.eastmoney.com/api/suggest/get"
        f"?input={code}&type=14&count=5&token={TOKEN}"
    )
    request = urllib.request.Request(url, headers=HEADERS)
    raw = urllib.request.urlopen(request, timeout=10).read().decode("utf-8", "replace")
    payload = json.loads(raw)
    rows = (payload.get("QuotationCodeTable") or {}).get("Data") or []
    for row in rows:
        if row.get("Code") == code and row.get("Classify") == "BK":
            return row.get("Name")
    return None


def main() -> int:
    seed = json.loads(SEED_FILE.read_text(encoding="utf-8"))["codes"]
    have = set(json.loads(BLOCKS_FILE.read_text(encoding="utf-8")).keys())
    missing = [code for code in seed if code not in have]

    print(f"[list] 种子 {len(seed)}，已有 {len(have)}，缺 {len(missing)}")
    names: dict[str, str] = {}
    failed: list[str] = []

    for index, code in enumerate(missing, start=1):
        try:
            name = lookup(code)
        except Exception:  # noqa: BLE001 - 单个失败不影响整体
            name = None
        if name:
            names[code] = name
        else:
            failed.append(code)
        if index % 80 == 0:
            print(f"[list] {index}/{len(missing)} ok={len(names)} fail={len(failed)}", flush=True)
        time.sleep(0.05)

    level_3 = [name for name in names.values() if name.endswith("Ⅲ")]
    level_2 = [name for name in names.values() if name.endswith("Ⅱ")]
    plain = [name for name in names.values() if not name.endswith(("Ⅱ", "Ⅲ"))]

    print(f"\n[list] 查到 {len(names)} 个，失败 {len(failed)} 个")
    print(f"[list] 带Ⅲ后缀 {len(level_3)} · 带Ⅱ后缀 {len(level_2)} · 无后缀 {len(plain)}")

    print("\n=== 无后缀 ===")
    print("、".join(plain))
    print("\n=== 带Ⅱ后缀 ===")
    print("、".join(level_2))
    print("\n=== 带Ⅲ后缀 ===")
    print("、".join(level_3))

    if failed:
        print(f"\n[list] 未查到：{', '.join(failed[:20])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
