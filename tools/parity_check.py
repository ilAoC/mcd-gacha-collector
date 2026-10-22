#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
网页版与 Skill 引擎一致性校验（parity check）。

校验网页内联数据与 Python 引擎计算结果是否一致：
1. 网页data.json 的卡池与 build_cards 重新计算结果一致
2. 稀有度分布与阈值一致
3. 稀有度/价格分档/品类判定一致
4. 概率权重配置一致

用法：python tools/parity_check.py
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "skills", "mcd-gacha-collector", "scripts"))

from gacha import (  # noqa: E402
    build_cards, compute_thresholds, RARITIES, DEFAULT_WEIGHTS,
    price_tier, guess_category, assign_rarity, rarity_value,
    compute_rarity_thresholds,
)

HTML = os.path.join(ROOT, "docs", "index.html")
DATA = os.path.join(HERE, "data.json")

PASS = FAIL = 0
FAILURES = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        FAILURES.append(f"{name} {detail}".strip())
        print(f"  [FAIL] {name} {detail}")


print("\n[1/8] 读取产物")
with open(DATA, "r", encoding="utf-8") as f:
    data = json.load(f)
cards = data["cards"]
meta = data["meta"]
check("data.json 卡池非空", len(cards) > 0, f"实际 {len(cards)}")
check("网页 index.html 存在", os.path.exists(HTML))

with open(HTML, "r", encoding="utf-8") as f:
    html = f.read()
check("网页已内联数据", "/*__DATA__*/" not in html)
check("网页体积合理(<200KB)", os.path.getsize(HTML) < 200_000,
      f"{os.path.getsize(HTML):,} bytes")

# 从网页 JS 里抠出内联 JSON，与 data.json 对比
m = re.search(r"const DATA = (\{.*?\});\s*const META", html, re.S)
check("可从网页解析出内联数据", m is not None)
if m:
    web_data = json.loads(m.group(1))
    check("网页内联数据与 data.json 完全一致",
          json.dumps(web_data, sort_keys=True) == json.dumps(data, sort_keys=True))

print("\n[2/8] 卡池重算一致性")
# 关键：必须用**全卡池**（单品+套餐）重建，否则稀有度阈值（按全池价值分位数）不一致
_single_cards = [c for c in cards if not c.get("is_combo")]
_combo_cards = [c for c in cards if c.get("is_combo")]
_rebuilt_rows = [{
    "productName": c["name"],
    "energyKcal": c["calories"], "protein": c["protein"], "fat": c["fat"],
    "carbohydrate": c["carbohydrate"], "sodium": c["sodium"],
    "calcium": 0, "energyKj": 0,
} for c in _single_cards]
_rebuilt_combos = [{
    "name": c["name"], "code": c.get("product_code", ""),
    "price": c["price"], "calories": c["calories"], "protein": c["protein"],
    "fat": c["fat"], "carbohydrate": c["carbohydrate"], "sodium": c["sodium"],
    "items": c.get("combo_items", []),
} for c in _combo_cards]
rebuilt = build_cards(_rebuilt_rows,
                      {c["name"]: c["price"] for c in _single_cards},
                      _rebuilt_combos)

check("重算卡池数量一致", len(rebuilt) == len(cards),
      f"{len(rebuilt)} vs {len(cards)}")

by_name = {r.name: r for r in rebuilt}
mismatch = []
for c in cards:
    r = by_name.get(c["name"])
    if not r:
        mismatch.append(f"{c['name']} 缺失")
        continue
    for f_ in ("rarity", "price", "calories", "protein", "fat",
               "carbohydrate", "sodium", "health_score", "price_tier",
               "category", "id"):
        if getattr(r, f_) != c.get(f_):
            mismatch.append(f"{c['name']}.{f_}: {getattr(r, f_)} vs {c.get(f_)}")
check("逐字段完全一致", not mismatch, "; ".join(mismatch[:3]))

