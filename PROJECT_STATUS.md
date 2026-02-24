# TradingBrain 專案進度追蹤

> 最後更新: 2026-02-24
> 當前階段: **第一階段 - 基礎建設** (已完成!)

---

## 已完成

- [x] 專案規劃 v3 最終版確定
- [x] GitHub repo 建立 (RayzChang/TradingBrain)
- [x] Git 初始化 + remote 設定
- [x] AGENT_INSTRUCTIONS.md 建立（AI 操作手冊）
- [x] PROJECT_STATUS.md 建立（進度追蹤）
- [x] .cursor/rules/project.mdc 建立（Cursor 自動規則）
- [x] **第一階段：基礎建設**
  - [x] 完整目錄結構（config/core/api/frontend/database/notifications/data/logs）
  - [x] Python 虛擬環境 + 依賴安裝（使用 ta 替代 pandas-ta，因 Python 3.14 不支援 numba）
  - [x] config/settings.py — 全局配置 + 環境變數
  - [x] config/risk_defaults.json — 保守/穩健/積極三套風控預設方案
  - [x] database/models.py — 7 張表：trades, signals, risk_params, risk_history, market_info, system_logs, scheduler_status
  - [x] database/db_manager.py — SQLite-WAL 管理器，含 CRUD 方法
  - [x] core/rate_limiter.py — 全局 API 限流器（Singleton，追蹤權重+訂單頻率）
  - [x] core/logger_setup.py — loguru 日誌系統（控制台+一般+錯誤+交易專用日誌，自動輪轉）
  - [x] main.py — 主程式入口（啟動序列+信號處理+優雅關閉）
  - [x] .env.example + .gitignore + README.md + requirements.txt
  - [x] 啟動測試通過：23 個風控參數成功載入

## 進行中

（無）

## 待做

- [ ] 第二階段：24/7 資訊管線（否決權模型）
- [ ] 第三階段：技術分析引擎
- [ ] 第四階段：策略與信號系統
- [ ] 第五階段：風險管理
- [ ] 第六階段：Web 儀表板 (React + FastAPI)
- [ ] 第七階段：回測系統
- [ ] 第八階段：模擬交易
- [ ] 第九階段：實盤上線

## 已知問題

- Python 3.14 不支援 numba，改用 `ta` 替代 `pandas-ta`（功能等效）
- 控制台中文顯示為亂碼（終端編碼問題，不影響功能，日誌檔正常）

## 下一步

開始第二階段：24/7 資訊管線
1. core/pipeline/scheduler.py — APScheduler 排程核心
2. core/data/websocket_feed.py — 幣安 WebSocket K 線即時數據
3. core/data/market_data.py — REST API 歷史數據 + Parquet
4. core/pipeline/funding_rate.py — 資金費率監控
5. core/pipeline/liquidation.py — 爆倉數據
6. core/pipeline/fear_greed.py — 恐懼貪婪指數
7. core/pipeline/veto_engine.py — 否決引擎

## 筆記

- 通知系統使用 LINE Messaging API（免費 200 則/月，心跳採靜默模式）
- 資訊管線採否決權模型，初期不做 NLP
- SQLite 使用 WAL 模式，K線存 Parquet
- 技術分析改用 `ta` 庫（因 Python 3.14 相容性）
- 起始資金 300 USDT，實盤從 50U 起步
