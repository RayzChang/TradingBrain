"""
策略基類 — 統一介面

所有策略必須繼承 BaseStrategy 並實作 evaluate()。
輸入為技術分析結果（單一 TF 或 FullAnalysis），輸出為候選交易信號列表。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from core.analysis.engine import AnalysisResult, FullAnalysis


@dataclass
class TradeSignal:
    """
    單一交易信號，對應資料庫 signals 表。
    """
    symbol: str
    timeframe: str
    signal_type: str  # "LONG" | "SHORT" | "CLOSE"
    strength: float  # 0.0 ~ 1.0
    strategy_name: str
    indicators: dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    def to_db_row(self) -> dict:
        """轉成資料庫 insert 用字典（不含 was_vetoed, veto_reason, was_executed）"""
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "signal_type": self.signal_type,
            "strength": self.strength,
            "strategy_name": self.strategy_name,
            "indicators": self.indicators,
        }


class BaseStrategy(ABC):
    """
    策略抽象基類。

    子類必須實作:
        name: 策略唯一名稱
        evaluate_single(result: AnalysisResult) -> list[TradeSignal]
    可選覆寫:
        evaluate_full(full: FullAnalysis) -> list[TradeSignal]  # 預設為對 primary_tf 調用 evaluate_single
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """策略唯一識別名稱"""
        ...

    @abstractmethod
    def evaluate_single(
        self,
        symbol: str,
        timeframe: str,
        result: AnalysisResult,
    ) -> list[TradeSignal]:
        """
        根據單一時間框架分析結果產生信號。

        Args:
            symbol: 交易對
            timeframe: 時間框架
            result: AnalysisResult（含 indicators, divergences, fibonacci, candle_patterns, chop）

        Returns:
            候選信號列表（可為空）
        """
        ...

    def evaluate_full(
        self,
        full: FullAnalysis,
        primary_tf: str | None = None,
    ) -> list[TradeSignal]:
        """
        根據完整 MTF 分析結果產生信號。
        預設使用 primary_tf 的單一分析結果呼叫 evaluate_single。
        子類可覆寫以結合多時間框架邏輯。
        """
        tf = primary_tf or full.primary_tf
        single = full.single_tf_results.get(tf)
        if not single:
            return []
        return self.evaluate_single(full.symbol, tf, single)
