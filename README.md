# TradingBrain V7

TradingBrain V7 是一套以 **市場結構、K 線確認、分層風控與研究型 logging** 為核心的加密貨幣交易系統，主要用於 Binance Testnet / Demo 觀察、策略迭代與交易研究。

## 核心理念

- 結構優先：先看支撐、壓力、箱體、swing high / low
- K 線確認：進場依賴 reclaim、engulfing、higher low / lower high
- 指標輔助：RSI、MACD、ADX、Bollinger Band 只做輔助，不主導交易
- 止損分層：`soft stop` + `hard stop`
- 止盈看區域：不再只靠固定 ATR 模板
- 槓桿是結果：先定風險，再由止損距離反推倉位與槓桿

## 當前策略

- `trend_following`
  - 順勢 pullback continuation
  - 使用 `4h / 1h` 方向、`15m` setup、`1m` trigger

- `breakout_retest`
  - 先建立 breakout setup，再走 retest confirm
  - 適合結構突破後的延續行情

- `mean_reversion`
  - 只在區間或回歸環境中工作
  - 偏短打、快進快出

## 多時間框架架構

- `4h`：大方向
- `1h`：方向過濾
- `15m`：setup 層
- `1m`：進場觸發、retest confirm、持倉保護

## 風控與出場

### Soft Stop / Hard Stop

- `soft stop`
  - 用來判斷交易邏輯失效
  - 需要收盤確認，不是影線碰到就走

- `hard stop`
  - 用來防 API 異常、極端行情、網路中斷
  - 為災難保命線

### 三套出場模板

- `trend_following`
  - 偏向保留趨勢延續空間

- `breakout / breakout_retest`
  - 偏向觀察突破延續
  - 目前使用較寬的結構保護與較遠的 TP 區

- `mean_reversion`
  - 偏短打
  - 可接受更快保本與更快出場

## Position Sizing

目前倉位大小基於：

- 結構止損距離優先
- 策略風險權重
- Signal strength 縮放
- 簡化版相關性保護（`BTCUSDT / ETHUSDT` 同向不可同持）

意思是：

1. 先找這筆單的合理失效位置
2. 再決定最多願意虧多少
3. 最後反推可開倉位與槓桿

## Telegram 通知

系統目前使用 Telegram 通知，內容包含：

- 啟動通知
- 每小時監控快報
- 開倉通知
- TP / SL / 全平倉通知
- 風控攔截通知
- 每日報告

啟動通知會顯示目前實際執行中的：

- 版本
- 模式
- 策略組合
- 風控摘要
- 各策略的 SL / TP 模板摘要

## 研究型 Logging

系統會把研究資料落到：

- `analysis_logs`
- `signals`
- `trades`
- `logs/daily_reports`
- `logs/daily_reports/agent_reports`

目前可追蹤內容包含：

- regime
- `mtf_4h_direction`
- `mtf_1h_direction`
- `mtf_gate_passed`
- `signal_strength`
- `strategy_risk_weight`
- `breakout_retest_status`
- `effective_risk_pct`
- `sl_atr_mult`
- `structure_stop_floor_triggered`

## 啟動方式

### 後端

```bash
python main.py
```

### 啟動器

```bash
python launcher.py
```

### 前端

```bash
cd frontend
npm install
npm run dev
```

## 測試

```bash
python -m pytest -q
```

## 專案結構

```text
tradingbrain/
├── main.py
├── launcher.py
├── config/
├── core/
│   ├── analysis/
│   ├── strategy/
│   ├── risk/
│   ├── execution/
│   └── pipeline/
├── database/
├── notifications/
├── frontend/
├── tests/
├── scripts/
├── logs/
└── data/
```

## 版本定位

V7 的重點不是再疊更多指標，而是把系統逐步拉向：

- 更像真正交易者的結構思維
- 更少機械式 ATR 模板
- 更清楚的多時間框架分層
- 更完整的風控、研究與通知鏈路

後續若要再深化，優先方向會是：

1. 三策略的結構型進場繼續深化
2. soft stop / hard stop 與結構區管理再細化
3. 日內節奏與風險分級更精準化
