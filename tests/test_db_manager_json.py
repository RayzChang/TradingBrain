from pathlib import Path
import json

import numpy as np

from database.db_manager import DatabaseManager


def test_insert_signal_normalizes_numpy_bool_scalars(tmp_path: Path) -> None:
    db = DatabaseManager(tmp_path / "json_signal.db")

    signal_id = db.insert_signal(
        {
            "symbol": "SUIUSDT",
            "timeframe": "15m",
            "signal_type": "SHORT",
            "strength": 0.9,
            "strategy_name": "breakout",
            "indicators": {
                "extra_volume_confirmed": np.bool_(True),
                "adx_neg_dominant": np.bool_(False),
            },
            "was_vetoed": 0,
            "veto_reason": None,
            "was_executed": 0,
        }
    )

    rows = db.execute("SELECT indicators FROM signals WHERE id=?", (signal_id,))
    payload = json.loads(rows[0]["indicators"])
    assert payload["extra_volume_confirmed"] is True
    assert payload["adx_neg_dominant"] is False


def test_insert_analysis_log_normalizes_numpy_bool_scalars(tmp_path: Path) -> None:
    db = DatabaseManager(tmp_path / "json_analysis.db")

    row_id = db.insert_analysis_log(
        {
            "symbol": "SUIUSDT",
            "timeframe": "15m",
            "strategy_name": "breakout",
            "signal_generated": 1,
            "signal_type": "SHORT",
            "signal_strength": 0.9,
            "veto_passed": 1,
            "veto_reasons": None,
            "veto_details": None,
            "risk_passed": None,
            "risk_reason": None,
            "final_action": "PENDING_RISK",
            "market_snapshot": {
                "mtf_gate_passed": np.bool_(True),
                "breakout_retest_status": "pending",
            },
        }
    )

    rows = db.execute("SELECT market_snapshot FROM analysis_logs WHERE id=?", (row_id,))
    payload = json.loads(rows[0]["market_snapshot"])
    assert payload["mtf_gate_passed"] is True
    assert payload["breakout_retest_status"] == "pending"
