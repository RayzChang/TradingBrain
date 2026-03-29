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
                "open": 100.0 + idx * 0.05,
                "high": 100.8 + idx * 0.05,
                "low": 99.4 + idx * 0.05,
                "close": 100.2 + idx * 0.05,
                "volume": 100.0,
                "adx": 20 + idx * 0.2,
                "adx_pos": 22.0,
                "adx_neg": 18.0,
                "rsi": 55.0,
                "macd_hist": 0.1 + idx * 0.01,
            }
        )
    return rows


def test_breakout_long_uses_structure_high_not_bollinger_band() -> None:
    rows = _base_rows()
    rows[-2].update({"close": 101.4, "high": 101.8, "low": 100.9, "adx": 27.8, "macd_hist": 0.55})
    rows[-1].update(
        {
            "open": 101.5,
            "high": 103.3,
            "low": 101.2,
            "close": 103.0,
            "volume": 220.0,
            "adx": 28.5,
            "adx_pos": 28.0,
            "adx_neg": 16.0,
            "rsi": 61.0,
            "macd_hist": 0.8,
        }
    )
    strategy = BreakoutStrategy(skip_on_chop=False)
    df = pd.DataFrame(rows)

    signals = strategy.evaluate_single("BTCUSDT", "15m", _result(df))

    assert len(signals) == 1
    assert signals[0].signal_type == "LONG"
    assert signals[0].indicators["breakout_price"] == round(float(df.iloc[-21:-1]["high"].max()), 4)
    assert signals[0].indicators["breakout_body_ok"] is True


def test_breakout_short_uses_structure_low_and_keeps_short_symmetry() -> None:
    rows = _base_rows()
    for idx, row in enumerate(rows):
        row.update(
            {
                "open": 105.0 - idx * 0.05,
                "high": 105.6 - idx * 0.05,
                "low": 104.2 - idx * 0.05,
                "close": 104.8 - idx * 0.05,
                "adx_pos": 18.0,
                "adx_neg": 24.0,
                "rsi": 42.0,
                "macd_hist": -0.1 - idx * 0.01,
            }
        )
    rows[-2].update({"close": 103.6, "high": 104.0, "low": 103.1, "adx": 27.8, "macd_hist": -0.55})
    rows[-1].update(
        {
            "open": 103.5,
            "high": 103.7,
            "low": 101.4,
            "close": 101.8,
            "volume": 230.0,
            "adx": 28.5,
            "adx_pos": 22.0,
            "adx_neg": 20.0,
            "rsi": 37.0,
            "macd_hist": -0.8,
        }
    )
    strategy = BreakoutStrategy(skip_on_chop=False)
    df = pd.DataFrame(rows)

    signals = strategy.evaluate_single("BTCUSDT", "15m", _result(df))

    assert len(signals) == 1
    assert signals[0].signal_type == "SHORT"
    assert signals[0].indicators["breakout_price"] == round(float(df.iloc[-21:-1]["low"].min()), 4)
    assert signals[0].indicators["adx_neg_dominant"] is False


def test_breakout_rejects_when_structure_level_is_not_broken() -> None:
    rows = _base_rows()
    rows[-2].update({"close": 101.4, "high": 102.4, "low": 100.9, "adx": 27.8, "macd_hist": 0.55})
    rows[-1].update(
        {
            "open": 101.5,
            "high": 102.2,
            "low": 101.2,
            "close": 102.0,
            "volume": 240.0,
            "adx": 28.5,
            "adx_pos": 28.0,
            "adx_neg": 16.0,
            "rsi": 61.0,
            "macd_hist": 0.8,
        }
    )
    strategy = BreakoutStrategy(skip_on_chop=False)

    signals = strategy.evaluate_single("BTCUSDT", "15m", _result(pd.DataFrame(rows)))

    assert signals == []
