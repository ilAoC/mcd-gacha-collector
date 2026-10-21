#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
套餐数据（MCP 实测）。

数据来源：
- 名称 / 价格 / 编码 / 图片：query-meals (storeCode=3230366, 2026-10-20)
- 默认搭配：query-meal-detail的 rounds[].choices[].isDefault == 1
- 营养：默认搭配各组件的 list-nutrition-foods 数据加总

注意：套餐热量为**默认搭配的基准值**，
实际点单时替换小食/饮料会改变热量（diffPrice 字段给出了差价）。
"""

# 单品营养基准（kcal, 蛋白g, 脂肪g, 碳水g, 钠mg），取自 list-nutrition-foods
NUTRI = {
    "巨无霸":           (513, 27, 26, 42, 961),
    "板烧鸡腿堡":       (391, 23, 17, 35, 1041),
    "麦辣鸡腿汉堡":     (485, 24, 24, 42, 1208),
    "双层深海鳕鱼堡":   (485, 28, 21, 46, 917),
    "培根安格斯厚牛堡": (707, 34, 44, 43, 1037),
    "芝士安格斯厚牛堡": (696, 32, 44, 43, 897),
    "培根蔬萃双层牛堡": (442, 24, 23, 34, 728),
    "不素之霸双层牛堡": (493, 28, 27, 34, 1012),
    "双层吉士汉堡":     (429, 27, 22, 31, 1017),
    "吉士汉堡包":       (294, 16, 12, 30, 673),
    "麦香鸡":           (369, 15, 17, 39, 731),
    "麦香鱼":           (325, 16, 13, 35, 556),
    "麦辣鸡翅4块":      (224, 13, 15, 9, 537),
    "麦乐鸡":           (213, 12, 12, 13, 422),
    "中薯条":           (289, 4, 12, 38, 165),
    "可乐中杯":         (147, 0, 0, 36, 0),
    "麦麦脆汁鸡":       (173, 18, 9, 5, 547),
    "大薯条":           (379, 6, 16, 50, 216),
    "儿童鱼排堡":       (269, 15, 6, 36, 442),
    "三文鱼双虾至尊月堡": (478, 36, 17, 44, 1343),
}

# 套餐：(名称, 编码, 售价, 默认搭配组件列表, 图片URL)
COMBOS = [
    ("巨无霸三件套", "9900005466", 51.5, ["巨无霸", "中薯条", "可乐中杯"],
     "https://menu-img.mcd.cn/pcm/prod/menu/20260824/product/MS_9900005466_320.png"),
    ("麦辣鸡腿汉堡三件套", "9900005456", 47.0, ["麦辣鸡腿汉堡", "中薯条", "可乐中杯"],
     "https://menu-img.mcd.cn/pcm/prod/menu/20260824/product/MS_9900005456_320.png"),
    ("板烧鸡腿堡三件套", "9900005462", 50.0, ["板烧鸡腿堡", "中薯条", "可乐中杯"],
     "https://menu-img.mcd.cn/pcm/prod/menu/20260824/product/MS_9900005462_320.png"),
    ("双层深海鳕鱼堡三件套", "9900005413", 50.5, ["双层深海鳕鱼堡", "中薯条", "可乐中杯"],
     "https://menu-img.mcd.cn/pcm/prod/menu/20260824/product/MS_9900005413_320.png"),
    ("培根蔬萃双层牛堡三件套", "9900005468", 50.5, ["培根蔬萃双层牛堡", "中薯条", "可乐中杯"],
     "https://menu-img.mcd.cn/pcm/prod/menu/20260824/product/MS_9900005468_320.png"),
    ("不素之霸双层牛堡三件套", "9900005411", 52.0, ["不素之霸双层牛堡", "中薯条", "可乐中杯"],
     "https://menu-img.mcd.cn/pcm/prod/menu/20260824/product/MS_9900005411_320.png"),
    ("培根安格斯厚牛堡三件套", "9900005428", 62.5, ["培根安格斯厚牛堡", "中薯条", "可乐中杯"],
     "https://menu-img.mcd.cn/pcm/prod/menu/20260824/product/MS_9900005428_320.png"),
    ("芝士安格斯厚牛堡三件套", "9900005430", 59.5, ["芝士安格斯厚牛堡", "中薯条", "可乐中杯"],
     "https://menu-img.mcd.cn/pcm/prod/menu/20260824/product/MS_9900005430_320.png"),
    ("麦香鸡中套餐", "9900005453", 41.5, ["麦香鸡", "中薯条", "可乐中杯"],
     "https://menu-img.mcd.cn/pcm/prod/menu/20260824/product/MS_9900005453_320.png"),
    ("麦乐鸡套餐", "9900004835", 39.0, ["麦乐鸡", "中薯条", "可乐中杯"],
     "https://menu-img.mcd.cn/pcm/prod/menu/20260824/product/MS_9900004835_320.png"),
    ("麦辣鸡翅4块套餐", "9900005451", 52.0, ["麦辣鸡翅4块", "大薯条", "可乐中杯"],
     "https://menu-img.mcd.cn/pcm/prod/menu/20260824/product/MS_9900005451_320.png"),
    ("精选单人餐三件套", "9900004064", 50.0, ["板烧鸡腿堡", "中薯条", "可乐中杯"],
     "https://menu-img.mcd.cn/pcm/prod/menu/20260824/product/MS_9900004064_320.gif"),
    ("双层吉士汉堡套餐", "9900005464", 48.0, ["双层吉士汉堡", "中薯条", "可乐中杯"],
     "https://menu-img.mcd.cn/pcm/prod/menu/20260824/product/MS_9900005464_320.png"),
    ("吉士汉堡包套餐", "9900005449", 43.5, ["吉士汉堡包", "中薯条", "可乐中杯"],
     "https://menu-img.mcd.cn/pcm/prod/menu/20260824/product/MS_9900005449_320.png"),
    ("麦香鱼套餐", "9900005460", 48.5, ["麦香鱼", "中薯条", "可乐中杯"],
     "https://menu-img.mcd.cn/pcm/prod/menu/20260824/product/MS_9900005460_320.png"),
    ("龙焰鸡腿堡三件套", "9900016073", 50.5, ["板烧鸡腿堡", "中薯条", "可乐中杯"],
     "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_9900016073_320.png"),
    ("龙焰芝士棒鸡腿堡三件套", "9900016075", 53.5, ["板烧鸡腿堡", "中薯条", "可乐中杯"],
     "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_9900016075_320.png"),
    ("三文鱼双虾至尊月堡三件套", "9900015851", 57.5, ["三文鱼双虾至尊月堡", "中薯条", "可乐中杯"],
     "https://menu-img.mcd.cn/pcm/prod/menu/20260824/product/MS_9900015851_320.png"),
]


def build_combo_rows() -> list[dict]:
    """把套餐定义转换为 build_cards 需要的行结构，营养按默认搭配加总。"""
    rows = []
    for name, code, price, items, image in COMBOS:
        k = p = f = c = s = 0
        ok = True
        for it in items:
            if it not in NUTRI:
                ok = False
                break
            n = NUTRI[it]
            k += n[0]; p += n[1]; f += n[2]; c += n[3]; s += n[4]
        if not ok:
            continue
        rows.append({
            "name": name, "code": code, "price": price, "items": items,
            "image_url": image,
            "calories": float(k), "protein": float(p), "fat": float(f),
            "carbohydrate": float(c), "sodium": float(s),
        })
    return rows


if __name__ == "__main__":
    import json
    rows = build_combo_rows()
    print(f"{len(rows)} 个套餐")
    for r in rows:
        print(f"  {r['name']:<24} ¥{r['price']:<6} {r['calories']:.0f}kcal  "
              f"蛋白{r['protein']:.0f}g  {'+'.join(r['items'])}")