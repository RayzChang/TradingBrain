"""
TradingBrain — 加密貨幣自動交易系統

主程式入口。啟動所有子系統：
1. 日誌系統
2. 資料庫初始化
3. 載入風控參數
4. 資訊管線排程
5. WebSocket 數據流
6. FastAPI 儀表板
7. Watchdog 進程守護
"""

import asyncio
import json
import signal
import sys
from pathlib import Path

from loguru import logger

from config.settings import TRADING_MODE, DB_PATH, KLINE_DATA_DIR
from core.logger_setup import setup_logger
from database.db_manager import DatabaseManager


class TradingBrain:
    """交易系統主控制器"""

    def __init__(self) -> None:
        self.running = False
        self.db: DatabaseManager | None = None

    async def startup(self) -> None:
        """系統啟動序列"""
        setup_logger()
        logger.info("=" * 60)
        logger.info("TradingBrain 啟動中...")
        logger.info(f"交易模式: {TRADING_MODE}")
        logger.info("=" * 60)

        # 確保必要目錄存在
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        KLINE_DATA_DIR.mkdir(parents=True, exist_ok=True)

        # 初始化資料庫
        self.db = DatabaseManager()
        logger.info("資料庫初始化完成")

        # 載入風控預設參數
        self._load_risk_defaults()
        logger.info("風控參數載入完成")

        self.running = True
        logger.info("TradingBrain 啟動完成！")
        logger.info(f"資料庫位置: {DB_PATH}")
        logger.info(f"K線資料目錄: {KLINE_DATA_DIR}")

        # TODO: Phase 2 - 啟動資訊管線排程
        # TODO: Phase 2 - 啟動 WebSocket 數據流
        # TODO: Phase 6 - 啟動 FastAPI 儀表板

    def _load_risk_defaults(self) -> None:
        """從 risk_defaults.json 載入預設風控參數"""
        defaults_path = Path("config/risk_defaults.json")
        if defaults_path.exists():
            with open(defaults_path, "r", encoding="utf-8") as f:
                config = json.load(f)

            active_preset = config.get("active_preset", "moderate")
            preset_params = config.get("presets", {}).get(active_preset, {})

            if preset_params:
                label = preset_params.pop("label", active_preset)
                self.db.load_risk_defaults(preset_params)
                self.db.set_risk_param(
                    "active_preset", active_preset, changed_by="system_default"
                )
                logger.info(f"風控預設方案: {label} ({active_preset})")

    async def shutdown(self) -> None:
        """系統關閉序列"""
        logger.info("TradingBrain 關閉中...")
        self.running = False

        # TODO: 關閉 WebSocket 連線
        # TODO: 關閉排程器
        # TODO: 確認無未處理的訂單

        logger.info("TradingBrain 已安全關閉")

    async def run(self) -> None:
        """主運行迴圈"""
        await self.startup()

        try:
            while self.running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            await self.shutdown()


def main() -> None:
    """程式進入點"""
    brain = TradingBrain()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def handle_signal(sig, frame):
        logger.info(f"收到信號 {sig}，準備關閉...")
        brain.running = False

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        loop.run_until_complete(brain.run())
    except KeyboardInterrupt:
        logger.info("收到鍵盤中斷")
        loop.run_until_complete(brain.shutdown())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
