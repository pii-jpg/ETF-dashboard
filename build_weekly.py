#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把日频资金流聚合为自然周，输出去重后的 weekly.json。

聚合口径：
    周净额   = 周内各交易日主力净额之和（净额可加）
    周涨跌幅 = 周内各交易日涨跌幅累乘
    周天数   = 该周实际有数据的交易日数（停牌与节假日不计入，不补零）

去重口径：全序列（每一天的净额与涨跌幅）完全一致的板块视为同一指数，
保留名称最短的作为主名，其余记入 alias。东财把一级、二级、三级行业平铺在
同一列表里，"银行"与"银行Ⅱ"就属于这种情况。
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
SEED_FILE = DATA_DIR / "blocks_seed.json"
BLOCKS_FILE = DATA_DIR / "blocks.json"
DAILY_FILE = DATA_DIR / "daily_flows.jsonl"
WEEKLY_FILE = DATA_DIR / "weekly.json"

# 板块名称规则：只保留申万一级与申万二级行业，三级细分不上看板。
# 东财板块名称没有统一层级后缀，只能按申万官方名单做白名单匹配。
LEVEL1_NAMES = {
    "农林牧渔", "基础化工", "钢铁", "有色金属", "电子", "家用电器", "食品饮料",
    "纺织服饰", "轻工制造", "医药生物", "公用事业", "交通运输", "房地产", "商贸零售",
    "社会服务", "综合", "建筑材料", "建筑装饰", "电力设备", "国防军工", "计算机",
    "传媒", "通信", "银行", "非银金融", "汽车", "机械设备", "煤炭", "石油石化",
    "环保", "美容护理",
}
LEVEL2_NAMES = {
    "种植业", "渔业", "养殖业", "饲料", "农产品加工", "农业综合Ⅱ", "林业Ⅱ", "动物保健Ⅱ",
    "化学原料", "化学制品", "化学纤维", "塑料", "橡胶", "农化制品", "非金属材料Ⅱ",
    "普钢", "特钢Ⅱ", "冶钢原料",
    "工业金属", "贵金属", "小金属", "金属新材料", "能源金属",
    "半导体", "元件", "光学光电子", "消费电子", "电子化学品Ⅱ", "其他电子Ⅱ",
    "白色家电", "黑色家电", "小家电", "厨卫电器", "家电零部件Ⅱ", "其他家电Ⅱ",
    "白酒Ⅱ", "非白酒", "饮料乳品", "休闲食品", "食品加工", "调味发酵品Ⅱ",
    "纺织制造", "服装家纺", "饰品",
    "造纸", "包装印刷", "家居用品", "文娱用品",
    "化学制药", "中药Ⅱ", "生物制品", "医药商业", "医疗器械", "医疗服务",
    "电力", "燃气Ⅱ",
    "物流", "铁路公路", "航空机场", "航运港口",
    "房地产开发", "房地产服务",
    "一般零售", "专业连锁Ⅱ", "互联网电商", "贸易Ⅱ",
    "体育Ⅱ", "酒店餐饮", "旅游及景区", "专业服务", "教育",
    "综合Ⅱ",
    "水泥", "玻璃玻纤", "装修建材",
    "房屋建设Ⅱ", "装修装饰Ⅱ", "基础建设", "专业工程", "工程咨询服务Ⅱ",
    "电机Ⅱ", "电网设备", "风电设备", "光伏设备", "电池", "其他电源设备Ⅱ",
    "航天装备Ⅱ", "航空装备Ⅱ", "航海装备Ⅱ", "地面兵装Ⅱ", "军工电子Ⅱ",
    "计算机设备", "软件开发", "IT服务Ⅱ",
    "游戏Ⅱ", "广告营销", "影视院线", "数字媒体", "出版", "电视广播Ⅱ",
    "通信设备", "通信服务",
    "银行",
    "证券Ⅱ", "保险Ⅱ", "多元金融",
    "乘用车", "商用车", "汽车零部件", "汽车服务", "摩托车及其他",
    "通用设备", "专用设备", "工程机械", "自动化设备", "轨交设备Ⅱ",
    "煤炭开采", "焦炭Ⅱ",
    "油气开采Ⅱ", "油服工程", "炼化及贸易",
    "环境治理", "环保设备Ⅱ",
    "个护用品", "化妆品", "医疗美容",
}
LEVEL12_NAMES = LEVEL1_NAMES | LEVEL2_NAMES

