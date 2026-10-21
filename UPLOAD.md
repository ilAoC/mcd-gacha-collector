# 上传到 GitHub 操作指南

## 前置条件

- ✅ 本地已 `git init` 并首次 commit（已完成）
- ✅ 仓库根：`C:\Users\Sunli\WorkBuddy\2026-09-20-10-39-32\mcd-gacha-collector`
- ✅ 没有真实 Token 泄漏（已 grep 校验）
- ❌ 需要您自己创建 GitHub 仓库 + 提供 push 凭据

---

## ⚠️ 安全提示

**请勿把 GitHub 密码告诉 AI**（包括我）。GitHub 自 2021 年已停止密码登录，
正确做法是生成 **Personal Access Token**（PAT）。

**Token 在哪里生成**：https://github.com/settings/tokens/new
- Note 随便填（如 `workbuddy-2026`）
- 选 **No expiration** 或 30 天
- 勾选 **`repo`** 权限
- 生成后**立即复制**（只显示一次）
- Token 格式：40+ 位随机字符串（GitHub 设置页生成后只显示一次）

---

## 方案 A：GitHub 网页建仓 + 本地 push（推荐）

### 1. 在 GitHub 网页创建空仓库

1. 登录 https://github.com
2. 点 **+ → New repository**
3. 填写：
   - **Repository name**：`mcd-gacha-collector`
   - **Description**：麦卡收藏家 · 基于麦当劳中国 MCP 的卡牌收集 Skill + 网页版（参赛项目）
   - **Public / Private**：**Public**（参赛要求公开）
   - **不要勾选** Add README / .gitignore / license（本地都有了）
4. 点 **Create repository**

### 2. 本地 push（两条命令）

打开 PowerShell 或 Git Bash，`cd` 到仓库根：

```bash
cd "C:\Users\Sunli\WorkBuddy\2026-09-20-10-39-32\mcd-gacha-collector"

# 关联远程仓库（替换 <你的GitHub用户名>）
git remote add origin https://github.com/<你的GitHub用户名>/mcd-gacha-collector.git

# 推送 main 分支
git push -u origin main
```

GitHub 会要求登录，按提示输入：
- 用户名（您的 GitHub 用户名）
- **Personal Access Token**（不是密码！粘贴时不会回显任何字符）

### 3. 验证

刷新 GitHub 仓库页，应能看到：
- 39 文件 / 6 commits
- README 渲染正确（含 4 张首屏截图 + 整页预览 + 原理图）
- 公网试玩链接可直接点击

---

## 方案 B：用 GitHub CLI（如果您已安装 gh）

```bash
gh auth login                                    # 一次性登录（粘贴 PAT）
gh repo create mcd-gacha-collector --public --source=. --remote=origin --push --description "麦卡收藏家 · 麦当劳中国 MCP 卡牌收集 Skill + 网页版"
```

一行搞定。

---

## 方案 C：GitHub Desktop（图形界面，最省心）

1. 打开 GitHub Desktop → File → Add Local Repository
2. 选 `C:\Users\Sunli\WorkBuddy\2026-09-20-10-39-32\mcd-gacha-collector`
3. 点 **Publish repository** → 填名字 + 公开 → Publish

---

## 之后如何更新

修改文件后：

```bash
git add -A
git commit -m "简明改动说明"
git push
```

---

## 参赛提交（Push 完成后）

1. 在 https://github.com/M-China/mcd-developer-innovation-challenge 发报名 Issue
2. Issue 标题：`【参赛申请】麦卡收藏家 mcd-gacha-collector`
3. Issue 正文（**标题与正文间不要换行**，**链接不要 Markdown**）：

```
【参赛申请】
项目名称：麦卡收藏家 mcd-gacha-collector
项目地址：https://github.com/<你的GitHub用户名>/mcd-gacha-collector
项目简介：基于麦当劳中国 MCP 的卡牌收集 Skill + 网页版。53 张卡牌按健康度相对分级（SSR/UR/R），抽到可直接下单。已实测 create-order 真实下单，IP 自动定位最近门店。
```

---

## 遇到问题

| 报错 | 解决 |
|---|---|
| `Permission denied (publickey)` | SSH 密钥未配置；改用 HTTPS + Personal Access Token |
| `support for password authentication was removed` | GitHub 已禁用密码登录，必须用 Personal Access Token |
| `Updates were rejected` | 远程已有内容，先 `git pull --rebase origin main` 再 push |
| 中文文件名乱码 | `git config --global core.quotePath false` |