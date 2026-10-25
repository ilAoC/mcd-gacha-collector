"""
mcd_client.py —— 麦当劳 MCP 客户端（零依赖，仅用标准库）

职责：封装 Streamable HTTP JSON-RPC 握手与 tools/call，
      让后端能安全持有 MCD_MCP_TOKEN 而不暴露给浏览器。

用法：
    from mcd_client import McdClient
    c = McdClient()                 # 从环境变量 MCD_MCP_TOKEN 读
    stores = c.nearby_stores("北京", "朝阳", be_type=1)
    price = c.calculate_price(store_code=..., be_type=1, items=[...])
    order = c.create_order(...)

安全约定：
- Token 只从环境变量读取，绝不写进代码或前端。
- 会话 id 自动管理（Streamable HTTP 要求 initialize 后带 Mcp-Session-Id）。
"""

import json
import os
import threading
import urllib.error
import urllib.request

DEFAULT_URL = "https://mcp.mcd.cn"
PROTOCOL_VERSION = "2024-11-05"
TIMEOUT = 40


class McdError(Exception):
    """MCP 调用失败（网络/鉴权/协议/工具错误）。"""

    def __init__(self, message, code=None, detail=None):
        super().__init__(message)
        self.code = code
        self.detail = detail


def _discover_token():
    """
    自动发现 MCP Token，省去用户额外配环境变量：
      1) 环境变量 MCD_MCP_TOKEN
      2) ~/.workbuddy/mcp.json 里 mcd-mcp 的 headers.Authorization
    """
    t = (os.environ.get("MCD_MCP_TOKEN") or "").strip()
    if t:
        return t
    try:
        import json as _json
        from pathlib import Path as _Path
        cfg = _Path.home() / ".workbuddy" / "mcp.json"
        if cfg.exists():
            data = _json.loads(cfg.read_text(encoding="utf-8"))
            srv = (data.get("mcpServers") or {}).get("mcd-mcp") or {}
            auth = ((srv.get("headers") or {}).get("Authorization") or "").strip()
            if auth.lower().startswith("bearer "):
                return auth[7:].strip()
            if auth:
                return auth
    except Exception:
        pass
    return ""


