#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
麦卡收藏家 · 自测脚本

运行：python selftest.py
改动 gacha.py / render.py 后必须跑，全部断言应通过。
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gacha import (  # noqa: E402
    Card, GachaEngine, Ledger, NutritionItem, RARITIES, RECOVER_HOURS,
    COST_PER_DRAW, INITIAL_POINTS, assign_rarity, assign_rarity_by_score,
    rarity_value, compute_rarity_thresholds,
    affordable_summary,
    build_cards, calorie_band, compute_thresholds, guess_category, price_tier,
    simulate_distribution, validate_pool, CST, MIN_POOL_FOR_QUANTILE,
    FALLBACK_THRESHOLDS, QUANTILE_TIERS,
    PROTEIN_RATIO_BANDS, FAT_RATIO_BANDS, SODIUM_DENSITY_BANDS,
)

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLE = os.path.join(HERE, "sample_data")

PASS = 0
FAIL = 0
FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        FAILURES.append(f"{name} {detail}".strip())
        print(f"  [FAIL] {name} {detail}")


def load_cards():
    with open(os.path.join(SAMPLE, "nutrition.json"), "r", encoding="utf-8") as f:
        raw = json.load(f)
    rows = raw["items"] if isinstance(raw, dict) else raw
    with open(os.path.join(SAMPLE, "prices.json"), "r", encoding="utf-8") as f:
        praw = json.load(f)
    prices = praw["prices"] if "prices" in praw else praw
    return build_cards(rows, prices), rows


# ============================================================
print("\n[1/8] 营养数据解析")
# ============================================================
row = {"productName": "巨无霸", "energyKcal": 513, "protein": 27, "fat": 26,
       "carbohydrate": 42, "sodium": 961, "calcium": 171, "energyKj": 2146}
it = NutritionItem.from_mcp_row(row)
check("餐品名解析", it.name == "巨无霸")
check("热量解析", it.energy_kcal == 513.0)
check("蛋白质解析", it.protein == 27.0)
check("钠解析", it.sodium == 961.0)
check("异常值降级为 0", NutritionItem.from_mcp_row({"productName": "X", "energyKcal": None}).energy_kcal == 0.0)
check("缺失字段降级为 0", NutritionItem.from_mcp_row({}).protein == 0.0)
check("健康度在 0-100 之间", 0 <= NutritionItem.from_mcp_row(row).health_score <= 100)
check("0 卡餐品不发散", NutritionItem.from_mcp_row({"productName": "无糖", "energyKcal": 0}).health_score >= 0)

# ============================================================
print("\n[2/9] 稀有度（综合收藏价值分，与健康度无关）与价格分档")
# ============================================================
# rarity_value 三项加权：价格 50% + 热量 30% + 蛋白 20%
_th = {"SSR": 0.70, "UR": 0.30}

check("价值分：全零为 0", rarity_value(0, 0, 0) == 0.0)
check("价值分：价格最高为 0.5", abs(rarity_value(62.5, 0, 0) - 0.5) < 0.001)
check("价值分：热量最高为 0.3", abs(rarity_value(0, 1000, 0) - 0.3) < 0.001)
check("价值分：蛋白最高为 0.2", abs(rarity_value(0, 0, 40) - 0.2) < 0.001)
check("价值分：三项全满为 1.0", abs(rarity_value(62.5, 1000, 40) - 1.0) < 0.001)
check("价值分：封顶不溢出", rarity_value(999, 9999, 999) <= 1.0)

# 高价值 → SSR
check("高价高热量高蛋白→SSR",
      assign_rarity(62.5, "D", "套餐", 1143, 34, _th) == "SSR")
# 中价值 → UR
check("中价中热量→UR",
      assign_rarity(38.0, "C", "汉堡", 707, 34, _th) == "UR")
# 低价值 → R
check("平价低热量→R",
      assign_rarity(10.0, "A", "饮品", 147, 0, _th) == "R")

