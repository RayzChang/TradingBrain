from __future__ import annotations

import json
import sys
import zipfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as main_module
from database.db_manager import DatabaseManager
from main import TradingBrain


def test_build_signal_decay_summary_mixes_db_and_log_markers(tmp_path, monkeypatch):
    db = DatabaseManager(tmp_path / "diagnostics.db")
    brain = TradingBrain.__new__(TradingBrain)
    brain.db = db

    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(main_module, "LOG_DIR", log_dir)

    report_date = datetime.now(main_module.APP_TIMEZONE).date().isoformat()
    zip_path = log_dir / f"trading_{report_date}.log.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            f"trading_{report_date}.log",
            "\n".join(
                [
                    "MTF_GATE_BLOCK: BTCUSDT no recommended direction",
                    "MTF_GATE_BLOCK: ETHUSDT no recommended direction",
                    "REGIME_GATE_BLOCK: SOLUSDT breakout market_regime=volatile",
                ]
            ),
        )

    rows = [
        {
            "symbol": "BTCUSDT",
            "timeframe": "15m",
            "strategy_name": "trend_following",
            "signal_generated": 1,
            "signal_type": "LONG",
            "signal_strength": 0.8,
            "veto_passed": 1,
            "final_action": "PENDING_RISK",
            "market_snapshot": {"stage": "candidate"},
        },
        {
            "symbol": "ETHUSDT",
            "timeframe": "15m",
            "strategy_name": "breakout",
            "signal_generated": 1,
            "signal_type": "SHORT",
            "signal_strength": 0.7,
            "veto_passed": 0,
            "final_action": "VETOED",
            "market_snapshot": {"stage": "candidate"},
        },
        {
            "symbol": "BTCUSDT",
            "timeframe": "1m_trigger",
            "strategy_name": "trend_following",
            "signal_generated": 1,
            "signal_type": "LONG",
            "signal_strength": 0.8,
            "veto_passed": 1,
            "final_action": "PENDING_TRIGGER",
            "market_snapshot": {"stage": "pending"},
        },
        {
            "symbol": "ETHUSDT",
            "timeframe": "1m_trigger",
            "strategy_name": "breakout",
            "signal_generated": 1,
            "signal_type": "SHORT",
            "signal_strength": 0.7,
            "veto_passed": 1,
            "final_action": "BREAKOUT_PENDING",
            "market_snapshot": {"stage": "pending"},
        },
        {
            "symbol": "BTCUSDT",
            "timeframe": "1m_trigger",
            "strategy_name": "trend_following",
            "signal_generated": 1,
            "signal_type": "LONG",
            "signal_strength": 0.8,
            "veto_passed": 1,
            "final_action": "TRIGGER_CONFIRMED",
            "market_snapshot": {"stage": "triggered"},
        },
        {
            "symbol": "ETHUSDT",
            "timeframe": "1m_trigger",
            "strategy_name": "breakout_retest",
            "signal_generated": 1,
            "signal_type": "SHORT",
            "signal_strength": 0.7,
            "veto_passed": 1,
            "final_action": "BREAKOUT_RETEST_HIT",
            "market_snapshot": {"stage": "retest"},
        },
        {
            "symbol": "ETHUSDT",
            "timeframe": "1m_trigger",
            "strategy_name": "breakout_retest",
            "signal_generated": 1,
            "signal_type": "SHORT",
            "signal_strength": 0.7,
            "veto_passed": 1,
            "final_action": "BREAKOUT_CONFIRMED",
            "market_snapshot": {"stage": "confirmed"},
        },
        {
            "symbol": "ADAUSDT",
            "timeframe": "1m_trigger",
            "strategy_name": "trend_following",
            "signal_generated": 1,
            "signal_type": "LONG",
            "signal_strength": 0.4,
            "veto_passed": 1,
            "final_action": "TRIGGER_EXPIRED",
            "market_snapshot": {"stage": "expired"},
        },
        {
            "symbol": "ETHUSDT",
            "timeframe": "1m_trigger",
            "strategy_name": "breakout_retest",
            "signal_generated": 1,
            "signal_type": "SHORT",
            "signal_strength": 0.7,
            "veto_passed": 1,
            "final_action": "MTF_RECHECK_BLOCK",
            "market_snapshot": {"stage": "recheck"},
        },
        {
            "symbol": "BTCUSDT",
            "timeframe": "1m_trigger",
            "strategy_name": "trend_following",
            "signal_generated": 1,
            "signal_type": "LONG",
            "signal_strength": 0.8,
            "veto_passed": 1,
            "risk_passed": 0,
            "final_action": "RISK_BLOCKED",
            "market_snapshot": {"stage": "risk"},
        },
        {
            "symbol": "XRPUSDT",
            "timeframe": "1m_trigger",
            "strategy_name": "mean_reversion",
            "signal_generated": 1,
            "signal_type": "LONG",
            "signal_strength": 0.6,
            "veto_passed": 1,
            "risk_passed": 1,
            "final_action": "EXECUTED",
            "market_snapshot": {"stage": "executed"},
        },
    ]
    for row in rows:
        db.insert_analysis_log(row)

    summary = brain._build_signal_decay_summary(day_offset=0, report_date=report_date)

    counts = summary["counts"]
    assert counts["candidate_signals"] == 5
    assert counts["regime_gate_blocked"] == 1
    assert counts["mtf_gate_blocked"] == 2
    assert counts["regime_gate_passed"] == 4
    assert counts["mtf_gate_passed"] == 2
    assert counts["veto_passed"] == 1
    assert counts["veto_blocked"] == 1
    assert counts["pending_created"] == 2
    assert counts["trigger_confirmed"] == 2
    assert counts["trigger_expired"] == 1
    assert counts["breakout_retest_hit"] == 1
    assert counts["breakout_confirmed"] == 1
    assert counts["mtf_recheck_blocked"] == 1
    assert counts["risk_blocked"] == 1
    assert counts["executed"] == 1
    assert summary["bottleneck"]["stage"] == "mtf_gate"
    assert summary["strategies"]["candidates"] == {
        "breakout": 1,
        "trend_following": 1,
    }
    assert summary["sides"]["executed"] == {"LONG": 1}


