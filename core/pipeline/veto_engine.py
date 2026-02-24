"""
否決引擎 (Veto Engine)

彙總所有否決條件，對交易信號進行過濾。
資訊管線只有「否決權」，不能「觸發」交易。

否決邏輯：
1. 恐懼貪婪 > threshold → 否決做多
2. 恐懼貪婪 < threshold → 否決做空
3. 資金費率 > threshold → 否決做多
4. 資金費率 < threshold → 否決做空
5. 爆倉異常 → 否決所有方向
6. 絞肉機行情 → 否決所有方向 (由 analysis/chop_detector 提供)
"""

from dataclasses import dataclass, field
from typing import Optional

from loguru import logger

from core.pipeline.fear_greed import FearGreedMonitor
from core.pipeline.funding_rate import FundingRateMonitor
from core.pipeline.liquidation import LiquidationMonitor
from database.db_manager import DatabaseManager


@dataclass
class VetoResult:
    """否決判定結果"""
    passed: bool
    reasons: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)

    @property
    def vetoed(self) -> bool:
        return not self.passed

    def __str__(self) -> str:
        if self.passed:
            return "PASS (no veto)"
        return f"VETOED: {', '.join(self.reasons)}"


class VetoEngine:
    """
    否決引擎 — 交易信號的安全閥。

    所有交易信號在進入風控之前，必須先通過否決引擎的檢查。
    任何一個否決條件成立，該信號就會被攔截。
    """

    def __init__(
        self,
        db: DatabaseManager,
        funding_monitor: FundingRateMonitor,
        fear_greed_monitor: FearGreedMonitor,
        liquidation_monitor: LiquidationMonitor,
    ) -> None:
        self.db = db
        self.funding = funding_monitor
        self.fear_greed = fear_greed_monitor
        self.liquidation = liquidation_monitor

        # 絞肉機狀態 (由外部 chop_detector 更新)
        self._chop_active = False
        self._chop_until: float = 0

    def _load_thresholds(self) -> dict:
        """從資料庫載入否決閾值"""
        params = self.db.get_risk_params()
        return {
            "fear_greed_high": params.get("veto_fear_greed_high", 80),
            "fear_greed_low": params.get("veto_fear_greed_low", 20),
            "funding_high": params.get("veto_funding_rate_high", 0.001),
            "funding_low": params.get("veto_funding_rate_low", -0.001),
            "liquidation_surge": params.get("veto_liquidation_surge", True),
        }

    def set_chop_active(self, active: bool, until: float = 0) -> None:
        """由 chop_detector 呼叫，設定絞肉機行情狀態"""
        self._chop_active = active
        self._chop_until = until
        if active:
            logger.warning(f"Chop market veto activated until {until}")

    def evaluate(self, symbol: str, direction: str) -> VetoResult:
        """
        評估交易信號是否應被否決。

        Args:
            symbol: 交易對 (e.g. "BTCUSDT")
            direction: 交易方向 ("LONG" or "SHORT")

        Returns:
            VetoResult with passed/vetoed status and reasons
        """
        thresholds = self._load_thresholds()
        reasons = []
        details = {}

        # === 1. 恐懼貪婪指數檢查 ===
        fg_value = self.fear_greed.get_value()
        if fg_value is not None:
            details["fear_greed"] = fg_value
            if direction == "LONG" and fg_value >= thresholds["fear_greed_high"]:
                reasons.append(
                    f"恐懼貪婪指數 {fg_value} >= {thresholds['fear_greed_high']} (極度貪婪，否決做多)"
                )
            elif direction == "SHORT" and fg_value <= thresholds["fear_greed_low"]:
                reasons.append(
                    f"恐懼貪婪指數 {fg_value} <= {thresholds['fear_greed_low']} (極度恐懼，否決做空)"
                )

        # === 2. 資金費率檢查 ===
        funding_rate = self.funding.get_rate(symbol)
        if funding_rate is not None:
            details["funding_rate"] = funding_rate
            if direction == "LONG" and funding_rate >= thresholds["funding_high"]:
                reasons.append(
                    f"資金費率 {funding_rate:.4f} >= {thresholds['funding_high']} (多頭擁擠，否決做多)"
                )
            elif direction == "SHORT" and funding_rate <= thresholds["funding_low"]:
                reasons.append(
                    f"資金費率 {funding_rate:.4f} <= {thresholds['funding_low']} (空頭擁擠，否決做空)"
                )

        # === 3. 爆倉異常檢查 ===
        if thresholds["liquidation_surge"] and self.liquidation.is_surge:
            details["liquidation_surge"] = True
            reasons.append("偵測到連環爆倉異常，暫停所有開單")

        # === 4. 絞肉機行情檢查 ===
        import time
        if self._chop_active and time.time() < self._chop_until:
            details["chop_market"] = True
            reasons.append("絞肉機行情偵測中，暫停開單")
        elif self._chop_active:
            self._chop_active = False

        # === 結果 ===
        result = VetoResult(
            passed=len(reasons) == 0,
            reasons=reasons,
            details=details,
        )

        if result.vetoed:
            logger.info(f"Veto [{symbol} {direction}]: {result}")
        else:
            logger.debug(f"Veto check passed: {symbol} {direction}")

        return result
