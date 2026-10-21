"""
app.py —— 麦卡收藏家后端（零依赖，仅标准库）

提供三个能力：
  1. 静态托管 docs/ 下的单文件网页
  2. POST /api/stores   —— 城市+地点 → 附近麦当劳门店（按距离排序）
  3. POST /api/order    —— 核价（step=quote）→ 用户确认 → 真实下单（step=confirm）

安全设计（重要）：
- MCD_MCP_TOKEN 只存在于服务端环境变量，绝不下发到浏览器。
- create-order 仅在 step=confirm 且带 quoteToken 时才执行，
  实现「先核价、用户过目、再下单」的强制二次确认。
- 报价用一次性 token 绑定（防止前端伪造价格直接下单）。

运行：
    PORT=8080 MCD_MCP_TOKEN=xxx python server/app.py
"""

import json
import os
import secrets
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcd_client import McdClient, McdError  # noqa: E402
from ip_locator import locate  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
# WEB_ROOT 兼容两种部署结构：
#   开发模式: app.py 在 server/ 下，docs 在 ../docs
#   部署包:   app.py 在 app-dist/ 根下，docs 在 ./docs
_candidates = [
    os.path.join(HERE, "docs"),
    os.path.join(HERE, "..", "docs"),
]
WEB_ROOT = next((p for p in _candidates if os.path.isdir(p)), _candidates[0])

PORT = int(os.environ.get("PORT", "8080"))

# 报价缓存：token -> {items, price, store, 过期时间}
_QUOTES = {}
_QUOTE_TTL = 15 * 60  # 15 分钟
_QUOTE_LOCK = threading.Lock()

# 极简限流：同一 IP 每分钟最多 30 次 API 调用
_RATE = {}
RATE_LIMIT = 30
RATE_WINDOW = 60

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}

_client_lock = threading.Lock()
_client = None


def get_client():
    """懒加载单例 MCP 客户端（复用 session）。"""
    global _client
    with _client_lock:
        if _client is None:
            _client = McdClient()
        return _client


def prune_quotes():
    now = time.time()
    with _QUOTE_LOCK:
        for k in [k for k, v in _QUOTES.items() if v["exp"] < now]:
            _QUOTES.pop(k, None)


def put_quote(items, price_info, store):
    token = uuid.uuid4().hex
    with _QUOTE_LOCK:
        _QUOTES[token] = {
            "items": items,
            "price": price_info,
            "store": store,
            "exp": time.time() + _QUOTE_TTL,
        }
    return token


def take_quote(token):
    """取出并作废（一次性使用，防止重放重复下单）。"""
    prune_quotes()
    with _QUOTE_LOCK:
        rec = _QUOTES.get(token)
        if rec:
            _QUOTES.pop(token, None)
        return rec


def norm_stores(data):
    """
    把 query-nearby-stores 返回整理成前端要的形状，按距离升序。
    distance 单位是米；MCP 不返回门店经纬度（实测为 0），故不做坐标计算。
    data 既可能是解包后的门店数组，也可能是残留的 {data:[...]} 信封。
    """
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        rows = data.get("data") if isinstance(data.get("data"), list) else None
        if rows is None and "storeCode" in data:
            rows = [data]
    else:
        rows = None
    out = []
    for r in (rows or []):
        try:
            dist = float(r.get("distance") or 0)
        except Exception:
            dist = 0.0
        st = r.get("businessStartTime")
        et = r.get("businessEndTime")
        open_text = "%s-%s" % (st, et) if (st and et) else (st or et or "")
        out.append({
            "storeCode": str(r.get("storeCode") or ""),
            "beCode": r.get("beCode") or "",
            "name": r.get("storeName") or "麦当劳",
            "address": r.get("address") or "",
            "distance": dist,
            "distanceText": _fmt_distance(dist),
            "open": open_text,
            "businessStatus": bool(r.get("businessStatus", True)),
            "reservation": bool(r.get("reservation", False)),
        })
    out.sort(key=lambda x: x["distance"])
    return out


def _fmt_distance(m):
    if m <= 0:
        return "距离未知"
    if m < 1000:
        return "%d m" % round(m)
    return "%.1f km" % (m / 1000.0)


