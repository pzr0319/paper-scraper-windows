<div align="right">

[English](README.md) | [简体中文](README_zh.md)

</div>

# Paper Scraper for Windows

> **paper-scraper-windows** — 针对 **ScienceDirect** 和 **INFORMS PubsOnLine** 的自动化论文爬虫。
> 支持按关键词、作者、期刊搜索，并通过机构账号批量下载 PDF。
>
> 为 **Windows** 优化，同时完整支持 macOS / Linux。

![License](https://img.shields.io/badge/License-MIT-blue)
![Python](https://img.shields.io/badge/Python-3.8+-green)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-blue)
![ScienceDirect](https://img.shields.io/badge/ScienceDirect-supported-orange)
![INFORMS](https://img.shields.io/badge/INFORMS-supported-orange)

---

## 支持平台

| 脚本 | 平台 | PDF 下载方式 |
|------|------|-------------|
| `sd_scraper.py` / `sd_scraper_en.py` | [ScienceDirect](https://www.sciencedirect.com)（Elsevier） | CDP `printToPDF`（绕过 Cloudflare） |
| `informs_scraper.py` / `informs_scraper_en.py` | [INFORMS PubsOnLine](https://pubsonline.informs.org) | Session Cookie 直连下载 |

`_en.py` 结尾为英文界面版，其余为中文界面版，逻辑完全相同。

### 独立 CDP 工具

| 脚本 | 用途 |
|------|------|
| `cdp_scraper.py` | CDP 搜索 + PDF 下载（独立运行，推荐中国大陆用户使用） |
| `cdp_search.py` | 轻量 CDP 搜索（不下载 PDF） |
| `extract_cookies_cdp.py` | 启动 Chrome 调试模式 + 通过 CDP 提取 Cookie |

---

## 四层自动降级策略 (v2.1)

所有抓取脚本均实现了完整的四层自动降级，确保最大成功率：

| 层级 | 优先方案 | 降级方案 | 降级触发条件 |
|------|---------|---------|-------------|
| **Cookie** | `browser_cookie3`（从 Chrome 磁盘读取） | CDP 启动 Chrome（调试端口提取） | `browser_cookie3` 未安装或返回空 |
| **搜索** | `curl_cffi` TLS 指纹模拟 | CDP 真实 Chrome 窗口（绕过 JS Challenge） | 搜索返回 0 条结果（Cloudflare 拦截） |
| **PDF 下载** | CDP `printToPDF` / `curl_cffi` 直连 | 信息表格 CSV（PDF 尝试前已保存） | PDF 下载失败 |
| **输出目录** | 用户 `--output` 指定路径 | `os.getcwd()`（启动脚本的目录） | 未提供 `--output` 参数 |

**关键保障：** CSV 信息表格在 PDF 下载**之前**就已保存——即使所有 PDF 都下载失败，搜索结果也不会丢失。

---

## 认证说明：需要登录有效账号

**TLS 和 CDP 两种方法都需要有效的机构账号登录。**

抓取工具不会绕过付费墙——它们"借用"你现有的登录状态：

- **TLS 方法**：从 Chrome 磁盘读取 Cookie（`browser_cookie3`），然后随每个 HTTP 请求发送。
- **CDP 方法**：复制你的 Chrome Profile（包含登录 Cookie），启动一个真实 Chrome 窗口——ScienceDirect 看到的只是一个已登录的正常浏览器。

没有有效登录，你仍然可以搜索和获取元数据，但无法下载全文 PDF。

**登录步骤：**
1. 打开 Chrome，访问 https://www.sciencedirect.com
2. 点击右上角 "Sign in" → "Access through your institution"
3. 搜索你的学校名称，完成 SSO/CARSI 统一认证
4. 确认右上角显示你的机构名称，说明登录成功

---

## 安装

```bash
pip install curl_cffi websocket-client browser-cookie3 openpyxl
```

如需使用 INFORMS 爬虫，额外安装：

```bash
pip install beautifulsoup4 lxml
```

完整依赖列表见 [`requirements.txt`](requirements.txt)。

---

## 快速上手

### ScienceDirect

```bash
# 交互式向导（首次使用推荐）
python sd_scraper.py

# 关键词搜索，保存为 XLSX
python sd_scraper.py -m keyword -q "machine learning" -n 100 --browser-cookies

# 关键词搜索 + 下载 PDF 到桌面
python sd_scraper.py -m keyword -q "耐心资本" -n 10 --browser-cookies --download-pdfs --output "C:/Users/你的用户名/Desktop"

# 浏览期刊（按时间倒序）
python sd_scraper.py -m journal -j "Energy" -n 200 --browser-cookies --sort date

# 在指定期刊内按关键词搜索
python sd_scraper.py -m journal_keyword -j "Renewable Energy" -q "solar cell" -n 50 --browser-cookies

# 按作者搜索
python sd_scraper.py -m author -a "Zhang Wei" -n 30 --browser-cookies

# 高级搜索（组合条件）
python sd_scraper.py -m advanced -q "deep learning" --date 2021-2024 --type REV -n 50 --browser-cookies --download-pdfs
```

### INFORMS PubsOnLine

```bash
# 交互式向导
python informs_scraper.py

# 关键词搜索
python informs_scraper.py -m keyword -q "supply chain" -n 100 --browser-cookies

# 浏览期刊
python informs_scraper.py -m journal -j mnsc -n 200 --browser-cookies

# 指定卷期目录
python informs_scraper.py -m toc -j mnsc -v 71 -i 3 --browser-cookies

# 关键词搜索 + 下载 PDF
python informs_scraper.py -m keyword -q "inventory" -n 50 --browser-cookies --download-pdf

# 最推荐的登录方式：弹出 Chrome 窗口手动登录
python informs_scraper.py -m keyword -q "machine learning" -n 50 --chrome-login --download-pdf
```

#### INFORMS 期刊代码

| 代码 | 期刊名称 |
|------|---------|
| `mnsc` | Management Science |
| `opre` | Operations Research |
| `ijoc` | INFORMS Journal on Computing |
| `mksc` | Marketing Science |
| `msom` | Manufacturing & Service Operations Management |
| `trsc` | Transportation Science |
| `isre` | Information Systems Research |
| `orsc` | Organization Science |

---

## PDF 下载原理

### ScienceDirect

在中国大陆，Cloudflare 会拦截对 PDF 端点的直接 HTTP 请求。抓取工具使用两种策略：

**策略一 — TLS 指纹 (curl_cffi)：**
- 在协议层面模拟 Chrome 的 TLS 指纹
- 快速，不需要浏览器窗口
- 在国外可用；在国内常被 Cloudflare JS Challenge 拦截

**策略二 — Chrome DevTools Protocol (CDP)：**
- 携带你现有的登录 Profile 启动一个真实的 Chrome 窗口
- 在文章页面调用 `Page.printToPDF` CDP 命令
- 解码 base64 PDF 响应后直接写入磁盘
- **完全绕过 Cloudflare JS Challenge**——ScienceDirect 看到的是正常浏览器
- 需要 Chrome 调试端口（9222）

```bash
# 若 Chrome 尚未登录，先运行：
python sd_scraper.py --open-browser-login
# 再执行抓取：
python sd_scraper.py -m keyword -q "turbine" -n 50 --browser-cookies --download-pdfs
```

### 独立 CDP 工具（推荐中国大陆用户使用）

由于 GFW DNS 污染和 Cloudflare JS Challenge，`curl_cffi` 搜索路径在中国大陆基本不可用。项目提供了独立的 CDP 工具直接操控 Chrome：

```bash
# 步骤 1：启动 Chrome 调试模式（自动检测代理）
python extract_cookies_cdp.py

# 步骤 2：CDP 搜索 + DOM 提取（元数据始终保存为 CSV）
python cdp_scraper.py "enterprise digital transformation" 5

# 步骤 3：搜索 + PDF 下载到指定目录
python cdp_scraper.py "enterprise digital transformation" 5 --download-pdfs -o "C:/Users/你的用户名/Desktop"

# 轻量搜索（不下载 PDF）
python cdp_search.py "machine learning" 10
```

`cdp_scraper.py` 特性：
- 通过真实 Chrome 窗口完全绕过 Cloudflare JS Challenge
- `_DOM_EXTRACT_JS` (~140行) 从 DOM 提取标题/作者/期刊/年份/PII/DOI
- PDF 通过 `Page.printToPDF` CDP 命令捕获（base64 解码后保存）
- 自动检测代理：环境变量 `HTTPS_PROXY` → Windows 注册表 → macOS `scutil --proxy`
- 搜索失败不丢数据：CSV 在 PDF 下载**之前**已保存

**重要提示：** CDP 工具同样需要你先在 Chrome 中登录 ScienceDirect。脚本会复制你的 Chrome Profile 以保留登录状态。

### INFORMS

INFORMS（Atypon 平台）的 PDF 端点没有 JS 验证，有效的 Session Cookie 即可直连下载。

```bash
# 方式一：从 Chrome 读取 Cookie（需提前在 Chrome 中登录）
python informs_scraper.py -m keyword -q "inventory" -n 30 --browser-cookies --download-pdf

# 方式二：弹出 Chrome 窗口手动登录，自动提取 Cookie（最推荐）
python informs_scraper.py -m keyword -q "inventory" -n 30 --chrome-login --download-pdf

# 方式三：会员账号直接登录
python informs_scraper.py -m keyword -q "inventory" -n 30 --member 123456 --password MyPwd --download-pdf
```

---

## 输出目录结构

默认输出到 `os.getcwd()`——即你启动脚本时所在的目录。使用 `--output` 可自定义。

```
<输出目录>/
└── keyword_machine_learning_20250628_120000/   ← 带时间戳的子目录
    ├── keyword_machine_learning_20250628_120000.xlsx   ← 元数据
    ├── keyword_machine_learning_20250628_120000.csv    ← CSV 备份
    └── pdfs/
        ├── 001_Zhang_2024_Deep learning for...pdf
        ├── 002_Li_2023_Transfer learning in...pdf
        └── ...
```

---

## 完整命令行参数

### ScienceDirect（`sd_scraper.py` / `sd_scraper_en.py`）

| 参数 | 说明 |
|------|------|
| `-m`, `--mode` | `keyword` / `journal` / `journal_keyword` / `author` / `issn` / `advanced` |
| `-q`, `--query` | 搜索关键词（支持 `AND` / `OR` / `NOT`） |
| `-j`, `--journal` | 期刊名称 |
| `-a`, `--author` | 作者姓名 |
| `--issn` | 期刊 ISSN |
| `-n`, `--count` | 最大抓取数量（默认 50） |
| `--date` | 年份范围，如 `2020-2024` |
| `--sort` | 排序：`relevance`（默认）/ `date` |
| `--type` | 文章类型：`FLA` / `REV` / `SCO` |
| `--browser-cookies` | 自动从本机 Chrome 读取 Cookie |
| `--cookies` | 指定 Cookie JSON 文件路径 |
| `--format` | 输出格式：`xlsx`（默认）/ `csv` / `json` / `all` |
| `--download-pdfs` | 搜索后下载 PDF |
| `--output` | 自定义输出目录（默认：当前工作目录） |
| `--open-browser-login` | 打开 Chrome 供机构登录 |
| `--interactive` | 启动交互式向导 |

### 独立 CDP 工具（`cdp_scraper.py`）

| 参数 | 说明 |
|------|------|
| `query` | 搜索关键词（位置参数，必填） |
| `count` | 最大抓取数量（位置参数，默认 3） |
| `--download-pdfs` | 搜索后下载 PDF |
| `-o`, `--output` | 输出目录（默认：`./results/`） |

### INFORMS（`informs_scraper.py` / `informs_scraper_en.py`）

| 参数 | 说明 |
|------|------|
| `-m`, `--mode` | `keyword` / `journal` / `toc` / `advanced` |
| `-q`, `--query` | 搜索关键词 |
| `-j`, `--journal` | 期刊代码（如 `mnsc`） |
| `-v`, `--volume` | 卷号（toc 模式） |
| `-i`, `--issue` | 期号（toc 模式） |
| `--author` | 作者姓名（advanced 模式） |
| `--date` | 年份范围，如 `2020-2024` |
| `-n`, `--count` | 最大抓取数量（默认 100） |
| `--chrome-login` | ★ 弹出 Chrome 手动登录（最推荐） |
| `--browser-cookies` | 从本机 Chrome 读取 Cookie |
| `--cookies-file` | 指定 Cookie JSON 文件路径 |
| `--member` | INFORMS 会员号 |
| `--password` | 账号密码 |
| `--format` | `csv`（默认）/ `json` / `xlsx` |
| `--download-pdf` | 搜索后下载 PDF |
| `-o`, `--output-dir` | 输出目录 |

---

## 注意事项

- **需要机构订阅权限**才能下载完整 PDF。开放获取文章无需登录。TLS 和 CDP 两种方法都依赖你现有的 Chrome 登录状态。
- **在中国大陆**，请使用 CDP 工具（`cdp_scraper.py`）——`curl_cffi` 搜索几乎总会被 GFW + Cloudflare 拦截。
- **请求限速**：脚本在每次请求之间加入随机延迟（默认 2–5 秒），请勿降低此数值。
- **跨平台支持**：Windows / macOS / Linux 均已适配，脚本自动检测操作系统选择正确的 Chrome 路径。
- **Cookie 有时效性**：Session Cookie 通常几天到几周后过期。遇到 403 错误时重新登录即可。
- **CSV 表格在 PDF 下载之前就已保存**——即使所有 PDF 都失败，搜索结果也不会丢失。
- 请遵守所在机构及各出版商的使用条款，仅用于个人学术研究。

---

## 开源协议

MIT
