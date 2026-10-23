#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
probe_images.py —— 探测麦当劳图源是否存在真实图片

原理：`ProductPool` 路径对**任意 code** 都返回 HTTP 200，
但图片不存在时返回 ~473 字节的占位图（1x1 或空白 PNG），
真实图片则是几十 KB。因此用**文件大小**判断 code 是否有效。

用法：
    python tools/probe_images.py 1106 4648 1450 ...
    python tools/probe_images.py --batch 1000 1500     # 扫区间
"""
import sys
import urllib.request
import urllib.error

BASE = "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_{}_320.png"
# 真实图片的最小字节数；占位图约 470 字节
MIN_REAL_BYTES = 2000
TIMEOUT = 8


def probe(code: str) -> tuple:
    """返回 (code, url, ok, size)"""
    url = BASE.format(code)
    try:
        req = urllib.request.Request(url, method="GET")
        req.add_header("User-Agent", "Mozilla/5.0")
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            data = r.read()
        size = len(data)
        return code, url, size >= MIN_REAL_BYTES, size
    except Exception as e:
        return code, url, False, -1


def batch_probe(codes, label=""):
    ok_list, bad_list = [], []
    for c in codes:
        code, url, ok, size = probe(str(c))
        if ok:
            ok_list.append((code, url, size))
            print(f"  [OK]   {code:>10s}  {size:>7d} bytes")
        else:
            bad_list.append(code)
            print(f"  [FAIL] {code:>10s}  {size:>7d}")
    print(f"\n{label} 有效 {len(ok_list)} / {len(codes)}")
    return ok_list, bad_list


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        raise SystemExit(0)

    if args[0] == "--batch":
        lo, hi = int(args[1]), int(args[2])
        codes = list(range(lo, hi + 1))
        print(f"扫描 code {lo}~{hi}（{len(codes)} 个）\n")
    else:
        codes = args
        print(f"探测 {len(codes)} 个 code\n")

    ok, bad = batch_probe(codes, "总计")
    if ok:
        print("\n有效 code 列表:")
        print("  " + " ".join(c for c, _, _ in ok))