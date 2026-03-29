import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.execution.position_manager import (
    OBSERVATION_TIMEOUT_SEC,
    SYNC_DUST_NOTIONAL_USDT,
    run_position_check,
    sync_positions_from_exchange,
)


async def _run_soft_stop_after_two_closes() -> None:
    db = MagicMock()
    db.get_open_trades.return_value = [
        {
            "id": 1,
            "symbol": "BTCUSDT",
            "side": "LONG",
            "entry_price": 100.0,
            "quantity": 1.0,
            "current_quantity": 1.0,
            "original_quantity": 1.0,
            "soft_stop_loss": 99.0,
            "hard_stop_loss": 95.0,
            "soft_stop_required_closes": 2,
            "tp_stage": 0,
            "highest_price": 101.0,
            "lowest_price": 99.0,
            "atr_at_entry": 2.0,
            "strategy_name": "breakout_retest",
            "status": "OPEN",
        }
    ]

    with patch("core.execution.position_manager._full_close", new=AsyncMock()) as full_close:
        await run_position_check(
            db,
            client=None,
            prices={"BTCUSDT": 98.7},
            recent_candles={
                "BTCUSDT": {
                    "1m": [
                        {"open": 99.5, "close": 99.4, "low": 99.2, "high": 100.2},
                        {"open": 98.9, "close": 98.8, "low": 98.7, "high": 99.5},
                        {"open": 98.8, "close": 98.7, "low": 98.6, "high": 99.0},
                    ],
                    "5m": [
                        {"open": 98.9, "close": 98.8, "low": 98.6, "high": 99.5},
                        {"open": 98.8, "close": 98.7, "low": 98.5, "high": 98.9},
                    ],
                }
            },
        )

    full_close.assert_awaited_once()
    # V10: observation mode uses OBSERVATION_STOP instead of SOFT_STOP
    assert full_close.await_args.args[4] == "OBSERVATION_STOP"


def test_soft_stop_requires_confirmed_closes():
    asyncio.run(_run_soft_stop_after_two_closes())


async def _run_hard_stop_immediate_exit() -> None:
    db = MagicMock()
    db.get_open_trades.return_value = [
        {
            "id": 1,
            "symbol": "ETHUSDT",
            "side": "LONG",
            "entry_price": 100.0,
            "quantity": 1.0,
            "current_quantity": 1.0,
            "original_quantity": 1.0,
            "soft_stop_loss": 99.0,
            "hard_stop_loss": 97.0,
            "soft_stop_required_closes": 2,
            "tp_stage": 0,
            "highest_price": 101.0,
            "lowest_price": 99.0,
            "atr_at_entry": 2.0,
            "strategy_name": "trend_following",
            "status": "OPEN",
        }
    ]

    with patch("core.execution.position_manager._full_close", new=AsyncMock()) as full_close:
        await run_position_check(
            db,
            client=None,
            prices={"ETHUSDT": 96.8},
            recent_candles={
                "ETHUSDT": {
                    "1m": [
                        {"close": 99.2, "low": 99.0, "high": 100.0},
                        {"close": 98.8, "low": 98.7, "high": 99.3},
                    ],
                    "5m": [],
                }
            },
        )

    full_close.assert_awaited_once()
    assert full_close.await_args.args[4] == "HARD_STOP"


def test_hard_stop_still_exits_immediately():
    asyncio.run(_run_hard_stop_immediate_exit())


async def _run_soft_stop_with_five_minute_backup() -> None:
    db = MagicMock()
    db.get_open_trades.return_value = [
        {
            "id": 2,
            "symbol": "SOLUSDT",
            "side": "LONG",
            "entry_price": 100.0,
            "quantity": 1.0,
            "current_quantity": 1.0,
            "original_quantity": 1.0,
            "soft_stop_loss": 99.0,
            "hard_stop_loss": 95.0,
            "soft_stop_required_closes": 2,
            "tp_stage": 0,
            "highest_price": 101.0,
            "lowest_price": 99.0,
            "atr_at_entry": 2.0,
            "strategy_name": "trend_following",
            "status": "OPEN",
        }
    ]

    with patch("core.execution.position_manager._full_close", new=AsyncMock()) as full_close:
        await run_position_check(
            db,
            client=None,
            prices={"SOLUSDT": 98.9},
            recent_candles={
                "SOLUSDT": {
                    "1m": [
                        {"open": 99.5, "close": 99.4, "low": 99.2, "high": 100.2},
                        {"open": 99.2, "close": 99.1, "low": 99.0, "high": 99.5},
                    ],
                    "5m": [
                        {"open": 98.9, "close": 98.7, "low": 98.6, "high": 98.95},
                        {"open": 98.7, "close": 98.5, "low": 98.4, "high": 98.8},
                    ],
                }
            },
        )

    full_close.assert_awaited_once()
    # V10: observation mode uses OBSERVATION_STOP instead of SOFT_STOP
    assert full_close.await_args.args[4] == "OBSERVATION_STOP"


