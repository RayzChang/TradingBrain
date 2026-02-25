"""系統狀態 API"""

from fastapi import APIRouter, Depends

from api.deps import get_db
from config.settings import TRADING_MODE, TRADING_INITIAL_BALANCE
from database.db_manager import DatabaseManager

router = APIRouter()


@router.get("/status")
def system_status(db: DatabaseManager = Depends(get_db)):
    """儀表板用：模式、餘額參考、今日損益、未平倉數"""
    daily_pnl = db.get_daily_pnl()
    open_trades = db.get_open_trades()
    total_pnl = db.get_total_realized_pnl()
    return {
        "mode": TRADING_MODE,
        "initial_balance": TRADING_INITIAL_BALANCE,
        "total_realized_pnl": total_pnl,
        "daily_pnl": daily_pnl,
        "open_positions_count": len(open_trades),
    }
