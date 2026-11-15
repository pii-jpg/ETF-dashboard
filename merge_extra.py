#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 data/extra_*.json 的补数合并进 daily_flows.jsonl。

补数文件用于本机网络被目标站点封禁时的应急通道：数据从另一条网络出口取得，
落成 JSON 后再并回本地日频库。合并规则与 sync_data.py 一致：只补缺失单元，
不覆盖本地已有值。
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DAILY_FILE = DATA / "daily_flows.jsonl"
BLOCKS_FILE = DATA / "blocks.json"

# 补数板块的代码与名称（名称取自接口返回，接口不可达时也需登记才能进聚合）
BLOCK_NAMES = {
    "BK0427": "公用事业",
    "BK0433": "农林牧渔",
    "BK0436": "纺织服饰",
    "BK0437": "煤炭",
    "BK0438": "食品饮料",
    "BK0448": "通信设备",
    "BK0456": "家用电器",
    "BK0464": "石油石化",
    "BK0465": "化学制药",
    "BK0478": "有色金属",
    "BK0479": "钢铁",
    "BK0481": "汽车零部件",
    "BK0486": "传媒",
    "BK0728": "环保",
    "BK0735": "计算机设备",
    "BK0737": "软件开发",
    "BK1031": "光伏设备",
    "BK1033": "电池",
    "BK1035": "美容护理",
    "BK1036": "半导体",
    "BK1040": "中药Ⅱ",
    "BK1041": "医疗器械",
    "BK0428": "电力",
    "BK0450": "航运港口",
    "BK0451": "房地产开发",
    "BK0473": "证券Ⅱ",
    "BK0474": "保险Ⅱ",
    "BK0482": "一般零售",
    "BK1043": "专业服务",
    "BK0910": "专用设备",
    "BK0459": "元件",
    "BK1038": "光学光电子",
    "BK1034": "其他电源设备Ⅱ",
    "BK0731": "农化制品",
    "BK0538": "化学制品",
    "BK1019": "化学原料",
    "BK0471": "化学纤维",
    "BK0727": "医疗服务",
    "BK1042": "医药商业",
    "BK0454": "塑料",
    "BK0738": "多元金融",
    "BK0440": "家居用品",
    "BK1027": "小金属",
    "BK0726": "工程咨询服务Ⅱ",
    "BK0739": "工程机械",
    "BK1045": "房地产服务",
    "BK0740": "教育",
    "BK1018": "橡胶",
    "BK0424": "水泥",
    "BK1016": "汽车服务",
    "BK1037": "消费电子",
    "BK1046": "游戏Ⅱ",
    "BK1028": "燃气Ⅱ",
    "BK0422": "物流",
    "BK0546": "玻璃玻纤",
    "BK1044": "生物制品",
    "BK1039": "电子化学品Ⅱ",
    "BK1030": "电机Ⅱ",
    "BK0457": "电网设备",
    "BK0539": "综合Ⅱ",
    "BK1015": "能源金属",
    "BK0420": "航空机场",
    "BK0476": "装修建材",
    "BK0725": "装修装饰Ⅱ",
    "BK0732": "贵金属",
    "BK0484": "贸易Ⅱ",
    "BK0736": "通信服务",
    "BK0545": "通用设备",
    "BK0421": "铁路公路",
    "BK1020": "非金属材料Ⅱ",
    "BK1032": "风电设备",
    "BK0734": "饰品",
}


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
    lines = []
    for date in sorted(days):
        payload = json.dumps(
            {"date": date, "rows": days[date]},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        lines.append(payload)
    DAILY_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    paths = sorted(DATA.glob("extra_*.json"))
    if not paths:
        print("[merge] data/extra_*.json 为空，无事可做")
        return 1

    days = load_daily()
    added = 0
    codes: set[str] = set()

    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"[merge] {path.name} 解析失败：{exc}")
            return 1
        series = payload.get("series") or {}
        for code, entries in series.items():
            codes.add(code)
            for entry in entries:
                parts = entry.split(",")
                if len(parts) < 3:
                    continue
                date = parts[0]
                try:
                    net = float(parts[1])
                    change = float(parts[2])
                except ValueError:
                    continue
                bucket = days.setdefault(date, {})
                if code not in bucket:
                    bucket[code] = [net, change]
                    added += 1

    save_daily(days)

    blocks: dict[str, str] = {}
    if BLOCKS_FILE.exists():
        try:
            blocks = json.loads(BLOCKS_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            blocks = {}
    registered = 0
    for code in codes:
        name = BLOCK_NAMES.get(code)
        if name and blocks.get(code) != name:
            blocks[code] = name
            registered += 1
    BLOCKS_FILE.write_text(
        json.dumps(dict(sorted(blocks.items())), ensure_ascii=False, indent=1),
        encoding="utf-8",
    )

    print(
        f"[merge] files={len(paths)} blocks={len(codes)} added_cells={added} "
        f"registered={registered} dates={len(days)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
