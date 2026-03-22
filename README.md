# TradingBrain V9

TradingBrain V9 是一套以 **市場結構、K 線確認、分層風控與研究型 logging** 為核心的加密貨幣交易系統，主要用於 Binance Testnet / Demo 觀察、策略迭代與交易研究。

## V9 更新重點

### 策略級槓桿上限
- 順勢策略上限 20x / 突破策略上限 25x / 均值回歸上限 15x
- 不再使用幣種最大值（BTC 125x、OP 50x 等），從源頭控制風險

### 信號篩選升級
- C 級信號（信心度 < 0.5）直接不開倉，減少垃圾單
- 均值回歸最低風報比從 1.0 提高至 1.5

### 保證金加大
- 固定保證金模式 $200-600/筆（V8 為 $100-500）
- 最低保證金門檻 100U，低於直接拒絕

### 手續費感知 TP 地板
- TP 最低百分比動態計算，確保覆蓋 2.5 倍來回手續費
- TP1 至少 0.8%、TP2 至少 1.5%、TP3 至少 2.5%

### Console 輸出清理
- 心跳每 1 分鐘：顯示餘額、持倉數、未實現盈虧、幣價
- 15m 分析批次輸出，只顯示有事件的幣種
- 開倉/平倉/風控事件有清楚的 console 輸出

### Telegram 通知中文化
- 啟動通知、開倉通知全中文
- 價格智能格式化（fmt_price）

## 核心理念

- 結構優先：先看支撐、壓力、箱體、swing high / low
- K 線確認：進場依賴 reclaim、engulfing、higher low / lower high
- 指標輔助：RSI、MACD、ADX、Bollinger Band 只做輔助，不主導交易
- 止損觀察制：到達警戒區後觀察市場行為，不機械式砍倉
- 固定保證金 + 策略槓桿上限，全倉模式扛波動

## 當前策略

- `trend_following`
  - 順勢 pullback continuation
  - 使用 `4h / 1h` 方向、`15m` setup、`1m` trigger
  - 槓桿上限 20x，risk weight 0.8

- `breakout_retest`
  - 先建立 breakout setup，再走 retest confirm
  - 適合結構突破後的延續行情
  - 槓桿上限 25x，risk weight 1.0

- `mean_reversion`
  - 只在區間或回歸環境中工作
  - 出場比例 30/30/40，有 TP3 和追蹤止損
  - 槓桿上限 15x，risk weight 0.7，最低風報比 1.5

## 多時間框架架構

- `4h`：大方向（Regime 分類）
- `1h`：方向過濾
- `15m`：setup 層
- `1m`：進場觸發、retest confirm、持倉保護

## 風控與出場

### 觀察止損模式

- **警戒區**：價格到達支撐/壓力位，進入觀察模式
- **觀察分析**：分析 K 線行為（插針 / 盤整 / 突破）
- **確認止損**：連續 2 根 5 分鐘 K 線實體收破才執行
- **災難硬止損**：保留作為極端行情最後防線

### 三套出場模板

- `trend_following` — 保留趨勢延續空間，TP1 25% / TP2 25% / TP3 放飛
- `breakout` — 觀察突破延續，TP1 40% / TP2 35% / TP3 放飛
- `mean_reversion` — TP1 30% / TP2 30% / TP3 放飛（含追蹤止損）

### SL 跟隨 TP 調整

- TP1 打到：找新結構止損（均值回歸拉到保本）
- TP2 打到：再更新結構止損，至少拉到入場價
- 持倉中每 5 秒檢查是否有更好的結構止損

## Position Sizing (V9)

固定保證金模型 + 策略槓桿上限：

1. 根據幣種槓桿級別決定基礎保證金（$200-600）
2. 套用策略槓桿上限（順勢 20x / 突破 25x / 均值回歸 15x）
3. 實際槓桿 = min(幣種最大, 策略上限)
4. 保證金 × 信心度倍數 × 策略權重 × 日內節奏調整
5. C 級信號（信心度 < 0.5）直接拒絕
6. 保證金低於 100U 也拒絕
7. 全倉模式，整個帳戶餘額作為保證金

## Telegram 通知

- 啟動通知（含版本、模式、策略組合、V9 風控摘要）
- 每小時監控快報
- 開倉通知（保證金、名義倉位、策略槓桿、止損模式）
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
│   ├── risk/               # V9 固定保證金倉位、策略槓桿上限、觀察止損
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

V9 的重點是在 V8 基礎上收緊風控、杜絕垃圾單：

- 策略槓桿上限取代幣種最大槓桿，從源頭控制風險
- C 級低信心信號不開倉，減少無意義交易
- 保證金加大 + 手續費感知 TP，確保每單有真實利潤空間
- 止損觀察制保留，不機械式碰線就跑
- 通知和文件全面 V9 對齊，版本一致
