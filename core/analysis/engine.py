"""
技術分析引擎 — 整合所有分析模組的統一入口

AnalysisEngine 是策略層與數據層之間的橋樑:
  1. 接收 K 線數據
  2. 計算所有技術指標
  3. 偵測背離、K 線型態
  4. 計算斐波那契位
  5. 進行多時間框架分析
  6. 偵測絞肉機行情
  7. 輸出結構化的分析結果供策略引擎使用
"""

from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from loguru import logger

from core.analysis.indicators import add_all_indicators, get_indicator_summary
from core.analysis.divergence import detect_all_divergences, Divergence
from core.analysis.fibonacci import calculate_fibonacci, get_fib_summary
from core.analysis.candlestick import detect_all_patterns, get_latest_pattern_signal, CandlePattern
from core.analysis.multi_timeframe import (
    analyze_multi_timeframe,
    check_htf_rsi_confirmation,
    MTFAnalysis,
)
from core.analysis.chop_detector import detect_chop, ChopResult


@dataclass
class AnalysisResult:
    """單一幣對、單一時間框架的分析結果"""
    symbol: str
    timeframe: str
    indicators: dict[str, Any] = field(default_factory=dict)
    divergences: list[Divergence] = field(default_factory=list)
    fibonacci: dict[str, Any] = field(default_factory=dict)
    candle_patterns: list[CandlePattern] = field(default_factory=list)
    chop: ChopResult | None = None
    df_enriched: pd.DataFrame | None = None  # 含指標的 DataFrame


@dataclass
class FullAnalysis:
    """完整分析結果（含 MTF）"""
    symbol: str
    primary_tf: str
    single_tf_results: dict[str, AnalysisResult] = field(default_factory=dict)
    mtf: MTFAnalysis | None = None
    htf_rsi_confirmed: bool = True


class AnalysisEngine:
    """
    技術分析引擎。

    使用方式:
        engine = AnalysisEngine()
        result = engine.analyze_single(symbol, timeframe, df)
        full = engine.analyze_full(symbol, kline_data_dict)
    """

    def analyze_single(
        self,
        symbol: str,
        timeframe: str,
        df: pd.DataFrame,
        divergence_lookback: int = 60,
        pattern_lookback: int = 10,
        fib_lookback: int = 100,
    ) -> AnalysisResult:
        """
        單一時間框架的完整技術分析。

        Args:
            symbol: 交易對 (e.g. "BTCUSDT")
            timeframe: 時間框架 (e.g. "15m")
            df: OHLCV DataFrame
            divergence_lookback: 背離偵測回溯數
            pattern_lookback: K 線型態回溯數
            fib_lookback: 斐波那契回溯數

        Returns:
            AnalysisResult
        """
        if df.empty or len(df) < 30:
            logger.warning(f"{symbol} {timeframe}: Not enough data ({len(df)} candles)")
            return AnalysisResult(symbol=symbol, timeframe=timeframe)

        df_enriched = add_all_indicators(df)

        indicators = get_indicator_summary(df_enriched)
        divergences = detect_all_divergences(df_enriched, divergence_lookback)
        fibonacci = get_fib_summary(df_enriched, fib_lookback)
        patterns = detect_all_patterns(df_enriched, pattern_lookback)
        chop = detect_chop(df_enriched)

        result = AnalysisResult(
            symbol=symbol,
            timeframe=timeframe,
            indicators=indicators,
            divergences=divergences,
            fibonacci=fibonacci,
            candle_patterns=patterns,
            chop=chop,
            df_enriched=df_enriched,
        )

        logger.debug(
            f"{symbol} {timeframe} analysis: "
            f"trend={indicators.get('trend')}, "
            f"divergences={len(divergences)}, "
            f"patterns={len(patterns)}, "
            f"chop={chop.is_chop if chop else 'N/A'}"
        )

        return result

    def analyze_full(
        self,
        symbol: str,
        kline_data: dict[str, pd.DataFrame],
        primary_tf: str = "15m",
    ) -> FullAnalysis:
        """
        完整多時間框架分析。

        Args:
            symbol: 交易對
            kline_data: {timeframe: DataFrame} 字典
            primary_tf: 主要進場時間框架

        Returns:
            FullAnalysis
        """
        full = FullAnalysis(symbol=symbol, primary_tf=primary_tf)

        enriched_data: dict[str, pd.DataFrame] = {}

        for tf, df in kline_data.items():
            result = self.analyze_single(symbol, tf, df)
            full.single_tf_results[tf] = result
            if result.df_enriched is not None:
                enriched_data[tf] = result.df_enriched

        if len(enriched_data) >= 2:
            full.mtf = analyze_multi_timeframe(enriched_data, primary_tf)

            if full.mtf.recommended_direction:
                full.htf_rsi_confirmed = check_htf_rsi_confirmation(
                    enriched_data,
                    full.mtf.recommended_direction,
                )
        else:
            logger.info(f"{symbol}: Only {len(enriched_data)} timeframe(s) available, skipping MTF")

        logger.info(
            f"{symbol} full analysis complete: "
            f"{len(full.single_tf_results)} timeframes, "
            f"MTF alignment={full.mtf.alignment.value if full.mtf else 'N/A'}, "
            f"HTF RSI confirmed={full.htf_rsi_confirmed}"
        )

        return full

    def get_analysis_snapshot(self, full: FullAnalysis) -> dict:
        """
        生成精簡的分析快照（供 API / 儀表板 / 策略使用）。
        """
        primary = full.single_tf_results.get(full.primary_tf)

        snapshot = {
            "symbol": full.symbol,
            "primary_tf": full.primary_tf,
            "indicators": primary.indicators if primary else {},
            "divergences": [
                {"type": d.type.value, "indicator": d.indicator, "strength": d.strength}
                for d in (primary.divergences if primary else [])
            ],
            "fibonacci": primary.fibonacci if primary else {},
            "candle_pattern": get_latest_pattern_signal(
                primary.df_enriched
            ) if primary and primary.df_enriched is not None else {},
            "chop": {
                "is_chop": primary.chop.is_chop,
                "score": primary.chop.score,
                "cooldown_minutes": primary.chop.cooldown_minutes,
            } if primary and primary.chop else {},
            "mtf": {
                "alignment": full.mtf.alignment.value,
                "confidence": full.mtf.confidence,
                "direction": full.mtf.recommended_direction,
                "htf_rsi_confirmed": full.htf_rsi_confirmed,
                "details": full.mtf.details,
            } if full.mtf else {},
        }

        return snapshot