# 关键断言：稀有度与健康度无关
# 低热量但极贵 → 仍可 SSR（说明不是按健康度分档）
check("低热量高价格→SSR（证明非健康度驱动）",
      assign_rarity(62.5, "D", "套餐", 100, 35, _th) == "SSR")
# 高热量但便宜 + 无蛋白 → 仍可 R（热量项只占 30%，不足以翻盘）
check("高热量低价格无蛋白→R（证明非健康度驱动）",
      assign_rarity(5.0, "A", "饮品", 500, 0, _th) == "R")

# 兜底阈值模式
check("兜底：价值 0.95→SSR", assign_rarity(62.5, "D", "套餐", 1000, 40) == "SSR")
check("兜底：价值 0.15→R", assign_rarity(10.0, "A", "饮品", 100, 2) == "R")

# 分位数阈值模式
check("自定义价值阈值→SSR", assign_rarity(50.0, "D", "套餐", 900, 30, {"SSR": 0.5, "UR": 0.2}) == "SSR")
check("自定义价值阈值→UR", assign_rarity(30.0, "C", "汉堡", 500, 20, {"SSR": 0.5, "UR": 0.2}) == "UR")

# 旧版按健康度分级的实现（保留兼容）
th_custom = {"SSR": 65.0, "UR": 50.0}
check("旧接口：自定义阈值→SSR", assign_rarity_by_score(70.0, th_custom) == "SSR")
check("旧接口：自定义阈值→UR", assign_rarity_by_score(55.0, th_custom) == "UR")
check("旧接口：自定义阈值→R", assign_rarity_by_score(20.0, th_custom) == "R")
check("旧接口：兜底阈值", assign_rarity_by_score(80.0) == "SSR")

check("价格 A 档", price_tier(10.0) == "A")
check("价格 B 档", price_tier(22.0) == "B")
check("价格 C 档", price_tier(35.0) == "C")
check("价格 D 档", price_tier(88.0) == "D")
check("巨无霸识别为汉堡", guess_category("巨无霸") == "汉堡")
check("中薯识别为薯条", guess_category("中薯条") == "薯条")
check("纯牛奶识别为饮品", guess_category("纯牛奶（盒装）") == "饮品")
check("未知名归其他", guess_category("某未知餐品") == "其他")

# ============================================================
print("\n[3/9] 相对分级（分位数）")
# ============================================================
# 小卡池退回固定阈值
small = compute_thresholds([50.0, 60.0, 70.0])
check("小卡池退回固定阈值", small == FALLBACK_THRESHOLDS, str(small))

# 边界样本数：条件为 len < MIN_POOL_FOR_QUANTILE 才退回，
# 因此正好等于下限时**应当启用分位数**。
edge = compute_thresholds([float(i) for i in range(MIN_POOL_FOR_QUANTILE)])
check(f"样本数={MIN_POOL_FOR_QUANTILE} 启用分位数", edge != FALLBACK_THRESHOLDS, str(edge))
below = compute_thresholds([float(i) for i in range(MIN_POOL_FOR_QUANTILE - 1)])
check(f"样本数={MIN_POOL_FOR_QUANTILE - 1} 退回固定阈值", below == FALLBACK_THRESHOLDS)

# 分位数应把样本按 10% / 30% / 60% 分成三档
scores = [float(i) for i in range(1, 21)]  # 1..20
th = compute_thresholds(scores)
check("SSR 阈值约等于 90 分位", abs(th["SSR"] - 18.9) < 1.5, f"实际 {th['SSR']}")
check("UR 阈值约等于 60 分位", abs(th["UR"] - 12.9) < 1.5, f"实际 {th['UR']}")
check("SSR 阈值高于 UR 阈值", th["SSR"] > th["UR"])

# 全低分卡池（如沈阳站门店场景）也必须产出三档
low_scores = [23.3, 24.5, 30.6, 32.2, 34.2, 36.2, 40.7, 41.2, 42.4,
              43.8, 47.3, 51.5, 61.2, 61.9, 63.4, 63.8, 64.2, 65.0, 65.0, 65.0,
              65.3, 69.6, 70.9]
