"""Send a Telegram smoke-test notification using the current V7 wording."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from notifications.telegram_notify import send_telegram_message


def main() -> None:
    message = (
        "🧪 TradingBrain V7 通知測試\n"
        "用途: Telegram 通知鏈路驗證\n"
        "內容: 這是一則測試訊息，不代表實際開倉或策略訊號。"
    )
    ok = send_telegram_message(message)
    print("OK" if ok else "FAIL")


if __name__ == "__main__":
    main()
