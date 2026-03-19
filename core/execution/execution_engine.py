"""
?瑁?撘? ??銝脫憸冽蝯??馳摰??柴神??DB

- 璅⊥嚗8嚗?BINANCE_TESTNET=true 銝?API Key 撌脰身摰?????Testnet 銝
- 撖衣嚗9嚗?BINANCE_TESTNET=false?RADING_MODE=live 銝?API Key 撌脰身摰????冽迤撘?銝
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
from core.risk.exit_profiles import get_exit_profile
from notifications.telegram_notify import send_telegram_message

if TYPE_CHECKING:
    from core.risk.risk_manager import RiskCheckResult
    from core.strategy.base import TradeSignal
    from database.db_manager import DatabaseManager


def is_trading_enabled() -> bool:
    """
    ?臬?瑁??祕銝嚗estnet ?祕?歹???
    - Testnet嚗INANCE_TESTNET=true 銝?API Key 撌脰身摰?
    - 撖衣嚗INANCE_TESTNET=false?RADING_MODE=live 銝?API Key 撌脰身摰???蝣箄??脰炊閫賂?
    """
    if not BINANCE_API_KEY:
        return False
    # paper 璅∪?瘞賊?銝?鈭斗??嚗璅⊥?漱撖?DB嚗?
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
    """
    靘◢?抒??鈭斗??銝??孵嚗???撖怠 trades 銵具?

    Args:
        signal: ???行捱?漱?縑??
        risk_result: 憸冽??蝯?嚗ize_usdt, leverage, stop_loss, take_profit嚗?
        entry_price: ?嗅?/?脣??
        db: 鞈?摨怎恣?
        strategy_name: 蝑?迂嚗敺?signal.strategy_name ??嚗?

    Returns:
        ??????DB trade id嚗?瑁??仃????None
    """
    if not risk_result.passed:
        return None

    strategy_name = strategy_name or signal.strategy_name
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

    # === paper 璅∪?嚗芋?祆?鈭歹?撖?DB嚗??漱??嚗?==
    if TRADING_MODE == "paper":
        quantity_base = size_usdt / entry_price if entry_price else 0
        if quantity_base <= 0:
            logger.warning(f"paper execute_trade: entry_price ?⊥? {entry_price}")
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
        msg = (
            f"✅ TradingBrain V7 模擬開倉\n"
            f"{symbol} {signal.signal_type} | 保證金 {paper_margin:.0f}U | 名義倉位 {size_usdt:.0f}U ({leverage}x)\n"
            f"進場: {entry_price:.2f}\n"
            f"Soft SL: {soft_stop_loss:.4f} | Hard SL: {hard_stop_loss:.4f}\n"
            f"TP1: {tp1:.4f} | TP2: {tp2:.4f} | TP3: {tp3:.4f}"
        )
        send_telegram_message(msg)
        logger.info(f"paper ???? trade_id={trade_id} {symbol} {signal.signal_type}")
        return trade_id

    if not is_trading_enabled():
        logger.info(
            f"鈭斗??芸??? {symbol} {signal.signal_type} "
            f"size={size_usdt}U sl={stop_loss} (??log嚗銝)"
        )
        return None

    quantity_base = size_usdt / entry_price if entry_price else 0
    if quantity_base <= 0:
        logger.warning(f"execute_trade: entry_price ?⊥? {entry_price}")
        return None

    client = BinanceFuturesClient()
    exchange_managed_protection = client.supports_algo_orders()
    use_leverage = leverage
    try:
        await client.set_leverage(symbol, leverage)
    except Exception as e:
        logger.warning(f"set_leverage({leverage}x) 憭望?: {e}")
        # Testnet 撣詨?擃?獢踹? 400嚗??.env ?身瑽▼?岫銝甈?
        use_leverage = max(1, min(DEFAULT_LEVERAGE, 25))
        try:
            await client.set_leverage(symbol, use_leverage)
        except Exception as e2:
            logger.error(f"set_leverage({use_leverage}x) 隞仃???箏??刻絲閬?銝: {e2}")
            return None
        logger.info(f"撌脫?冽?獢?{use_leverage}x 蝜潛?銝")

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

    mode = "Testnet" if BINANCE_TESTNET else "撖衣"
    margin_cost = size_usdt / leverage if leverage else size_usdt
    open_msg = (
        f"✅ TradingBrain V7 開倉 ({mode})\n"
        f"{symbol} {signal.signal_type} | 策略: {strategy_name}\n"
        f"保證金 {margin_cost:.0f} U | 名義倉位 {size_usdt:.0f} U ({leverage}x)\n"
        f"進場: {entry_price:.4f}\n"
        f"Soft SL: {soft_stop_loss:.4f} | Hard SL: {hard_stop_loss:.4f}\n"
        f"TP1: {tp1:.4f} | TP2: {tp2:.4f} | TP3: {tp3:.4f}"
    )
    send_telegram_message(open_msg)

    return trade_id

