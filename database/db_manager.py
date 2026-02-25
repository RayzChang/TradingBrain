"""
SQLite 資料庫管理器

使用 WAL 模式提升並發讀寫效能。
提供統一的 CRUD 介面供所有模組使用。
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Generator, Optional

from loguru import logger

from config.settings import DB_PATH
from database.models import INDEXES, TABLES


class DatabaseManager:
    """SQLite 資料庫管理器（WAL 模式）"""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path or DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """初始化資料庫：建表、開啟 WAL 模式"""
        with self.get_connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA busy_timeout=5000;")
            conn.execute("PRAGMA synchronous=NORMAL;")

            for table_name, create_sql in TABLES.items():
                conn.execute(create_sql)
                logger.debug(f"Table ensured: {table_name}")

            for index_sql in INDEXES:
                conn.execute(index_sql)

            conn.commit()
        logger.info(f"Database initialized at {self.db_path} (WAL mode)")

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """取得資料庫連線的 context manager"""
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
        """執行 SQL 並回傳結果"""
        with self.get_connection() as conn:
            cursor = conn.execute(sql, params)
            conn.commit()
            return cursor.fetchall()

    def execute_many(self, sql: str, params_list: list[tuple]) -> None:
        """批次執行 SQL"""
        with self.get_connection() as conn:
            conn.executemany(sql, params_list)
            conn.commit()

    # === Trade Operations ===

    def insert_trade(self, trade_data: dict) -> int:
        """新增交易記錄，回傳 trade id"""
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
        """平倉更新"""
        sql = """
            UPDATE trades
            SET exit_price=?, pnl=?, pnl_pct=?, fee=?,
                exit_reason=?, status='CLOSED', closed_at=?
            WHERE id=?
        """
        now = datetime.utcnow().isoformat()
        self.execute(sql, (exit_price, pnl, pnl_pct, fee, exit_reason, now, trade_id))
        logger.info(f"Trade closed: id={trade_id}, pnl={pnl:.2f}")

    def get_open_trades(self) -> list[dict]:
        """取得所有未平倉交易"""
        rows = self.execute("SELECT * FROM trades WHERE status='OPEN'")
        return [dict(r) for r in rows]

    def get_trades_today(self) -> list[dict]:
        """取得今日所有交易"""
        today = datetime.utcnow().strftime("%Y-%m-%d")
        rows = self.execute(
            "SELECT * FROM trades WHERE opened_at >= ? ORDER BY opened_at DESC",
            (today,),
        )
        return [dict(r) for r in rows]

    def get_daily_pnl(self) -> float:
        """計算今日累計損益"""
        today = datetime.utcnow().strftime("%Y-%m-%d")
        rows = self.execute(
            "SELECT COALESCE(SUM(pnl), 0) as total FROM trades "
            "WHERE status='CLOSED' AND closed_at >= ?",
            (today,),
        )
        return rows[0]["total"] if rows else 0.0

    def get_total_realized_pnl(self) -> float:
        """計算全部已平倉累計損益"""
        rows = self.execute(
            "SELECT COALESCE(SUM(pnl), 0) as total FROM trades WHERE status='CLOSED'"
        )
        return rows[0]["total"] if rows else 0.0

    def get_recent_closed_trades(self, limit: int = 20) -> list[dict]:
        """取得最近 N 筆已平倉交易（按平倉時間倒序，供連虧冷卻判斷）"""
        rows = self.execute(
            "SELECT * FROM trades WHERE status='CLOSED' ORDER BY closed_at DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in rows]

    # === Risk Parameters ===

    def get_risk_params(self) -> dict[str, Any]:
        """取得所有風控參數"""
        rows = self.execute("SELECT param_name, param_value FROM risk_params")
        result = {}
        for row in rows:
            try:
                result[row["param_name"]] = json.loads(row["param_value"])
            except (json.JSONDecodeError, TypeError):
                result[row["param_name"]] = row["param_value"]
        return result

    def set_risk_param(
        self, name: str, value: Any, changed_by: str = "user"
    ) -> None:
        """設定風控參數（自動記錄歷史）"""
        value_str = json.dumps(value)

        # 查詢舊值
        old_rows = self.execute(
            "SELECT param_value FROM risk_params WHERE param_name=?", (name,)
        )
        old_value = old_rows[0]["param_value"] if old_rows else None

        # Upsert
        self.execute(
            "INSERT INTO risk_params (param_name, param_value, updated_at) "
            "VALUES (?, ?, datetime('now')) "
            "ON CONFLICT(param_name) DO UPDATE SET param_value=?, updated_at=datetime('now')",
            (name, value_str, value_str),
        )

        # 記錄變更歷史
        self.execute(
            "INSERT INTO risk_history (param_name, old_value, new_value, changed_by) "
            "VALUES (?, ?, ?, ?)",
            (name, old_value, value_str, changed_by),
        )
        logger.info(f"Risk param updated: {name} = {value} (by {changed_by})")

    def load_risk_defaults(self, defaults: dict) -> None:
        """載入預設風控參數（僅在參數不存在時寫入）"""
        existing = self.get_risk_params()
        for name, value in defaults.items():
            if name not in existing:
                self.set_risk_param(name, value, changed_by="system_default")

    # === Signal Operations ===

    def insert_signal(self, signal_data: dict) -> int:
        """記錄交易信號"""
        if "indicators" in signal_data and isinstance(
            signal_data["indicators"], dict
        ):
            signal_data["indicators"] = json.dumps(signal_data["indicators"])

        fields = ", ".join(signal_data.keys())
        placeholders = ", ".join(["?"] * len(signal_data))
        sql = f"INSERT INTO signals ({fields}) VALUES ({placeholders})"

        with self.get_connection() as conn:
            cursor = conn.execute(sql, tuple(signal_data.values()))
            conn.commit()
            return cursor.lastrowid

    # === Market Info ===

    def save_market_info(
        self, info_type: str, data: Any, symbol: Optional[str] = None
    ) -> None:
        """儲存市場資訊（資金費率、恐懼貪婪等）"""
        data_str = json.dumps(data) if not isinstance(data, str) else data
        self.execute(
            "INSERT INTO market_info (info_type, symbol, data) VALUES (?, ?, ?)",
            (info_type, symbol, data_str),
        )

    def get_latest_market_info(self, info_type: str) -> Optional[dict]:
        """取得最新的市場資訊"""
        rows = self.execute(
            "SELECT * FROM market_info WHERE info_type=? "
            "ORDER BY fetched_at DESC LIMIT 1",
            (info_type,),
        )
        if rows:
            row = dict(rows[0])
            try:
                row["data"] = json.loads(row["data"])
            except (json.JSONDecodeError, TypeError):
                pass
            return row
        return None

    # === Scheduler Status ===

    def update_scheduler_status(
        self, task_name: str, status: str, error: Optional[str] = None
    ) -> None:
        """更新排程任務狀態"""
        now = datetime.utcnow().isoformat()
        if error:
            self.execute(
                "INSERT INTO scheduler_status (task_name, last_run, last_status, run_count, error_count, last_error) "
                "VALUES (?, ?, ?, 1, 1, ?) "
                "ON CONFLICT(task_name) DO UPDATE SET "
                "last_run=?, last_status=?, run_count=run_count+1, error_count=error_count+1, last_error=?",
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