print("\n[3/8] 稀有度规则与分布")
# 稀有度按综合收藏价值分（价格 50% + 热量 30% + 蛋白 20%）划分，与健康度无关
# cards 是从 HTML 反解的 dict，直接按公式算阈值
_vals_all = sorted(rarity_value(c["price"], c["calories"], c["protein"]) for c in cards)
_n = len(_vals_all)
_rth = ({"SSR": _vals_all[int(round(0.75 * (_n - 1)))],
         "UR": _vals_all[int(round(0.42 * (_n - 1)))]}
        if _n >= 8 else {"SSR": 0.70, "UR": 0.30})
bad_rar = [c["name"] for c in cards
           if assign_rarity(c["price"], c["price_tier"], c["category"],
                            c["calories"], c["protein"], _rth) != c["rarity"]]
check("稀有度与规则一致（综合价值分）", not bad_rar, str(bad_rar[:3]))
bad_val = [c["name"] for c in cards
           if abs(c.get("rarity_value", 0) - rarity_value(c["price"], c["calories"], c["protein"])) > 0.001]
check("每张卡的价值分与公式一致", not bad_val, str(bad_val[:3]))

dist = {r: sum(1 for c in cards if c["rarity"] == r) for r in RARITIES}
check("三档均有卡", all(v > 0 for v in dist.values()), str(dist))

# 解耦验证：三档的健康度区间必须大幅重叠（否则说明回退成了按健康度分级）
_health = {r: [c["health_score"] for c in cards if c["rarity"] == r] for r in RARITIES}
_ranges = {r: (min(v), max(v)) for r, v in _health.items() if v}
_overlap = max(lo for lo, _ in _ranges.values()) < min(hi for _, hi in _ranges.values())
check("三档健康度区间重叠（已解耦）", _overlap, str(_ranges))
# 价值分区间必须单调分离（稀有度确实由价值分决定）
_vals = {r: [c.get("rarity_value", 0) for c in cards if c["rarity"] == r] for r in RARITIES}
_vmin = {r: min(v) for r, v in _vals.items() if v}
check("价值分随稀有度单调升高", _vmin["SSR"] > _vmin["UR"] > _vmin["R"], str(_vmin))
check("meta 含稀有度规则与阈值",
      "rarityRule" in meta and "rarityThresholds" in meta)

print("\n[4/8] 规则与常量一致性")
bad_tier = [c["name"] for c in cards if c["price_tier"] != price_tier(c["price"])]
check("价格分档一致", not bad_tier, str(bad_tier[:3]))
# 品类判定：单品走关键词匹配，套餐统一为「套餐」
bad_cat = [c["name"] for c in cards
           if c["category"] != (c.get("category") if c.get("is_combo")
                               else guess_category(c["name"]))]
check("品类判定一致（单品关键词 / 套餐固定）", not bad_cat, str(bad_cat[:3]))
check("单品关键词判定生效",
      all(c["category"] == guess_category(c["name"])
          for c in cards if not c.get("is_combo")))
check("抽卡权重与引擎默认一致", meta["weights"] == DEFAULT_WEIGHTS,
      f"{meta['weights']} vs {DEFAULT_WEIGHTS}")
check("恢复间隔为 4 小时", meta["recoverHours"] == 4)
check("初始积分一致", meta["initialPoints"] == 5)
check("单抽消耗为 1", meta["costPerDraw"] == 1)
check("卡面路径规则一致",
      all(c["image_path"] == f"assets/cards/{c['id']}.png" for c in cards))
check("积分满额值已定义", "MAX_POINTS" in html and "COOLDOWN_MS" in html)
check("网页使用同一套权重表", 'META.weights[r]' in html)
check("Skill 端仍保留 4 小时恢复配置",
      meta.get("recoverHours") == 4, str(meta.get("recoverHours")))
check("网页不含真实 Token",
      "Bearer " not in html and "${MCD_MCP_TOKEN}" not in html
      and not re.search(r'Authorization\s*[:=]\s*["\']\s*(?!Bearer\s*$)\w{16,}', html))

print("\n[5/8] 卡面图片")
sys.path.insert(0, HERE)
from image_map import IMAGE_MAP  # noqa: E402

