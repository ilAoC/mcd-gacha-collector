#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
麦卡收藏家 · mcd-gacha-collector
核心引擎：积分账本 + 卡池构建 + 加权抽卡 + 收藏册管理

设计原则：取数交给 MCP，算术交给代码，表达交给 Agent。
本模块不负责与用户对话，只做确定性的数据处理。

纯标准库实现，无第三方依赖。
"""

from __future__ import annotations

import json
import math
import os
import random
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

# ============================================================
# 常量配置
# ============================================================

CST = timezone(timedelta(hours=8))

#: 积分恢复间隔（小时）。默认 4 小时恢复 1 次抽卡机会。
RECOVER_HOURS = 4

#: 每次抽卡消耗的积分
COST_PER_DRAW = 1

#: 新用户初始积分
INITIAL_POINTS = 5

#: 稀有度定义：SSR > UR > R
RARITIES = ["SSR", "UR", "R"]

#: 各稀有度的默认抽卡权重
DEFAULT_WEIGHTS = {"SSR": 5.0, "UR": 20.0, "R": 75.0}

#: 健康度评分权重（用于稀有度划分与排序）
#:
#: 依据国家卫生健康委《体重管理指导原则（2024 年版）》：
#:   - 「每日减少 500~1000 千卡或减少 30% 总能量摄入」→ 单餐热量应以
#:     **每日推荐摄入的一餐占比**为基准（成年轻体力活动约 2000 kcal/日，
#:     三餐按早 30% / 午 40% / 晚 30% 分配 → 午餐基准 800 kcal）
#:   - 「碳水 50~60%、脂肪 20~30%、蛋白质 15~20%」→ 蛋白质供能比是
#:     官方明确推荐区间，用蛋白密度衡量最贴近原则
#:   - 「减少高糖、高油、高盐食物」→ 低钠单列一项
HEALTH_WEIGHTS = {
    "protein_density": 0.30,   # 蛋白质密度（对应供能比 15~20%）
    "meal_share": 0.40,        # 单餐热量占每日推荐摄入比（核心新增维度）
    "sodium_light": 0.30,      # 低钠
}

#: 套餐专用权重：看营养结构而非总量
COMBO_WEIGHTS = {
    "protein_density": 0.35,   # 每 100 大卡的蛋白质
    "sodium_density": 0.30,    # 每 100 大卡的钠
    "calorie_load": 0.35,      # 热量载荷（基准线提高到 1000 大卡 = 一顿正餐）
}

#: ---- 体重管理参考常量（《体重管理指导原则（2024 年版）》推导）----
#:
#: 中国成年男性轻体力活动日总能量约 2250 kcal，女性约 1800 kcal；
#: 取轻体力活动成年人日均 2000 kcal 作为参考基准。
DAILY_ENERGY_REF = 2000.0

#: 三餐能量分配：早 30% / 午 40% / 晚 30%（原则第 10 页「合理膳食」）
MEAL_SHARE = {"breakfast": 0.30, "lunch": 0.40, "dinner": 0.30}

#: 单餐热量基准（按午餐 40% 计）= 800 kcal
MEAL_ENERGY_REF = DAILY_ENERGY_REF * MEAL_SHARE["lunch"]

#: 减重期单餐建议上限：原则要求每日减 500~1000 kcal，
#: 反推一餐不应超过参考基准的 80%（否则当日难以完成缺口）
MEAL_ENERGY_LOSS_CAP = MEAL_ENERGY_REF * 0.80  # 640 kcal

#: ---- 卡面标签体系（把原始营养数值转成 3 个通俗等级）----
#:
#: 依据《体重管理指导原则（2024 年版）》的宏量营养素供能比推荐：
#:   碳水 50~60% · 脂肪 20~30% · 蛋白质 15~20%（减重高蛋白 20~30%）
#: 卡面不展示原始克数，只展示「高/中/低」三档标签，降低认知负担。

#: 蛋白质供能比分档（%）：原则推荐 15~20%，减重高蛋白 20~30%
#: 阈值按实测分布收紧，保证三档都有卡（否则全是「高」或全是「低」）
PROTEIN_RATIO_BANDS = ((20.0, "高"), (12.0, "中"), (0.0, "低"))

#: 脂肪供能比分档（%）：原则推荐 20~30%，实测多数肉品落在 30~45%
FAT_RATIO_BANDS = ((30.0, "低"), (42.0, "中"), (0.0, "高"))

#: 钠密度分档（mg/100kcal）：中国居民膳食指南建议每日<2000mg
#: 实测多数餐品在 80~200 之间，据此定三档
SODIUM_DENSITY_BANDS = ((120.0, "低"), (220.0, "中"), (0.0, "高"))

#: 单餐能量负荷分档（占日均 2000 kcal）：
#: ≤32%（≤640 kcal）= 轻（减重期建议上限）/ ≤40%（≤800 kcal）= 中 / 其余 = 重
ENERGY_TAG_BANDS = ((MEAL_ENERGY_LOSS_CAP, "轻"), (MEAL_ENERGY_REF, "中"), (1e9, "重"))

#: 单张卡价格区间（元），用于价格分档
PRICE_TIERS = [
    (0, 15, "A"),     # ≤15 元
    (15, 30, "B"),    # 15-30 元
    (30, 45, "C"),    # 30-45 元
    (45, 10 ** 9, "D"),  # >45 元
]

SCHEMA_VERSION = "1.0"


# ============================================================
# 数据结构
# ============================================================

@dataclass
class NutritionItem:
    """来自 MCP list-nutrition-foods 的单个餐品营养数据。"""
    name: str
    energy_kcal: float = 0.0
    protein: float = 0.0
    fat: float = 0.0
    carbohydrate: float = 0.0
    sodium: float = 0.0
    calcium: float = 0.0
    energy_kj: float = 0.0
    #: 仅供套餐评分使用：套餐售价（元）。单品评分不依赖该字段。
    _price: float = 0.0

    @classmethod
    def from_mcp_row(cls, row: Dict[str, Any]) -> "NutritionItem":
        def num(v: Any) -> float:
            try:
                return float(v)
            except (TypeError, ValueError):
                return 0.0
        return cls(
            name=(row.get("productName") or "").strip(),
            energy_kcal=num(row.get("energyKcal")),
            protein=num(row.get("protein")),
            fat=num(row.get("fat")),
            carbohydrate=num(row.get("carbohydrate")),
            sodium=num(row.get("sodium")),
            calcium=num(row.get("calcium")),
            energy_kj=num(row.get("energyKj")),
        )

    @property
    def health_score(self) -> float:
        """
        健康度评分 0~100。
        蛋白质密度 30% + 单餐能量占比 40% + 低钠 30%。
        评分只用于稀有度划分与展示，不代表任何医学建议。

        评分基准来自《体重管理指导原则（2024 年版）》：
          - 单餐能量基准 800 kcal（日均 2000 kcal × 午餐占比 40%）
          - 减重期单餐上限 640 kcal（基准的 80%）
        """
        # 1) 蛋白质密度：每 100 大卡含多少克蛋白，上限 15g/100kcal 记满分
        protein_density = (self.protein / self.energy_kcal * 100) if self.energy_kcal > 0 else 0.0
        p_score = min(protein_density / 15.0, 1.0)

        # 2) 单餐能量占比：以 800 kcal 为满分基准，超过 640 kcal 线性衰减到 0
        c_score = self.meal_share_score()

        # 3) 低钠：钠含量 0 最优，2000mg 以上 0 分
        s_score = max(0.0, min(1.0, (2000.0 - self.sodium) / 2000.0))

        raw = (
            HEALTH_WEIGHTS["protein_density"] * p_score
            + HEALTH_WEIGHTS["meal_share"] * c_score
            + HEALTH_WEIGHTS["sodium_light"] * s_score
        )
        return round(raw * 100, 1)

    @property
    def macro_ratio(self) -> Dict[str, float]:
        """
        三大营养素供能比（%），依据《体重管理指导原则（2024 年版）》。
        碳水 50~60% · 脂肪 20~30% · 蛋白质 15~20%（减重高蛋白 20~30%）。
        """
        if self.energy_kcal <= 0:
            return {"protein": 0.0, "fat": 0.0, "carb": 0.0}
        total_kcal = self.energy_kcal
        return {
            "protein": round(self.protein * 4 / total_kcal * 100, 1),
            "fat": round(self.fat * 9 / total_kcal * 100, 1),
            "carb": round(self.carbohydrate * 4 / total_kcal * 100, 1),
        }

    @staticmethod
    def _band(value: float, bands) -> str:
        """按阈值表取值：bands 为 ((下限, 标签), ...) 降序排列。"""
        for threshold, label in bands:
            if value >= threshold:
                return label
        return bands[-1][1]

    @property
    def protein_tag(self) -> str:
        """蛋白质标签：供能比≥25% 高 / ≥15% 中 / 其余 低。"""
        if self.energy_kcal <= 0 or self.protein <= 0:
            return "—"
        return self._band(self.macro_ratio["protein"], PROTEIN_RATIO_BANDS)

    @property
    def fat_tag(self) -> str:
        """脂肪标签：供能比≤20% 低 / ≤30% 中 / 其余 高。"""
        if self.energy_kcal <= 0 or self.fat <= 0:
            return "—"
        ratio = self.macro_ratio["fat"]
        if ratio <= FAT_RATIO_BANDS[0][0]:
            return "低"
        if ratio <= FAT_RATIO_BANDS[1][0]:
            return "中"
        return "高"

    @property
    def sodium_tag(self) -> str:
        """钠标签：钠密度≤80mg/100kcal 低 / ≤180 中 / 其余 高。"""
        if self.energy_kcal <= 0 or self.sodium <= 0:
            return "—"
        density = self.sodium / self.energy_kcal * 100
        if density <= SODIUM_DENSITY_BANDS[0][0]:
            return "低"
        if density <= SODIUM_DENSITY_BANDS[1][0]:
            return "中"
        return "高"

    @property
    def energy_tag(self) -> str:
        """能量负荷标签：≤640kcal 轻 / ≤800kcal 中 / 其余 重。"""
        if self.energy_kcal <= 0:
            return "—"
        if self.energy_kcal <= ENERGY_TAG_BANDS[0][0]:
            return "轻"
        if self.energy_kcal <= ENERGY_TAG_BANDS[1][0]:
            return "中"
        return "重"

    @property
    def meal_share(self) -> float:
        """单餐能量占每日参考摄入（2000 kcal）的百分比，如 28.6 表示 28.6%。"""
        return round(self.energy_kcal / DAILY_ENERGY_REF * 100, 1)

    def meal_share_score(self) -> float:
        """
        单餐能量占比得分 0~1。
        ≤640 kcal（减重期建议上限）记满分，
        800 kcal（一餐基准）记 0.5 分，
        ≥1000 kcal 记 0 分。
        """
        kcal = self.energy_kcal
        if kcal <= 0:
            return 1.0  # 无热量数据（如水）不扣分
        if kcal <= MEAL_ENERGY_LOSS_CAP:
            return 1.0
        if kcal >= MEAL_ENERGY_REF * 1.25:   # 1000 kcal
            return 0.0
        # 640~1000 之间线性衰减（1000 时为 0）
        return max(0.0, (MEAL_ENERGY_REF * 1.25 - kcal) /
                   (MEAL_ENERGY_REF * 1.25 - MEAL_ENERGY_LOSS_CAP))

    @property
    def combo_health_score(self) -> float:
        """
        套餐专用健康度评分 0~100。

        套餐与单品的差异在于：套餐是一次性摄入多件食物，
        总量大但**结构可控**（主食+小食+饮料的配比）。
        因此评分不看总量，而看两项结构指标：

          1) 蛋白质密度（35%）：每 100 大卡含多少克蛋白。
             对应原则「蛋白质供能 15~20%，减重期 20~30%」。
             套餐普遍含优质蛋白，因此分数不会天然偏低。
          2) 钠密度（30%）：每 100 大卡含多少毫克钠。
             对应原则「减少高盐食物」。
          3) 热量载荷（35%）：以 1000 大卡为满分基准线向下衰减，
             1200 大卡（占日均 60%）记 0 分。
             套餐本身就是**一整顿**，需按整餐视角评估；
             若沿用单品的 800 大卡基准，套餐会集体低分。

        评分基准来自《体重管理指导原则（2024 年版）》：
        日均约 2000 kcal，一餐基准 800 kcal（午餐占 40%），
        减重期建议每日减 500~1000 kcal。

        该指标仅用于游戏化分级，不代表营养建议。
        """
        if self.energy_kcal <= 0:
            return 0.0

        # 蛋白质密度：每 100 大卡的蛋白克数。
        # 实测三件套约 2.4~4.4 g/100kcal，取 0~5.0 为满分区间。
        p_density = self.protein / self.energy_kcal * 100
        p_score = max(0.0, min(1.0, p_density / 5.0))

        # 钠密度：每 100 大卡的钠毫克数。
        # 实测三件套约 90~165 mg/100kcal，取 80~200 为线性区间，
        # 低于 80 满分、高于 200 零分，能有效区分高钠套餐。
        s_density = self.sodium / self.energy_kcal * 100
        s_score = max(0.0, min(1.0, (200.0 - s_density) / 120.0))

        # 热量载荷：1000 kcal 记满分（套餐=一整顿，按整餐基准评估），
        # 1200 kcal（占日均 60%）记 0 分
        c_score = max(0.0, min(1.0, (1200.0 - self.energy_kcal) / 200.0))

        raw = (
            COMBO_WEIGHTS["protein_density"] * p_score
            + COMBO_WEIGHTS["sodium_density"] * s_score
            + COMBO_WEIGHTS["calorie_load"] * c_score
        )
        return round(raw * 100, 1)


@dataclass
class Card:
    """一张卡牌。"""
    id: str
    name: str
    rarity: str                      # SSR / UR / R
    price: float
    calories: float
    protein: float
    fat: float
    carbohydrate: float
    sodium: float
    health_score: float
    price_tier: str = "A"
    category: str = "其他"
    image_path: str = ""             # 预留：用户用生图软件制作的卡面
    image_url: str = ""              # MCP query-meals image 字段返回的真实菜单图
    product_code: str = ""           # MCP 餐品编码，用于下单
    is_combo: bool = False           # 是否为套餐
    combo_items: List[str] = field(default_factory=list)  # 套餐默认搭配的组件名
    # ---- 卡面展示用的通俗标签（原始克数不显示）----
    rarity_value: float = 0.0        # 综合收藏价值分 0~1（决定稀有度，与健康度无关）
    meal_share: float = 0.0          # 占每日参考摄入 2000 kcal 的百分比
    protein_tag: str = "—"           # 蛋白质供能比等级：高/中/低
    fat_tag: str = "—"               # 脂肪供能比等级：低/中/高
    sodium_tag: str = "—"            # 钠密度等级：低/中/高
    energy_tag: str = "—"            # 能量负荷等级：轻/中/重
    obtained_at: str = ""
    draw_index: int = 0
    is_new: bool = True              # 是否为本次新获得（收藏册高亮用）
    duplicate_count: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @property
    def tags(self) -> List[Dict[str, str]]:
        """卡面标签组（供前端直接渲染）。"""
        return [
            {"key": "energy", "label": "能量", "value": self.energy_tag},
            {"key": "protein", "label": "蛋白", "value": self.protein_tag},
            {"key": "fat", "label": "脂肪", "value": self.fat_tag},
            {"key": "sodium", "label": "钠", "value": self.sodium_tag},
        ]

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Card":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})


# ============================================================
# 稀有度划分
# ============================================================

#: 相对分级的分位阈值（按卡池内健康度排名取百分比）
#:
#: 采用相对分级而非固定阈值，原因是：各门店在售菜单结构差异很大
#: （例如沈阳站门店没有咖啡类单品，固定阈值会导致 SSR 为空、玩法失真）。
#: 分位数保证**任何门店都能得到完整的三档层次**。
QUANTILE_TIERS = {
    "SSR": 0.90,  # 健康度前 10% -> SSR
    "UR": 0.60,   # 60%~90% -> UR
                # 其余 60%     -> R
}

#: 小卡池兜底：卡池小于该数量时，相对分级区分度不足，退回固定阈值
MIN_POOL_FOR_QUANTILE = 8

#: 固定阈值（仅在卡池过小时作为兜底）
FALLBACK_THRESHOLDS = {"SSR": 75.0, "UR": 55.0}


# ---- 稀有度规则（综合「收藏价值」，与健康度完全解耦）----
#:
#: 设计原则：**稀有度回答「值不值得收集」，健康度回答「好不好」**。
#: 两者是正交维度。若稀有度由健康度决定，会出现
#: 「高热量低营养 = R 档」这类误导——玩家会误以为 R 档就是差。
#:
#: 稀有度改由**综合收藏价值分**决定，三个维度加权：
#:   价格 50% —— 越贵重越难收集（经典抽卡逻辑）
#:   热量载荷 30% —— 正餐份量越足越有收集价值
#:   蛋白含量 20% —— 营养密度高的更有收集价值
#:
#: 三个维度都是**「越高越稀有」**，与健康度的方向无关。

#: 价格归一化上限（元）—— 取卡池内最高价
RARITY_PRICE_CAP = 62.5

#: 热量载荷归一化上限（kcal）—— 取卡池内最高值附近
RARITY_KCAL_CAP = 1000.0

#: 蛋白含量归一化上限（g）
RARITY_PROTEIN_CAP = 40.0

#: 综合收藏价值的三项权重
RARITY_WEIGHTS = {"price": 0.50, "calorie": 0.30, "protein": 0.20}

#: 三档的价值分位数（R 取后 58%，UR 取 42%~75%，SSR 取前 25%）
RARITY_TIERS = {"SSR": 0.75, "UR": 0.42}

#: 归入 UR 的汉堡类品类（保留给旧数据兼容）
UR_BURGER_CATEGORIES = {"汉堡"}

#: 归入 SSR 的最低价格（元）
SSR_PRICE_FLOOR = 45.0

#: 归入 UR 的汉堡最低价格（元）
UR_BURGER_PRICE_FLOOR = 24.0


def rarity_value(price: float, calories: float, protein: float) -> float:
    """
    综合收藏价值分 0~1（越高越稀有）。

    与健康度**完全无关**：三个维度都是「越高越稀有」，
    但它们衡量的都是「收集价值」而非「营养质量」。

      价格 50%：min(price / 62.5, 1.0)
      热量 30%：min(calories / 1000, 1.0)  —— 份量越足越有收集价值
      蛋白 20%：min(protein / 40, 1.0)

    实测 53 张卡分布：0.068 ~ 0.990
    """
    p = min(price / RARITY_PRICE_CAP, 1.0)
    k = min(calories / RARITY_KCAL_CAP, 1.0)
    pr = min(protein / RARITY_PROTEIN_CAP, 1.0)
    return round(
        RARITY_WEIGHTS["price"] * p
        + RARITY_WEIGHTS["calorie"] * k
        + RARITY_WEIGHTS["protein"] * pr,
        4,
    )


def assign_rarity(price: float, price_tier_: str, category: str,
                  calories: float = 0.0, protein: float = 0.0,
                  thresholds: Optional[Dict[str, float]] = None) -> str:
    """
    按综合收藏价值划分稀有度（**与健康度无关**）。

    流程：
      1. 算综合收藏价值分（价格 50% + 热量 30% + 蛋白 20%）
      2. 用**卡池内分位数**切三档（价值前 25% = SSR，42%~75% = UR，其余 R）

    分位数而非固定分数线：各门店菜单结构差异大，
    固定分数线会导致某些门店抽不到 SSR。

    :param price: 门店售价（元）
    :param price_tier_: 价格档（保留参数，兼容旧调用）
    :param category: 品类（保留参数，兼容旧调用）
    :param calories: 热量（kcal）
    :param protein: 蛋白质（g）
    :param thresholds: 价值分阈值 {"SSR": 0.74, "UR": 0.27}
    """
    v = rarity_value(price, calories, protein)
    th = thresholds or RARITY_FALLBACK_THRESHOLDS
    if v >= th["SSR"]:
        return "SSR"
    if v >= th["UR"]:
        return "UR"
    return "R"


#: 卡池过小时的兜底阈值（价值分）
RARITY_FALLBACK_THRESHOLDS = {"SSR": 0.70, "UR": 0.30}


def compute_rarity_thresholds(cards: List["Card"]) -> Dict[str, float]:
    """按卡池内的综合价值分布，计算三档阈值（分位数法）。"""
    values = [rarity_value(c.price, c.calories, c.protein) for c in cards]
    if len(values) < MIN_POOL_FOR_QUANTILE:
        return dict(RARITY_FALLBACK_THRESHOLDS)
    ordered = sorted(values)
    n = len(ordered)

    def pct(p: float) -> float:
        return ordered[int(round(p * (n - 1)))]

    return {"SSR": pct(RARITY_TIERS["SSR"]), "UR": pct(RARITY_TIERS["UR"])}


def assign_rarity_by_score(health_score: float,
                           thresholds: Optional[Dict[str, float]] = None) -> str:
    """
    旧版按健康度分级的实现（保留供历史数据与测试使用）。

    新流程不再调用此函数——稀有度已与健康度解耦。
    """
    th = thresholds or FALLBACK_THRESHOLDS
    if health_score >= th["SSR"]:
        return "SSR"
    if health_score >= th["UR"]:
        return "UR"
    return "R"


def compute_thresholds(scores: List[float]) -> Dict[str, float]:
    """
    依据当前卡池的健康度分布，计算三档阈值。

    采用分位数（分位点法），对分布形态稳健：不受极端值影响，
    且样本量变化时划分比例保持稳定。

    卡池过小时分位数区分度不足（可能多个餐品同分），
    此时退回固定阈值，避免出现"所有卡都是同一档"或"空档"。
    """
    if len(scores) < MIN_POOL_FOR_QUANTILE:
        return dict(FALLBACK_THRESHOLDS)

    ordered = sorted(scores)
    n = len(ordered)

    def percentile(p: float) -> float:
        idx = int(round(p * (n - 1)))
        return ordered[idx]

    return {"SSR": percentile(QUANTILE_TIERS["SSR"]),
            "UR": percentile(QUANTILE_TIERS["UR"])}


def price_tier(price: float) -> str:
    for lo, hi, tier in PRICE_TIERS:
        if lo <= price < hi:
            return tier
    return "D"


def guess_category(name: str) -> str:
    """按餐品名关键词粗分品类，仅用于卡面标签展示。"""
    table = [
        ("巨无霸", "汉堡"), ("堡", "汉堡"), ("麦满分", "早餐"), ("卷", "卷类"),
        ("鸡翅", "小食"), ("麦乐鸡", "小食"), ("趣鸡球", "小食"),
        ("脆薯饼", "小食"), ("香肠", "小食"), ("翅", "小食"), ("球", "小食"),
        ("玉米", "小食"), ("薯", "薯条"),
        ("派", "甜点"), ("新地", "甜点"), ("旋风", "甜品"), ("雪冰", "甜品"),
        ("奶冻", "甜品"),
        ("咖啡", "饮品"), ("摩卡", "饮品"), ("玛奇朵", "饮品"), ("美式", "饮品"),
        ("红茶", "饮品"), ("伯爵红茶", "饮品"), ("柠檬红茶", "饮品"),
        ("拉明顿", "饮品"), ("阿芙佳朵", "饮品"),
        ("可乐", "饮料"), ("雪碧", "饮料"), ("怡泉", "饮料"),
        ("橙", "饮品"), ("苹果", "饮品"), ("牛奶", "饮品"), ("豆浆", "饮品"),
        ("燕麦", "饮品"), ("奶铁", "饮品"), ("热牛奶", "饮品"), ("冰牛奶", "饮品"),
        ("朱古力", "饮品"),
        ("沙拉", "轻食"), ("粥", "早餐"), ("油条", "早餐"), ("鸡", "鸡肉"),
    ]
    for kw, cat in table:
        if kw in name:
            return cat
    return "其他"


# ============================================================
# 卡池构建
# ============================================================

def build_cards(
    nutrition_rows: List[Dict[str, Any]],
    price_map: Optional[Dict[str, float]] = None,
    combo_rows: Optional[List[Dict[str, Any]]] = None,
) -> List[Card]:
    """
    由 MCP 营养数据构建卡池（单品 + 套餐）。

    :param nutrition_rows: list-nutrition-foods 归一化后的单品行列表
    :param price_map: 餐品名 -> 售价（元）。缺失价格的会被剔除，
                       因为卡牌必须标注价格。
    :param combo_rows: 套餐行列表。每行形如
        {"name": 套餐名, "price": 售价, "items": [组件名...],
         "calories": 总热量, "protein":..., "fat":...,
         "carbohydrate":..., "sodium":...}
        套餐营养由默认搭配组件加总而来，评分走combo_health_score 独立算法，
        且**与单品分别计算稀有度阈值**，避免套餐因分量大而集体低分。
    """
    price_map = price_map or {}
    seen: set[str] = set()

    # ---- 第一趟：解析单品 ----
    singles: List[Tuple[NutritionItem, float]] = []
    for row in nutrition_rows:
        item = NutritionItem.from_mcp_row(row)
        if not item.name or item.name in seen:
            continue
        price = price_map.get(item.name)
        if price is None:
            continue
        seen.add(item.name)
        singles.append((item, round(float(price), 2)))

    # ---- 解析套餐 ----
    combos: List[Tuple[Dict[str, Any], NutritionItem, float]] = []
    for row in (combo_rows or []):
        name = (row.get("name") or "").strip()
        if not name or name in seen:
            continue
        price = row.get("price")
        if price is None:
            continue
        price = round(float(price), 2)
        item = NutritionItem(
            name=name,
            energy_kcal=float(row.get("calories", 0) or 0),
            protein=float(row.get("protein", 0) or 0),
            fat=float(row.get("fat", 0) or 0),
            carbohydrate=float(row.get("carbohydrate", 0) or 0),
            sodium=float(row.get("sodium", 0) or 0),
        )
        # 供combo_health_score 取用价格
        item._price = price
        seen.add(name)
        combos.append((row, item, price))

    # ---- 分别计算阈值：单品一套、套餐一套 ----
    th_single = compute_thresholds([it.health_score for it, _ in singles])
    th_combo = compute_thresholds([it.combo_health_score for _, it, _ in combos])

    cards: List[Card] = []
    for item, price in singles:
        hs = item.health_score
        tier = price_tier(price)
        cat = guess_category(item.name)
        cid = f"_{_slug(item.name)}"  # 稀有度前缀稍后回填
        cards.append(Card(
            id=cid, name=item.name, rarity="R", price=price,
            calories=item.energy_kcal, protein=item.protein, fat=item.fat,
            carbohydrate=item.carbohydrate, sodium=item.sodium, health_score=hs,
            price_tier=tier, category=cat,
            image_path="", is_combo=False,
            meal_share=item.meal_share, protein_tag=item.protein_tag,
            fat_tag=item.fat_tag, sodium_tag=item.sodium_tag,
            energy_tag=item.energy_tag,
        ))

    for row, item, price in combos:
        hs = item.combo_health_score
        tier = price_tier(price)
        cid = f"_{_slug(item.name)}"
        cards.append(Card(
            id=cid, name=item.name, rarity="R", price=price,
            calories=item.energy_kcal, protein=item.protein, fat=item.fat,
            carbohydrate=item.carbohydrate, sodium=item.sodium, health_score=hs,
            price_tier=tier, category="套餐",
            image_path="", is_combo=True,
            combo_items=list(row.get("items", [])),
            meal_share=item.meal_share, protein_tag=item.protein_tag,
            fat_tag=item.fat_tag, sodium_tag=item.sodium_tag,
            energy_tag=item.energy_tag,
        ))

    # 第二趟：按全池价值分位数定稀有度，回填 id / image_path
    th_rar = compute_rarity_thresholds(cards)
    for c in cards:
        c.rarity_value = rarity_value(c.price, c.calories, c.protein)
        c.rarity = assign_rarity(c.price, c.price_tier, c.category,
                                 c.calories, c.protein, th_rar)
        c.id = f"{c.rarity.lower()}_{c.id.lstrip('_')}"
        c.image_path = f"assets/cards/{c.id}.png"
    return cards


def pool_thresholds(
    nutrition_rows: List[Dict[str, Any]],
    combo_rows: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Dict[str, float]]:
    """返回构建卡池时实际使用的阈值，便于 --inspect 展示与调试。"""
    singles = []
    seen: set[str] = set()
    for row in nutrition_rows:
        it = NutritionItem.from_mcp_row(row)
        if it.name and it.name not in seen:
            seen.add(it.name)
            singles.append(it.health_score)
    combos = []
    for row in (combo_rows or []):
        price = float(row.get("price", 0) or 0)
        if not price:
            continue
        it = NutritionItem(
            name=row.get("name", ""),
            energy_kcal=float(row.get("calories", 0) or 0),
            protein=float(row.get("protein", 0) or 0),
            fat=float(row.get("fat", 0) or 0),
            carbohydrate=float(row.get("carbohydrate", 0) or 0),
            sodium=float(row.get("sodium", 0) or 0),
        )
        it._price = price
        combos.append(it.combo_health_score)
    return {"single": compute_thresholds(singles),
            "combo": compute_thresholds(combos) if combos else dict(FALLBACK_THRESHOLDS)}


def _slug(name: str) -> str:
    """把中文餐品名转成文件名安全的 slug（保留中文，去掉非法字符）。"""
    bad = '<>:"/\\|?*'
    out = "".join("_" if ch in bad else ch for ch in name)
    return out.strip() or "item"


def validate_pool(cards: List[Card], thresholds: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """卡池自检：分布是否合理、字段是否完整。"""
    dist: Dict[str, int] = {r: 0 for r in RARITIES}
    missing_img = 0
    missing_price = 0
    zero_cal = 0
    for c in cards:
        dist[c.rarity] = dist.get(c.rarity, 0) + 1
        if not c.image_path:
            missing_img += 1
        if c.price <= 0:
            missing_price += 1
        if c.calories <= 0:
            zero_cal += 1
    total = len(cards) or 1

    # 反推本次使用的阈值：SSR 档的最低分即 SSR 阈值，UR 档最低分即 UR 阈值
    eff: Dict[str, float] = dict(thresholds) if thresholds else {}
    if not eff:
        for r in ("SSR", "UR"):
            vals = [c.health_score for c in cards if c.rarity == r]
            if vals:
                eff[r] = min(vals)

    return {
        "total": len(cards),
        "distribution": dist,
        "distribution_pct": {k: round(v / total * 100, 1) for k, v in dist.items()},
        "thresholds": {k: round(v, 1) for k, v in eff.items()},
        "all_tiers_present": all(dist.get(r, 0) > 0 for r in RARITIES),
        "missing_image": missing_img,
        "missing_price": missing_price,
        "zero_calorie_items": zero_cal,
        "avg_health_score": round(sum(c.health_score for c in cards) / total, 1) if cards else 0,
    }


# ============================================================
# 加权抽卡
# ============================================================

class GachaEngine:
    """抽卡引擎。随机种子可注入，保证可复现（便于自测）。"""

    def __init__(
        self,
        cards: List[Card],
        weights: Optional[Dict[str, float]] = None,
        seed: Optional[int] = None,
    ):
        if not cards:
            raise ValueError("卡池为空，无法抽卡")
        self.cards = cards
        self.weights = dict(weights or DEFAULT_WEIGHTS)
        self.rng = random.Random(seed)

    def draw(self, budget: Optional[float] = None) -> Card:
        """
        抽一张卡。

        :param budget: 预算上限（元）。给定后，售价高于预算的卡不参与抽卡。
        :raises ValueError: 预算内无卡可选。
        """
        pool = self.cards
        if budget is not None:
            pool = [c for c in self.cards if c.price <= budget]
            if not pool:
                raise ValueError(
                    f"预算 {budget} 元内没有可抽取的餐品，"
                    f"卡池最低售价为 {min(c.price for c in self.cards)} 元"
                )

        # 先按稀有度加权选档，再在档内等概率选具体餐品
        by_rarity: Dict[str, List[Card]] = {r: [] for r in RARITIES}
        for c in pool:
            by_rarity.setdefault(c.rarity, []).append(c)
        by_rarity = {k: v for k, v in by_rarity.items() if v}
        if not by_rarity:
            raise ValueError("预算内无卡可选")

        rarities = list(by_rarity.keys())
        w = [self.weights.get(r, 1.0) for r in rarities]
        rarity = self.rng.choices(rarities, weights=w, k=1)[0]
        return self.rng.choice(by_rarity[rarity])

    def draw_many(self, n: int, budget: Optional[float] = None) -> List[Card]:
        return [self.draw(budget) for _ in range(n)]


def simulate_distribution(cards: List[Card], times: int = 10000, seed: int = 42) -> Dict[str, Any]:
    """蒙特卡洛模拟：验证实际抽卡分布与配置权重是否一致。"""
    eng = GachaEngine(cards, seed=seed)
    counts: Dict[str, int] = {r: 0 for r in RARITIES}
    pool_dist: Dict[str, int] = {r: sum(1 for c in cards if c.rarity == r) for r in RARITIES}
    for _ in range(times):
        c = eng.draw()
        counts[c.rarity] += 1

    expected = {}
    total_w = sum(DEFAULT_WEIGHTS[r] for r in pool_dist if pool_dist[r] > 0)
    for r, n in pool_dist.items():
        if n > 0 and total_w > 0:
            # 档内等概率，所以实际概率 = 权重 × 档内占比
            expected[r] = round(
                DEFAULT_WEIGHTS[r] / total_w * (n / sum(pool_dist.values())) * 100, 2
            )
    actual = {r: round(counts[r] / times * 100, 2) for r in RARITIES}
    return {
        "times": times,
        "expected_pct": expected,
        "actual_pct": actual,
        "raw_counts": counts,
        "pool_distribution": pool_dist,
    }


# ============================================================
# 积分账本（游戏化本地积分）
# ============================================================

@dataclass
class Ledger:
    """
    本地积分账本。

    说明：这是 Skill 自建的游戏化玩法机制，与麦当劳官方积分账户
    （query-my-account）相互独立，不影响也不消耗用户真实积分。
    """
    points: int = INITIAL_POINTS
    last_recover_at: str = ""
    total_draws: int = 0
    collection: List[Dict[str, Any]] = field(default_factory=list)
    updated_at: str = ""

    # ---- 时间处理 ----
    @staticmethod
    def _now() -> datetime:
        return datetime.now(CST)

    @staticmethod
    def _fmt(dt: datetime) -> str:
        return dt.strftime("%Y-%m-%d %H:%M:%S")

    @classmethod
    def load(cls, path: str) -> "Ledger":
        if not os.path.exists(path):
            led = cls(last_recover_at=cls._fmt(cls._now()))
            led.save(path)
            return led
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in raw.items() if k in known})

    def save(self, path: str) -> None:
        self.updated_at = self._fmt(self._now())
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, ensure_ascii=False, indent=2)

    # ---- 恢复逻辑 ----
    def recover(self, recover_hours: int = RECOVER_HOURS) -> Dict[str, Any]:
        """
        按时间恢复积分。
        每经过 recover_hours 小时恢复 COST_PER_DRAW 积分，最多累计恢复 24 小时。
        """
        if not self.last_recover_at:
            self.last_recover_at = self._fmt(self._now())
            return {"recovered": 0, "points": self.points}

        last = datetime.strptime(self.last_recover_at, "%Y-%m-%d %H:%M:%S").replace(tzinfo=CST)
        now = self._now()
        elapsed_h = (now - last).total_seconds() / 3600.0

        # 最多累计 24 小时，防止长期不开游戏一次性暴增
        capped = min(elapsed_h, 24.0)
        steps = int(capped // recover_hours)
        recovered = steps * COST_PER_DRAW

        if recovered > 0:
            self.points += recovered
            # 消费掉已结算的时间段，保留余数
            self.last_recover_at = self._fmt(
                last + timedelta(hours=steps * recover_hours)
            )

        remain_h = (now - datetime.strptime(self.last_recover_at, "%Y-%m-%d %H:%M:%S")
                    .replace(tzinfo=CST)).total_seconds() / 3600.0
        return {
            "recovered": recovered,
            "points": self.points,
            "elapsed_hours": round(elapsed_h, 2),
            "next_recover_in_hours": round(max(0.0, recover_hours - remain_h), 2),
        }

    def next_recover_at(self, recover_hours: int = RECOVER_HOURS) -> str:
        if not self.last_recover_at:
            return self._fmt(self._now())
        last = datetime.strptime(self.last_recover_at, "%Y-%m-%d %H:%M:%S").replace(tzinfo=CST)
        return self._fmt(last + timedelta(hours=recover_hours))

    def can_draw(self, n: int = 1) -> bool:
        return self.points >= n * COST_PER_DRAW

    def consume(self, n: int = 1) -> None:
        need = n * COST_PER_DRAW
        if self.points < need:
            raise ValueError(f"积分不足：需要 {need}，当前 {self.points}")
        self.points -= need
        self.total_draws += n

    # ---- 收藏册 ----
    def add_card(self, card: Card) -> Card:
        """把抽到的卡加入收藏册；重复卡累加次数。"""
        now = self._fmt(self._now())
        for entry in self.collection:
            if entry.get("id") == card.id:
                entry["duplicate_count"] = int(entry.get("duplicate_count", 1)) + 1
                card.duplicate_count = entry["duplicate_count"]
                card.is_new = False
                return card
        card.obtained_at = now
        card.draw_index = len(self.collection) + 1
        self.collection.append(card.to_dict())
        return card

    def collection_stats(self) -> Dict[str, Any]:
        cards = [Card.from_dict(e) for e in self.collection]
        dist: Dict[str, int] = {r: 0 for r in RARITIES}
        for c in cards:
            dist[c.rarity] = dist.get(c.rarity, 0) + 1
        return {
            "collected": len(cards),
            "distribution": dist,
            "avg_calories": round(sum(c.calories for c in cards) / len(cards), 1) if cards else 0,
            "avg_health_score": round(sum(c.health_score for c in cards) / len(cards), 1) if cards else 0,
            "total_draws": self.total_draws,
            "points": self.points,
        }


# ============================================================
# 预算与约束辅助
# ============================================================

def affordable_summary(cards: List[Card], budget: float) -> Dict[str, Any]:
    """给定预算，统计可抽到的卡池分布。"""
    pool = [c for c in cards if c.price <= budget]
    dist: Dict[str, int] = {r: 0 for r in RARITIES}
    for c in pool:
        dist[c.rarity] = dist.get(c.rarity, 0) + 1
    return {
        "budget": budget,
        "affordable_count": len(pool),
        "total_count": len(cards),
        "distribution": dist,
        "cheapest": min((c.price for c in pool), default=None),
        "priciest": max((c.price for c in pool), default=None),
        "lightest_calories": min((c.calories for c in pool), default=None),
    }


def calorie_band(cards: List[Card], limit: float) -> List[Card]:
    """按热量上限过滤（可选附加约束）。"""
    return [c for c in cards if c.calories <= limit]


# ============================================================
# CLI
# ============================================================

def _load_pool(data_dir: str) -> Tuple[List[Card], Optional[str]]:
    """
    从数据目录读取卡池。
    读取优先级：
      1) data.json —— 网页构建产物（包含套餐、image_url、product_code）
      2) pool.json —— Agent 归一化后生成的中间产物
      3) nutrition.json + prices.json —— 兜底，运行时按单算法构建
    """
    # 1) data.json：网页端构建产物，含 meta 与 cards
    data_json = os.path.join(data_dir, "data.json")
    if os.path.exists(data_json):
        with open(data_json, "r", encoding="utf-8") as f:
            raw = json.load(f)
        items = raw.get("cards") if isinstance(raw, dict) and "cards" in raw else raw
        return [Card.from_dict(x) for x in items], data_json

    # 2) pool.json
    pool_path = os.path.join(data_dir, "pool.json")
    if os.path.exists(pool_path):
        with open(pool_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        items = raw.get("items") if isinstance(raw, dict) else raw
        return [Card.from_dict(x) for x in items], pool_path

    # 3) nutrition.json + prices.json 兜底
    nut_path = os.path.join(data_dir, "nutrition.json")
    price_path = os.path.join(data_dir, "prices.json")
    if os.path.exists(nut_path):
        with open(nut_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        rows = raw.get("items") if isinstance(raw, dict) else raw
        if not isinstance(rows, list):
            rows = []
        prices = {}
        if os.path.exists(price_path):
            with open(price_path, "r", encoding="utf-8") as f:
                praw = json.load(f)
            prices = praw.get("prices") if isinstance(praw, dict) and "prices" in praw else praw
        return build_cards(rows, prices), nut_path
    return [], None


def main(argv: List[str]) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="麦卡收藏家 · 抽卡引擎")
    ap.add_argument("data_dir", help="数据目录（含 pool.json 或 nutrition.json）")
    ap.add_argument("--draw", type=int, default=1, help="抽卡次数")
    ap.add_argument("--budget", type=float, default=None, help="预算上限（元）")
    ap.add_argument("--ledger", default=None, help="积分账本路径")
    ap.add_argument("--recover-hours", type=int, default=RECOVER_HOURS, help="积分恢复间隔小时数")
    ap.add_argument("--seed", type=int, default=None, help="随机种子（可复现）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--inspect", action="store_true", help="只检查卡池，不抽卡")
    ap.add_argument("--collection", action="store_true", help="查看收藏册统计")
    ap.add_argument("--simulate", type=int, default=0, help="模拟抽卡次数，验证概率分布")
    args = ap.parse_args(argv)

    cards, source = _load_pool(args.data_dir)
    if not cards:
        print(json.dumps({"success": False, "error": f"未在 {args.data_dir} 找到卡池数据"}, ensure_ascii=False))
        return 1

    if args.inspect:
        out = {"success": True, "source": source, "validate": validate_pool(cards)}
        if args.budget is not None:
            out["budget_view"] = affordable_summary(cards, args.budget)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    if args.simulate > 0:
        out = {"success": True, "simulation": simulate_distribution(cards, args.simulate, args.seed or 42)}
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    ledger_path = args.ledger or os.path.join(args.data_dir, "ledger.json")
    led = Ledger.load(ledger_path)
    rec = led.recover(args.recover_hours)

    if args.collection:
        out = {"success": True, "recover": rec, "stats": led.collection_stats(),
               "collection": led.collection}
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    if not led.can_draw(args.draw):
        out = {
            "success": False,
            "error": f"积分不足：抽 {args.draw} 次需要 {args.draw * COST_PER_DRAW}，当前 {led.points}",
            "points": led.points,
            "next_recover_at": led.next_recover_at(args.recover_hours),
            "recover": rec,
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 2

    engine = GachaEngine(cards, seed=args.seed)
    drawn: List[Card] = []
    for _ in range(args.draw):
        c = engine.draw(args.budget)
        c = led.add_card(c)
        drawn.append(c)
    # 抽卡成功后才扣积分，避免抽卡失败却扣分
    led.consume(args.draw)
    led.save(ledger_path)

    out = {
        "success": True,
        "recover": rec,
        "drawn": [c.to_dict() for c in drawn],
        "stats": led.collection_stats(),
        "next_recover_at": led.next_recover_at(args.recover_hours),
        "ledger_path": ledger_path,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))