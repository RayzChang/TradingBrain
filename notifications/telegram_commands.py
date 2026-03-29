"""Telegram Bot command handler — polls for user commands and replies."""

import asyncio
from datetime import datetime

import httpx
from loguru import logger

from config.settings import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    BINANCE_TESTNET,
    TRADING_MODE,
    APP_TIMEZONE,
    APP_TIMEZONE_NAME,
)


_BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
_POLL_INTERVAL = 1.5  # seconds
_MAX_POLL_BACKOFF = 30.0
_TRANSIENT_POLL_ERRORS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadError,
    httpx.ReadTimeout,
    httpx.RemoteProtocolError,
)


def _reply(chat_id: str, text: str) -> None:
    """Send a reply to a specific chat."""
    if not TELEGRAM_BOT_TOKEN:
        return
    try:
        with httpx.Client(timeout=10.0) as client:
            client.post(
                f"{_BASE_URL}/sendMessage",
                json={"chat_id": chat_id, "text": text[:4096]},
            )
    except Exception as exc:
        logger.error(f"Telegram reply failed: {exc}")


class TelegramCommandHandler:
    """Long-poll Telegram for /commands and reply with live data."""

    def __init__(self, brain):
        """brain is the TradingBrainEngine instance."""
        self.brain = brain
        self._offset = 0
        self._poll_failures = 0

    async def start(self) -> None:
        """Start polling loop — run as asyncio task."""
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            logger.info("Telegram commands disabled (no token/chat_id)")
            return
        logger.info("📱 Telegram 指令監聽啟動")
        while True:
            sleep_seconds = _POLL_INTERVAL
            try:
                await self._poll()
                self._record_poll_success()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                sleep_seconds = self._record_poll_failure(exc)
            await asyncio.sleep(sleep_seconds)

    def _poll_backoff_seconds(self) -> float:
        """Return the retry delay for the current transient failure streak."""
        exponent = min(max(self._poll_failures - 1, 0), 4)
        return min(_POLL_INTERVAL * (2**exponent), _MAX_POLL_BACKOFF)

    def _record_poll_failure(self, exc: Exception) -> float:
        """Record a polling failure and choose log level / retry delay."""
        self._poll_failures += 1
        retry_in = self._poll_backoff_seconds()

        if isinstance(exc, _TRANSIENT_POLL_ERRORS):
            if (
                self._poll_failures == 1
                or self._poll_failures in {3, 10}
                or self._poll_failures % 30 == 0
            ):
                logger.warning(
                    "Telegram poll transient network error "
                    f"({type(exc).__name__}) failure #{self._poll_failures}; "
                    f"retrying in {retry_in:.1f}s: {exc!r}"
                )
            return retry_in

        logger.exception(
            f"Telegram poll error ({type(exc).__name__}): {exc!r}"
        )
        return retry_in

    def _record_poll_success(self) -> None:
        """Reset failure streak after a successful poll."""
        if self._poll_failures:
            logger.info(
                "Telegram poll recovered after "
                f"{self._poll_failures} consecutive failure(s)"
            )
            self._poll_failures = 0

    async def _poll(self) -> None:
        """Fetch new updates via getUpdates."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{_BASE_URL}/getUpdates",
                params={"offset": self._offset, "timeout": 20},
            )
        if resp.status_code != 200:
            return
        data = resp.json()
        for update in data.get("result", []):
            self._offset = update["update_id"] + 1
            msg = update.get("message", {})
            chat_id = str(msg.get("chat", {}).get("id", ""))
            text = (msg.get("text") or "").strip()
            # Only respond to the configured chat
            if chat_id != TELEGRAM_CHAT_ID:
                continue
            if text.startswith("/"):
                await self._handle(chat_id, text)

    async def _handle(self, chat_id: str, text: str) -> None:
        """Dispatch command."""
        cmd = text.split()[0].lower()
        handlers = {
            "/balance": self._cmd_balance,
            "/資金": self._cmd_balance,
            "/pos": self._cmd_positions,
            "/持倉": self._cmd_positions,
            "/pnl": self._cmd_pnl,
            "/損益": self._cmd_pnl,
            "/status": self._cmd_status,
            "/狀態": self._cmd_status,
            "/help": self._cmd_help,
            "/指令": self._cmd_help,
        }
        handler = handlers.get(cmd)
        if handler:
            await handler(chat_id)
        else:
            _reply(chat_id, f"❓ 未知指令: {cmd}\n輸入 /指令 查看可用指令")

    # ── Commands ──────────────────────────────────────────

    async def _cmd_balance(self, chat_id: str) -> None:
        """💰 查詢交易所餘額"""
        if not self.brain.binance_client:
            _reply(chat_id, "⚠️ 交易所未連線")
            return
        try:
            bal = await self.brain.binance_client.get_balance()
            mode = "DEMO" if BINANCE_TESTNET else "LIVE"
            _reply(chat_id, f"💰 餘額 [{mode}]\n💵 {bal:,.2f} USDT")
        except Exception as exc:
            _reply(chat_id, f"❌ 查詢失敗: {exc}")

    async def _cmd_positions(self, chat_id: str) -> None:
        """📦 查詢未平倉位"""
        # DB open trades
        db_trades = self.brain.db.get_open_trades() if self.brain.db else []

        # Exchange positions
        exchange_positions = []
        if self.brain.binance_client:
            try:
                exchange_positions = await self.brain.binance_client.get_positions()
            except Exception:
                pass

        if not db_trades and not exchange_positions:
            _reply(chat_id, "📦 目前無持倉")
            return

        lines = ["📦 持倉一覽\n"]
        for t in db_trades:
            symbol = t.get("symbol", "?")
            side = t.get("side", "?")
            entry = float(t.get("entry_price", 0))
            side_emoji = "🟢" if side == "LONG" else "🔴"
            tp_stage = int(t.get("tp_stage", 0))
            stage_label = f"TP{tp_stage}" if tp_stage > 0 else "持倉中"

            # Try to get current price from exchange
            pnl_str = ""
            if self.brain.binance_client and entry:
                try:
                    price = await self.brain.binance_client.get_ticker_price(symbol)
                    if price:
                        leverage = int(t.get("leverage", 1))
                        margin = float(t.get("margin_cost", 0)) or (float(t.get("size_usdt", 0)) / leverage if leverage else 0)
                        if side == "LONG":
                            pnl_pct = (price - entry) / entry * 100
                        else:
                            pnl_pct = (entry - price) / entry * 100
                        pnl_u = margin * leverage * pnl_pct / 100
                        pnl_emoji = "📈" if pnl_pct >= 0 else "📉"
                        pnl_str = f" | {pnl_emoji} {pnl_pct:+.2f}% ({pnl_u:+.1f}U)"
                except Exception:
                    pass

            lines.append(f"{side_emoji} {symbol} {side} | 入場 {entry:.4f} | {stage_label}{pnl_str}")

        _reply(chat_id, "\n".join(lines))

    async def _cmd_pnl(self, chat_id: str) -> None:
        """💰 查詢今日損益"""
        if not self.brain.db:
            _reply(chat_id, "⚠️ 資料庫未連線")
            return
        daily_pnl = self.brain.db.get_daily_pnl(tz=APP_TIMEZONE)
        trades = self.brain.db.get_trades_today(tz=APP_TIMEZONE)
        closed = [t for t in trades if t.get("status") == "CLOSED"]
        wins = sum(1 for t in closed if float(t.get("pnl", 0)) > 0)
        win_rate = (wins / len(closed) * 100) if closed else 0

        pnl_emoji = "💚" if daily_pnl >= 0 else "💔"
        now = datetime.now(APP_TIMEZONE).strftime("%H:%M")

        msg = (
            f"📊 今日損益 ({APP_TIMEZONE_NAME} {now})\n"
            f"{pnl_emoji} {daily_pnl:+.2f} USDT\n"
            f"📋 {len(closed)}筆已平 | 勝率 {win_rate:.0f}%"
        )
        _reply(chat_id, msg)

    async def _cmd_status(self, chat_id: str) -> None:
        """📡 系統狀態"""
        mode = "DEMO" if BINANCE_TESTNET else "LIVE"
        trade_mode = TRADING_MODE
        open_count = len(self.brain.db.get_open_trades()) if self.brain.db else 0

        bal_str = ""
        if self.brain.binance_client:
            try:
                bal = await self.brain.binance_client.get_balance()
                bal_str = f"\n💵 餘額: {bal:,.2f} USDT"
            except Exception:
                pass

        msg = (
            f"📡 系統狀態\n"
            f"🏷 V10 [{mode}] | 模式: {trade_mode}\n"
            f"📦 持倉: {open_count}{bal_str}\n"
            f"🕐 {datetime.now(APP_TIMEZONE).strftime('%Y-%m-%d %H:%M')} ({APP_TIMEZONE_NAME})"
        )
        _reply(chat_id, msg)

    async def _cmd_help(self, chat_id: str) -> None:
        """📖 指令列表"""
        msg = (
            "📖 TradingBrain V10 指令選單\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "💰 /資金 (/balance)\n"
            "查詢交易所即時 USDT 餘額，確認目前可用資金\n\n"
            "📦 /持倉 (/pos)\n"
            "列出所有未平倉位，含幣種、方向、入場價、當前盈虧% 及套保進度 (TP1/TP2/TP3)\n\n"
            "📊 /損益 (/pnl)\n"
            "今日已實現損益總額、平倉筆數、勝率統計\n\n"
            "📡 /狀態 (/status)\n"
            "系統總覽：運行模式 (DEMO/LIVE)、持倉數、餘額、目前時間\n\n"
            "📖 /指令 (/help)\n"
            "顯示本選單\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "💡 中英文指令皆可使用"
        )
        _reply(chat_id, msg)
