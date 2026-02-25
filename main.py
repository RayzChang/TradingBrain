"""
TradingBrain — 加密貨幣自動交易系統

主程式入口。啟動所有子系統：
1. 日誌系統
2. 資料庫初始化 + 風控參數載入
3. 資訊管線排程（資金費率、爆倉、恐懼貪婪）
4. WebSocket K 線數據流
5. 否決引擎
6. 技術分析引擎
7. 策略與信號系統（多策略投票 + 否決過濾）
8. 風險管理核心（倉位/止損/熔斷/冷卻）
9. Web 儀表板 API（FastAPI，與主程式同進程背景執行）
10. (未來) 交易執行
"""

import asyncio
import json
import signal
import threading
import time
from pathlib import Path

import pandas as pd
from loguru import logger

from config.settings import (
    TRADING_MODE, DB_PATH, KLINE_DATA_DIR,
    SCHEDULER_CONFIG, DEFAULT_WATCHLIST,
    API_PORT,
)
from core.logger_setup import setup_logger
from core.data.websocket_feed import BinanceWebSocketFeed
from core.pipeline.scheduler import TaskScheduler
from core.pipeline.funding_rate import FundingRateMonitor
from core.pipeline.fear_greed import FearGreedMonitor
from core.pipeline.liquidation import LiquidationMonitor
from core.pipeline.veto_engine import VetoEngine
from core.analysis.engine import AnalysisEngine
from core.analysis.chop_detector import detect_chop
from core.strategy.trend_following import TrendFollowingStrategy
from core.strategy.mean_reversion import MeanReversionStrategy
from core.strategy.signal_aggregator import SignalAggregator
from core.strategy.coin_screener import CoinScreener
from core.risk.risk_manager import RiskManager
from config.settings import TRADING_INITIAL_BALANCE
from database.db_manager import DatabaseManager


