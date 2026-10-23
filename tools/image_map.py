#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
卡面图片映射：MCP query-meals 返回的 image 字段。

数据来源：query-meals 多店实测（3230366 沈阳站 / 3230486 和平湾 / 3230221 国际软件园）
           beType=1, orderType=1, 2026-10-20~23
键为营养数据中的餐品名，值为 MCP 返回的图片 URL 与餐品编码。
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))

#餐品名 -> (餐品编码, MCP 返回的 image URL)
IMAGE_MAP = {
    "巨无霸":            ("1100",     "https://menu-img.mcd.cn/pcm/prod/menu/20260309/product/MS_1100_320.png"),
    "板烧鸡腿堡":("1406",     "https://menu-img.mcd.cn/pcm/prod/menu/20241008/product/MS_1406_320.png"),
    "麦辣鸡腿汉堡":      ("1440",     "https://menu-img.mcd.cn/pcm/prod/menu/20260325/product/MS_1440_320.png"),
    "双层深海鳕鱼堡":    ("9900003586", "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_9900003586_320.png"),
    "培根安格斯厚牛堡":  ("511781",   "https://menu-img.mcd.cn/pcm/prod/menu/20260309/product/MS_511781_320.png"),
    "芝士安格斯厚牛堡":  ("511782",   "https://menu-img.mcd.cn/pcm/prod/menu/20260309/product/MS_511782_320.png"),
    "培根蔬萃双层牛堡":  ("1106",     "https://menu-img.mcd.cn/pcm/prod/menu/20260309/product/MS_1106_320.png"),
    "不素之霸双层牛堡":  ("4648",     "https://menu-img.mcd.cn/pcm/prod/menu/20260309/product/MS_4648_320.png"),
    "双层吉士汉堡":      ("1120",     "https://menu-img.mcd.cn/pcm/prod/menu/20260309/product/MS_1120_320.png"),
    "麦香鸡":            ("1450",     "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_1450_320.png"),
    "麦香鱼":            ("1600",     "https://menu-img.mcd.cn/pcm/prod/menu/20260101/product/MS_1600_320.png"),
    "麦辣鸡翅-2块":("1700",     "https://menu-img.mcd.cn/pcm/prod/menu/20260325/product/MS_G1700_320.png"),
    "薄皮焦香V翅":       ("520445",   "https://menu-img.mcd.cn/pcm/prod/menu/20241202/product/MS_520445_320.png"),
    "麦乐鸡5块":         ("1401",     "https://menu-img.mcd.cn/pcm/prod/menu/20260529/product/MS_G1401_320.png"),
    "那么大鸡排":        ("521156",   "https://menu-img.mcd.cn/pcm/prod/menu/20260101/product/MS_521156_320.png"),
    "脆脆薯条":          ("514782",   "https://menu-img.mcd.cn/pcm/prod/menu/20250523/product/MS_514782_320_1747877523158.png"),
    "中薯条":            ("4810",     "https://menu-img.mcd.cn/pcm/prod/menu/20250523/product/MS_G4810_320_1747877491921.png"),
    "脆薯饼":            ("9900016082", "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_9900016082_320.png"),
    "麦麦脆汁鸡-琵琶腿": ("9900005432", "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_9900005432_320.png"),
    "圆筒冰淇淋":        ("515837",   "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_515837_320.png"),
    "菠萝派":            ("9900008752", "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_G9900008752_320.gif"),
    "大杯玉米杯":        ("4437",     "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_G4437_320.png"),
    "苹果片":            ("6102",     "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_6102_320.png"),
    "纯牛奶（盒装）":("3755",     "https://menu-img.mcd.cn/pcm/prod/menu/20240731/product/MS_3755_320.png"),
    "纯悦":              ("3757",     "https://menu-img.mcd.cn/pcm/prod/menu/20240904/product/MS_3757_320.png"),
    "燕麦奶":            ("510488",   "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_G510489_320.png"),
    "大杯鲜萃咖啡":      ("520689",   "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_G520688_320.gif"),
    "锡兰红茶":          ("3505",     "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_3505_320.png"),
    "阳光柠檬红茶中杯":  ("515280",   "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_G515280_320.png"),
    "可乐中杯":          ("9900008751", "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_9900008751_320.gif"),
    "雪碧中杯":          ("3010",     "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_G3010_320.png"),
    "中杯怡泉+C":        ("515520",   "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_G515520_320.png"),
    "100%苹果汁":        ("6362",     "https://menu-img.mcd.cn/pcm/prod/menu/20250430/product/MS_6362_320_1745552987716.png"),
    "奥利奥麦旋风":      ("9900013732", "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_9900013732_320.gif"),
    "朱古力新地":        ("9900008745", "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_9900008745_320.gif"),
    "汉堡包":            ("9900008747", "https://menu-img.mcd.cn/pcm/prod/menu/20260309/product/MS_9900008747_320.gif"),
"猪柳蛋麦满分": ("5022", "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_5022_320.png"),
    "猪柳麦满分": ("5024", "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_5024_320.png"),
    "火腿扒麦满分": ("1254", "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_1254_320.png"),
    "大脆鸡扒麦满分": ("5889", "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_5889_320.png"),
    "原味板烧鸡腿麦满分": ("6800", "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_6800_320.png"),
    "双层原味板烧鸡腿麦满分": ("4989", "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_4989_320.png"),
    "双层猪柳蛋麦满分": ("520830", "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_520830_320.png"),
    "吉士蛋麦满分": ("5888", "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_5888_320.png"),
    "猪柳炒双蛋堡": ("502773", "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_502773_320.png"),
    "原味板烧鸡腿炒双蛋堡": ("514700", "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_514700_320.png"),
    "火腿扒早安营养卷": ("513112", "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_513112_320.png"),
    "图林根香肠早安营养卷": ("513113", "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_513113_320.png"),
    "枫糖风味厚松饼猪柳堡": ("521990", "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_521990_320.png"),
    "枫糖风味厚松饼猪柳蛋堡": ("521989", "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_521989_320.png"),
    "芝芝火腿扒堡": ("521315", "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_521315_320.png"),
    "脆香油条": ("2631", "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_2631_320.png"),
    "德式图林根香肠": ("505235", "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_505235_320.png"),
    "冰牛奶中杯": ("510041", "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_510041_320.png"),
    "优品豆浆": ("1088", "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_1088_320.png"),
    "麦咖啡™美式": ("507411", "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_507411_320.png"),
    "麦咖啡™奶铁": ("507409", "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_507409_320.png"),
    "燕麦奶铁": ("510479", "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_510479_320.png"),
    "麦咖啡™热美式中杯": ("507368", "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_507368_320.png"),
    "麦咖啡™热奶铁中杯": ("507328", "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_507328_320.png"),
    "卡布奇诺": ("507387", "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_507387_320.png"),
    "浓浓黑巧（冰/热）": ("515946", "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_515946_320.png"),
    "浓浓燕麦黑巧（冰/热）": ("515955", "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_515955_320.png"),
    "【美汁源】“黄金橙橙”": ("2430", "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_2430_320.png"),
    "【美汁源】“多汁柠柠”": ("521817", "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_521817_320.png"),
    "经典麦旋风": ("9900013732", "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_9900013732_320.png"),
    "吉士汉堡包": ("9900005449", "https://menu-img.mcd.cn/pcm/prod/menu/20260824/product/MS_G504971_320.png"),
    "高达吉士双牛堡": ("521316", "https://menu-img.mcd.cn/pcm/prod/menu/20260309/product/MS_521316_320.png"),
    "浓缩咖啡": ("507389", "https://menu-img.mcd.cn/pcm/prod/menu/20250324/product/MS_507389_320.png"),
    "阳光橙麦炫酷": ("6352", "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_6352_320.png"),
    "龙焰鸡腿堡": ("521952", "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_521952_320.png"),
    "龙焰芝士棒鸡腿堡": ("521953", "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_521953_320.png"),
}

if __name__ == "__main__":
    out = os.path.join(HERE, "image_map.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({k: {"code": v[0], "image": v[1]} for k, v in IMAGE_MAP.items()},
                  f, ensure_ascii=False, indent=2)
    print(f"{len(IMAGE_MAP)} 条映射已写出 -> {out}")
    missing = [k for k, v in IMAGE_MAP.items() if not v[1]]
    if missing:
        print("缺图待补:", missing)