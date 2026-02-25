"""
信號聚合器 (Signal Aggregator)

1. 對完整分析結果執行多個策略，收集候選信號
2. 每個信號經否決引擎過濾，通過者進入下一階段（風控/執行）
3. 可選：將所有信號（含被否決）寫入資料庫供紀錄與回測
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from loguru import logger

from core.analysis.engine import FullAnalysis
from core.pipeline.veto_engine import VetoEngine
from core.strategy.base import BaseStrategy, TradeSignal

if TYPE_CHECKING:
    from database.db_manager import DatabaseManager


@dataclass
class AggregatorResult:
    """聚合結果"""
    passed: list[TradeSignal] = field(default_factory=list)
    vetoed: list[tuple[TradeSignal, str]] = field(default_factory=list)  # (signal, veto_reason)


class SignalAggregator:
    """
    多策略投票 + 否決引擎過濾。

    使用方式:
        aggregator = SignalAggregator(strategies=[...], veto_engine=veto_engine, db=db)
        result = aggregator.evaluate(full_analysis, save_to_db=True)
        # result.passed -> 進入風控的信號
        # result.vetoed -> 被否決的信號及原因
    """

    def __init__(
        self,
        strategies: list[BaseStrategy],
        veto_engine: VetoEngine,
        db: "DatabaseManager | None" = None,
    ) -> None:
        self.strategies = strategies
        self.veto_engine = veto_engine
        self.db = db

    def evaluate(
        self,
        full: FullAnalysis,
        primary_tf: str | None = None,
        save_to_db: bool = False,
    ) -> AggregatorResult:
        """
        執行所有策略並過濾否決。

        Args:
            full: 完整 MTF 分析結果
            primary_tf: 主時間框架（預設用 full.primary_tf）
            save_to_db: 是否將信號寫入 signals 表（含 was_vetoed, veto_reason）

        Returns:
            AggregatorResult(passed=[...], vetoed=[(signal, reason), ...])
        """
        tf = primary_tf or full.primary_tf
        candidates: list[TradeSignal] = []

        for strategy in self.strategies:
            sigs = strategy.evaluate_full(full, primary_tf=tf)
            candidates.extend(sigs)

        if not candidates:
            logger.debug(f"{full.symbol} no candidate signals from {len(self.strategies)} strategies")
            return AggregatorResult()

        passed: list[TradeSignal] = []
        vetoed: list[tuple[TradeSignal, str]] = []

        for sig in candidates:
            if sig.signal_type not in ("LONG", "SHORT"):
                continue
            veto = self.veto_engine.evaluate(sig.symbol, sig.signal_type)
            if veto.passed:
                passed.append(sig)
                logger.info(f"Signal PASS: {sig.symbol} {sig.signal_type} by {sig.strategy_name} strength={sig.strength}")
            else:
                reason = "; ".join(veto.reasons)
                vetoed.append((sig, reason))
                logger.info(f"Signal VETOED: {sig.symbol} {sig.signal_type} - {reason}")

        if save_to_db and self.db:
            self._save_signals(passed, vetoed)

        return AggregatorResult(passed=passed, vetoed=vetoed)

    def _save_signals(
        self,
        passed: list[TradeSignal],
        vetoed: list[tuple[TradeSignal, str]],
    ) -> None:
        """將信號寫入資料庫"""
        for sig in passed:
            row = sig.to_db_row()
            row["was_vetoed"] = 0
            row["veto_reason"] = None
            row["was_executed"] = 0
            self.db.insert_signal(row)
        for sig, reason in vetoed:
            row = sig.to_db_row()
            row["was_vetoed"] = 1
            row["veto_reason"] = reason
            row["was_executed"] = 0
            self.db.insert_signal(row)
