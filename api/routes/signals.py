"""信號 API — 最近信號列表"""

from fastapi import APIRouter, Depends, Query

from api.deps import get_db
from database.db_manager import DatabaseManager

router = APIRouter()


@router.get("")
def list_signals(
    limit: int = Query(50, ge=1, le=200),
    db: DatabaseManager = Depends(get_db),
):
    """取得最近信號（含是否被否決、是否執行）"""
    return db.get_recent_signals(limit=limit)
