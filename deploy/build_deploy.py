#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
构建可发布的后端应用包。

产出结构（用于部署，勿手工改动）：
    app-dist/
      app.py          后端服务（零依赖 stdlib）
      mcd_client.py   MCP 客户端
      docs/           网页静态资源（index.html + assets/）

用法：python deploy/build_deploy.py
"""
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DIST = os.path.join(HERE, "app-dist")
SERVER = os.path.join(ROOT, "server")
DOCS = os.path.join(ROOT, "docs")


def main():
    if os.path.isdir(DIST):
        shutil.rmtree(DIST)
    os.makedirs(DIST)

    # 1. 后端代码
    for name in ("app.py", "mcd_client.py", "ip_locator.py"):
        src = os.path.join(SERVER, name)
        if not os.path.exists(src):
            print("缺少后端文件:", src)
            return 1
        shutil.copy2(src, os.path.join(DIST, name))

    # 2. 网页资源
    dst_docs = os.path.join(DIST, "docs")
    shutil.copytree(DOCS, dst_docs)

    # 3. 部署说明
    readme = os.path.join(DIST, "README.md")
    with open(readme, "w", encoding="utf-8") as f:
        f.write(
            "# 麦卡收藏家 · 部署包\n\n"
            "启动：\n\n"
            "```bash\n"
            "PORT=8080 MCD_MCP_TOKEN=<你的Token> python app.py\n"
            "```\n\n"
            "必需环境变量：\n\n"
            "- `PORT`：HTTP 端口，默认 8080\n"
            "- `MCD_MCP_TOKEN`：麦当劳开放平台 MCP Token\n"
            "  （到 https://open.mcd.cn/mcp 扫码登录 → 控制台 → 激活 → 复制）\n\n"
            "新接口（v2）：\n\n"
            "- `GET /api/ip-locate` —— 根据请求 IP 定位城市（ip-api.com 免费库）\n"
            "- `POST /api/stores` —— 当 city/keyword 缺省时，自动用 IP 定位兜底\n\n"
            "说明：Token 只在服务端使用，不会下发到浏览器。\n"
        )

    total = sum(
        os.path.getsize(os.path.join(dp, fn))
        for dp, _, fns in os.walk(DIST) for fn in fns
    )
    print(f"部署包已生成：{DIST}  ({total:,} bytes)")
    print("启动命令：PORT=8080 MCD_MCP_TOKEN=xxx python app.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())