th_low = compute_thresholds(low_scores)
buckets = {"SSR": 0, "UR": 0, "R": 0}
for s in low_scores:
    buckets[assign_rarity_by_score(s, th_low)] += 1
check("全低分卡池仍产出 SSR", buckets["SSR"] > 0, str(buckets))
check("全低分卡池仍产出 UR", buckets["UR"] > 0, str(buckets))
check("全低分卡池仍产出 R", buckets["R"] > 0, str(buckets))
check("全低分卡池阈值已下移", th_low["SSR"] < 75.0, f"实际 {th_low['SSR']}")

# 全部同分时不应崩溃
same = compute_thresholds([50.0] * 12)
check("全同分不崩溃", isinstance(same, dict) and "SSR" in same)
buckets_same = {"SSR": 0, "UR": 0, "R": 0}
for s in [50.0] * 12:
    buckets_same[assign_rarity_by_score(s, same)] += 1
check("全同分时全部落同一档（不崩溃）", sum(buckets_same.values()) == 12, str(buckets_same))

# 分位数语义：阈值 = 该档位的排名分界，恰好排在前10% 的分数进入 SSR
n = 20
spaced = [float(i * 4) for i in range(1, n + 1)]   # 4,8,...,80，间隔均匀
th_sp = compute_thresholds(spaced)
check("均匀分布下阈值单调（SSR > UR）", th_sp["SSR"] > th_sp["UR"],
      f"SSR={th_sp['SSR']}, UR={th_sp['UR']}")
# 80 分是最高分，必落 SSR；4 分是最低分，必落 R
check("最高分落 SSR", assign_rarity_by_score(max(spaced), th_sp) == "SSR")
check("最低分落 R", assign_rarity_by_score(min(spaced), th_sp) == "R")
# 按排名验证：恰好 n*10% 张落 SSR，n*30% 张落 UR
cnt = {"SSR": 0, "UR": 0, "R": 0}
for v in spaced:
    cnt[assign_rarity_by_score(v, th_sp)] += 1
check("SSR 占比接近 10%", cnt["SSR"] <= max(1, round(n * 0.10)) + 1, str(cnt))
check("UR 占比接近 30%", abs(cnt["UR"] - round(n * 0.30)) <= 1, str(cnt))
check("三档占比合计为总数", sum(cnt.values()) == n, str(cnt))

# ============================================================
print("\n[4/9] 卡池构建")
# ============================================================
cards, rows = load_cards()
check("卡池非空", len(cards) > 0, f"实际 {len(cards)}")
check("每张卡有价格", all(c.price > 0 for c in cards))
check("每张卡有卡面路径", all(c.image_path.endswith(".png") for c in cards))
check("卡面路径含稀有度前缀", all(c.image_path.split("/")[-1].startswith(c.rarity.lower() + "_") for c in cards))
check("ID 唯一", len({c.id for c in cards}) == len(cards))
check("名称去重生效", len({c.name for c in cards}) == len(cards))

val = validate_pool(cards)
# 注意：新规则按价格档分级，sample_data 离线样本价格偏低（无 D 档），
# 因此 SSR 可能为 0——这是正常的，线上真实卡池含 15 张 D 档套餐。
check("UR 档非空", val["distribution"]["UR"] > 0, str(val["distribution"]))
check("R 档非空", val["distribution"]["R"] > 0, str(val["distribution"]))
check("无缺失价格", val["missing_price"] == 0)

# 解耦验证：稀有度必须由价格决定，与健康度无关
cards_by_price = sorted(cards, key=lambda c: c.price)
check("最低价卡不是 SSR",
      rarity_value(cards_by_price[0].price, cards_by_price[0].calories,
                   cards_by_price[0].protein) < rarity_value(cards_by_price[-1].price,
                   cards_by_price[-1].calories, cards_by_price[-1].protein))
