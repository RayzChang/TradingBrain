"""LINE Messaging API push helper."""

import json

import httpx
from loguru import logger

from config.settings import LINE_CHANNEL_ACCESS_TOKEN, LINE_USER_ID

LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"


def send_line_message(text: str) -> bool:
    """Send a UTF-8 text message to the configured LINE user."""
    if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_USER_ID:
        logger.debug("LINE token or user id is missing, skip sending message.")
        return False

    payload = {
        "to": LINE_USER_ID,
        "messages": [{"type": "text", "text": text[:5000]}],
    }
    headers = {
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json; charset=utf-8",
    }

    try:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        with httpx.Client(timeout=10.0) as client:
            response = client.post(LINE_PUSH_URL, content=body, headers=headers)
        if response.status_code != 200:
            logger.warning(
                f"LINE send failed: status={response.status_code} body={response.text}"
            )
            return False
        logger.debug("LINE message sent successfully.")
        return True
    except Exception as exc:
        logger.error(f"LINE send failed with exception: {exc}")
        return False
