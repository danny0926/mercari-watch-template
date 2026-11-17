"""手動通過駿河屋 Cloudflare 驗證的小工具。

開一個「有畫面」的 CloakBrowser，使用與無頭監聽完全相同的設定檔，
讓你手動點過「驗證您是人類」核取方塊。通過後 cf_clearance cookie 會寫入
專用設定檔，之後無頭監聽即可沿用，不再卡在驗證。

重要：請在你自己的終端機（一般 PowerShell/cmd）執行，不要透過自動化代理：

    cd D:\\vscode_python\\mercari-watch-template
    .\\.venv\\Scripts\\python.exe verify_surugaya.py

執行前建議確認駿河屋正處於冷卻（監聽不會同時開同一個設定檔）。
"""
import asyncio
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT))

from dotenv import load_dotenv
from browser_runtime import configure_browser_driver, configure_cloak_runtime, browser_child_environment
from surugaya_source import surugaya_search_url

WAIT_SECONDS = 420  # 最多等 7 分鐘讓你手動點過驗證


async def main() -> int:
    load_dotenv(PROJECT / ".env", override=False, interpolate=False)
    # 與無頭監聽相同：若套件 Playwright 的 Node 損壞，改用專案 Patchright 的 Node。
    configure_browser_driver()
    conf = configure_cloak_runtime()
    profile = conf["profile"]
    from cloakbrowser import launch_persistent_context_async
    from playwright.async_api import TimeoutError as BrowserTimeout

    context = await launch_persistent_context_async(
        str(profile), headless=False, humanize=True,
        browser_version=conf["version"], env=browser_child_environment(),
        args=[f"--disk-cache-dir={profile / 'disk-cache'}",
              f"--crash-dumps-dir={conf['temporary'] / 'crash-dumps'}",
              "--disable-breakpad", "--disable-crash-reporter"],
    )
    page = context.pages[0] if context.pages else await context.new_page()
    url = surugaya_search_url("フィギュア")
    print(f"已開啟駿河屋搜尋頁，請在視窗點過『驗證您是人類』：\n{url}", flush=True)
    await page.goto(url, wait_until="domcontentloaded", timeout=60000)

    def challenge_present() -> bool:
        from urllib.parse import urlparse
        return any(urlparse(f.url).hostname == "challenges.cloudflare.com" for f in page.frames)

    ok = False
    for _ in range(WAIT_SECONDS // 2):
        # 成功 = Cloudflare 挑戰消失、且駿河屋搜尋頁已出現（命中數或搜尋框）。
        if not challenge_present():
            try:
                if await page.locator('#search_header .hit, #search_header').count():
                    ok = True
                    break
            except BrowserTimeout:
                pass
        await page.wait_for_timeout(2000)
    if ok:
        await page.wait_for_timeout(1500)  # 讓 cookie 寫入設定檔
        print("✅ 驗證通過，搜尋結果已載入；cf_clearance 已存入設定檔，無頭監聽可沿用。", flush=True)
    else:
        print("⏱ 逾時：未偵測到搜尋結果（可能尚未點過驗證）。可重新執行再試。", flush=True)
    await context.close()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