# 申万二级 → 一级 归属。看板按此展示每个板块所属的一级行业。
LEVEL2_PARENT: dict[str, str] = {}
for _parent, _children in {
    "农林牧渔": ["种植业", "渔业", "养殖业", "饲料", "农产品加工", "农业综合Ⅱ", "林业Ⅱ", "动物保健Ⅱ"],
    "基础化工": ["化学原料", "化学制品", "化学纤维", "塑料", "橡胶", "农化制品", "非金属材料Ⅱ"],
    "钢铁": ["普钢", "特钢Ⅱ", "冶钢原料"],
    "有色金属": ["工业金属", "贵金属", "小金属", "金属新材料", "能源金属"],
    "电子": ["半导体", "元件", "光学光电子", "消费电子", "电子化学品Ⅱ", "其他电子Ⅱ"],
    "家用电器": ["白色家电", "黑色家电", "小家电", "厨卫电器", "家电零部件Ⅱ", "其他家电Ⅱ"],
    "食品饮料": ["白酒Ⅱ", "非白酒", "饮料乳品", "休闲食品", "食品加工", "调味发酵品Ⅱ"],
    "纺织服饰": ["纺织制造", "服装家纺", "饰品"],
    "轻工制造": ["造纸", "包装印刷", "家居用品", "文娱用品"],
    "医药生物": ["化学制药", "中药Ⅱ", "生物制品", "医药商业", "医疗器械", "医疗服务"],
    "公用事业": ["电力", "燃气Ⅱ"],
    "交通运输": ["物流", "铁路公路", "航空机场", "航运港口"],
    "房地产": ["房地产开发", "房地产服务"],
    "商贸零售": ["一般零售", "专业连锁Ⅱ", "互联网电商", "贸易Ⅱ"],
    "社会服务": ["体育Ⅱ", "酒店餐饮", "旅游及景区", "专业服务", "教育"],
    "综合": ["综合Ⅱ"],
    "建筑材料": ["水泥", "玻璃玻纤", "装修建材"],
    "建筑装饰": ["房屋建设Ⅱ", "装修装饰Ⅱ", "基础建设", "专业工程", "工程咨询服务Ⅱ"],
    "电力设备": ["电机Ⅱ", "电网设备", "风电设备", "光伏设备", "电池", "其他电源设备Ⅱ"],
    "国防军工": ["航天装备Ⅱ", "航空装备Ⅱ", "航海装备Ⅱ", "地面兵装Ⅱ", "军工电子Ⅱ"],
    "计算机": ["计算机设备", "软件开发", "IT服务Ⅱ"],
    "传媒": ["游戏Ⅱ", "广告营销", "影视院线", "数字媒体", "出版", "电视广播Ⅱ"],
    "通信": ["通信设备", "通信服务"],
    "银行": ["银行"],
    "非银金融": ["证券Ⅱ", "保险Ⅱ", "多元金融"],
    "汽车": ["乘用车", "商用车", "汽车零部件", "汽车服务", "摩托车及其他"],
    "机械设备": ["通用设备", "专用设备", "工程机械", "自动化设备", "轨交设备Ⅱ"],
    "煤炭": ["煤炭开采", "焦炭Ⅱ"],
    "石油石化": ["油气开采Ⅱ", "油服工程", "炼化及贸易"],
    "环保": ["环境治理", "环保设备Ⅱ"],
    "美容护理": ["个护用品", "化妆品", "医疗美容"],
}.items():
    for _child in _children:
        LEVEL2_PARENT[_child] = _parent


def level_info(name: str) -> tuple[int, str]:
    """返回 (层级, 所属一级行业)。一级行业的所属行业为空。"""
    if name in LEVEL1_NAMES:
        return 1, ""
    return 2, LEVEL2_PARENT.get(name, "")


def iso_week(day: str) -> str:
    year, week, _ = date.fromisoformat(day).isocalendar()
    return f"{year}-W{week:02d}"


