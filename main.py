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
import zipfile
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

import pandas as pd
from loguru import logger

from config.settings import (
    BINANCE_TESTNET,
    TRADING_MODE, DB_PATH, KLINE_DATA_DIR,
    SCHEDULER_CONFIG, DEFAULT_WATCHLIST,
    API_PORT,
    LOG_DIR,
    TRADING_INITIAL_BALANCE,
    DEFAULT_LEVERAGE,
    runtime_config_errors,
    runtime_config_warnings,
    APP_TIMEZONE,
    APP_TIMEZONE_NAME,
)
from core.logger_setup import setup_logger, console, fmt_price
from core.data.websocket_feed import BinanceWebSocketFeed
from core.data.market_data import MarketDataFetcher
from core.pipeline.scheduler import TaskScheduler
from core.pipeline.funding_rate import FundingRateMonitor
from core.pipeline.fear_greed import FearGreedMonitor
from core.pipeline.liquidation import LiquidationMonitor
from core.pipeline.veto_engine import VetoEngine
from core.analysis.engine import AnalysisEngine
from core.analysis.chop_detector import detect_chop
from core.analysis.indicators import add_all_indicators, get_trend_direction
from core.strategy.base import MarketRegime, TradeSignal
from core.strategy.trend_following import TrendFollowingStrategy
from core.strategy.mean_reversion import MeanReversionStrategy
from core.strategy.breakout import BreakoutStrategy
from core.strategy.signal_aggregator import SignalAggregator
from core.strategy.coin_screener import CoinScreener
from core.risk.exit_profiles import normalize_strategy_family
from core.risk.position_sizer import get_strategy_risk_weight
from core.risk.exit_profiles import get_exit_profile
from core.risk.risk_manager import RiskManager
from core.brain import get_overrides as brain_get_overrides
from core.execution.execution_engine import execute_trade, is_trading_enabled
from core.execution.binance_client import BinanceFuturesClient
from core.execution.position_manager import sync_positions_from_exchange, run_position_check
from notifications.telegram_notify import send_telegram_message
from notifications.telegram_commands import TelegramCommandHandler
from database.db_manager import DatabaseManager


@dataclass
class PendingEntry:
    signal: TradeSignal
    market_snapshot_json: str | None
    setup_time: float
    expires_at: float
    trigger_high: float
    trigger_low: float
    trigger_close: float
    atr: float
    structure_df: pd.DataFrame | None
    state: str = "pending"
    breakout_price: float = 0.0
    breakout_bar_time: str = ""
    expire_bars: int = 15
    signal_strength: float = 0.0
    retest_zone_low: float = 0.0
    retest_zone_high: float = 0.0
    bars_waited: int = 0


@dataclass
class EntryTriggerCheck:
    triggered: bool
    reason: str


