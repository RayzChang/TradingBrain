"""
TradingBrain 的「大腦」— 可被回報更新、程式運行時讀取的適應性狀態。

- 狀態存於 data/brain_state.json，由 Agent 根據每 3 小時回報更新。
- 策略與否決層在運行時讀取大腦覆寫參數，無需重啟程式。
"""

from core.brain.state import (
    get_overrides,
    load_state,
    update_state,
)

__all__ = ["get_overrides", "load_state", "update_state"]
