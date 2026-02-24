"""
APScheduler 排程引擎核心

管理所有定時任務：資金費率、爆倉監控、恐懼貪婪指數、
幣種篩選、策略評估、持倉檢查、心跳、每日報告。
"""

import asyncio
from datetime import datetime
from typing import Any, Callable, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger

from database.db_manager import DatabaseManager


class TaskScheduler:
    """
    排程引擎 — 管理所有定時任務

    每個任務執行完畢後自動更新資料庫中的排程狀態，
    供 Web 儀表板的系統狀態頁面查看。
    """

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db
        self.scheduler = AsyncIOScheduler(
            timezone="UTC",
            job_defaults={
                "coalesce": True,       # 錯過的執行合併為一次
                "max_instances": 1,     # 同一任務最多一個實例
                "misfire_grace_time": 60,
            },
        )
        self._tasks: dict[str, dict] = {}

    def add_interval_task(
        self,
        task_id: str,
        func: Callable,
        minutes: int,
        description: str = "",
        args: Optional[tuple] = None,
        kwargs: Optional[dict] = None,
    ) -> None:
        """
        新增間隔執行的任務。

        Args:
            task_id: 任務唯一識別碼
            func: 要執行的 async 函數
            minutes: 執行間隔（分鐘）
            description: 任務描述
        """
        wrapped = self._wrap_task(task_id, func)

        self.scheduler.add_job(
            wrapped,
            trigger=IntervalTrigger(minutes=minutes),
            id=task_id,
            name=description or task_id,
            args=args,
            kwargs=kwargs,
            replace_existing=True,
        )
        self._tasks[task_id] = {
            "type": "interval",
            "minutes": minutes,
            "description": description,
        }
        logger.info(f"Scheduled: {task_id} (every {minutes}min) - {description}")

    def add_cron_task(
        self,
        task_id: str,
        func: Callable,
        cron_expr: str,
        description: str = "",
        args: Optional[tuple] = None,
        kwargs: Optional[dict] = None,
    ) -> None:
        """
        新增 cron 表達式的定時任務。

        Args:
            task_id: 任務唯一識別碼
            func: 要執行的 async 函數
            cron_expr: cron 表達式 (e.g. "0 0 * * *")
            description: 任務描述
        """
        parts = cron_expr.split()
        cron_kwargs = {}
        fields = ["minute", "hour", "day", "month", "day_of_week"]
        for i, part in enumerate(parts):
            if i < len(fields):
                cron_kwargs[fields[i]] = part

        wrapped = self._wrap_task(task_id, func)

        self.scheduler.add_job(
            wrapped,
            trigger=CronTrigger(**cron_kwargs),
            id=task_id,
            name=description or task_id,
            args=args,
            kwargs=kwargs,
            replace_existing=True,
        )
        self._tasks[task_id] = {
            "type": "cron",
            "cron": cron_expr,
            "description": description,
        }
        logger.info(f"Scheduled: {task_id} (cron: {cron_expr}) - {description}")

    def _wrap_task(self, task_id: str, func: Callable) -> Callable:
        """包裝任務函數，自動記錄執行狀態到資料庫"""
        async def wrapper(*args: Any, **kwargs: Any) -> None:
            try:
                if asyncio.iscoroutinefunction(func):
                    await func(*args, **kwargs)
                else:
                    func(*args, **kwargs)
                self.db.update_scheduler_status(task_id, "success")
            except Exception as e:
                logger.error(f"Task {task_id} failed: {e}")
                self.db.update_scheduler_status(task_id, "error", str(e))
        return wrapper

    def start(self) -> None:
        """啟動排程器"""
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info(
                f"Scheduler started with {len(self._tasks)} tasks"
            )

    def stop(self) -> None:
        """停止排程器"""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped")

    def pause_task(self, task_id: str) -> bool:
        """暫停指定任務"""
        try:
            self.scheduler.pause_job(task_id)
            logger.info(f"Task paused: {task_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to pause task {task_id}: {e}")
            return False

    def resume_task(self, task_id: str) -> bool:
        """恢復指定任務"""
        try:
            self.scheduler.resume_job(task_id)
            logger.info(f"Task resumed: {task_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to resume task {task_id}: {e}")
            return False

    def get_all_status(self) -> list[dict]:
        """取得所有任務的運行狀態（供儀表板）"""
        statuses = []
        for task_id, info in self._tasks.items():
            # 從資料庫讀取執行紀錄
            rows = self.db.execute(
                "SELECT * FROM scheduler_status WHERE task_name=?",
                (task_id,),
            )
            db_status = dict(rows[0]) if rows else {}

            job = self.scheduler.get_job(task_id)
            next_run = None
            is_paused = False
            if job:
                next_run = str(job.next_run_time) if job.next_run_time else None
                is_paused = job.next_run_time is None

            statuses.append({
                "task_id": task_id,
                "description": info.get("description", ""),
                "type": info.get("type", ""),
                "schedule": info.get("minutes", info.get("cron", "")),
                "last_run": db_status.get("last_run"),
                "last_status": db_status.get("last_status", "never"),
                "run_count": db_status.get("run_count", 0),
                "error_count": db_status.get("error_count", 0),
                "last_error": db_status.get("last_error"),
                "next_run": next_run,
                "is_paused": is_paused,
            })

        return statuses
