"""验证 norm_stores 对真实 MCP 返回的解析：排序、距离格式化、字段映射。"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server"))
from app import norm_stores, _fmt_distance  # noqa: E402

# 真实 MCP 返回（北京朝阳，distance 单位=米，longitude/latitude 均为 0）
REAL = {
    "success": True, "code": 200,
    "data": [
        {"storeCode": "1950538", "storeName": "麦当劳北京朝阳站三层候车餐厅(三层出发层)",
         "address": "北京朝阳站三层G2-10号", "distance": 18,
         "businessStatus": True, "businessStartTime": "07:00", "businessEndTime": "21:00",
         "longitude": 0.0, "latitude": 0.0, "reservation": True},
        {"storeCode": "1950918", "storeName": "麦当劳北京青年北路(姚家园万象汇)餐厅",
         "address": "青年北路35号院1号", "distance": 821,
         "businessStatus": True, "businessStartTime": "07:00", "businessEndTime": "22:00",
         "longitude": 0.0, "latitude": 0.0, "reservation": True},
        {"storeCode": "1950304", "storeName": "麦当劳北京姚家园路(活力东方广场)餐厅",
         "address": "姚家园路甲1号", "distance": 1233,
         "businessStatus": True, "businessStartTime": "07:00", "businessEndTime": "22:30",
         "longitude": 0.0, "latitude": 0.0, "reservation": True},
        {"storeCode": "1950998", "storeName": "麦当劳北京青年路国美第一城餐厅",
         "address": "青年路西里3号院", "distance": 1362,
         "businessStatus": True, "businessStartTime": "07:00", "businessEndTime": "23:00",
         "longitude": 0.0, "latitude": 0.0, "reservation": True},
    ],
}

ok = True


def check(name, cond, extra=""):
    global ok
    print(("  ✓ " if cond else "  ✗ ") + name + ("  " + extra if extra else ""))
    if not cond:
        ok = False


print("[1] 距离格式化")
check("18m → '18 m'", _fmt_distance(18) == "18 m", repr(_fmt_distance(18)))
check("821m → '821 m'", _fmt_distance(821) == "821 m", repr(_fmt_distance(821)))
check("1362m → '1.4 km'", _fmt_distance(1362) == "1.4 km", repr(_fmt_distance(1362)))
check("0 → '距离未知'", _fmt_distance(0) == "距离未知", repr(_fmt_distance(0)))

print("\n[2] 真实数据解析")
rows = norm_stores(REAL)
check("解析出 4 家门店", len(rows) == 4, f"实际 {len(rows)}")
check("按距离升序", [r["distance"] for r in rows] == sorted(r["distance"] for r in rows))
check("最近的是 18m 那家", rows[0]["storeCode"] == "1950538", rows[0]["distanceText"])
check("字段映射 storeCode", rows[0]["storeCode"] == "1950538")
check("字段映射 name", "朝阳站" in rows[0]["name"])
check("字段映射 address", rows[0]["address"] == "北京朝阳站三层G2-10号")
check("字段映射 open", rows[0]["open"] == "07:00-21:00", repr(rows[0]["open"]))
check("字段映射 reservation", rows[0]["reservation"] is True)
check("含 distanceText 供前端显示", all(r["distanceText"] for r in rows))

print("\n[3] 边界情况")
check("空 data → []", norm_stores({"data": []}) == [])
check("缺 data → []", norm_stores({}) == [])
check("distance 为 null 不崩", norm_stores({"data": [{"storeCode": "x"}]})[0]["distance"] == 0.0)
check("单条对象也兼容", len(norm_stores({"storeCode": "s1", "storeName": "n",
                                       "distance": 5})) == 1)

print("\n" + ("全部通过" if ok else "存在失败"))
sys.exit(0 if ok else 1)