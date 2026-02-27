# Agent 循環 — 訓練 TradingBrain 直到達標

> 每次 Agent session 或定期執行此循環，直到 Testnet 5000U 每日平均收益達 50~100U。  
> 目標定義見 `TARGET.md`。  
> **出資人操作節奏請直接看：`給出資人.md`**

---

## 出資人何時來讓 Agent 改一次？

- **建議：每收到 3 則 LINE 監控快報（約 3 小時），把這 3 則貼到 Cursor，說「根據這些回報改策略」。**
- 即使 3 則都是「今日筆數 0」也貼 — Agent 會依「長期 0 單」改（出單條件／否決／執行），不會因為沒 log 就不改。
- 出資人可自訂為「每 6 則」或「每天一次」；重點是**固定把回報貼給 Agent**，Agent 才有數據可改。

---

## 現實說明：監控誰做、多久一次？改善誰做？數據會自動傳給 AI 嗎？

### 監控：多久一次？誰在做？

- **自動監控（有）**  
  **main.py 在跑時**，程式內建一個排程：**每 60 分鐘**讀一次 DB（今日損益、今日筆數、未平倉），組一則短訊，**自動用 LINE 發給你**（「監控快報」）。  
  → 所以：**只要 main 在跑，就是每 60 分鐘監控一次，並把結果推到你的 LINE**。不需要你或任何人手動跑腳本。

- **手動監控（可選）**  
  你或我在 Cursor 裡手動跑 `scripts/check_performance.py`、或開 `logs/trading_YYYY-MM-DD.log` 搜「信號通過否決」「風控攔截」等，是**額外**的，不是「系統每 N 分鐘自動跑」的。

### 改善：誰改程式碼／設定檔？數據會自動傳給 Agent 嗎？

- **改程式碼或設定檔的，只有兩種**：  
  **(1) 你本人**  
  **(2) 在 Cursor 裡跟你對話的 AI（我，Agent）**  

- **腳本不會改 code、也不會改設定檔。**  
  `check_performance.py`、`agent_cycle_report.py` 只會：讀 DB、印出或送 LINE。它們**不會**編輯任何檔案。

- **沒有任何「後台自動把監控數據傳給某個 AI、再自動改 code」的機制。**  
  所以：**不會**有「數據自動傳給 Agent、Agent 自動改程式」這種事。  
  改善**只會**發生在：**你開 Cursor，跟我說「跑一輪／幫我根據監控改」→ 我（或你）執行監控腳本或看 LINE 快報 → 我根據數據改檔案**。沒有你或我介入，就不會有任何改 code 的行為。

### 總結

| 項目 | 誰做 | 頻率／方式 |
|------|------|------------|
| **監控** | main.py 內建排程 | **每 60 分鐘**自動發一則 LINE 監控快報（今日損益／筆數／未平倉）。 |
| **改善** | **只有你或 Cursor 裡的 Agent（我）** | 你開 Cursor 叫我「根據監控改」→ 我看數據（或你貼 LINE）→ 我改 code/config。不會自動改。 |
| **數據給 Agent** | 無自動管道 | 你貼 LINE 快報給我、或叫我在 Cursor 跑 `check_performance.py`，我才有數據。 |

---

## 一輪循環（Loop）要做的事

```
1. 運行程式     → 確保 main.py 在跑（或啟動它）
2. 監控程式     → 查 DB + 日誌（不關 main），看今日損益、開倉數、否決/風控原因
3. 發現並改善   → 根據數據改策略/否決/風控（改 code 或 config）→ 改完要重啟 main
4. 驗證         → 必要時跑回測，再重啟程式
5. 發 LINE 報告 → 執行 scripts/agent_cycle_report.py，你會收到本輪摘要
6. 重複 1~5    → 直到每日平均收益 50~100U
```

---

## 步驟 1：運行程式

- 若未運行：在專案根目錄執行  
  `venv\Scripts\python main.py`  
  （可背景執行，或另開終端常駐。）
- 若已運行：跳過，直接步驟 2。

---

## 步驟 2：監控程式（你多半不用手動做）

- **main 跑著就會每 60 分鐘自動發 LINE 監控快報**（今日損益、今日筆數、未平倉）。間隔可在 `config/settings.py` 的 `SCHEDULER_CONFIG["monitor_report"]["interval_min"]` 修改。
- 若你要或 Agent 要「自己看一筆」：可手動執行監控腳本：

```bash
venv\Scripts\python scripts\check_performance.py
```

或手動查：

- **DB**：今日損益 `get_daily_pnl()`、今日交易筆數 `get_trades_today()`、未平倉 `get_open_trades()`、累計已實現 `get_total_realized_pnl()`。
- **日誌**：`logs/trading_YYYY-MM-DD.log` — 搜尋「信號通過否決」「風控攔截」「無候選信號」「set_leverage」「保底開單」。

判斷：

- 0 單 → 卡在信號/否決/風控/API，依 STRATEGY_MONITORING 對應調整。
- 有單但虧 → 調止損止盈、進場條件、或每筆風險。
- 有單且賺但未達 50~100U/日 → 在風控允許下提高倉位/頻率或優化勝率。

---

## 步驟 3：發現並改善（利益最大化優先）

- 對照 `STRATEGY_MONITORING.md` 的「何時該改」。
- 改動方向優先級：
  1. 提高期望值（勝率 × 平均賺 - 敗率 × 平均賠）。
  2. 在回撤可接受下提高單筆倉位或開倉頻率。
  3. 減少「該賺沒賺到」的否決（可先從 Testnet 放寬驗證）。
- 改動後若為策略/風控參數，建議跑回測再上線。

---

## 步驟 4：驗證與重啟

- 若有改程式或 config：**先關掉正在跑的 main.py，再重新執行**，新邏輯才會生效。
- 若有改風控預設：重啟後會重載 `risk_defaults.json`。
- 下一輪（下次 session 或定時）從步驟 1 再跑一輪。

---

## 步驟 5：發 LINE 報告（讓你知道有在做）

每輪結束後執行（Agent 或你手動皆可）：

```bash
venv\Scripts\python scripts\agent_cycle_report.py
```

若有本輪改動，可帶摘要當參數，會一併出現在 LINE 裡：

```bash
venv\Scripts\python scripts\agent_cycle_report.py "本輪改動：放寬 ADX 至 15、改用訓練型風控"
```

你就會在 LINE 收到一則「TradingBrain Agent 循環報告」，內容包含：日期、今日損益、今日筆數、未平倉、目標狀態、以及本輪改動（若有）。

---

## 何時停止循環

- **達標**：Testnet 5000U，連續多日每日平均已實現損益在 50~100U → 更新 TARGET.md / PROJECT_STATUS，可設新目標或進實盤。
- **未達標**：持續依數據改策略/風控，重複本循環。

---

## 檔案對應

- 目標數字：`TARGET.md`
- 策略/否決/風控怎麼改：`STRATEGY_MONITORING.md`
- 監控腳本：`scripts/check_performance.py`
- **LINE 循環報告**：`scripts/agent_cycle_report.py`（每輪跑一次，你就收到通知）
- 進度與下一步：`PROJECT_STATUS.md`
