"""
日誌系統配置

使用 loguru 提供分級日誌、檔案輪轉、控制台彩色輸出。
Console 只顯示標記為 console=True 的訊息或 WARNING 以上的訊息，
其餘 INFO/DEBUG 只寫入檔案。
"""

import sys
from datetime import datetime
from pathlib import Path

from loguru import logger

from config.settings import LOG_DIR, LOG_LEVEL


def _console_filter(record: dict) -> bool:
    """Console sink 過濾器：只放行 console 標記的訊息或 ERROR+"""
    if record["level"].no >= 40:  # ERROR = 40
        return True
    return record["extra"].get("console", False)


def setup_logger() -> None:
    """初始化全局日誌配置"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    # 取消預設的 stderr 輸出，避免 log 重複。但不使用 logger.remove() 清除所有
    # 因為 launcher_bridge 已經註冊了 LogCapture sink
    try:
        logger.remove(0)
    except ValueError:
        pass

    # 控制台輸出（彩色）— 只顯示 console 標記的訊息或 WARNING+
    logger.add(
        sys.stderr,
        level=LOG_LEVEL,
        format=(
            "<green>{time:HH:mm:ss}</green> | "
            "<level>{message}</level>"
        ),
        filter=_console_filter,
        colorize=True,
    )

    # 一般日誌檔（每天輪轉，保留 30 天）
    logger.add(
        LOG_DIR / "trading_{time:YYYY-MM-DD}.log",
        level="DEBUG",
        rotation="00:00",
        retention="30 days",
        compression="zip",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}",
        encoding="utf-8",
    )

    # 錯誤日誌（獨立檔案，方便排查）
    logger.add(
        LOG_DIR / "error_{time:YYYY-MM-DD}.log",
        level="ERROR",
        rotation="00:00",
        retention="60 days",
        compression="zip",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}\n{exception}",
        encoding="utf-8",
    )

    # 交易專用日誌（記錄所有交易操作）
    logger.add(
        LOG_DIR / "trades_{time:YYYY-MM-DD}.log",
        level="INFO",
        rotation="00:00",
        retention="90 days",
        filter=lambda record: "trade" in record["extra"].get("category", ""),
        format="{time:YYYY-MM-DD HH:mm:ss} | {message}",
        encoding="utf-8",
    )

    logger.info("Logger initialized")


def get_trade_logger():
    """取得交易專用 logger"""
    return logger.bind(category="trade")


# ── Console 專用輸出工具 ──

_console_logger = logger.bind(console=True)


def console(msg: str) -> None:
    """輸出到 console 的乾淨訊息（同時寫入檔案 log）"""
    _console_logger.info(msg)


def fmt_price(price: float) -> str:
    """根據價格大小自動調整小數位數"""
    if price >= 1000:
        return f"{price:,.0f}"
    if price >= 10:
        return f"{price:.2f}"
    if price >= 1:
        return f"{price:.3f}"
    return f"{price:.4f}"
