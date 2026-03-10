from fastapi import APIRouter, Depends, Query
import httpx

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
    """Fetch OHLCV data for the chart from Binance Futures REST."""
    _ = db
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{BINANCE_REST_URL}/fapi/v1/klines",
                params={"symbol": symbol.upper(), "interval": timeframe, "limit": limit},
            )
            raw = response.json()
            if isinstance(raw, dict) and "code" in raw:
                return {
                    "symbol": symbol.upper(),
                    "timeframe": timeframe,
                    "klines": [],
                    "error": f"Binance rejected the request: {raw.get('msg', 'unknown error')}",
                }
            if not isinstance(raw, list) or len(raw) == 0:
                return {
                    "symbol": symbol.upper(),
                    "timeframe": timeframe,
                    "klines": [],
                    "error": f"No kline data returned for {symbol.upper()}.",
                }
    except Exception as exc:
        return {
            "symbol": symbol.upper(),
            "timeframe": timeframe,
            "klines": [],
            "error": f"Failed to fetch klines: {exc}",
        }

    klines = [
        {
            "time": candle[0] // 1000,
            "open": float(candle[1]),
            "high": float(candle[2]),
            "low": float(candle[3]),
            "close": float(candle[4]),
            "volume": float(candle[5]),
        }
        for candle in raw
    ]

    return {"symbol": symbol.upper(), "timeframe": timeframe, "klines": klines}


@router.get("/{symbol}/trade-markers")
def get_trade_markers(
    symbol: str,
    limit: int = Query(default=50, le=200),
    db: DatabaseManager = Depends(get_db),
):
    """Return chart markers for recent entries and exits."""
    all_trades = db.get_recent_closed_trades(limit=limit)
    open_trades = db.get_open_trades()

    markers = []

    for trade in all_trades:
        if trade.get("symbol") != symbol.upper():
            continue
        side = (trade.get("side") or "LONG").upper()
        entry_label = "Long" if side == "LONG" else "Short"

        if trade.get("opened_at"):
            markers.append(
                {
                    "time": trade["opened_at"],
                    "position": "belowBar" if side == "LONG" else "aboveBar",
                    "color": "#00ff88" if side == "LONG" else "#ff4466",
                    "shape": "arrowUp" if side == "LONG" else "arrowDown",
                    "text": f"{entry_label} {trade.get('strategy_name', '')}".strip(),
                    "type": "entry",
                    "price": trade.get("entry_price"),
                }
            )

        if trade.get("closed_at") and trade.get("exit_price"):
            pnl = trade.get("pnl", 0) or 0
            markers.append(
                {
                    "time": trade["closed_at"],
                    "position": "aboveBar" if side == "LONG" else "belowBar",
                    "color": "#00ff88" if pnl >= 0 else "#ff4466",
                    "shape": "circle",
                    "text": f"Exit {'+' if pnl >= 0 else ''}{pnl:.2f}U",
                    "type": "exit",
                    "price": trade.get("exit_price"),
                }
            )

    for trade in open_trades:
        if trade.get("symbol") != symbol.upper():
            continue
        side = (trade.get("side") or "LONG").upper()
        entry_label = "Long" if side == "LONG" else "Short"
        if trade.get("opened_at"):
            markers.append(
                {
                    "time": trade["opened_at"],
                    "position": "belowBar" if side == "LONG" else "aboveBar",
                    "color": "#ffaa00",
                    "shape": "arrowUp" if side == "LONG" else "arrowDown",
                    "text": f"{entry_label} (open)",
                    "type": "entry_open",
                    "price": trade.get("entry_price"),
                }
            )

    return {"symbol": symbol.upper(), "markers": markers}
