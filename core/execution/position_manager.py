"""
持倉同步與止損/止盈檢查

- 啟動時以交易所為準同步 DB 未平倉。
- 定時檢查持倉市價是否觸及止損/止盈，觸及則市價平倉並更新 DB。
"""

from datetime import datetime
from typing import TYPE_CHECKING

from loguru import logger

from core.execution.binance_client import BinanceFuturesClient
from notifications.line_notify import send_line_message

if TYPE_CHECKING:
    from database.db_manager import DatabaseManager


async def sync_positions_from_exchange(db: "DatabaseManager", client: BinanceFuturesClient) -> None:
    """
    以交易所為準同步未平倉：交易所有的寫入/更新 DB；DB 有但交易所已平的標記為 SYNC_CLOSED。
    """
    try:
        positions = await client.get_positions()
    except Exception as e:
        logger.error(f"sync_positions 取得持倉失敗: {e}")
        return

    # 交易所 (symbol, side) -> positionAmt, entryPrice, ...
    exchange_set: set[tuple[str, str]] = set()
    for p in positions:
        symbol = p.get("symbol", "")
        amt = p.get("positionAmt", 0)
        side = "LONG" if amt > 0 else "SHORT"
        exchange_set.add((symbol, side))
        # 若 DB 無此 OPEN 則補一筆（可能是外部下單或重啟後漏記）
        open_trades = db.get_open_trades()
        found = any(t["symbol"] == symbol and t["side"] == side for t in open_trades)
        if not found:
            trade_data = {
                "symbol": symbol,
                "side": side,
                "entry_price": p.get("entryPrice", 0),
                "quantity": abs(float(amt)),
                "leverage": p.get("leverage", 1),
                "status": "OPEN",
                "opened_at": datetime.utcnow().isoformat(),
                "strategy_name": "sync",
            }
            db.insert_trade(trade_data)
            logger.info(f"sync_positions: 補登交易所持倉 {symbol} {side}")

    # DB 中 OPEN 但交易所已無 -> 視為已平倉
    open_trades = db.get_open_trades()
    for t in open_trades:
        key = (t["symbol"], t["side"])
        if key not in exchange_set:
            # 交易所已平，更新 DB
            db.close_trade(
                trade_id=t["id"],
                exit_price=t.get("entry_price") or 0,
                pnl=0,
                pnl_pct=0,
                fee=0,
                exit_reason="SYNC_CLOSED",
            )
            logger.info(f"sync_positions: DB 持倉已於交易所平倉 {t['symbol']} {t['side']} -> 標記 CLOSED")
    logger.debug("sync_positions 完成")
    return


async def run_position_check(
    db: "DatabaseManager",
    client: BinanceFuturesClient | None,
    prices: dict[str, float],
    *,
    risk_manager=None,
) -> None:
    """
    檢查所有 DB 未平倉：若市價觸及止損或止盈則市價平倉並 close_trade。
    prices: symbol -> 當前價（由呼叫方從快取或 REST 填入）。
    """
    open_trades = db.get_open_trades()
    for t in open_trades:
        symbol = t["symbol"]
        side = t["side"]
        stop_loss = t.get("stop_loss")
        take_profit = t.get("take_profit")
        quantity = float(t.get("quantity", 0))
        trade_id = t["id"]
        entry = float(t.get("entry_price", 0))

        current = prices.get(symbol) or 0
        if current <= 0:
            continue

        should_close = False
        exit_reason = ""
        if side == "LONG":
            if stop_loss and current <= stop_loss:
                should_close = True
                exit_reason = "STOP_LOSS"
            elif take_profit and current >= take_profit:
                should_close = True
                exit_reason = "TAKE_PROFIT"
        else:  # SHORT
            if stop_loss and current >= stop_loss:
                should_close = True
                exit_reason = "STOP_LOSS"
            elif take_profit and current <= take_profit:
                should_close = True
                exit_reason = "TAKE_PROFIT"

        if not should_close:
            continue

        # paper 模式：不打交易所，直接以當前價結算
        if client is not None:
            close_side = "SELL" if side == "LONG" else "BUY"
            order_id = await client.close_position_market(symbol, close_side, quantity)
            if order_id is None:
                logger.warning(f"position_check 平倉下單失敗: {symbol} {side}")
                continue

        pnl = (current - entry) * quantity if side == "LONG" else (entry - current) * quantity
        pnl_pct = (pnl / (entry * quantity)) * 100 if entry and quantity else 0
        db.close_trade(
            trade_id=trade_id,
            exit_price=current,
            pnl=pnl,
            pnl_pct=pnl_pct,
            fee=0,
            exit_reason=exit_reason,
        )
        # P9: 平倉 LINE 通知
        close_msg = (
            f"📉 TradingBrain 平倉\n"
            f"{symbol} {side} | {exit_reason} | PnL {pnl:+.2f} U ({pnl_pct:+.2f}%)"
        )
        send_line_message(close_msg)
        if risk_manager and hasattr(risk_manager, "update_equity_high_water_mark"):
            # 可選：更新權益高水位
            try:
                if client is not None:
                    balance = await client.get_balance()
                    risk_manager.update_equity_high_water_mark(balance)
            except Exception:
                pass
        logger.info(f"position_check 已平倉: {symbol} {side} {exit_reason} pnl={pnl:.2f}")
