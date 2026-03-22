"""
交易執行引擎：下單、寫入 DB

- Testnet：BINANCE_TESTNET=true 且有 API Key 時走 Testnet 交易
- 實盤：BINANCE_TESTNET=false, TRADING_MODE=live 且有 API Key 時走實盤
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from loguru import logger

from config.settings import (
    BINANCE_API_KEY,
    BINANCE_TESTNET,
    DEFAULT_LEVERAGE,
    TRADING_MODE,
)
from core.execution.binance_client import BinanceFuturesClient
from core.logger_setup import console, fmt_price
from core.risk.exit_profiles import get_exit_profile, normalize_strategy_family
from notifications.telegram_notify import send_telegram_message

if TYPE_CHECKING:
    from core.risk.risk_manager import RiskCheckResult
    from core.strategy.base import TradeSignal
    from database.db_manager import DatabaseManager


def _is_test_notification(strategy_name: str, signal: "TradeSignal") -> bool:
    strategy = (strategy_name or signal.strategy_name or "").strip().lower()
    reason = (getattr(signal, "reason", "") or "").strip().lower()
    return strategy in {"test", "smoke_test", "telegram_test"} or "test" in reason


def _build_trade_open_message(
    *,
    is_test: bool,
    version: str,
    mode: str,
    symbol: str,
    side: str,
    strategy_name: str,
    strategy_family: str,
    margin_cost: float,
    size_usdt: float,
    leverage: int,
    entry_price: float,
    soft_stop_loss: float,
    hard_stop_loss: float,
    soft_stop_required_closes: int,
    tp1: float,
    tp2: float,
    tp3: float,
) -> str:
    side_emoji = "🟢" if side == "LONG" else "🔴"
    tp_line = f"🎯 {fmt_price(tp1)} / {fmt_price(tp2)}"
    if tp3:
        tp_line += f" / {fmt_price(tp3)}"

    if is_test:
        return (
            f"🧪 {symbol} {side_emoji} {side} 測試 [{mode}]\n"
            f"📋 {strategy_name} | 💰 {margin_cost:.0f}U × {leverage}x = {size_usdt:.0f}U\n"
            f"📍 入場 {entry_price:.4f}\n"
            f"🛡 SL {soft_stop_loss:.4f} / {hard_stop_loss:.4f}\n"
            f"{tp_line}"
        )

    return (
        f"✅ {symbol} {side_emoji} {side} 開倉 [{mode}]\n"
        f"📋 {strategy_name} | 💰 {margin_cost:.0f}U × {leverage}x = {size_usdt:.0f}U\n"
        f"📍 入場 {entry_price:.4f}\n"
        f"🛡 SL {soft_stop_loss:.4f} / {hard_stop_loss:.4f} (觀察制)\n"
        f"{tp_line}"
    )


def is_trading_enabled() -> bool:
    """判斷是否啟用交易（Testnet 或實盤）。"""
    if not BINANCE_API_KEY:
        return False
    # paper 模式不真正下單（只記 DB）
    if TRADING_MODE == "paper":
        return False
    if BINANCE_TESTNET:
        return True
    return TRADING_MODE == "live"


async def execute_trade(
    signal: "TradeSignal",
    risk_result: "RiskCheckResult",
    entry_price: float,
    db: "DatabaseManager",
    strategy_name: str = "",
) -> Optional[int]:
    """執行交易：下單到交易所並寫入 trades 表。"""
    if not risk_result.passed:
        return None

    strategy_name = strategy_name or signal.strategy_name
    strategy_family = normalize_strategy_family(strategy_name)
    is_test_notification = _is_test_notification(strategy_name, signal)
    symbol = signal.symbol
    side_binance = "BUY" if signal.signal_type == "LONG" else "SELL"
    size_usdt = risk_result.size_usdt
    leverage = risk_result.leverage
    stop_loss = risk_result.stop_loss
    soft_stop_loss = getattr(risk_result, "soft_stop_loss", stop_loss) or stop_loss
    hard_stop_loss = getattr(risk_result, "hard_stop_loss", stop_loss) or stop_loss
    soft_stop_required_closes = int(
        getattr(risk_result, "soft_stop_required_closes", 0) or 0
    )
    stop_zone_low = getattr(risk_result, "stop_zone_low", 0.0) or 0.0
    stop_zone_high = getattr(risk_result, "stop_zone_high", 0.0) or 0.0
    take_profit = risk_result.take_profit

    tp1 = getattr(risk_result, "tp1", 0.0) or 0.0
    tp1_zone_low = getattr(risk_result, "tp1_zone_low", 0.0) or 0.0
    tp1_zone_high = getattr(risk_result, "tp1_zone_high", 0.0) or 0.0
    tp2 = getattr(risk_result, "tp2", 0.0) or 0.0
    tp2_zone_low = getattr(risk_result, "tp2_zone_low", 0.0) or 0.0
    tp2_zone_high = getattr(risk_result, "tp2_zone_high", 0.0) or 0.0
    tp3 = getattr(risk_result, "tp3", 0.0) or 0.0
    tp3_zone_low = getattr(risk_result, "tp3_zone_low", 0.0) or 0.0
    tp3_zone_high = getattr(risk_result, "tp3_zone_high", 0.0) or 0.0
    atr = getattr(risk_result, "atr", 0.0) or 0.0
    effective_risk_pct = getattr(risk_result, "effective_risk_pct", 0.0) or 0.0
    sl_atr_mult = getattr(risk_result, "sl_atr_mult", 0.0) or 0.0
    structure_stop_floor_triggered = bool(
        getattr(risk_result, "structure_stop_floor_triggered", False)
    )

        # === paper 模式：不真正下單，只記 DB ===
    if TRADING_MODE == "paper":
        quantity_base = size_usdt / entry_price if entry_price else 0
        if quantity_base <= 0:
            logger.warning(f"paper execute_trade: entry_price 無效 {entry_price}")
            return None
        opened_at = datetime.now(timezone.utc).isoformat()
        trade_data = {
            "symbol": symbol,
            "side": signal.signal_type,
            "entry_price": entry_price,
            "quantity": quantity_base,
            "leverage": leverage,
            "stop_loss": hard_stop_loss if hard_stop_loss else None,
            "soft_stop_loss": soft_stop_loss if soft_stop_loss else None,
            "hard_stop_loss": hard_stop_loss if hard_stop_loss else None,
            "soft_stop_required_closes": soft_stop_required_closes,
            "stop_zone_low": stop_zone_low if stop_zone_low else None,
            "stop_zone_high": stop_zone_high if stop_zone_high else None,
            "take_profit": take_profit if take_profit else None,
            "tp1_price": tp1 if tp1 else None,
            "tp1_zone_low": tp1_zone_low if tp1_zone_low else None,
            "tp1_zone_high": tp1_zone_high if tp1_zone_high else None,
            "tp2_price": tp2 if tp2 else None,
            "tp2_zone_low": tp2_zone_low if tp2_zone_low else None,
            "tp2_zone_high": tp2_zone_high if tp2_zone_high else None,
            "tp3_price": tp3 if tp3 else None,
            "tp3_zone_low": tp3_zone_low if tp3_zone_low else None,
            "tp3_zone_high": tp3_zone_high if tp3_zone_high else None,
            "tp_stage": 0,
            "original_quantity": quantity_base,
            "current_quantity": quantity_base,
            "highest_price": entry_price,
            "lowest_price": entry_price,
            "atr_at_entry": atr if atr else None,
            "effective_risk_pct": effective_risk_pct if effective_risk_pct else None,
            "sl_atr_mult": sl_atr_mult if sl_atr_mult else None,
            "structure_stop_floor_triggered": int(structure_stop_floor_triggered),
            "status": "OPEN",
            "entry_reason": getattr(signal, "reason", None) or "strategy",
            "strategy_name": strategy_name,
            "opened_at": opened_at,
            "exchange_order_id": "PAPER",
        }
        trade_id = db.insert_trade(trade_data)
        paper_margin = size_usdt / leverage if leverage else size_usdt
        msg = _build_trade_open_message(
            is_test=is_test_notification,
            version="V9",
            mode="Paper",
            symbol=symbol,
            side=signal.signal_type,
            strategy_name=strategy_name,
            strategy_family=strategy_family,
            margin_cost=paper_margin,
            size_usdt=size_usdt,
            leverage=leverage,
            entry_price=entry_price,
            soft_stop_loss=soft_stop_loss,
            hard_stop_loss=hard_stop_loss,
            soft_stop_required_closes=soft_stop_required_closes,
            tp1=tp1,
            tp2=tp2,
            tp3=tp3,
        )
        send_telegram_message(msg)
        logger.info(f"paper 開倉 trade_id={trade_id} {symbol} {signal.signal_type}")
        side_icon = "🟢" if signal.signal_type == "LONG" else "🔴"
        console(
            f"✅ {symbol} {side_icon} {signal.signal_type} 開倉！{strategy_name} | "
            f"{paper_margin:.0f}U × {leverage}x = {size_usdt:.0f}U"
        )
        console(
            f"   📍 入場 {fmt_price(entry_price)} | 🛡 SL {fmt_price(soft_stop_loss)}/{fmt_price(hard_stop_loss)} | "
            f"🎯 {fmt_price(tp1)}/{fmt_price(tp2)}/{fmt_price(tp3)}"
        )
        return trade_id

    if not is_trading_enabled():
        logger.info(
                        f"交易功能未啟用 {symbol} {signal.signal_type} "
                        f"size={size_usdt}U sl={stop_loss} (僅記 log)"
        )
        return None

    quantity_base = size_usdt / entry_price if entry_price else 0
    if quantity_base <= 0:
        logger.warning(f"execute_trade: entry_price 無效 {entry_price}")
        return None

    client = BinanceFuturesClient()
    exchange_managed_protection = client.supports_algo_orders()
    use_leverage = leverage
    try:
        await client.set_leverage(symbol, leverage)
    except Exception as e:
        logger.warning(f"set_leverage({leverage}x) 失敗: {e}")
        # Testnet 可能不支援高槓桿，fallback 到安全值
        use_leverage = max(1, min(DEFAULT_LEVERAGE, 25))
        try:
            await client.set_leverage(symbol, use_leverage)
        except Exception as e2:
            logger.error(f"set_leverage({use_leverage}x) 也失敗，放棄開倉: {e2}")
            return None
        logger.info(f"槓桿降級為 {use_leverage}x（原始 {leverage}x 不可用）")
    # 統一用實際生效的槓桿，確保 DB/通知/計算一致
    leverage = use_leverage

    order_id = await client.place_market_order(symbol, side_binance, quantity_base)
    if order_id is None:
        return None

    close_side = "SELL" if signal.signal_type == "LONG" else "BUY"
    if exchange_managed_protection:
        if hard_stop_loss and hard_stop_loss > 0:
            await client.place_stop_loss(
                symbol, close_side, quantity_base, hard_stop_loss, reduce_only=True
            )
        profile = get_exit_profile(strategy_name)
        tp1_qty = quantity_base * profile.tp1_close_pct
        if tp1 and tp1 > 0:
            await client.place_take_profit(
                symbol, close_side, tp1_qty, tp1, reduce_only=True
            )
    else:
        logger.info(
            f"Testnet protective orders stay local: {symbol} "
            f"SL/TP managed by position_check"
        )

    opened_at = datetime.now(timezone.utc).isoformat()
    trade_data = {
        "symbol": symbol,
        "side": signal.signal_type,
        "entry_price": entry_price,
        "quantity": quantity_base,
        "leverage": leverage,
        "stop_loss": hard_stop_loss if hard_stop_loss else None,
        "soft_stop_loss": soft_stop_loss if soft_stop_loss else None,
        "hard_stop_loss": hard_stop_loss if hard_stop_loss else None,
        "soft_stop_required_closes": soft_stop_required_closes,
        "stop_zone_low": stop_zone_low if stop_zone_low else None,
        "stop_zone_high": stop_zone_high if stop_zone_high else None,
        "take_profit": take_profit if take_profit else None,
        "tp1_price": tp1 if tp1 else None,
        "tp1_zone_low": tp1_zone_low if tp1_zone_low else None,
        "tp1_zone_high": tp1_zone_high if tp1_zone_high else None,
        "tp2_price": tp2 if tp2 else None,
        "tp2_zone_low": tp2_zone_low if tp2_zone_low else None,
        "tp2_zone_high": tp2_zone_high if tp2_zone_high else None,
        "tp3_price": tp3 if tp3 else None,
        "tp3_zone_low": tp3_zone_low if tp3_zone_low else None,
        "tp3_zone_high": tp3_zone_high if tp3_zone_high else None,
        "tp_stage": 0,
        "original_quantity": quantity_base,
        "current_quantity": quantity_base,
        "highest_price": entry_price,
        "lowest_price": entry_price,
        "atr_at_entry": atr if atr else None,
        "effective_risk_pct": effective_risk_pct if effective_risk_pct else None,
        "sl_atr_mult": sl_atr_mult if sl_atr_mult else None,
        "structure_stop_floor_triggered": int(structure_stop_floor_triggered),
        "status": "OPEN",
        "entry_reason": getattr(signal, "reason", None) or "strategy",
        "strategy_name": strategy_name,
        "opened_at": opened_at,
        "exchange_order_id": str(order_id),
    }
    trade_id = db.insert_trade(trade_data)
    logger.info(f"交易建立完成: trade_id={trade_id} {symbol} {signal.signal_type} orderId={order_id}")
    side_icon = "🟢" if signal.signal_type == "LONG" else "🔴"
    console(
        f"✅ {symbol} {side_icon} {signal.signal_type} 開倉！{strategy_name} | "
        f"{size_usdt / leverage if leverage else size_usdt:.0f}U × {leverage}x = {size_usdt:.0f}U"
    )
    console(
        f"   📍 入場 {fmt_price(entry_price)} | 🛡 SL {fmt_price(soft_stop_loss)}/{fmt_price(hard_stop_loss)} | "
        f"🎯 {fmt_price(tp1)}/{fmt_price(tp2)}/{fmt_price(tp3)}"
    )

    mode = "Testnet" if BINANCE_TESTNET else "實盤"
    margin_cost = size_usdt / leverage if leverage else size_usdt
    open_msg = _build_trade_open_message(
        is_test=is_test_notification,
        version="V9",
        mode=mode,
        symbol=symbol,
        side=signal.signal_type,
        strategy_name=strategy_name,
        strategy_family=strategy_family,
        margin_cost=margin_cost,
        size_usdt=size_usdt,
        leverage=leverage,
        entry_price=entry_price,
        soft_stop_loss=soft_stop_loss,
        hard_stop_loss=hard_stop_loss,
        soft_stop_required_closes=soft_stop_required_closes,
        tp1=tp1,
        tp2=tp2,
        tp3=tp3,
    )
    send_telegram_message(open_msg)

    return trade_id

