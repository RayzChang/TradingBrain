# TradingBrain - AI Agent 操作手冊

> 這份文件是給所有 AI 助手（Cursor / Antigravity / 任何工具）的通用操作指南。
> 每次開啟新的 AI session 時，請先讓 AI 讀取此文件。

---

## 必讀規則

### 1. 語言
- **永遠使用繁體中文回應**
- 程式碼中的變數名/函數名使用英文，註解可用中英文混合

### 2. 每次開始工作前
1. 先讀取 `PROJECT_STATUS.md` 了解目前進度
2. 執行 `git log --oneline -20` 查看最近的 commit 歷史
3. 確認當前分支和狀態：`git status`
4. 根據進度檔中的「下一步」繼續工作
5. **策略監控**：若使用者要求「監控策略、確保能開倉/賺錢」，請讀取 `STRATEGY_MONITORING.md` 並依其中清單檢查 DB、日誌、策略與否決，再提出或實作改動
5b. **出資人貼回報**：若出資人貼上「幾則 LINE 監控快報」並說「根據這些改策略」，請**只改大腦**（`data/brain_state.json` 或呼叫 `core.brain.update_state()`），不要改寫死的 `main.py` / `core/strategy/*.py`。若「今日筆數 0」持續多則 → 放寬大腦 overrides（adx_min 降低、rsi 區間放寬、relax_veto true）；若有單但虧 → 收緊大腦；若有單且賺未達目標 → 微調大腦。程式每 15 分鐘會讀取大腦，**不需重啟 main**。大腦說明見 `BRAIN.md`，出資人節奏見 `給出資人.md`
6. **訓練循環**：若使用者要求「運行程式、監控、改善、以利益最大化為優先並持續循環直到達標」，請依 `AGENT_LOOP.md` 執行：運行程式 → 監控（`check_performance.py` + 日誌，**不關 main**）→ 若需改善則**改 code/config 後重啟 main** → 每輪結束後執行 `scripts/agent_cycle_report.py`（可帶本輪改動摘要），**使用者會收到 LINE 報告**。

### 3. 每次結束工作前
1. 確保所有修改都已測試可運行
2. 用有意義的 commit message 提交（格式見下方）
3. **更新 `PROJECT_STATUS.md`**：記錄做了什麼、下一步是什麼、有什麼問題
4. Push 到 GitHub：`git push origin main`

### 4. Git Commit 規範
格式：`[階段] 類型: 簡短描述`

範例：
- `[Phase1] feat: 建立專案骨架和配置管理`
- `[Phase2] feat: 實作資金費率監控模組`
- `[Phase3] fix: 修復 RSI 計算邊界條件`
- `[Phase4] refactor: 重構信號聚合引擎`

類型：
- `feat`: 新功能
- `fix`: 修復 bug
- `refactor`: 重構（不改變功能）
- `docs`: 文件更新
- `test`: 測試
- `chore`: 雜項（依賴更新等）

### 5. 程式碼規範
- Python: 遵循 PEP 8，使用 type hints
- TypeScript/React: 使用函數組件 + hooks
- 所有模組必須有 docstring 說明用途
- 不要在程式碼中硬編碼 API 密鑰，一律從 `.env` 讀取
- 不要在 commit 中包含 `.env` 檔案

### 6. 危險操作禁止
- **絕對不要**修改或刪除 `.env` 中的真實 API 密鑰
- **絕對不要**在未確認的情況下執行實盤交易相關程式碼
- **絕對不要**推送含有密鑰的程式碼到 GitHub
- **絕對不要** force push 到 main 分支

---

## 專案架構概覽

### 技術棧
- **後端**: Python 3.11+ / FastAPI / APScheduler
- **前端**: React 18 + TypeScript + TailwindCSS + Recharts + lightweight-charts
- **交易所**: ccxt + python-binance
- **技術分析**: ta (Technical Analysis Library，因 Python 3.14 不支援 pandas-ta 的 numba 依賴)
- **數據儲存**: SQLite-WAL（關聯數據）+ Parquet（K線時序）
- **通知**: LINE Messaging API（單向通知，無互動指令）

### 核心設計原則
1. **技術指標觸發，資訊管線否決** — 技術面是開單唯一來源，資金費率/恐懼貪婪/爆倉只用來否決
2. **全局 API 限流器** — 所有幣安 API 請求必須經過 RateLimiter singleton
3. **最小下單額保護** — 倉位 < 10 USDT 時放棄交易，不破壞風控
4. **絞肉機行情偵測** — 高低差大但收盤無變化 = 暫停開單
5. **先回測 -> 再模擬 -> 最後實盤** — 順序不可跳過

### 目錄結構快速參考
```
TradingBrain/
├── config/          # 配置管理
├── core/            # 核心邏輯
│   ├── data/        # 市場數據採集
│   ├── pipeline/    # 資訊管線（否決權模型）
│   ├── analysis/    # 技術分析引擎
│   ├── strategy/    # 交易策略
│   ├── risk/        # 風險管理
│   ├── execution/   # 交易執行
│   └── backtest/    # 回測系統
├── api/             # FastAPI 後端
├── frontend/        # React 前端
├── notifications/   # LINE 通知
├── database/        # 數據庫管理
├── data/klines/     # Parquet K線檔案
└── logs/            # 日誌
```

### 風控參數（可在 Web UI 調整）
- 每筆風險: 2% | 每日虧損上限: 5% | 最大回撤: 15%
- 最大槓桿: 5x | 最低風報比: 1:1.5
- 資金 <500U = 1倉 | 500-1000U = 2倉 | >1000U = 3倉
- 起始資金: 300 USDT（實盤從 50U 起步）

---

## 策略監控與迭代
- **`TARGET.md`**：訓練目標 — Testnet 5000U，每日平均收益 50~100U。達標前 Agent 循環以此為止。
- **`AGENT_LOOP.md`**：一輪循環 — 運行程式 → 監控（`scripts/check_performance.py` + 日誌）→ 改善策略/否決/風控（利益最大化）→ 驗證與重啟 → 重複直到達標。
- **`STRATEGY_MONITORING.md`**：何時改、怎麼改 — 依 DB 與回測落實賺錢。

## 完整計畫文件
詳細的 9 階段計畫請參閱：`PLAN.md`（專案根目錄）
