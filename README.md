<div align="right">

[English](README.md) | [简体中文](README_zh.md)

</div>

# Paper Scraper for Windows

> **paper-scraper-windows** — Automated academic paper scrapers for **ScienceDirect** and **INFORMS PubsOnLine**.
> Search papers by keyword, author, or journal, and batch-download PDFs using your institutional access.
>
> Optimized for **Windows** with full cross-platform support (macOS / Linux).

![License](https://img.shields.io/badge/License-MIT-blue)
![Python](https://img.shields.io/badge/Python-3.8+-green)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-blue)
![ScienceDirect](https://img.shields.io/badge/ScienceDirect-supported-orange)
![INFORMS](https://img.shields.io/badge/INFORMS-supported-orange)

---

## Supported Platforms

| Script | Platform | PDF Download |
|--------|----------|--------------|
| `sd_scraper.py` / `sd_scraper_en.py` | [ScienceDirect](https://www.sciencedirect.com) (Elsevier) | CDP `printToPDF` (bypasses Cloudflare) |
| `informs_scraper.py` / `informs_scraper_en.py` | [INFORMS PubsOnLine](https://pubsonline.informs.org) | Direct HTTP with session cookie |

Files ending in `_en.py` are full English-interface versions; the others are Chinese-interface versions. Logic is identical.

### Standalone CDP Tools

| Script | Purpose |
|--------|---------|
| `cdp_scraper.py` | CDP search + PDF download (self-contained, recommended for mainland China users) |
| `cdp_search.py` | Lightweight CDP search only (no PDF download) |
| `extract_cookies_cdp.py` | Launch Chrome in debug mode + extract cookies via CDP |

---

## Four-Layer Auto-Fallback Strategy (v2.1)

The scrapers implement a complete four-layer fallback chain to maximize success rate:

| Layer | Preferred | Fallback | When Fallback Triggers |
|-------|-----------|----------|------------------------|
| **Cookie** | `browser_cookie3` (reads Chrome cookies from disk) | CDP Chrome launch (extracts cookies via DevTools) | `browser_cookie3` not installed or returns empty |
| **Search** | `curl_cffi` TLS fingerprint emulation | CDP real Chrome window (bypasses JS Challenge) | Search returns 0 results (Cloudflare blocked) |
| **PDF Download** | CDP `printToPDF` / `curl_cffi` direct download | Info table CSV (always saved before PDF attempt) | PDF download fails for any reason |
| **Output Dir** | User-specified `--output` path | `os.getcwd()` (the directory where you launched the script) | No `--output` flag provided |

**Key guarantee:** the CSV info table is saved **before** PDF download is attempted. Even if every PDF fails, you never lose the search results.

---

## Authentication Required

**Both TLS and CDP methods require a valid institutional login to ScienceDirect.**

The scrapers do NOT bypass the paywall — they "borrow" your existing login state:

- **TLS method**: reads cookies from your Chrome profile on disk (`browser_cookie3`), then sends them with every HTTP request.
- **CDP method**: copies your Chrome profile (including login cookies) and launches a real Chrome window — ScienceDirect sees a normal logged-in browser.

Without a valid login, you can still search and get metadata, but full-text PDFs will be blocked.

**How to log in:**
1. Open Chrome, go to https://www.sciencedirect.com
2. Click "Sign in" → "Access through your institution"
3. Search for your university, complete SSO/CARSI login
4. Verify your institution name appears in the top-right corner

---

## Installation

```bash
pip install curl_cffi websocket-client browser-cookie3 openpyxl
```

For INFORMS scraper, also install:

```bash
pip install beautifulsoup4 lxml
```

Full dependency list: [`requirements.txt`](requirements.txt)

---

## Quick Start

### ScienceDirect

```bash
# Interactive wizard (recommended for first use)
python sd_scraper_en.py

# Keyword search — save metadata as XLSX
python sd_scraper_en.py -m keyword -q "machine learning" -n 100 --browser-cookies

# Keyword search + download PDFs to Desktop
python sd_scraper_en.py -m keyword -q "patient capital" -n 10 --browser-cookies --download-pdfs --output "C:/Users/YourName/Desktop"

# Browse a journal (most recent first)
python sd_scraper_en.py -m journal -j "Energy" -n 200 --browser-cookies --sort date

# Keyword search within a specific journal
python sd_scraper_en.py -m journal_keyword -j "Renewable Energy" -q "solar cell" -n 50 --browser-cookies

# Search by author
python sd_scraper_en.py -m author -a "Zhang Wei" -n 30 --browser-cookies

# Advanced search (combine criteria)
python sd_scraper_en.py -m advanced -q "deep learning" --date 2021-2024 --type REV -n 50 --browser-cookies --download-pdfs
```

### INFORMS PubsOnLine

```bash
# Interactive wizard
python informs_scraper_en.py

# Keyword search
python informs_scraper_en.py -m keyword -q "supply chain" -n 100 --browser-cookies

# Browse a journal
python informs_scraper_en.py -m journal -j mnsc -n 200 --browser-cookies

# Specific volume/issue TOC
python informs_scraper_en.py -m toc -j mnsc -v 71 -i 3 --browser-cookies

# Keyword search + download PDFs
python informs_scraper_en.py -m keyword -q "inventory" -n 50 --browser-cookies --download-pdf

# Best login method: pop up Chrome, log in manually
python informs_scraper_en.py -m keyword -q "machine learning" -n 50 --chrome-login --download-pdf
```

#### INFORMS Journal Codes

| Code | Journal |
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

## How PDF Download Works

### ScienceDirect

Cloudflare blocks direct HTTP requests to PDF endpoints in mainland China. The scrapers use two strategies:

**Strategy 1 — TLS fingerprint (curl_cffi):**
- Emulates Chrome's TLS fingerprint at the protocol level
- Fast, no browser window needed
- Works outside mainland China; inside China, often blocked by Cloudflare JS Challenge

**Strategy 2 — Chrome DevTools Protocol (CDP):**
- Launches a real Chrome window with your existing login profile
- Calls `Page.printToPDF` CDP command on the article page
- Decodes the base64 PDF response and writes it to disk
- **Completely bypasses Cloudflare JS Challenge** — ScienceDirect sees a normal browser
- Requires Chrome debug port (port 9222)

```bash
# If Chrome isn't already logged in, use this first:
python sd_scraper_en.py --open-browser-login
# Then run your actual scrape:
python sd_scraper_en.py -m keyword -q "turbine" -n 50 --browser-cookies --download-pdfs
```

### Standalone CDP Tools (Recommended for users in mainland China)

Due to GFW DNS poisoning and Cloudflare JS Challenges, the `curl_cffi` search path often does not work from mainland China. The standalone CDP tools drive Chrome directly:

```bash
# Step 1: Launch Chrome with debug port (auto-detects proxy)
python extract_cookies_cdp.py

# Step 2: CDP search + DOM extraction (metadata always saved as CSV)
python cdp_scraper.py "enterprise digital transformation" 5

# Step 3: Search + PDF download to custom directory
python cdp_scraper.py "enterprise digital transformation" 5 --download-pdfs -o "C:/Users/YourName/Desktop"

# Lightweight: search only (no PDF download)
python cdp_search.py "machine learning" 10
```

`cdp_scraper.py` features:
- Bypasses Cloudflare JS Challenge completely via a real Chrome window
- `_DOM_EXTRACT_JS` (~140 lines) extracts title/author/journal/year/PII/DOI from the DOM
- PDF captured via `Page.printToPDF` CDP command (base64-decoded, saved to disk)
- Auto-detects proxy: env var `HTTPS_PROXY` → Windows registry → macOS `scutil --proxy`
- CSV always saved **before** PDF attempt — failed downloads don't lose data

**Important:** CDP tools require you to be logged in to ScienceDirect in Chrome first. The script copies your Chrome profile to preserve the login session.

### INFORMS

INFORMS (Atypon platform) does not enforce JS challenges on PDF endpoints — a valid session cookie is sufficient.

```bash
# Option 1: read cookies from Chrome (must be logged in already)
python informs_scraper_en.py -m keyword -q "inventory" -n 30 --browser-cookies --download-pdf

# Option 2: pop up Chrome, log in, then auto-extract cookies
python informs_scraper_en.py -m keyword -q "inventory" -n 30 --chrome-login --download-pdf

# Option 3: member credentials (direct login)
python informs_scraper_en.py -m keyword -q "inventory" -n 30 --member 123456 --password MyPwd --download-pdf
```

---

## Output

Output defaults to `os.getcwd()` — the directory where you launched the script. Use `--output` to customize.

```
<output_dir>/
└── keyword_machine_learning_20250628_120000/   ← timestamped subfolder
    ├── keyword_machine_learning_20250628_120000.xlsx   ← metadata
    ├── keyword_machine_learning_20250628_120000.csv    ← CSV backup
    └── pdfs/
        ├── 001_Zhang_2024_Deep learning for...pdf
        ├── 002_Li_2023_Transfer learning in...pdf
        └── ...
```

---

## All CLI Options

### ScienceDirect (`sd_scraper_en.py` / `sd_scraper.py`)

| Option | Description |
|--------|-------------|
| `-m`, `--mode` | `keyword` / `journal` / `journal_keyword` / `author` / `issn` / `advanced` |
| `-q`, `--query` | Search keywords (supports `AND` / `OR` / `NOT`) |
| `-j`, `--journal` | Journal name |
| `-a`, `--author` | Author name |
| `--issn` | Journal ISSN |
| `-n`, `--count` | Max papers to fetch (default: 50) |
| `--date` | Year range, e.g. `2020-2024` |
| `--sort` | `relevance` (default) or `date` |
| `--type` | Article type: `FLA` / `REV` / `SCO` |
| `--browser-cookies` | Auto-read cookies from local Chrome |
| `--cookies` | Path to a cookie JSON file |
| `--format` | Output format: `xlsx` (default) / `csv` / `json` / `all` |
| `--download-pdfs` | Download PDFs after saving metadata |
| `--output` | Custom output directory (default: current working directory) |
| `--open-browser-login` | Open Chrome for manual institutional login |
| `--interactive` | Launch interactive wizard |

### Standalone CDP (`cdp_scraper.py`)

| Argument | Description |
|----------|-------------|
| `query` | Search keywords (positional, required) |
| `count` | Max papers to fetch (positional, default: 3) |
| `--download-pdfs` | Download PDFs after search |
| `-o`, `--output` | Output directory (default: `./results/`) |

### INFORMS (`informs_scraper_en.py` / `informs_scraper.py`)

| Option | Description |
|--------|-------------|
| `-m`, `--mode` | `keyword` / `journal` / `toc` / `advanced` |
| `-q`, `--query` | Search keywords |
| `-j`, `--journal` | Journal code (e.g. `mnsc`) |
| `-v`, `--volume` | Volume number (toc mode) |
| `-i`, `--issue` | Issue number (toc mode) |
| `--author` | Author name (advanced mode) |
| `--date` | Year range, e.g. `2020-2024` |
| `-n`, `--count` | Max papers (default: 100) |
| `--chrome-login` | ★ Pop up Chrome for manual login (most reliable) |
| `--browser-cookies` | Read cookies from local Chrome |
| `--cookies-file` | Load cookies from a JSON file |
| `--member` | INFORMS member ID |
| `--password` | Account password |
| `--format` | `csv` (default) / `json` / `xlsx` |
| `--download-pdf` | Download PDFs after scraping |
| `-o`, `--output-dir` | Output directory |

---

## Notes

- **Institutional access required** for full-text PDF download. Open-access papers can be downloaded without login. Both TLS and CDP methods depend on your existing Chrome login session.
- **In mainland China**, use the CDP tools (`cdp_scraper.py`) — `curl_cffi` searches are almost always blocked by the GFW + Cloudflare.
- **Rate limiting**: the scraper adds random delays between requests (default 2–5 s). Do not reduce these aggressively.
- **Cross-platform**: Windows, macOS, and Linux are fully supported. The scripts auto-detect the OS and select the correct Chrome path automatically.
- **Cookie expiry**: session cookies expire (typically days to weeks). Re-login if you encounter 403 errors.
- **CSV is always saved before PDF download** — even if all PDFs fail, your search results are safe.
- Use responsibly and in accordance with your institution's and the publishers' terms of service.

---

## License

MIT