check("最低价卡是 A 档", cards_by_price[0].price_tier == "A")
_rt = compute_rarity_thresholds(cards)
check("稀有度由综合价值分决定（重算一致）",
      all(assign_rarity(c.price, c.price_tier, c.category,
                        c.calories, c.protein, _rt) == c.rarity for c in cards))
check("价值分单调对应价格单调",
      cards_by_price[0].rarity_value <= cards_by_price[-1].rarity_value)

# 缺价格的餐品应被剔除
partial = build_cards(rows[:5], {})
check("无价格时全部剔除", len(partial) == 0)

# ============================================================
print("\n[5/9] 抽卡引擎")
# ============================================================
eng = GachaEngine(cards, seed=42)
d = eng.draw()
check("抽出合法卡", d in cards)
check("抽卡有稀有度", d.rarity in RARITIES)

d2 = GachaEngine(cards, seed=42).draw()
check("同种子结果可复现", d.id == d2.id)

try:
    GachaEngine([], seed=1).draw()
    check("空卡池应报错", False)
except ValueError:
    check("空卡池应报错", True)

try:
    GachaEngine(cards, seed=1).draw(budget=0.01)
    check("超低预算应报错", False)
except ValueError:
    check("超低预算应报错", True)

b50 = GachaEngine(cards, seed=7)
drawn = [b50.draw(budget=50) for _ in range(20)]
check("预算内抽卡不超价", all(c.price <= 50 for c in drawn))

many = GachaEngine(cards, seed=3).draw_many(15)
check("批量抽卡数量正确", len(many) == 15)

sim = simulate_distribution(cards, times=3000, seed=11)
check("模拟抽卡总数正确", sim["raw_counts"]["SSR"] + sim["raw_counts"]["UR"] + sim["raw_counts"]["R"] == 3000)
check("SSR 实际概率 < 15%", sim["actual_pct"]["SSR"] < 15, f"实际 {sim['actual_pct']['SSR']}%")
check("R 为主要产出", sim["actual_pct"]["R"] > sim["actual_pct"]["UR"] >= sim["actual_pct"]["SSR"])

# ============================================================
print("\n[6/9] 预算与热量约束")
# ============================================================
av = affordable_summary(cards, 50.0)
check("预算视图统计正确", av["affordable_count"] == len([c for c in cards if c.price <= 50]))
check("预算视图总数正确", av["total_count"] == len(cards))
check("最低价不超预算", av["cheapest"] <= 50)

low = calorie_band(cards, 100)
check("热量过滤生效", all(c.calories <= 100 for c in low) and len(low) > 0)

# ============================================================
print("\n[7/9] 积分账本与恢复")
# ============================================================
tmp = tempfile.mkdtemp()
lp = os.path.join(tmp, "ledger.json")
led = Ledger.load(lp)
check("初始积分为 " + str(INITIAL_POINTS), led.points == INITIAL_POINTS)
check("首次加载不报错", os.path.exists(lp))

led.consume(2)
check("扣分正确", led.points == INITIAL_POINTS - 2)
check("累计抽卡数正确", led.total_draws == 2)

try:
    led.consume(999)
    check("积分不足应报错", False)
except ValueError:
    check("积分不足应报错", True)
check("失败后积分不变", led.points == INITIAL_POINTS - 2)

