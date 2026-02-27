# 策略監控與迭代指引（Agent 常駐監控）

> 本文件供 AI Agent 或維護者「定期檢查策略是否有效、並改進以落實賺錢」使用。  
> 建議：每次開啟 session 或每週至少一次檢視此清單並依資料做出調整。

---

## 1. 監控目標

- **有單可下**：Testnet/實盤能穩定產出信號並成功下單，不被否決或風控過度擋下。
- **能賺錢**：勝率、期望值、回撤在可接受範圍；長期權益曲線向上或至少不大幅回撤。
- **可迭代**：參數與邏輯有依據（回測/實績），而非盲目調參。

---

## 2. 每週/每次 Session 必查

### 2.1 從資料庫與日誌看「有沒有單」

- **查詢**：`trades` 表 — 最近 7 天開倉筆數、平倉筆數。
- **日誌關鍵字**：`信號通過否決`、`風控通過但未下單`、`風控攔截`、`set_leverage 失敗`、`無候選信號`。
- **若長期 0 單**：
  - 先區分：是「沒信號」、「信號被否決」、還是「風控/交易所 API 擋」。
  - 對應調整：放寬策略門檻（ADX/RSI/chop）、放寬否決（或 Testnet 用 `RELAX_VETO_ON_TESTNET`）、或檢查 API/餘額/槓桿。

### 2.2 從績效看「有沒有賺」

- **查詢**：`trades` 表 — 已平倉的 `realized_pnl` 彙總、勝率（獲利筆數/總筆數）、最大連續虧損。
- **指標**：
  - 勝率 > 40%、期望值 > 0（平均每筆賺）、最大回撤 < 20%（依本金），可視為「策略有效」的起碼條件。
  - 若勝率過低或期望值為負：檢視止損/止盈比例、進場邏輯（是否常追高殺低）、是否在震盪市頻繁被洗出。

### 2.3 從信號表看「策略與否決」

- **查詢**：`signals` 表 — `was_vetoed`、`veto_reason`、`strategy_name` 分布。
- **解讀**：若多數被恐懼貪婪/資金費率否決，可考慮在 Testnet 放寬或實盤微調閾值；若多數被 chop 否決，可視需求放寬絞肉機條件或縮短 cooldown。

---

## 3. 何時該改策略/參數

| 狀況 | 建議動作 |
|------|----------|
| 連續多日 0 單（且非 API 問題） | 放寬策略門檻或否決（先 Testnet 驗證） |
| 有單但幾乎都虧（勝率 < 35%、期望值負） | 檢視止損/止盈、進場條件、時間框架；先回測再調 |
| 回撤過大（> 20% 權益） | 降低每筆風險、槓桿、或暫停開單直到檢討完 |
| 信號很多但多被否決 | 檢視否決閾值與 RELAX_VETO_ON_TESTNET（僅 Testnet） |
| 交易所常 400/限流 | 檢查 API 權限、Testnet 限制、或改用實盤端點 |

---

## 4. 怎麼改才叫「落實賺錢」

1. **先量後改**：用 DB 的 trades/signals 與回測結果判斷問題點（沒單 / 虧損 / 回撤），再改對應模組。
2. **回測優先**：參數或邏輯變更先跑 `run_backtest.py` 或後端回測 API，確認期望值與回撤可接受再上 Testnet/實盤。
3. **小步迭代**：一次改一類（例如只改 ADX 門檻、或只改否決閾值），觀察一週再決定下一步。
4. **區分環境**：Testnet 可放寬否決/保底開單以便驗證流程；實盤必須保留風控與否決，不應為「有單」而過度放寬。

---

## 5. 程式與檔案對應

- **策略門檻**：`main.py`（Testnet 用 ADX 15、RSI 35/65）、`core/strategy/trend_following.py`、`core/strategy/mean_reversion.py`。
- **否決**：`core/pipeline/veto_engine.py`、`config/risk_defaults.json`（veto_fear_greed_*、veto_funding_*）。
- **風控**：`config/risk_defaults.json`、`core/risk/`（position_sizer、stop_loss、daily_limits、cooldown）。
- **執行**：`core/execution/execution_engine.py`、`core/execution/binance_client.py`（下單、槓桿、餘額）。
- **回測**：`run_backtest.py`、`core/backtest/`、`api/routes/backtest.py`。

---

## 6. Agent 檢查清單（可複製使用）

- [ ] 讀取 `PROJECT_STATUS.md` 與最近 commit。
- [ ] 查 DB：最近 7 天開倉/平倉筆數、已實現損益、勝率。
- [ ] 查日誌：是否有「信號通過否決」「風控攔截」「set_leverage 失敗」等。
- [ ] 若 0 單：依 2.1 判斷原因並改策略/否決/風控或 API。
- [ ] 若有單但虧：依 2.2 檢視止損止盈與進場邏輯，必要時回測後調參。
- [ ] 更新 `PROJECT_STATUS.md` 與 commit，註明「策略監控：發現 X、做了 Y」。
