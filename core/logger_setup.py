"""
日誌系統配置

使用 loguru 提供分級日誌、檔案輪轉、控制台彩色輸出。
"""

import sys
from pathlib import Path

from loguru import logger

from config.settings import LOG_DIR, LOG_LEVEL


def setup_logger() -> None:
    """初始化全局日誌配置"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger.remove()

    # 控制台輸出（彩色）
    logger.add(
        sys.stderr,
        level=LOG_LEVEL,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        ),
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
