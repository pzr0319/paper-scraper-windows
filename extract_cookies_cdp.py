"""通过 Chrome CDP 提取 ScienceDirect Cookie 并保存为 JSON 文件。

用法：
    python extract_cookies_cdp.py [输出文件路径]

前提：Chrome 已通过机构账号登录 ScienceDirect。
此脚本会：
1. 检查 Chrome 调试端口是否已开启
2. 若未开启，先关旧 Chrome，再以调试模式启动
3. 通过 CDP websocket 提取 Cookie 并保存为 JSON
"""

import sys
import os
import json
import time
import tempfile
import shutil
import subprocess
import platform

CHROME_DEBUG_PORT = 9222
IS_WINDOWS = platform.system() == "Windows"

if IS_WINDOWS:
    CHROME_BIN = "C:/Program Files/Google/Chrome/Application/chrome.exe"
    DEFAULT_PROFILE = os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data\Default")
else:
    CHROME_BIN = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    DEFAULT_PROFILE = os.path.expanduser("~/Library/Application Support/Google/Chrome/Default")

TMP_PROFILE = os.path.join(tempfile.gettempdir(), "chrome_cdp_profile")


def _detect_proxy():
    """自动检测用户全局代理设置。

    检测顺序：
    1. 环境变量 HTTPS_PROXY / HTTP_PROXY
    2. Windows 注册表 Internet Settings
    3. macOS 系统代理设置

    返回代理 URL 字符串，未检测到返回 None。
    """
    for var in ("HTTPS_PROXY", "HTTP_PROXY"):
        val = os.environ.get(var, "")
        if val:
            print(f"  [代理检测] 从环境变量 {var} 发现: {val}")
            return val

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
                                if "://" not in proxy:
                                    proxy = f"http://{proxy}"
                                print(f"  [代理检测] 从 Windows 注册表发现: {proxy}")
                                return proxy
        except Exception:
            pass
    else:
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
                    print(f"  [代理检测] 从 macOS 系统代理发现: {proxy}")
                    return proxy
        except Exception:
            pass

    print("  [代理检测] 未检测到代理设置")
    return None


def is_chrome_debug_ready():
    import urllib.request
    try:
        urllib.request.urlopen(
            f"http://127.0.0.1:{CHROME_DEBUG_PORT}/json/version", timeout=2)
        return True
    except Exception:
        return False


def kill_chrome():
    print("  正在关闭现有 Chrome...")
    try:
        if IS_WINDOWS:
            subprocess.run(["taskkill", "/F", "/IM", "chrome.exe"],
                           capture_output=True, timeout=15)
        else:
            subprocess.run(["pkill", "-f", "Google Chrome"], timeout=10)
    except Exception:
        pass
    time.sleep(2)


