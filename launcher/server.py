"""
Launcher FastAPI Server

提供啟動器 REST API 端點 + 伺服靜態 UI。
在 port 8899 運行（與 TradingBrain API 的 8888 分開）。
"""

import sys
from pathlib import Path

# 專案根加入 path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from launcher.bridge import LauncherBridge

app = FastAPI(title="TradingBrain Launcher", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全域 bridge 實例
bridge = LauncherBridge()

# ─── API 端點 ─────────────────────────────────────────

@app.get("/api/env")
def get_env():
    return bridge.load_env()

@app.post("/api/env")
def save_env(data: dict):
    return bridge.save_env(data)

@app.post("/api/setup")
def run_setup():
    bridge.run_setup()
    return {"message": "Setup started"}

@app.post("/api/brain/start")
def start_brain():
    return bridge.start_brain()

@app.post("/api/brain/stop")
def stop_brain():
    return bridge.stop_brain()

@app.get("/api/status")
def get_status():
    return bridge.get_status()

@app.get("/api/logs")
def get_logs(n: int = 80):
    return bridge.get_logs(n)



# ─── 靜態檔案伺服 ────────────────────────────────────

UI_DIR = Path(__file__).parent / "ui"

@app.get("/")
def serve_index():
    return FileResponse(str(UI_DIR / "index.html"))

# 掛載靜態資源（css, js）
if UI_DIR.exists():
    app.mount("/ui", StaticFiles(directory=str(UI_DIR)), name="ui")
