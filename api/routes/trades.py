"""交易 API — 持倉與歷史"""

from typing import Any

import httpx
from fastapi import APIRouter, Depends

from api.deps import get_db
from config.settings import BINANCE_REST_URL
from database.db_manager import DatabaseManager

router = APIRouter()


def _fetch_ticker_price(symbol: str) -> float | None:
    """向幣安公開接口取得最新價（不需 API Key）"""
    try:
        with httpx.Client(timeout=5.0) as client:
            r = client.get(f"{BINANCE_REST_URL}/fapi/v1/ticker/price", params={"symbol": symbol})
            r.raise_for_status()
            data = r.json()
            return float(data.get("price", 0)) if data.get("price") else None
    except Exception:
        return None


@router.get("/open")
def open_trades(db: DatabaseManager = Depends(get_db)):
    """未平倉列表（含 DB 既有欄位：stop_loss, take_profit, strategy_name）"""
    return db.get_open_trades()


@router.get("/open-with-pnl")
def open_trades_with_pnl(db: DatabaseManager = Depends(get_db)):
    """
    未平倉列表 + 當前價與未實現損益。
    回傳每筆的 current_price、unrealized_pnl，以及總計 total_unrealized_pnl。
    """
    open_list = db.get_open_trades()
    if not open_list:
        return {"open_trades": [], "total_unrealized_pnl": 0.0}

    symbols_seen: dict[str, float | None] = {}
    for t in open_list:
        sym = t.get("symbol")
        if sym and sym not in symbols_seen:
            symbols_seen[sym] = _fetch_ticker_price(sym)

    result: list[dict[str, Any]] = []
    total_unrealized = 0.0
    for t in open_list:
        row = dict(t)
        entry = float(t.get("entry_price") or 0)
        qty = float(t.get("quantity") or 0)
        side = (t.get("side") or "LONG").upper()
        current = symbols_seen.get(t.get("symbol")) if t.get("symbol") else None
        if current is not None and entry and qty:
            if side == "LONG":
                u_pnl = (current - entry) * qty
            else:
                u_pnl = (entry - current) * qty
            row["current_price"] = current
            row["unrealized_pnl"] = round(u_pnl, 2)
            total_unrealized += u_pnl
        else:
            row["current_price"] = None
            row["unrealized_pnl"] = None
        result.append(row)

    return {
        "open_trades": result,
        "total_unrealized_pnl": round(total_unrealized, 2),
    }


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
