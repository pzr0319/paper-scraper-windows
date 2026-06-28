"""通过 Chrome CDP 搜索 ScienceDirect + 下载 PDF，绕过 Cloudflare JS Challenge。

用法：
    python cdp_scraper.py "enterprise digital transformation" 3
    python cdp_scraper.py "enterprise digital transformation" 3 --download-pdfs
    python cdp_scraper.py "enterprise digital transformation" 5 -o "D:/my_papers/"

依赖：websocket-client
前提：Chrome 调试端口 9222 已开启，用户已登录机构账号
"""

import sys
import os
import json
import time
import re
import csv
import base64
import html as html_module
import platform
import subprocess
import argparse
import websocket
import urllib.request
import urllib.parse

BASE_CDP = "http://127.0.0.1:9222"
BASE_URL = "https://www.sciencedirect.com"


def _detect_proxy():
    """自动检测用户全局代理设置。

    检测顺序：
    1. 环境变量 HTTPS_PROXY / HTTP_PROXY
    2. Windows 注册表 Internet Settings
    3. macOS 系统代理设置

    返回代理 URL 字符串（如 "http://127.0.0.1:7897"），未检测到返回 None。
    """
    # 1) 环境变量
    for var in ("HTTPS_PROXY", "HTTP_PROXY"):
        val = os.environ.get(var, "")
        if val:
            print(f"[代理检测] 从环境变量 {var} 发现: {val}")
            return val

    IS_WINDOWS = platform.system() == "Windows"

    # 2) Windows 注册表
    if IS_WINDOWS:
        try:
            result = subprocess.run(
                ["reg", "query",
                 r"HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                 "/v", "ProxyServer"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    line = line.strip()
                    if "ProxyServer" in line:
                        parts = line.split("REG_SZ", 1)
                        if len(parts) >= 2:
                            proxy = parts[1].strip()
                            if proxy:
                                # 补全 http:// 前缀
                                if "://" not in proxy:
                                    proxy = f"http://{proxy}"
                                print(f"[代理检测] 从 Windows 注册表发现: {proxy}")
                                return proxy
        except Exception:
            pass

    # 3) macOS 系统代理（通过 scutil）
    if not IS_WINDOWS:
        try:
            result = subprocess.run(
                ["scutil", "--proxy"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                http_host = http_port = None
                for line in result.stdout.splitlines():
                    line = line.strip()
                    if line.startswith("HTTPProxy :") and "0" not in line.split(":")[-1]:
                        http_host = line.split(":", 1)[-1].strip()
                    if line.startswith("HTTPPort :"):
                        http_port = line.split(":", 1)[-1].strip()
                if http_host and http_port:
                    proxy = f"http://{http_host}:{http_port}"
                    print(f"[代理检测] 从 macOS 系统代理发现: {proxy}")
                    return proxy
        except Exception:
            pass

    print("[代理检测] 未检测到代理设置")
    return None


# ── CDP 低层工具 ────────────────────────────────────────────────────────────────

def _cdp_send(ws, method, params=None, msg_id=1):
    ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))


def _cdp_recv(ws, msg_id=1, timeout_loops=30):
    for _ in range(timeout_loops):
        msg = json.loads(ws.recv())
        if msg.get("id") == msg_id:
            return msg
    return {}


def _ws_connect(tab):
    return websocket.create_connection(
        tab["webSocketDebuggerUrl"], timeout=30, suppress_origin=True)


def _new_tab(url=None):
    if url:
        req_url = f"{BASE_CDP}/json/new?{urllib.parse.quote(url, safe=':/?&=%')}"
    else:
        req_url = f"{BASE_CDP}/json/new"
    req = urllib.request.Request(req_url, method="PUT")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def _close_tab(page_id):
    try:
        urllib.request.urlopen(f"{BASE_CDP}/json/close/{page_id}", timeout=10)
    except Exception:
        pass


def _evaluate(tab, expression, timeout_loops=30):
    """在标签页中执行 JS 并返回结果。"""
    ws = _ws_connect(tab)
    _cdp_send(ws, "Runtime.evaluate", {"expression": expression, "returnByValue": True})
    result = _cdp_recv(ws, timeout_loops=timeout_loops)
    ws.close()
    return result.get("result", {}).get("result", {}).get("value", "")


# ── 搜索结果提取（从渲染后的 DOM）────────────────────────────────────────────────

_DOM_EXTRACT_JS = """
(function() {
    var results = [];
    var items = document.querySelectorAll('.result-item-content');

    items.forEach(function(item, idx) {
        if (idx >= 50) return;

        // 标题 + 链接
        var titleEl = item.querySelector('h2 a, h3 a, .result-item-title a, a[class*="title"]');
        var title = titleEl ? titleEl.textContent.trim() : '';
        var link = titleEl ? titleEl.href : '';

        // PII
        var pii = '';
        var m = link.match(/\\/pii\\/([^\\/?#]+)/);
        if (m) pii = m[1];

        // 作者（.author 类下的 span 或 text）
        var authorEls = item.querySelectorAll('.author, [class*="author"] span, .text-s');
        var authorNames = [];
        authorEls.forEach(function(a) {
            var t = a.textContent.trim();
            // 过滤：作者名通常比较短，不像 metadata
            if (t && t.length > 1 && t.length < 80) authorNames.push(t);
        });
        // 去重（同一个 author 可能出现在多个 span 中）
        var seen = {};
        authorNames = authorNames.filter(function(n) { return seen[n] ? false : (seen[n] = true); });

        // 全文文本（用于提取期刊和日期）
        var fullText = item.textContent;
        // 清理：去掉多余空白
        fullText = fullText.replace(/\\s+/g, ' ').trim();

        // 从文本中提取期刊和年份
        // 模式: "期刊名  日期" 或 "期刊名Date"
        var journal = '';
        var year = '';

        // 提取日期：格式 "DD Month YYYY"
        var dateMatch = fullText.match(/(\\d{1,2}\\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\\s+\\d{4})/i);
        if (dateMatch) {
            var dateStr = dateMatch[1];
            var dateIdx = dateMatch.index;
            year = dateStr.match(/\\d{4}/)[0];
            // 期刊名 = 日期前面的一段文本，找最后一个大写开头的词序列
            var before = fullText.substring(0, dateIdx);
            // 去掉文章类型前缀
            before = before.replace(/^(?:Research article|Review article|Full text access|Open access|Open archive)\\s*/i, '');
            before = before.trim();
            // 从后往前找以大写字母开头的连续词作为期刊名
            var words = before.split(/\\s+/);
            var jWords = [];
            for (var w = words.length - 1; w >= 0; w--) {
                var word = words[w];
                // 大写开头 + 不是特殊关键词 → 期刊名的一部分
                if (/^[A-Z]/.test(word) && !/^(Abstract|Extracts|Figures|Export|View|PDF|Download|Full|Text|Access|[\\d,]+)$/i.test(word)) {
                    jWords.unshift(word);
                } else if (jWords.length > 0) {
                    // 遇到非期刊词，如果已经收集了足够期刊词就停
                    if (jWords.length >= 2) break;
                    jWords = [];
                }
            }
            journal = jWords.join(' ');
            if (journal.length > 70) journal = journal.substring(journal.length - 60);
        }

        // 备用：仅年份
        if (!year) {
            var yearOnly = fullText.match(/\\b(20\\d{2})\\b/);
            if (yearOnly) year = yearOnly[1];
        }

        // 备用：匹配已知期刊名模式
        if (!journal || journal.length < 3 || journal.length > 70) {
            var jMatch = fullText.match(/([A-Z][A-Za-z&]+(?:\\s+[A-Z][A-Za-z&]+){1,6})\\s*(?:(?:Studies|Research|Review|Journal|Letters|Management|Economics)\\b)/);
            if (jMatch) journal = jMatch[0];
        }

        // DOI
        var doiMatch = fullText.match(/10\\.\\d{4,}\\/[^\\s]+/);
        var doi = doiMatch ? doiMatch[0] : '';

        // Open Access
        var openAccess = /open access/i.test(fullText);

        results.push({
            idx: idx,
            title: title,
            pii: pii,
            link: link,
            authors: authorNames.join('; '),
            journal: journal,
            year: year,
            doi: doi,
            open_access: openAccess
        });
    });

    return JSON.stringify(results);
})()
"""


def _extract_results_from_dom(tab, max_results=25):
    """从渲染后的 ScienceDirect 搜索结果页 DOM 提取论文列表。"""
    raw = _evaluate(tab, _DOM_EXTRACT_JS, timeout_loops=25)
    try:
        items = json.loads(raw)
    except Exception:
        return []

    results = []
    seen = set()
    for item in items:
        pii = item.get("pii", "")
        if not pii or pii in seen:
            continue
        seen.add(pii)

        title = html_module.unescape(item.get("title", "")).strip()

        results.append({
            "title": title,
            "authors": item.get("authors", ""),
            "year": item.get("year", ""),
            "journal": item.get("journal", ""),
            "volume": "",
            "issue": "",
            "pages": "",
            "doi": item.get("doi", "") or pii,
            "pii": pii,
            "link": item.get("link", ""),
            "abstract": "",
            "open_access": item.get("open_access", False),
        })

        if len(results) >= max_results:
            break

    return results


# ── 搜索流程 ────────────────────────────────────────────────────────────────────

def cdp_search(query, count=25):
    """通过 CDP 搜索 ScienceDirect 并返回论文列表。"""
    print(f"\n[CDP 搜索]  关键词: {query}  (目标 {count} 篇)")

    # 1. 打开搜索页
    search_url = f"{BASE_URL}/search?qs={urllib.parse.quote(query)}&show={min(count, 100)}"
    print(f"  打开搜索页...")
    tab = _new_tab(search_url)

    # 2. 等待 Cloudflare + JS 渲染搜索结果
    print("  等待页面渲染 + Cloudflare 验证...")
    time.sleep(12)

    # 检查是否到达 ScienceDirect
    current_url = _evaluate(tab, "location.href", timeout_loops=10)
    print(f"  URL: {current_url[:120]}...")

    if "sciencedirect.com" not in current_url:
        print(f"  [错误] 未到达 ScienceDirect！")
        _close_tab(tab["id"])
        return []

    # 检查是否有搜索结果
    dom_count = _evaluate(tab, "document.querySelectorAll('.result-item-content').length", timeout_loops=10)
    print(f"  找到 {dom_count} 条 DOM 结果")

    if int(dom_count or 0) == 0:
        # 可能还在加载，再等等
        print("  等待更多时间...")
        time.sleep(8)
        dom_count = _evaluate(tab, "document.querySelectorAll('.result-item-content').length", timeout_loops=10)
        print(f"  找到 {dom_count} 条 DOM 结果")

    # 3. 提取
    print("  提取结果...")
    results = _extract_results_from_dom(tab, count)

    _close_tab(tab["id"])
    print(f"  共获取 {len(results)} 条结果")
    return results


# ── PDF 下载（CDP）───────────────────────────────────────────────────────────────

def _cdp_download_pdf(tab, pii, paper, pdf_dir, idx):
    """在单个标签页中通过 CDP 下载一篇 PDF。

    流程：提取 pdfft 链接 → 打开 PDF viewer → printToPDF
    调用前需确保 tab 已打开文章页并等待渲染完毕。
    """

    ws = _ws_connect(tab)

    # 步骤 1: 提取 pdfft 链接（含 md5/pid 参数）
    _cdp_send(ws, "Runtime.evaluate", {
        "expression": """
(function() {
    var a = document.querySelector('a[href*=\"pdfft\"]');
    return a ? a.href : '';
})()
""",
        "returnByValue": True
    })
    pdf_result = _cdp_recv(ws, timeout_loops=12)
    pdf_url = pdf_result.get("result", {}).get("result", {}).get("value", "")
    ws.close()

    if not pdf_url:
        return False, f"未找到 PDF 链接（可能为非 Elsevier 期刊）"

    # 步骤 3: 在新标签页打开 PDF URL，等待完全加载
    pdf_tab = _new_tab(pdf_url)
    if not pdf_tab:
        return False, "无法创建 PDF 标签页"

    print(f"    等待 PDF 渲染...")
    time.sleep(18)

    # 步骤 4: 短连接 printToPDF
    try:
        pws = _ws_connect(pdf_tab)
        _cdp_send(pws, "Page.enable")
        time.sleep(0.5)
        # 排空 enable 响应
        pws.settimeout(2)
        for _ in range(3):
            try:
                pws.recv()
            except Exception:
                pass

        _cdp_send(pws, "Page.printToPDF", {
            "printBackground": True,
            "paperWidth": 8.27,
            "paperHeight": 11.69,
        })
        pws.settimeout(30)
        pdf_data = ""
        for _ in range(15):
            try:
                msg = json.loads(pws.recv())
                if msg.get("id") == 1:
                    pdf_data = msg.get("result", {}).get("data", "")
                    break
            except Exception:
                break
        pws.close()
    except Exception as e:
        _close_tab(pdf_tab["id"])
        return False, f"PDF 获取异常: {e}"

    _close_tab(pdf_tab["id"])

    if not pdf_data:
        return False, "printToPDF 返回空数据"

    pdf_bytes = base64.b64decode(pdf_data)
    if len(pdf_bytes) < 10000:
        return False, f"PDF 太小 ({len(pdf_bytes)} 字节)，可能失败"

    # 保存
    filename = _make_pdf_filename(idx, paper)
    filepath = os.path.join(pdf_dir, filename)
    with open(filepath, "wb") as f:
        f.write(pdf_bytes)

    return True, f"已保存 ({len(pdf_bytes):,} 字节)"


def _make_pdf_filename(idx, paper):
    authors = paper.get("authors", "")
    first_author = (authors.split(";")[0].strip().split()[-1] if authors else "Unknown")
    year = paper.get("year", "")
    safe_title = re.sub(r'[\\/*?:"<>|]', "", paper.get("title", ""))[:60].strip()
    return f"{idx:03d}_{first_author}_{year}_{safe_title}.pdf"


def cdp_download_pdfs(results, output_dir):
    """通过 CDP 批量下载 PDF（每篇独立标签页）。"""
    pdf_dir = os.path.join(output_dir, "pdfs")
    os.makedirs(pdf_dir, exist_ok=True)

    print(f"\n[CDP PDF 下载]  共 {len(results)} 篇 → {pdf_dir}")

    success = fail = skip = 0

    for idx, paper in enumerate(results):
        pii = paper.get("pii", "")
        if not pii:
            print(f"  [{idx + 1}] 跳过（无 PII）")
            skip += 1
            continue

        title = paper.get("title", "")[:60]
        journal = paper.get("journal", "")
        print(f"  [{idx + 1}/{len(results)}] {title}...")

        # 先打开文章页获取 pdfft 链接
        article_tab = _new_tab(f"{BASE_URL}/science/article/pii/{pii}")
        if not article_tab:
            print(f"    ✗ 无法创建标签页")
            fail += 1
            continue

        time.sleep(8)

        ok, msg = _cdp_download_pdf(article_tab, pii, paper, pdf_dir, idx + 1)
        if ok:
            print(f"    [OK] {msg}")
            success += 1
        else:
            print(f"    [FAIL] {msg}")
            fail += 1

        _close_tab(article_tab["id"])

        if idx < len(results) - 1:
            time.sleep(5)

    print(f"\n[PDF 完成] 成功: {success}  失败: {fail}  跳过: {skip}")


# ── 保存 ────────────────────────────────────────────────────────────────────────

def _save_csv(results, filepath):
    fields = ["title", "authors", "year", "journal", "volume", "issue",
              "pages", "doi", "pii", "link", "abstract", "open_access"]
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)
    print(f"[CSV] 已保存 → {filepath}")


# ── 主入口 ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="ScienceDirect CDP 搜索与 PDF 下载工具 — 通过 Chrome DevTools Protocol 绕过 Cloudflare",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  python cdp_scraper.py "enterprise digital transformation"
  python cdp_scraper.py "enterprise digital transformation" 5 --download-pdfs
  python cdp_scraper.py "deep learning" 10 --output "D:/my_papers/"
  python cdp_scraper.py "machine learning" 3 -o ./downloads/ --download-pdfs
        """,
    )
    parser.add_argument("query", nargs="?", default="enterprise digital transformation",
                        help="搜索关键词（默认: enterprise digital transformation）")
    parser.add_argument("count", nargs="?", type=int, default=3,
                        help="最大抓取数量（默认: 3）")
    parser.add_argument("--download-pdfs", action="store_true",
                        help="搜索后下载 PDF")
    parser.add_argument("-o", "--output", default=None,
                        help="输出目录（默认: 脚本所在目录下的 results/）")

    args = parser.parse_args()
    query = args.query
    count = args.count
    download = args.download_pdfs

    # 自动检测代理
    proxy = _detect_proxy()

    # 启动目录（用户运行命令的目录）
    launch_dir = os.getcwd()

    # 检查 Chrome
    try:
        with urllib.request.urlopen(f"{BASE_CDP}/json/version", timeout=5) as r:
            info = json.loads(r.read())
            print(f"Chrome 就绪: {info.get('Browser', 'unknown')}")
    except Exception:
        print("[错误] Chrome 调试端口 9222 未开启！")
        print("请先运行: python extract_cookies_cdp.py")
        sys.exit(1)

    # 输出目录：用户指定 > 脚本目录下的 results/ > 启动目录
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if args.output:
        output_dir = os.path.abspath(args.output)
    else:
        output_dir = os.path.join(script_dir, "results")
    try:
        os.makedirs(output_dir, exist_ok=True)
    except Exception:
        output_dir = launch_dir
        os.makedirs(output_dir, exist_ok=True)

    # 搜索
    results = cdp_search(query, count)
    if not results:
        print("\n未获取到任何结果。")
        sys.exit(1)

    # 保存 CSV
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    safe_query = query.replace(" ", "_")[:30]
    csv_path = os.path.join(output_dir, f"{safe_query}_{timestamp}.csv")
    _save_csv(results, csv_path)

    # 同时在启动目录保存一份表格备份（仅当未手动指定输出目录时）
    if not args.output and os.path.abspath(output_dir) != os.path.abspath(launch_dir):
        try:
            launch_csv = os.path.join(launch_dir, f"{safe_query}_{timestamp}.csv")
            _save_csv(results, launch_csv)
        except Exception:
            pass

    # 打印结果
    print(f"\n{'=' * 60}")
    print(f"  搜索结果 ({len(results)} 篇)")
    print(f"{'=' * 60}")
    for i, r in enumerate(results):
        print(f"\n  {i + 1}. {r['title'][:100]}")
        print(f"     作者: {r['authors'][:80]}")
        print(f"     期刊: {r['journal']}, {r['year']}")
        print(f"     DOI: {r['doi']}")
        print(f"     链接: {r['link']}")

    # 下载 PDF（如果用户请求）
    if download:
        cdp_download_pdfs(results, output_dir)
    else:
        print(f"\n[提示] 未指定 --download-pdfs，仅保存搜索表格。")
        print(f"  表格位置: {csv_path}")

    print(f"\n完成！结果保存在: {output_dir}")
    return results


if __name__ == "__main__":
    main()