class TradingBrain:
    """交易系統主控制器"""

    def __init__(self) -> None:
        self.running = False
        self.db: DatabaseManager | None = None
        self.scheduler: TaskScheduler | None = None
        self.ws_feed: BinanceWebSocketFeed | None = None
        self.funding_monitor: FundingRateMonitor | None = None
        self.fear_greed_monitor: FearGreedMonitor | None = None
        self.liquidation_monitor: LiquidationMonitor | None = None
        self.veto_engine: VetoEngine | None = None
        self.analysis_engine: AnalysisEngine | None = None
        self.signal_aggregator: SignalAggregator | None = None
        self.coin_screener: CoinScreener | None = None
        self.risk_manager: RiskManager | None = None

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

        # 1. 初始化資料庫
        self.db = DatabaseManager()
        logger.info("資料庫初始化完成 (SQLite-WAL)")

        # 2. 載入風控預設參數
        self._load_risk_defaults()
        logger.info("風控參數載入完成")

        # 3. 初始化資訊管線模組
        self.funding_monitor = FundingRateMonitor(self.db)
        self.fear_greed_monitor = FearGreedMonitor(self.db)
        self.liquidation_monitor = LiquidationMonitor(self.db)

        # 4. 初始化否決引擎
        self.veto_engine = VetoEngine(
            db=self.db,
            funding_monitor=self.funding_monitor,
            fear_greed_monitor=self.fear_greed_monitor,
            liquidation_monitor=self.liquidation_monitor,
        )
        logger.info("否決引擎初始化完成")

        # 5. 初始化技術分析引擎
        self.analysis_engine = AnalysisEngine()
        logger.info("技術分析引擎初始化完成")

        # 5b. 初始化策略與信號聚合器
        strategies = [
            TrendFollowingStrategy(adx_min=25.0, skip_on_chop=True),
            MeanReversionStrategy(rsi_oversold=30, rsi_overbought=70, skip_on_chop=True),
        ]
        self.signal_aggregator = SignalAggregator(
            strategies=strategies,
            veto_engine=self.veto_engine,
            db=self.db,
        )
        self.coin_screener = CoinScreener()
        logger.info("策略與信號聚合器初始化完成")

        # 5c. 初始化風控核心
        self.risk_manager = RiskManager(self.db)
        logger.info("風控核心初始化完成")

        # 6. 初始化 WebSocket 數據流
        self.ws_feed = BinanceWebSocketFeed(
            symbols=DEFAULT_WATCHLIST,
            timeframes=["1m", "15m", "1h", "4h"],
            on_kline=self._on_kline_closed,
        )

        # 7. 初始化排程器並註冊任務
        self.scheduler = TaskScheduler(self.db)
        self._register_scheduled_tasks()

        self.running = True
        logger.info("TradingBrain 啟動完成！")
        logger.info(f"資料庫: {DB_PATH}")
        logger.info(f"監控幣種: {', '.join(DEFAULT_WATCHLIST)}")
        logger.info(f"交易模式: {TRADING_MODE}")

        # 8. 啟動 Web API（儀表板後端，背景執行）
        def _run_api():
            import uvicorn
            uvicorn.run(
                "api.app:app",
                host="0.0.0.0",
                port=API_PORT,
                log_level="warning",
            )
        api_thread = threading.Thread(target=_run_api, daemon=True)
        api_thread.start()
        logger.info(f"儀表板 API: http://0.0.0.0:{API_PORT} （前端請另開 npm run dev 並開 http://localhost:5173）")

    def _load_risk_defaults(self) -> None:
        """從 risk_defaults.json 載入預設風控參數"""
        defaults_path = Path("config/risk_defaults.json")
        if not defaults_path.exists():
            return

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

    def _register_scheduled_tasks(self) -> None:
        """註冊所有定時任務到排程器"""
        # 資金費率 - 每 30 分鐘
        self.scheduler.add_interval_task(
            "funding_rate", self.funding_monitor.fetch_and_store,
            minutes=30, description="資金費率監控",
        )

        # 爆倉數據 - 每 5 分鐘
        self.scheduler.add_interval_task(
            "liquidation_monitor", self.liquidation_monitor.fetch_and_store,
            minutes=5, description="爆倉數據掃描",
        )

        # 恐懼貪婪指數 - 每 60 分鐘
        self.scheduler.add_interval_task(
            "fear_greed_index", self.fear_greed_monitor.fetch_and_store,
            minutes=60, description="恐懼貪婪指數",
        )

        # TODO Phase3+: 策略評估 - 每 1 分鐘
        # TODO Phase3+: 持倉檢查 - 每 1 分鐘
        # TODO Phase4+: 幣種篩選 - 每 60 分鐘

        # 每日報告 - 每天 UTC 00:00
        self.scheduler.add_cron_task(
            "daily_report", self._daily_report,
            cron_expr="0 0 * * *", description="每日績效報告",
        )

    async def _on_kline_closed(self, candle: dict) -> None:
        """
        K 線收盤回調 — 每當一根 K 線完成時觸發。
        觸發技術分析計算，並在適當時間框架上做完整 MTF 分析。
        """
        symbol = candle["symbol"]
        tf = candle["timeframe"]
        close = candle["close"]

        logger.debug(
            f"Kline closed: {symbol} {tf} close={close:.2f} vol={candle['volume']:.2f}"
        )

        # 從 WebSocket 快取取得 K 線數據並轉為 DataFrame
        cache_candles = self.ws_feed.cache.get(symbol.lower(), tf)
        if len(cache_candles) < 30:
            return

        df = pd.DataFrame(cache_candles)
        for col in ("open", "high", "low", "close", "volume"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # 單時間框架分析
        result = self.analysis_engine.analyze_single(symbol, tf, df)

        # 絞肉機偵測 → 同步更新否決引擎
        if result.chop and result.chop.is_chop:
            cooldown_until = time.time() + result.chop.cooldown_minutes * 60
            self.veto_engine.set_chop_active(True, cooldown_until)

        # 在 15m 收盤時做完整 MTF 分析（主進場時間框架）
        if tf == "15m":
            await self._run_mtf_analysis(symbol)

        # TODO Phase4: 觸發策略信號評估
        # TODO Phase5: 信號通過否決引擎 -> 風控 -> 執行

    async def _run_mtf_analysis(self, symbol: str) -> None:
        """執行完整多時間框架分析"""
        kline_data: dict[str, pd.DataFrame] = {}

        for tf in ["5m", "15m", "1h", "4h"]:
            cache_candles = self.ws_feed.cache.get(symbol.lower(), tf)
            if len(cache_candles) < 50:
                continue
            df = pd.DataFrame(cache_candles)
            for col in ("open", "high", "low", "close", "volume"):
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            kline_data[tf] = df

        if len(kline_data) < 2:
            return

        full = self.analysis_engine.analyze_full(symbol, kline_data)
        snapshot = self.analysis_engine.get_analysis_snapshot(full)

        logger.info(
            f"MTF分析 {symbol}: "
            f"趨勢={snapshot.get('mtf', {}).get('alignment', 'N/A')}, "
            f"方向={snapshot.get('mtf', {}).get('direction', 'N/A')}, "
            f"信心={snapshot.get('mtf', {}).get('confidence', 0):.0%}"
        )

        # 策略評估 + 否決過濾，通過信號寫入 DB
        agg_result = self.signal_aggregator.evaluate(full, save_to_db=True)
        if agg_result.passed:
            logger.info(f"信號通過否決: {symbol} -> {len(agg_result.passed)} 筆")
        if agg_result.vetoed:
            logger.debug(f"信號被否決: {symbol} -> {len(agg_result.vetoed)} 筆")

        # 風控評估：通過否決的信號進入風控（倉位/止損/熔斷/冷卻）
        primary = full.single_tf_results.get(full.primary_tf)
        if not primary or primary.df_enriched is None:
            primary = None
        balance = TRADING_INITIAL_BALANCE  # Phase6+ 改為交易所餘額
        open_trades = self.db.get_open_trades()
        for sig in agg_result.passed:
            entry_price = primary.df_enriched["close"].iloc[-1] if primary else 0
            atr_val = primary.indicators.get("atr") if primary else None
            if atr_val is None and primary and primary.df_enriched is not None:
                atr_val = primary.df_enriched["atr"].iloc[-1]
            atr = float(atr_val) if atr_val is not None else 0
            if primary and entry_price is not None and atr:
                risk_result = self.risk_manager.evaluate(
                    sig, balance, float(entry_price), atr, len(open_trades)
                )
                if risk_result.passed:
                    logger.info(
                        f"風控通過: {sig.symbol} {sig.signal_type} "
                        f"size={risk_result.size_usdt}U sl={risk_result.stop_loss} (待執行層下單)"
                    )
                else:
                    logger.info(f"風控攔截: {sig.symbol} {sig.signal_type} - {risk_result.reason}")

    async def _daily_report(self) -> None:
        """生成每日績效報告"""
        trades_today = self.db.get_trades_today()
        daily_pnl = self.db.get_daily_pnl()
        open_trades = self.db.get_open_trades()

        report = (
            f"📊 TradingBrain 每日報告\n"
            f"日期: {__import__('datetime').datetime.utcnow().strftime('%Y-%m-%d')}\n"
            f"今日交易: {len(trades_today)} 筆\n"
            f"今日損益: {daily_pnl:+.2f} USDT\n"
            f"未平倉位: {len(open_trades)} 個\n"
            f"模式: {TRADING_MODE}"
        )
        logger.info(report)
        # TODO Phase9: 透過 LINE 發送報告

    async def run(self) -> None:
        """主運行迴圈"""
        await self.startup()

        # 啟動排程器
        self.scheduler.start()

        # 首次啟動立即抓取資訊管線數據
        logger.info("首次啟動：立即獲取市場資訊...")
        await asyncio.gather(
            self.funding_monitor.fetch_and_store(),
            self.fear_greed_monitor.fetch_and_store(),
            self.liquidation_monitor.fetch_and_store(),
            return_exceptions=True,
        )

        # 啟動 WebSocket（在背景執行）
        ws_task = asyncio.create_task(self.ws_feed.start())

        try:
            while self.running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            await self.shutdown()
            ws_task.cancel()
            try:
                await ws_task
            except asyncio.CancelledError:
                pass

    async def shutdown(self) -> None:
        """系統關閉序列"""
        logger.info("TradingBrain 關閉中...")
        self.running = False

        if self.scheduler:
            self.scheduler.stop()

        if self.ws_feed:
            await self.ws_feed.stop()

        if self.funding_monitor:
            await self.funding_monitor.close()

        if self.fear_greed_monitor:
            await self.fear_greed_monitor.close()

        if self.liquidation_monitor:
            await self.liquidation_monitor.close()

        logger.info("TradingBrain 已安全關閉")


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