class McdClient:
    def __init__(self, token=None, url=None):
        self.token = (token or _discover_token() or "").strip()
        self.url = (url or os.environ.get("MCD_MCP_URL") or DEFAULT_URL).strip()
        if not self.token:
            raise McdError(
                "未配置 MCD_MCP_TOKEN。请到 https://open.mcd.cn/mcp 扫码登录 → "
                "控制台 → 激活 → 复制 MCP Token，然后设为环境变量。"
            )
        self._sid = None
        self._rid = 0
        self._lock = threading.Lock()

    # ---------- 底层传输 ----------

    def _next_id(self):
        with self._lock:
            self._rid += 1
            return self._rid

    def _headers(self):
        h = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": "Bearer " + self.token,
        }
        if self._sid:
            h["Mcp-Session-Id"] = self._sid
        return h

    @staticmethod
    def _parse_body(body):
        """兼容 application/json 与 text/event-stream 两种响应。"""
        body = (body or "").strip()
        if not body:
            return None
        if body[0] in "{[":
            try:
                return json.loads(body)
            except Exception:
                pass
        # SSE：取最后一条 data:
        payload = None
        for line in body.splitlines():
            if line.startswith("data:"):
                chunk = line[5:].strip()
                if chunk:
                    try:
                        payload = json.loads(chunk)
                    except Exception:
                        continue
        return payload

    def _post(self, payload, expect_reply=True):
        req = urllib.request.Request(
            self.url,
            data=json.dumps(payload).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                sid = resp.headers.get("Mcp-Session-Id") or resp.headers.get("mcp-session-id")
                if sid:
                    self._sid = sid
                body = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            hint = ""
            if e.code == 401:
                hint = "（Token 无效或已过期，请重新到开放平台复制）"
            elif e.code == 429:
                hint = "（触发限流，每 Token 600 次/分钟）"
            raise McdError("MCP HTTP %s %s%s" % (e.code, e.reason, hint), code=e.code)
        except Exception as e:
            raise McdError("MCP 网络错误：%s" % e)

        if not expect_reply:
            return None
        data = self._parse_body(body)
        if data is None:
            raise McdError("MCP 返回空响应")
        if isinstance(data, dict) and data.get("error"):
            err = data["error"]
            raise McdError(
                "MCP 报错：%s" % (err.get("message") or err),
                code=err.get("code"),
                detail=err,
            )
        return data

    # ---------- MCP 协议层 ----------

    def ensure_session(self):
        if self._sid:
            return
        self._post({
            "jsonrpc": "2.0", "id": self._next_id(), "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "mcd-gacha-backend", "version": "1.0.0"},
            },
        })
        # 通知类消息无 id，不等结果
        try:
            self._post({"jsonrpc": "2.0", "method": "notifications/initialized"},
                       expect_reply=False)
        except McdError:
            pass

    def call(self, tool, args=None, retry_auth=True):
        """调用一个 MCP tool，返回解析后的业务 JSON（而不是原始信封）。"""
        self.ensure_session()
        try:
            data = self._post({
                "jsonrpc": "2.0", "id": self._next_id(), "method": "tools/call",
                "params": {"name": tool, "arguments": args or {}},
            })
        except McdError as e:
            # 会话过期：清掉 session 重试一次
            if retry_auth and e.code in (400, 404, 401):
                self._sid = None
                return self.call(tool, args, retry_auth=False)
            raise

        result = (data or {}).get("result") or {}
        if result.get("isError"):
            raise McdError("工具 %s 执行失败：%s" % (tool, _text_of(result)))
        return _extract_json(result)

    # ---------- 业务封装 ----------

    def nearby_stores(self, city, keyword, be_type=1):
        """按城市+地点查附近门店。be_type: 1=到店自取, 5=得来速。"""
        if not city or not keyword:
            raise McdError("city 与 keyword 必填")
        return self.call("query-nearby-stores", {
            "searchType": 2,
            "city": str(city).strip(),
            "keyword": str(keyword).strip(),
            "beType": int(be_type),
        })

    def list_nutrition_foods(self):
        """
        拉取全平台餐品营养数据（约 160 项）。
        平台 data 是 CSV 字符串（list-nutrition-foods 专用形态）。
        返回 [{productName, energyKcal, protein, fat, carbohydrate, sodium, calcium, ...}]
        """
        raw = self.call("list-nutrition-foods", {})
        if isinstance(raw, str):
            return parse_nutrition_csv(raw)
        if isinstance(raw, list):
            return raw
        if isinstance(raw, dict):
            for k in ("items", "data", "rows"):
                v = raw.get(k)
                if isinstance(v, str):
                    return parse_nutrition_csv(v)
                if isinstance(v, list):
                    return v
        return []

    def meals(self, store_code, be_type=1, be_code=None, order_type=1):
        """查门店实时在售菜单与价格。order_type: 1=到店, 2=外送（必填）。"""
        args = {
            "storeCode": str(store_code),
            "beType": int(be_type),
            "orderType": int(order_type),
        }
        if be_code:
            args["beCode"] = str(be_code)
        return self.call("query-meals", args)

    def calculate_price(self, store_code, be_type, items, be_code=None,
                        order_type=1):
        """
        核价（cart/quote）。必填 storeCode / beCode / orderType / beType / items。
        order_type: 1=到店（含自取+得来速），2=外送。
        返回 data 含：价格（单位「分」）、productList、takeWayList(取餐方式) 等。
        """
        args = {
            "storeCode": str(store_code),
            "beType": int(be_type),
            "orderType": int(order_type),
            "items": items,
        }
        if be_code:
            args["beCode"] = str(be_code)
        return self.call("calculate-price", args)

    def create_order(self, store_code, be_type, items, be_code=None,
                     take_way_code=None, order_type=1, remark=None):
        """
        真实下单。仅在用户明确二次确认后调用。
        必填 storeCode / beCode / takeWayCode(来自核价返回的 takeWayList) / beType / items。
        返回 data 含 orderId / payH5Url。
        """
        args = {
            "storeCode": str(store_code),
            "beType": int(be_type),
            "items": items,
        }
        if be_code:
            args["beCode"] = str(be_code)
        if take_way_code:
            args["takeWayCode"] = str(take_way_code)
        if order_type:
            args["orderType"] = int(order_type)
        if remark:
            args["remark"] = str(remark)[:50]
        return self.call("create-order", args)

    def cancel_order(self, order_id, cancel_reason_code=3):
        return self.call("cancel-order", {
            "orderId": str(order_id),
            "cancelReasonCode": int(cancel_reason_code),
        })


