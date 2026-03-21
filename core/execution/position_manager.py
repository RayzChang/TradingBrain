"""
Open-position synchronization and TP/SL management.

- Sync exchange positions into the local database on startup.
- Manage staged take-profit logic (TP1 / TP2 / TP3).
- Update trailing stops after partial exits.
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from loguru import logger
import pandas as pd

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

    pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"
    close_msg = (
        f"{pnl_emoji} TradingBrain V8 平倉\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"幣種: {symbol} {side}\n"
        f"原因: {exit_reason}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"進場: {entry:.4f}\n"
        f"出場: {current_price:.4f}\n"
        f"損益: {total_pnl:+.2f} U ({pnl_pct:+.2f}%)"
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


def _default_soft_stop_required_closes(trade: dict) -> int:
    return 1 if _is_mean_reversion_trade(trade) else 2


def _analyze_stop_zone_behavior(
    candles_1m: list[dict] | None,
    candles_5m: list[dict] | None,
    side: str,
    soft_stop: float,
    hard_stop: float,
) -> str:
    """Analyze price behavior near the stop zone.

    V8 observation mode: instead of mechanical stop-loss, analyze whether
    price is wicking through the zone or truly breaking down.

    Returns: 'WICK_REVERSAL', 'CONSOLIDATING', 'CONFIRMED_BREAKDOWN', or 'NOT_IN_ZONE'
    """
    if not candles_5m or len(candles_5m) < 2:
        # Not enough data, fall back to confirmed if 1m shows breach
        if candles_1m and len(candles_1m) >= 2:
            candles_5m = candles_1m[-3:]
        else:
            return "NOT_IN_ZONE"

    recent = candles_5m[-3:]
    bodies = []
    for c in recent:
        try:
            o = float(c.get("open", 0))
            cl = float(c.get("close", 0))
            bodies.append((min(o, cl), max(o, cl)))
        except (TypeError, ValueError):
            return "NOT_IN_ZONE"

    if not bodies:
        return "NOT_IN_ZONE"

    latest_body_low, latest_body_high = bodies[-1]

    if side == "LONG":
        # For LONG: stop zone breach = price below soft_stop
        # Check if latest candle body recovered above soft_stop
        if latest_body_low > soft_stop:
            return "WICK_REVERSAL"
        # Check if 2+ consecutive 5m bodies fully below soft_stop
        below_count = sum(1 for low, high in bodies[-2:] if high < soft_stop)
        if below_count >= 2:
            return "CONFIRMED_BREAKDOWN"
        return "CONSOLIDATING"
    else:
        # For SHORT: stop zone breach = price above soft_stop
        if latest_body_high < soft_stop:
            return "WICK_REVERSAL"
        above_count = sum(1 for low, high in bodies[-2:] if low > soft_stop)
        if above_count >= 2:
            return "CONFIRMED_BREAKDOWN"
        return "CONSOLIDATING"


def _catastrophic_buffer(reference_price: float, atr: float, family: str) -> float:
    pct_floor = {
        "breakout": 0.0025,
        "trend_following": 0.002,
        "mean_reversion": 0.0015,
    }.get(family, 0.002)
    atr_mult = {
        "breakout": 0.6,
        "trend_following": 0.45,
        "mean_reversion": 0.25,
    }.get(family, 0.4)
    return max(abs(reference_price) * pct_floor, max(atr, 0.0) * atr_mult)


def _derive_hard_stop_from_soft(soft_stop: float, side: str, atr: float, family: str) -> float:
    buffer = _catastrophic_buffer(soft_stop, atr, family)
    if side == "LONG":
        return round(max(soft_stop - buffer, 0), 4)
    return round(soft_stop + buffer, 4)


def _is_better_stop(side: str, candidate: float | None, current: float | None) -> bool:
    if candidate is None or candidate <= 0:
        return False
    if current is None or current <= 0:
        return True
    if side == "LONG":
        return candidate > current
    return candidate < current


def _recent_structure_stop_from_candles(
    candles: list[dict] | None,
    side: str,
    family: str,
) -> float | None:
    if not candles or len(candles) < 7:
        return None

    df = pd.DataFrame(candles[-30:]).copy()
    if df.empty or "low" not in df.columns or "high" not in df.columns:
        return None

    for column in ("low", "high", "close"):
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")

    order = 2
    buffer_pct = 0.0015 if family != "mean_reversion" else 0.001
    if side == "LONG":
        lows = df["low"].dropna().tolist()
        if len(lows) < (order * 2 + 1):
            return None
        candidate = None
        for idx in range(order, len(lows) - order):
            value = lows[idx]
            if all(value <= lows[idx - step] for step in range(1, order + 1)) and all(
                value <= lows[idx + step] for step in range(1, order + 1)
            ):
                candidate = value
        if candidate is None:
            return None
        return round(max(candidate * (1 - buffer_pct), 0), 4)

    highs = df["high"].dropna().tolist()
    if len(highs) < (order * 2 + 1):
        return None
    candidate = None
    for idx in range(order, len(highs) - order):
        value = highs[idx]
        if all(value >= highs[idx - step] for step in range(1, order + 1)) and all(
            value >= highs[idx + step] for step in range(1, order + 1)
        ):
            candidate = value
    if candidate is None:
        return None
    return round(candidate * (1 + buffer_pct), 4)


def _check_consecutive_closes(
    candles: list[dict] | None,
    side: str,
    soft_stop: float,
    required_closes: int,
) -> bool:
    if not candles or soft_stop <= 0 or required_closes <= 0:
        return False

    closes: list[float] = []
    for candle in candles[-required_closes:]:
        close = candle.get("close")
        try:
            closes.append(float(close))
        except (TypeError, ValueError):
            return False
    if len(closes) < required_closes:
        return False

    if side == "LONG":
        return all(close < soft_stop for close in closes)
    return all(close > soft_stop for close in closes)


def _soft_stop_confirmed(
    candles_1m: list[dict] | None,
    candles_5m: list[dict] | None,
    side: str,
    soft_stop: float,
    required_closes: int,
) -> bool:
    if _check_consecutive_closes(candles_1m, side, soft_stop, required_closes):
        return True
    return _check_consecutive_closes(candles_5m, side, soft_stop, 1)


async def run_position_check(
    db: "DatabaseManager",
    client: BinanceFuturesClient | None,
    prices: dict[str, float],
    *,
    recent_candles: dict[str, dict[str, list[dict]] | list[dict]] | None = None,
    risk_manager=None,
) -> None:
    """Apply TP/SL/trailing logic to all open trades using the latest prices."""
    for trade in db.get_open_trades():
        symbol = trade["symbol"]
        side = trade["side"]
        trade_id = trade["id"]
        entry = float(trade.get("entry_price", 0) or 0)
        hard_stop = float(trade.get("hard_stop_loss") or trade.get("stop_loss") or 0)
        soft_stop = float(trade.get("soft_stop_loss") or trade.get("stop_loss") or 0)
        soft_stop_required = int(
            trade.get("soft_stop_required_closes")
            or _default_soft_stop_required_closes(trade)
        )
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
        family = _strategy_family(trade)
        is_mean_reversion = profile.tp2_final_exit
        symbol_recent = (recent_candles or {}).get(symbol, {})
        if isinstance(symbol_recent, list):
            symbol_candles = symbol_recent
            symbol_candles_5m: list[dict] = []
        else:
            symbol_candles = list(symbol_recent.get("1m", []))
            symbol_candles_5m = list(symbol_recent.get("5m", []))

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
                    candidate_soft = _recent_structure_stop_from_candles(
                        symbol_candles,
                        side,
                        family,
                    )
                    new_soft = soft_stop
                    if is_mean_reversion:
                        new_soft = entry
                    elif _is_better_stop(side, candidate_soft, soft_stop):
                        new_soft = candidate_soft

                    new_hard = _derive_hard_stop_from_soft(
                        new_soft if new_soft > 0 else (soft_stop or entry),
                        side,
                        atr,
                        family,
                    )
                    db.update_trade_tp_stage(trade_id, 1, new_qty, new_hard)
                    db.update_trade_protection(
                        trade_id,
                        soft_stop_loss=new_soft,
                        hard_stop_loss=new_hard,
                        soft_stop_required_closes=soft_stop_required,
                        highest_price=highest if side == "LONG" else None,
                        lowest_price=lowest if side == "SHORT" else None,
                    )

                    if _supports_exchange_protection(client):
                        await client.cancel_all_orders(symbol)
                        close_side = "SELL" if side == "LONG" else "BUY"
                        await client.place_stop_loss(symbol, close_side, new_qty, new_hard)
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
                        f"Soft SL: {new_soft:.4f}\n"
                        f"Hard SL: {new_hard:.4f}"
                    )
                    if tp2:
                        message += f"\nNext TP2: {tp2:.4f}"
                    send_telegram_message(message)
                    logger.info(f"TP1 hit: {symbol} {side}")
                    tp_stage = 1
                    soft_stop = new_soft
                    hard_stop = new_hard
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

                    candidate_soft = _recent_structure_stop_from_candles(
                        symbol_candles,
                        side,
                        family,
                    )
                    if side == "LONG":
                        fallback_soft = max(soft_stop or 0, entry)
                    else:
                        fallback_soft = min(soft_stop or float("inf"), entry)
                        if fallback_soft == float("inf"):
                            fallback_soft = entry
                    new_soft = candidate_soft if _is_better_stop(side, candidate_soft, soft_stop) else fallback_soft
                    new_hard = _derive_hard_stop_from_soft(new_soft, side, atr, family)
                    db.update_trade_tp_stage(trade_id, 2, new_qty, new_hard)
                    db.update_trade_protection(
                        trade_id,
                        soft_stop_loss=new_soft,
                        hard_stop_loss=new_hard,
                        soft_stop_required_closes=soft_stop_required,
                        highest_price=highest if side == "LONG" else None,
                        lowest_price=lowest if side == "SHORT" else None,
                    )

                    if _supports_exchange_protection(client):
                        await client.cancel_all_orders(symbol)
                        close_side = "SELL" if side == "LONG" else "BUY"
                        await client.place_stop_loss(symbol, close_side, new_qty, new_hard)

                    message = (
                        f"TP2 hit\n"
                        f"{symbol} {side} | close {profile.tp2_close_pct:.0%} ({close_qty:.6f})\n"
                        f"剩餘倉位: {new_qty:.6f}\n"
                        f"Soft SL: {new_soft:.4f}\n"
                        f"Hard SL: {new_hard:.4f}"
                    )
                    if tp3:
                        message += f"\nRemaining position trails toward TP3: {tp3:.4f}"
                    send_telegram_message(message)
                    logger.info(f"TP2 hit: {symbol} {side}")
                    tp_stage = 2
                    soft_stop = new_soft
                    hard_stop = new_hard
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

        if tp_stage >= 1 and not is_mean_reversion:
            candidate_soft = _recent_structure_stop_from_candles(
                symbol_candles,
                side,
                family,
            )
            if _is_better_stop(side, candidate_soft, soft_stop):
                soft_stop = candidate_soft
                hard_stop = _derive_hard_stop_from_soft(soft_stop, side, atr, family)
                db.update_trade_protection(
                    trade_id,
                    soft_stop_loss=soft_stop,
                    hard_stop_loss=hard_stop,
                    soft_stop_required_closes=soft_stop_required,
                    highest_price=highest if side == "LONG" else None,
                    lowest_price=lowest if side == "SHORT" else None,
                )
                if _supports_exchange_protection(client):
                    await client.cancel_all_orders(symbol)
                    close_side = "SELL" if side == "LONG" else "BUY"
                    await client.place_stop_loss(symbol, close_side, current_qty, hard_stop)
                logger.debug(
                    f"Structure trailing updated: {symbol} {side} "
                    f"soft={soft_stop:.4f} hard={hard_stop:.4f}"
                )
            elif price_updated:
                db.update_trade_protection(
                    trade_id,
                    highest_price=highest if side == "LONG" else None,
                    lowest_price=lowest if side == "SHORT" else None,
                )
        elif price_updated:
            db.update_trade_protection(
                trade_id,
                highest_price=highest if side == "LONG" else None,
                lowest_price=lowest if side == "SHORT" else None,
            )

        if hard_stop:
            hard_hit = (side == "LONG" and current <= hard_stop) or (
                side == "SHORT" and current >= hard_stop
            )
            if hard_hit:
                exit_reason = "HARD_STOP"
                if tp_stage == 1:
                    exit_reason = "HARD_STOP_AFTER_TP1"
                elif tp_stage == 2:
                    exit_reason = "HARD_STOP_AFTER_TP2"
                await _full_close(db, client, trade, current, exit_reason)
                if risk_manager and hasattr(risk_manager, "update_equity_high_water_mark"):
                    await _update_hwm(client, risk_manager)
                continue

        # V8: Dynamic stop-loss observation mode
        # Instead of mechanical "N closes below soft stop = exit",
        # analyze whether price is wicking or truly breaking down.
        if soft_stop:
            in_danger_zone = (
                (side == "LONG" and current <= soft_stop)
                or (side == "SHORT" and current >= soft_stop)
            )
            if in_danger_zone:
                behavior = _analyze_stop_zone_behavior(
                    symbol_candles,
                    symbol_candles_5m,
                    side,
                    soft_stop,
                    hard_stop,
                )
                if behavior == "CONFIRMED_BREAKDOWN":
                    exit_reason = "OBSERVATION_STOP"
                    if tp_stage == 1:
                        exit_reason = "OBSERVATION_STOP_AFTER_TP1"
                    elif tp_stage == 2:
                        exit_reason = "OBSERVATION_STOP_AFTER_TP2"
                    await _full_close(db, client, trade, current, exit_reason)
                    if risk_manager and hasattr(risk_manager, "update_equity_high_water_mark"):
                        await _update_hwm(client, risk_manager)
                elif behavior == "WICK_REVERSAL":
                    logger.debug(
                        f"Observation: {symbol} {side} wick reversal detected at "
                        f"soft_stop={soft_stop:.4f}, keeping position"
                    )
                elif behavior == "CONSOLIDATING":
                    logger.debug(
                        f"Observation: {symbol} {side} consolidating near "
                        f"soft_stop={soft_stop:.4f}, monitoring..."
                    )


async def _update_hwm(client, risk_manager) -> None:
    """Refresh the risk manager high-water mark from exchange balance."""
    try:
        if client is not None:
            balance = await client.get_balance()
            risk_manager.update_equity_high_water_mark(balance)
    except Exception:
        pass
