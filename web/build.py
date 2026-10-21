#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
构建单文件网页版：把 data.json 内联进 index.html，产出零依赖、可直接发布的单文件。

用法：python build.py
产出：../docs/index.html（覆盖）
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(HERE, "..", "tools", "data.json")
with open(DATA_PATH, "r", encoding="utf-8") as f:
    DATA = json.load(f)
with open(os.path.join(HERE, "template.html"), "r", encoding="utf-8") as f:
    tpl = f.read()

payload = json.dumps(DATA, ensure_ascii=False, separators=(",", ":"))
html = tpl.replace("/*__DATA__*/", payload)

out = os.path.join(HERE, "..", "docs", "index.html")
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w", encoding="utf-8") as f:
    f.write(html)
print(f"已生成 {out}  ({os.path.getsize(out):,} bytes)")