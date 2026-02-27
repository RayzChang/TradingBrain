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
10. 交易執行（Testnet 模擬 / 實盤）
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
    BINANCE_TESTNET,
    TRADING_MODE, DB_PATH, KLINE_DATA_DIR,
    SCHEDULER_CONFIG, DEFAULT_WATCHLIST,
    API_PORT,
    TRADING_INITIAL_BALANCE,
    BINANCE_TESTNET,
)
from core.logger_setup import setup_logger
from core.data.websocket_feed import BinanceWebSocketFeed
from core.data.market_data import MarketDataFetcher
from core.pipeline.scheduler import TaskScheduler
from core.pipeline.funding_rate import FundingRateMonitor
from core.pipeline.fear_greed import FearGreedMonitor
from core.pipeline.liquidation import LiquidationMonitor
from core.pipeline.veto_engine import VetoEngine
from core.analysis.engine import AnalysisEngine
from core.analysis.chop_detector import detect_chop
from core.strategy.base import TradeSignal
from core.strategy.trend_following import TrendFollowingStrategy
from core.strategy.mean_reversion import MeanReversionStrategy
from core.strategy.breakout import BreakoutStrategy
from core.strategy.signal_aggregator import SignalAggregator
from core.strategy.coin_screener import CoinScreener
from core.risk.risk_manager import RiskManager, RiskCheckResult
from core.brain import get_overrides as brain_get_overrides
from core.execution.execution_engine import execute_trade, is_trading_enabled
from core.execution.binance_client import BinanceFuturesClient
from core.execution.position_manager import sync_positions_from_exchange, run_position_check
from notifications.line_notify import send_line_message
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
        self.binance_client: BinanceFuturesClient | None = None
        self.last_kline_received_at: float = 0.0  # 供心跳檢查用
        self._startup_time: float = 0.0
        self._testnet_fallback_done: bool = False  # Testnet 保底開單僅觸發一次

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

        # 5b. 策略與信號聚合器 — 參數由大腦覆寫，運行中每 15 分鐘熱重載
        self.signal_aggregator = SignalAggregator(
            strategies=self._strategies_from_brain(),
            veto_engine=self.veto_engine,
            db=self.db,
        )
        self.coin_screener = CoinScreener()
        logger.info("策略與信號聚合器初始化完成（參數由大腦驅動）")

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

        # 7b. 模擬/實盤：初始化幣安客戶端並同步持倉（斷網/斷電恢復）
        if is_trading_enabled():
            try:
                self.binance_client = BinanceFuturesClient()
                await sync_positions_from_exchange(self.db, self.binance_client)
                logger.info("Testnet 持倉同步完成")
            except Exception as e:
                logger.warning(f"Testnet 持倉同步跳過: {e}")
                self.binance_client = None

        self.running = True
        self._startup_time = time.time()
        logger.info("TradingBrain 啟動完成！")
        logger.info(f"資料庫: {DB_PATH}")
        logger.info(f"監控幣種: {', '.join(DEFAULT_WATCHLIST)}")
        logger.info(f"交易模式: {TRADING_MODE}")

        # LINE 啟動通知
        mode_tag = "[DEMO]" if BINANCE_TESTNET else "[LIVE]"
        send_line_message(
            f"🚀 TradingBrain v3 {mode_tag} 已啟動\n"
            f"模式: {TRADING_MODE} | 幣種: {len(DEFAULT_WATCHLIST)}\n"
            f"策略: 趨勢追蹤 + 突破 + 均值回歸 (市場自適應)\n"
            f"風控: 3% 風險 / 5x 槓桿 / SL=1.5ATR / TP=4ATR"
        )

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

    def _strategies_from_brain(self) -> list:
        """依大腦覆寫參數組出策略實例，供啟動與定時熱重載使用"""
        o = brain_get_overrides()
        adx_min = float(o.get("adx_min", 15.0))
        skip_chop = bool(o.get("skip_on_chop", False))
        rsi_low = float(o.get("rsi_oversold", 35.0))
        rsi_high = float(o.get("rsi_overbought", 65.0))
        return [
            TrendFollowingStrategy(adx_min=adx_min, skip_on_chop=skip_chop),
            MeanReversionStrategy(rsi_oversold=rsi_low, rsi_overbought=rsi_high, skip_on_chop=skip_chop),
            BreakoutStrategy(skip_on_chop=skip_chop),
        ]

    def _rebuild_strategies_from_brain(self) -> None:
        """定時呼叫：用大腦當前參數替換聚合器內策略，無需重啟程式"""
        if self.signal_aggregator is None:
            return
        self.signal_aggregator.strategies = self._strategies_from_brain()
        logger.debug("策略已依大腦狀態熱重載")

    async def _preload_kline_cache(self) -> None:
        """啟動時用 REST 拉取 15m/1h/4h 歷史 K 線灌入 cache，否則 MTF 要等數天才有足夠根數。"""
        fetcher = MarketDataFetcher()
        min_bars = 50
        timeframes = ["15m", "1h", "4h"]
        try:
            for symbol in DEFAULT_WATCHLIST:
                for tf in timeframes:
                    try:
                        df = await fetcher.fetch_klines(symbol, tf, limit=100)
                        if df.empty or len(df) < min_bars:
                            logger.warning(f"預載 {symbol} {tf}: 僅 {len(df)} 根，跳過")
                            continue
                        key = symbol.lower()
                        for _, row in df.iterrows():
                            ot = row["open_time"]
                            ct = row["close_time"]
                            open_ms = int(ot.timestamp() * 1000) if hasattr(ot, "timestamp") else int(ot)
                            close_ms = int(ct.timestamp() * 1000) if hasattr(ct, "timestamp") else int(ct)
                            candle = {
                                "symbol": symbol,
                                "timeframe": tf,
                                "open_time": open_ms,
                                "open": float(row["open"]),
                                "high": float(row["high"]),
                                "low": float(row["low"]),
                                "close": float(row["close"]),
                                "volume": float(row["volume"]),
                                "close_time": close_ms,
                                "quote_volume": float(row.get("quote_volume", 0)),
                                "trades": int(row.get("trades", 0)),
                                "taker_buy_volume": float(row.get("taker_buy_volume", 0)),
                                "taker_buy_quote_volume": float(row.get("taker_buy_quote_volume", 0)),
                                "is_closed": True,
                            }
                            self.ws_feed.cache.update(key, tf, candle)
                        logger.info(f"預載 {symbol} {tf}: {len(df)} 根")
                    except Exception as e:
                        logger.warning(f"預載 {symbol} {tf} 失敗: {e}")
            await fetcher.close()
        except Exception as e:
            logger.warning(f"預載 K 線 cache 失敗: {e}")

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

        # 持倉/止損檢查 - 每 1 分鐘（paper 模式也需要，用來模擬平倉結算）
        if is_trading_enabled() or TRADING_MODE == "paper":
            self.scheduler.add_interval_task(
                "position_check", self._position_check,
                minutes=SCHEDULER_CONFIG["position_check"]["interval_min"],
                description="持倉止損止盈檢查",
            )
        # 心跳（靜默：僅異常時 LINE）
        self.scheduler.add_interval_task(
            "heartbeat", self._heartbeat,
            minutes=SCHEDULER_CONFIG["heartbeat"]["interval_min"],
            description="LINE 心跳(靜默)",
        )

        # 監控快報 - 每 60 分鐘發一則 LINE（今日損益/筆數/未平倉），讓你被動收到監控數據
        self.scheduler.add_interval_task(
            "monitor_report", self._monitor_report,
            minutes=SCHEDULER_CONFIG["monitor_report"]["interval_min"],
            description="監控快報(LINE)",
        )

        # 大腦熱重載 - 每 15 分鐘用 data/brain_state.json 覆寫策略參數，無需重啟
        self.scheduler.add_interval_task(
            "brain_reload", self._brain_reload,
            minutes=15, description="大腦狀態熱重載",
        )

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

        self.last_kline_received_at = time.time()

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
        # 只使用有訂閱的 15m/1h/4h（不要求 5m），每 TF 至少 50 根
        for tf in ["15m", "1h", "4h"]:
            cache_candles = self.ws_feed.cache.get(symbol.lower(), tf)
            if len(cache_candles) < 50:
                logger.debug(
                    f"MTF 跳過 {symbol}: {tf} 僅 {len(cache_candles)} 根 (需 50)"
                )
                continue
            df = pd.DataFrame(cache_candles)
            for col in ("open", "high", "low", "close", "volume"):
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            kline_data[tf] = df

        if len(kline_data) < 2:
            logger.debug(
                f"MTF 跳過 {symbol}: 僅 {len(kline_data)} 個 TF 達 50 根 (需至少 2)"
            )
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
            logger.info(
                f"信號被否決: {symbol} -> {len(agg_result.vetoed)} 筆 "
                f"(通過 {len(agg_result.passed)} 筆)"
            )

        # 風控評估：通過否決的信號進入風控（倉位/止損/熔斷/冷卻）
        primary = full.single_tf_results.get(full.primary_tf)
        if not primary or primary.df_enriched is None:
            primary = None
        # 模擬/實盤時使用交易所餘額，否則使用設定初始餘額
        balance = TRADING_INITIAL_BALANCE
        if self.binance_client:
            try:
                balance = await self.binance_client.get_balance()
            except Exception as e:
                logger.warning(f"取得交易所餘額失敗，使用初始餘額: {e}")
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
                    trade_id = await execute_trade(
                        sig, risk_result, float(entry_price), self.db, sig.strategy_name
                    )
                    if trade_id:
                        open_trades = self.db.get_open_trades()
                    else:
                        logger.info(
                            f"風控通過但未下單: {sig.symbol} {sig.signal_type} "
                            f"size={risk_result.size_usdt}U sl={risk_result.stop_loss}"
                        )
                else:
                    logger.info(f"風控攔截: {sig.symbol} {sig.signal_type} - {risk_result.reason}")

        # 保底開單（僅觸發一次）：避免長時間 0 倉，讓整條流程可被驗證/訓練
        if (
            (BINANCE_TESTNET or TRADING_MODE == "paper")
            and (is_trading_enabled() or TRADING_MODE == "paper")
            and not self._testnet_fallback_done
            and (time.time() - self._startup_time) >= (20 * 60 if TRADING_MODE == "paper" else 90 * 60)
            and len(self.db.get_open_trades()) == 0
        ):
            await self._try_testnet_fallback_order()

    async def _try_testnet_fallback_order(self) -> None:
        """Testnet 專用：一次小額 BTCUSDT LONG 以驗證下單流程（僅觸發一次）"""
        self._testnet_fallback_done = True
        symbol = "BTCUSDT"
        cache_candles = self.ws_feed.cache.get(symbol.lower(), "15m") if self.ws_feed else []
        if len(cache_candles) < 10:
            logger.warning("Testnet 保底開單跳過: BTCUSDT 15m 快取不足")
            return
        last_c = cache_candles[-1]
        entry_price = float(last_c.get("close", 0))
        if not entry_price or entry_price <= 0:
            logger.warning("Testnet 保底開單跳過: 無法取得價格")
            return
        # 小額 15U 名義、2x 槓桿，止損/止盈各約 0.5%
        size_usdt = 15.0
        sl = entry_price * 0.995
        tp = entry_price * 1.01
        sig = TradeSignal(
            symbol=symbol,
            timeframe="15m",
            signal_type="LONG",
            strength=0.5,
            strategy_name="testnet_fallback",
            reason="Testnet 保底開單驗證流程",
        )
        risk_result = RiskCheckResult(
            passed=True,
            size_usdt=size_usdt,
            leverage=2,
            stop_loss=sl,
            take_profit=tp,
        )
        logger.info(f"Testnet 保底開單: {symbol} LONG 約 {size_usdt}U @ {entry_price:.2f}")
        trade_id = await execute_trade(sig, risk_result, entry_price, self.db, "testnet_fallback")
        if trade_id:
            logger.info(f"Testnet 保底開單成功: trade_id={trade_id}")
        else:
            logger.warning("Testnet 保底開單未成功（可能交易所 API 限制）")

    async def _brain_reload(self) -> None:
        """排程：每 15 分鐘依大腦狀態重載策略參數"""
        self._rebuild_strategies_from_brain()

    async def _monitor_report(self) -> None:
        """每 N 分鐘發一則監控快報到 LINE"""
        trades_today = self.db.get_trades_today()
        daily_pnl = self.db.get_daily_pnl()
        open_trades = self.db.get_open_trades()
        mode_tag = "[DEMO]" if BINANCE_TESTNET else "[LIVE]"
        balance_str = ""
        if self.binance_client:
            try:
                bal = await self.binance_client.get_balance()
                balance_str = f"\n交易所餘額: {bal:.2f} U"
            except Exception:
                pass
        msg = (
            f"📊 {mode_tag} 監控快報\n"
            f"今日損益: {daily_pnl:+.2f} U | 筆數: {len(trades_today)} | 未平倉: {len(open_trades)}"
            f"{balance_str}\n"
            f"策略: v3 (趨勢+突破+MTF) | 日目標: 3-10%"
        )
        send_line_message(msg)
        logger.debug("監控快報已發送")

    async def _daily_report(self) -> None:
        """生成每日績效報告並透過 LINE 發送"""
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
        send_line_message(report)

    async def _heartbeat(self) -> None:
        """心跳檢查（靜默）：僅在異常時發送 LINE 告警"""
        # 超過 5 分鐘未收到 K 線視為異常
        stale = (time.time() - self.last_kline_received_at) > 300
        if stale and self.last_kline_received_at > 0:
            msg = (
                "⚠️ TradingBrain 心跳異常: 超過 5 分鐘未收到 K 線數據，"
                "請檢查 WebSocket 連線或網路。"
            )
            logger.warning(msg)
            send_line_message(msg)

    async def _position_check(self) -> None:
        """持倉止損/止盈檢查：從快取或 REST 取價，觸及則平倉"""
        # paper 模式允許 client=None（不打交易所，直接結算）
        if not self.binance_client and TRADING_MODE != "paper":
            return
        open_trades = self.db.get_open_trades()
        if not open_trades:
            return
        symbols = {t["symbol"] for t in open_trades}
        prices: dict[str, float] = {}
        for sym in symbols:
            # 優先從 WebSocket 快取取最新價
            latest = self.ws_feed.cache.get_latest(sym.lower(), "15m") if self.ws_feed else None
            if latest and "close" in latest:
                prices[sym] = float(latest["close"])
            else:
                if self.binance_client is not None:
                    try:
                        p = await self.binance_client.get_ticker_price(sym)
                        if p is not None:
                            prices[sym] = p
                    except Exception:
                        pass
        await run_position_check(
            self.db, self.binance_client, prices, risk_manager=self.risk_manager
        )

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

        # 預載歷史 K 線到 cache，否則 MTF 要等數天才有足夠 4h 根數
        await self._preload_kline_cache()

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
