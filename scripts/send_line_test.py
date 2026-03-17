"""Send a UTF-8 Telegram test message from a real source file."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from notifications.telegram_notify import send_telegram_message


def main() -> None:
    message = (
        "🧪 TradingBrain V5 測試通知\n"
        "這是一則中文測試訊息。\n"
        "如果你看到這段文字，代表 LINE 推播正常。"
    )
    ok = send_telegram_message(message)
    print("OK" if ok else "FAIL")


if __name__ == "__main__":
    main()
