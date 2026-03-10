"""Local launcher entry point for TradingBrain."""

import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LAUNCHER_PORT = 8899


def main() -> None:
    print("=" * 50)
    print("  TradingBrain Launcher")
    print("  Starting local control panel...")
    print("=" * 50)

    def open_browser() -> None:
        time.sleep(1.5)
        url = f"http://localhost:{LAUNCHER_PORT}"
        print(f"\n  Launcher URL: {url}")
        print("  If the browser does not open automatically, paste that URL into your browser.")
        print("  Press Ctrl+C to stop the launcher.\n")
        webbrowser.open(url)

    threading.Thread(target=open_browser, daemon=True).start()

    import uvicorn

    uvicorn.run(
        "launcher.server:app",
        host="127.0.0.1",
        port=LAUNCHER_PORT,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
