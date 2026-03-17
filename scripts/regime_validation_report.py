"""Summarize daily regime-switch counts from analysis_logs."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger

from config.settings import APP_TIMEZONE
from database.db_manager import DatabaseManager

logger.remove()

PHASE_1_GATE_EXCLUDED_SYMBOLS = {"APTUSDT"}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate Phase 1 regime-switch validation stats."
    )
    parser.add_argument(
        "--date",
        help="Local report date in YYYY-MM-DD. Defaults to yesterday in app timezone.",
    )
    return parser.parse_args()


def _target_date(raw_date: str | None) -> date:
    if raw_date:
        return date.fromisoformat(raw_date)
    return datetime.now(APP_TIMEZONE).date() - timedelta(days=1)


def _local_day_bounds(target: date) -> tuple[str, str]:
    local_start = datetime(
        target.year, target.month, target.day, 0, 0, 0, tzinfo=APP_TIMEZONE
    )
    local_end = local_start + timedelta(days=1)
    return (
        local_start.astimezone(timezone.utc).isoformat(),
        local_end.astimezone(timezone.utc).isoformat(),
    )


def _extract_regime(snapshot_text: str | None) -> str | None:
    if not snapshot_text:
        return None
    try:
        snapshot = json.loads(snapshot_text)
    except json.JSONDecodeError:
        return None
    regime = snapshot.get("market_regime")
    return regime if isinstance(regime, str) else None


def build_report(target: date) -> dict:
    db = DatabaseManager()
    start_at, end_at = _local_day_bounds(target)
    rows = db.execute(
        "SELECT symbol, created_at, market_snapshot "
        "FROM analysis_logs "
        "WHERE strategy_name='regime_monitor' AND timeframe='15m' "
        "AND created_at >= ? AND created_at < ? "
        "ORDER BY symbol, created_at ASC",
        (start_at, end_at),
    )

    regimes_by_symbol: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        regime = _extract_regime(row["market_snapshot"])
        if regime:
            regimes_by_symbol[row["symbol"]].append(regime)

    switch_counts: dict[str, int] = {}
    for symbol, regimes in regimes_by_symbol.items():
        switches = 0
        prev = None
        for regime in regimes:
            if prev is not None and regime != prev:
                switches += 1
            prev = regime
        switch_counts[symbol] = switches

    gate_counts = {
        symbol: count
        for symbol, count in switch_counts.items()
        if symbol not in PHASE_1_GATE_EXCLUDED_SYMBOLS
    }

    median_switches = median(switch_counts.values()) if switch_counts else 0
    max_symbol = max(switch_counts, key=switch_counts.get) if switch_counts else None
    gate_median_switches = median(gate_counts.values()) if gate_counts else 0
    gate_max_symbol = max(gate_counts, key=gate_counts.get) if gate_counts else None

    return {
        "report_date": target.isoformat(),
        "symbols_observed": len(regimes_by_symbol),
        "median_switches": median_switches,
        "max_switch_symbol": max_symbol,
        "max_switch_count": switch_counts.get(max_symbol, 0) if max_symbol else 0,
        "per_symbol": dict(sorted(switch_counts.items())),
        "phase_1_gate_excluded_symbols": sorted(PHASE_1_GATE_EXCLUDED_SYMBOLS),
        "phase_1_gate_scope": "exclude_high_beta_symbols",
        "gate_symbols_observed": len(gate_counts),
        "gate_median_switches": gate_median_switches,
        "gate_max_switch_symbol": gate_max_symbol,
        "gate_max_switch_count": gate_counts.get(gate_max_symbol, 0) if gate_max_symbol else 0,
        "gate_per_symbol": dict(sorted(gate_counts.items())),
        "passes_phase_1_gate": bool(
            gate_counts
            and all(count <= 8 for count in gate_counts.values())
            and gate_median_switches <= 5
        ),
    }


if __name__ == "__main__":
    args = _parse_args()
    report = build_report(_target_date(args.date))
    print(json.dumps(report, ensure_ascii=False, indent=2))