class TradingBrain:
    """交易系統主控制器"""

    BREAKOUT_RETEST_TOLERANCE_PCT = 0.005
    BREAKOUT_RETEST_EXPIRE_BARS = 5

    @staticmethod
    def _format_strategy_profile(name: str, alias: str) -> str:
        """Render a concise strategy risk/exit summary for notifications."""
        profile = get_exit_profile(name)
        risk_weight = get_strategy_risk_weight(name)
        strategy_descriptions = {
            "trend_following": "順勢回踩續行",
            "breakout_retest": "結構突破回踩",
            "mean_reversion": "區間邊界回歸",
        }
        regime_notes = {
            "trend_following": "偏好 TRENDING，RANGING 降權",
            "breakout_retest": "偏好 TRENDING，RANGING 降權",
            "mean_reversion": "偏好 RANGING，MTF gate 豁免",
        }
        if profile.tp2_final_exit:
            target_text = (
                f"SL {profile.stop_loss_atr_mult:.2f} ATR / "
                f"TP1 {profile.tp1_atr_mult:.2f} / TP2 {profile.tp2_atr_mult:.2f} ATR"
            )
        else:
            target_text = (
                f"SL {profile.stop_loss_atr_mult:.2f} ATR / "
                f"TP1 {profile.tp1_atr_mult:.2f} / "
                f"TP2 {profile.tp2_atr_mult:.2f} / "
                f"TP3 {profile.tp3_atr_mult:.2f} ATR"
            )
        description = strategy_descriptions.get(alias, alias)
        regime_note = regime_notes.get(alias, "依當前 regime 運行")
        return (
            f"- {alias}: {description} | {regime_note} | "
            f"risk x{risk_weight:.1f} | {target_text}"
        )

    def _build_runtime_notification_summary(self) -> dict[str, str]:
        """Return startup/heartbeat summary fields based on live runtime config."""
        from core.risk.position_sizer import STRATEGY_LEVERAGE_CAP

        params = self.db.get_risk_params() if self.db else {}
        active_preset = params.get("active_preset", "unknown")
        margin_low = int(float(params.get("fixed_margin_low", 200)))
        margin_high = int(float(params.get("fixed_margin_high", 600)))
        max_open_positions = params.get("max_open_positions", "auto")
        max_daily_loss_pct = float(params.get("max_daily_loss", 0.0)) * 100
        mode_text = "paper" if TRADING_MODE == "paper" else ("testnet" if BINANCE_TESTNET else "live")
        strategy_lines = [
            self._format_strategy_profile("trend_following", "trend_following"),
            self._format_strategy_profile("breakout_retest", "breakout_retest"),
            self._format_strategy_profile("mean_reversion", "mean_reversion"),
        ]
        trend_cap = STRATEGY_LEVERAGE_CAP.get("trend_following", 20)
        breakout_cap = STRATEGY_LEVERAGE_CAP.get("breakout", 25)
        mr_cap = STRATEGY_LEVERAGE_CAP.get("mean_reversion", 15)
        risk_lines = [
            f"- 預設方案: {active_preset}",
            f"- 固定保證金 {margin_low}-{margin_high}U / 最大同時持倉 {max_open_positions}",
            f"- 策略槓桿上限: 順勢 {trend_cap}x / 突破 {breakout_cap}x / 均值回歸 {mr_cap}x",
            f"- 單日虧損上限 {max_daily_loss_pct:.1f}% / C 級信號不開倉",
            "- 結構止損優先，soft stop + hard stop 雙層保護",
        ]
        preset_labels = {
            "conservative": "保守",
            "moderate": "穩健",
            "aggressive": "積極",
            "passive_income": "被動收入",
        }
        preset_cn = preset_labels.get(active_preset, active_preset)
        return {
            "mode_text": mode_text,
            "risk_text": (
                f"{preset_cn}模式 | 保證金 {margin_low}-{margin_high}U | "
                f"最多 {max_open_positions} 倉 | 槓桿上限 {trend_cap}/{breakout_cap}/{mr_cap}x"
            ),
            "strategy_text": "順勢 / 突破回踩 / 均值回歸",
            "strategy_lines": "\n".join(strategy_lines),
            "risk_lines": "\n".join(risk_lines),
        }

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
        self._pending_entries: dict[str, list[PendingEntry]] = {}
        self._mtf_batch: dict[str, str] = {}  # symbol -> console summary line
        self._mtf_flush_task: asyncio.Task | None = None
        self._observation_state: dict = {}  # trade_id -> consolidating start time

    @staticmethod
    def _mtf_gate_passed(full) -> bool:
        """Return whether the strict Phase 3 MTF gate would pass for the current setup."""
        if full.mtf is None:
            return False
        details = full.mtf.details or {}
        direction_4h = details.get("4h")
        direction_1h = details.get("1h")
        valid = {"BULLISH", "BEARISH"}
        return (
            direction_4h in valid
            and direction_1h in valid
            and direction_4h == direction_1h
            and full.mtf.recommended_direction is not None
        )

    @staticmethod
    def _with_signal_research_fields(
        base_snapshot: dict | str | None,
        sig: TradeSignal,
        *,
        breakout_retest_status: str | None = None,
    ) -> dict:
        """Merge per-signal research metadata into a market snapshot payload."""
        if isinstance(base_snapshot, str):
            try:
                snapshot = json.loads(base_snapshot)
            except json.JSONDecodeError:
                snapshot = {}
        else:
            snapshot = dict(base_snapshot or {})
        family = normalize_strategy_family(sig.strategy_name)
        snapshot["strategy_name"] = sig.strategy_name
        snapshot["signal_strength"] = sig.strength
        snapshot["strategy_risk_weight"] = get_strategy_risk_weight(sig.strategy_name)
        snapshot["entry_quality_filter_triggered"] = bool(
            sig.indicators.get("entry_quality_filter_triggered", False)
        ) if family == "trend_following" else False
        snapshot["breakout_retest_status"] = (
            breakout_retest_status
            if breakout_retest_status is not None
            else sig.indicators.get("breakout_retest_status")
        )
        return snapshot

    @staticmethod
    def _snapshot_from_json(snapshot_json: str | None, **updates) -> dict | None:
        """Load a snapshot JSON blob, merge updates, and return a dict payload."""
        if not snapshot_json:
            base: dict = {}
        else:
            try:
                base = json.loads(snapshot_json)
            except json.JSONDecodeError:
                base = {}
        base.update(updates)
        return base

    @staticmethod
    def _report_log_markers() -> dict[str, tuple[str, ...]]:
        """Return text markers that can be counted from trading logs."""
        return {
            "mtf_gate_blocked": ("MTF_GATE_BLOCK:",),
            "regime_gate_blocked": ("REGIME_GATE_BLOCK:", "跳過: 市場狀態"),
        }

    @staticmethod
    def _format_count_map(counts: dict[str, int]) -> str:
        """Render grouped counts as a compact comma-separated string."""
        if not counts:
            return "none"
        ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        return ", ".join(f"{name}×{total}" for name, total in ordered)

    def _read_trading_log_for_date(self, report_date: str) -> str:
        """Read a plain or archived trading log for one local report date."""
        plain_path = LOG_DIR / f"trading_{report_date}.log"
        if plain_path.exists():
            try:
                return plain_path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                return ""

        zip_path = LOG_DIR / f"trading_{report_date}.log.zip"
        if not zip_path.exists():
            return ""

        try:
            with zipfile.ZipFile(zip_path) as archive:
                member_names = [
                    name for name in archive.namelist()
                    if name.lower().endswith(".log")
                ]
                if not member_names:
                    return ""
                with archive.open(member_names[0]) as member:
                    return member.read().decode("utf-8", errors="ignore")
        except (OSError, zipfile.BadZipFile):
            return ""

    def _count_trading_log_markers(self, report_date: str) -> dict[str, int]:
        """Count explicit diagnostic markers from the archived daily trading log."""
        text = self._read_trading_log_for_date(report_date)
        if not text:
            return {key: 0 for key in self._report_log_markers()}

        counts: dict[str, int] = {}
        for key, patterns in self._report_log_markers().items():
            counts[key] = sum(text.count(pattern) for pattern in patterns)
        return counts

    def _build_signal_decay_summary(
        self,
        *,
        day_offset: int = -1,
        report_date: str | None = None,
    ) -> dict:
        """Build the daily signal funnel from analysis logs plus text log markers."""
        if self.db is None:
            return {
                "counts": {},
                "bottleneck": {"stage": "unavailable", "blocked": 0},
                "strategies": {"candidates": {}, "executed": {}},
                "sides": {"candidates": {}, "executed": {}},
            }

        report_date = report_date or (
            datetime.now(APP_TIMEZONE).date() + pd.Timedelta(days=day_offset)
        ).isoformat()
        action_counts = self.db.get_analysis_action_counts(
            tz=APP_TIMEZONE,
            day_offset=day_offset,
        )
        strategy_candidates = self.db.get_analysis_strategy_counts(
            tz=APP_TIMEZONE,
            day_offset=day_offset,
            final_actions=("PENDING_RISK", "VETOED"),
        )
        strategy_executed = self.db.get_analysis_strategy_counts(
            tz=APP_TIMEZONE,
            day_offset=day_offset,
            final_actions=("EXECUTED",),
        )
        side_candidates = self.db.get_analysis_signal_type_counts(
            tz=APP_TIMEZONE,
            day_offset=day_offset,
            final_actions=("PENDING_RISK", "VETOED"),
        )
        side_executed = self.db.get_analysis_signal_type_counts(
            tz=APP_TIMEZONE,
            day_offset=day_offset,
            final_actions=("EXECUTED",),
        )
        log_counts = self._count_trading_log_markers(report_date)

        regime_gate_blocked = int(log_counts.get("regime_gate_blocked", 0))
        mtf_gate_blocked = int(log_counts.get("mtf_gate_blocked", 0))
        vetoed = int(action_counts.get("VETOED", 0))
        pending_risk = int(action_counts.get("PENDING_RISK", 0))
        candidates_total = regime_gate_blocked + mtf_gate_blocked + pending_risk + vetoed
        regime_gate_passed = max(candidates_total - regime_gate_blocked, 0)
        mtf_gate_passed = max(regime_gate_passed - mtf_gate_blocked, 0)

        pending_created = int(action_counts.get("PENDING_TRIGGER", 0)) + int(
            action_counts.get("BREAKOUT_PENDING", 0)
        )
        trigger_confirmed = int(action_counts.get("TRIGGER_CONFIRMED", 0)) + int(
            action_counts.get("BREAKOUT_CONFIRMED", 0)
        )
        trigger_expired = int(action_counts.get("TRIGGER_EXPIRED", 0)) + int(
            action_counts.get("BREAKOUT_EXPIRED", 0)
        ) + int(action_counts.get("BREAKOUT_EXPIRED_TIMEOUT", 0))

        counts = {
            "candidate_signals": candidates_total,
            "regime_gate_passed": regime_gate_passed,
            "regime_gate_blocked": regime_gate_blocked,
            "mtf_gate_passed": mtf_gate_passed,
            "mtf_gate_blocked": mtf_gate_blocked,
            "veto_passed": pending_risk,
            "veto_blocked": vetoed,
            "pending_created": pending_created,
            "trigger_confirmed": trigger_confirmed,
            "trigger_expired": trigger_expired,
            "breakout_retest_hit": int(action_counts.get("BREAKOUT_RETEST_HIT", 0)),
            "breakout_confirmed": int(action_counts.get("BREAKOUT_CONFIRMED", 0)),
            "breakout_expired": int(action_counts.get("BREAKOUT_EXPIRED", 0))
            + int(action_counts.get("BREAKOUT_EXPIRED_TIMEOUT", 0)),
            "mtf_recheck_blocked": int(action_counts.get("MTF_RECHECK_BLOCK", 0)),
            "risk_blocked": int(action_counts.get("RISK_BLOCKED", 0)),
            "executed": int(action_counts.get("EXECUTED", 0)),
            "exchange_rejected": int(action_counts.get("EXCHANGE_REJECTED", 0)),
            "no_signal": int(action_counts.get("NO_SIGNAL", 0)),
        }

        bottleneck_candidates = {
            "regime_gate": counts["regime_gate_blocked"],
            "mtf_gate": counts["mtf_gate_blocked"],
            "veto": counts["veto_blocked"],
            "trigger_expired": counts["trigger_expired"],
            "mtf_recheck": counts["mtf_recheck_blocked"],
            "risk": counts["risk_blocked"],
            "exchange": counts["exchange_rejected"],
        }
        bottleneck_stage, bottleneck_total = max(
            bottleneck_candidates.items(),
            key=lambda item: item[1],
            default=("none", 0),
        )

        return {
            "counts": counts,
            "bottleneck": {
                "stage": bottleneck_stage,
                "blocked": bottleneck_total,
            },
            "strategies": {
                "candidates": strategy_candidates,
                "executed": strategy_executed,
            },
            "sides": {
                "candidates": side_candidates,
                "executed": side_executed,
            },
        }

    def _append_daily_report_log(self, report_payload: dict) -> None:
        """Persist daily summary snapshots for later strategy review."""
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        daily_dir = LOG_DIR / "daily_reports"
        daily_dir.mkdir(parents=True, exist_ok=True)

        report_date = report_payload["report_date"]
        signal_chain = report_payload.get("signal_chain", {})
        signal_counts = signal_chain.get("counts", {})
        bottleneck = signal_chain.get("bottleneck", {})
        text_lines = [
            "TradingBrain Daily Report",
            f"report_date: {report_payload['report_date']}",
            f"timezone: {report_payload['timezone']}",
            f"mode: {report_payload['mode']}",
            f"trades_count: {report_payload['trades_count']}",
            f"daily_pnl: {report_payload['daily_pnl']:+.2f}",
            f"open_positions: {report_payload['open_positions']}",
            f"exchange_balance: {report_payload['exchange_balance']}",
            f"generated_at: {report_payload['generated_at']}",
            "",
            "Signal Chain Summary",
            f"candidate_signals: {signal_counts.get('candidate_signals', 0)}",
            f"regime_gate_passed: {signal_counts.get('regime_gate_passed', 0)}",
            f"regime_gate_blocked: {signal_counts.get('regime_gate_blocked', 0)}",
            f"mtf_gate_passed: {signal_counts.get('mtf_gate_passed', 0)}",
            f"mtf_gate_blocked: {signal_counts.get('mtf_gate_blocked', 0)}",
            f"veto_passed: {signal_counts.get('veto_passed', 0)}",
            f"veto_blocked: {signal_counts.get('veto_blocked', 0)}",
            f"pending_created: {signal_counts.get('pending_created', 0)}",
            f"trigger_confirmed: {signal_counts.get('trigger_confirmed', 0)}",
            f"trigger_expired: {signal_counts.get('trigger_expired', 0)}",
            f"mtf_recheck_blocked: {signal_counts.get('mtf_recheck_blocked', 0)}",
            f"risk_blocked: {signal_counts.get('risk_blocked', 0)}",
            f"executed: {signal_counts.get('executed', 0)}",
            f"breakout_retest_hit: {signal_counts.get('breakout_retest_hit', 0)}",
            f"breakout_confirmed: {signal_counts.get('breakout_confirmed', 0)}",
            f"breakout_expired: {signal_counts.get('breakout_expired', 0)}",
            f"bottleneck_stage: {bottleneck.get('stage', 'none')}",
            f"bottleneck_blocked: {bottleneck.get('blocked', 0)}",
            f"candidate_strategies: {self._format_count_map(signal_chain.get('strategies', {}).get('candidates', {}))}",
            f"executed_strategies: {self._format_count_map(signal_chain.get('strategies', {}).get('executed', {}))}",
            f"candidate_sides: {self._format_count_map(signal_chain.get('sides', {}).get('candidates', {}))}",
            f"executed_sides: {self._format_count_map(signal_chain.get('sides', {}).get('executed', {}))}",
        ]

        daily_file = daily_dir / f"{report_date}.md"
        daily_file.write_text("\n".join(text_lines) + "\n", encoding="utf-8")

        history_file = daily_dir / "history.jsonl"
        with history_file.open("a", encoding="utf-8") as file:
            file.write(json.dumps(report_payload, ensure_ascii=False) + "\n")

    async def startup(self) -> None:
        """系統啟動序列"""
        setup_logger()

        config_errors = runtime_config_errors()
        if config_errors:
            for err in config_errors:
                logger.error(f"Configuration error: {err}")
            raise RuntimeError("Invalid runtime configuration. Fix .env before starting TradingBrain.")

        for warning in runtime_config_warnings():
            logger.warning(f"Configuration warning: {warning}")

        
        # 0. 啟動 Web API（儀表板後端，背景執行）- 優先啟動以便 UI 能連線
        from config.settings import API_PORT
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
        logger.info(f"儀表板 API 已啟動於: http://0.0.0.0:{API_PORT}")

        # ── 注入共用 DB 給 API 層（避免雙實例衝突）──
        # 1. 初始化資料庫（提前到 API 注入前）
        self.db = DatabaseManager()
        logger.info("資料庫初始化完成 (SQLite-WAL)")
        from api.deps import set_db
        set_db(self.db)

        console("=" * 50)
        console("🧠 TradingBrain V10 啟動中...")
        console(f"⚙ 交易模式: {TRADING_MODE}")
        console("=" * 50)

        # 確保必要目錄存在
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        KLINE_DATA_DIR.mkdir(parents=True, exist_ok=True)
        (LOG_DIR / "daily_reports").mkdir(parents=True, exist_ok=True)

        # 1. 資料庫已在上方初始化（API 注入後）

        # 2. 載入風控預設參數
        self._load_risk_defaults()
        console("✅ 風控參數載入完成")

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
        console("✅ 否決引擎初始化完成")

        # 5. 初始化技術分析引擎
        self.analysis_engine = AnalysisEngine()
        console("✅ 技術分析引擎初始化完成")

        # 5b. 策略與信號聚合器 — 參數由大腦覆寫，運行中每 15 分鐘熱重載
        self.signal_aggregator = SignalAggregator(
            strategies=self._strategies_from_brain(),
            veto_engine=self.veto_engine,
            db=self.db,
        )
        self.coin_screener = CoinScreener()
        console("✅ 策略與信號聚合器初始化完成")

        # 5c. 初始化風控核心
        self.risk_manager = RiskManager(self.db)
        console("✅ 風控核心初始化完成")

        # 6. 初始化 WebSocket 數據流
        self.ws_feed = BinanceWebSocketFeed(
            symbols=DEFAULT_WATCHLIST,
            timeframes=["1m", "5m", "15m", "1h", "4h"],
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
                console("✅ Testnet 持倉同步完成")
            except Exception as e:
                logger.warning(f"Testnet 持倉同步跳過: {e}")
                self.binance_client = None

        self.running = True
        console("🟢 TradingBrain 啟動完成！")
        console(f"📂 資料庫: {DB_PATH}")
        console(f"📊 監控: {', '.join(DEFAULT_WATCHLIST)}")
        logger.info(f"交易模式: {TRADING_MODE}")

        summary = self._build_runtime_notification_summary()

        # Telegram 啟動通知
        mode_tag = "[DEMO]" if BINANCE_TESTNET else "[LIVE]"
        send_telegram_message(
            f"🧠 TradingBrain V10 啟動 {mode_tag}\n"
            f"📊 {len(DEFAULT_WATCHLIST)} 幣種 | 📋 {summary['strategy_text']}\n"
            f"🛡 {summary['risk_text']}"
        )



        console(f"🌐 儀表板: http://0.0.0.0:{API_PORT}")
        console("=" * 50)

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
            label = preset_params.get("label", active_preset)
            params_to_load = {k: v for k, v in preset_params.items() if k != "label"}
            self.db.load_risk_defaults(params_to_load)
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
        timeframes = ["5m", "15m", "1h", "4h"]
        try:
            for symbol in DEFAULT_WATCHLIST:
                for tf in timeframes:
                    try:
                        df = await fetcher.fetch_klines(symbol, tf, limit=500)
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
                        logger.debug(f"預載 {symbol} {tf}: {len(df)} 根")
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
                seconds=SCHEDULER_CONFIG["position_check"]["interval_sec"],
                description="持倉止損止盈檢查",
            )
        # 心跳 — 每 1 分鐘 console 狀態行
        self.scheduler.add_interval_task(
            "heartbeat", self._heartbeat,
            minutes=1,
            description="Console 心跳",
        )

        # 監控快報 - 每 60 分鐘發一則 Telegram（今日損益/筆數/未平倉），讓你被動收到監控數據
        self.scheduler.add_interval_task(
            "monitor_report", self._monitor_report,
            minutes=SCHEDULER_CONFIG["monitor_report"]["interval_min"],
            description="監控快報(Telegram)",
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
        symbol = candle.get("symbol") if candle else None
        tf = candle.get("timeframe") if candle else None
        close = candle.get("close") if candle else None

        if not symbol or not tf or close is None:
            logger.warning(f"_on_kline_closed: invalid candle data: {candle}")
            return

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

        if tf == "1m":
            await self._process_pending_entries(symbol)

        # 在 15m 收盤時做完整 MTF 分析（主進場時間框架）
        if tf == "15m":
            await self._run_mtf_analysis(symbol)
            # 延遲 flush — 等所有幣種的 15m 分析完成後批次輸出
            if self._mtf_flush_task and not self._mtf_flush_task.done():
                self._mtf_flush_task.cancel()
            self._mtf_flush_task = asyncio.create_task(self._flush_mtf_batch())

    async def _flush_mtf_batch(self) -> None:
        """等所有 15m 分析完成後，批次輸出乾淨的 console 摘要"""
        await asyncio.sleep(3)  # 等待所有幣種分析完成
        batch = dict(self._mtf_batch)
        self._mtf_batch.clear()
        if not batch:
            return

        # 分類：有事的 vs 無信號
        interesting = {s: v for s, v in batch.items() if v != "無信號"}
        silent_count = len(batch) - len(interesting)

        console(f"📊 15m 分析完成 ({len(batch)} 幣種)")
        for sym, summary in interesting.items():
            short = sym.replace("USDT", "")
            console(f"   {short:>6} | {summary}")
        if silent_count > 0:
            console(f"   其餘 {silent_count} 幣種：無信號")

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
        primary = full.single_tf_results.get(full.primary_tf)
        regime_assessment = (
            MarketRegime.assess(primary, full=full) if primary else None
        )

        regime_label = regime_assessment.regime if regime_assessment else "N/A"
        mtf_direction = snapshot.get("mtf", {}).get("direction", "N/A")
        logger.info(
            f"MTF分析 {symbol}: "
            f"趨勢={snapshot.get('mtf', {}).get('alignment', 'N/A')}, "
            f"方向={mtf_direction}, "
            f"信心={snapshot.get('mtf', {}).get('confidence', 0):.0%}, "
            f"regime={regime_label}"
        )

        # ── 市場快照（開單當下的指標數值，供覆盤分析）──
        market_snap = {}
        if primary and primary.df_enriched is not None:
            df_e = primary.df_enriched
            last_row = df_e.iloc[-1] if len(df_e) > 0 else None
            if last_row is not None:
                close_val = float(last_row.get("close", 0))
                atr_val = float(last_row.get("atr", 0)) if "atr" in df_e.columns else 0.0
                market_snap = {
                    "close": close_val,
                    "rsi": round(float(last_row.get("rsi", 0)), 2) if "rsi" in df_e.columns else None,
                    "adx": round(float(last_row.get("adx", 0)), 2) if "adx" in df_e.columns else None,
                    "macd": round(float(last_row.get("macd", 0)), 4) if "macd" in df_e.columns else None,
                    "macd_signal": round(float(last_row.get("macd_signal", 0)), 4) if "macd_signal" in df_e.columns else None,
                    "bb_upper": round(float(last_row.get("bb_upper", 0)), 2) if "bb_upper" in df_e.columns else None,
                    "bb_lower": round(float(last_row.get("bb_lower", 0)), 2) if "bb_lower" in df_e.columns else None,
                    "atr": round(atr_val, 4) if "atr" in df_e.columns else None,
                    "atr_ratio": round(atr_val / close_val, 6) if close_val > 0 and atr_val > 0 else None,
                    "bb_width": round(float(last_row.get("bb_width", 0)), 4) if "bb_width" in df_e.columns else None,
                    "adx_pos": round(float(last_row.get("adx_pos", 0)), 2) if "adx_pos" in df_e.columns else None,
                    "adx_neg": round(float(last_row.get("adx_neg", 0)), 2) if "adx_neg" in df_e.columns else None,
                    "ema_21": round(float(last_row.get("ema_21", 0)), 2) if "ema_21" in df_e.columns else None,
                    "ema_50": round(float(last_row.get("ema_50", 0)), 2) if "ema_50" in df_e.columns else None,
                    "volume": float(last_row.get("volume", 0)),
                    "mtf_direction": snapshot.get("mtf", {}).get("direction"),
                    "mtf_4h_direction": full.mtf.details.get("4h") if full.mtf else None,
                    "mtf_1h_direction": full.mtf.details.get("1h") if full.mtf else None,
                    "mtf_gate_passed": self._mtf_gate_passed(full),
                    "mtf_alignment": snapshot.get("mtf", {}).get("alignment"),
                    "mtf_confidence": snapshot.get("mtf", {}).get("confidence"),
                }
        if regime_assessment is not None:
            market_snap["regime"] = regime_assessment.regime
            market_snap["market_regime"] = regime_assessment.regime
            market_snap["regime_scores"] = {
                "trend": round(regime_assessment.trend_score, 2),
                "range": round(regime_assessment.range_score, 2),
                "volatile": round(regime_assessment.volatility_score, 2),
            }
            market_snap["regime_metrics"] = regime_assessment.metrics
            market_snap["regime_reasons"] = regime_assessment.reasons

        if regime_assessment is not None:
            self.db.insert_analysis_log({
                "symbol": symbol,
                "timeframe": full.primary_tf,
                "strategy_name": "regime_monitor",
                "signal_generated": 0,
                "signal_type": None,
                "signal_strength": None,
                "veto_passed": None,
                "veto_reasons": None,
                "veto_details": None,
                "final_action": "REGIME_OBSERVATION",
                "market_snapshot": market_snap,
            })

        # 策略評估 + 否決過濾，通過信號寫入 DB
        agg_result = self.signal_aggregator.evaluate(full, save_to_db=True)

        # ── 決策日誌：記錄完整決策鏈 ──
        if agg_result.passed or agg_result.vetoed:
            # 記錄所有通過的信號
            for sig in agg_result.passed:
                self.db.insert_analysis_log({
                    "symbol": sig.symbol,
                    "timeframe": full.primary_tf,
                    "strategy_name": sig.strategy_name,
                    "signal_generated": 1,
                    "signal_type": sig.signal_type,
                    "signal_strength": sig.strength,
                    "veto_passed": 1,
                    "veto_reasons": None,
                    "veto_details": None,
                    "final_action": "PENDING_RISK",
                    "market_snapshot": self._with_signal_research_fields(
                        market_snap,
                        sig,
                        breakout_retest_status=(
                            "pending" if normalize_strategy_family(sig.strategy_name) == "breakout" else None
                        ),
                    ),
                })
            # 記錄所有被否決的信號
            for sig, reason in agg_result.vetoed:
                self.db.insert_analysis_log({
                    "symbol": sig.symbol,
                    "timeframe": full.primary_tf,
                    "strategy_name": sig.strategy_name,
                    "signal_generated": 1,
                    "signal_type": sig.signal_type,
                    "signal_strength": sig.strength,
                    "veto_passed": 0,
                    "veto_reasons": reason,
                    "veto_details": None,
                    "final_action": "VETOED",
                    "market_snapshot": self._with_signal_research_fields(
                        market_snap,
                        sig,
                        breakout_retest_status=(
                            "pending" if normalize_strategy_family(sig.strategy_name) == "breakout" else None
                        ),
                    ),
                })
        else:
            # 沒有任何信號產生 — 記錄「為什麼不開單」
            self.db.insert_analysis_log({
                "symbol": symbol,
                "timeframe": full.primary_tf,
                "strategy_name": None,
                "signal_generated": 0,
                "signal_type": None,
                "signal_strength": None,
                "veto_passed": None,
                "veto_reasons": None,
                "veto_details": None,
                "final_action": "NO_SIGNAL",
                "market_snapshot": market_snap,
            })

        if agg_result.passed:
            logger.info(f"信號通過否決: {symbol} -> {len(agg_result.passed)} 筆")
        if agg_result.vetoed:
            logger.info(
                f"信號被否決: {symbol} -> {len(agg_result.vetoed)} 筆 "
                f"(通過 {len(agg_result.passed)} 筆)"
            )

        # ── 收集 console 批次摘要 ──
        open_trades = self.db.get_open_trades() if self.db else []
        if any(t["symbol"] == symbol for t in open_trades):
            self._mtf_batch[symbol] = "--持倉中-- 跳過分析"
        elif agg_result.passed:
            sigs = [f"{s.signal_type} ({s.strategy_name})" for s in agg_result.passed]
            regime_arrow = {"BULLISH": "↗", "BEARISH": "↘"}.get(mtf_direction, "─")
            self._mtf_batch[symbol] = f"{regime_label} {regime_arrow} | ⚡ {', '.join(sigs)}"
        elif agg_result.vetoed:
            reasons = [r for _, r in agg_result.vetoed]
            regime_arrow = {"BULLISH": "↗", "BEARISH": "↘"}.get(mtf_direction, "─")
            self._mtf_batch[symbol] = f"{regime_label} {regime_arrow} | ❌ {'; '.join(reasons)}"
        else:
            self._mtf_batch[symbol] = "無信號"

        if primary and primary.df_enriched is not None:
            await self._queue_pending_entries(
                agg_result.passed,
                primary,
                market_snap,
            )

    async def _brain_reload(self) -> None:
        """排程：每 15 分鐘依大腦狀態重載策略參數"""
        self._rebuild_strategies_from_brain()

    async def _queue_pending_entries(
        self,
        signals: list[TradeSignal],
        primary,
        market_snapshot: dict | None,
    ) -> None:
        if not signals or primary.df_enriched is None:
            return

        current_time = time.time()
        latest = primary.df_enriched.iloc[-1]
        atr_val = primary.indicators.get("atr")
        if atr_val is None and "atr" in primary.df_enriched.columns:
            atr_val = primary.df_enriched["atr"].iloc[-1]
        atr = float(atr_val) if atr_val is not None else 0.0
        if atr <= 0:
            return

        pending_for_symbol = self._pending_entries.setdefault(primary.symbol, [])
        pending_for_symbol[:] = [entry for entry in pending_for_symbol if entry.expires_at > current_time]

        for sig in signals:
            sig.indicators["_structure_df"] = primary.df_enriched.tail(200).copy()
            breakout_price = 0.0
            zone_low = 0.0
            zone_high = 0.0
            expire_bars = 15
            breakout_bar_time = ""
            final_action = "PENDING_TRIGGER"
            if sig.strategy_name == "breakout":
                breakout_price = float(
                    sig.indicators.get(
                        "breakout_price",
                        latest.get("close", 0),
                    )
                )
                tolerance = breakout_price * self.BREAKOUT_RETEST_TOLERANCE_PCT
                zone_low = float(sig.indicators.get("retest_zone_low", breakout_price - tolerance))
                zone_high = float(sig.indicators.get("retest_zone_high", breakout_price + tolerance))
                expire_bars = self.BREAKOUT_RETEST_EXPIRE_BARS
                breakout_bar_time_raw = latest.get("open_time") or latest.get("close_time")
                if isinstance(breakout_bar_time_raw, pd.Timestamp):
                    breakout_bar_time = breakout_bar_time_raw.isoformat()
                elif breakout_bar_time_raw is not None:
                    breakout_bar_time = str(breakout_bar_time_raw)
                final_action = "BREAKOUT_PENDING"
            pending = PendingEntry(
                signal=sig,
                market_snapshot_json=json.dumps(
                    self._with_signal_research_fields(
                        market_snapshot or {},
                        sig,
                        breakout_retest_status=(
                            "pending" if normalize_strategy_family(sig.strategy_name) == "breakout" else None
                        ),
                    ),
                    ensure_ascii=False,
                ) if market_snapshot is not None else None,
                setup_time=current_time,
                expires_at=current_time + 45 * 60,
                trigger_high=float(latest.get("high", latest.get("close", 0))),
                trigger_low=float(latest.get("low", latest.get("close", 0))),
                trigger_close=float(latest.get("close", 0)),
                atr=atr,
                structure_df=primary.df_enriched.tail(200).copy(),
                breakout_price=breakout_price,
                breakout_bar_time=breakout_bar_time,
                expire_bars=expire_bars,
                signal_strength=sig.strength,
                retest_zone_low=zone_low,
                retest_zone_high=zone_high,
            )
            pending_for_symbol.append(pending)
            self.db.insert_analysis_log({
                "symbol": sig.symbol,
                "timeframe": "1m_trigger",
                "strategy_name": sig.strategy_name,
                "signal_generated": 1,
                "signal_type": sig.signal_type,
                "signal_strength": sig.strength,
                "veto_passed": 1,
                "final_action": final_action,
                "market_snapshot": self._with_signal_research_fields(
                    market_snapshot or {},
                    sig,
                    breakout_retest_status=(
                        "pending" if normalize_strategy_family(sig.strategy_name) == "breakout" else None
                    ),
                ),
            })
            if sig.strategy_name == "breakout":
                console(
                    f"⚡ {sig.symbol} {sig.signal_type} 候選 (breakout, 等待1m retest, {expire_bars}根內有效)"
                )
            else:
                console(
                    f"⚡ {sig.symbol} {sig.signal_type} 候選 ({sig.strategy_name}, 等待1m觸發)"
                )
            logger.info(f"候選訊號已建立: {sig.symbol} {sig.signal_type} {sig.strategy_name}")

    def _build_breakout_retest_signal(self, pending: PendingEntry) -> TradeSignal:
        indicators = dict(pending.signal.indicators)
        indicators.update({
            "breakout_price": round(pending.breakout_price, 6),
            "retest_zone_low": round(pending.retest_zone_low, 6),
            "retest_zone_high": round(pending.retest_zone_high, 6),
            "retest_confirmed": True,
            "breakout_retest_status": "confirmed",
            "strategy_family": "breakout",
        })
        return replace(
            pending.signal,
            strategy_name="breakout_retest",
            indicators=indicators,
            reason=(
                f"{pending.signal.reason} | retest confirmed at "
                f"{pending.breakout_price:.4f}"
            ),
        )

    @staticmethod
    def _signal_grade(signal_strength: float) -> str:
        if signal_strength >= 0.7:
            return "A"
        if signal_strength >= 0.5:
            return "B"
        return "C"

    @staticmethod
    def _pending_signal_strength(pending: PendingEntry) -> float:
        if pending.signal_strength > 0:
            return pending.signal_strength
        return pending.signal.strength

    @staticmethod
    def _required_support_passes(
        signal_strength: float,
        total_checks: int,
        default_passes: int,
    ) -> int:
        grade = TradingBrain._signal_grade(signal_strength)
        if grade == "A":
            return max(1, default_passes - 1)
        if grade == "B":
            return default_passes
        return total_checks

    @staticmethod
    def _normalize_quick_mtf_direction(raw_direction: str | None) -> str | None:
        if raw_direction in {"BULLISH", "LEAN_BULLISH"}:
            return "LONG"
        if raw_direction in {"BEARISH", "LEAN_BEARISH"}:
            return "SHORT"
        return None

    def _quick_mtf_direction_check(self, symbol: str) -> str | None:
        if self.ws_feed is None:
            return None

        directions: dict[str, str | None] = {}
        for timeframe in ("4h", "1h"):
            candles = self.ws_feed.cache.get(symbol.lower(), timeframe)
            if len(candles) < 50:
                directions[timeframe] = None
                continue

            df = pd.DataFrame(candles)
            for col in ("open", "high", "low", "close", "volume"):
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            df = df.dropna(subset=["open", "high", "low", "close", "volume"])
            if len(df) < 50:
                directions[timeframe] = None
                continue

            enriched = add_all_indicators(df)
            directions[timeframe] = self._normalize_quick_mtf_direction(
                get_trend_direction(enriched)
            )

        dir_4h = directions.get("4h")
        dir_1h = directions.get("1h")
        if dir_4h and dir_1h:
            if dir_4h != dir_1h:
                return "CONFLICTING"
            return dir_4h
        return dir_4h or dir_1h or "NEUTRAL"

    def _process_breakout_retest_entry(
        self,
        pending: PendingEntry,
        one_min_result,
    ) -> tuple[PendingEntry | None, EntryTriggerCheck, TradeSignal | None]:
        if one_min_result.df_enriched is None or one_min_result.df_enriched.empty:
            return pending, EntryTriggerCheck(False, "1m data unavailable"), None

        curr = one_min_result.df_enriched.iloc[-1]
        close = float(curr.get("close", 0))
        open_price = float(curr.get("open", close))
        high = float(curr.get("high", close))
        low = float(curr.get("low", close))
        ema9 = curr.get("ema_9")

        in_retest_zone = (
            high >= pending.retest_zone_low and low <= pending.retest_zone_high
        )

        next_bars_waited = pending.bars_waited + 1

        if pending.state == "pending" and in_retest_zone:
            pending.state = "retest_zone"
            self.db.insert_analysis_log({
                "symbol": pending.signal.symbol,
                "timeframe": "1m_trigger",
                "strategy_name": pending.signal.strategy_name,
                "signal_generated": 1,
                "signal_type": pending.signal.signal_type,
                "signal_strength": pending.signal.strength,
                "veto_passed": 1,
                "final_action": "BREAKOUT_RETEST_HIT",
                "market_snapshot": self._snapshot_from_json(
                    pending.market_snapshot_json,
                    breakout_retest_status="pending",
                ),
            })
            console(
                f"⚡ {pending.signal.symbol} {pending.signal.signal_type} "
                f"retest zone 觸及 [{fmt_price(pending.retest_zone_low)}, {fmt_price(pending.retest_zone_high)}]"
            )
            logger.info(
                f"BREAKOUT_RETEST_HIT: {pending.signal.symbol} "
                f"{pending.signal.signal_type} zone="
                f"[{pending.retest_zone_low:.4f}, {pending.retest_zone_high:.4f}]"
            )

        if pending.state == "retest_zone":
            signal_grade = self._signal_grade(self._pending_signal_strength(pending))
            if pending.signal.signal_type == "LONG":
                checks = {
                    "green_candle": close > open_price,
                    "above_ema9": ema9 is not None and close > float(ema9),
                }
                if signal_grade == "C":
                    checks["close_above_breakout"] = close > pending.breakout_price
            else:
                checks = {
                    "red_candle": close < open_price,
                    "below_ema9": ema9 is not None and close < float(ema9),
                }
                if signal_grade == "C":
                    checks["close_below_breakout"] = close < pending.breakout_price
            failed = [name for name, ok in checks.items() if not ok]
            if not failed:
                confirmed_signal = self._build_breakout_retest_signal(pending)
                self.db.insert_analysis_log({
                    "symbol": confirmed_signal.symbol,
                    "timeframe": "1m_trigger",
                    "strategy_name": confirmed_signal.strategy_name,
                    "signal_generated": 1,
                    "signal_type": confirmed_signal.signal_type,
                    "signal_strength": confirmed_signal.strength,
                    "veto_passed": 1,
                    "final_action": "BREAKOUT_CONFIRMED",
                    "market_snapshot": self._snapshot_from_json(
                        pending.market_snapshot_json,
                        breakout_retest_status="confirmed",
                    ),
                })
                return None, EntryTriggerCheck(True, "triggered"), confirmed_signal

        pending.bars_waited = next_bars_waited
        if pending.bars_waited >= pending.expire_bars:
            self.db.insert_analysis_log({
                "symbol": pending.signal.symbol,
                "timeframe": "1m_trigger",
                "strategy_name": pending.signal.strategy_name,
                "signal_generated": 1,
                "signal_type": pending.signal.signal_type,
                "signal_strength": pending.signal.strength,
                "veto_passed": 1,
                "final_action": "BREAKOUT_EXPIRED",
                "market_snapshot": self._snapshot_from_json(
                    pending.market_snapshot_json,
                    breakout_retest_status="expired",
                ),
            })
            console(
                f"⏰ {pending.signal.symbol} {pending.signal.signal_type} "
                f"breakout 過期 ({pending.bars_waited} bars)"
            )
            logger.info(
                f"BREAKOUT_EXPIRED: {pending.signal.symbol} "
                f"{pending.signal.signal_type} after {pending.bars_waited} bars"
            )
            return None, EntryTriggerCheck(False, "breakout_retest_expired"), None

        return pending, EntryTriggerCheck(False, "breakout_retest_waiting"), None

    async def _process_pending_entries(self, symbol: str) -> None:
        pending_list = self._pending_entries.get(symbol)
        if not pending_list or self.analysis_engine is None or self.ws_feed is None:
            return

        now = time.time()
        expired_entries = [entry for entry in pending_list if entry.expires_at <= now]
        for expired in expired_entries:
            final_action = (
                "BREAKOUT_EXPIRED_TIMEOUT"
                if expired.signal.strategy_name == "breakout"
                else "TRIGGER_EXPIRED"
            )
            snapshot_updates = {
                "pending_expired_reason": "timeout",
            }
            if normalize_strategy_family(expired.signal.strategy_name) == "breakout":
                snapshot_updates["breakout_retest_status"] = "expired"
            self.db.insert_analysis_log({
                "symbol": expired.signal.symbol,
                "timeframe": "1m_trigger",
                "strategy_name": expired.signal.strategy_name,
                "signal_generated": 1,
                "signal_type": expired.signal.signal_type,
                "signal_strength": expired.signal.strength,
                "veto_passed": 1,
                "final_action": final_action,
                "market_snapshot": self._snapshot_from_json(
                    expired.market_snapshot_json,
                    **snapshot_updates,
                ),
            })
        active_entries = [entry for entry in pending_list if entry.expires_at > now]
        if not active_entries:
            self._pending_entries.pop(symbol, None)
            return

        open_trades = self.db.get_open_trades()
        if any(trade["symbol"] == symbol for trade in open_trades):
            self._pending_entries.pop(symbol, None)
            return

        one_min_candles = self.ws_feed.cache.get(symbol.lower(), "1m")
        if len(one_min_candles) < 30:
            self._pending_entries[symbol] = active_entries
            return

        one_min_df = pd.DataFrame(one_min_candles)
        for col in ("open", "high", "low", "close", "volume"):
            if col in one_min_df.columns:
                one_min_df[col] = pd.to_numeric(one_min_df[col], errors="coerce")
        one_min_result = self.analysis_engine.analyze_single(symbol, "1m", one_min_df)

        remaining: list[PendingEntry] = []
        for pending in active_entries:
            pending_atr = pending.atr
            pending_snapshot = pending.market_snapshot_json
            signal_to_execute = pending.signal
            if pending.signal.strategy_name == "breakout":
                pending, trigger_check, confirmed_signal = self._process_breakout_retest_entry(
                    pending,
                    one_min_result,
                )
                if confirmed_signal is not None:
                    signal_to_execute = confirmed_signal
                if pending is None and not trigger_check.triggered:
                    continue
            else:
                trigger_check = self._entry_triggered(pending, one_min_result)
            if not trigger_check.triggered:
                logger.debug(
                    f"1m 觸發未成立: {pending.signal.symbol} {pending.signal.signal_type} "
                    f"{pending.signal.strategy_name} | {trigger_check.reason}"
                )
                remaining.append(pending)
                continue
            if pending.signal.strategy_name != "breakout":
                self.db.insert_analysis_log({
                    "symbol": signal_to_execute.symbol,
                    "timeframe": "1m_trigger",
                    "strategy_name": signal_to_execute.strategy_name,
                    "signal_generated": 1,
                    "signal_type": signal_to_execute.signal_type,
                    "signal_strength": signal_to_execute.strength,
                    "veto_passed": 1,
                    "final_action": "TRIGGER_CONFIRMED",
                    "market_snapshot": self._snapshot_from_json(
                        pending_snapshot,
                        trigger_reason=trigger_check.reason,
                    ),
                })
            # 從 1m K 線取入場 K 線 OHLC 供止損計算
            _1m_last = one_min_result.df_enriched.iloc[-1]
            _entry_candle = {
                "open": float(_1m_last.get("open", 0)),
                "high": float(_1m_last.get("high", 0)),
                "low": float(_1m_last.get("low", 0)),
                "close": float(_1m_last.get("close", 0)),
            }
            trade_id = await self._run_risk_and_execute(
                signal_to_execute,
                float(one_min_result.df_enriched["close"].iloc[-1]),
                pending_atr,
                pending_snapshot,
                entry_candle=_entry_candle,
            )
            if trade_id:
                logger.info(
                    f"1m 觸發成功: {signal_to_execute.symbol} {signal_to_execute.signal_type} "
                    f"{signal_to_execute.strategy_name}"
                )
            break

        if remaining:
            self._pending_entries[symbol] = remaining
        else:
            self._pending_entries.pop(symbol, None)

    def _entry_triggered(self, pending: PendingEntry, one_min_result) -> EntryTriggerCheck:
        if one_min_result.df_enriched is None or one_min_result.df_enriched.empty:
            return EntryTriggerCheck(False, "1m data unavailable")

        curr = one_min_result.df_enriched.iloc[-1]
        close = float(curr.get("close", 0))
        open_price = float(curr.get("open", close))
        high = float(curr.get("high", close))
        low = float(curr.get("low", close))
        volume = float(curr.get("volume", 0))
        avg_volume = float(one_min_result.df_enriched["volume"].iloc[-20:].mean())
        ema9 = curr.get("ema_9")
        rsi = curr.get("rsi")

        direction = pending.signal.signal_type
        strategy = pending.signal.strategy_name

        def _support_gate(checks: dict[str, bool], required_passes: int) -> EntryTriggerCheck:
            passed = [name for name, ok in checks.items() if ok]
            failed = [name for name, ok in checks.items() if not ok]
            if len(passed) >= required_passes:
                return EntryTriggerCheck(True, "triggered")
            return EntryTriggerCheck(
                False,
                f"support_checks_{len(passed)}_of_{len(checks)}: {', '.join(failed)}",
            )

        if strategy == "trend_following":
            signal_strength = self._pending_signal_strength(pending)
            if direction == "LONG":
                core_ok = close > pending.trigger_close
                if not core_ok:
                    return EntryTriggerCheck(False, "close_not_above_trigger_close")
                checks = {
                    "green_candle": close > open_price,
                    "above_ema9": ema9 is not None and close > float(ema9),
                    "rsi_ok": rsi is not None and float(rsi) >= 50,
                }
            else:
                core_ok = close < pending.trigger_close
                if not core_ok:
                    return EntryTriggerCheck(False, "close_not_below_trigger_close")
                checks = {
                    "red_candle": close < open_price,
                    "below_ema9": ema9 is not None and close < float(ema9),
                    "rsi_ok": rsi is not None and float(rsi) <= 50,
                }
            return _support_gate(
                checks,
                required_passes=self._required_support_passes(
                    signal_strength,
                    total_checks=len(checks),
                    default_passes=2,
                ),
            )

        if strategy == "breakout":
            volume_ok = avg_volume > 0 and volume > avg_volume * 1.2
            if direction == "LONG":
                checks = {
                    "close_break_high": close > pending.trigger_high,
                    "green_candle": close > open_price,
                    "volume_ok": volume_ok,
                }
            else:
                checks = {
                    "close_break_low": close < pending.trigger_low,
                    "red_candle": close < open_price,
                    "volume_ok": volume_ok,
                }
            failed = [name for name, ok in checks.items() if not ok]
            return EntryTriggerCheck(not failed, ", ".join(failed) if failed else "triggered")

        if strategy == "mean_reversion":
            signal_strength = self._pending_signal_strength(pending)
            if direction == "LONG":
                core_ok = close > pending.trigger_close
                if not core_ok:
                    return EntryTriggerCheck(False, "close_not_above_trigger_close")
                checks = {
                    "green_candle": close > open_price,
                    "above_ema9": ema9 is not None and close > float(ema9),
                }
            else:
                core_ok = close < pending.trigger_close
                if not core_ok:
                    return EntryTriggerCheck(False, "close_not_below_trigger_close")
                checks = {
                    "red_candle": close < open_price,
                    "below_ema9": ema9 is not None and close < float(ema9),
                }
            return _support_gate(
                checks,
                required_passes=self._required_support_passes(
                    signal_strength,
                    total_checks=len(checks),
                    default_passes=1,
                ),
            )

        return EntryTriggerCheck(False, f"unsupported strategy: {strategy}")

    async def _run_risk_and_execute(
        self,
        sig: TradeSignal,
        entry_price: float,
        atr: float,
        market_snapshot_json: str | None,
        entry_candle: dict | None = None,
    ) -> int | None:
        if normalize_strategy_family(sig.strategy_name) != "mean_reversion":
            current_mtf = self._quick_mtf_direction_check(sig.symbol)
            if current_mtf not in {None, "NEUTRAL", sig.signal_type}:
                console(
                    f"🚫 {sig.symbol} {sig.signal_type} MTF方向改變被擋 (當前MTF={current_mtf})"
                )
                logger.warning(
                    f"MTF_RECHECK_BLOCK: {sig.symbol} signal={sig.signal_type} "
                    f"but current MTF={current_mtf}"
                )
                self.db.insert_analysis_log({
                    "symbol": sig.symbol,
                    "timeframe": "1m_trigger",
                    "strategy_name": sig.strategy_name,
                    "signal_generated": 1,
                    "signal_type": sig.signal_type,
                    "signal_strength": sig.strength,
                    "veto_passed": 1,
                    "final_action": "MTF_RECHECK_BLOCK",
                    "market_snapshot": self._snapshot_from_json(
                        market_snapshot_json,
                        current_mtf_direction=current_mtf,
                    ),
                })
                return None

        balance = TRADING_INITIAL_BALANCE
        if self.binance_client:
            try:
                balance = await self.binance_client.get_balance()
            except Exception as e:
                logger.warning(f"取得交易所餘額失敗，使用初始餘額: {e}")
        open_trades = self.db.get_open_trades()
        if entry_price <= 0 or atr <= 0:
            return None

        # Get per-coin max leverage for fixed-margin sizing
        coin_max_lev = None
        if self.binance_client:
            try:
                coin_max_lev = await self.binance_client.get_leverage_brackets(sig.symbol)
            except Exception:
                pass
        if coin_max_lev is None:
            from core.risk.position_sizer import get_coin_max_leverage
            coin_max_lev = get_coin_max_leverage(sig.symbol)

        risk_result = self.risk_manager.evaluate(
            sig, balance, entry_price, atr, len(open_trades),
            coin_max_leverage=coin_max_lev,
            entry_candle=entry_candle,
        )
        if risk_result.passed:
            trade_id = await execute_trade(
                sig, risk_result, entry_price, self.db, sig.strategy_name
            )
            self.db.insert_analysis_log({
                "symbol": sig.symbol,
                "timeframe": "1m_trigger",
                "strategy_name": sig.strategy_name,
                "signal_generated": 1,
                "signal_type": sig.signal_type,
                "signal_strength": sig.strength,
                "veto_passed": 1,
                "risk_passed": 1,
                "final_action": "EXECUTED" if trade_id else "EXCHANGE_REJECTED",
                "market_snapshot": self._snapshot_from_json(
                    market_snapshot_json,
                    effective_risk_pct=round(risk_result.effective_risk_pct, 6),
                    sl_atr_mult=round(risk_result.sl_atr_mult, 4),
                    soft_stop_loss=round(risk_result.soft_stop_loss, 4),
                    hard_stop_loss=round(risk_result.hard_stop_loss, 4),
                    soft_stop_required_closes=int(risk_result.soft_stop_required_closes),
                    stop_zone_low=round(risk_result.stop_zone_low, 4),
                    stop_zone_high=round(risk_result.stop_zone_high, 4),
                    structure_stop_floor_triggered=bool(
                        risk_result.structure_stop_floor_triggered
                    ),
                ),
            })
            if not trade_id:
                    send_telegram_message(
                    f"❌ 退單 | {sig.symbol} {sig.signal_type} | {sig.strategy_name}\n📝 檢查日誌（保證金不足或槓桿問題）"
                )
            return trade_id

        self.db.insert_analysis_log({
            "symbol": sig.symbol,
            "timeframe": "1m_trigger",
            "strategy_name": sig.strategy_name,
            "signal_generated": 1,
            "signal_type": sig.signal_type,
            "signal_strength": sig.strength,
            "veto_passed": 1,
            "risk_passed": 0,
            "risk_reason": risk_result.reason,
            "final_action": "RISK_BLOCKED",
            "market_snapshot": self._snapshot_from_json(
                market_snapshot_json,
                effective_risk_pct=round(risk_result.effective_risk_pct, 6),
                sl_atr_mult=round(risk_result.sl_atr_mult, 4),
                soft_stop_loss=round(risk_result.soft_stop_loss, 4),
                hard_stop_loss=round(risk_result.hard_stop_loss, 4),
                soft_stop_required_closes=int(risk_result.soft_stop_required_closes),
                stop_zone_low=round(risk_result.stop_zone_low, 4),
                stop_zone_high=round(risk_result.stop_zone_high, 4),
                structure_stop_floor_triggered=bool(
                    risk_result.structure_stop_floor_triggered
                ),
            ),
        })
        send_telegram_message(
            f"🚫 風控擋 | {sig.symbol} {sig.signal_type} | {sig.strategy_name}\n📝 {risk_result.reason}"
        )
        console(f"🚫 {sig.symbol} {sig.signal_type} 風控擋！{risk_result.reason}")
        logger.info(f"風控攔截: {sig.symbol} {sig.signal_type} - {risk_result.reason}")
        return None

    async def _monitor_report(self) -> None:
        """每 N 分鐘發一則監控快報到 Telegram"""
        trades_today = self.db.get_trades_today(tz=APP_TIMEZONE)
        daily_pnl = self.db.get_daily_pnl(tz=APP_TIMEZONE)
        open_trades = self.db.get_open_trades()
        mode_tag = "[DEMO]" if BINANCE_TESTNET else "[LIVE]"
        summary = self._build_runtime_notification_summary()
        balance_str = ""
        if self.binance_client:
            try:
                bal = await self.binance_client.get_balance()
                balance_str = f"\n交易所餘額: {bal:.2f} U"
            except Exception:
                pass
        msg = (
            f"📊 快報 {mode_tag}\n"
            f"💰 {daily_pnl:+.2f}U | 📋 {len(trades_today)}筆 | 📦 持倉 {len(open_trades)}"
            f"{balance_str}"
        )
        send_telegram_message(msg)
        logger.debug("監控快報已發送")

    async def _daily_report(self) -> None:
        """生成每日績效報告並透過 Telegram 發送"""
        report_date = (datetime.now(APP_TIMEZONE).date() - pd.Timedelta(days=1)).isoformat()
        trades_today = self.db.get_trades_today(tz=APP_TIMEZONE, day_offset=-1)
        daily_pnl = self.db.get_daily_pnl(tz=APP_TIMEZONE, day_offset=-1)
        open_trades = self.db.get_open_trades()
        signal_chain = self._build_signal_decay_summary(day_offset=-1, report_date=report_date)
        exchange_balance = None
        if self.binance_client:
            try:
                exchange_balance = round(await self.binance_client.get_balance(), 2)
            except Exception:
                exchange_balance = None

        report_payload = {
            "report_date": report_date,
            "timezone": APP_TIMEZONE_NAME,
            "mode": TRADING_MODE,
            "trades_count": len(trades_today),
            "daily_pnl": round(float(daily_pnl), 2),
            "open_positions": len(open_trades),
            "exchange_balance": exchange_balance,
            "generated_at": datetime.now(APP_TIMEZONE).isoformat(),
            "signal_chain": signal_chain,
        }
        self._append_daily_report_log(report_payload)

        counts = signal_chain.get("counts", {})
        bottleneck = signal_chain.get("bottleneck", {})
        executed = counts.get('executed', 0)
        risk_blocked = counts.get('risk_blocked', 0)
        candidates = counts.get('candidate_signals', 0)
        bal_str = f" | 餘額 {exchange_balance:.0f}U" if exchange_balance is not None else ""
        report = (
            f"📈 日報 {report_date}\n"
            f"💰 {daily_pnl:+.2f}U | 📋 {len(trades_today)}筆 | 📦 持倉 {len(open_trades)}{bal_str}\n"
            f"🔍 信號 {candidates} → ✅ 執行 {executed} / 🚫 擋 {risk_blocked}\n"
            f"⚡ 瓶頸: {bottleneck.get('stage', 'none')} ({bottleneck.get('blocked', 0)})\n"
            f"📊 {self._format_count_map(signal_chain.get('strategies', {}).get('executed', {}))}"
        )
        logger.info(report)
        send_telegram_message(report)

    async def _heartbeat(self) -> None:
        """每分鐘 console 心跳 + 異常告警"""
        # 超過 5 分鐘未收到 K 線視為異常
        stale = (time.time() - self.last_kline_received_at) > 300
        if stale and self.last_kline_received_at > 0:
            msg = "💀 心跳異常 | >5分鐘無K線 | 檢查 WebSocket"
            console(msg)
            logger.warning(msg)
            send_telegram_message(msg)
            return

        # ── 正常心跳：顯示乾淨狀態行 ──
        balance_str = "N/A"
        if self.binance_client:
            try:
                bal = await self.binance_client.get_balance()
                balance_str = f"{bal:,.1f}U"
            except Exception:
                pass

        open_trades = self.db.get_open_trades() if self.db else []
        pending_count = sum(len(v) for v in self._pending_entries.values())

        # 價格：BTC + ETH + 持倉中的幣
        held_symbols = {t["symbol"] for t in open_trades}
        show_symbols = ["BTCUSDT", "ETHUSDT"]
        for sym in held_symbols:
            if sym not in show_symbols:
                show_symbols.append(sym)

        price_parts = []
        unrealized_pnl = 0.0
        for sym in show_symbols:
            latest = self.ws_feed.cache.get_latest(sym.lower(), "1m") if self.ws_feed else None
            if not latest and self.ws_feed:
                latest = self.ws_feed.cache.get_latest(sym.lower(), "15m")
            if latest and "close" in latest:
                price = float(latest["close"])
                short_name = sym.replace("USDT", "")
                if sym in held_symbols:
                    # 找到持倉的盈虧
                    trade = next((t for t in open_trades if t["symbol"] == sym), None)
                    if trade:
                        entry = float(trade.get("entry_price", 0))
                        side = trade.get("side", "LONG")
                        qty = float(trade.get("current_quantity") or trade.get("quantity", 0) or 0)
                        if entry > 0:
                            pnl_pct = ((price - entry) / entry) * 100
                            pos_pnl = (price - entry) * qty
                            if side == "SHORT":
                                pnl_pct = -pnl_pct
                                pos_pnl = (entry - price) * qty
                            unrealized_pnl += pos_pnl
                            price_parts.append(f"{short_name} {fmt_price(price)} ({pnl_pct:+.1f}%)")
                            continue
                price_parts.append(f"{short_name} {fmt_price(price)}")

        pnl_str = f" | 未實現 {unrealized_pnl:+.2f}U" if open_trades else ""
        line1 = f"💓 運行中 | 餘額 {balance_str}{pnl_str} | 持倉 {len(open_trades)} | 待觸發 {pending_count}"
        line2 = "   " + " | ".join(price_parts) if price_parts else ""
        console(line1)
        if line2.strip():
            console(line2)

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
        recent_candles: dict[str, dict[str, list[dict]]] = {}
        for sym in symbols:
            if self.ws_feed:
                recent_candles[sym] = {
                    "1m": list(self.ws_feed.cache.get(sym.lower(), "1m")[-30:]),
                    "5m": list(self.ws_feed.cache.get(sym.lower(), "5m")[-12:]),
                }
            # 優先從 WebSocket 快取取最新價
            latest = self.ws_feed.cache.get_latest(sym.lower(), "1m") if self.ws_feed else None
            if not latest and self.ws_feed:
                latest = self.ws_feed.cache.get_latest(sym.lower(), "15m")
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
        try:
            await asyncio.wait_for(
                run_position_check(
                    self.db,
                    self.binance_client,
                    prices,
                    recent_candles=recent_candles,
                    risk_manager=self.risk_manager,
                    observation_state=self._observation_state,
                ),
                timeout=30,
            )
        except asyncio.TimeoutError:
            logger.error("position_check timed out after 30s")

    async def run(self) -> None:
        """主運行迴圈"""
        await self.startup()

        # 啟動排程器
        self.scheduler.start()

        # 首次啟動立即抓取資訊管線數據
        console("📡 首次獲取市場資訊...")
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

        # 啟動 Telegram 指令監聽
        cmd_handler = TelegramCommandHandler(self)
        cmd_task = asyncio.create_task(cmd_handler.start())

        try:
            while self.running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            await self.shutdown()
            cmd_task.cancel()
            ws_task.cancel()
            try:
                await asyncio.gather(ws_task, cmd_task, return_exceptions=True)
            except asyncio.CancelledError:
                pass

    async def shutdown(self) -> None:
        """系統關閉序列"""
        console("🔴 TradingBrain 關閉中...")
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
