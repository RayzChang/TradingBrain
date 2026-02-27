"""
策略基類 — 統一介面 v3

所有策略必須繼承 BaseStrategy 並實作 evaluate()。

v3 改版：
  - evaluate_full() 加入市場狀態偵測（trending vs ranging）
  - 趨勢狀態 → 只允許 trend_following + breakout
  - 震盪狀態 → 只允許 mean_reversion
  - MTF 方向過濾維持不變
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from loguru import logger

from core.analysis.engine import AnalysisResult, FullAnalysis


class MarketRegime:
    """市場狀態判定"""
    TRENDING = "trending"     # ADX > 20，有方向
    RANGING = "ranging"       # ADX < 20，橫盤震盪
    UNKNOWN = "unknown"

    @staticmethod
    def detect(result: AnalysisResult) -> str:
        """根據分析結果判定當前市場狀態"""
        if result.df_enriched is None or result.df_enriched.empty:
            return MarketRegime.UNKNOWN

        adx = result.indicators.get("adx")
        if adx is None:
            return MarketRegime.UNKNOWN

        try:
            adx_f = float(adx)
        except (TypeError, ValueError):
            return MarketRegime.UNKNOWN

        if pd.isna(adx_f):
            return MarketRegime.UNKNOWN

        if adx_f >= 20:
            return MarketRegime.TRENDING
        else:
            return MarketRegime.RANGING


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
    策略抽象基類 v3。

    子類需設定 allowed_regimes 來標明適用的市場狀態。
    """

    # 子類覆寫: 這個策略適用哪些市場狀態
    allowed_regimes: list[str] = [MarketRegime.TRENDING, MarketRegime.RANGING]

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def evaluate_single(
        self,
        symbol: str,
        timeframe: str,
        result: AnalysisResult,
    ) -> list[TradeSignal]:
        ...

    def evaluate_full(
        self,
        full: FullAnalysis,
        primary_tf: str | None = None,
    ) -> list[TradeSignal]:
        """
        根據完整 MTF 分析結果產生信號。

        v3 改版：
        1. 市場狀態檢查：策略只在允許的狀態下出信號
        2. MTF 方向過濾：信號必須與多時間框架推薦方向一致
        3. HTF RSI 確認
        """
        tf = primary_tf or full.primary_tf
        single = full.single_tf_results.get(tf)
        if not single:
            return []

        # --- 市場狀態檢查 ---
        regime = MarketRegime.detect(single)
        if regime != MarketRegime.UNKNOWN and regime not in self.allowed_regimes:
            logger.debug(
                f"{self.name} 跳過: 市場狀態 {regime} 不在允許範圍 {self.allowed_regimes}"
            )
            return []

        signals = self.evaluate_single(full.symbol, tf, single)
        if not signals:
            return signals

        # --- MTF 方向過濾 ---
        mtf_direction = None
        mtf_confidence = 0.0
        if full.mtf and full.mtf.recommended_direction:
            mtf_direction = full.mtf.recommended_direction
            mtf_confidence = full.mtf.confidence

        htf_rsi_ok = full.htf_rsi_confirmed

        filtered: list[TradeSignal] = []
        for sig in signals:
            # MTF 方向不一致 → 過濾
            if mtf_direction is not None and sig.signal_type != mtf_direction:
                logger.debug(
                    f"MTF 過濾: {sig.symbol} {sig.signal_type} "
                    f"(MTF={mtf_direction}, conf={mtf_confidence:.0%})"
                )
                continue

            # HTF RSI 極端 → 過濾
            if not htf_rsi_ok:
                logger.debug(
                    f"HTF RSI 過濾: {sig.symbol} {sig.signal_type}"
                )
                continue

            # MTF 一致 → 加分
            if mtf_direction == sig.signal_type and mtf_confidence > 0.5:
                sig.strength = min(sig.strength + 0.1, 1.0)
                sig.indicators["mtf_aligned"] = True
                sig.indicators["mtf_confidence"] = mtf_confidence

            sig.indicators["market_regime"] = regime
            filtered.append(sig)

        return filtered
