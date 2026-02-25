"""
執行引擎 — 串接風控結果與幣安下單、寫入 DB

僅在 BINANCE_TESTNET 且 API Key 已設定時實際下單；否則僅 log。
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from loguru import logger

from config.settings import BINANCE_API_KEY, BINANCE_TESTNET
from core.execution.binance_client import BinanceFuturesClient

if TYPE_CHECKING:
    from core.risk.risk_manager import RiskCheckResult
    from core.strategy.base import TradeSignal
    from database.db_manager import DatabaseManager


def _is_simulation_trading_enabled() -> bool:
    """僅在 Testnet 且 API Key 已設定時執行真實下單"""
    return bool(BINANCE_TESTNET and BINANCE_API_KEY)


async def execute_trade(
    signal: "TradeSignal",
    risk_result: "RiskCheckResult",
    entry_price: float,
    db: "DatabaseManager",
    strategy_name: str = "",
) -> Optional[int]:
    """
    依風控結果在交易所下市價單，成功則寫入 trades 表。

    Args:
        signal: 通過否決的交易信號
        risk_result: 風控通過結果（size_usdt, leverage, stop_loss, take_profit）
        entry_price: 當前/進場價
        db: 資料庫管理器
        strategy_name: 策略名稱（可從 signal.strategy_name 取得）

    Returns:
        成功時回傳 DB trade id，未執行或失敗回傳 None
    """
    if not risk_result.passed:
        return None

    strategy_name = strategy_name or signal.strategy_name
    symbol = signal.symbol
    side_binance = "BUY" if signal.signal_type == "LONG" else "SELL"
    size_usdt = risk_result.size_usdt
    leverage = risk_result.leverage
    stop_loss = risk_result.stop_loss
    take_profit = risk_result.take_profit

    if not _is_simulation_trading_enabled():
        logger.info(
            f"模擬交易未啟用: {symbol} {signal.signal_type} "
            f"size={size_usdt}U sl={stop_loss} (僅 log，未下單)"
        )
        return None

    quantity_base = size_usdt / entry_price if entry_price else 0
    if quantity_base <= 0:
        logger.warning(f"execute_trade: entry_price 無效 {entry_price}")
        return None

    client = BinanceFuturesClient()
    try:
        await client.set_leverage(symbol, leverage)
    except Exception as e:
        logger.error(f"set_leverage 失敗: {e}")
        return None

    order_id = await client.place_market_order(symbol, side_binance, quantity_base)
    if order_id is None:
        return None

    # 可選：掛止損/止盈（若風控有給且 > 0）
    close_side = "SELL" if signal.signal_type == "LONG" else "BUY"
    if stop_loss and stop_loss > 0:
        await client.place_stop_loss(
            symbol, close_side, quantity_base, stop_loss, reduce_only=True
        )
    if take_profit and take_profit > 0:
        await client.place_take_profit(
            symbol, close_side, quantity_base, take_profit, reduce_only=True
        )

    opened_at = datetime.utcnow().isoformat()
    trade_data = {
        "symbol": symbol,
        "side": signal.signal_type,
        "entry_price": entry_price,
        "quantity": quantity_base,
        "leverage": leverage,
        "stop_loss": stop_loss if stop_loss else None,
        "take_profit": take_profit if take_profit else None,
        "status": "OPEN",
        "entry_reason": getattr(signal, "reason", None) or "strategy",
        "strategy_name": strategy_name,
        "opened_at": opened_at,
    }
    trade_id = db.insert_trade(trade_data)
    logger.info(f"執行完成: trade_id={trade_id} {symbol} {signal.signal_type} orderId={order_id}")
    return trade_id
