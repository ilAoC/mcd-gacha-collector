#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
麦卡收藏家 · 卡牌渲染器（v3 · 麦当劳品牌风）

把抽到的卡牌渲染成 HTML（卡面图 + 价格 + 卡路里 + 立即购买按钮），
并生成收藏册页面。

视觉风格与网页端保持一致：
  - 品牌色：番茄红 #DA291C + 金黄 #FFC72C + 深棕底 #140705
  - 卡面：MCP query-meals image 字段（官方菜单图）→ 自动降级为 emoji
  - 健康度评分：右上角环形徽章
  - 稀有度：斜切横幅角标（SSR 金 / UR 玫红 / R 红）

支持两类卡：
  - 单品（is_combo=False）：用单品算法评分（35% 蛋白密度 + 40% 低热量 + 25% 低钠）
  - 套餐（is_combo=True）：用套餐算法评分（40% 蛋白密度 + 35% 钠密度 + 25% 热量载荷），
    卡面额外标注「套餐」徽章与默认搭配组件

纯标准库实现。
"""

from __future__ import annotations

import html
import json
import os
import sys
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gacha import Card, RARITIES  # noqa: E402

# ------------------------------------------------------------
# 视觉：三档稀有度配色（与网页端 CSS 变量一一对应）
# ------------------------------------------------------------

RARITY_THEME = {
    "SSR": {"label": "SSR", "c1": "#FFE9A8", "c2": "#FFC72C", "c3": "#FF7A00",
            "gl": "rgba(255,199,44,0.72)"},
    "UR":  {"label": "UR",  "c1": "#FFD3E4", "c2": "#FF5C9D", "c3": "#B3155E",
            "gl": "rgba(255,92,157,0.55)"},
    "R":   {"label": "R",   "c1": "#CFE4FF", "c2": "#5AA9F0", "c3": "#1B5FA8",
            "gl": "rgba(90,169,240,0.44)"},
}

EMOJI_FALLBACK = {
    "汉堡": "🍔", "卷类": "🌯", "小食": "🍟", "薯条": "🍟",
    "甜点": "🥧", "甜品": "🍦", "饮品": "🥤", "饮料": "🥤",
    "轻食": "🥗", "早餐": "🍳", "鸡肉": "🍗", "套餐": "🍱",
}

# 字号约定：数值用 Orbitron 风格（letter-spacing），标签用 Rajdhani
CSS = """
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --mcd-red:#DA291C;--mcd-red-d:#8E1509;--mcd-gold:#FFC72C;--mcd-gold-d:#E09A00;
  --bg:#140705;--txt:#FFF4E8;--dim:#C9A28E;
}
body{
  font-family:"PingFang SC","HarmonyOS Sans SC","Microsoft YaHei","Segoe UI",system-ui,sans-serif;
  background:var(--bg);color:var(--txt);min-height:100vh;padding:28px 16px 56px;
}
.wrap{max-width:1180px;margin:0 auto}

/* ============ 页面头部 ============ */
.page-head{text-align:center;margin-bottom:30px}
.page-head h1{
  display:inline-block;padding:11px 28px;border-radius:16px;
  font-size:30px;font-weight:900;letter-spacing:2px;color:#fff;
  background:linear-gradient(150deg,var(--mcd-red),var(--mcd-red-d));
  border:2.5px solid var(--mcd-gold);
  box-shadow:0 8px 0 rgba(0,0,0,.34),0 12px 30px rgba(218,41,28,.45),inset 0 2px 0 rgba(255,255,255,.24);
  text-shadow:0 2px 4px rgba(0,0,0,.4)
}
.page-head .sub{color:var(--mcd-gold);font-size:13px;margin-top:14px;font-weight:700;letter-spacing:.6px}
.page-head .store{color:#FFDCA8;font-size:11.5px;margin-top:8px;
  background:rgba(218,41,28,.3);border:1px solid rgba(255,199,44,.34);
  padding:5px 14px;border-radius:20px;display:inline-block}

/* ============ 统计条：细窄胶囊 ============ */
.stats{display:flex;align-items:center;justify-content:center;flex-wrap:wrap;
  gap:7px 15px;margin:22px auto 30px;padding:11px 18px;width:fit-content;max-width:100%;
  background:linear-gradient(180deg,rgba(255,199,44,.1),rgba(218,41,28,.06));
  border:1px solid rgba(255,199,44,.2);border-radius:20px}
