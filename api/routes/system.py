"""系統狀態 API"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from api.deps import get_db
from config.settings import TRADING_MODE, TRADING_INITIAL_BALANCE, BINANCE_TESTNET
from database.db_manager import DatabaseManager

router = APIRouter()


@router.get("/status")
async def system_status(db: DatabaseManager = Depends(get_db)):
    """儀表板用：模式、餘額參考、今日損益、未平倉數、交易所實際餘額"""
    daily_pnl = db.get_daily_pnl()
    open_trades = db.get_open_trades()
    total_pnl = db.get_total_realized_pnl()

    # 嘗試從交易所取得真實餘額
    exchange_balance = None
    if TRADING_MODE in ("live", "paper") and BINANCE_TESTNET:
        try:
            from core.execution.binance_client import BinanceFuturesClient
            client = BinanceFuturesClient()
            exchange_balance = await client.get_balance()
        except Exception:
            exchange_balance = None

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