def test_append_daily_report_log_writes_signal_chain_section(tmp_path, monkeypatch):
    brain = TradingBrain.__new__(TradingBrain)
    monkeypatch.setattr(main_module, "LOG_DIR", tmp_path / "logs")

    payload = {
        "report_date": "2026-03-20",
        "timezone": "Asia/Bangkok",
        "mode": "testnet",
        "trades_count": 3,
        "daily_pnl": 42.5,
        "open_positions": 1,
        "exchange_balance": 5012.34,
        "generated_at": "2026-03-20T00:00:00+07:00",
        "signal_chain": {
            "counts": {
                "candidate_signals": 8,
                "regime_gate_passed": 6,
                "regime_gate_blocked": 2,
                "mtf_gate_passed": 5,
                "mtf_gate_blocked": 1,
                "veto_passed": 4,
                "veto_blocked": 1,
                "pending_created": 4,
                "trigger_confirmed": 2,
                "trigger_expired": 1,
                "mtf_recheck_blocked": 1,
                "risk_blocked": 0,
                "executed": 2,
                "breakout_retest_hit": 1,
                "breakout_confirmed": 1,
                "breakout_expired": 0,
            },
            "bottleneck": {"stage": "regime_gate", "blocked": 2},
            "strategies": {
                "candidates": {"breakout": 2, "trend_following": 1},
                "executed": {"breakout_retest": 1, "mean_reversion": 1},
            },
            "sides": {
                "candidates": {"LONG": 2, "SHORT": 1},
                "executed": {"SHORT": 1, "LONG": 1},
            },
        },
    }

    brain._append_daily_report_log(payload)

    daily_file = (tmp_path / "logs" / "daily_reports" / "2026-03-20.md")
    history_file = (tmp_path / "logs" / "daily_reports" / "history.jsonl")
    assert daily_file.exists()
    content = daily_file.read_text(encoding="utf-8")
    assert "Signal Chain Summary" in content
    assert "candidate_signals: 8" in content
    assert "bottleneck_stage: regime_gate" in content
    assert "candidate_strategies: breakout×2, trend_following×1" in content

    history_rows = history_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(history_rows) == 1
    history_payload = json.loads(history_rows[0])
    assert history_payload["signal_chain"]["counts"]["executed"] == 2
