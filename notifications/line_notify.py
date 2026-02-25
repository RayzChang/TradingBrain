"""
LINE Messaging API 推送模組

用於每日報告與心跳異常通知。靜默模式：僅在異常時發送心跳以節省免費額度。
"""

import httpx
from loguru import logger

from config.settings import LINE_CHANNEL_ACCESS_TOKEN, LINE_USER_ID

LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"


def send_line_message(text: str) -> bool:
    """
    使用 LINE Messaging API 推送文字訊息給設定好的 USER_ID。

    Args:
        text: 要發送的純文字內容（LINE 單則上限約 5000 字元）

    Returns:
        True 表示發送成功，False 表示未發送（未設定 token/user_id）或發送失敗
    """
    if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_USER_ID:
        logger.debug("LINE 未設定 CHANNEL_ACCESS_TOKEN 或 USER_ID，跳過發送")
        return False

    payload = {
        "to": LINE_USER_ID,
        "messages": [{"type": "text", "text": text[:5000]}],
    }
    headers = {
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(LINE_PUSH_URL, json=payload, headers=headers)
        if resp.status_code != 200:
            logger.warning(f"LINE 發送失敗: status={resp.status_code} body={resp.text}")
            return False
        logger.debug("LINE 訊息已發送")
        return True
    except Exception as e:
        logger.error(f"LINE 發送異常: {e}")
        return False
