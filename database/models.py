"""
SQLite 資料表定義

所有表結構的 SQL 建立語句集中在此管理。
使用 SQLite WAL 模式以提升並發讀寫效能。
"""

TABLES = {
    "trades": """
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL CHECK(side IN ('LONG', 'SHORT')),
            entry_price REAL NOT NULL,
            exit_price REAL,
            quantity REAL NOT NULL,
            leverage INTEGER NOT NULL,
            stop_loss REAL,
            take_profit REAL,
            status TEXT NOT NULL DEFAULT 'OPEN'
                CHECK(status IN ('OPEN', 'CLOSED', 'CANCELLED')),
            pnl REAL,
            pnl_pct REAL,
            fee REAL DEFAULT 0,
            entry_reason TEXT,
            exit_reason TEXT,
            strategy_name TEXT,
            veto_applied TEXT,
            exchange_order_id TEXT,
            opened_at TEXT NOT NULL,
            closed_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """,

    "signals": """
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            signal_type TEXT NOT NULL CHECK(signal_type IN ('LONG', 'SHORT', 'CLOSE')),
            strength REAL DEFAULT 0,
            strategy_name TEXT NOT NULL,
            indicators TEXT,
            was_vetoed INTEGER DEFAULT 0,
            veto_reason TEXT,
            was_executed INTEGER DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """,

    "risk_params": """
        CREATE TABLE IF NOT EXISTS risk_params (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            param_name TEXT NOT NULL UNIQUE,
            param_value TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """,

    "risk_history": """
        CREATE TABLE IF NOT EXISTS risk_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            param_name TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT NOT NULL,
            changed_by TEXT DEFAULT 'system',
            changed_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """,

    "market_info": """
        CREATE TABLE IF NOT EXISTS market_info (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            info_type TEXT NOT NULL,
            symbol TEXT,
            data TEXT NOT NULL,
            fetched_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """,

    "system_logs": """
        CREATE TABLE IF NOT EXISTS system_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            level TEXT NOT NULL,
            module TEXT,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """,

    "scheduler_status": """
        CREATE TABLE IF NOT EXISTS scheduler_status (
            task_name TEXT PRIMARY KEY,
            last_run TEXT,
            last_status TEXT,
            run_count INTEGER DEFAULT 0,
            error_count INTEGER DEFAULT 0,
            last_error TEXT
        )
    """,

    "analysis_logs": """
        CREATE TABLE IF NOT EXISTS analysis_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            strategy_name TEXT,
            signal_generated INTEGER DEFAULT 0,
            signal_type TEXT,
            signal_strength REAL,
            veto_passed INTEGER,
            veto_reasons TEXT,
            veto_details TEXT,
            risk_passed INTEGER,
            risk_reason TEXT,
            final_action TEXT DEFAULT 'NO_SIGNAL',
            market_snapshot TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """,
}

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol)",
    "CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status)",
    "CREATE INDEX IF NOT EXISTS idx_trades_opened ON trades(opened_at)",
    "CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals(symbol)",
    "CREATE INDEX IF NOT EXISTS idx_signals_created ON signals(created_at)",
    "CREATE INDEX IF NOT EXISTS idx_market_info_type ON market_info(info_type)",
    "CREATE INDEX IF NOT EXISTS idx_market_info_fetched ON market_info(fetched_at)",
    "CREATE INDEX IF NOT EXISTS idx_risk_history_param ON risk_history(param_name)",
    "CREATE INDEX IF NOT EXISTS idx_analysis_logs_symbol ON analysis_logs(symbol)",
    "CREATE INDEX IF NOT EXISTS idx_analysis_logs_created ON analysis_logs(created_at)",
    "CREATE INDEX IF NOT EXISTS idx_analysis_logs_action ON analysis_logs(final_action)",
]
