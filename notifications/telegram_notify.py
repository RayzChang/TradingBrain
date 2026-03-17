"""Telegram Bot API push helper."""

import httpx
from loguru import logger

from config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


def send_telegram_message(text: str) -> bool:
    """Send a text message to the configured Telegram chat."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.debug("Telegram bot token or chat id is missing, skip sending message.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text[:4096],
    }

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(url, json=payload)
        if response.status_code != 200:
            logger.warning(
                f"Telegram send failed: status={response.status_code} body={response.text}"
            )
            return False
        body = response.json()
        if not body.get("ok", False):
            logger.warning(f"Telegram send failed: body={body}")
            return False
        logger.debug("Telegram message sent successfully.")
        return True
    except Exception as exc:
        logger.error(f"Telegram send failed with exception: {exc}")
        return False
