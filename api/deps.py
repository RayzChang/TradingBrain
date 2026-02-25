"""FastAPI 依賴 — 資料庫等"""

from database.db_manager import DatabaseManager

_db: DatabaseManager | None = None


def get_db() -> DatabaseManager:
    """取得資料庫管理器（單例）"""
    global _db
    if _db is None:
        _db = DatabaseManager()
    return _db
