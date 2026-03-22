"""Tests for execution utilities and trade execution flow."""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.execution.execution_engine import execute_trade, is_trading_enabled
from core.risk.risk_manager import RiskCheckResult
from core.strategy.base import TradeSignal
from notifications.telegram_notify import send_telegram_message


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


def test_telegram_send_when_empty_token():
    """Telegram sending should fail fast when credentials are incomplete."""
    with patch("notifications.telegram_notify.TELEGRAM_BOT_TOKEN", ""), patch(
        "notifications.telegram_notify.TELEGRAM_CHAT_ID", "user"
    ):
        assert send_telegram_message("test") is False
    with patch("notifications.telegram_notify.TELEGRAM_BOT_TOKEN", "token"), patch(
        "notifications.telegram_notify.TELEGRAM_CHAT_ID", ""
    ):
        assert send_telegram_message("test") is False


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
        effective_risk_pct=0.016,
        sl_atr_mult=1.5,
        structure_stop_floor_triggered=True,
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
    ) as klass, patch(
        "core.execution.execution_engine.send_telegram_message"
    ) as send_mock:
        inst = MagicMock()
        inst.supports_algo_orders.return_value = True
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
    assert trade_data["effective_risk_pct"] == 0.016
    assert trade_data["sl_atr_mult"] == 1.5
    assert trade_data["structure_stop_floor_triggered"] == 1
    send_mock.assert_called_once()
    test_message = send_mock.call_args.args[0]
    assert "測試" in test_message
    assert "BTCUSDT" in test_message
    assert "LONG" in test_message


def test_execute_trade_success_mock():
    asyncio.run(_execute_trade_success_mock())


def test_build_trade_open_message_uses_test_label_for_test_strategy():
    from core.execution.execution_engine import _build_trade_open_message

    message = _build_trade_open_message(
        is_test=True,
        version="V7",
        mode="Testnet",
        symbol="BTCUSDT",
        side="LONG",
        strategy_name="test",
        strategy_family="test",
        margin_cost=50,
        size_usdt=100,
        leverage=2,
        entry_price=100000.0,
        soft_stop_loss=99000.0,
        hard_stop_loss=98500.0,
        soft_stop_required_closes=2,
        tp1=101000.0,
        tp2=102000.0,
        tp3=103000.0,
    )

    assert "測試" in message
    assert "BTCUSDT" in message
    assert "LONG" in message
    assert "開倉" not in message.splitlines()[0]


async def _execute_trade_breakout_profile_uses_profile_tp1_qty() -> None:
    signal = TradeSignal(
        symbol="BTCUSDT",
        timeframe="15m",
        signal_type="LONG",
        strength=0.8,
        strategy_name="breakout_retest",
    )
    risk_result = RiskCheckResult(
        passed=True,
        size_usdt=100,
        leverage=2,
        stop_loss=99000,
        take_profit=105000,
        tp1=101000,
        tp2=102000,
        tp3=103000,
    )
    db = MagicMock()
    db.insert_trade.return_value = 1

    with patch("core.execution.execution_engine.is_trading_enabled", return_value=True), patch(
        "core.execution.execution_engine.BinanceFuturesClient"
    ) as klass, patch(
        "core.execution.execution_engine.send_telegram_message"
    ):
        inst = MagicMock()
        inst.supports_algo_orders.return_value = True
        inst.set_leverage = AsyncMock(return_value=None)
        inst.place_market_order = AsyncMock(return_value=12345)
        inst.place_stop_loss = AsyncMock(return_value=12346)
        inst.place_take_profit = AsyncMock(return_value=12347)
        klass.return_value = inst

        out = await execute_trade(signal, risk_result, 100000.0, db, "breakout_retest")

    assert out == 1
    inst.place_take_profit.assert_awaited_once()
    args = inst.place_take_profit.await_args.args
    assert args[0] == "BTCUSDT"
    assert args[1] == "SELL"
    assert args[2] == 0.0004
    assert args[3] == 101000


def test_execute_trade_breakout_profile_uses_profile_tp1_qty():
    asyncio.run(_execute_trade_breakout_profile_uses_profile_tp1_qty())


async def _execute_trade_testnet_local_protection() -> None:
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

    with patch("core.execution.execution_engine.is_trading_enabled", return_value=True), patch(
        "core.execution.execution_engine.BinanceFuturesClient"
    ) as klass, patch(
        "core.execution.execution_engine.send_telegram_message"
    ):
        inst = MagicMock()
        inst.supports_algo_orders.return_value = False
        inst.set_leverage = AsyncMock(return_value=None)
        inst.place_market_order = AsyncMock(return_value=12345)
        inst.place_stop_loss = AsyncMock(return_value=12346)
        inst.place_take_profit = AsyncMock(return_value=12347)
        klass.return_value = inst

        out = await execute_trade(signal, risk_result, 100000.0, db, "test")

    assert out == 1
    inst.place_market_order.assert_awaited_once()
    inst.place_stop_loss.assert_not_called()
    inst.place_take_profit.assert_not_called()


def test_execute_trade_testnet_local_protection():
    asyncio.run(_execute_trade_testnet_local_protection())


def test_binance_client_round_quantity():
    from core.execution.binance_client import _round_quantity

    assert _round_quantity(0.00123456, 0.001) == "0.001"
    assert _round_quantity(1.999, 0.1) == "1.9"
    assert _round_quantity(0.5, 0.01) == "0.5"
