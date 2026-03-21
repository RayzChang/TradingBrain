# TradingBrain V8

TradingBrain V8 是一套以 **市場結構、K 線確認、分層風控與研究型 logging** 為核心的加密貨幣交易系統，主要用於 Binance Testnet / Demo 觀察、策略迭代與交易研究。

## V8 更新重點

### 固定保證金倉位模型
- 取代 V7 風險百分比計算，改用固定保證金模式（$100-500/筆）
- 根據幣種最大槓桿自動調整：高槓桿幣（BTC 125x）用小保證金，低槓桿幣（ATOM 20x）用大保證金
- 全倉模式（CROSSED），整個帳戶餘額作為保證金，不再切割分配

### 動態止損觀察模式
- 支撐/壓力位 = 警戒線，不是逃跑線
- 價格進入警戒區後分析 1m/5m K 線行為：插針反轉、盤整中、或確認突破
- 連續 2 根 5 分鐘 K 線實體收破才確認止損
- 保留災難硬止損防閃崩

### 策略觸發優化
- MTF Gate 放寬：無方向時降低信號強度而非完全阻擋
- TRENDING 判定門檻降低，讓趨勢跟蹤和突破策略有更多機會
- 均值回歸出場比例調整：TP1 從 75% 降至 30%，新增 TP3，更大利潤空間

### 日內限制放寬
- 利潤減速器門檻提高（1.6%→3%），匹配每日 $50-200U 目標
- 日虧上限提高至 10%，容忍合理的單筆虧損
- 冷卻機制：連虧 3 筆才冷卻 5 分鐘

### Telegram 通知升級
- 開倉/平倉通知格式重新設計
- 新增觀察止損模式標記

## 核心理念

- 結構優先：先看支撐、壓力、箱體、swing high / low
- K 線確認：進場依賴 reclaim、engulfing、higher low / lower high
- 指標輔助：RSI、MACD、ADX、Bollinger Band 只做輔助，不主導交易
- 止損觀察制：到達警戒區後觀察市場行為，不機械式砍倉
- 固定保證金：小保證金 + 幣種最大槓桿，全倉模式扛波動

## 當前策略

- `trend_following`
  - 順勢 pullback continuation
  - 使用 `4h / 1h` 方向、`15m` setup、`1m` trigger

- `breakout_retest`
  - 先建立 breakout setup，再走 retest confirm
  - 適合結構突破後的延續行情

- `mean_reversion`
  - 只在區間或回歸環境中工作
  - V8: 出場比例調整為 30/30/40，新增 TP3 和追蹤止損

## 多時間框架架構

- `4h`：大方向（Regime 分類）
- `1h`：方向過濾
- `15m`：setup 層
- `1m`：進場觸發、retest confirm、持倉保護

## 風控與出場

### V8 觀察止損模式

- **警戒區**：價格到達支撐/壓力位，進入觀察模式
- **觀察分析**：分析 K 線行為（插針 / 盤整 / 突破）
- **確認止損**：連續 2 根 5 分鐘 K 線實體收破才執行
- **災難硬止損**：保留作為極端行情最後防線

### 三套出場模板

- `trend_following` — 保留趨勢延續空間，TP1 25% / TP2 25% / TP3 放飛
- `breakout` — 觀察突破延續，TP1 40% / TP2 35% / TP3 放飛
- `mean_reversion` — V8 改為 TP1 30% / TP2 30% / TP3 放飛（含追蹤止損）

## Position Sizing (V8)

固定保證金模型：

1. 查詢幣種最大槓桿（BTC 125x、ETH 100x、ATOM 20x）
2. 根據槓桿級別決定保證金（$100-500）
3. 名義倉位 = 保證金 × 槓桿
4. 全倉模式，整個帳戶餘額作為保證金
5. 信號強度和策略權重作為保證金倍數調整

## Telegram 通知

系統使用 Telegram 通知，內容包含：

- 啟動通知（含版本、模式、策略組合、風控摘要）
- 每小時監控快報
- 開倉通知（保證金、名義倉位、槓桿、止損模式）
- TP / SL / 觀察止損通知
- 風控攔截通知
- 每日報告

## 啟動方式

### 後端

```bash
python main.py              # 啟動交易引擎（port 8888）
python launcher.py          # 啟動控制面板（port 8899）
```

### 前端

```bash
cd frontend
npm install
npm run dev                 # 開發伺服器（port 5173）
```

## 測試

```bash
python -m pytest -q
```

## 專案結構

```text
tradingbrain/
├── main.py                 # 交易引擎主程式
├── launcher.py             # 控制面板啟動器
├── config/                 # 設定檔（風控參數、環境設定）
├── core/
│   ├── analysis/           # 技術分析（指標、MTF、Fibonacci）
│   ├── strategy/           # 三策略信號生成
│   ├── risk/               # V8 固定保證金倉位、觀察止損、日內限制
│   ├── execution/          # 幣安客戶端、訂單執行、持倉管理
│   └── pipeline/           # 排程、Veto 引擎、監控
├── database/               # SQLite 資料模型
├── notifications/          # Telegram 通知
├── frontend/               # React/TypeScript 儀表板
├── tests/                  # Pytest 測試套件
├── scripts/                # 研究與回測工具
├── logs/                   # 日誌與報告
└── data/                   # SQLite DB、K 線資料
```

## 版本定位

V8 的重點是讓交易系統更貼近真實交易者的思維：

- 固定保證金 + 最大槓桿，簡單直接
- 止損不再機械式碰線就跑，而是觀察市場行為
- 放寬策略觸發門檻，讓三策略都有機會執行
- 日內限制匹配實際收益目標
