"""
TradingBrain Web API — FastAPI 應用入口

提供儀表板所需之 REST 端點：風控參數、信號、持倉、系統狀態。
認證：HTTP Basic（DASHBOARD_USERNAME / DASHBOARD_PASSWORD）。
"""

import sys
from pathlib import Path

# 專案根目錄加入 path，供 import core / database / config
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import secrets

from config.settings import (
    API_HOST,
    API_PORT,
    DASHBOARD_USERNAME,
    DASHBOARD_PASSWORD,
    TRADING_MODE,
    TRADING_INITIAL_BALANCE,
)
from api.routes import risk, signals, trades, system, backtest

app = FastAPI(
    title="TradingBrain API",
    description="加密貨幣自動交易系統 — 儀表板後端",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

security = HTTPBasic()


def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)) -> str:
    """驗證儀表板帳密"""
    correct_user = secrets.compare_digest(credentials.username.encode("utf-8"), DASHBOARD_USERNAME.encode("utf-8"))
    correct_pass = secrets.compare_digest(credentials.password.encode("utf-8"), DASHBOARD_PASSWORD.encode("utf-8"))
    if not (correct_user and correct_pass):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return credentials.username


# 掛載路由（皆需認證）
app.include_router(risk.router, prefix="/api/risk", tags=["risk"], dependencies=[Depends(verify_credentials)])
app.include_router(signals.router, prefix="/api/signals", tags=["signals"], dependencies=[Depends(verify_credentials)])
app.include_router(trades.router, prefix="/api/trades", tags=["trades"], dependencies=[Depends(verify_credentials)])
app.include_router(system.router, prefix="/api/system", tags=["system"], dependencies=[Depends(verify_credentials)])
app.include_router(backtest.router, prefix="/api/backtest", tags=["backtest"], dependencies=[Depends(verify_credentials)])


@app.get("/api/health")
def health():
    """無需認證的健康檢查"""
    return {"status": "ok", "mode": TRADING_MODE}


def run_api():
    """供 main 或單獨啟動時呼叫"""
    import uvicorn
    uvicorn.run(
        "api.app:app",
        host=API_HOST,
        port=API_PORT,
        reload=False,
    )


if __name__ == "__main__":
    run_api()
