"""
大腦狀態：讀取 / 更新 data/brain_state.json

- get_overrides(): 供策略與否決層呼叫，回傳當前覆寫參數（帶快取，避免每筆都讀檔）
- update_state(): 供 Agent 或腳本呼叫，根據回報更新大腦（寫入 JSON）
"""

import json
import time
from pathlib import Path
from typing import Any

from loguru import logger

# 專案根目錄
BASE_DIR = Path(__file__).resolve().parent.parent.parent
STATE_PATH = BASE_DIR / "data" / "brain_state.json"

# 快取：60 秒內重複呼叫 get_overrides 不重新讀檔
_CACHE: dict[str, Any] | None = None
_CACHE_TIME: float = 0
TTL_SEC = 60

DEFAULT_OVERRIDES = {
    "adx_min": 25.0,
    "rsi_oversold": 30.0,
    "rsi_overbought": 70.0,
    "skip_on_chop": True,
    "relax_veto": False,
    "max_risk_per_trade_override": None,  # 若設數字則覆寫風控每筆風險比例
}


def _ensure_state_file() -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not STATE_PATH.exists():
        initial = {
            "version": 1,
            "last_updated": "",
            "consecutive_zero_trade_reports": 0,
            "overrides": {},
            "notes": "大腦初始狀態，由 Agent 根據回報更新",
        }
        STATE_PATH.write_text(json.dumps(initial, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"Brain state file created: {STATE_PATH}")


def load_state() -> dict[str, Any]:
    """載入完整大腦狀態（不建議高頻呼叫，用 get_overrides）"""
    _ensure_state_file()
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return data
    except Exception as e:
        logger.warning(f"Brain load_state failed: {e}")
        return {
            "version": 1,
            "last_updated": "",
            "consecutive_zero_trade_reports": 0,
            "overrides": {},
            "notes": "",
        }


def get_overrides() -> dict[str, Any]:
    """供策略/否決層呼叫：回傳當前覆寫參數，未設的用預設值。帶 60 秒快取。"""
    global _CACHE, _CACHE_TIME
    now = time.time()
    if _CACHE is not None and (now - _CACHE_TIME) < TTL_SEC:
        return _CACHE.copy()
    data = load_state()
    overrides = data.get("overrides", {}) or {}
    out = {k: overrides.get(k, v) for k, v in DEFAULT_OVERRIDES.items()}
    out.update({k: v for k, v in overrides.items() if k in DEFAULT_OVERRIDES})
    _CACHE = out
    _CACHE_TIME = now
    return out.copy()


def invalidate_cache() -> None:
    """更新狀態後呼叫，強制下次 get_overrides 重讀檔"""
    global _CACHE, _CACHE_TIME
    _CACHE = None
    _CACHE_TIME = 0


def update_state(
    overrides_delta: dict[str, Any] | None = None,
    consecutive_zero_trade_reports: int | None = None,
    notes: str | None = None,
) -> None:
    """
    更新大腦狀態（由 Agent 或腳本在收到回報後呼叫）。

    Args:
        overrides_delta: 要合併進 overrides 的鍵值，例如 {"adx_min": 10, "relax_veto": True}
        consecutive_zero_trade_reports: 若提供，寫入狀態（連續幾次回報為 0 筆）
        notes: 若提供，寫入備註（Agent 可寫入本輪判斷）
    """
    import datetime
    _ensure_state_file()
    data = load_state()
    if overrides_delta:
        data["overrides"] = {**(data.get("overrides") or {}), **overrides_delta}
    if consecutive_zero_trade_reports is not None:
        data["consecutive_zero_trade_reports"] = consecutive_zero_trade_reports
    if notes is not None:
        data["notes"] = notes
    data["last_updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    STATE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    invalidate_cache()
    logger.info(f"Brain updated: overrides={overrides_delta} zero_reports={consecutive_zero_trade_reports}")
