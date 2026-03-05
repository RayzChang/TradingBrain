"""K 線數據 API — 提供蠟燭圖資料與交易標記"""

from typing import Optional

import httpx
from fastapi import APIRouter, Depends, Query

from api.deps import get_db
from config.settings import BINANCE_REST_URL
from database.db_manager import DatabaseManager

router = APIRouter()


@router.get("/{symbol}/{timeframe}")
async def get_klines(
    symbol: str,
    timeframe: str,
    limit: int = Query(default=300, le=500),
    db: DatabaseManager = Depends(get_db),
):
    """
    取得 K 線 OHLCV 數據。
    優先從 Binance REST API 取得（公開接口，不需 API Key）。
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{BINANCE_REST_URL}/fapi/v1/klines",
                params={"symbol": symbol.upper(), "interval": timeframe, "limit": limit},
            )
            raw = r.json()
            # Binance returns {"code": -1121, "msg": "Invalid symbol."} for bad symbols
            if isinstance(raw, dict) and "code" in raw:
                return {"error": f"幣種 {symbol.upper()} 不存在（{raw.get('msg', '未知錯誤')}）", "klines": []}
            if not isinstance(raw, list) or len(raw) == 0:
                return {"error": f"找不到 {symbol.upper()} 的數據", "klines": []}
    except Exception as e:
        return {"error": f"無法取得 K 線數據: {e}", "klines": []}

    klines = []
    for candle in raw:
        klines.append({
            "time": candle[0] // 1000,  # lightweight-charts 用秒級時間戳
            "open": float(candle[1]),
            "high": float(candle[2]),
            "low": float(candle[3]),
            "close": float(candle[4]),
            "volume": float(candle[5]),
        })

    return {"symbol": symbol.upper(), "timeframe": timeframe, "klines": klines}


@router.get("/{symbol}/trade-markers")
def get_trade_markers(
    symbol: str,
    limit: int = Query(default=50, le=200),
    db: DatabaseManager = Depends(get_db),
):
    """
    取得該幣種的歷史買賣點標記（供 K 線圖標記用）。
    回傳開倉和平倉的時間、價格、方向。
    """
    all_trades = db.get_recent_closed_trades(limit=limit)
    open_trades = db.get_open_trades()

    markers = []

    # 已平倉的交易
    for t in all_trades:
        if t.get("symbol") != symbol.upper():
            continue
        side = (t.get("side") or "LONG").upper()

        # 開倉標記
        if t.get("opened_at"):
            markers.append({
                "time": t["opened_at"],
                "position": "belowBar" if side == "LONG" else "aboveBar",
                "color": "#00ff88" if side == "LONG" else "#ff4466",
                "shape": "arrowUp" if side == "LONG" else "arrowDown",
                "text": f"{'做多' if side == 'LONG' else '做空'} {t.get('strategy_name', '')}",
                "type": "entry",
                "price": t.get("entry_price"),
            })

        # 平倉標記
        if t.get("closed_at") and t.get("exit_price"):
            pnl = t.get("pnl", 0) or 0
            markers.append({
                "time": t["closed_at"],
                "position": "aboveBar" if side == "LONG" else "belowBar",
                "color": "#00ff88" if pnl >= 0 else "#ff4466",
                "shape": "circle",
                "text": f"平倉 {'+' if pnl >= 0 else ''}{pnl:.2f}U",
                "type": "exit",
                "price": t.get("exit_price"),
            })

    # 未平倉的交易
    for t in open_trades:
        if t.get("symbol") != symbol.upper():
            continue
        side = (t.get("side") or "LONG").upper()
        if t.get("opened_at"):
            markers.append({
                "time": t["opened_at"],
                "position": "belowBar" if side == "LONG" else "aboveBar",
                "color": "#ffaa00",
                "shape": "arrowUp" if side == "LONG" else "arrowDown",
                "text": f"{'做多' if side == 'LONG' else '做空'} (持倉中)",
                "type": "entry_open",
                "price": t.get("entry_price"),
            })

    return {"symbol": symbol.upper(), "markers": markers}