def launch_chrome_with_debug():
    """启动带调试端口的 Chrome（使用原始用户 Profile，保留登录态）。"""
    print("  正在启动 Chrome（调试模式，使用原始 Profile）...")

    user_data_dir = os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data") if IS_WINDOWS else os.path.expanduser("~/Library/Application Support/Google/Chrome")

    # 清理原 Profile 的锁文件（旧 Chrome 已关闭）
    for lock in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        lf = os.path.join(user_data_dir, lock)
        try:
            os.remove(lf)
        except FileNotFoundError:
            pass

    # ── 启动 Chrome（自动检测系统代理） ─────────────────────────────
    proxy = _detect_proxy()
    cmd = [
        CHROME_BIN,
        f"--remote-debugging-port={CHROME_DEBUG_PORT}",
        f"--remote-allow-origins=http://127.0.0.1:{CHROME_DEBUG_PORT}",
        f"--user-data-dir={user_data_dir}",
        "--disable-blink-features=AutomationControlled",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if proxy:
        cmd.append(f"--proxy-server={proxy}")

    log_path = os.path.join(tempfile.gettempdir(), "chrome_cdp.log")
    try:
        with open(log_path, "w") as log_f:
            subprocess.Popen(cmd, stdout=log_f, stderr=subprocess.STDOUT,
                             creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if IS_WINDOWS else 0)
    except Exception as e:
        print(f"  [错误] 启动 Chrome 失败：{e}")
        return False

    # 等待调试端口就绪
    print("  等待 Chrome 调试端口就绪...")
    for i in range(45):
        time.sleep(1)
        if is_chrome_debug_ready():
            print(f"  Chrome 调试端口已就绪 ({i + 1}s)")
            return True
        if (i + 1) % 10 == 0:
            print(f"  等待中... ({i + 1}s)")

    print(f"  [错误] Chrome 在 45s 内未就绪，查看日志：{log_path}")
    return False


def extract_cookies(output_path):
    """通过 CDP websocket 提取 Cookie 并保存为 JSON。"""
    import websocket
    import urllib.request

    # 获取第一个标签页的 webSocketDebuggerUrl
    url = f"http://127.0.0.1:{CHROME_DEBUG_PORT}/json"
    with urllib.request.urlopen(url, timeout=10) as r:
        tabs = json.loads(r.read())

    if not tabs:
        print("[错误] 没有打开的标签页")
        return False

    ws_url = tabs[0].get("webSocketDebuggerUrl")
    if not ws_url:
        print("[错误] 无法获取 webSocketDebuggerUrl")
        return False

    print(f"  连接 CDP...")
    ws = websocket.create_connection(ws_url, timeout=15, suppress_origin=True)

    # 获取所有相关域的 Cookie
    all_cookies = []
    for domain in [
        "https://www.sciencedirect.com",
        "https://www.sciencedirectassets.com",
        "https://pdf.sciencedirectassets.com",
        "https://www.elsevier.com",
    ]:
        ws.send(json.dumps({
            "id": 1,
            "method": "Network.getCookies",
            "params": {"urls": [domain]}
        }))
        for _ in range(10):
            msg = json.loads(ws.recv())
            if msg.get("id") == 1:
                cookies = msg.get("result", {}).get("cookies", [])
                all_cookies.extend(cookies)
                break

    ws.close()

    if not all_cookies:
        print("[错误] 未提取到任何 Cookie。请确保 Chrome 中已登录 ScienceDirect")
        return False

    # 格式化为 JSON 数组（与 browser-cookie3 输出兼容）
    cookie_list = []
    for c in all_cookies:
        cookie_list.append({
            "name": c["name"],
            "value": c["value"],
            "domain": c.get("domain", ""),
        })

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(cookie_list, f, ensure_ascii=False, indent=2)

    print(f"  ✓ 已提取 {len(cookie_list)} 个 Cookie，保存至 {output_path}")
    return True


def main():
    output_path = sys.argv[1] if len(sys.argv) > 1 else "sd_cookies.json"

    # 步骤 1：确保 Chrome 调试端口可用
    if not is_chrome_debug_ready():
        print("Chrome 调试端口未开启，正在启动...")
        kill_chrome()
        if not launch_chrome_with_debug():
            print("请手动以调试模式启动 Chrome：")
            print(f'  "{CHROME_BIN}" --remote-debugging-port={CHROME_DEBUG_PORT}')
            sys.exit(1)

    # 步骤 1.5：打开 ScienceDirect 触发 Cookie 加载
    import urllib.request
    print("正在打开 ScienceDirect 页面...")
    try:
        create_url = f"http://127.0.0.1:{CHROME_DEBUG_PORT}/json/new?https://www.sciencedirect.com"
        req = urllib.request.Request(create_url, method="PUT")
        with urllib.request.urlopen(req, timeout=20) as r:
            tab = json.loads(r.read())
        print(f"  已打开 ScienceDirect 标签页")
        # 等待页面加载完成 + Cookie 写入
        time.sleep(5)
        # 关闭这个临时标签页
        try:
            urllib.request.urlopen(
                f"http://127.0.0.1:{CHROME_DEBUG_PORT}/json/close/{tab['id']}", timeout=10)
        except Exception:
            pass
    except Exception as e:
        print(f"  [警告] 打开页面前失败：{e}（将继续尝试提取 Cookie）")

    # 步骤 2：提取 Cookie
    print("正在通过 CDP 提取 Cookie...")
    if not extract_cookies(output_path):
        sys.exit(1)

    print(f"\n完成！现在可以运行：")
    print(f'  HTTPS_PROXY=http://127.0.0.1:7897 python sd_scraper.py -m keyword -q "enterprise digital transformation" -n 3 --cookies {output_path} --format csv')


if __name__ == "__main__":
    main()
