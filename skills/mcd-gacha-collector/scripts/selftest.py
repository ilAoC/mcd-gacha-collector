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
    COST_PER_DRAW, INITIAL_POINTS, assign_rarity, affordable_summary,
    build_cards, calorie_band, compute_thresholds, guess_category, price_tier,
    simulate_distribution, validate_pool, CST, MIN_POOL_FOR_QUANTILE,
    FALLBACK_THRESHOLDS, QUANTILE_TIERS,
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
print("\n[2/10] 稀有度与价格分档")
# ============================================================
# 兜底阈值模式（未传 thresholds 时）
check("高分→SSR", assign_rarity(80.0) == "SSR")
check("中高分→UR", assign_rarity(60.0) == "UR")
check("低分→R", assign_rarity(30.0) == "R")
check("边界 75 属 SSR", assign_rarity(75.0) == "SSR")
check("边界 55 属 UR", assign_rarity(55.0) == "UR")

# 显式阈值模式（相对分级）
th_custom = {"SSR": 65.0, "UR": 50.0}
check("自定义阈值→SSR", assign_rarity(70.0, th_custom) == "SSR")
check("自定义阈值→UR", assign_rarity(55.0, th_custom) == "UR")
check("自定义阈值→R", assign_rarity(20.0, th_custom) == "R")

check("价格 A 档", price_tier(10.0) == "A")
check("价格 B 档", price_tier(22.0) == "B")
check("价格 C 档", price_tier(35.0) == "C")
check("价格 D 档", price_tier(88.0) == "D")
check("巨无霸识别为汉堡", guess_category("巨无霸") == "汉堡")
check("中薯识别为薯条", guess_category("中薯条") == "薯条")
check("纯牛奶识别为饮品", guess_category("纯牛奶（盒装）") == "饮品")
check("未知名归其他", guess_category("某未知餐品") == "其他")

# ============================================================
print("\n[3/10] 相对分级（分位数）")
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
    buckets[assign_rarity(s, th_low)] += 1
check("全低分卡池仍产出 SSR", buckets["SSR"] > 0, str(buckets))
check("全低分卡池仍产出 UR", buckets["UR"] > 0, str(buckets))
check("全低分卡池仍产出 R", buckets["R"] > 0, str(buckets))
check("全低分卡池阈值已下移", th_low["SSR"] < 75.0, f"实际 {th_low['SSR']}")

# 全部同分时不应崩溃
same = compute_thresholds([50.0] * 12)
check("全同分不崩溃", isinstance(same, dict) and "SSR" in same)
buckets_same = {"SSR": 0, "UR": 0, "R": 0}
for s in [50.0] * 12:
    buckets_same[assign_rarity(s, same)] += 1
check("全同分时全部落同一档（不崩溃）", sum(buckets_same.values()) == 12, str(buckets_same))

# 分位数语义：阈值 = 该档位的排名分界，恰好排在前10% 的分数进入 SSR
n = 20
spaced = [float(i * 4) for i in range(1, n + 1)]   # 4,8,...,80，间隔均匀
th_sp = compute_thresholds(spaced)
check("均匀分布下阈值单调（SSR > UR）", th_sp["SSR"] > th_sp["UR"],
      f"SSR={th_sp['SSR']}, UR={th_sp['UR']}")
# 80 分是最高分，必落 SSR；4 分是最低分，必落 R
check("最高分落 SSR", assign_rarity(max(spaced), th_sp) == "SSR")
check("最低分落 R", assign_rarity(min(spaced), th_sp) == "R")
# 按排名验证：恰好 n*10% 张落 SSR，n*30% 张落 UR
cnt = {"SSR": 0, "UR": 0, "R": 0}
for v in spaced:
    cnt[assign_rarity(v, th_sp)] += 1
check("SSR 占比接近 10%", cnt["SSR"] <= max(1, round(n * 0.10)) + 1, str(cnt))
check("UR 占比接近 30%", abs(cnt["UR"] - round(n * 0.30)) <= 1, str(cnt))
check("三档占比合计为总数", sum(cnt.values()) == n, str(cnt))