def test_soft_stop_accepts_single_five_minute_close_break():
    asyncio.run(_run_soft_stop_with_five_minute_backup())


async def _run_sync_auto_closes_dust_position() -> None:
    db = MagicMock()
    db.get_open_trades.return_value = []

    client = MagicMock()
    client.get_positions = AsyncMock(
        return_value=[
            {
                "symbol": "DOGEUSDT",
                "positionAmt": "-1",
                "entryPrice": "0.0905",
                "leverage": "20",
            }
        ]
    )
    client.close_position_market = AsyncMock(return_value=123456)

    await sync_positions_from_exchange(db, client)

    client.close_position_market.assert_awaited_once_with("DOGEUSDT", "BUY", 1.0)
    db.insert_trade.assert_not_called()


def test_sync_auto_closes_dust_positions_instead_of_importing():
    asyncio.run(_run_sync_auto_closes_dust_position())


async def _run_sync_imports_position_when_dust_close_fails() -> None:
    db = MagicMock()
    db.get_open_trades.return_value = []

    client = MagicMock()
    client.get_positions = AsyncMock(
        return_value=[
            {
                "symbol": "UNIUSDT",
                "positionAmt": "-1",
                "entryPrice": str(SYNC_DUST_NOTIONAL_USDT / 2),
                "leverage": "20",
            }
        ]
    )
    client.close_position_market = AsyncMock(return_value=None)

    await sync_positions_from_exchange(db, client)

    client.close_position_market.assert_awaited_once()
    db.insert_trade.assert_called_once()


def test_sync_imports_dust_position_if_auto_close_fails():
    asyncio.run(_run_sync_imports_position_when_dust_close_fails())


async def _run_observation_timeout_closes_position() -> None:
    """CONSOLIDATING for > 30 minutes triggers OBSERVATION_STOP_TIMEOUT."""
    db = MagicMock()
    db.get_open_trades.return_value = [
        {
            "id": 99,
            "symbol": "BTCUSDT",
            "side": "LONG",
            "entry_price": 100.0,
            "quantity": 1.0,
            "current_quantity": 1.0,
            "original_quantity": 1.0,
            "soft_stop_loss": 99.0,
            "hard_stop_loss": 95.0,
            "soft_stop_required_closes": 2,
            "tp_stage": 0,
            "highest_price": 101.0,
            "lowest_price": 99.0,
            "atr_at_entry": 2.0,
            "strategy_name": "trend_following",
            "status": "OPEN",
        }
    ]

    # Candles that produce CONSOLIDATING (price near soft stop, not confirmed breakdown)
    consolidating_candles = {
        "BTCUSDT": {
            "1m": [
                {"open": 99.1, "close": 99.0, "low": 98.9, "high": 99.2},
                {"open": 99.0, "close": 98.9, "low": 98.8, "high": 99.1},
            ],
            "5m": [
                {"open": 99.1, "close": 99.0, "low": 98.8, "high": 99.3},
                {"open": 99.0, "close": 99.05, "low": 98.9, "high": 99.2},
            ],
        }
    }

    # Pre-seed observation_state with a timestamp 31 minutes ago
    obs_state = {"99": datetime.now(timezone.utc) - timedelta(seconds=OBSERVATION_TIMEOUT_SEC + 60)}

    with patch("core.execution.position_manager._full_close", new=AsyncMock()) as full_close:
        await run_position_check(
            db,
            client=None,
            prices={"BTCUSDT": 98.95},
            recent_candles=consolidating_candles,
            observation_state=obs_state,
        )

    full_close.assert_awaited_once()
    assert full_close.await_args.args[4] == "OBSERVATION_STOP_TIMEOUT"
    # Key should be cleaned up after close
    assert "99" not in obs_state


def test_observation_timeout_closes_position():
    asyncio.run(_run_observation_timeout_closes_position())
