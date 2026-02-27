# TradingBrain 的「大腦」— 專案內唯一會隨回報演進的邏輯

> 策略不再寫死。大腦狀態存於 `data/brain_state.json`，由 Agent 根據你每 3 小時的回報更新；程式運行時每 15 分鐘讀取，**無需重啟**。

---

## 大腦是什麼

- **實體**：`data/brain_state.json` 一個 JSON 檔 + `core/brain/` 讀寫模組。
- **作用**：存「當前覆寫參數」：策略用的 ADX/RSI/chop、否決是否放寬、之後可擴充風控等。策略與否決層**只認大腦**，不認寫死的常數。
- **誰改**：**只有 Agent（我）** 根據你貼的 LINE 回報改這個檔（或透過 `core.brain.update_state()`）。你不需要改 code。

---

## 覆寫參數說明（overrides）

| 鍵 | 說明 | 預設 |
|----|------|------|
| adx_min | 趨勢策略 ADX 門檻，愈低愈容易出信號 | 15 |
| rsi_oversold | 均值回歸做多：RSI 低於此視為超賣 | 35 |
| rsi_overbought | 均值回歸做空：RSI 高於此視為超買 | 65 |
| skip_on_chop | 是否在絞肉機行情跳過出信號（false = 照樣出） | false |
| relax_veto | 是否放寬否決（恐懼貪婪/資金費率/絞肉機不擋） | true |

Agent 根據回報可改上述任一項；程式每 15 分鐘重讀，**不需重啟 main**。

---

## Agent 收到「每 3 小時回報」時要做的事

1. **解讀回報**：今日筆數、今日損益、未平倉。
2. **只改大腦**：呼叫 `core.brain.update_state(overrides_delta=..., consecutive_zero_trade_reports=..., notes=...)` 或直接編輯 `data/brain_state.json`。
   - 連續多則 0 筆 → 加大放寬：例如 `adx_min: 10`, `rsi_oversold: 40`, `rsi_overbought: 60`。
   - 有單但虧 → 收緊：提高 adx_min、縮小 RSI 區間或設 `relax_veto: false`。
   - 有單且賺未達目標 → 微調倉位或維持，必要時在 overrides 加欄位（需同步改 core/brain/state.py 的 DEFAULT_OVERRIDES）。
3. **不要**為「改策略邏輯」去改 `main.py` 或 `core/strategy/*.py` 的寫死常數；**只改大腦**，讓大腦驅動行為。

---

## 程式怎麼讀大腦

- **策略**：main 啟動時與每 15 分鐘排程呼叫 `_strategies_from_brain()`，用 `brain.get_overrides()` 的 adx_min、rsi_oversold、rsi_overbought、skip_on_chop 組出策略實例，替換進信號聚合器。
- **否決**：否決引擎每次 evaluate 時呼叫 `brain.get_overrides()`，若 `relax_veto` 為 true 則放寬恐懼貪婪/資金費率/絞肉機。
- **快取**：`get_overrides()` 60 秒快取，避免每筆信號都讀檔；排程每 15 分鐘重載策略時會用到新參數。

---

## 總結

- **你**：跑 main、每 3 則 LINE 快報貼給 Agent。
- **Agent**：只改 `data/brain_state.json`（或透過 `update_state`），不改寫死的 code。
- **程式**：每 15 分鐘讀大腦、更新策略與否決行為，**不用重啟**，大腦就是專案裡會隨回報演進的「腦子」。