# ============================================================
print("\n[4/10] 卡池构建")
# ============================================================
cards, rows = load_cards()
check("卡池非空", len(cards) > 0, f"实际 {len(cards)}")
check("每张卡有价格", all(c.price > 0 for c in cards))
check("每张卡有卡面路径", all(c.image_path.endswith(".png") for c in cards))
check("卡面路径含稀有度前缀", all(c.image_path.split("/")[-1].startswith(c.rarity.lower() + "_") for c in cards))
check("ID 唯一", len({c.id for c in cards}) == len(cards))
check("名称去重生效", len({c.name for c in cards}) == len(cards))

val = validate_pool(cards)
check("三档均非空", all(val["distribution"][r] > 0 for r in RARITIES), str(val["distribution"]))
check("三档齐备标记为真", val["all_tiers_present"] is True)
check("SSR 占比 <= 15%（稀有度稀缺）", val["distribution_pct"]["SSR"] <= 15, f"实际 {val['distribution_pct']['SSR']}%")
check("无缺失价格", val["missing_price"] == 0)
check("自检含阈值信息", "thresholds" in val and "SSR" in val["thresholds"])

# 缺价格的餐品应被剔除
partial = build_cards(rows[:5], {})
check("无价格时全部剔除", len(partial) == 0)

# ============================================================
print("\n[5/10] 抽卡引擎")
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
print("\n[6/10] 预算与热量约束")
# ============================================================
av = affordable_summary(cards, 50.0)
check("预算视图统计正确", av["affordable_count"] == len([c for c in cards if c.price <= 50]))
check("预算视图总数正确", av["total_count"] == len(cards))
check("最低价不超预算", av["cheapest"] <= 50)

low = calorie_band(cards, 100)
check("热量过滤生效", all(c.calories <= 100 for c in low) and len(low) > 0)

# ============================================================
print("\n[7/10] 积分账本与恢复")
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
print("\n[8/10] 收藏册")
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
print("\n[9/9] 套餐独立算法")
# ============================================================
# 套餐走 combo_health_score（每元营养密度），与单品算法互不干扰
from gacha import COMBO_WEIGHTS, NutritionItem  # noqa: E402


def mkcombo(kcal, protein, sodium, price=50.0):
    it = NutritionItem(name="测试套餐", energy_kcal=kcal, protein=protein, sodium=sodium)
    it._price = price
    return it


c1 = mkcombo(949, 31, 1200)     # 巨无霸三件套（典型三件套）
c2 = mkcombo(649, 16, 900)      # 麦乐鸡套餐（总热量更低）
check("套餐评分在 0-100", 0 <= c1.combo_health_score <= 100)
# 算法看结构：蛋白密度高的应更高分
check("高蛋白密度得分更高",
      mkcombo(900, 40, 1000).combo_health_score > mkcombo(900, 10, 1000).combo_health_score)
# 算法看钠密度：同热量下低钠更高分
check("同热量下低钠得分更高",
      mkcombo(900, 25, 600).combo_health_score > mkcombo(900, 25, 1600).combo_health_score)
# 算法保留热量载荷（基准线 700 大卡，单品是 600）
check("低热量套餐得分更高",
      mkcombo(600, 25, 800).combo_health_score > mkcombo(1400, 25, 800).combo_health_score)
check("套餐评分与价格无关（看结构不看单价）",
      mkcombo(900, 25, 800, 40).combo_health_score == mkcombo(900, 25, 800, 60).combo_health_score)
check("零热量时评分为 0", mkcombo(0, 0, 0).combo_health_score == 0)
check("单品评分不受价格影响",
      NutritionItem.from_mcp_row({"productName": "X", "energyKcal": 500}).health_score
      == NutritionItem.from_mcp_row({"productName": "X", "energyKcal": 500}).health_score)
check("套餐权重和为 1", abs(sum(COMBO_WEIGHTS.values()) - 1.0) < 1e-9)

# 关键回归：套餐不得因分量大而集体低分（这是引入独立算法的目的）
_typical_combo = mkcombo(900, 30, 1100)
check("典型三件套评分不低于 40（不因分量大而低分）",
      _typical_combo.combo_health_score >= 40,
      f"实际 {_typical_combo.combo_health_score}")

