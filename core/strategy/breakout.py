"""
突破策略 (Breakout) v1

邏輯:
- 做多突破: 價格突破布林上軌 + 成交量放大 + ADX 上升中（趨勢正在形成）
- 做空跌破: 價格跌破布林下軌 + 成交量放大 + ADX 上升中
- 強化確認: MACD 柱狀圖擴張 + K 線型態確認

設計理念:
  突破策略捕捉的是「大行情剛啟動」的時刻。
  與趨勢策略不同，突破不需要 EMA 交叉（那已經太慢了），
  而是直接看價格是否「衝出」正常波動範圍。
  搭配成交量確認，過濾假突破。
"""

import pandas as pd
from loguru import logger

from core.analysis.engine import AnalysisResult
from core.analysis.candlestick import PatternDirection
from core.strategy.base import BaseStrategy, TradeSignal, MarketRegime


class BreakoutStrategy(BaseStrategy):
    """
    布林帶突破 + 成交量確認 + MACD 動能。
    只在趨勢狀態下適用（突破通常伴隨趨勢產生）。
    """
    allowed_regimes = [MarketRegime.TRENDING]

    def __init__(
        self,
        volume_mult: float = 1.5,    # 成交量需>均量 1.5 倍
        adx_rising_bars: int = 3,     # ADX 連續上升 N 根
        skip_on_chop: bool = True,
    ) -> None:
        self.volume_mult = volume_mult
        self.adx_rising_bars = adx_rising_bars
        self.skip_on_chop = skip_on_chop

    @property
    def name(self) -> str:
        return "breakout"

    def evaluate_single(
        self,
        symbol: str,
        timeframe: str,
        result: AnalysisResult,
    ) -> list[TradeSignal]:
        signals: list[TradeSignal] = []

        if result.df_enriched is None or len(result.df_enriched) < 30:
            return signals

        if self.skip_on_chop and result.chop and result.chop.is_chop:
            return signals

        df = result.df_enriched
        required = ["close", "bb_upper", "bb_lower", "volume", "adx", "macd_hist"]
        if not all(c in df.columns for c in required):
            return signals

        curr = df.iloc[-1]
        prev = df.iloc[-2]
        close = float(curr["close"])
        bb_upper = float(curr["bb_upper"]) if not pd.isna(curr["bb_upper"]) else None
        bb_lower = float(curr["bb_lower"]) if not pd.isna(curr["bb_lower"]) else None
        volume = float(curr["volume"])
        adx = float(curr["adx"]) if not pd.isna(curr["adx"]) else None

        if bb_upper is None or bb_lower is None or adx is None:
            return signals

        # 均量計算
        avg_volume = df["volume"].iloc[-20:].mean()
        volume_confirmed = volume > avg_volume * self.volume_mult

        # ADX 上升確認（趨勢正在加強）
        adx_rising = self._is_adx_rising(df, self.adx_rising_bars)

        # MACD 柱狀圖方向
        macd_hist = float(curr["macd_hist"]) if not pd.isna(curr["macd_hist"]) else 0
        macd_hist_prev = float(prev["macd_hist"]) if not pd.isna(prev["macd_hist"]) else 0
        macd_expanding_bullish = macd_hist > macd_hist_prev and macd_hist > 0
        macd_expanding_bearish = macd_hist < macd_hist_prev and macd_hist < 0

        # K 線型態加分
        candle = self._candle_pattern_bonus(result)

        # === 做多突破 ===
        # 價格收在布林上軌之上（突破）
        if close > bb_upper and float(prev["close"]) <= float(prev.get("bb_upper", bb_upper)):
            if volume_confirmed and adx_rising:
                strength = 0.6

                if macd_expanding_bullish:
                    strength += 0.15
                if candle.get("bullish", 0) > 0:
                    strength += 0.1
                if adx > 30:
                    strength += 0.1  # 強趨勢加分

                strength = min(strength, 1.0)

                signals.append(TradeSignal(
                    symbol=symbol,
                    timeframe=timeframe,
                    signal_type="LONG",
                    strength=round(strength, 2),
                    strategy_name=self.name,
                    indicators={
                        "adx": round(adx, 2),
                        "volume_ratio": round(volume / avg_volume, 2),
                        "macd_expanding": macd_expanding_bullish,
                        "bb_upper": round(bb_upper, 4),
                        "close": round(close, 4),
                    },
                    reason=f"價格突破布林上軌（量增{volume/avg_volume:.1f}x、ADX上升中）",
                ))
                logger.debug(f"{self.name} LONG breakout: {symbol} {timeframe} ADX={adx:.1f}")

        # === 做空跌破 ===
        if close < bb_lower and float(prev["close"]) >= float(prev.get("bb_lower", bb_lower)):
            if volume_confirmed and adx_rising:
                strength = 0.6

                if macd_expanding_bearish:
                    strength += 0.15
                if candle.get("bearish", 0) > 0:
                    strength += 0.1
                if adx > 30:
                    strength += 0.1

                strength = min(strength, 1.0)

                signals.append(TradeSignal(
                    symbol=symbol,
                    timeframe=timeframe,
                    signal_type="SHORT",
                    strength=round(strength, 2),
                    strategy_name=self.name,
                    indicators={
                        "adx": round(adx, 2),
                        "volume_ratio": round(volume / avg_volume, 2),
                        "macd_expanding": macd_expanding_bearish,
                        "bb_lower": round(bb_lower, 4),
                        "close": round(close, 4),
                    },
                    reason=f"價格跌破布林下軌（量增{volume/avg_volume:.1f}x、ADX上升中）",
                ))
                logger.debug(f"{self.name} SHORT breakout: {symbol} {timeframe} ADX={adx:.1f}")

        return signals

    @staticmethod
    def _is_adx_rising(df: pd.DataFrame, bars: int = 3) -> bool:
        """ADX 是否連續上升 N 根"""
        if "adx" not in df.columns or len(df) < bars + 1:
            return False
        adx_vals = df["adx"].iloc[-(bars + 1):].values
        for i in range(1, len(adx_vals)):
            if pd.isna(adx_vals[i]) or pd.isna(adx_vals[i - 1]):
                return False
            if adx_vals[i] <= adx_vals[i - 1]:
                return False
        return True

    @staticmethod
    def _candle_pattern_bonus(result: AnalysisResult) -> dict:
        bullish = sum(1 for p in result.candle_patterns if p.direction == PatternDirection.BULLISH)
        bearish = sum(1 for p in result.candle_patterns if p.direction == PatternDirection.BEARISH)
        return {"bullish": bullish, "bearish": bearish}
