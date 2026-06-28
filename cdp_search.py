"""通过 Chrome CDP 直接搜索 ScienceDirect 并提取结果，绕过 Cloudflare JS Challenge。

用法：
    python cdp_search.py "enterprise digital transformation" 3

依赖：websocket-client (已安装)
前提：Chrome 调试端口 9222 已开启
"""

import sys
import json
import time
import websocket
import urllib.request
import re


def cdp_search(query, count=3):
    """通过 CDP 在 ScienceDirect 搜索关键词并返回结果。"""
    base_url = "http://127.0.0.1:9222"

    # ── 辅助函数 ────────────────────────────────────────────────
    def new_tab(url=None):
        if url:
            req = urllib.request.Request(
                f"{base_url}/json/new?{urllib.request.quote(url, safe=':/?&=%')}",
                method="PUT")
        else:
            req = urllib.request.Request(f"{base_url}/json/new", method="PUT")
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())

    def close_tab(page_id):
        try:
            urllib.request.urlopen(f"{base_url}/json/close/{page_id}", timeout=10)
        except Exception:
            pass

    def get_page_url(tab):
        ws = websocket.create_connection(
            tab["webSocketDebuggerUrl"], timeout=30, suppress_origin=True)
        ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                           "params": {"expression": "location.href", "returnByValue": True}}))
        result = ""
        for _ in range(15):
            msg = json.loads(ws.recv())
            if msg.get("id") == 1:
                result = msg.get("result", {}).get("result", {}).get("value", "")
                break
        ws.close()
        return result

    def get_page_text(tab):
        """获取页面 body innerText。"""
        ws = websocket.create_connection(
            tab["webSocketDebuggerUrl"], timeout=30, suppress_origin=True)
        ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                           "params": {"expression": "document.body.innerText", "returnByValue": True}}))
        result = ""
        for _ in range(20):
            msg = json.loads(ws.recv())
            if msg.get("id") == 1:
                result = msg.get("result", {}).get("result", {}).get("value", "")
                break
        ws.close()
        return result

    def get_page_html(tab):
        """获取页面完整 HTML。"""
        ws = websocket.create_connection(
            tab["webSocketDebuggerUrl"], timeout=30, suppress_origin=True)
        ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                           "params": {"expression": "document.documentElement.outerHTML", "returnByValue": True}}))
        result = ""
        for _ in range(30):
            msg = json.loads(ws.recv())
            if msg.get("id") == 1:
                result = msg.get("result", {}).get("result", {}).get("value", "")
                break
        ws.close()
        return result

    def extract_results_from_html(html):
        """从 ScienceDirect 搜索结果页 HTML 中提取论文列表。"""
        results = []
        seen_piis = set()

        # 匹配搜索结果卡片 - ScienceDirect 的 result-item 结构
        # 每个结果在 <li class="result-item"> 或 <div class="result-item-content"> 中
        import html as html_module

        # 方法1: 从 INITIAL_STATE JSON 中提取 (最可靠)
        m = re.search(r'window\.__INITIAL_STATE__\s*=\s*({.*?});\s*</script>', html, re.DOTALL)
        if not m:
            m = re.search(r'"searchResults":\s*(\[.*?\])', html, re.DOTALL)
            if m:
                try:
                    items = json.loads(m.group(1))
                except Exception:
                    items = []
            else:
                items = []
        else:
            try:
                state = json.loads(m.group(1))
                items = state.get("searchResults", {}).get("results", [])
            except Exception:
                items = []

        for item in items:
            pii = item.get("pii", "")
            if not pii or pii in seen_piis:
                continue
            seen_piis.add(pii)

            # 提取标题
            title = ""
            if isinstance(item.get("title"), dict):
                title = item["title"].get("#text", "") or item["title"].get("text", "")
            elif isinstance(item.get("title"), str):
                title = item["title"]
            if not title:
                title = item.get("dc:title", "")

            # 提取作者
            authors = ""
            authors_list = item.get("authors", [])
            if isinstance(authors_list, list):
                authors = "; ".join(
                    a.get("name", "") if isinstance(a, dict) else str(a)
                    for a in authors_list
                )
            elif isinstance(authors_list, str):
                authors = authors_list

            # 提取日期
            date = item.get("coverDate", "") or item.get("publicationDate", "")
            year = date[:4] if date else ""

            # 提取链接
            link = ""
            if pii:
                link = f"https://www.sciencedirect.com/science/article/pii/{pii}"

            # PDF 链接
            pdf_info = item.get("pdfLink", {}) or item.get("fullTextLink", {})
            pdf_link = pdf_info.get("downloadLink", "") if isinstance(pdf_info, dict) else ""

            result = {
                "title": html_module.unescape(title).strip(),
                "authors": authors,
                "year": year,
                "journal": item.get("publicationName", "") or item.get("sourceTitle", ""),
                "volume": item.get("volume", ""),
                "issue": item.get("issue", ""),
                "pages": item.get("pages", ""),
                "doi": item.get("doi", "") or item.get("pii", ""),
                "pii": pii,
                "link": link,
                "pdf_link": pdf_link,
                "abstract": "",
                "open_access": bool(item.get("openAccess", False)),
            }
            results.append(result)

        return results

    # ── 主流程 ──────────────────────────────────────────────────
    print(f"\n[CDP 搜索]  关键词: {query}  (目标 {count} 篇)")

    # 1. 打开搜索页面（带结果数量参数）
    search_url = f"https://www.sciencedirect.com/search?qs={urllib.request.quote(query)}&show={min(count, 100)}"
    print(f"  打开搜索页...")
    tab = new_tab(search_url)
    print("  等待页面加载 + Cloudflare 验证...")
    time.sleep(10)

    # 检查是否到达 ScienceDirect
    current_url = get_page_url(tab)
    print(f"  落地 URL: {current_url[:120]}...")

    if "sciencedirect.com" not in current_url:
        print(f"  [错误] 未到达 ScienceDirect")
        close_tab(tab["id"])
        return []

    # 2. 获取页面 HTML 并提取结果
    print("  提取页面数据...")
    html = get_page_html(tab)
    print(f"  页面大小: {len(html):,} 字节")

    all_results = extract_results_from_html(html)

    close_tab(tab["id"])

    print(f"\n[完成] 共获取 {len(all_results)} 条结果")
    return all_results[:count]


def save_csv(results, filepath):
    import csv
    fields = ["title", "authors", "year", "journal", "volume", "issue",
              "pages", "doi", "pii", "link", "abstract", "open_access"]
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)
    print(f"[CSV] 已保存 → {filepath}")


if __name__ == "__main__":
    query = sys.argv[1] if len(sys.argv) > 1 else "enterprise digital transformation"
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 3

    results = cdp_search(query, count)

    if results:
        output = f"results/cdp_{query.replace(' ', '_')[:40]}_{time.strftime('%Y%m%d_%H%M%S')}.csv"
        import os
        os.makedirs("results", exist_ok=True)
        save_csv(results, output)

        print("\n── 搜索结果 ──")
        for i, r in enumerate(results):
            print(f"\n  {i+1}. {r['title'][:100]}")
            print(f"     作者: {r['authors'][:80]}")
            print(f"     期刊: {r['journal']}, {r['year']}")
            print(f"     DOI: {r['doi']}")
            print(f"     PII: {r['pii']}")
            print(f"     链接: {r['link']}")
    else:
        print("\n未获取到任何结果。")
        sys.exit(1)
