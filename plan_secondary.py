#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""规划待补的申万二级行业。

东财板块列表没有层级字段，命名后缀（Ⅱ/Ⅲ）也不完全可靠，
因此用「申万二级行业标准名单」做白名单匹配，把缺口算准。

产物：data/secondary_plan.json —— 待补板块的代码与名称
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
NAME_MAP_FILE = DATA / "name_map.json"
PLAN_FILE = DATA / "secondary_plan.json"

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
TOKEN = "D43BF722C8E33BDC906FB84D85E326E8"

# 申万 2021 版二级行业（124 个），按一级行业分组
SECONDARY = [
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
]


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
    blocks = json.loads(BLOCKS_FILE.read_text(encoding="utf-8"))
    have_codes = set(blocks)
    have_names = set(blocks.values())
    missing = [code for code in seed if code not in have_codes]

    name_map: dict[str, str] = {}
    if NAME_MAP_FILE.exists():
        name_map = json.loads(NAME_MAP_FILE.read_text(encoding="utf-8"))

    for index, code in enumerate(missing, start=1):
        if code in name_map:
            continue
        try:
            name = lookup(code)
        except Exception:  # noqa: BLE001
            name = None
        if name:
            name_map[code] = name
        if index % 80 == 0:
            print(f"[plan] 查询 {index}/{len(missing)}", flush=True)
        time.sleep(0.05)

    NAME_MAP_FILE.write_text(
        json.dumps(name_map, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    wanted = set(SECONDARY) - have_names
    plan = [
        {"code": code, "name": name}
        for code, name in name_map.items()
        if name in wanted and code not in have_codes
    ]
    plan.sort(key=lambda item: item["name"])

    PLAN_FILE.write_text(
        json.dumps(
            {"count": len(plan), "blocks": plan},
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )

    print(f"[plan] 种子 {len(seed)}，已有 {len(have_codes)}，缺 {len(missing)}")
    print(f"[plan] 二级行业共 {len(SECONDARY)} 个，已有 {len(set(SECONDARY) & have_names)} 个")
    print(f"[plan] 待补二级行业 {len(plan)} 个，已写入 {PLAN_FILE.name}")
    print("[plan] " + "、".join(item["name"] for item in plan))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
