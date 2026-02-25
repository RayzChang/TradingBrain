"""
第八階段測試 — 模擬交易執行層

驗證: 執行引擎開關、LINE 發送（未設定時跳過）、持倉同步/止損檢查邏輯（mock）
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.execution.execution_engine import execute_trade, _is_simulation_trading_enabled
from core.strategy.base import TradeSignal
from core.risk.risk_manager import RiskCheckResult
from notifications.line_notify import send_line_message


def test_is_simulation_trading_enabled():
    """模擬交易僅在 Testnet 且 API Key 設定時啟用"""
    with patch("core.execution.execution_engine.BINANCE_TESTNET", True), patch(
        "core.execution.execution_engine.BINANCE_API_KEY", "key"
    ):
        assert _is_simulation_trading_enabled() is True
    with patch("core.execution.execution_engine.BINANCE_TESTNET", False), patch(
        "core.execution.execution_engine.BINANCE_API_KEY", "key"
    ):
        assert _is_simulation_trading_enabled() is False
    with patch("core.execution.execution_engine.BINANCE_TESTNET", True), patch(
        "core.execution.execution_engine.BINANCE_API_KEY", ""
    ):
        assert _is_simulation_trading_enabled() is False
    print("  [PASS] _is_simulation_trading_enabled")


def test_line_send_when_empty_token():
    """LINE token 或 user_id 為空時不發送、回傳 False"""
    with patch("notifications.line_notify.LINE_CHANNEL_ACCESS_TOKEN", ""), patch(
        "notifications.line_notify.LINE_USER_ID", "user"
    ):
        assert send_line_message("test") is False
    with patch("notifications.line_notify.LINE_CHANNEL_ACCESS_TOKEN", "token"), patch(
        "notifications.line_notify.LINE_USER_ID", ""
    ):
        assert send_line_message("test") is False
    print("  [PASS] send_line_message 未設定時跳過")


async def test_execute_trade_when_simulation_disabled():
    """模擬交易關閉時 execute_trade 不呼叫交易所、回傳 None"""
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

    with patch("core.execution.execution_engine._is_simulation_trading_enabled", return_value=False):
        out = await execute_trade(signal, risk_result, 100000.0, db, "test")
    assert out is None
    db.insert_trade.assert_not_called()
    print("  [PASS] execute_trade 未啟用時不下單")


async def test_execute_trade_success_mock():
    """模擬交易啟用時：mock client 下單成功後應 insert_trade"""
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
        pass

    async def mock_place_market(symbol, side, qty):
        return 12345

    async def mock_place_sl(*args, **kwargs):
        return 12346

    async def mock_place_tp(*args, **kwargs):
        return 12347

    with patch("core.execution.execution_engine._is_simulation_trading_enabled", return_value=True):
        with patch("core.execution.execution_engine.BinanceFuturesClient") as Klass:
            inst = MagicMock()
            inst.set_leverage = AsyncMock(side_effect=mock_set_leverage)
            inst.place_market_order = AsyncMock(side_effect=mock_place_market)
            inst.place_stop_loss = AsyncMock(side_effect=mock_place_sl)
            inst.place_take_profit = AsyncMock(side_effect=mock_place_tp)
            Klass.return_value = inst

            out = await execute_trade(signal, risk_result, 100000.0, db, "test")

    assert out == 1
    db.insert_trade.assert_called_once()
    (trade_data,) = db.insert_trade.call_args[0]
    assert trade_data["symbol"] == "BTCUSDT"
    assert trade_data["side"] == "LONG"
    assert trade_data["status"] == "OPEN"
    print("  [PASS] execute_trade 成功時 insert_trade 被呼叫")


def test_binance_client_round_quantity():
    """倉位數量依 stepSize 捨入（向 step 倍數捨去）"""
    from core.execution.binance_client import _round_quantity
    assert _round_quantity(0.00123456, 0.001) == "0.001"
    assert _round_quantity(1.999, 0.1) == "1.9"
    assert _round_quantity(0.5, 0.01) == "0.5"
    print("  [PASS] _round_quantity")


if __name__ == "__main__":
    test_is_simulation_trading_enabled()
    test_line_send_when_empty_token()
    test_binance_client_round_quantity()
    import asyncio
    asyncio.run(test_execute_trade_when_simulation_disabled())
    asyncio.run(test_execute_trade_success_mock())
    print("\nAll execution tests passed.")
