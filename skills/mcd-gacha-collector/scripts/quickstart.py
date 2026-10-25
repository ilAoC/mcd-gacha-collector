#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
quickstart.py —— 麦卡收藏家「一条命令」全链路

设计目标：**不让 AI 做任何数据转录**。
以前要 AI 手工把 list-nutrition-foods 的 160 行文本转成 JSON，
再拼 prices.json，最后才跑 gacha.py —— 这一步极慢。

现在脚本自己直连麦当劳 MCP：
  定位门店 → 拉实时菜单 → 拉营养库（带缓存）→ 建卡池 → 抽卡 → 核价 → 下单

Token 自动发现顺序：
  1) 环境变量 MCD_MCP_TOKEN
  2) ~/.workbuddy/mcp.json 里 mcd-mcp 的 headers.Authorization

用法：
  # 门店列表（阶段 B 用）
  python quickstart.py stores --city 沈阳 --keyword 国际软件园

  # 抽卡（一条命令搞定取数+建池+抽卡）
  python quickstart.py draw --store 3230221 --count 10 --budget 50

  # 抽卡并把结果打印成可直接转述的 Markdown
  python quickstart.py draw --store 3230221 --count 3 --budget 50 --speak

  # 核价（阶段下单用）
  python quickstart.py quote --store 3230221 --code 9900008751 --name 可乐

  # 下单（必须先 quote 拿到 quoteToken）
  python quickstart.py order --store 3230221 --code 9900008751 --name 可乐 \
      --take-way eat-in

  # 收藏册统计
  python quickstart.py collection --ledger tmp/ledger.json
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from mcp_client import McdClient, McdError  # noqa: E402
from gacha import build_cards  # noqa: E402
from category_map import category_of  # noqa: E402

CACHE_DIR = HERE.parent / "cache"
NUT_CACHE = CACHE_DIR / "nutrition.json"
NUT_TTL = 12 * 3600          # 营养库全平台固定，12 小时足够
MENU_CACHE = CACHE_DIR / "menus"
MENU_TTL = 600               # 门店菜单随时段变，10 分钟


# ---------------------------------------------------------------- 工具

def _json_print(obj, pretty=True):
    print(json.dumps(obj, ensure_ascii=False, indent=2 if pretty else None))


def _client():
    try:
        return McdClient()
    except McdError as e:
        print("❌ " + str(e), file=sys.stderr)
        print("   提示：Token 也可能已存在 ~/.workbuddy/mcp.json 的 mcd-mcp 配置里，"
              "确认其中的 headers.Authorization 是最新的。", file=sys.stderr)
        raise SystemExit(2)


def _norm_nutrition(rows):
    """MCP 营养行 → gacha.py 需要的字段名。"""
    out = []
    for r in rows:
        name = (r.get("productName") or "").strip()
        if not name:
            continue
        def num(k):
            v = r.get(k)
            try:
                return float(v) if v is not None else 0.0
            except (TypeError, ValueError):
                return 0.0
        out.append({
            "productName": name,
            "energyKj": num("energyKj"),
            "energyKcal": num("energyKcal"),
            "protein": num("protein"),
            "fat": num("fat"),
            "carbohydrate": num("carbohydrate"),
            "sodium": num("sodium"),
            "calcium": num("calcium"),
        })
    return out


# ---------------------------------------------------------------- 名称归一化
#
# 门店菜单与营养库用词不一致，是交集变小的主因：
#   菜单「可乐」          ↔ 营养库「可乐中杯 / 可乐小杯 / 可乐大杯」
#   菜单「100% 苹果汁(盒装)」↔ 营养库「100%苹果汁」
#   菜单「麦辣鸡翅」       ↔ 营养库「麦辣鸡翅-2块」
# 因此按三级规则匹配：精确 → 去规格后缀 → 去套餐后缀。