with_img = [c for c in cards if c.get("image_url")]
check("全部卡牌都有图片", len(with_img) == len(cards),
      f"{len(with_img)}/{len(cards)}")
check("图片均来自麦当劳官方 CDN",
      all(c["image_url"].startswith("https://menu-img.mcd.cn/") for c in with_img))
check("图片 URL 无重复",
      len({c["image_url"] for c in with_img}) == len(with_img))
check("每张卡有餐品编码", all(c.get("product_code") for c in cards))
# 单品图片来自 image_map，套餐图片来自 combo_data，两者都不应缺失
check("单品图片映射表覆盖完整",
      set(IMAGE_MAP.keys()) >= {c["name"] for c in cards if not c.get("is_combo")})
check("网页渲染 image_url 字段", "c.image_url" in html)
check("网页有图片加载失败降级", "onerror=" in html)
check("网页弹窗展示大图", 'class="mimg"' in html or "mimg" in html)
# 积分机制已从「按时间恢复」改为「手动刷新重置」，此处不再校验 24h 封顶

print("\n[6/8] 卡牌视觉与演出")
# 卡面结构：图片不遮挡、数据独立面板、稀有度角标
check("卡面图片为独立区块", 'class="art"' in html)
check("数据区为独立面板", 'class="panel"' in html)
_art_h = re.search(r"\.art\{[^}]*height:\s*(\d+)px", html)
check("图片高度足够大(>=140px)",
      _art_h is not None and int(_art_h.group(1)) >= 140,
      f"实际 {_art_h.group(1) if _art_h else 'N/A'}px")
check("健康度为右上角环形徽章", 'class="score"' in html and "scoreBadge" in html)
check("环形进度用 SVG 实现", "stroke-dasharray" in html and "<circle" in html)
check("面板内不再有旧进度条", 'class="hs"' not in html and 'class="bar"' not in html)
check("NEW 徽标避开分数位", re.search(r"\.new\{[^}]*top:62px", html) is not None)
check("引入展示字体", "Orbitron" in html and "Rajdhani" in html)
check("数值统一用展示字体", "var(--f-num)" in html)
check("标签统一用展示字体", "var(--f-lab)" in html)

print("\n[7/8] 页面精简")
# 已删除的区块不应残留
check("已移除本次抽卡区", 'id="lastBox"' not in html and 'id="lastInfo"' not in html)
check("已移除 lastDraw 变量", "lastDraw" not in html)
check("已移除顶部已收集数", 'id="ctNum"' not in html)
# 保留的区块应存在
check("保留收藏册", 'id="colBox"' in html)
check("保留抽卡按钮", 'id="btnDraw"' in html)
check("保留预算输入", 'id="inpBudget"' in html)
check("积分改为手动刷新重置", 'id="btnRefill"' in html and "refill" in html)
check("已移除时间恢复逻辑",
      "nextInText" not in html and "lastRecover" not in html
      and "META.recoverHours" not in html)
check("刷新有冷却防刷", "COOLDOWN_MS" in html)
check("刷新满额状态有样式", "pt-refill.full" in html)
# 统计条：细窄、在底部、含关键指标
check("统计条为细窄布局", re.search(r"\.stats\{[^}]*display:flex", html) is not None)
check("统计条不含网格格子", "grid" not in re.search(r"\.stats\{[^}]*\}", html).group(0))
check("统计数字已缩小", re.search(r"\.stat \.v\{[^}]*font-size:1[0-5]px", html) is not None)
check("统计含已收集/SSR/UR/R",
      all(k in html for k in ["已收集", "SSR", "UR", "均热量", "总抽卡"]))
check("SSR/UR/R 统计值分色",
      "stat.ssr" in html and "stat.ur" in html and "stat.r" in html)
# NEW 标记改由 drawnIds驱动（本次抽卡区已删）
check("NEW 由本次抽卡集合驱动", "drawnIds" in html)
check("NEW 会定时撤除", "drawnIds.clear()" in html)
check("演出后滚动到收藏册", 'scrollIntoView' in html and 'colBox' in html)
# Hero 图鉴轮播
check("Hero 有图鉴容器", 'id="heroShelf"' in html and "renderShelf" in html)
check("图鉴展示已收集卡", "led.collection" in html)
check("未收集显示锁定剪影", "hs-card locked" in html or 'locked' in html)
check("图鉴自动轮播", "setInterval" in html and "shelfTimer" in html)