class Handler(BaseHTTPRequestHandler):
    server_version = "McdGacha/1.0"

    # ---------- 基础工具 ----------

    def log_message(self, fmt, *args):
        sys.stderr.write("[web] %s\n" % (fmt % args))

    def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def _json(self, obj, code=200):
        self._send(code, obj)

    def _err(self, msg, code=400, **kw):
        d = {"success": False, "error": msg}
        d.update(kw)
        self._json(d, code)

    def _read_json(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except Exception:
            n = 0
        if n <= 0:
            return {}
        if n > 256 * 1024:
            raise ValueError("请求体过大")
        raw = self.rfile.read(n).decode("utf-8", "replace")
        try:
            return json.loads(raw or "{}")
        except Exception:
            raise ValueError("JSON 解析失败")

    def _rate_ok(self):
        ip = self.client_address[0] if self.client_address else "?"
        now = time.time()
        with _QUOTE_LOCK:
            arr = [t for t in _RATE.get(ip, []) if now - t < RATE_WINDOW]
            if len(arr) >= RATE_LIMIT:
                _RATE[ip] = arr
                return False
            arr.append(now)
            _RATE[ip] = arr
        return True

    def _client_ip(self):
        """
        取真实客户端 IP（处理反向代理）：
        X-Forwarded-For > X-Real-IP > 直接连接的 peer
        """
        xff = (self.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
        if xff:
            return xff
        xr = self.headers.get("X-Real-IP") or ""
        if xr.strip():
            return xr.strip()
        return self.client_address[0] if self.client_address else ""

    # ---------- 路由 ----------

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/health":
            configured = bool(os.environ.get("MCD_MCP_TOKEN"))
            return self._json({"success": True, "mcpConfigured": configured,
                                "ts": int(time.time())})
        if path == "/api/ip-locate":
            loc = locate(client_ip=self._client_ip())
            return self._json({"success": True, "location": loc})
        return self._serve_static(path)

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path not in ("/api/stores", "/api/order"):
            return self._err("未知接口", 404)
        if not self._rate_ok():
            return self._err("请求过于频繁，请稍后再试", 429)
        try:
            body = self._read_json()
        except ValueError as e:
            return self._err(str(e))
        try:
            if path == "/api/stores":
                return self._api_stores(body)
            return self._api_order(body)
        except McdError as e:
            return self._err(str(e), 502)
        except Exception as e:  # noqa: BLE001
            self.log_message("unhandled: %r", e)
            return self._err("服务器内部错误", 500)

    # ---------- API: 附近门店 ----------

    def _api_stores(self, body):
        city = (body.get("city") or "").strip()
        keyword = (body.get("keyword") or "").strip()
        be_type = int(body.get("beType") or 1)
        if be_type not in (1, 5):
            return self._err("beType 只能是 1（到店自取）或 5（得来速）")
        # 缺 city / keyword 时，IP 定位兜底
        auto_city = ""
        if not city or not keyword:
            loc = locate(client_ip=self._client_ip())
            auto_city = loc.get("city") or ""
            if not city:
                city = auto_city
            if not keyword:
                # 用城市名 + "站"做兜底关键词，覆盖大多数出行场景
                keyword = city
        if not city or not keyword:
            return self._err("请填写城市和地点，例如「北京」「朝阳站」", 400,
                             hint={"city": city, "keyword": keyword})
        data = get_client().nearby_stores(city, keyword, be_type)
        stores = norm_stores(data)
        if not stores:
            # 兜底失败：返回城市但列表空，让前端提示用户手动改 keyword
            return self._err("附近没搜到门店，换个地点关键词试试", 404,
                             stores=[], city=city, keyword=keyword,
                             autoCity=auto_city)
        return self._json({"success": True, "stores": stores,
                            "beType": be_type, "city": city, "keyword": keyword,
                            "autoCity": auto_city})

    # ---------- API: 核价 / 下单 ----------

    def _api_order(self, body):
        step = (body.get("step") or "quote").strip()

        # ---- 下单 ----
        if step == "confirm":
            token = (body.get("quoteToken") or "").strip()
            if not token:
                return self._err("缺少 quoteToken，请先核价")
            rec = take_quote(token)
            if not rec:
                return self._err("报价已失效或已使用，请重新核价", 409)
            try:
                res = get_client().create_order(
                    store_code=rec["store"]["storeCode"],
                    be_type=int(rec["store"].get("beType") or 1),
                    items=rec["items"],
                    be_code=rec["store"].get("beCode") or None,
                    take_way_code=(rec["price"].get("takeWayCode")
                                   if isinstance(rec["price"], dict) else None),
                    remark=(body.get("remark") or None),
                )
            except McdError as e:
                # 下单失败时把报价还回去，允许用户重试
                put_quote(rec["items"], rec["price"], rec["store"])
                return self._err(str(e), 502)
            return self._json({"success": True, "step": "ordered",
                                "order": _norm_order(res)})

        if step != "quote":
            return self._err("step 只能是 quote 或 confirm")

        # ---- 核价 ----
        store = body.get("store") or {}
        store_code = (store.get("storeCode") or "").strip()
        if not store_code:
            return self._err("请先选择门店")
        be_type = int(body.get("beType") or store.get("beType") or 1)
        items = body.get("items") or []
        if not isinstance(items, list) or not items:
            return self._err("请选择要购买的餐品")

        data = get_client().calculate_price(
            store_code=store_code, be_type=be_type, items=items,
            be_code=store.get("beCode") or None,
        )
        # 价格单位是「分」→ 转「元」给前端展示
        fen = lambda v: (round(v / 100.0, 2) if isinstance(v, (int, float)) else v)
        price_view = {
            "price": fen(data.get("price")),
            "discount": fen(data.get("discount")),
            "deliveryPrice": fen(data.get("deliveryPrice")),
            "packingPrice": fen(data.get("packingPrice")),
            "originalPrice": fen(data.get("originalPrice")),
            "takeWayList": data.get("takeWayList") or [],
            "productList": data.get("productList") or [],
        }
        # 默认取餐方式：优先「到店自取」
        tw = price_view["takeWayList"]
        default_tw = ""
        if tw:
            pick = next((t for t in tw if "自取" in str(t.get("title", ""))
                         or "到店" in str(t.get("title", ""))), tw[0])
            default_tw = pick.get("code")

        store_info = dict(store)
        store_info["beType"] = be_type
        store_info["takeWayCode"] = default_tw
        # 把 takeWayList 一并存进报价，下单时回传
        store_info["takeWayList"] = tw
        token = put_quote(items, {"view": price_view, "raw": data,
                                   "takeWayCode": default_tw}, store_info)
        return self._json({
            "success": True, "step": "quoted",
            "price": price_view,
            "quoteToken": token,
            "store": store_info,
            # 明确告知前端：这是报价，下单需用户确认
            "needsConfirm": True,
            "expiresIn": _QUOTE_TTL,
        })

    # ---------- 静态文件 ----------

    def _serve_static(self, path):
        rel = path.lstrip("/") or "index.html"
        # 防目录穿越
        target = os.path.normpath(os.path.join(WEB_ROOT, rel))
        if not target.startswith(os.path.normpath(WEB_ROOT)):
            return self._err("forbidden", 403)
        if os.path.isdir(target):
            target = os.path.join(target, "index.html")
        if not os.path.exists(target):
            # 单页应用回退
            target = os.path.join(WEB_ROOT, "index.html")
            if not os.path.exists(target):
                return self._err("页面不存在", 404)
        ext = os.path.splitext(target)[1].lower()
        try:
            with open(target, "rb") as f:
                data = f.read()
        except Exception:
            return self._err("读取失败", 500)
        ctype = MIME.get(ext, "application/octet-stream")
        cache = "public, max-age=300" if ext in (".jpg", ".jpeg", ".png",
                                                 ".gif", ".webp") else "no-cache"
        self._send(200, data, ctype, {"Cache-Control": cache})


def _norm_order(res):
    """抽取下单结果里用户关心的字段。"""
    d = res if isinstance(res, dict) else {}
    data = d.get("data") if isinstance(d.get("data"), dict) else d
    return {
        "orderId": data.get("orderId") or data.get("orderNo") or "",
        "payId": data.get("payId") or "",
        "payUrl": data.get("payH5Url") or data.get("payUrl") or "",
        "status": data.get("status") or "",
        "raw": d,
    }


def main():
    web = os.path.normpath(WEB_ROOT)
    print("麦卡收藏家 · 后端启动")
    print("  静态目录 : %s" % web)
    print("  监听     : 0.0.0.0:%d" % PORT)
    print("  MCP Token: %s" % ("已配置" if os.environ.get("MCD_MCP_TOKEN")
                             else "未配置（门店查询/下单将返回错误）"))
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    srv.daemon_threads = True
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()