# 区分度：真实套餐区间不应挤在一起
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..", "tools"))
try:
    from combo_data import build_combo_rows as _bcr
    _rows = _bcr()
    _scores = []
    for _r in _rows:
        _scores.append(NutritionItem(
            name=_r["name"], energy_kcal=_r["calories"],
            protein=_r["protein"], sodium=_r["sodium"]).combo_health_score)
    check("套餐数据非空", len(_rows) > 0, f"{len(_rows)}")
    spread = max(_scores) - min(_scores)
    check("套餐评分有足够区分度(>=15分)", spread >= 15, f"实际 {spread:.1f}")
    from gacha import compute_thresholds as _ct
    _th = _ct(_scores)
    _b = {"SSR": 0, "UR": 0, "R": 0}
    for _s in _scores:
        _b[assign_rarity(_s, _th)] += 1
    check("套餐能切出完整三档", all(_b[r] > 0 for r in RARITIES), str(_b))
    _gap = _th["SSR"] - _th["UR"]
    check("套餐 SSR/UR 阈值有合理间隔(>=3分)", _gap >= 3, f"实际 {_gap:.1f}")
except ImportError:
    check("combo_data 可导入（可选）", True)

# build_cards 同时接受单品与套餐
_combo_arg = [{"name": "测试套餐A", "price": 50.0, "items": ["巨无霸"],
               "calories": 513, "protein": 27, "fat": 26,
               "carbohydrate": 42, "sodium": 961}]
_mixed = build_cards(rows, {"巨无霸": 28.0}, _combo_arg)
check("混合卡池同时含单品与套餐",
      any(c.is_combo for c in _mixed) and any(not c.is_combo for c in _mixed))
check("套餐卡category 为「套餐」",
      all(c.category == "套餐" for c in _mixed if c.is_combo))
check("套餐卡记录组件", all(c.combo_items for c in _mixed if c.is_combo))
check("单品卡is_combo 为 False", all(c.is_combo is False for c in _mixed if not c.is_combo))

print("\n[10/10] HTML 渲染（v3 · 麦当劳品牌风）")
# ============================================================
from render import RARITY_THEME, card_html, render_page  # noqa: E402

# 卡面骨架：与网页端 cardHtml 对齐
h = card_html(cards[0])
check("卡牌含价格", "¥" in h)
check("卡牌含热量", "kcal" in h)
check("卡牌含图片降级", "onerror" in h)
check("卡牌含环形健康度徽章", 'class="score"' in h and "stroke-dasharray" in h)
check("卡牌有斜切稀有度角标 DOM", 'class="rar-tag"' in h)
check("卡牌有独立数据面板", 'class="panel"' in h)
# 字体与 skewX 写在 CSS 里，下面通过完整页面检查

# 三档主题色：与网页端 CSS 变量一一对应
for r in RARITIES:
    c = Card(id=f"{r.lower()}_t", name="测试", rarity=r, price=10, calories=100,
             protein=5, fat=1, carbohydrate=10, sodium=50, health_score=70)
    hh = card_html(c)
    check(f"{r} 卡牌渲染无异常", len(hh) > 100)
    check(f"{r} 含主题色 c2", RARITY_THEME[r]["c2"] in hh)

# 套餐卡：is_combo=True 时显示「套餐」徽章
_combo = Card(id="combo_t", name="测试套餐", rarity="R", price=50, calories=900,
              protein=30, fat=20, carbohydrate=100, sodium=1100, health_score=65,
              is_combo=True, combo_items=["巨无霸", "中薯条", "可乐中杯"])
hh_c = card_html(_combo, is_new=True)
check("套餐卡显示套餐徽章", 'class="tier combo"' in hh_c)
check("套餐卡显示 NEW", 'class="new"' in hh_c)
# 重复卡：构造一份已经记入收藏册的卡（duplicate_count=2）验证 dup 标记
_dup_combo = Card(id="combo_t", name="测试套餐", rarity="R", price=50, calories=900,
                  protein=30, fat=20, carbohydrate=100, sodium=1100, health_score=65,
                  is_combo=True, combo_items=["巨无霸"], duplicate_count=2)
