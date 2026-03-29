"""
連虧冷卻機制 (Cooldown After Consecutive Losses)

連續虧損筆數 >= max_consecutive_losses 時，在 cool_down_after_loss_sec 秒內禁止開新倉。
"""

from datetime import datetime, timezone
from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from database.db_manager import DatabaseManager


@dataclass
class CooldownResult:
    """冷卻檢查結果"""
    can_open: bool
    reason: str = ""


class CooldownChecker:
    """
    依最近平倉紀錄判斷是否處於連虧冷卻期。
    """

    def __init__(self, db: "DatabaseManager") -> None:
        self.db = db

    def can_open(self) -> CooldownResult:
        """
        檢查是否允許開新倉（未在連虧冷卻中）。

        邏輯：取最近 N 筆已平倉，從最新一筆往前數連續虧損筆數；
        若 >= max_consecutive_losses，且最後一筆虧損時間在 cool_down_after_loss_sec 內，則禁止。
        """
        params = self.db.get_risk_params()
        max_consecutive = int(params.get("max_consecutive_losses", 3))
        cooldown_sec = int(params.get("cool_down_after_loss_sec", 300))

        recent = self.db.get_recent_closed_trades(limit=max_consecutive + 5)
        if not recent:
            return CooldownResult(can_open=True)

        consecutive_losses = 0
        for t in recent:
            pnl = t.get("pnl")
            if pnl is None:
                break
            try:
                pnl_f = float(pnl)
            except (TypeError, ValueError):
                break
            if pnl_f < 0:
                consecutive_losses += 1
            else:
                break

        if consecutive_losses < max_consecutive:
            return CooldownResult(can_open=True)

        # 檢查最後一筆虧損的時間
        last_trade = recent[0]
        closed_at = last_trade.get("closed_at")
        if not closed_at:
            return CooldownResult(can_open=True)

        try:
            # closed_at 為 UTC 儲存 (datetime.utcnow().isoformat())
            dt = datetime.fromisoformat(closed_at.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            last_loss_ts = dt.timestamp()
        except Exception:
            last_loss_ts = 0

        now = datetime.now(timezone.utc).timestamp()
        if now - last_loss_ts <= cooldown_sec:
            reason = (
                f"連虧 {consecutive_losses} 筆，冷卻 {cooldown_sec}s 內禁止開倉 "
                f"(剩 {int(cooldown_sec - (now - last_loss_ts))}s)"
            )
            logger.warning(reason)
            return CooldownResult(can_open=False, reason=reason)

        return CooldownResult(can_open=True)

    def per_symbol_direction_cooldown(
        self,
        symbol: str,
        direction: str,
    ) -> CooldownResult:
        """同幣同方向冷卻：1 筆虧→2h, 2 筆→4h, 3 筆→8h。"""
        recent = self.db.get_recent_closed_trades(limit=20)
        if not recent:
            return CooldownResult(can_open=True)

        losses = 0
        last_loss_ts = 0.0
        for t in recent:
            if t.get("symbol") != symbol or t.get("side") != direction:
                continue
            pnl = t.get("pnl")
            if pnl is None:
                break
            try:
                pnl_f = float(pnl)
            except (TypeError, ValueError):
                break
            if pnl_f < 0:
                losses += 1
                if losses == 1:
                    closed_at = t.get("closed_at")
                    if closed_at:
                        try:
                            dt = datetime.fromisoformat(closed_at.replace("Z", "+00:00"))
                            if dt.tzinfo is None:
                                dt = dt.replace(tzinfo=timezone.utc)
                            last_loss_ts = dt.timestamp()
                        except Exception:
                            pass
            else:
                break

        if losses == 0:
            return CooldownResult(can_open=True)

        cooldown_hours = {1: 2, 2: 4}.get(losses, 8 if losses >= 3 else 0)
        cooldown_sec = cooldown_hours * 3600

        now = datetime.now(timezone.utc).timestamp()
        if last_loss_ts > 0 and now - last_loss_ts <= cooldown_sec:
            remaining = int(cooldown_sec - (now - last_loss_ts))
            reason = (
                f"{symbol} {direction} 連虧 {losses} 筆，"
                f"同方向冷卻 {cooldown_hours}h (剩 {remaining}s)"
            )
            logger.warning(reason)
            return CooldownResult(can_open=False, reason=reason)

        return CooldownResult(can_open=True)
