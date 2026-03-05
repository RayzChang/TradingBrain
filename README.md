<div align="center">

# 🧠 TradingBrain v4

### _Cyberpunk Edition_

**加密貨幣 AI 自動交易系統**

> 市場狀態自適應策略 × 多時間框架分析 × 智慧風控 × Cyberpunk UI
>
> **30 天回測：5,000U → 13,053U (+161%)，日均 +5.37%**

---

![](https://img.shields.io/badge/版本-v4.0-blueviolet?style=for-the-badge)
![](https://img.shields.io/badge/引擎-Python_3.11-blue?style=for-the-badge)
![](https://img.shields.io/badge/前端-React_+_Vite-cyan?style=for-the-badge)
![](https://img.shields.io/badge/交易所-Binance_Futures-yellow?style=for-the-badge)

</div>

---

## ⚡ v4 新功能

| 功能 | 說明 |
|------|------|
| 🎨 **Cyberpunk UI** | 霓虹紫藍 Glassmorphism 設計、掃描線動畫、即時 K 線蠟燭圖 |
| 📊 **專業 K 線圖** | EMA7/25/99、布林通道、MACD、RSI 指標切換，1 秒即時更新 |
| 🔍 **選幣器** | 20 幣種 24h 行情總覽、漲跌排序、點擊即時預覽 K 線 |
| 🧠 **決策管道** | 即時視覺化信號通過/否決狀態 |
| 📱 **LINE 通知** | 啟動通知 + 開單/平倉 + 每日績效報告 |

---

## 系統架構

```
K 線數據 (WebSocket 15m/1h/4h)
       ↓
  技術分析引擎 → 指標 + 斐波那契 + K線型態 + 背離 + MTF
       ↓
  市場狀態偵測 (ADX ≥ 20 = 趨勢 / ADX < 20 = 震盪)
       ↓
  ┌─ 趨勢狀態 → 趨勢追蹤策略 + 突破策略
  └─ 震盪狀態 → 均值回歸策略
       ↓
  MTF 方向過濾（信號必須與大時間框架趨勢一致）
       ↓
  衝突解決 + 同標的冷卻（2 小時）
       ↓
  否決引擎（恐懼貪婪指數、資金費率、爆倉偵測、絞肉機偵測）
       ↓
  風控（3% 風險 / 5x 槓桿 / SL=1.5ATR / TP=4ATR）
       ↓
  部分止盈 50% @ 2ATR → trailing stop 1.5%
       ↓
  幣安合約 API 執行下單
       ↓
  LINE 即時通知 + Cyberpunk Web 儀表板
```

---

## 三大策略

| 策略 | 適用市場 | 進場邏輯 | 30天回測 |
|------|----------|----------|----------|
| **趨勢追蹤** | ADX ≥ 20 | EMA 交叉 + ADX + K線型態 + 斐波那契 + 背離 | 124筆, 50.8% WR, +3,452U |
| **突破** | ADX ≥ 20 | 布林帶突破 + 量增 1.5x + ADX 連升 + MACD | 126筆, 55.6% WR, +4,601U |
| **均值回歸** | ADX < 20 | BB上下軌 + RSI 超買超賣 + K線反轉 | 市場自適應切換 |

---

## 回測成績（30 天 / 10 幣種）

| 指標 | 數值 |
|------|------|
| 初始 → 最終 | 5,000U → 13,053U |
| ROI | **+161%** |
| 日均 ROI | **+5.37%** |
| 總交易 | 250 筆 |
| 勝率 | 53.2% |
| 獲利因子 | 1.34 |
| 最大回撤 | 31.8% |

---

## 快速開始

### 1. 環境建置

```bash
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

### 2. 前端安裝（首次）

```bash
cd frontend
npm install
npm run build
cd ..
```

### 3. 啟動控制台

```bash
python launcher.py
```

瀏覽器自動開啟 `http://localhost:8899`，點擊**啟動**按鈕即可。

| 介面 | 網址 | 說明 |
|------|------|------|
| 控制台 | `localhost:8899` | 啟動/停止交易大腦 |
| 儀表板 | `localhost:8888` | Cyberpunk 即時儀表板（帳號 admin / changeme） |

---

## 風控機制

| 參數 | 值 | 說明 |
|------|-----|------|
| 每單風險 | 3% | 最多虧 150U/單（5000U 本金） |
| 最大槓桿 | 5x | 放大但不瘋狂 |
| 止損 | 1.5 ATR | 給足空間不被洗出 |
| 止盈 | 4.0 ATR | 讓利潤跑遠 |
| 部分止盈 | 2.0 ATR | 50% 先落袋 |
| Trailing | 1.5% | 剩 50% 跟蹤最高價 |
| 每日停損 | 6% | 虧 300U 即停 |
| 最大持倉 | 3 | 分散風險 |

---

## 專案結構

```
├── launcher.py                  # ⭐ 控制台啟動器
├── main.py                      # 交易引擎入口
├── config/                      # 設定檔
├── core/
│   ├── analysis/                # 技術分析引擎（RSI, MACD, BB, ADX, ATR, EMA...）
│   ├── strategy/                # 交易策略（趨勢/突破/均值回歸）
│   ├── execution/               # 幣安合約 API 客戶端 + 持倉管理
│   ├── risk/                    # 風險管理
│   ├── pipeline/                # 資訊管線（資金費率、恐懼貪婪、爆倉）
│   └── brain/                   # 大腦狀態管理
├── api/                         # FastAPI 後端
│   └── routes/                  # API 路由（K線、信號、交易、風控）
├── frontend/                    # React + Vite Cyberpunk 儀表板
│   └── src/
│       ├── components/          # Sidebar、KlineChart、StatCard、DecisionPipeline
│       └── pages/               # Dashboard、Market、Screener、Signals、Trades
├── notifications/               # LINE 推送
├── database/                    # SQLite 資料庫
└── scripts/                     # 回測腳本
```

---

## LINE 通知設定

1. [LINE Developers](https://developers.line.biz/) 建立 Messaging API Channel
2. 取得 **Channel Access Token** → 填入 `.env` 的 `LINE_CHANNEL_ACCESS_TOKEN`
3. 取得你的 **User ID** → 填入 `LINE_USER_ID`

通知內容：🚀 啟動通知 · 📊 監控快報 · 📋 每日績效

---

## 版本歷史

### v4.0 — Cyberpunk UI 大升級 (2026-03-05)
- 全新 Cyberpunk Glassmorphism 前端（霓虹紫藍、掃描線、毛玻璃卡片）
- 專業 K 線蠟燭圖 + EMA/BOLL/MACD/RSI 指標
- 選幣器（20 幣種 24h 行情 + K 線預覽）
- 決策管道即時視覺化
- 1 秒即時更新 K 線
- 自訂幣種搜尋 + 6 時間框架

### v3.2 — 決策日誌 + 幣種擴充 (2026-03-04)
- 決策日誌系統（覆盤用完整決策鏈記錄）
- Watchlist 10 → 20 幣種
- K 線快取 200 → 500 根

### v3.1 — 健康檢查修復 (2026-03-04)
- 風控設定保護、DB 實例統一、API Rate Limit 保護
- 連線池、線程安全、前端動態 hostname

### v3.0 — 策略重大升級 (2026-02-27)
- 市場狀態自適應（ADX 趨勢/震盪切換）
- 突破策略 + 部分止盈 + Trailing Stop + MTF 過濾
- 控制台啟動器 (`python launcher.py`)

---

## ⚠️ 安全提醒

- **不要把 `.env` 上傳到 Git**（已在 .gitignore 中）
- **API Key 只開合約交易權限，不開提幣**
- **先用 Demo/Testnet 測試至少 1-2 週再考慮實盤**
- **回測 ≠ 實盤，過去表現不代表未來**

---

<div align="center">

**Made with � by TradingBrain v4 — Cyberpunk Edition**

</div>
