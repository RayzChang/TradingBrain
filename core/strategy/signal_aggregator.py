"""
信號聚合器 (Signal Aggregator) v2

1. 對完整分析結果執行多個策略，收集候選信號
2. v2: 同幣對衝突解決（同時有 LONG/SHORT 只取強度最高的）
3. 每個信號經否決引擎過濾，通過者進入下一階段（風控/執行）
4. v2: 同標的同方向冷卻（短時間內不重複開倉）
5. 可選：將所有信號（含被否決）寫入資料庫供紀錄與回測
"""

import time
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
    多策略投票 + 衝突解決 + 同標的冷卻 + 否決引擎過濾。

    使用方式:
        aggregator = SignalAggregator(strategies=[...], veto_engine=veto_engine, db=db)
        result = aggregator.evaluate(full_analysis, save_to_db=True)
        # result.passed -> 進入風控的信號
        # result.vetoed -> 被否決的信號及原因
    """

    # 同標的同方向冷卻時間（秒），預設 4 小時
    SYMBOL_COOLDOWN_SEC = 2 * 3600

    def __init__(
        self,
        strategies: list[BaseStrategy],
        veto_engine: VetoEngine,
        db: "DatabaseManager | None" = None,
    ) -> None:
        self.strategies = strategies
        self.veto_engine = veto_engine
        self.db = db
        # 同標的冷卻記錄: {(symbol, direction): last_signal_time}
        self._symbol_cooldown: dict[tuple[str, str], float] = {}

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
            logger.info(
                f"{full.symbol} 無候選信號（{len(self.strategies)} 個策略均未觸發）"
            )
            return AggregatorResult()

        # --- v2: 衝突解決 ---
        # 同幣對同時有 LONG 和 SHORT → 只保留 strength 最高的
        candidates = self._resolve_conflicts(candidates)

        passed: list[TradeSignal] = []
        vetoed: list[tuple[TradeSignal, str]] = []

        for sig in candidates:
            if sig.signal_type not in ("LONG", "SHORT"):
                continue

            # v2: 同標的冷卻檢查
            cooldown_key = (sig.symbol, sig.signal_type)
            last_time = self._symbol_cooldown.get(cooldown_key, 0)
            if time.time() - last_time < self.SYMBOL_COOLDOWN_SEC:
                remaining = int(self.SYMBOL_COOLDOWN_SEC - (time.time() - last_time))
                reason = f"同標的冷卻: {sig.symbol} {sig.signal_type} 剩餘 {remaining}s"
                vetoed.append((sig, reason))
                logger.info(f"Signal COOLDOWN: {sig.symbol} {sig.signal_type} - {reason}")
                continue

            veto = self.veto_engine.evaluate(sig.symbol, sig.signal_type)
            if veto.passed:
                passed.append(sig)
                # 記錄冷卻時間
                self._symbol_cooldown[cooldown_key] = time.time()
                logger.info(f"Signal PASS: {sig.symbol} {sig.signal_type} by {sig.strategy_name} strength={sig.strength}")
            else:
                reason = "; ".join(veto.reasons)
                vetoed.append((sig, reason))
                logger.info(f"Signal VETOED: {sig.symbol} {sig.signal_type} - {reason}")

        if save_to_db and self.db:
            self._save_signals(passed, vetoed)

        return AggregatorResult(passed=passed, vetoed=vetoed)

    @staticmethod
    def _resolve_conflicts(candidates: list[TradeSignal]) -> list[TradeSignal]:
        """
        衝突解決：同幣對同時有 LONG 和 SHORT 信號時，只保留 strength 最高的。
        不同幣對的信號互不影響。
        """
        # 按 symbol 分組
        by_symbol: dict[str, list[TradeSignal]] = {}
        for sig in candidates:
            by_symbol.setdefault(sig.symbol, []).append(sig)

        resolved: list[TradeSignal] = []
        for symbol, sigs in by_symbol.items():
            directions = set(s.signal_type for s in sigs)
            if "LONG" in directions and "SHORT" in directions:
                # 衝突！只保留最強的方向
                best = max(sigs, key=lambda s: s.strength)
                logger.info(
                    f"信號衝突解決: {symbol} 有 {len(sigs)} 個信號 "
                    f"(LONG+SHORT)，保留 {best.signal_type} strength={best.strength}"
                )
                resolved.append(best)
            else:
                # 同方向 → 保留最強的一個（不重複開同方向）
                best = max(sigs, key=lambda s: s.strength)
                resolved.append(best)

        return resolved

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