.stat{display:flex;align-items:baseline;gap:4px;white-space:nowrap}
.stat .v{font-family:"Orbitron","Rajdhani",ui-monospace,"SF Mono",monospace;
  font-size:14px;font-weight:900;color:var(--mcd-gold);line-height:1;letter-spacing:.2px}
.stat .k{font-family:"Rajdhani","PingFang SC",sans-serif;
  font-size:10px;color:var(--dim);letter-spacing:.6px}
.stat.ssr .v{color:#FFC72C}.stat.ur .v{color:#FF5C9D}.stat.r .v{color:#5AA9F0}
.stat.combo .v{color:var(--mcd-red)}

/* ============ 分区标题 ============ */
.section-title{display:flex;align-items:center;gap:9px;font-size:16px;font-weight:800;
  margin:30px 0 14px;color:var(--mcd-gold);letter-spacing:.6px}
.section-title::before{content:"";width:5px;height:17px;
  background:linear-gradient(180deg,var(--mcd-gold),var(--mcd-red));border-radius:2px}
.section-title small{margin-left:auto;font-size:11.5px;color:var(--dim);font-weight:500}

/* ============ 卡牌：与网页端一致 ============ */
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(204px,1fr));gap:16px}

.card{position:relative;border-radius:17px;padding:3px;cursor:pointer;
  transition:transform .22s cubic-bezier(.34,1.56,.64,1),box-shadow .22s}
.card:hover{transform:translateY(-8px) scale(1.025);z-index:5}
.card:active{transform:scale(.975)}

.card-in{
  position:relative;border-radius:14px;overflow:hidden;min-height:330px;
  display:flex;flex-direction:column;
  box-shadow:inset 0 0 0 1px rgba(255,255,255,.09),inset 0 -30px 46px rgba(0,0,0,.42)
}

