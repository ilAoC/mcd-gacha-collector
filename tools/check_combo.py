#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查套餐评分分布与分档结果（读取最新 data.json）。"""
import io
import json
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(HERE, "data.json"), "r", encoding="utf-8") as f:
    d = json.load(f)

cards = d["cards"]
sc = [c for c in cards if not c.get("is_combo")]
cb = [c for c in cards if c.get("is_combo")]


def dist(arr):
    return {r: sum(1 for c in arr if c["rarity"] == r) for r in ("SSR", "UR", "R")}


print("meta.thresholds     :", d["meta"]["thresholds"])
print("meta.thresholdsCombo:", d["meta"].get("thresholdsCombo"))
print(f"单品 {len(sc)} 张  {dist(sc)}")
print(f"套餐 {len(cb)} 张  {dist(cb)}")
print(f"合计 {len(cards)} 张  {dist(cards)}")
print()
print("--- 套餐评分明细（看区分度） ---")
for c in sorted(cb, key=lambda x: -x["health_score"]):
    pd = c["protein"] / c["calories"] * 100
    sd = c["sodium"] / c["calories"] * 100
    print(f"  {c['rarity']:<4}{c['name']:<22} {c['price']:>6.1f}元 "
          f"{c['calories']:>6.0f}kcal  蛋白密度{pd:>4.1f}  钠密度{sd:>5.1f}  评分 {c['health_score']:>5.1f}")
print()
scores = [c["health_score"] for c in cb]
print(f"套餐评分区间: {min(scores):.1f} ~ {max(scores):.1f}  (跨度 {max(scores)-min(scores):.1f})")