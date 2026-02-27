# TradingBrain 專案進度追蹤

> 最後更新: 2026-02-25
> 當前階段: **第九階段 - 實盤上線** (已完成!)

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
- [x] **第二階段：24/7 資訊管線（否決權模型）**
  - [x] core/data/market_data.py — REST K線採集 + Parquet 讀寫 + 自動分頁
  - [x] core/data/websocket_feed.py — WebSocket 即時 K 線 + KlineCache 記憶體快取 + 自動重連
  - [x] core/pipeline/funding_rate.py — 幣安資金費率監控（697 交易對）
  - [x] core/pipeline/fear_greed.py — 恐懼貪婪指數（Alternative.me API）
  - [x] core/pipeline/liquidation.py — 爆倉數據監控 + 連環爆倉偵測
  - [x] core/pipeline/veto_engine.py — 否決引擎（資金費率/恐懼貪婪/爆倉/絞肉機）
  - [x] core/pipeline/scheduler.py — APScheduler 排程引擎（含任務狀態追蹤）
  - [x] main.py 整合全部資訊管線模組
  - [x] 測試通過：恐懼貪婪=8(極度恐懼)、697對資金費率、否決引擎正確否決做空

- [x] **第三階段：技術分析引擎**
  - [x] core/analysis/indicators.py — 14 項指標：RSI, MACD, BB, EMA(9/21/50/200), SMA, ATR, ADX, OBV, VWAP, Stoch RSI
  - [x] core/analysis/divergence.py — RSI/MACD 常規看漲/看跌背離偵測（Swing High/Low 演算法）
  - [x] core/analysis/fibonacci.py — 自動斐波那契回撤(7級)+擴展(5級)，含最近支撐/阻力位查找
  - [x] core/analysis/candlestick.py — K線型態辨識：十字星、錘子/倒錘、吞噬、晨星/夜星、三白兵/三黑鴉
  - [x] core/analysis/multi_timeframe.py — 多時間框架趨勢一致性分析 + HTF RSI 確認
  - [x] core/analysis/chop_detector.py — 絞肉機偵測器（ADX+影線比+位移率+假突破，含冷卻時間）
  - [x] core/analysis/engine.py — AnalysisEngine 統一入口，整合所有分析模組
  - [x] main.py 整合：K線收盤觸發分析 → 絞肉機結果同步否決引擎 → 15m 觸發 MTF 分析
  - [x] 測試通過：7 項測試（指標/背離/斐波那契/K線型態/絞肉機/MTF/引擎整合）全部 PASS
- [x] **第四階段：策略與信號系統**
  - [x] core/strategy/base.py — 策略基類（TradeSignal、BaseStrategy 統一介面）
  - [x] core/strategy/trend_following.py — 趨勢跟蹤（EMA9/21 交叉 + ADX 門檻，可跳過絞肉機）
  - [x] core/strategy/mean_reversion.py — 均值回歸（布林帶觸及 + RSI 超買超賣，背離加分）
  - [x] core/strategy/signal_aggregator.py — 信號聚合器（多策略投票 + 否決引擎過濾，可寫入 signals 表）
  - [x] core/strategy/coin_screener.py — 幣種篩選器（MTF 信心/HTF RSI/ADX/絞肉機扣分 → score + rank）
  - [x] main.py 整合：15m MTF 分析後呼叫 aggregator.evaluate(full, save_to_db=True)
  - [x] 測試通過：tests/test_strategy.py 5 項測試全部 PASS
- [x] **第五階段：風險管理核心**
  - [x] core/risk/position_sizer.py — 倉位計算（每筆風險%、ATR 止損距離）+ 最小下單額 10U 保護，max_open_positions 自適應
  - [x] core/risk/stop_loss.py — ATR 動態止損/止盈 + 最低風報比檢查
  - [x] core/risk/daily_limits.py — 每日虧損熔斷、回撤熔斷（equity_high_water_mark 可更新）
  - [x] core/risk/cooldown.py — 連虧冷卻（max_consecutive_losses + cool_down_after_loss_sec）
  - [x] core/risk/risk_manager.py — 風控總入口：熔斷→冷卻→持倉數→倉位→止損止盈
  - [x] database/db_manager.py — get_total_realized_pnl、get_recent_closed_trades
  - [x] config/settings.py — TRADING_INITIAL_BALANCE（Phase6+ 改為交易所餘額）
  - [x] main.py：通過否決信號進入 risk_manager.evaluate，通過則 log「待執行層下單」
  - [x] 測試通過：tests/test_risk.py 6 項測試全部 PASS
