"""
TradingBrain 控制台 — 整合啟動器

啟動方式:
    python launcher.py

會在 http://localhost:8899 開啟控制台介面，
自動用瀏覽器打開。

功能:
  - 設定 .env（API Key、交易模式、槓桿等）
  - 一鍵設定交易所（Setup Testnet）
  - 啟動 / 停止交易大腦
  - 開啟 Web 儀表板
  - 即時查看系統日誌
"""

import sys
import time
import threading
import webbrowser
from pathlib import Path

# 確保專案根在 path
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


LAUNCHER_PORT = 8899


def main():
    print("=" * 50)
    print("  TradingBrain 控制台")
    print("  啟動中...")
    print("=" * 50)

    # 延遲開啟瀏覽器（等 server 起來）
    def open_browser():
        time.sleep(1.5)
        url = f"http://localhost:{LAUNCHER_PORT}"
        print(f"\n  🌐 控制台已開啟: {url}")
        print("  （如果瀏覽器沒有自動跳出，請手動開啟上面的網址）")
        print("  按 Ctrl+C 可關閉控制台\n")
        webbrowser.open(url)

    threading.Thread(target=open_browser, daemon=True).start()

    # 啟動 FastAPI
    import uvicorn
    uvicorn.run(
        "launcher.server:app",
        host="127.0.0.1",
        port=LAUNCHER_PORT,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
