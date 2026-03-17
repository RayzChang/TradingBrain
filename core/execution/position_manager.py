"""
Open-position synchronization and TP/SL management.

- Sync exchange positions into the local database on startup.
- Manage staged take-profit logic (TP1 / TP2 / TP3).
- Update trailing stops after partial exits.
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from loguru import logger

from core.execution.binance_client import BinanceFuturesClient
from core.risk.exit_profiles import get_exit_profile, normalize_strategy_family
from notifications.telegram_notify import send_telegram_message

if TYPE_CHECKING:
    from database.db_manager import DatabaseManager


def _trade_exit_profile(trade: dict):
    """Return the shared exit profile for the trade strategy."""
    return get_exit_profile(trade.get("strategy_name", ""))


def _strategy_family(trade: dict) -> str:
    """Return the normalized strategy family for the trade."""
    return normalize_strategy_family(trade.get("strategy_name", ""))


def _is_mean_reversion_trade(trade: dict) -> bool:
    """Return True when the trade was opened by the mean reversion strategy."""
    return _strategy_family(trade) == "mean_reversion"


def _supports_exchange_protection(client: BinanceFuturesClient | None) -> bool:
    """Return True when stop-loss / take-profit algo orders should be managed on exchange."""
    return client is not None and client.supports_algo_orders()


async def sync_positions_from_exchange(
    db: "DatabaseManager", client: BinanceFuturesClient
) -> None:
    """Mirror exchange-side open positions into the local trade table."""
    try:
        positions = await client.get_positions()
    except Exception as exc:
        logger.error(f"sync_positions failed to fetch positions: {exc}")
        return

    exchange_keys: set[tuple[str, str]] = set()
    for position in positions:
        symbol = position.get("symbol", "")
        amount = float(position.get("positionAmt", 0) or 0)
        if amount == 0:
            continue

        side = "LONG" if amount > 0 else "SHORT"
        exchange_keys.add((symbol, side))

        open_trades = db.get_open_trades()
        found = any(
            trade["symbol"] == symbol and trade["side"] == side
            for trade in open_trades
        )
        if found:
            continue

        entry_price = float(position.get("entryPrice", 0) or 0)
        quantity = abs(amount)
        trade_data = {
            "symbol": symbol,
            "side": side,
            "entry_price": entry_price,
            "quantity": quantity,
            "leverage": position.get("leverage", 1),
            "original_quantity": quantity,
            "current_quantity": quantity,
            "highest_price": entry_price,
            "lowest_price": entry_price,
            "tp_stage": 0,
            "status": "OPEN",
            "opened_at": datetime.now(timezone.utc).isoformat(),
            "strategy_name": "sync",
        }
        db.insert_trade(trade_data)
        logger.info(f"sync_positions added exchange position {symbol} {side}")

    for trade in db.get_open_trades():
        key = (trade["symbol"], trade["side"])
        if key in exchange_keys:
            continue

        db.close_trade(
            trade_id=trade["id"],
            exit_price=trade.get("entry_price") or 0,
            pnl=0,
            pnl_pct=0,
            fee=0,
            exit_reason="SYNC_CLOSED",
        )
        logger.info(
            f"sync_positions marked missing exchange position as closed: "
            f"{trade['symbol']} {trade['side']}"
        )

    logger.debug("sync_positions completed")


async def _partial_close(
    db: "DatabaseManager",
    client: BinanceFuturesClient | None,
    trade: dict,
    close_qty: float,
    current_price: float,
    reason: str,
) -> bool:
    """Close part of a position on exchange if needed and log the result."""
    symbol = trade["symbol"]
    side = trade["side"]

    if client is not None:
        close_side = "SELL" if side == "LONG" else "BUY"
        order_id = await client.close_position_market(symbol, close_side, close_qty)
        if order_id is None:
            logger.warning(
                f"Partial close failed: {symbol} {side} qty={close_qty:.6f} reason={reason}"
            )
            return False

    entry = float(trade.get("entry_price", 0) or 0)
    pnl = (
        (current_price - entry) * close_qty
        if side == "LONG"
        else (entry - current_price) * close_qty
    )
    pnl_pct = ((current_price - entry) / entry * 100) if entry else 0.0
    if side == "SHORT":
        pnl_pct = -pnl_pct

    logger.info(
        f"Partial close {symbol} {side} {reason} | "
        f"qty={close_qty:.6f} @ {current_price:.4f} | "
        f"PnL={pnl:+.2f}U ({pnl_pct:+.2f}%)"
    )
    return True


async def _full_close(
    db: "DatabaseManager",
    client: BinanceFuturesClient | None,
    trade: dict,
    current_price: float,
    exit_reason: str,
) -> None:
    """Close the remaining position and persist the closed trade."""
    symbol = trade["symbol"]
    side = trade["side"]
    current_qty = float(trade.get("current_quantity") or trade.get("quantity", 0) or 0)

    if client is not None:
        await client.cancel_all_orders(symbol)
        close_side = "SELL" if side == "LONG" else "BUY"
        order_id = await client.close_position_market(symbol, close_side, current_qty)
        if order_id is None:
            logger.warning(f"Full close failed: {symbol} {side}")
            return

    entry = float(trade.get("entry_price", 0) or 0)
    total_pnl = _calc_total_pnl(trade, current_price)
    pnl_pct = ((current_price - entry) / entry * 100) if entry else 0.0
    if side == "SHORT":
        pnl_pct = -pnl_pct

    db.close_trade(
        trade_id=trade["id"],
        exit_price=current_price,
        pnl=total_pnl,
        pnl_pct=pnl_pct,
        fee=0,
        exit_reason=exit_reason,
    )

    close_msg = (
        f"TradingBrain close\n"
        f"{symbol} {side} | {exit_reason}\n"
        f"Entry: {entry:.4f} | Exit: {current_price:.4f}\n"
        f"PnL: {total_pnl:+.2f} U ({pnl_pct:+.2f}%)\n"
        f"剩餘倉位: 0"
    )
    send_telegram_message(close_msg)
    logger.info(
        f"Full close completed: {symbol} {side} {exit_reason} pnl={total_pnl:.2f}"
    )


def _calc_total_pnl(trade: dict, final_price: float) -> float:
    """Calculate realized PnL for the original position size."""
    entry = float(trade.get("entry_price", 0) or 0)
    original_qty = float(trade.get("original_quantity") or trade.get("quantity", 0) or 0)
    side = trade["side"]
    if side == "LONG":
        return (final_price - entry) * original_qty
    return (entry - final_price) * original_qty


async def run_position_check(
    db: "DatabaseManager",
    client: BinanceFuturesClient | None,
    prices: dict[str, float],
    *,
    risk_manager=None,
) -> None:
    """Apply TP/SL/trailing logic to all open trades using the latest prices."""
    for trade in db.get_open_trades():
        symbol = trade["symbol"]
        side = trade["side"]
        trade_id = trade["id"]
        entry = float(trade.get("entry_price", 0) or 0)
        stop_loss = trade.get("stop_loss")
        current_qty = float(trade.get("current_quantity") or trade.get("quantity", 0) or 0)
        original_qty = float(trade.get("original_quantity") or trade.get("quantity", 0) or 0)
        tp1 = trade.get("tp1_price")
        tp2 = trade.get("tp2_price")
        tp3 = trade.get("tp3_price")
        tp_stage = int(trade.get("tp_stage") or 0)
        highest = float(trade.get("highest_price") or entry)
        lowest = float(trade.get("lowest_price") or entry)
        atr = float(trade.get("atr_at_entry") or 0)
        profile = _trade_exit_profile(trade)
        is_mean_reversion = profile.tp2_final_exit

        current = float(prices.get(symbol) or 0)
        if current <= 0:
            continue

        price_updated = False
        if side == "LONG" and current > highest:
            highest = current
            price_updated = True
        elif side == "SHORT" and current < lowest:
            lowest = current
            price_updated = True

        if tp_stage == 0 and tp1:
            tp1_hit = (side == "LONG" and current >= tp1) or (
                side == "SHORT" and current <= tp1
            )
            if tp1_hit:
                tp1_close_pct = profile.tp1_close_pct
                close_qty = original_qty * tp1_close_pct
                new_qty = current_qty - close_qty
                success = await _partial_close(db, client, trade, close_qty, current, "TP1")
                if success:
                    new_sl = entry
                    db.update_trade_tp_stage(trade_id, 1, new_qty, new_sl)
                    if price_updated:
                        db.update_trade_trailing(
                            trade_id,
                            new_sl,
                            highest_price=highest if side == "LONG" else None,
                            lowest_price=lowest if side == "SHORT" else None,
                        )

                    if _supports_exchange_protection(client):
                        await client.cancel_all_orders(symbol)
                        close_side = "SELL" if side == "LONG" else "BUY"
                        await client.place_stop_loss(symbol, close_side, new_qty, new_sl)
                        if tp2:
                            await client.place_take_profit(
                                symbol,
                                close_side,
                                new_qty if is_mean_reversion else original_qty * profile.tp2_close_pct,
                                tp2,
                            )

                    message = (
                        f"TP1 hit\n"
                        f"{symbol} {side} | close {tp1_close_pct:.0%} ({close_qty:.6f})\n"
                        f"剩餘倉位: {new_qty:.6f}\n"
                        f"Move SL to entry: {entry:.4f}"
                    )
                    if tp2:
                        message += f"\nNext TP2: {tp2:.4f}"
                    send_telegram_message(message)
                    logger.info(f"TP1 hit: {symbol} {side}")
                    tp_stage = 1
                    stop_loss = new_sl
                continue

        if tp_stage == 1 and tp2:
            tp2_hit = (side == "LONG" and current >= tp2) or (
                side == "SHORT" and current <= tp2
            )
            if tp2_hit:
                close_qty = current_qty if is_mean_reversion else original_qty * profile.tp2_close_pct
                new_qty = max(0.0, current_qty - close_qty)
                success = await _partial_close(db, client, trade, close_qty, current, "TP2")
                if success:
                    if is_mean_reversion:
                        db.close_trade(
                            trade_id=trade_id,
                            exit_price=current,
                            pnl=_calc_total_pnl(trade, current),
                            pnl_pct=((current - entry) / entry * 100) if side == "LONG" and entry else ((entry - current) / entry * 100) if entry else 0.0,
                            fee=0,
                            exit_reason="TP2",
                        )
                        send_telegram_message(
                            f"TP2 hit\n{symbol} {side} | close remaining {close_qty:.6f}\n剩餘倉位: 0\nExit profile: mean_reversion"
                        )
                        logger.info(f"TP2 final exit: {symbol} {side} mean_reversion")
                        if risk_manager and hasattr(risk_manager, "update_equity_high_water_mark"):
                            await _update_hwm(client, risk_manager)
                        continue

                    new_sl = tp1 if tp1 else entry
                    db.update_trade_tp_stage(trade_id, 2, new_qty, new_sl)
                    if price_updated:
                        db.update_trade_trailing(
                            trade_id,
                            new_sl,
                            highest_price=highest if side == "LONG" else None,
                            lowest_price=lowest if side == "SHORT" else None,
                        )

                    if _supports_exchange_protection(client):
                        await client.cancel_all_orders(symbol)
                        close_side = "SELL" if side == "LONG" else "BUY"
                        await client.place_stop_loss(symbol, close_side, new_qty, new_sl)

                    message = (
                        f"TP2 hit\n"
                        f"{symbol} {side} | close {profile.tp2_close_pct:.0%} ({close_qty:.6f})\n"
                        f"剩餘倉位: {new_qty:.6f}\n"
                        f"Move SL to {new_sl:.4f}"
                    )
                    if tp3:
                        message += f"\nRemaining position trails toward TP3: {tp3:.4f}"
                    send_telegram_message(message)
                    logger.info(f"TP2 hit: {symbol} {side}")
                    tp_stage = 2
                    stop_loss = new_sl
                continue

        if tp_stage == 2 and tp3 and not is_mean_reversion:
            tp3_hit = (side == "LONG" and current >= tp3) or (
                side == "SHORT" and current <= tp3
            )
            if tp3_hit:
                await _full_close(db, client, trade, current, "TP3")
                send_telegram_message(f"TP3 hit\n{symbol} {side} | final exit @ {current:.4f}")
                if risk_manager and hasattr(risk_manager, "update_equity_high_water_mark"):
                    await _update_hwm(client, risk_manager)
                continue

        if tp_stage == 2 and atr > 0 and not is_mean_reversion:
            if side == "LONG":
                trailing_sl = highest - (atr * profile.tp2_trailing_atr_mult)
                if trailing_sl > (stop_loss or 0):
                    stop_loss = trailing_sl
                    db.update_trade_trailing(trade_id, stop_loss, highest_price=highest)
                    if _supports_exchange_protection(client):
                        await client.cancel_all_orders(symbol)
                        await client.place_stop_loss(symbol, "SELL", current_qty, stop_loss)
                    logger.debug(
                        f"Trailing SL updated: {symbol} LONG SL={stop_loss:.4f} "
                        f"(highest={highest:.4f})"
                    )
                elif price_updated:
                    db.update_trade_trailing(trade_id, stop_loss, highest_price=highest)
            else:
                trailing_sl = lowest + (atr * profile.tp2_trailing_atr_mult)
                if trailing_sl < (stop_loss or float("inf")):
                    stop_loss = trailing_sl
                    db.update_trade_trailing(trade_id, stop_loss, lowest_price=lowest)
                    if _supports_exchange_protection(client):
                        await client.cancel_all_orders(symbol)
                        await client.place_stop_loss(symbol, "BUY", current_qty, stop_loss)
                    logger.debug(
                        f"Trailing SL updated: {symbol} SHORT SL={stop_loss:.4f} "
                        f"(lowest={lowest:.4f})"
                    )
                elif price_updated:
                    db.update_trade_trailing(trade_id, stop_loss, lowest_price=lowest)

        elif tp_stage == 1 and atr > 0 and not is_mean_reversion:
            if side == "LONG":
                trailing_sl = highest - (atr * profile.tp1_trailing_atr_mult)
                if trailing_sl > (stop_loss or 0):
                    stop_loss = trailing_sl
                    db.update_trade_trailing(trade_id, stop_loss, highest_price=highest)
                    if _supports_exchange_protection(client):
                        await client.cancel_all_orders(symbol)
                        await client.place_stop_loss(symbol, "SELL", current_qty, stop_loss)
                    logger.debug(f"TP1 trailing SL updated: {symbol} LONG SL={stop_loss:.4f}")
                elif price_updated:
                    db.update_trade_trailing(trade_id, stop_loss, highest_price=highest)
            else:
                trailing_sl = lowest + (atr * profile.tp1_trailing_atr_mult)
                if trailing_sl < (stop_loss or float("inf")):
                    stop_loss = trailing_sl
                    db.update_trade_trailing(trade_id, stop_loss, lowest_price=lowest)
                    if _supports_exchange_protection(client):
                        await client.cancel_all_orders(symbol)
                        await client.place_stop_loss(symbol, "BUY", current_qty, stop_loss)
                    logger.debug(
                        f"TP1 trailing SL updated: {symbol} SHORT SL={stop_loss:.4f}"
                    )
                elif price_updated:
                    db.update_trade_trailing(trade_id, stop_loss, lowest_price=lowest)

        elif tp_stage == 0 and price_updated:
            db.update_trade_trailing(
                trade_id,
                stop_loss or 0,
                highest_price=highest if side == "LONG" else None,
                lowest_price=lowest if side == "SHORT" else None,
            )

        if stop_loss:
            sl_hit = (side == "LONG" and current <= stop_loss) or (
                side == "SHORT" and current >= stop_loss
            )
            if sl_hit:
                exit_reason = "STOP_LOSS"
                if tp_stage == 1:
                    exit_reason = "TRAILING_SL_AFTER_TP1"
                elif tp_stage == 2:
                    exit_reason = "TRAILING_SL_AFTER_TP2"
                await _full_close(db, client, trade, current, exit_reason)
                if risk_manager and hasattr(risk_manager, "update_equity_high_water_mark"):
                    await _update_hwm(client, risk_manager)


async def _update_hwm(client, risk_manager) -> None:
    """Refresh the risk manager high-water mark from exchange balance."""
    try:
        if client is not None:
            balance = await client.get_balance()
            risk_manager.update_equity_high_water_mark(balance)
    except Exception:
        pass