- [x] **第六階段：Web 儀表板 (React + FastAPI)**
  - [x] api/app.py — FastAPI 應用、CORS、HTTP Basic 認證
  - [x] api/routes/ — risk（參數讀寫、預設方案載入）、signals、trades、system/status
  - [x] api/deps.py — get_db 單例
  - [x] database get_recent_signals
  - [x] frontend/ — Vite + React 18 + TypeScript + Tailwind，總覽 / 風控參數 / 信號 / 交易 四頁
  - [x] main.py 啟動時背景執行 API（daemon thread），run_api_only.py 供前端開發
  - [x] README 儀表板啟動說明
- [x] **第七階段：回測系統**
  - [x] core/backtest/engine.py — 回測引擎（Parquet 或 DataFrame、0.1% 滑點、0.04% 手續費、策略+風控同實盤）
  - [x] core/backtest/report.py — 績效報告（總報酬、最大回撤、勝率、交易次數）
  - [x] run_backtest.py — CLI（--symbol, --tf, --balance, --days 模擬 K 線）
  - [x] api/routes/backtest.py — POST /api/backtest/run（需 Parquet 存在）
  - [x] tests/test_backtest.py 通過
- [x] **第八階段：模擬交易**
  - [x] notifications/line_notify.py — LINE 每日報告與心跳異常通知
  - [x] core/execution/binance_client.py — 幣安合約簽名客戶端（餘額/持倉/市價單/止損止盈）
  - [x] core/execution/execution_engine.py — 風控通過後下單與 insert_trade
  - [x] core/execution/position_manager.py — 啟動時持倉同步、定時止損止盈檢查
  - [x] main.py — 交易所餘額、execute_trade、position_check/heartbeat 排程、_daily_report 發 LINE
  - [x] trades 表新增 exchange_order_id；.env.example 註解更新
  - [x] tests/test_execution.py 通過
- [x] **第九階段：實盤上線**
  - [x] execution_engine: is_trading_enabled() 支援實盤（BINANCE_TESTNET=false + TRADING_MODE=live）
  - [x] 開倉/平倉 LINE 通知（實盤與模擬皆可發送）
  - [x] main 以 is_trading_enabled() 驅動同步與持倉檢查（模擬與實盤共用）
  - [x] .env.example 補充 TRADING_MODE 說明；測試與文件更新

## 進行中

- **訓練循環**：依 `AGENT_LOOP.md` 運行程式 → 監控 → 改善策略（利益最大化）→ 重複直到達標。目標見 `TARGET.md`（Testnet 5000U，每日平均 50~100U）。

## 待做

- 達標前持續執行 Agent 循環；達標後可調高目標或進入實盤驗證。

## 已知問題

- Python 3.14 不支援 numba，改用 `ta` 替代 `pandas-ta`（功能等效）
- 控制台中文顯示為亂碼（終端編碼問題，不影響功能，日誌檔正常）

## 下一步

1. 每次 session：依 `AGENT_LOOP.md` 執行一輪（運行 → `scripts/check_performance.py` 監控 → 依數據改策略/風控 → 必要時回測與重啟）。
2. 達標（每日平均 50~100U）後：更新 TARGET.md、可設新目標或實盤 50U 起步。

## 筆記

- 通知系統使用 LINE Messaging API（免費 200 則/月，心跳採靜默模式）
- 資訊管線採否決權模型，初期不做 NLP
- SQLite 使用 WAL 模式，K線存 Parquet
- 技術分析改用 `ta` 庫（因 Python 3.14 相容性）
- 起始資金 300 USDT，實盤從 50U 起步
