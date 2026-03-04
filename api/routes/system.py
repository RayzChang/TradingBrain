"""系統狀態 API"""

import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from api.deps import get_db
from config.settings import TRADING_MODE, TRADING_INITIAL_BALANCE, BINANCE_TESTNET
from database.db_manager import DatabaseManager

router = APIRouter()

# ── 餘額快取（避免每次輪詢都打交易所 API）──
_balance_cache: dict[str, float | None] = {"value": None}
_balance_cache_ts: float = 0.0
_BALANCE_CACHE_TTL: float = 30.0  # 30 秒


@router.get("/status")
async def system_status(db: DatabaseManager = Depends(get_db)):
    """儀表板用：模式、餘額參考、今日損益、未平倉數、交易所實際餘額"""
    global _balance_cache, _balance_cache_ts

    daily_pnl = db.get_daily_pnl()
    open_trades = db.get_open_trades()
    total_pnl = db.get_total_realized_pnl()

    # 嘗試從交易所取得真實餘額（帶快取）
    exchange_balance = _balance_cache.get("value")
    now = time.time()
    if TRADING_MODE in ("live", "paper") and BINANCE_TESTNET:
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
    if BINANCE_TESTNET:
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
