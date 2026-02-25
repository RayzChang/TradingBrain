"""交易 API — 持倉與歷史"""

from fastapi import APIRouter, Depends

from api.deps import get_db
from database.db_manager import DatabaseManager

router = APIRouter()


@router.get("/open")
def open_trades(db: DatabaseManager = Depends(get_db)):
    """未平倉列表"""
    return db.get_open_trades()


@router.get("/today")
def trades_today(db: DatabaseManager = Depends(get_db)):
    """今日交易"""
    return db.get_trades_today()


@router.get("/daily-pnl")
def daily_pnl(db: DatabaseManager = Depends(get_db)):
    """今日累計損益"""
    return {"daily_pnl": db.get_daily_pnl()}


@router.get("/recent")
def recent_closed(limit: int = 20, db: DatabaseManager = Depends(get_db)):
    """最近已平倉"""
    return db.get_recent_closed_trades(limit=limit)
