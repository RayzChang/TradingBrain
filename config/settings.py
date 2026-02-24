"""
TradingBrain 全局配置管理

從 .env 載入敏感資訊，集中管理所有系統配置。
"""

import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


# === Binance API ===
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")
BINANCE_TESTNET = os.getenv("BINANCE_TESTNET", "true").lower() == "true"

BINANCE_TESTNET_REST = "https://testnet.binancefuture.com"
BINANCE_TESTNET_WS = "wss://stream.binancefuture.com"
BINANCE_LIVE_REST = "https://fapi.binance.com"
BINANCE_LIVE_WS = "wss://fstream.binance.com"

BINANCE_REST_URL = BINANCE_TESTNET_REST if BINANCE_TESTNET else BINANCE_LIVE_REST
BINANCE_WS_URL = BINANCE_TESTNET_WS if BINANCE_TESTNET else BINANCE_LIVE_WS


# === LINE Messaging API ===
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_USER_ID = os.getenv("LINE_USER_ID", "")


# === Web Dashboard ===
DASHBOARD_USERNAME = os.getenv("DASHBOARD_USERNAME", "admin")
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "changeme")
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
API_HOST = "0.0.0.0"
API_PORT = 8888


# === Database ===
DB_PATH = BASE_DIR / "data" / "trading_brain.db"
KLINE_DATA_DIR = BASE_DIR / "data" / "klines"


# === Logging ===
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_DIR = BASE_DIR / "logs"


# === Trading Mode ===
TRADING_MODE = os.getenv("TRADING_MODE", "paper")  # paper | live


# === API Rate Limiting (Binance) ===
RATE_LIMIT_WEIGHT_PER_MINUTE = 1200
RATE_LIMIT_ORDER_PER_MINUTE = 300
RATE_LIMIT_SAFETY_MARGIN = 0.8  # use max 80% of limit


# === Scheduler Intervals (minutes) ===
SCHEDULER_CONFIG = {
    "websocket_klines":    {"type": "persistent",   "desc": "K線即時數據流"},
    "funding_rate":        {"interval_min": 30,      "desc": "資金費率監控"},
    "liquidation_monitor": {"interval_min": 5,       "desc": "爆倉數據掃描"},
    "fear_greed_index":    {"interval_min": 60,      "desc": "恐懼貪婪指數"},
    "coin_screening":      {"interval_min": 60,      "desc": "分批掃描幣種"},
    "strategy_evaluation": {"interval_min": 1,       "desc": "策略信號評估"},
    "position_check":      {"interval_min": 1,       "desc": "持倉/止損檢查"},
    "heartbeat":           {"interval_min": 10,      "desc": "LINE 心跳(靜默)"},
    "daily_report":        {"cron": "0 0 * * *",     "desc": "每日績效報告"},
    "kline_to_parquet":    {"cron": "0 */6 * * *",   "desc": "K線寫入Parquet"},
}


# === K-line Timeframes ===
KLINE_TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"]
PRIMARY_TIMEFRAME = "15m"


# === Default Watchlist (initial coins to monitor) ===
DEFAULT_WATCHLIST = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "DOTUSDT", "LINKUSDT",
]
