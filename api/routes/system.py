"""System status API endpoints."""

import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from api.deps import get_db
from config.settings import BINANCE_TESTNET, TRADING_INITIAL_BALANCE, TRADING_MODE
from database.db_manager import DatabaseManager

router = APIRouter()

_balance_cache: dict[str, float | None] = {"value": None}
_balance_cache_ts: float = 0.0
_BALANCE_CACHE_TTL: float = 30.0


@router.get("/status")
async def system_status(db: DatabaseManager = Depends(get_db)):
    """Return a lightweight status snapshot for the dashboard."""
    global _balance_cache, _balance_cache_ts

    daily_pnl = db.get_daily_pnl()
    open_trades = db.get_open_trades()
    total_pnl = db.get_total_realized_pnl()

    exchange_balance = None
    now = time.time()
    should_query_exchange = TRADING_MODE == "live" or (TRADING_MODE == "paper" and BINANCE_TESTNET)
    if should_query_exchange:
        exchange_balance = _balance_cache.get("value")
        if now - _balance_cache_ts > _BALANCE_CACHE_TTL:
            try:
                from core.execution.binance_client import BinanceFuturesClient

                client = BinanceFuturesClient()
                exchange_balance = await client.get_balance()
                _balance_cache["value"] = exchange_balance
                _balance_cache_ts = now
            except Exception:
                exchange_balance = _balance_cache.get("value")

    mode_label = TRADING_MODE
    if BINANCE_TESTNET and TRADING_MODE != "live":
        mode_label = f"{TRADING_MODE} [DEMO]"

    return {
        "mode": mode_label,
        "initial_balance": TRADING_INITIAL_BALANCE,
        "total_realized_pnl": total_pnl,
        "daily_pnl": daily_pnl,
        "open_positions_count": len(open_trades),
        "exchange_balance": exchange_balance,
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }
