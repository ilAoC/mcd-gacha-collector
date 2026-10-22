#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成网页版卡池数据（web/data.json）。

与 Skill 使用**同一套算法**（gacha.py）：健康度评分 + 相对分位分级，
确保网页端与 Agent 端抽卡结果口径完全一致。

数据来源（均为麦当劳 MCP 实测）：
- 价格：query-meals  storeCode=3230366 麦当劳沈阳站出发层餐厅
- 营养：list-nutrition-foods 全量 160 项
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "skills", "mcd-gacha-collector", "scripts"))
from gacha import build_cards, compute_thresholds, pool_thresholds, RARITIES  # noqa: E402
from image_map import IMAGE_MAP  # noqa: E402
from combo_data import build_combo_rows  # noqa: E402

# ---- query-meals 实测价格（门店实时，元） ----
PRICES = {
    "巨无霸": 28.0, "板烧鸡腿堡": 26.0, "麦辣鸡腿汉堡": 25.5, "双层深海鳕鱼堡": 26.0,
    "培根安格斯厚牛堡": 38.0, "芝士安格斯厚牛堡": 35.0, "培根蔬萃双层牛堡": 26.0,
    "不素之霸双层牛堡": 27.5, "双层吉士汉堡": 25.5, "麦香鸡": 19.0, "麦香鱼": 24.5,
    "麦辣鸡翅-2块": 15.5, "薄皮焦香V翅": 16.5, "麦乐鸡5块": 15.5, "那么大鸡排": 15.0,
    "脆脆薯条": 16.5, "中薯条": 14.5, "脆薯饼": 15.5, "麦麦脆汁鸡-琵琶腿": 15.5,
    "圆筒冰淇淋": 5.0, "菠萝派": 9.5, "大杯玉米杯": 14.5, "苹果片": 7.5,
    "纯牛奶（盒装）": 12.0, "纯悦": 8.5, "燕麦奶": 25.0, "大杯鲜萃咖啡": 10.5,
    "锡兰红茶": 12.5, "阳光柠檬红茶中杯": 10.0, "可乐中杯": 10.0, "雪碧中杯": 10.0,
    "中杯怡泉+C": 13.0, "100%苹果汁": 12.5, "奥利奥麦旋风": 16.0, "朱古力新地": 14.0,
    "汉堡包": 15.0,
}

# ---- list-nutrition-foods 实测营养（kcal, 蛋白g, 脂肪g, 碳水g, 钠mg, 钙mg） ----
NUT = {
    "巨无霸": (513, 27, 26, 42, 961, 171), "板烧鸡腿堡": (391, 23, 17, 35, 1041, 93),
    "麦辣鸡腿汉堡": (485, 24, 24, 42, 1208, 154), "双层深海鳕鱼堡": (485, 28, 21, 46, 917, 147),
    "培根安格斯厚牛堡": (707, 34, 44, 43, 1037, 161), "芝士安格斯厚牛堡": (696, 32, 44, 43, 897, 150),
    "培根蔬萃双层牛堡": (442, 24, 23, 34, 728, 73), "不素之霸双层牛堡": (493, 28, 27, 34, 1012, 75),
    "双层吉士汉堡": (429, 27, 22, 31, 1017, 232), "麦香鸡": (369, 15, 17, 39, 731, 73),
    "麦香鱼": (325, 16, 13, 35, 556, 99), "麦辣鸡翅-2块": (224, 13, 15, 9, 537, 13),
    "薄皮焦香V翅": (192, 17, 11, 6, 594, 15), "麦乐鸡5块": (213, 12, 12, 13, 422, 9),
    "那么大鸡排": (385, 24, 21, 24, 996, 13), "脆脆薯条": (279, 4, 14, 32, 540, 13),
    "中薯条": (289, 4, 12, 38, 165, 18), "脆薯饼": (146, 1, 9, 14, 311, 7),
    "麦麦脆汁鸡-琵琶腿": (173, 18, 9, 5, 547, 15), "圆筒冰淇淋": (93, 2, 3, 14, 36, 77),
    "菠萝派": (221, 2, 11, 27, 147, 5), "大杯玉米杯": (87, 4, 1, 12, 2, 10),
    "苹果片": (32, 0, 0, 7, 0, 18), "纯牛奶（盒装）": (129, 7, 7, 10, 73, 231),
    "纯悦": (0, 0, 0, 0, 0, 0), "大杯鲜萃咖啡": (13, 1, 0, 0, 3, 8),
    "锡兰红茶": (2, 0, 0, 0, 0, 5), "阳光柠檬红茶中杯": (117, 0, 0, 29, 17, 0),
    "可乐中杯": (147, 0, 0, 36, 0, 10), "雪碧中杯": (105, 0, 0, 26, 29, 0),
    "中杯怡泉+C": (110, 0, 0, 27, 0, 0), "100%苹果汁": (88, 0, 0, 21, 0, 0),
    "奥利奥麦旋风": (266, 5, 9, 40, 116, 185), "朱古力新地": (282, 5, 9, 44, 126, 182),
    "汉堡包": (248, 13, 8, 29, 492, 61),
}

rows = [{"productName": n, "energyKcal": v[0], "protein": v[1], "fat": v[2],
         "carbohydrate": v[3], "sodium": v[4], "calcium": v[5], "energyKj": 0}
        for n, v in NUT.items()]

combos = build_combo_rows()
cards = build_cards(rows, PRICES, combos)
th = pool_thresholds(rows, combos)

# 注入 MCP 真实卡面图片与餐品编码
combo_by_name = {r["name"]: r for r in combos}
with_img = 0
for c in cards:
    if c.is_combo:
        src = combo_by_name.get(c.name, {})
        c.product_code = src.get("code", c.id)
        c.image_url = src.get("image_url", "")
    else:
        hit = IMAGE_MAP.get(c.name)
        if hit:
            c.product_code = hit[0]
            c.image_url = hit[1]
        else:
            c.product_code = c.id
            c.image_url = ""
    if c.image_url:
        with_img += 1

n_single = sum(1 for c in cards if not c.is_combo)
n_combo = sum(1 for c in cards if c.is_combo)

payload = {
    "meta": {
        "store": "麦当劳沈阳站出发层餐厅",
        "storeCode": "3230366",
        "address": "胜利南街2号沈阳站候车室夹层10号商铺",
        "sampledAt": "2026-10-20",
        # 稀有度规则：按价格档 + 品类划分，与健康度无关
        "rarityRule": "价格档 D（>45元）→SSR；C（30~45元）或 B 档汉堡（≥24元）→UR；其余→R",
        "rarityNote": "稀有度表示收集难度（贵重正餐更难抽到），与健康度评分相互独立",
        "weights": {"SSR": 5, "UR": 20, "R": 75},
        "recoverHours": 4,
        "initialPoints": 5,
        "costPerDraw": 1,
        "imageSource": "菜单餐品图片，来源 query-meals image 字段",
        "singleCount": n_single,
        "comboCount": n_combo,
        "comboNote": "套餐营养为默认搭配基准值，实际可替换小食/饮料",
    },
    "cards": [c.to_dict() for c in cards],
}

out = os.path.join(HERE, "data.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

dist = {r: sum(1 for c in cards if c.rarity == r) for r in RARITIES}
print(f"卡池{len(cards)} 张  {dist}  阈值{th}")
print(f"已生成 {out} ({os.path.getsize(out)} bytes)")