/* 卡面图片：主体，不被遮挡 */
.art{position:relative;width:100%;height:166px;flex:none;overflow:hidden;
  background:linear-gradient(155deg,var(--c3),#120704)}
.art img{width:100%;height:100%;object-fit:cover;display:block;
  transition:transform .5s cubic-bezier(.34,1.3,.64,1)}
.card:hover .art img{transform:scale(1.07)}
.art::after{content:"";position:absolute;inset:0;pointer-events:none;
  background:linear-gradient(180deg,transparent 46%,rgba(18,7,4,.88) 100%)}
.art::before{content:"";position:absolute;inset:0;z-index:1;
  background:radial-gradient(ellipse at 50% 42%,transparent 52%,rgba(18,7,4,.34) 100%)}
.art .ph{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
  font-size:46px;z-index:2}

/* 稀有度角标：斜切横幅 */
.rar-tag{position:absolute;top:10px;left:9px;z-index:6;
  display:flex;align-items:center;gap:4px;padding:4px 13px 4px 10px;
  font-family:"Orbitron","Rajdhani",ui-monospace,monospace;
  font-size:12.5px;font-weight:900;letter-spacing:1.6px;color:#2A0E04;
  background:linear-gradient(120deg,var(--c1),var(--c2) 52%,var(--c3));
  border-radius:4px 11px 11px 4px;
  box-shadow:0 3px 12px rgba(0,0,0,.5),inset 0 1px 0 rgba(255,255,255,.5);
  transform:skewX(-9deg)}
.rar-tag span{transform:skewX(9deg)}

/* 健康度环形徽章 */
.score{position:absolute;top:8px;right:8px;z-index:7;
  width:50px;height:50px;border-radius:50%;
  display:flex;align-items:center;justify-content:center;
  background:radial-gradient(circle at 50% 42%,rgba(28,12,8,.96),rgba(12,5,3,.98));
  border:1.5px solid var(--c2);
  box-shadow:0 3px 12px rgba(0,0,0,.62),0 0 16px var(--gl),inset 0 1px 4px rgba(0,0,0,.7)}
.score svg{position:absolute;inset:0;width:100%;height:100%;transform:rotate(-90deg)}
.score .tr{fill:none;stroke:rgba(255,255,255,.1);stroke-width:3.4}
.score .pg{fill:none;stroke-width:3.4;stroke-linecap:round;
  stroke:url(#sgrad);filter:drop-shadow(0 0 3px var(--gl))}
.score .inner{position:relative;z-index:2;text-align:center;line-height:1}
.score .num{font-family:"Orbitron",ui-monospace,monospace;
  font-size:16px;font-weight:900;color:#fff;letter-spacing:-.3px;
  text-shadow:0 1px 4px rgba(0,0,0,.9)}
.score .cap{font-family:"Rajdhani","PingFang SC",sans-serif;
  font-size:7px;font-weight:700;letter-spacing:.7px;color:var(--c1);margin-top:2px}

/* 卡名：压在图片下沿 */
.cn{position:absolute;left:11px;right:11px;bottom:8px;z-index:5;
  font-size:15px;font-weight:900;line-height:1.26;color:#fff;letter-spacing:.3px;
  text-shadow:0 2px 6px rgba(0,0,0,.95),0 0 14px rgba(0,0,0,.75)}
.cn .tier{display:inline-block;margin-left:5px;font-family:"Rajdhani","PingFang SC",sans-serif;
  font-size:9.5px;font-weight:700;letter-spacing:.6px;color:#3A1408;
  background:linear-gradient(120deg,var(--c1),var(--c2));
  padding:1.5px 7px;border-radius:20px;vertical-align:middle;
  text-shadow:none;box-shadow:0 1px 4px rgba(0,0,0,.4)}
.cn .tier.combo{color:#fff;background:linear-gradient(120deg,var(--mcd-gold),var(--mcd-red));
  padding:2px 8px;font-weight:700;letter-spacing:.8px;
  box-shadow:0 2px 8px rgba(218,41,28,.5),inset 0 1px 0 rgba(255,255,255,.34)}

/* 数据面板：与图片独立 */
.panel{flex:1;padding:11px 11px 12px;
  background:linear-gradient(180deg,rgba(18,7,4,.5),rgba(18,7,4,.9))}
.price-row{display:flex;align-items:baseline;gap:6px;margin-bottom:9px}
.price{font-family:"Orbitron",ui-monospace,monospace;
  font-size:21px;font-weight:900;color:var(--mcd-gold);line-height:1;letter-spacing:.5px;
  text-shadow:0 0 16px rgba(255,199,44,.55)}
.price-unit{font-family:"Rajdhani","PingFang SC",sans-serif;
  font-size:9.5px;color:var(--dim);font-weight:700;letter-spacing:.8px}
.nutri{display:grid;grid-template-columns:1fr 1fr;gap:6px}
.nu{background:rgba(0,0,0,.42);border-radius:9px;padding:6px 8px;
  border:1px solid rgba(255,255,255,.07)}
.nu .v{font-family:"Orbitron",ui-monospace,monospace;
  font-size:13.5px;font-weight:900;line-height:1.15;
  display:flex;align-items:baseline;gap:2px;letter-spacing:.2px}
.nu .u{font-family:"Rajdhani","PingFang SC",sans-serif;
  font-size:9px;font-weight:700;opacity:.7;letter-spacing:.3px}
.nu .k{font-size:9.5px;color:var(--dim);margin-top:2px;letter-spacing:.4px}
.nu.kcal .v{color:#8FD3FF}.nu.protein .v{color:#8FE9A0}
.nu.sodium .v{color:#FFAFA0}.nu.fat .v{color:#FFD08A}

/* NEW 徽标：与右上角分数徽章错开 */
.new{position:absolute;top:62px;right:8px;z-index:7;
  background:linear-gradient(120deg,var(--mcd-gold),var(--mcd-gold-d));color:#3A1408;
  font-family:"Rajdhani","PingFang SC",sans-serif;
  font-size:8.5px;font-weight:700;padding:2.5px 8px;border-radius:20px;
  letter-spacing:1.1px;box-shadow:0 3px 10px rgba(0,0,0,.5),inset 0 1px 0 rgba(255,255,255,.5)}

/* 重复计数 */
.dup{position:absolute;bottom:11px;right:11px;z-index:6;
  font-family:"Rajdhani","PingFang SC",sans-serif;font-size:9.5px;font-weight:900;
  background:rgba(255,199,44,.3);border:1px solid rgba(255,199,44,.44);
  padding:2px 8px;border-radius:20px;color:#FFE9B8}

/* ============ 空状态 ============ */
.empty{text-align:center;padding:70px 20px;color:#A8806F;
  border:1.5px dashed rgba(255,199,44,.28);border-radius:16px;
  background:rgba(255,199,44,.04)}
.empty .big{font-size:42px;margin-bottom:14px}
.empty .tip{color:#FFDCA8;font-size:12px;margin-top:14px;letter-spacing:.5px}

/* ============ 弹窗 ============ */
.modal{position:fixed;inset:0;background:rgba(20,7,5,.94);z-index:120;
  display:none;align-items:center;justify-content:center;padding:20px}
.modal.on{display:flex}
.mbox{background:#1E0B07;border:2px solid rgba(255,199,44,.32);border-radius:17px;
  padding:22px;max-width:400px;width:100%;max-height:88vh;overflow:auto;
  box-shadow:0 18px 50px rgba(0,0,0,.6)}
.mtitle{font-size:18px;font-weight:900;margin-bottom:14px;display:flex;
  align-items:center;gap:9px;letter-spacing:.4px}
.mtitle .rr{padding:3px 10px;border-radius:4px 9px 9px 4px;font-size:12px;font-weight:900;
  transform:skewX(-9deg);color:#2A0E04}
.mtitle .rr>span{transform:skewX(9deg);display:block}
.mimg{width:100%;height:168px;object-fit:cover;border-radius:11px;margin-bottom:14px;
  border:1.5px solid rgba(255,199,44,.26)}
.mrow{display:flex;justify-content:space-between;padding:9px 0;
  border-bottom:1px solid rgba(255,199,44,.14);font-size:13.5px}
.mrow span:first-child{color:var(--dim)}
.mrow b{font-family:"Orbitron",ui-monospace,monospace;
  font-weight:900;font-variant-numeric:tabular-nums;letter-spacing:.3px}
.mnote{font-size:11.5px;color:#C9A794;margin-top:13px;line-height:1.75}
.mbtns{display:flex;gap:9px;margin-top:18px}
.mbtns button{flex:1;padding:12px;border:none;border-radius:11px;
  font-size:14px;font-weight:900;cursor:pointer;font-family:inherit}
.mb-no{background:rgba(255,255,255,.1);color:var(--txt)}
.mb-yes{background:linear-gradient(96deg,var(--mcd-gold),var(--mcd-red));color:#fff;
  box-shadow:0 4px 14px rgba(218,41,28,.44)}

footer{margin-top:42px;padding-top:20px;border-top:2px solid rgba(255,199,44,.2);
  text-align:center;color:#A8806F;font-size:11.5px;line-height:2}
footer a{color:var(--mcd-gold);text-decoration:none}

@media(max-width:640px){
 .grid{grid-template-columns:repeat(auto-fill,minmax(172px,1fr));gap:11px}
 .card-in{min-height:302px}.art{height:150px}
 .price{font-size:18px}
}
"""


# ------------------------------------------------------------
# SVG 渐变定义（供健康度进度弧使用，单文件内嵌）
# ------------------------------------------------------------
SVG_DEFS = (
    '<svg width="0" height="0" style="position:absolute" aria-hidden="true">'
    '<defs><linearGradient id="sgrad" x1="0%" y1="0%" x2="100%" y2="100%">'
    '<stop offset="0%" stop-color="#FF7A00"/>'
    '<stop offset="55%" stop-color="#FFC72C"/>'
    '<stop offset="100%" stop-color="#FFF3C4"/>'
    '</linearGradient></defs></svg>'
)


def _esc(s: Any) -> str:
    return html.escape(str(s if s is not None else ""))


def _resolve_image(card: Card) -> str:
    """优先使用 MCP 真实图（card.image_url），否则回退到用户自制图路径。"""
    if getattr(card, "image_url", ""):
        return card.image_url
    return card.image_path or f"assets/cards/{card.id}.png"


def _score_badge(score: float) -> str:
    """环形健康度徽章（与网页端 scoreBadge 完全一致）。"""
    pct = max(0.0, min(100.0, float(score)))
    R = 21
    C = 2 * 3.14159265 * R
    dash = (pct / 100.0 * C)
    return (
        f'<div class="score" title="健康度 {score:.1f} / 100">'
        f'<svg viewBox="0 0 50 50"><circle class="tr" cx="25" cy="25" r="{R}"/>'
        f'<circle class="pg" cx="25" cy="25" r="{R}" stroke-dasharray="{dash:.2f} {C}"/></svg>'
        f'<div class="inner"><div class="num">{score:.0f}</div>'
        f'<div class="cap">健康度</div></div></div>'
    )


def _art_html(card: Card, emoji_fallback: str) -> str:
    img = _resolve_image(card)
    return (
        f'<div class="art"><img src="{_esc(img)}" alt="{_esc(card.name)}" loading="lazy" '
        f'onerror="this.parentNode.innerHTML=\'<div class="ph">{emoji_fallback}</div>\'"></div>'
    )


def card_html(card: Card, is_new: bool = False) -> str:
    """渲染单张卡牌 HTML（与网页端 cardHtml 视觉对齐）。"""
    th = RARITY_THEME.get(card.rarity, RARITY_THEME["R"])
    emoji = EMOJI_FALLBACK.get(card.category or "", "🍽️")
    is_combo = bool(getattr(card, "is_combo", False))

    tier_html = (
        f'<span class="tier combo">套餐</span>' if is_combo
        else f'<span class="tier">{_esc(card.category)}</span>'
    )
    new_html = '<div class="new">NEW</div>' if is_new else ''
    dup_html = (
        f'<div class="dup">×{card.duplicate_count}</div>' if card.duplicate_count > 1 else ''
    )

    return f"""<div class="card t-{card.rarity}" style="background:linear-gradient(150deg,{th['c1']},{th['c2']} 46%,{th['c3']});box-shadow:0 6px 22px {th['gl']}">
  <div class="card-in" style="background:linear-gradient(165deg,{th['c3']},#140806 62%)">
    {new_html}
    <div class="rar-tag"><span>{card.rarity}</span></div>
    {_score_badge(card.health_score)}
    {_art_html(card, emoji)}
    <div class="cn">{_esc(card.name)}{tier_html}</div>
    <div class="panel">
      <div class="price-row"><span class="price">¥{card.price:.2f}</span><span class="price-unit">门店价</span></div>
      <div class="nutri">
        <div class="nu kcal"><div class="v">{card.calories:.0f}<span class="u">kcal</span></div><div class="k">热量</div></div>
        <div class="nu protein"><div class="v">{card.protein:.0f}<span class="u">g</span></div><div class="k">蛋白质</div></div>
        <div class="nu fat"><div class="v">{card.fat:.0f}<span class="u">g</span></div><div class="k">脂肪</div></div>
        <div class="nu sodium"><div class="v">{card.sodium:.0f}<span class="u">mg</span></div><div class="k">钠</div></div>
      </div>
    </div>
    {dup_html}
  </div>
</div>"""


def _stats_bar(stats: Dict[str, Any]) -> str:
    if not stats:
        return ""
    d = stats.get("distribution", {})
    return f"""<div class="stats">
  <div class="stat"><span class="v">{stats.get('collected',0)}</span><span class="k">已收集</span></div>
  <div class="stat ssr"><span class="v">{d.get('SSR',0)}</span><span class="k">SSR</span></div>
  <div class="stat ur"><span class="v">{d.get('UR',0)}</span><span class="k">UR</span></div>
  <div class="stat r"><span class="v">{d.get('R',0)}</span><span class="k">R</span></div>
  <div class="stat combo"><span class="v">{stats.get('combo_count',0)}</span><span class="k">套餐</span></div>
  <div class="stat"><span class="v">{stats.get('avg_calories',0):.0f}</span><span class="k">均热量</span></div>
  <div class="stat"><span class="v">{stats.get('total_draws',0)}</span><span class="k">总抽卡</span></div>
</div>"""


def _meta_block(meta: Dict[str, Any]) -> str:
    if not meta:
        return ""
    parts = []
    if meta.get("store"):
        parts.append(f'<div class="store">📍 {_esc(meta["store"])} · {_esc(meta.get("sampledAt",""))} 实采</div>')
    return "".join(parts)


def render_page(
    drawn: List[Card],
    collection: List[Dict[str, Any]],
    stats: Dict[str, Any],
    out_path: str,
    title: str = "麦卡收藏家",
    meta: Optional[Dict[str, Any]] = None,
) -> str:
    """
    渲染完整页面：本次抽卡 + 我的收藏册 + 统计。

    :param drawn: 本次抽到的卡
    :param collection: 收藏册原始 dict 列表
    :param stats: 统计 dict
    :param out_path: 输出 HTML 路径
    :param meta: 元数据（含 store、sampledAt 等，用于头部展示）
    """
    parts: List[str] = []
    parts.append('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">')
    parts.append('<meta name="viewport" content="width=device-width,initial-scale=1">')
    parts.append(f"<title>{_esc(title)}</title><style>{CSS}</style></head><body>")
    parts.append(SVG_DEFS)
    parts.append('<div class="wrap">')
    parts.append(
        f'<div class="page-head"><h1>{_esc(title)}</h1>'
        f'<div class="sub">每一张卡，都是一份营养档案</div>'
        f'{_meta_block(meta or {})}</div>'
    )
    parts.append(_stats_bar(stats))

    if drawn:
        parts.append(f'<div class="section-title">本次抽卡 <small>共 {len(drawn)} 张</small></div>')
        parts.append('<div class="grid">' + "".join(card_html(c, is_new=True) for c in drawn) + "</div>")

    parts.append('<div class="section-title">我的收藏册</div>')
    coll_cards = [Card.from_dict(x) for x in collection]
    if coll_cards:
        coll_sorted = sorted(
            coll_cards,
            key=lambda c: (RARITIES.index(c.rarity), -c.health_score),
        )
        # 收藏册里的卡，如果本次也抽到了，加 NEW 标记
        drawn_ids = {c.id for c in drawn}
        parts.append(
            '<div class="grid">' + "".join(
                card_html(c, is_new=(c.id in drawn_ids)) for c in coll_sorted
            ) + "</div>"
        )
    else:
        parts.append(
            '<div class="empty"><div class="big">🃏</div>'
            '<div>收藏册还是空的，去抽第一张卡吧</div>'
            '<div class="tip">告诉 AI「抽一张」即可开始</div></div>'
        )

    parts.append(
        '<footer>'
        "麦卡收藏家 · mcd-gacha-collector · 麦当劳程序员创意开发大赛参赛作品<br>"
        "数据来自麦当劳 MCP Server（open.mcd.cn），餐品价格与供应以官方渠道实时结果为准。<br>"
        "本页面为参赛作品，非麦当劳官方产品；健康度评分仅供趣味参考，不构成营养建议。<br>"
        "<a href=\"https://github.com/M-China/mcd-developer-innovation-challenge\" target=\"_blank\" rel=\"noopener\">麦当劳程序员创意开发大赛</a>"
        "</footer>"
    )
    parts.append("</div>")

    # 弹窗：点卡牌看详情 + 购买按钮
    parts.append(_modal_html())

    # 点击卡牌弹出详情（含购买按钮）
    parts.append(_modal_js())

    doc = "".join(parts)
    # 把卡片数据序列化到页面，供弹窗使用（占位符注入）
    card_dump = [c.to_dict() for c in (drawn or [Card.from_dict(x) for x in collection])]
    doc = doc.replace("const DATA = __DATA__;", "const DATA = " + json.dumps(card_dump, ensure_ascii=False) + ";")
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(doc)
    return out_path


def _modal_html() -> str:
    return (
        '<div class="modal" id="modal" onclick="if(event.target===this)closeM()">'
        '<div class="mbox">'
        '<div class="mtitle" id="mTitle"></div>'
        '<div id="mBody"></div>'
        '<div class="mbtns">'
        '<button class="mb-no" onclick="closeM()">关闭</button>'
        '<button class="mb-yes" id="mYes">立即购买</button>'
        '</div>'
        '</div></div>'
    )


def _modal_js() -> str:
    return """<script>
const DATA = __DATA__;
function openM(idx){
  const c = DATA[idx]; if(!c) return;
  const t = ({SSR:{c1:'#FFE9A8',c2:'#FFC72C',c3:'#FF7A00'},UR:{c1:'#FFD3E4',c2:'#FF5C9D',c3:'#B3155E'},R:{c1:'#CFE4FF',c2:'#5AA9F0',c3:'#1B5FA8'}})[c.rarity]||{c1:'#CFE4FF',c2:'#5AA9F0',c3:'#1B5FA8'};
  document.querySelector('#mTitle').innerHTML =
    '<span class="rr" style="background:linear-gradient(120deg,'+t.c1+','+t.c2+','+t.c3+')"><span>'+c.rarity+'</span></span> '+
    esc(c.name);
  const img = c.image_url ? '<img class="mimg" src="'+esc(c.image_url)+'" alt="'+esc(c.name)+'" onerror="this.style.display=\'none\'">' : '';
  const items = c.combo_items && c.combo_items.length
    ? '<div class="mrow"><span>默认搭配</span><b style="font-size:12px">'+esc(c.combo_items.join(' + '))+'</b></div>'
    : '';
  document.querySelector('#mBody').innerHTML = img +
    '<div class="mrow"><span>价格</span><b style="color:#FFC72C">¥'+c.price.toFixed(2)+'</b></div>' +
    '<div class="mrow"><span>热量</span><b>'+c.calories.toFixed(0)+' kcal</b></div>' +
    '<div class="mrow"><span>蛋白质 / 脂肪 / 碳水</span><b>'+c.protein.toFixed(0)+' / '+c.fat.toFixed(0)+' / '+c.carbohydrate.toFixed(0)+' g</b></div>' +
    '<div class="mrow"><span>钠</span><b>'+c.sodium.toFixed(0)+' mg</b></div>' +
    '<div class="mrow"><span>健康度评分</span><b style="color:'+t.c2+'">'+c.health_score.toFixed(1)+'<span style="font-size:11px;opacity:.7"> / 100</span></b></div>' +
    '<div class="mrow"><span>品类</span><b>'+esc(c.category)+'</b></div>' +
    items +
    '<div class="mrow"><span>餐品编码</span><b>'+esc(c.product_code || c.id)+'</b></div>' +
    '<div class="mnote">数据来自麦当劳 MCP 实测。<br>' +
    (c.is_combo ? '套餐营养为<strong>默认搭配</strong>基准值，实际可替换小食与饮料。' : '') +
    '<br>网页版不含下单能力，可回复「买这张 '+esc(c.name)+'」通过 Skill 完成下单。</div>';
  document.querySelector('#mYes').onclick = () => {
    closeM();
    alert('告诉 AI：「购买 '+c.name+'（'+esc(c.product_code || c.id)+'）」\\n门店：'+esc(c.store||''));
  };
  document.querySelector('#modal').classList.add('on');
}
function closeM(){ document.querySelector('#modal').classList.remove('on'); }
function esc(s){ return String(s==null?'':s).replace(/[&<>\"']/g, m => ({\"&\":\"&\",\"<\":\"<\",\">\":\">\",\"\\\"\":\""\",\"'\":\"&#39;\"}[m])); }
// 绑定卡牌点击
document.querySelectorAll('.card').forEach((el, i) => {
  el.addEventListener('click', () => openM(i));
});
</script>"""


def main(argv: List[str]) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="卡牌渲染器（麦当劳品牌风）")
    ap.add_argument("ledger", help="账本 JSON 路径")
    ap.add_argument("--out", required=True, help="输出 HTML 路径")
    ap.add_argument("--last-draw", type=int, default=0, help="最近抽卡张数（渲染为「本次抽卡」）")
    ap.add_argument("--title", default="麦卡收藏家")
    ap.add_argument("--meta", default=None, help="元数据 JSON 路径（可选，含门店信息等）")
    args = ap.parse_args(argv)

    with open(args.ledger, "r", encoding="utf-8") as f:
        led = json.load(f)

    coll = led.get("collection", [])
    cards = [Card.from_dict(x) for x in coll]
    n = min(args.last_draw, len(cards))
    drawn = cards[-n:] if n else []

    dist: Dict[str, int] = {r: 0 for r in RARITIES}
    combo_count = 0
    for c in cards:
        dist[c.rarity] = dist.get(c.rarity, 0) + 1
        if getattr(c, "is_combo", False):
            combo_count += 1
    stats = {
        "collected": len(cards),
        "distribution": dist,
        "avg_calories": sum(c.calories for c in cards) / len(cards) if cards else 0,
        "avg_health_score": sum(c.health_score for c in cards) / len(cards) if cards else 0,
        "total_draws": led.get("total_draws", 0),
        "points": led.get("points", 0),
        "combo_count": combo_count,
    }

    meta = None
    if args.meta and os.path.exists(args.meta):
        with open(args.meta, "r", encoding="utf-8") as f:
            raw = json.load(f)
        meta = raw.get("meta") or raw.get("store") or {}

    out = render_page(drawn, coll, stats, args.out, args.title, meta)

    print(json.dumps({"success": True, "out": out, "cards": len(cards), "drawn": len(drawn)},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))