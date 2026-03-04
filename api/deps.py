"""FastAPI 依賴 — 資料庫等"""

from database.db_manager import DatabaseManager

_db: DatabaseManager | None = None


def set_db(db: DatabaseManager) -> None:
    """注入共用 DB 實例（由 main.py 呼叫，避免雙實例衝突）"""
    global _db
    _db = db


def get_db() -> DatabaseManager:
    """取得資料庫管理器（單例）"""
    global _db
    if _db is None:
        _db = DatabaseManager()
    return _db