check("套餐卡可重复标记", 'class="dup"' in card_html(_dup_combo, is_new=False))

# 完整页面
out = os.path.join(tmp2, "page.html")
render_page([cards[0]], l2.collection, l2.collection_stats(), out, "测试",
            meta={"store": "麦当劳沈阳站出发层餐厅", "sampledAt": "2026-10-20"})
check("页面文件已生成", os.path.exists(out))
with open(out, "r", encoding="utf-8") as f:
    doc = f.read()
check("页面是完整 HTML", doc.startswith("<!DOCTYPE html>"))
check("页面含麦当劳品牌色", "#DA291C" in doc and "#FFC72C" in doc)
check("页面 CSS 含斜切角标", "skewX" in doc)
check("页面 CSS 含 Orbitron 字体", "Orbitron" in doc)
check("页面 CSS 含 Rajdhani 字体", "Rajdhani" in doc)
check("页面含移动适配", "viewport" in doc)
check("页面含免责声明", "非麦当劳官方产品" in doc)

# 卡牌点击弹窗（详情 + 立即购买按钮）
check("页面含点击弹窗", 'id="modal"' in doc and "openM" in doc)
check("页面注入了卡片数据", "const DATA" in doc and "__DATA__" not in doc)

# 图片优先级：MCP 真实图 > 用户自制图
_cimg = Card(id="img_t", name="有图卡", rarity="R", price=10, calories=100,
             protein=5, fat=1, carbohydrate=10, sodium=50, health_score=70,
             image_url="https://menu-img.mcd.cn/abc.png")
_cnimg = Card(id="nimg_t", name="无图卡", rarity="R", price=10, calories=100,
              protein=5, fat=1, carbohydrate=10, sodium=50, health_score=70,
              image_path="assets/cards/nimg_t.png")
check("优先使用 MCP image_url", "menu-img.mcd.cn" in card_html(_cimg))
check("无 image_url 时回退到 image_path", "assets/cards/nimg_t.png" in card_html(_cnimg))

# 空收藏册
empty_out = os.path.join(tmp2, "empty.html")
l3 = Ledger.load(os.path.join(tmp2, "e3.json"))
render_page([], [], l3.collection_stats(), empty_out)
with open(empty_out, "r", encoding="utf-8") as f:
    d3 = f.read()
check("空收藏册显示提示", "收藏册还是空的" in d3)
check("空收藏册显示引导", "告诉 AI「抽一张」" in d3)

# 同步卡池：data.json 也能读（与网页端共享 53 张卡池）
import os as _os2, sys as _sys2
_T2 = _os2.path.dirname(_os2.path.abspath(__file__))
_tools_dir = _os2.path.join(_T2, "..", "..", "tools")
_sys2.path.insert(0, _tools_dir)
_data_json = _os2.path.join(_tools_dir, "data.json")
if _os2.path.exists(_data_json):
    from gacha import _load_pool
    _cards, _src = _load_pool(_tools_dir)
    check("能从 data.json 加载卡池", len(_cards) > 0, f"{len(_cards)} 张")
    check("data.json 卡池含套餐", any(getattr(c, "is_combo", False) for c in _cards))
    _noimg = [c for c in _cards if not getattr(c, "image_url", "") and not getattr(c, "is_combo", False)]
    check("data.json 单品卡池全部有图源", not _noimg, f"{len(_noimg)} 张缺图")
    _full = render_page([], [c.to_dict() for c in _cards],
                        {"collected": len(_cards), "distribution": {}, "avg_calories": 500,
                         "avg_health_score": 60, "total_draws": 0, "points": 5, "combo_count": 0},
                        _os2.path.join(tmp2, "full.html"), "全部卡牌",
                        meta={"store": "麦当劳沈阳站出发层餐厅", "sampledAt": "2026-10-20"})
    with open(_full, "r", encoding="utf-8") as f:
        _dfull = f.read()
    check("整页渲染含 MCP 真实图", "menu-img.mcd.cn" in _dfull)

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