"""
SQLite database manager.

Uses WAL mode for better concurrent read/write behavior and provides a
centralized CRUD layer for the rest of the application.
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Generator, Optional
from zoneinfo import ZoneInfo

from loguru import logger

from config.settings import APP_TIMEZONE, DB_PATH
from database.models import INDEXES, TABLES


class DatabaseManager:
    """SQLite database manager running in WAL mode."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path or DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Initialize tables, indexes, and lightweight schema migrations."""
        with self.get_connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA busy_timeout=5000;")
            conn.execute("PRAGMA synchronous=NORMAL;")

            for table_name, create_sql in TABLES.items():
                conn.execute(create_sql)
                logger.debug(f"Table ensured: {table_name}")

            for index_sql in INDEXES:
                conn.execute(index_sql)

            migration_columns = [
                ("trades", "exchange_order_id", "TEXT"),
                ("trades", "tp1_price", "REAL"),
                ("trades", "tp2_price", "REAL"),
                ("trades", "tp3_price", "REAL"),
                ("trades", "soft_stop_loss", "REAL"),
                ("trades", "hard_stop_loss", "REAL"),
                ("trades", "soft_stop_required_closes", "INTEGER NOT NULL DEFAULT 0"),
                ("trades", "stop_zone_low", "REAL"),
                ("trades", "stop_zone_high", "REAL"),
                ("trades", "tp1_zone_low", "REAL"),
                ("trades", "tp1_zone_high", "REAL"),
                ("trades", "tp2_zone_low", "REAL"),
                ("trades", "tp2_zone_high", "REAL"),
                ("trades", "tp3_zone_low", "REAL"),
                ("trades", "tp3_zone_high", "REAL"),
                ("trades", "tp_stage", "INTEGER NOT NULL DEFAULT 0"),
                ("trades", "original_quantity", "REAL"),
                ("trades", "current_quantity", "REAL"),
                ("trades", "highest_price", "REAL"),
                ("trades", "lowest_price", "REAL"),
                ("trades", "atr_at_entry", "REAL"),
                ("trades", "effective_risk_pct", "REAL"),
                ("trades", "sl_atr_mult", "REAL"),
                ("trades", "structure_stop_floor_triggered", "INTEGER NOT NULL DEFAULT 0"),
            ]
            for table, column, column_type in migration_columns:
                try:
                    conn.execute(
                        f"ALTER TABLE {table} ADD COLUMN {column} {column_type}"
                    )
                except sqlite3.OperationalError as exc:
                    if "duplicate column" not in str(exc).lower():
                        raise

            conn.commit()

        logger.info(f"Database initialized at {self.db_path} (WAL mode)")

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Yield a SQLite connection with row access enabled."""
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def execute(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        """Execute SQL and return fetched rows."""
        with self.get_connection() as conn:
            cursor = conn.execute(sql, params)
            conn.commit()
            return cursor.fetchall()

    def execute_many(self, sql: str, params_list: list[tuple]) -> None:
        """Execute a SQL statement against many parameter tuples."""
        with self.get_connection() as conn:
            conn.executemany(sql, params_list)
            conn.commit()

    # === Trade operations ===

    def insert_trade(self, trade_data: dict) -> int:
        """Insert a trade and return its database id."""
        fields = ", ".join(trade_data.keys())
        placeholders = ", ".join(["?"] * len(trade_data))
        sql = f"INSERT INTO trades ({fields}) VALUES ({placeholders})"

        with self.get_connection() as conn:
            cursor = conn.execute(sql, tuple(trade_data.values()))
            conn.commit()
            trade_id = cursor.lastrowid
            logger.info(f"Trade inserted: id={trade_id}, {trade_data.get('symbol')}")
            return trade_id

    def close_trade(
        self,
        trade_id: int,
        exit_price: float,
        pnl: float,
        pnl_pct: float,
        fee: float,
        exit_reason: str,
    ) -> None:
        """Mark an open trade as closed."""
        sql = """
            UPDATE trades
            SET exit_price=?, pnl=?, pnl_pct=?, fee=?,
                exit_reason=?, status='CLOSED', closed_at=?
            WHERE id=?
        """
        now = datetime.now(timezone.utc).isoformat()
        self.execute(sql, (exit_price, pnl, pnl_pct, fee, exit_reason, now, trade_id))
        logger.info(f"Trade closed: id={trade_id}, pnl={pnl:.2f}")

    def get_open_trades(self) -> list[dict]:
        """Return all currently open trades."""
        rows = self.execute("SELECT * FROM trades WHERE status='OPEN'")
        return [dict(row) for row in rows]

    @staticmethod
    def _local_day_bounds(
        tz: ZoneInfo | None = None,
        day_offset: int = 0,
    ) -> tuple[str, str]:
        """Return UTC ISO bounds for a local calendar day."""
        tz = tz or APP_TIMEZONE
        local_now = datetime.now(tz) + timedelta(days=day_offset)
        local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        local_end = local_start + timedelta(days=1)
        return (
            local_start.astimezone(timezone.utc).isoformat(),
            local_end.astimezone(timezone.utc).isoformat(),
        )

    def get_trades_today(
        self,
        *,
        tz: ZoneInfo | None = None,
        day_offset: int = 0,
    ) -> list[dict]:
        """Return trades opened within the selected local calendar day."""
        start_at, end_at = self._local_day_bounds(tz, day_offset)
        rows = self.execute(
            "SELECT * FROM trades WHERE opened_at >= ? AND opened_at < ? ORDER BY opened_at DESC",
            (start_at, end_at),
        )
        return [dict(row) for row in rows]

    def get_daily_pnl(
        self,
        *,
        tz: ZoneInfo | None = None,
        day_offset: int = 0,
    ) -> float:
        """Return realized PnL for the selected local calendar day."""
        start_at, end_at = self._local_day_bounds(tz, day_offset)
        rows = self.execute(
            "SELECT COALESCE(SUM(pnl), 0) AS total FROM trades "
            "WHERE status='CLOSED' AND closed_at >= ? AND closed_at < ?",
            (start_at, end_at),
        )
        return rows[0]["total"] if rows else 0.0

    def get_total_realized_pnl(self) -> float:
        """Return cumulative realized PnL across all closed trades."""
        rows = self.execute(
            "SELECT COALESCE(SUM(pnl), 0) AS total FROM trades WHERE status='CLOSED'"
        )
        return rows[0]["total"] if rows else 0.0

    def get_recent_closed_trades(self, limit: int = 20) -> list[dict]:
        """Return the most recent closed trades for cooldown logic."""
        rows = self.execute(
            "SELECT * FROM trades WHERE status='CLOSED' ORDER BY closed_at DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in rows]

    # === Risk parameters ===

    def get_risk_params(self) -> dict[str, Any]:
        """Return all persisted risk parameters."""
        rows = self.execute("SELECT param_name, param_value FROM risk_params")
        result: dict[str, Any] = {}
        for row in rows:
            try:
                result[row["param_name"]] = json.loads(row["param_value"])
            except (json.JSONDecodeError, TypeError):
                result[row["param_name"]] = row["param_value"]
        return result

    def set_risk_param(
        self, name: str, value: Any, changed_by: str = "user"
    ) -> None:
        """Upsert a risk parameter and write a history row."""
        value_str = json.dumps(value)

        old_rows = self.execute(
            "SELECT param_value FROM risk_params WHERE param_name=?",
            (name,),
        )
        old_value = old_rows[0]["param_value"] if old_rows else None

        self.execute(
            "INSERT INTO risk_params (param_name, param_value, updated_at) "
            "VALUES (?, ?, datetime('now')) "
            "ON CONFLICT(param_name) DO UPDATE SET "
            "param_value=?, updated_at=datetime('now')",
            (name, value_str, value_str),
        )

        self.execute(
            "INSERT INTO risk_history (param_name, old_value, new_value, changed_by) "
            "VALUES (?, ?, ?, ?)",
            (name, old_value, value_str, changed_by),
        )
        logger.info(f"Risk param updated: {name} = {value} (by {changed_by})")

    def load_risk_defaults(self, defaults: dict) -> None:
        """Load default risk parameters if they are not already present."""
        existing = self.get_risk_params()
        for name, value in defaults.items():
            if name not in existing:
                self.set_risk_param(name, value, changed_by="system_default")

    # === Signal operations ===

    def insert_signal(self, signal_data: dict) -> int:
        """Persist a generated trade signal."""
        if "indicators" in signal_data and isinstance(signal_data["indicators"], dict):
            signal_data["indicators"] = json.dumps(signal_data["indicators"])

        fields = ", ".join(signal_data.keys())
        placeholders = ", ".join(["?"] * len(signal_data))
        sql = f"INSERT INTO signals ({fields}) VALUES ({placeholders})"

        with self.get_connection() as conn:
            cursor = conn.execute(sql, tuple(signal_data.values()))
            conn.commit()
            return cursor.lastrowid

    def get_recent_signals(self, limit: int = 50) -> list[dict]:
        """Return recent signals for the dashboard."""
        rows = self.execute(
            "SELECT * FROM signals ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        result = []
        for row in rows:
            item = dict(row)
            if item.get("indicators") and isinstance(item["indicators"], str):
                try:
                    item["indicators"] = json.loads(item["indicators"])
                except (json.JSONDecodeError, TypeError):
                    pass
            result.append(item)
        return result

    # === Market info ===

    def save_market_info(
        self, info_type: str, data: Any, symbol: Optional[str] = None
    ) -> None:
        """Persist market metadata such as funding or sentiment."""
        data_str = json.dumps(data) if not isinstance(data, str) else data
        self.execute(
            "INSERT INTO market_info (info_type, symbol, data) VALUES (?, ?, ?)",
            (info_type, symbol, data_str),
        )

    def get_latest_market_info(self, info_type: str) -> Optional[dict]:
        """Return the newest market-info record for a given type."""
        rows = self.execute(
            "SELECT * FROM market_info WHERE info_type=? "
            "ORDER BY fetched_at DESC LIMIT 1",
            (info_type,),
        )
        if not rows:
            return None

        row = dict(rows[0])
        try:
            row["data"] = json.loads(row["data"])
        except (json.JSONDecodeError, TypeError):
            pass
        return row

    # === Scheduler status ===

    def update_scheduler_status(
        self, task_name: str, status: str, error: Optional[str] = None
    ) -> None:
        """Update execution metadata for a scheduled task."""
        now = datetime.now(timezone.utc).isoformat()
        if error:
            self.execute(
                "INSERT INTO scheduler_status "
                "(task_name, last_run, last_status, run_count, error_count, last_error) "
                "VALUES (?, ?, ?, 1, 1, ?) "
                "ON CONFLICT(task_name) DO UPDATE SET "
                "last_run=?, last_status=?, run_count=run_count+1, "
                "error_count=error_count+1, last_error=?",
                (task_name, now, status, error, now, status, error),
            )
        else:
            self.execute(
                "INSERT INTO scheduler_status (task_name, last_run, last_status, run_count) "
                "VALUES (?, ?, ?, 1) "
                "ON CONFLICT(task_name) DO UPDATE SET "
                "last_run=?, last_status=?, run_count=run_count+1",
                (task_name, now, status, now, status),
            )

    # === Analysis logs ===

    def insert_analysis_log(self, data: dict) -> int:
        """Write a strategy decision log row."""
        market_snapshot = data.get("market_snapshot")
        if isinstance(market_snapshot, (dict, list)):
            data = {**data, "market_snapshot": json.dumps(market_snapshot, ensure_ascii=False)}

        sql = (
            "INSERT INTO analysis_logs "
            "(symbol, timeframe, strategy_name, signal_generated, signal_type, "
            "signal_strength, veto_passed, veto_reasons, veto_details, "
            "risk_passed, risk_reason, final_action, market_snapshot) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        )
        params = (
            data.get("symbol"),
            data.get("timeframe"),
            data.get("strategy_name"),
            data.get("signal_generated", 0),
            data.get("signal_type"),
            data.get("signal_strength"),
            data.get("veto_passed"),
            data.get("veto_reasons"),
            data.get("veto_details"),
            data.get("risk_passed"),
            data.get("risk_reason"),
            data.get("final_action", "NO_SIGNAL"),
            data.get("market_snapshot"),
        )
        with self.get_connection() as conn:
            cursor = conn.execute(sql, params)
            conn.commit()
            return int(cursor.lastrowid)

    def get_analysis_logs(self, limit: int = 100) -> list[dict]:
        """Return recent strategy decision logs."""
        rows = self.execute(
            "SELECT * FROM analysis_logs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in rows]

    # === TP / trailing updates ===

    def update_trade_tp_stage(
        self,
        trade_id: int,
        tp_stage: int,
        current_quantity: float,
        stop_loss: float,
    ) -> None:
        """Persist the current take-profit stage and adjusted stop."""
        self.execute(
            "UPDATE trades SET tp_stage=?, current_quantity=?, stop_loss=? WHERE id=?",
            (tp_stage, current_quantity, stop_loss, trade_id),
        )
        logger.info(
            f"Trade {trade_id}: TP stage -> {tp_stage}, "
            f"remaining qty={current_quantity:.6f}, new SL={stop_loss:.4f}"
        )

    def update_trade_trailing(
        self,
        trade_id: int,
        stop_loss: float,
        highest_price: float | None = None,
        lowest_price: float | None = None,
    ) -> None:
        """Persist trailing-stop adjustments and price extremes."""
        if highest_price is not None:
            self.execute(
                "UPDATE trades SET stop_loss=?, highest_price=? WHERE id=?",
                (stop_loss, highest_price, trade_id),
            )
            return

        if lowest_price is not None:
            self.execute(
                "UPDATE trades SET stop_loss=?, lowest_price=? WHERE id=?",
                (stop_loss, lowest_price, trade_id),
            )
            return

        self.execute(
            "UPDATE trades SET stop_loss=? WHERE id=?",
            (stop_loss, trade_id),
        )

    def update_trade_protection(
        self,
        trade_id: int,
        *,
        soft_stop_loss: float | None = None,
        hard_stop_loss: float | None = None,
        soft_stop_required_closes: int | None = None,
        highest_price: float | None = None,
        lowest_price: float | None = None,
    ) -> None:
        """Persist soft/hard stop changes while keeping the legacy stop_loss field in sync."""
        updates: list[str] = []
        params: list[Any] = []

        if soft_stop_loss is not None:
            updates.append("soft_stop_loss=?")
            params.append(soft_stop_loss)
        if hard_stop_loss is not None:
            updates.extend(["hard_stop_loss=?", "stop_loss=?"])
            params.extend([hard_stop_loss, hard_stop_loss])
        if soft_stop_required_closes is not None:
            updates.append("soft_stop_required_closes=?")
            params.append(soft_stop_required_closes)
        if highest_price is not None:
            updates.append("highest_price=?")
            params.append(highest_price)
        if lowest_price is not None:
            updates.append("lowest_price=?")
            params.append(lowest_price)

        if not updates:
            return

        params.append(trade_id)
        sql = f"UPDATE trades SET {', '.join(updates)} WHERE id=?"
        self.execute(sql, tuple(params))
