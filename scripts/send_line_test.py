"""Legacy compatibility entrypoint that now forwards to the Telegram test script."""

from scripts.send_telegram_test import main


if __name__ == "__main__":
    main()