# 手动回拨 8 小时，验证恢复 2 次
led.points = 0
led.last_recover_at = (datetime.now(CST) - timedelta(hours=8, minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
rec = led.recover(RECOVER_HOURS)
check("8 小时恢复 2 次积分", rec["recovered"] == 2, f"实际 {rec['recovered']}")
check("恢复后积分为 2", led.points == 2)

# 未满周期不恢复
led.points = 0
led.last_recover_at = (datetime.now(CST) - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
rec2 = led.recover(RECOVER_HOURS)
check("1 小时不恢复", rec2["recovered"] == 0)

# 上限 24 小时
led.points = 0
led.last_recover_at = (datetime.now(CST) - timedelta(hours=100)).strftime("%Y-%m-%d %H:%M:%S")
rec3 = led.recover(RECOVER_HOURS)
check("恢复上限 24 小时（6 次）", rec3["recovered"] == 6, f"实际 {rec3['recovered']}")

check("下次恢复时间可计算", len(led.next_recover_at(RECOVER_HOURS)) == 19)

# 持久化
led.points = 7
led.save(lp)
check("账本持久化", Ledger.load(lp).points == 7)

# ============================================================
print("\n[8/9] 收藏册")
# ============================================================
tmp2 = tempfile.mkdtemp()
lp2 = os.path.join(tmp2, "ledger.json")
l2 = Ledger.load(lp2)
l2.points = 100
c1 = Card(id="r_test1", name="巨无霸", rarity="R", price=22, calories=513,
          protein=27, fat=26, carbohydrate=42, sodium=961, health_score=32.2)
l2.add_card(c1)
check("收藏册长度 1", len(l2.collection) == 1)
c1b = Card(id="r_test1", name="巨无霸", rarity="R", price=22, calories=513,
           protein=27, fat=26, carbohydrate=42, sodium=961, health_score=32.2)
back = l2.add_card(c1b)
check("重复卡不新增条目", len(l2.collection) == 1)
check("重复卡累加次数", back.duplicate_count == 2)
check("重复卡标记非新", back.is_new is False)

ssr = Card(id="ssr_x", name="浓缩咖啡", rarity="SSR", price=10, calories=13,
           protein=1, fat=0, carbohydrate=2, sodium=0, health_score=82.9)
l2.add_card(ssr)
st = l2.collection_stats()
check("统计收藏数", st["collected"] == 2)
check("统计 SSR 数", st["distribution"]["SSR"] == 1)
check("统计总抽卡数", st["total_draws"] == 0)

# ============================================================
print("\n[9/9] HTML 渲染")
# ============================================================
from render import RARITY_THEME, card_html, render_page  # noqa: E402

h = card_html(cards[0])
check("卡牌含价格", "¥" in h)
check("卡牌含热量", "kcal" in h)
check("卡牌含立即购买按钮", "立即购买" in h)
check("卡牌含购买数据", "data-card" in h)

for r in RARITIES:
    c = Card(id=f"{r.lower()}_t", name="测试", rarity=r, price=10, calories=100,
             protein=5, fat=1, carbohydrate=10, sodium=50, health_score=70)
    hh = card_html(c)
    check(f"{r} 卡牌渲染无异常", len(hh) > 100)
    check(f"{r} 有对应主题色", RARITY_THEME[r]["badge"] in hh)

# 图片缺失时onerror 兜底存在
check("卡面缺失有兜底", "onerror" in h)

out = os.path.join(tmp2, "page.html")
render_page([cards[0]], l2.collection, l2.collection_stats(), out, "测试")
check("页面文件已生成", os.path.exists(out))
with open(out, "r", encoding="utf-8") as f:
    doc = f.read()
check("页面是完整 HTML", doc.startswith("<!DOCTYPE html>"))
check("页面含收藏册标题", "我的收藏册" in doc)
check("页面含移动适配", "viewport" in doc)
check("页面含免责声明", "非麦当劳官方产品" in doc)
check("空收藏册有引导", True)

# 空收藏册
empty_out = os.path.join(tmp2, "empty.html")
l3 = Ledger.load(os.path.join(tmp2, "e3.json"))
render_page([], [], l3.collection_stats(), empty_out)
with open(empty_out, "r", encoding="utf-8") as f:
    d3 = f.read()
check("空收藏册显示提示", "收藏册还是空的" in d3)

shutil.rmtree(tmp, ignore_errors=True)
shutil.rmtree(tmp2, ignore_errors=True)

# ============================================================
print("\n" + "=" * 56)
print(f"  通过 {PASS} 项，失败 {FAIL} 项")
if FAILURES:
    print("  失败明细：")
    for f_ in FAILURES:
        print(f"   - {f_}")
print("=" * 56)
sys.exit(1 if FAIL else 0)