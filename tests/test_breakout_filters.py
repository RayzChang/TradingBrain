import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.analysis.engine import AnalysisResult
from core.strategy.breakout import BreakoutStrategy


@dataclass
class _DummyChop:
    is_chop: bool = False


def _result(df: pd.DataFrame) -> AnalysisResult:
    return AnalysisResult(
        symbol="BTCUSDT",
        timeframe="15m",
        indicators={},
        divergences=[],
        fibonacci={"available": False},
        candle_patterns=[],
        chop=_DummyChop(False),
        df_enriched=df,
    )


def _base_rows() -> list[dict]:
    rows: list[dict] = []
    for idx in range(30):
        rows.append(
            {
                "open": 100 - idx * 0.2,
                "high": 100.3 - idx * 0.2,
                "low": 99.7 - idx * 0.2,
                "close": 100 - idx * 0.2,
                "bb_upper": 102.0,
                "bb_lower": 94.0,
                "volume": 100.0,
                "adx": 20 + idx * 0.2,
                "adx_pos": 18.0,
                "adx_neg": 24.0,
                "rsi": 42.0,
                "macd_hist": -0.2 - idx * 0.01,
                "ema_21": 96.0,
                "ema_50": 97.0,
            }
        )
    return rows


def test_breakout_short_requires_bearish_structure_stack() -> None:
    rows = _base_rows()
    rows[-2].update({"close": 94.2, "bb_lower": 94.0, "adx": 28.0, "macd_hist": -0.8})
    rows[-1].update(
        {
            "open": 94.1,
            "high": 94.4,
            "low": 93.4,
            "close": 93.8,
            "bb_lower": 94.0,
            "volume": 140.0,
            "adx": 29.0,
            "adx_pos": 22.0,
            "adx_neg": 20.0,
            "rsi": 39.0,
            "macd_hist": -1.0,
            "ema_21": 93.9,
            "ema_50": 93.7,
        }
    )
    strategy = BreakoutStrategy(skip_on_chop=False)

    signals = strategy.evaluate_single("BTCUSDT", "15m", _result(pd.DataFrame(rows)))

    assert signals == []


def test_breakout_short_emits_when_bearish_breakout_is_confirmed() -> None:
    rows = _base_rows()
    rows[-2].update({"close": 94.2, "bb_lower": 94.0, "adx": 28.0, "macd_hist": -0.8})
    rows[-1].update(
        {
            "open": 94.0,
            "high": 94.1,
            "low": 92.8,
            "close": 93.0,
            "bb_lower": 94.0,
            "volume": 240.0,
            "adx": 29.0,
            "adx_pos": 18.0,
            "adx_neg": 27.0,
            "rsi": 39.0,
            "macd_hist": -1.1,
            "ema_21": 93.5,
            "ema_50": 95.0,
        }
    )
    strategy = BreakoutStrategy(skip_on_chop=False)

    signals = strategy.evaluate_single("BTCUSDT", "15m", _result(pd.DataFrame(rows)))

    assert len(signals) == 1
    assert signals[0].signal_type == "SHORT"
    assert signals[0].indicators["breakout_body_ok"] is True


def test_breakout_short_allows_early_trend_breaks_without_ema_stack() -> None:
    rows = _base_rows()
    rows[-2].update({"close": 94.2, "bb_lower": 94.0, "adx": 28.0, "macd_hist": -0.8, "low": 93.9})
    rows[-1].update(
        {
            "open": 94.0,
            "high": 94.1,
            "low": 92.8,
            "close": 93.0,
            "bb_lower": 94.0,
            "volume": 160.0,
            "adx": 29.0,
            "adx_pos": 18.0,
            "adx_neg": 27.0,
            "rsi": 39.0,
            "macd_hist": -1.1,
            "ema_21": 92.7,
            "ema_50": 92.5,
        }
    )
    strategy = BreakoutStrategy(skip_on_chop=False)

    signals = strategy.evaluate_single("BTCUSDT", "15m", _result(pd.DataFrame(rows)))

    assert len(signals) == 1
    assert signals[0].signal_type == "SHORT"


def test_breakout_short_skips_oversold_flushes() -> None:
    rows = _base_rows()
    rows[-2].update({"close": 94.2, "bb_lower": 94.0, "adx": 28.0, "macd_hist": -0.8, "low": 93.9})
    rows[-1].update(
        {
            "open": 94.0,
            "high": 94.1,
            "low": 92.8,
            "close": 93.0,
            "bb_lower": 94.0,
            "volume": 260.0,
            "adx": 29.0,
            "adx_pos": 18.0,
            "adx_neg": 27.0,
            "rsi": 28.0,
            "macd_hist": -1.1,
            "ema_21": 93.5,
            "ema_50": 95.0,
        }
    )
    strategy = BreakoutStrategy(skip_on_chop=False)

    signals = strategy.evaluate_single("BTCUSDT", "15m", _result(pd.DataFrame(rows)))

    assert signals == []