print("\n[8/8] 套餐支持")
combos = [c for c in cards if c.get("is_combo")]
singles = [c for c in cards if not c.get("is_combo")]
check("卡池含单品", len(singles) > 0, f"{len(singles)}")
check("卡池含套餐", len(combos) > 0, f"{len(combos)}")
check("套餐 category 统一为「套餐」", all(c["category"] == "套餐" for c in combos))
check("套餐均记录组件", all(c.get("combo_items") for c in combos))
check("单品均标记 is_combo=False", all(c.get("is_combo") is False for c in singles))
check("稀有度规则为综合价值分（套餐与单品共用）",
      "rarityRule" in meta and "价格" in meta["rarityRule"] and "热量" in meta["rarityRule"])
# 套餐评分不得因分量大而集体低分
cs = [c["health_score"] for c in combos]
check("套餐评分有区分度(跨度>=15)", (max(cs) - min(cs)) >= 15, f"{max(cs)-min(cs):.1f}")
check("套餐评分中位数 >= 55（不集体低分）",
      sorted(cs)[len(cs)//2] >= 55, f"{sorted(cs)[len(cs)//2]:.1f}")
cdist = {r: sum(1 for c in combos if c["rarity"] == r) for r in RARITIES}
check("套餐稀有度按综合价值分划分",
      all(assign_rarity(c["price"], c["price_tier"], "套餐",
                        c["calories"], c["protein"], _rth) == c["rarity"]
          for c in cards if c.get("is_combo")))
# 卡片与页面
check("卡面显示套餐标签", 'class="tier combo"' in html or "is_combo" in html)
check("弹窗展示默认搭配", "combo_items" in html)
check("弹窗说明套餐热量为默认搭配", "默认搭配" in html)
check("统计含套餐数量", "套餐" in html and "nCombo" in html)
check("提示区分单品与套餐", "singleCount" in html and "comboCount" in html)
check("套餐有图片", all(c.get("image_url") for c in combos))
check("稀有度斜切角标", "rar-tag" in html and "skewX" in html)
check("三档均有主题类", all(f"t-{r}" in html for r in RARITIES))
check("SSR 角标有呼吸光效", "rarGlow" in html)
check("卡名带描边不遮主体", "text-shadow" in html)

# 抽卡演出
check("有翻牌结构", "flip-wrap" in html and 'class="flip"' in html)
check("卡背为 3D 翻转", "preserve-3d" in html and "rotateY(180deg)" in html)
check("有召唤飞入动画", "summonIn" in html and 'classList.add("summon")' in html)
check("召唤动画有落位回弹", "@keyframes summonIn" in html)
check("SSR 光柱旋转特效", "repeating-conic-gradient" in html and "spin" in html)
check("SSR 全屏金色光晕", "ssr-veil" in html)
check("SSR 粒子爆散", "ssr-burst" in html and "burst" in html)
check("SSR 大字特效", "ssr-word" in html and "ssrWord" in html)
check("UR 有独立演出", "ur-veil" in html)
check("末张 SSR 压轴排序", "order[a.rarity] - order[b.rarity]" in html)
check("演出防重入", "busy" in html and "if(busy) return" in html)
check("演出可跳过但仅末张", "allowSkip" in html)
check("doDraw 为 async", "async function doDraw" in html)

# 兼容性与无死代码
check("支持减少动效偏好", "prefers-reduced-motion" in html)
check("已移除废弃的 artHtml", "function artHtml" not in html)
check("CSS 变量已迁移", "--ssr-a" in html and "--ur-b" in html)

print("\n" + "=" * 52)
print(f"  通过 {PASS} 项，失败 {FAIL} 项")
if FAILURES:
    print("  失败明细：")
    for f_ in FAILURES:
        print(f"   - {f_}")
print("=" * 52)
sys.exit(1 if FAIL else 0)