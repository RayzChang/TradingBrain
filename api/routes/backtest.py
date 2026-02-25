"""回測 API — 觸發回測並回傳績效摘要"""

from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException

from api.deps import get_db
from config.settings import KLINE_DATA_DIR
from core.backtest.engine import BacktestEngine
from core.backtest.report import get_report_dict
from database.db_manager import DatabaseManager

router = APIRouter()


@router.post("/run")
def run_backtest(
    body: dict = Body(...),
    db: DatabaseManager = Depends(get_db),
):
    """
    執行回測。body: { "symbol": "BTCUSDT", "timeframe": "15m", "initial_balance": 300 }
    若無對應 Parquet 則回傳 404。
    """
    symbol = body.get("symbol", "BTCUSDT")
    timeframe = body.get("timeframe", "15m")
    initial_balance = float(body.get("initial_balance", 300))

    path = KLINE_DATA_DIR / f"{symbol}_{timeframe}.parquet"
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"找不到 K 線檔案: {symbol}_{timeframe}.parquet，請先執行數據採集或使用 run_backtest.py 模擬數據",
        )

    engine = BacktestEngine(
        symbol=symbol,
        timeframe=timeframe,
        initial_balance=initial_balance,
        slippage_pct=0.001,
        fee_rate=0.0004,
    )
    df = engine.load_data(path)
    if len(df) < 100:
        raise HTTPException(status_code=400, detail="K 線數量不足 100 根")

    result = engine.run(df)
    return {
        "report": get_report_dict(result),
        "n_trades": result.n_trades,
        "trades": [
            {
                "entry_time": t.entry_time,
                "exit_time": t.exit_time,
                "side": t.side,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "pnl": round(t.pnl, 2),
                "pnl_pct": round(t.pnl_pct, 2),
                "exit_reason": t.exit_reason,
            }
            for t in result.trades[:50]
        ],
    }
