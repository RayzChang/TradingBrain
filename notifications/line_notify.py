"""Backward-compatible LINE notifier shim that now forwards to Telegram."""

from notifications.telegram_notify import send_telegram_message


def send_line_message(text: str) -> bool:
    """Preserve old imports while routing all notifications to Telegram."""
    return send_telegram_message(text)