# 规格类后缀（同一款的不同容量，去掉后视为同款，取中杯优先）
_SIZE_SUFFIX = ["中杯", "大杯", "小杯", "中碗", "大碗", "小碗", "盒装", "杯装"]
# 套餐类后缀（去掉后指向主单品）
_SET_SUFFIX = [
    "三件套", "四件套", "五件套", "二件套", "单件套", "六件套",
    "超值四件套随心选", "三件套随心选", "四件套随心选",
    "套餐", "超值套餐", "精选套餐", "单人餐", "双人餐", "开心乐园餐",
    "开心亲子餐", "亲子餐", "组合", "双拼", "全家餐", "分享餐",
    "精选单人餐", "精选", "超值", "随心", "随心选",
]
# 括号内容（(盒装) 之类）
_PAREN = "（）()【】[]"


def _strip_paren(s):
    for ch in _PAREN:
        while ch in s:
            i = s.index(ch)
            j = s.find(ch, i + 1)
            if j == -1:
                s = s[:i] + s[i + 1:]
            else:
                s = s[:i] + s[j + 1:]
    return s.strip()


def _strip_size(name):
    for suf in _SIZE_SUFFIX:
        if name.endswith(suf):
            return name[:-len(suf)]
    return name


def _strip_set(name):
    changed = True
    while changed:
        changed = False
        for suf in _SET_SUFFIX:
            if name.endswith(suf) and len(name) > len(suf) + 1:
                name = name[:-len(suf)]
                changed = True
    return name


def _match_map(menu_names, nutrition_names):
    """
    建立「菜单名 → 营养库名」映射。
    返回 (mapping, unmatched_menu, unmatched_nutrition)
    """
    nut_set = set(nutrition_names)
    # 营养库索引：去括号 / 去规格 / 去套餐
    idx_size, idx_set = {}, {}
    for n in nut_set:
        base = _strip_paren(n)
        idx_size.setdefault(base, n)
        idx_size.setdefault(_strip_size(base), n)
        idx_set.setdefault(_strip_set(base), n)
        idx_set.setdefault(_strip_set(_strip_size(base)), n)

    mapping, unmatched = {}, []
    for m in menu_names:
        if m in nut_set:
            mapping[m] = m
            continue
        base = _strip_paren(m)
        cand = idx_size.get(base) or idx_size.get(_strip_size(base))
        if not cand:
            cand = idx_set.get(_strip_set(base)) or idx_set.get(_strip_set(_strip_size(base)))
        if cand:
            mapping[m] = cand
        else:
            unmatched.append(m)
    return mapping, unmatched, sorted(nut_set - set(mapping.values()))



