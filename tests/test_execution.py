"""Tests for execution utilities and trade execution flow."""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.execution.execution_engine import execute_trade, is_trading_enabled
from core.risk.risk_manager import RiskCheckResult
from core.strategy.base import TradeSignal
from notifications.line_notify import send_line_message


def test_is_trading_enabled():
    """Trading is enabled only for live mode with credentials, or demo with non-paper mode."""
    with patch("core.execution.execution_engine.BINANCE_TESTNET", True), patch(
        "core.execution.execution_engine.BINANCE_API_KEY", "key"
    ), patch("core.execution.execution_engine.TRADING_MODE", "paper"):
        assert is_trading_enabled() is False

    with patch("core.execution.execution_engine.BINANCE_TESTNET", True), patch(
        "core.execution.execution_engine.BINANCE_API_KEY", "key"
    ), patch("core.execution.execution_engine.TRADING_MODE", "live"):
        assert is_trading_enabled() is True

    with patch("core.execution.execution_engine.BINANCE_TESTNET", False), patch(
        "core.execution.execution_engine.BINANCE_API_KEY", "key"
    ), patch("core.execution.execution_engine.TRADING_MODE", "paper"):
        assert is_trading_enabled() is False

    with patch("core.execution.execution_engine.BINANCE_TESTNET", False), patch(
        "core.execution.execution_engine.BINANCE_API_KEY", "key"
    ), patch("core.execution.execution_engine.TRADING_MODE", "live"):
        assert is_trading_enabled() is True

    with patch("core.execution.execution_engine.BINANCE_API_KEY", ""):
        assert is_trading_enabled() is False


def test_line_send_when_empty_token():
    """LINE sending should fail fast when credentials are incomplete."""
    with patch("notifications.line_notify.LINE_CHANNEL_ACCESS_TOKEN", ""), patch(
        "notifications.line_notify.LINE_USER_ID", "user"
    ):
        assert send_line_message("test") is False
    with patch("notifications.line_notify.LINE_CHANNEL_ACCESS_TOKEN", "token"), patch(
        "notifications.line_notify.LINE_USER_ID", ""
    ):
        assert send_line_message("test") is False


async def _execute_trade_when_simulation_disabled() -> None:
    signal = TradeSignal(
        symbol="BTCUSDT",
        timeframe="15m",
        signal_type="LONG",
        strength=0.8,
        strategy_name="test",
    )
    risk_result = RiskCheckResult(
        passed=True,
        size_usdt=50,
        leverage=2,
        stop_loss=99000,
        take_profit=105000,
    )
    db = MagicMock()

    with patch("core.execution.execution_engine.is_trading_enabled", return_value=False):
        out = await execute_trade(signal, risk_result, 100000.0, db, "test")

    assert out is None
    db.insert_trade.assert_not_called()


def test_execute_trade_when_simulation_disabled():
    asyncio.run(_execute_trade_when_simulation_disabled())


async def _execute_trade_success_mock() -> None:
    signal = TradeSignal(
        symbol="BTCUSDT",
        timeframe="15m",
        signal_type="LONG",
        strength=0.8,
        strategy_name="test",
    )
    risk_result = RiskCheckResult(
        passed=True,
        size_usdt=100,
        leverage=2,
        stop_loss=99000,
        take_profit=105000,
    )
    db = MagicMock()
    db.insert_trade.return_value = 1

    async def mock_set_leverage(symbol, leverage):
        return None

    async def mock_place_market(symbol, side, qty):
        return 12345

    async def mock_place_sl(*args, **kwargs):
        return 12346

    async def mock_place_tp(*args, **kwargs):
        return 12347

    with patch("core.execution.execution_engine.is_trading_enabled", return_value=True), patch(
        "core.execution.execution_engine.BinanceFuturesClient"
    ) as klass:
        inst = MagicMock()
        inst.set_leverage = AsyncMock(side_effect=mock_set_leverage)
        inst.place_market_order = AsyncMock(side_effect=mock_place_market)
        inst.place_stop_loss = AsyncMock(side_effect=mock_place_sl)
        inst.place_take_profit = AsyncMock(side_effect=mock_place_tp)
        klass.return_value = inst

        out = await execute_trade(signal, risk_result, 100000.0, db, "test")

    assert out == 1
    db.insert_trade.assert_called_once()
    (trade_data,) = db.insert_trade.call_args[0]
    assert trade_data["symbol"] == "BTCUSDT"
    assert trade_data["side"] == "LONG"
    assert trade_data["status"] == "OPEN"


def test_execute_trade_success_mock():
    asyncio.run(_execute_trade_success_mock())


def test_binance_client_round_quantity():
    from core.execution.binance_client import _round_quantity

    assert _round_quantity(0.00123456, 0.001) == "0.001"
    assert _round_quantity(1.999, 0.1) == "1.9"
    assert _round_quantity(0.5, 0.01) == "0.5"