# ---------- 响应解析助手 ----------

def _text_of(result):
    """取 tool 结果里的文本内容（MCP 标准 content 数组）。"""
    parts = []
    for c in (result.get("content") or []):
        if c.get("type") == "text":
            parts.append(c.get("text") or "")
    return "\n".join(parts)


def _extract_balanced_json(s):
    """从字符串中截取第一个配平的 JSON 对象（处理 Markdown 代码块/说明文字）。"""
    start = s.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                cand = s[start:i + 1]
                try:
                    return json.loads(cand)
                except Exception:
                    return None
    return None


def _extract_json(result):
    """
    麦当劳 MCP 返回两种结构：

    1) ``structuredContent`` 字典：
         {success, code, message, datetime, traceId, data}
       其中 data 可能是 dict / list / str（list-nutrition-foods 是 CSV 字符串）。

    2) ``content[].text`` 字符串：
         「Markdown 字段说明 + ## Original Response + JSON 代码块」
       其中 JSON 也可能自带 ``{success, code, message, data}`` 信封。

    本函数统一解信封：成功返回 ``data``（可能再嵌套一层）；
    ``list-nutrition-foods`` 的 CSV 字符串由 ``parse_nutrition_csv`` 单独处理。
    """
    # === 路径 1：structuredContent ===
    sc = result.get("structuredContent")
    if isinstance(sc, dict) and sc:
        obj = sc
    else:
        obj = None

    # === 路径 2：从 content 文本里抽 JSON ===
    if obj is None:
        text = _text_of(result)
        if not text.strip():
            return {}
        idx = text.find("Original Response")
        if idx != -1:
            obj = _extract_balanced_json(text[idx:])
        if obj is None:
            obj = _extract_balanced_json(text)
        if obj is None:
            return {"_raw": text}

    # === 统一解信封 ===
    if isinstance(obj, dict) and ("code" in obj or "success" in obj):
        ok_flag = obj.get("success")
        code = obj.get("code")
        if ok_flag is False or (code is not None and code != 200):
            raise McdError(
                "MCP 工具错误：%s" % (obj.get("message") or "未知错误"),
                code=code,
            )
        # 成功：返回 data（dict / list / str 皆可）
        return obj.get("data", obj)
    return obj


def parse_nutrition_csv(csv_text):
    """
    ``list-nutrition-foods`` 的 data 是 CSV 字符串：

        [N]{col1,col2,...}:
          name,desc,kj,kcal,protein,fat,carb,sodium,calcium
          name2,desc2,...

    返回 [{productName, nutritionDescription, energyKj, energyKcal,
           protein, fat, carbohydrate, sodium, calcium}, ...]
    """
    if not isinstance(csv_text, str) or not csv_text.strip():
        return []
    s = csv_text.strip()
    # 解析字段名：在第一个 `{` 与 `}` 内，逗号分隔
    lb = s.find("{")
    rb = s.find("}", lb) if lb != -1 else -1
    if lb == -1 or rb == -1:
        return []
    header = [c.strip() for c in s[lb + 1:rb].split(",")]
    body = s[rb + 1:]
    # 解析 [N] 计数（仅校验，不强制）
    # 每行以两个空格开头（或任意前空白）
    items = []
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line or "," not in line:
            continue
        # 空字段保留为 None
        vals = [v.strip() if v.strip().lower() != "null" else None
                for v in line.split(",")]
        # 长度对齐
        if len(vals) < len(header):
            vals += [None] * (len(header) - len(vals))
        elif len(vals) > len(header):
            vals = vals[:len(header)]
        item = {}
        for k, v in zip(header, vals):
            item[k] = v
        items.append(item)
    return items