def fetch_nutrition(cli, use_cache=True):
    """营养库全量，带本地缓存（内容全平台固定，缓存可省一次网络往返）。"""
    if use_cache and NUT_CACHE.exists():
        age = time.time() - NUT_CACHE.stat().st_mtime
        if age < NUT_TTL:
            try:
                data = json.loads(NUT_CACHE.read_text(encoding="utf-8"))
                data["_cached"] = True
                return data["items"]
            except Exception:
                pass
    rows = cli.list_nutrition_foods()
    items = _norm_nutrition(rows)
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        NUT_CACHE.write_text(
            json.dumps({"fetchedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "items": items}, ensure_ascii=False, indent=1),
            encoding="utf-8")
    except Exception:
        pass
    return items


def fetch_menu(cli, store_code, be_type=1, be_code=None, use_cache=True):
    """门店实时菜单 + 价格（价格直接从 data.meals.currentPrice 取）。"""
    key = f"{store_code}_{be_type}_{be_code or 'na'}.json"
    path = MENU_CACHE / key
    if use_cache and path.exists():
        if time.time() - path.stat().st_mtime < MENU_TTL:
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                pass
    res = cli.meals(store_code, be_type=be_type, be_code=be_code)
    data = res.get("data") if isinstance(res, dict) else None
    if not isinstance(data, dict):
        data = res if isinstance(res, dict) else {}
    meals = data.get("meals") or {}
    prices, codes = {}, {}
    for code, m in meals.items():
        if not isinstance(m, dict):
            continue
        name = (m.get("name") or "").strip()
        if not name:
            continue
        try:
            p = float(m.get("currentPrice"))
        except (TypeError, ValueError):
            continue
        prices[name] = p
        codes[name] = code
    payload = {"prices": prices, "codes": codes,
               "fetchedAt": time.strftime("%Y-%m-%d %H:%M:%S")}
    try:
        MENU_CACHE.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return payload


def build_pool(cli, store_code, be_type=1, be_code=None):
    """拉数据 → 名称归一化求交集 → 建卡池。返回 (rows, prices, codes, meta)。"""
    nutrition = fetch_nutrition(cli)
    menu = fetch_menu(cli, store_code, be_type, be_code)
    prices, codes = menu["prices"], menu["codes"]

    nut_by_name = {r["productName"]: r for r in nutrition}
    mapping, unmatched, _ = _match_map(list(prices.keys()),
                                       [r["productName"] for r in nutrition])

    # 归一化后：用营养库的标准名做卡面名（更简洁），价格仍取门店实价
    rows, pool_prices = [], {}
    for menu_name, nut_name in mapping.items():
        src = dict(nut_by_name[nut_name])
        src["productName"] = menu_name          # 卡面显示门店实际叫法
        rows.append(src)
        pool_prices[menu_name] = prices[menu_name]

    meta = {
        "nutritionTotal": len(nutrition),
        "menuTotal": len(prices),
        "poolTotal": len(rows),
        "unmatched": len(unmatched),
        "unmatchedSample": unmatched[:8],
    }
    return rows, pool_prices, codes, meta


# ---------------------------------------------------------------- 命令

def cmd_stores(args):
    cli = _client()
    res = cli.nearby_stores(args.city, args.keyword, be_type=args.be_type)
    data = res.get("data") if isinstance(res, dict) else res
    stores = data if isinstance(data, list) else (data or {}).get("stores") or []
    out = []
    for s in stores:
        if not isinstance(s, dict):
            continue
        out.append({
            "storeCode": s.get("storeCode") or s.get("store_code"),
            "name": s.get("storeName") or s.get("name"),
            "address": s.get("address"),
            "distance": s.get("distance"),
            "beCode": s.get("beCode") or s.get("be_code") or "",
            "businessStatus": s.get("businessStatus", True),
        })
    _json_print(out)


def cmd_draw(args):
    cli = _client()
    rows, prices, codes, meta = build_pool(cli, args.store, args.be_type, args.be_code)
    if not rows:
        print("❌ 卡池为空：该门店在售餐品与营养库没有交集，"
              "换个时段或换一家门店。", file=sys.stderr)
        raise SystemExit(1)
    cards = build_cards(rows, prices, None,
                      category_map={r["productName"]: category_of(r["productName"])
                                    for r in rows})
    budget = args.budget
    pool = [c for c in cards if budget is None or c.price <= budget]
    if not pool:
        print(f"❌ 预算 {budget} 元内没有可抽的卡。", file=sys.stderr)
        raise SystemExit(1)

    # 加权抽卡（与网页同算法：SSR 5% / UR 20% / R 75%）
    weights = {"SSR": 5, "UR": 20, "R": 75}
    import random
    buckets = {r: [c for c in pool if c.rarity == r] for r in weights}
    drawn = []
    for _ in range(args.count):
        avail = [r for r in weights if buckets[r]]
        if not avail:
            break
        r = random.choices(avail, weights=[weights[x] for x in avail])[0]
        c = random.choice(buckets[r])
        buckets[r].remove(c)
        drawn.append(c)

    result = {
        "success": True,
        "meta": meta,
        "drawn": [{
            "name": c.name, "rarity": c.rarity, "price": c.price,
            "calories": c.calories, "health_score": c.health_score,
            "category": getattr(c, "category", ""),
            "product_code": codes.get(c.name, ""),
            "energy_tag": getattr(c, "energy_tag", ""),
            "protein_tag": getattr(c, "protein_tag", ""),
            "fat_tag": getattr(c, "fat_tag", ""),
            "sodium_tag": getattr(c, "sodium_tag", ""),
        } for c in drawn],
    }
    if args.speak:
        print(_speak_md(result, budget))
    else:
        _json_print(result)
    return result


def _speak_md(result, budget):
    """把抽卡结果渲染成可直接转述给用户的 Markdown。"""
    d = result["drawn"]
    m = result["meta"]
    lines = []
    lines.append(f"🎴 **抽到 {len(d)} 张：**\n")
    for c in d:
        mark = {"SSR": "✨✨", "UR": "💎", "R": "🎴"}.get(c["rarity"], "🎴")
        cat = f" · {c['category']}" if c.get("category") else ""
        lines.append(
            f"{mark} **{c['rarity']}**　{c['name']}{cat}\n"
            f"💰 ¥{c['price']:.2f} · 🔥 {c['calories']:.0f} kcal"
            f"（占日 {c['calories']/20:.0f}%）\n"
            f"💚 健康度 {c['health_score']:.0f}"
            + (f" · 能量{c['energy_tag']}" if c.get("energy_tag") else "") + "\n")
    lines.append("━━━━━━━━━━━━━━━━━━━━━")
    lines.append("📦 **你的选择：要买哪一张？**\n")
    lines.append("回我卡名就行，比如「买" + (d[0]["name"] if d else "可乐") + "」\n"
                 "也可以说「都不买」或「再来几张」")
    lines.append(f"\n> 卡池 {m['poolTotal']} 张"
                 + (f"（预算 ≤{budget:.0f} 元）" if budget else "")
                 + f" · 营养库 {m['nutritionTotal']} 项 × 门店在售 {m['menuTotal']} 项取交集")
    return "\n".join(lines)


def _unwrap(res):
    """MCP client.call() 已解包 data，这里兼容两种形态。"""
    if isinstance(res, dict):
        d = res.get("data")
        if isinstance(d, dict) and d:
            return d
        if isinstance(d, list):
            return {"items": d}
        return res
    return res or {}


def cmd_quote(args):
    """
    核价。输出总价（元）、商品明细、takeWayList（取餐方式）。
    takeWayCode 是下单必填项，必须从这里取。
    """
    cli = _client()
    res = cli.calculate_price(
        args.store, args.be_type,
        [{"productCode": args.code, "quantity": args.qty}],
        be_code=args.be_code, order_type=1)
    d = _unwrap(res)
    if not d:
        print("❌ 核价返回为空，该餐品可能已下架或门店不支持。", file=sys.stderr)
        raise SystemExit(1)

    def yuan(v):
        try:
            return round(float(v) / 100.0, 2)
        except (TypeError, ValueError):
            return None

    total = yuan(d.get("price"))
    out = {
        "success": True,
        "item": {"productCode": args.code, "name": args.name or "", "quantity": args.qty},
        "price": {
            "total": total,
            "originalTotal": yuan(d.get("originalPrice")),
            "productTotal": yuan(d.get("productPrice")),
            "discount": yuan(d.get("discount")),
            "deliveryFee": yuan(d.get("deliveryPrice")),
            "tablewareFee": yuan(d.get("tablewarePrice")),
        },
        "products": [{
            "name": p.get("productName"),
            "quantity": p.get("quantity"),
            "subtotal": yuan(p.get("subtotal")),
        } for p in (d.get("productList") or []) if isinstance(p, dict)],
        "takeWayList": d.get("takeWayList") or [],
        "needsConfirm": True,
    }
    _json_print(out)
    return out


def cmd_order(args):
    """
    下单。**必须**在用户明确二次确认之后调用。
    --take-way 取自 quote 的 takeWayList[].code。
    """
    cli = _client()
    res = cli.create_order(
        args.store, args.be_type,
        [{"productCode": args.code, "quantity": args.qty}],
        be_code=args.be_code, take_way_code=args.take_way,
        order_type=1, remark=args.remark)
    d = _unwrap(res)
    det = d.get("orderDetail") if isinstance(d.get("orderDetail"), dict) else d
    order = {
        "orderId": d.get("orderId") or det.get("orderId") or "",
        "payUrl": d.get("payH5Url") or det.get("payH5Url") or "",
        "payId": d.get("payId") or det.get("payId") or "",
        "status": det.get("orderStatus") or det.get("status") or "",
        "storeName": det.get("storeName") or "",
        "storeAddress": det.get("storeAddress") or "",
        "takeWay": det.get("takeWay") or "",
        "totalAmount": det.get("realTotalAmount") or det.get("totalAmount") or "",
        "expirePayTime": det.get("expirePayTime") or "",
        "createTime": det.get("createTime") or "",
        "products": [{
            "name": p.get("productName"), "quantity": p.get("quantity"),
            "price": p.get("price"),
        } for p in (det.get("orderProductList") or []) if isinstance(p, dict)],
    }
    _json_print({"success": True, "order": order})
    return order


def cmd_cancel(args):
    """取消未支付订单。"""
    cli = _client()
    res = cli.cancel_order(args.order_id, args.reason)
    _json_print({"success": True, "result": _unwrap(res)})


def cmd_collection(args):
    cli = _client()
    res = cli.call("query-meal-assistance", {}) if False else {}
    _json_print({"note": "收藏册统计请用 gacha.py --collection"})


# ---------------------------------------------------------------- 入口

def main(argv=None):
    ap = argparse.ArgumentParser(
        description="麦卡收藏家 · 一键全链路（定位/抽卡/核价/下单）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("stores", help="查询附近门店")
    p.add_argument("--city", required=True)
    p.add_argument("--keyword", required=True)
    p.add_argument("--be-type", type=int, default=1, choices=[1, 5])
    p.set_defaults(func=cmd_stores)

    p = sub.add_parser("draw", help="抽卡（含取数与建池）")
    p.add_argument("--store", required=True, help="门店编号 storeCode")
    p.add_argument("--count", type=int, default=1)
    p.add_argument("--budget", type=float, default=None)
    p.add_argument("--be-type", type=int, default=1, choices=[1, 5])
    p.add_argument("--be-code", default=None)
    p.add_argument("--speak", action="store_true", help="输出可直接转述的 Markdown")
    p.set_defaults(func=cmd_draw)

    p = sub.add_parser("quote", help="核价")
    p.add_argument("--store", required=True)
    p.add_argument("--code", required=True, help="餐品编码 productCode")
    p.add_argument("--name", default="", help="餐品名（仅用于日志）")
    p.add_argument("--qty", type=int, default=1)
    p.add_argument("--be-type", type=int, default=1, choices=[1, 5])
    p.add_argument("--be-code", default=None)
    p.set_defaults(func=cmd_quote)

    p = sub.add_parser("order", help="下单")
    p.add_argument("--store", required=True)
    p.add_argument("--code", required=True)
    p.add_argument("--name", default="")
    p.add_argument("--qty", type=int, default=1)
    p.add_argument("--take-way", required=True,
                   help="取餐方式 code，来自 quote 返回的 takeWayList")
    p.add_argument("--be-type", type=int, default=1, choices=[1, 5])
    p.add_argument("--be-code", default=None)
    p.add_argument("--remark", default=None)
    p.set_defaults(func=cmd_order)

    p = sub.add_parser("cancel", help="取消未支付订单")
    p.add_argument("--order-id", required=True)
    p.add_argument("--reason", type=int, default=3)
    p.set_defaults(func=cmd_cancel)

    args = ap.parse_args(argv)
    try:
        args.func(args)
    except McdError as e:
        print(f"❌ MCP 调用失败：{e}", file=sys.stderr)
        raise SystemExit(3)
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        print(f"❌ 未预期错误：{e!r}", file=sys.stderr)
        raise SystemExit(4)


if __name__ == "__main__":
    main()
