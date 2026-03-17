"""
第五階段測試 — 風險管理核心

驗證: 倉位計算、止損止盈、每日熔斷、連虧冷卻、RiskManager 整合
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.risk.position_sizer import PositionSizer, PositionSizeResult, _parse_max_open_positions
from core.risk.stop_loss import StopLossCalculator, StopLossResult
from core.risk.exit_profiles import get_exit_profile, normalize_strategy_family
from core.risk.structure_levels import (
    StructureLevels,
    compute_structure_levels,
    get_structure_stop_floor_mult,
)
from core.risk.daily_limits import DailyLimitsChecker, DailyLimitsResult
from core.risk.cooldown import CooldownChecker, CooldownResult
from core.risk.risk_manager import RiskManager, RiskCheckResult
from core.strategy.base import TradeSignal


def test_parse_max_open_positions():
    print("\n=== 測試 max_open_positions 自適應 ===")
    assert _parse_max_open_positions("auto", 300) == 1
    assert _parse_max_open_positions("auto", 500) == 2
    assert _parse_max_open_positions("auto", 800) == 2
    assert _parse_max_open_positions("auto", 1000) == 3
    assert _parse_max_open_positions("auto", 1500) == 3
    assert _parse_max_open_positions(2, 100) == 2
    print("  [PASS]")


def test_position_sizer():
    print("\n=== 測試倉位計算器 ===")
    # 無 DB 時用預設參數
    sizer = PositionSizer(db=None)
    # 手動給足夠 ATR 使倉位 > 10
    result = sizer.compute(
        balance=300, entry_price=100, atr=2.0, direction="LONG",
        stop_loss_atr_mult=1.5,
    )
    assert isinstance(result, PositionSizeResult)
    if not result.rejected:
        assert result.size_usdt >= 10
        assert result.leverage >= 1
    else:
        assert result.reason

    # 故意讓倉位 < 10（小 ATR 或大止損倍數）
    small = sizer.compute(
        balance=50, entry_price=100, atr=0.1, direction="SHORT",
        stop_loss_atr_mult=3.0,
    )
    # 可能 rejected 因 size < min_notional
    print(f"  size result: rejected={result.rejected}, size_usdt={result.size_usdt}")
    print(f"  small balance result: rejected={small.rejected}, reason={small.reason}")
    print("  [PASS]")


def test_position_sizer_prefers_structure_stop_distance():
    print("\n=== 測試 position sizing 優先使用結構止損距離 ===")
    sizer = PositionSizer(db=None)
    close_stop = sizer.compute(
        balance=1000,
        entry_price=100,
        atr=2.0,
        direction="LONG",
        stop_loss_atr_mult=1.5,
        stop_loss_price=99,
    )
    far_stop = sizer.compute(
        balance=1000,
        entry_price=100,
        atr=2.0,
        direction="LONG",
        stop_loss_atr_mult=1.5,
        stop_loss_price=95,
    )
    assert close_stop.rejected is False
    assert far_stop.rejected is False
    assert close_stop.size_usdt > far_stop.size_usdt
    print("  [PASS]")


def test_position_sizer_applies_strategy_weight_and_signal_strength():
    print("\n=== 測試 position sizing 套用策略權重與信號強度 ===")
    sizer = PositionSizer(db=None)
    breakout = sizer.compute(
        balance=1000,
        entry_price=100,
        atr=2.0,
        direction="LONG",
        strategy_name="breakout_retest",
        signal_strength=1.0,
        stop_loss_price=96.0,
    )
    trend = sizer.compute(
        balance=1000,
        entry_price=100,
        atr=2.0,
        direction="LONG",
        strategy_name="trend_following",
        signal_strength=1.0,
        stop_loss_price=96.0,
    )
    mean_rev = sizer.compute(
        balance=1000,
        entry_price=100,
        atr=2.0,
        direction="LONG",
        strategy_name="mean_reversion",
        signal_strength=1.0,
        stop_loss_price=96.0,
    )
    boosted = sizer.compute(
        balance=1000,
        entry_price=100,
        atr=2.0,
        direction="LONG",
        strategy_name="breakout",
        signal_strength=2.0,
        stop_loss_price=96.0,
    )
    assert breakout.rejected is False
    assert trend.rejected is False
    assert mean_rev.rejected is False
    assert boosted.rejected is False
    assert breakout.effective_risk_pct == 0.02
    assert trend.effective_risk_pct == 0.016
    assert mean_rev.effective_risk_pct == 0.014
    assert boosted.effective_risk_pct == 0.026
    assert breakout.size_usdt > trend.size_usdt > mean_rev.size_usdt
    assert boosted.size_usdt > breakout.size_usdt
    print("  [PASS]")


def test_stop_loss_calculator():
    print("\n=== 測試止損止盈計算 ===")
    calc = StopLossCalculator(db=None)
    r = calc.compute(entry_price=100, atr=2, direction="LONG")
    assert isinstance(r, StopLossResult)
    assert r.stop_loss < 100
    assert r.take_profit > 100
    r_short = calc.compute(entry_price=100, atr=2, direction="SHORT")
    assert r_short.stop_loss > 100
    assert r_short.take_profit < 100
    print(f"  LONG sl={r.stop_loss} tp={r.take_profit}")
    print(f"  SHORT sl={r_short.stop_loss} tp={r_short.take_profit}")
    print("  [PASS]")


def test_stop_loss_calculator_mean_reversion_profile():
    print("\n=== 測試 mean_reversion 專屬出場模板 ===")
    calc = StopLossCalculator(db=None)
    result = calc.compute(
        entry_price=100,
        atr=2,
        direction="LONG",
        strategy_name="mean_reversion",
    )
    assert result.rejected is False
    assert result.stop_loss == 97.5
    assert result.tp1 == 102.0
    assert result.tp2 == 103.6
    assert result.tp3 == 0.0
    assert result.take_profit == result.tp2
    print("  [PASS]")


def test_stop_loss_calculator_breakout_and_trend_profiles_differ():
    print("\n=== 測試 breakout / trend_following 出場模板拆分 ===")
    calc = StopLossCalculator(db=None)
    breakout = calc.compute(
        entry_price=100,
        atr=2,
        direction="LONG",
        strategy_name="breakout_retest",
    )
    trend = calc.compute(
        entry_price=100,
        atr=2,
        direction="LONG",
        strategy_name="trend_following",
    )
    assert breakout.rejected is False
    assert trend.rejected is False
    assert breakout.stop_loss == 96.0
    assert trend.stop_loss == 97.0
    assert breakout.tp1 == 103.0
    assert breakout.tp2 == 106.0
    assert breakout.tp3 == 109.0
    assert trend.tp1 == 104.0
    assert trend.tp2 == 107.0
    assert trend.tp3 == 110.0
    assert breakout.tp3 < trend.tp3
    print("  [PASS]")


def test_structure_levels_long():
    print("\n=== 測試結構型出場層級 ===")
    df = pd.DataFrame(
        {
            "open": [100, 101, 102, 104, 103, 105, 107, 106, 108, 110],
            "high": [101, 102, 103, 105, 104, 107, 108, 109, 111, 112],
            "low": [99, 100, 101, 102, 101, 103, 105, 104, 106, 108],
            "close": [100, 102, 103, 103, 104, 106, 106, 108, 110, 111],
        }
    )
    levels = compute_structure_levels(df, entry_price=106, direction="LONG")
    assert levels.stop_loss is not None
    assert levels.stop_loss < 106
    assert levels.tp1 is not None
    assert levels.tp1 > 106
    print("  [PASS]")


def test_structure_stop_floor_mult_mapping() -> None:
    print("\n=== 測試結構止損 ATR floor 對應 ===")
    assert get_structure_stop_floor_mult("breakout") == 2.0
    assert get_structure_stop_floor_mult("breakout_retest") == 2.0
    assert get_structure_stop_floor_mult("trend_following") == 1.2
    assert get_structure_stop_floor_mult("mean_reversion") == 0.8
    assert get_structure_stop_floor_mult("other") is None
    print("  [PASS]")


def test_exit_profile_family_mapping() -> None:
    print("\n=== 測試 exit profile strategy family 對應 ===")
    assert normalize_strategy_family("breakout_retest") == "breakout"
    assert get_exit_profile("breakout_retest").family == "breakout"
    assert get_exit_profile("trend_following").family == "trend_following"
    assert get_exit_profile("mean_reversion").tp2_final_exit is True
    print("  [PASS]")


def test_daily_limits_checker():
    print("\n=== 測試每日熔斷 ===")
    db = MagicMock()
    db.get_risk_params.return_value = {"max_daily_loss": 0.05, "max_drawdown": 0.15, "daily_profit_target": 0.0}
    db.get_daily_pnl.return_value = 0.0
    checker = DailyLimitsChecker(db)
    result = checker.can_open(current_balance=300)
    assert isinstance(result, DailyLimitsResult)
    assert result.can_open is True

    db.get_daily_pnl.return_value = -20.0  # 超過 300*0.05=15
    result2 = checker.can_open(current_balance=300)
    assert result2.can_open is False
    assert "今日虧損" in result2.reason or "上限" in result2.reason

    # 獲利達標鎖利：今日獲利 >= 當日起始權益 × daily_profit_target → 不開新倉
    db.get_risk_params.return_value = {"max_daily_loss": 0.05, "max_drawdown": 0.15, "daily_profit_target": 0.10}
    db.get_daily_pnl.return_value = 600.0  # 當日起始 5000，現在 5600，600 >= 5000*0.1=500
    result3 = checker.can_open(current_balance=5600)
    assert result3.can_open is False
    assert "獲利" in result3.reason or "鎖利" in result3.reason
    print("  [PASS]")


def test_cooldown_checker():
    print("\n=== 測試連虧冷卻 ===")
    db = MagicMock()
    db.get_risk_params.return_value = {
        "max_consecutive_losses": 3,
        "cool_down_after_loss_sec": 300,
    }
    db.get_recent_closed_trades.return_value = []
    checker = CooldownChecker(db)
    result = checker.can_open()
    assert isinstance(result, CooldownResult)
    assert result.can_open is True
    print("  [PASS]")


def test_risk_manager_integration():
    print("\n=== 測試 RiskManager 整合 ===")
    db = MagicMock()
    db.get_risk_params.return_value = {
        "max_risk_per_trade": 0.02,
        "min_notional_value": 10,
        "max_open_positions": "auto",
        "max_leverage": 5,
        "stop_loss_atr_mult": 1.5,
        "take_profit_atr_mult": 2.25,
        "min_risk_reward": 1.5,
        "max_daily_loss": 0.05,
        "max_drawdown": 0.15,
        "max_consecutive_losses": 3,
        "cool_down_after_loss_sec": 300,
    }
    db.get_daily_pnl.return_value = 0.0
    db.get_open_trades.return_value = []
    db.get_recent_closed_trades.return_value = []

    manager = RiskManager(db)
    sig = TradeSignal(
        symbol="BTCUSDT", timeframe="15m", signal_type="LONG",
        strength=0.8, strategy_name="trend_following", indicators={},
    )
    risk_result = manager.evaluate(sig, current_balance=300, entry_price=100, atr=2.0, open_trades_count=0)
    assert isinstance(risk_result, RiskCheckResult)
    if risk_result.passed:
        assert risk_result.size_usdt >= 0
        assert risk_result.stop_loss > 0
        assert risk_result.take_profit > 0
    print(f"  risk result: passed={risk_result.passed}, reason={risk_result.reason}")
    print("  [PASS]")


def test_risk_manager_uses_mean_reversion_profile():
    print("\n=== 測試 RiskManager 套用 mean_reversion 模板 ===")
    db = MagicMock()
    db.get_risk_params.return_value = {
        "max_risk_per_trade": 0.02,
        "min_notional_value": 10,
        "max_open_positions": "auto",
        "max_leverage": 5,
        "stop_loss_atr_mult": 1.5,
        "take_profit_atr_mult": 2.25,
        "min_risk_reward": 1.5,
        "mean_reversion_stop_loss_atr_mult": 1.25,
        "mean_reversion_tp1_atr_mult": 1.0,
        "mean_reversion_tp2_atr_mult": 1.8,
        "mean_reversion_min_risk_reward": 1.2,
        "max_daily_loss": 0.05,
        "max_drawdown": 0.15,
        "max_consecutive_losses": 3,
        "cool_down_after_loss_sec": 300,
    }
    db.get_daily_pnl.return_value = 0.0
    db.get_recent_closed_trades.return_value = []

    manager = RiskManager(db)
    sig = TradeSignal(
        symbol="BTCUSDT",
        timeframe="15m",
        signal_type="LONG",
        strength=0.8,
        strategy_name="mean_reversion",
        indicators={},
    )
    risk_result = manager.evaluate(
        sig,
        current_balance=300,
        entry_price=100,
        atr=2.0,
        open_trades_count=0,
    )
    assert risk_result.passed is True
    assert risk_result.stop_loss == 97.5
    assert risk_result.tp1 == 102.0
    assert risk_result.tp2 == 103.6
    assert risk_result.tp3 == 0.0
    assert risk_result.take_profit == 103.6
    print("  [PASS]")


def test_stop_loss_calculator_uses_structure_when_available():
    print("\n=== 測試風控優先使用結構位 ===")
    calc = StopLossCalculator(db=None)
    df = pd.DataFrame(
        {
            "open": [100, 101, 102, 103, 104, 106, 108, 109, 108, 110, 111, 112],
            "high": [101, 102, 103, 104, 106, 108, 109, 110, 110, 112, 113, 115],
            "low": [99, 100, 101, 102, 103, 105, 107, 108, 107.8, 109, 110, 111],
            "close": [100, 101.5, 102.5, 103.5, 105.5, 107.5, 108.5, 108.8, 109.5, 111, 112, 114],
        }
    )
    result = calc.compute(
        entry_price=110,
        atr=2,
        direction="LONG",
        strategy_name="trend_following",
        structure_df=df,
    )
    assert result.rejected is False
    assert result.stop_loss < 110
    assert result.tp1 > 110
    print("  [PASS]")


def test_stop_loss_calculator_applies_structure_floor_for_breakout_long(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    print("\n=== 測試 breakout 結構止損套用最小 ATR floor ===")
    calc = StopLossCalculator(db=None)
    monkeypatch.setattr(
        "core.risk.stop_loss.compute_structure_levels",
        lambda *args, **kwargs: StructureLevels(
            stop_loss=1.3210,
            tp1=1.3351,
            tp2=1.3531,
            tp3=1.3730,
            source="structure",
        ),
    )
    df = pd.DataFrame({"open": [1.32], "high": [1.324], "low": [1.318], "close": [1.323]})
    result = calc.compute(
        entry_price=1.323,
        atr=0.0088,
        direction="LONG",
        symbol="NEARUSDT",
        strategy_name="breakout",
        structure_df=df,
        min_risk_reward=1.4,
    )
    expected_floor = round(1.323 - (2.0 * 0.0088), 4)
    assert result.rejected is False
    assert result.stop_loss == expected_floor
    assert result.sl_atr_mult == 2.0
    assert result.structure_stop_floor_triggered is True
    print("  [PASS]")


def test_stop_loss_calculator_applies_structure_floor_for_breakout_short(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    print("\n=== 測試 breakout SHORT 結構止損套用最小 ATR floor ===")
    calc = StopLossCalculator(db=None)
    monkeypatch.setattr(
        "core.risk.stop_loss.compute_structure_levels",
        lambda *args, **kwargs: StructureLevels(
            stop_loss=100.5,
            tp1=98.0,
            tp2=97.0,
            tp3=96.0,
            source="structure",
        ),
    )
    df = pd.DataFrame({"open": [99.0], "high": [100.0], "low": [98.0], "close": [98.5]})
    result = calc.compute(
        entry_price=99.0,
        atr=2.0,
        direction="SHORT",
        symbol="BTCUSDT",
        strategy_name="breakout",
        structure_df=df,
        min_risk_reward=0.7,
    )
    expected_floor = round(99.0 + (2.0 * 2.0), 4)
    assert result.rejected is False
    assert result.stop_loss == expected_floor
    assert result.sl_atr_mult == 2.0
    assert result.structure_stop_floor_triggered is True
    print("  [PASS]")


def test_stop_loss_calculator_atr_fallback_unchanged_without_structure() -> None:
    print("\n=== 測試 ATR fallback 路徑不受 structure floor 影響 ===")
    calc = StopLossCalculator(db=None)
    result = calc.compute(
        entry_price=100,
        atr=2,
        direction="LONG",
        symbol="BTCUSDT",
        strategy_name="breakout",
        structure_df=None,
    )
    assert result.rejected is False
    assert result.stop_loss == 96.0
    assert result.sl_atr_mult == 2.0
    assert result.structure_stop_floor_triggered is False
    print("  [PASS]")


def main():
    print("=" * 60)
    print("TradingBrain Phase 5 - 風險管理核心測試")
    print("=" * 60)
    test_parse_max_open_positions()
    test_position_sizer()
    test_position_sizer_prefers_structure_stop_distance()
    test_position_sizer_applies_strategy_weight_and_signal_strength()
    test_stop_loss_calculator()
    test_stop_loss_calculator_mean_reversion_profile()
    test_stop_loss_calculator_breakout_and_trend_profiles_differ()
    test_structure_levels_long()
    test_structure_stop_floor_mult_mapping()
    test_exit_profile_family_mapping()
    test_stop_loss_calculator_uses_structure_when_available()
    test_stop_loss_calculator_applies_structure_floor_for_breakout_long()
    test_stop_loss_calculator_applies_structure_floor_for_breakout_short()
    test_stop_loss_calculator_atr_fallback_unchanged_without_structure()
    test_daily_limits_checker()
    test_cooldown_checker()
    test_risk_manager_integration()
    test_risk_manager_uses_mean_reversion_profile()
    print("\n" + "=" * 60)
    print("ALL TESTS PASSED!")
    print("=" * 60)


if __name__ == "__main__":
    main()
