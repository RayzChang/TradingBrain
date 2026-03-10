"""Runtime settings for TradingBrain."""

import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


# === Binance API ===
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "").strip()
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "").strip()
BINANCE_TESTNET = os.getenv("BINANCE_TESTNET", "true").lower() == "true"

BINANCE_TESTNET_REST = os.getenv("BINANCE_TESTNET_REST", "https://demo-fapi.binance.com").strip()
BINANCE_TESTNET_WS = os.getenv("BINANCE_TESTNET_WS", "wss://fstream.binance.com").strip()
BINANCE_LIVE_REST = os.getenv("BINANCE_LIVE_REST", "https://fapi.binance.com").strip()
BINANCE_LIVE_WS = os.getenv("BINANCE_LIVE_WS", "wss://fstream.binance.com").strip()

BINANCE_REST_URL = BINANCE_TESTNET_REST if BINANCE_TESTNET else BINANCE_LIVE_REST
BINANCE_WS_URL = BINANCE_TESTNET_WS if BINANCE_TESTNET else BINANCE_LIVE_WS
RELAX_VETO_ON_TESTNET = os.getenv("RELAX_VETO_ON_TESTNET", "true").lower() == "true"


# === LINE Messaging API ===
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
LINE_USER_ID = os.getenv("LINE_USER_ID", "").strip()


# === Web Dashboard ===
DASHBOARD_USERNAME = os.getenv("DASHBOARD_USERNAME", "admin").strip() or "admin"
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "").strip()
SECRET_KEY = os.getenv("SECRET_KEY", "").strip()
API_HOST = os.getenv("API_HOST", "0.0.0.0").strip() or "0.0.0.0"
API_PORT = int(os.getenv("API_PORT", "8888"))


# === Trading ===
TRADING_INITIAL_BALANCE = float(os.getenv("TRADING_INITIAL_BALANCE", "300"))
TRADING_MODE = os.getenv("TRADING_MODE", "paper").strip().lower() or "paper"


# === Database ===
DB_PATH = BASE_DIR / "data" / "trading_brain.db"
KLINE_DATA_DIR = BASE_DIR / "data" / "klines"


# === Logging ===
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO"
LOG_DIR = BASE_DIR / "logs"
APP_TIMEZONE_NAME = os.getenv("APP_TIMEZONE", "Asia/Bangkok").strip() or "Asia/Bangkok"
APP_TIMEZONE = ZoneInfo(APP_TIMEZONE_NAME)


# === API Rate Limiting (Binance) ===
RATE_LIMIT_WEIGHT_PER_MINUTE = 1200
RATE_LIMIT_ORDER_PER_MINUTE = 300
RATE_LIMIT_SAFETY_MARGIN = 0.8


# === Scheduler Intervals ===
SCHEDULER_CONFIG = {
    "websocket_klines": {"type": "persistent", "desc": "Realtime kline websocket"},
    "funding_rate": {"interval_min": 30, "desc": "Funding rate monitor"},
    "liquidation_monitor": {"interval_min": 5, "desc": "Liquidation monitor"},
    "fear_greed_index": {"interval_min": 60, "desc": "Fear and Greed monitor"},
    "coin_screening": {"interval_min": 60, "desc": "Coin screener"},
    "strategy_evaluation": {"interval_min": 1, "desc": "Strategy evaluation"},
    "position_check": {
        "interval_sec": int(os.getenv("POSITION_CHECK_INTERVAL_SECONDS", "5")),
        "desc": "Open position check",
    },
    "heartbeat": {"interval_min": 10, "desc": "Health heartbeat"},
    "monitor_report": {"interval_min": 60, "desc": "Periodic monitor report"},
    "daily_report": {"cron": "0 0 * * *", "desc": "Daily report"},
    "kline_to_parquet": {"cron": "0 */6 * * *", "desc": "Persist kline data"},
}


# === K-line Timeframes ===
KLINE_TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"]
PRIMARY_TIMEFRAME = "15m"


# === Default Watchlist ===
DEFAULT_WATCHLIST = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "DOTUSDT", "LINKUSDT",
    "MATICUSDT", "NEARUSDT", "ARBUSDT", "OPUSDT", "APTUSDT",
    "SUIUSDT", "ATOMUSDT", "FILUSDT", "LTCUSDT", "UNIUSDT",
]


# === Margin ===
MARGIN_TYPE = os.getenv("MARGIN_TYPE", "CROSSED").upper()
if MARGIN_TYPE not in ("CROSSED", "ISOLATED"):
    MARGIN_TYPE = "CROSSED"
DEFAULT_LEVERAGE = int(os.getenv("DEFAULT_LEVERAGE", "2"))


def runtime_config_errors() -> list[str]:
    """Return configuration errors that should block startup."""
    errors: list[str] = []

    if TRADING_MODE not in {"paper", "live"}:
        errors.append("TRADING_MODE must be 'paper' or 'live'.")

    if TRADING_MODE != "paper" and (not BINANCE_API_KEY or not BINANCE_API_SECRET):
        errors.append("Exchange trading requires BINANCE_API_KEY and BINANCE_API_SECRET.")

    return errors


def runtime_config_warnings() -> list[str]:
    """Return warnings that should be logged but not block startup."""
    warnings: list[str] = []

    if TRADING_MODE != "paper" and (not DASHBOARD_PASSWORD or DASHBOARD_PASSWORD == "changeme"):
        warnings.append("Dashboard password is empty or still using the default value.")
    if TRADING_MODE != "paper" and (not SECRET_KEY or SECRET_KEY.startswith("dev-")):
        warnings.append("SECRET_KEY is missing or weak.")
    if TRADING_MODE == "live" and BINANCE_TESTNET:
        warnings.append("TRADING_MODE=live with BINANCE_TESTNET=true means exchange-connected demo mode, not real-money live trading.")

    return warnings
