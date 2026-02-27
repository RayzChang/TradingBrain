"""
第五階段測試 — 風險管理核心

驗證: 倉位計算、止損止盈、每日熔斷、連虧冷卻、RiskManager 整合
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.risk.position_sizer import PositionSizer, PositionSizeResult, _parse_max_open_positions
from core.risk.stop_loss import StopLossCalculator, StopLossResult
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


def main():
    print("=" * 60)
    print("TradingBrain Phase 5 - 風險管理核心測試")
    print("=" * 60)
    test_parse_max_open_positions()
    test_position_sizer()
    test_stop_loss_calculator()
    test_daily_limits_checker()
    test_cooldown_checker()
    test_risk_manager_integration()
    print("\n" + "=" * 60)
    print("ALL TESTS PASSED!")
    print("=" * 60)


if __name__ == "__main__":
    main()
