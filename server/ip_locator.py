"""
ip_locator.py —— IP → 城市定位（零依赖标准库）。

数据源：``http://ip-api.com/json/{ip}?lang=zh-CN``（免费，无 key，每分钟 45 次限制）。
返回 {city, regionName, country, lat, lon, isp, query}。

为何不用高德/百度：需要 key 与注册，且仅返回经纬度（仍需「城市+地点」二段搜索）。
ip-api 直接给中文城市名，恰好契合 MCP ``query-nearby-stores`` 的 city 字段。

失败兜底：返回 ``{city: "沈阳"}``（开发者常驻城市），让前端总能进入门店选择流程。
"""

import json
import urllib.error
import urllib.request

API = "http://ip-api.com/json/{ip}?lang=zh-CN"
TIMEOUT = 4

# 兜底城市
FALLBACK = {
    "city": "沈阳",
    "regionName": "辽宁",
    "country": "中国",
    "lat": 41.8057,
    "lon": 123.4315,
    "isp": "",
    "query": "",
    "source": "fallback",
}


def locate(ip=None, client_ip=None):
    """
    定位客户端所在城市。

    参数:
      ip:        可显式指定 IP（调试用）
      client_ip: 通常从 ``request.headers["X-Real-IP"]`` 或 REMOTE_ADDR 拿

    返回 dict：至少含 ``city`` 字段。失败时返回 FALLBACK。
    """
    target = (ip or client_ip or "").strip()
    # 本机/内网 IP 直接走兜底
    if not target or target.startswith("127.") or target.startswith("::1") \
            or target.startswith("10.") or target.startswith("192.168.") \
            or target.startswith("172."):
        return dict(FALLBACK)

    try:
        url = API.format(ip=target)
        req = urllib.request.Request(url, headers={"User-Agent": "mcd-gacha/1.0"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read().decode("utf-8", "replace")
        data = json.loads(body)
        if data.get("status") != "success":
            return dict(FALLBACK)
        return {
            "city": data.get("city") or FALLBACK["city"],
            "regionName": data.get("regionName") or "",
            "country": data.get("country") or "中国",
            "lat": data.get("lat"),
            "lon": data.get("lon"),
            "isp": data.get("isp") or "",
            "query": data.get("query") or target,
            "source": "ip-api",
        }
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError):
        return dict(FALLBACK)
    except Exception:
        return dict(FALLBACK)