def load_daily() -> list[dict]:
    if not DAILY_FILE.exists():
        return []
    rows: list[dict] = []
    with DAILY_FILE.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("date") and obj.get("rows"):
                rows.append(obj)
    return rows


def load_blocks() -> dict[str, str]:
    if not BLOCKS_FILE.exists():
        return {}
    return json.loads(BLOCKS_FILE.read_text(encoding="utf-8"))


def load_seed() -> set[str]:
    """行业板块白名单。为空时不作过滤。"""
    if not SEED_FILE.exists():
        return set()
    payload = json.loads(SEED_FILE.read_text(encoding="utf-8"))
    return set(payload.get("codes") or [])


def aggregate_week(cell_net: float, cell_change: float, acc: dict) -> None:
    acc["net"] += cell_net
    acc["gross"] *= 1.0 + cell_change / 100.0
    if cell_net > 0:
        acc["up"] += 1
    acc["days"] += 1


def build_block_rows(
    blocks: dict[str, str],
    daily: list[dict],
    week_index: dict[str, int],
) -> list[dict]:
    rows: list[dict] = []
    for code, name in blocks.items():
        buckets: dict[str, dict] = {}
        for day in daily:
            cell = day["rows"].get(code)
            if not cell:
                continue
            week = iso_week(day["date"])
            acc = buckets.setdefault(week, {"net": 0.0, "gross": 1.0, "up": 0, "days": 0})
            aggregate_week(cell[0], cell[1], acc)

        if not buckets:
            continue

        series: list[list | None] = [None] * len(week_index)
        for week, acc in buckets.items():
            series[week_index[week]] = [
                round(acc["net"], 2),
                round((acc["gross"] - 1.0) * 100.0, 2),
                acc["up"],
                acc["days"],
            ]
        level, parent = level_info(name)
        rows.append({"c": code, "n": name, "t": series, "l": level, "p": parent})
    return rows


def dedupe(rows: list[dict]) -> list[dict]:
    """全序列完全一致的板块合并为一条，保留名称最短者。"""
    groups: dict[tuple, list[dict]] = {}
    for row in rows:
        fingerprint = tuple(tuple(cell) if cell else None for cell in row["t"])
        groups.setdefault(fingerprint, []).append(row)

    result: list[dict] = []
    for group in groups.values():
        group.sort(key=lambda item: (len(item["n"]), item["n"]))
        primary = group[0]
        if len(group) > 1:
            primary["a"] = [item["n"] for item in group[1:]]
        result.append(primary)
    return result


def main() -> int:
    blocks = load_blocks()
    seed = load_seed()
    if seed:
        # 只输出行业板块：日频文件里可能残留早期枚举扫到的概念板块
        blocks = {code: name for code, name in blocks.items() if code in seed}
    # 板块名称规则：三级细分不进看板
    blocks = {code: name for code, name in blocks.items() if name in LEVEL12_NAMES}
    daily = load_daily()
    if not blocks:
        print("[weekly] data/blocks.json 为空，先运行 sync_data.py")
        return 1
    if not daily:
        print("[weekly] data/daily_flows.jsonl 为空，先运行 sync_data.py")
        return 1

    dates = sorted(day["date"] for day in daily)
    week_meta: dict[str, dict] = {}
    week_order: list[str] = []
    for day in dates:
        week = iso_week(day)
        if week not in week_meta:
            week_meta[week] = {"k": week, "s": day, "e": day, "n": 0}
            week_order.append(week)
        week_meta[week]["e"] = day
        week_meta[week]["n"] += 1

    week_index = {week: index for index, week in enumerate(week_order)}
    rows = build_block_rows(blocks, daily, week_index)
    raw_count = len(rows)
    rows = dedupe(rows)
    rows.sort(key=lambda item: item["c"])

    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "span": {"start": dates[0], "end": dates[-1], "days": len(dates)},
        "weeks": [week_meta[week] for week in week_order],
        "blocks": rows,
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    WEEKLY_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

    aliases = sum(len(row.get("a") or []) for row in rows)
    print(
        f"[weekly] weeks={len(week_order)} blocks={raw_count} "
        f"deduped={len(rows)} aliases={aliases} "
        f"span={dates[0]}~{dates[-1]} size={WEEKLY_FILE.stat().st_size // 1024}KB"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
