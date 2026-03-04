# TradingBrain — 加密貨幣 AI 自動交易系統

> 🤖 市場狀態自適應策略 × 多時間框架分析 × 智慧風控  
> **30 天回測：5,000U → 13,053U (+161%)，日均 +5.37%**

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
  LINE 即時通知 + Web 儀表板
```

---

## 三大策略（v3）

| 策略 | 適用市場 | 進場邏輯 | 30天回測 |
|------|----------|----------|----------|
| **趨勢追蹤** | ADX ≥ 20 (趨勢) | EMA 交叉 + ADX 強度 + K線型態 + 斐波那契 + 背離 | 124筆, 50.8% WR, +3,452U |
| **突破** | ADX ≥ 20 (趨勢) | 布林帶突破 + 量增 1.5x + ADX 連升 + MACD 動能 | 126筆, 55.6% WR, +4,601U |
| **均值回歸** | ADX < 20 (震盪) | BB上下軌 + RSI 超買超賣 + K線反轉型態 | 市場自適應關閉（近期趨勢盤） |

---

## 回測成績（30 天 / 10 幣種）

| 指標 | 數值 |
|------|------|
| 初始 → 最終 | 5,000U → 13,053U |
| ROI | +161% |
| 日均 ROI | **+5.37%** |
| 總交易 | 250 筆 |
| 勝率 | 53.2% |
| 獲利因子 | 1.34 |
| 最大回撤 | 31.8% |

**幣種排名：**
LINK (+2,260) → DOT (+2,068) → ADA (+1,699) → DOGE (+1,006) → AVAX (+844)

---

## 快速開始

### 1. 環境建置

```bash
# 建立虛擬環境
python -m venv venv

# 啟動（Windows）
venv\Scripts\activate

# 安裝依賴
pip install -r requirements.txt
```

### 2. 啟動控制台（⭐ 推薦）

```bash
python launcher.py
```

瀏覽器會自動開啟控制台介面 (`http://localhost:8899`)，這是一個全功能的輕量化控制中心：

1. **首頁總覽** — 控制大腦開關，即時監控幣安合約帳戶實時餘額與今日損益。
2. **信號與明細** — 隨時查閱最新 15 分鐘 MTF 綜合分析信號與所有活躍/歷史開單。
3. **環境設定** — 填入 API Key、切換交易模式、設定自訂槓桿。
4. **系統日誌** — 監控底層過濾器、系統排程、AI 指標與警報的即時滾動輸出。
5. **執行交易所設定** — 第一次使用前，請點擊一鍵設定你的合約槓桿與全倉/逐倉。

> 💡 系統已全面輕量化，不再依賴 Node.js/Vite，以上面板開啟即用，極度省電節能。

### 或者手動操作（進階）

```bash
# 複製設定檔並編輯
copy .env.example .env

# 設定交易所
python setup_testnet.py

# 啟動交易引擎
python main.py
```

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
| 同標的冷卻 | 2 小時 | 避免連續追單 |

---

## 專案結構

```
├── launcher.py                  # ⭐ 控制台啟動器入口（python launcher.py 一鍵啟動）
├── launcher/                    # 控制台模組
│   ├── bridge.py                # Python 後端（.env 管理、大腦控制、日誌）
│   ├── server.py                # FastAPI 控制台 API
│   └── ui/                      # 控制台前端（HTML/CSS/JS）
├── main.py                      # 交易引擎入口
├── setup_testnet.py             # 交易所設定工具
├── config/
│   ├── settings.py              # 全局配置
│   └── risk_defaults.json       # 風控預設（含 passive_income 最佳參數）
├── core/
│   ├── analysis/                # 技術分析引擎
│   │   ├── engine.py            # 多時間框架分析核心
│   │   ├── indicators.py        # RSI, MACD, BB, ADX, ATR, EMA...
│   │   ├── candlestick.py       # K 線型態辨識
│   │   ├── fibonacci.py         # 斐波那契回撤/擴展
│   │   ├── divergence.py        # 背離偵測
│   │   ├── multi_timeframe.py   # MTF 趨勢分析
│   │   └── chop_detector.py     # 絞肉機偵測
│   ├── strategy/                # 交易策略
│   │   ├── base.py              # 基類 + MarketRegime 偵測
│   │   ├── trend_following.py   # 趨勢追蹤策略
│   │   ├── breakout.py          # 突破策略
│   │   ├── mean_reversion.py    # 均值回歸策略
│   │   └── signal_aggregator.py # 信號聚合 + 衝突解決 + 冷却
│   ├── execution/               # 交易執行
│   │   ├── binance_client.py    # 幣安合約 API 客戶端
│   │   └── position_manager.py  # 持倉管理
│   ├── risk/                    # 風險管理
│   ├── pipeline/                # 資訊管線（資金費率、恐懼貪婪、爆倉）
│   └── brain/                   # 大腦狀態管理
├── api/                         # FastAPI 後端（儀表板 API）
├── frontend/                    # React 儀表板
├── notifications/               # LINE 推送
├── docs/                        # 文件（使用說明書）
├── scripts/                     # 回測腳本
│   ├── backtest_v3.py           # 多參數組合回測
│   └── backtest_30d.py          # 30 天完整回測
└── database/                    # SQLite 資料庫
```

---

## LINE 通知設定

1. 到 [LINE Developers](https://developers.line.biz/) 登入
2. 建立 Provider → Channel（類型：Messaging API）
3. Channel 設定頁：
   - **Channel access token** → 填入 `.env` 的 `LINE_CHANNEL_ACCESS_TOKEN`
   - 掃描 QR Code 加入官方帳號為好友
4. 到 [LINE Login API](https://developers.line.biz/) 取得你的 User ID → 填入 `LINE_USER_ID`

系統會自動推送：
- 🚀 啟動通知（含策略和風控參數）
- 📊 定時監控快報（損益、筆數、交易所餘額）
- 📋 每日績效報告

---

## 2026-02-27 v3 更新摘要

### 策略重大升級
- **市場狀態自適應**：ADX ≥ 20 用趨勢+突破策略，ADX < 20 用均值回歸（不再互相打架）
- **新增突破策略**：布林帶突破 + 成交量確認 + ADX 上升 + MACD 動能擴張
- **部分止盈 + Trailing Stop**：50% 在 2ATR 落袋，剩 50% trailing 1.5% 讓利潤跑
- **MTF 方向過濾**：信號必須與 1h/4h 大時間框架趨勢一致
- **衝突解決**：同幣種同時有 LONG+SHORT 信號時只取最強
- **同標的冷卻**：2 小時內不重複交易同幣同方向

### 控制台啟動器（新增）
- ⭐ **`python launcher.py`** 一鍵啟動控制台
- 在瀏覽器介面上完成所有設定和操作（取代手動編輯 `.env`）
- 提供詳細的設定說明和模式對照表
- 即時日誌查看（帶顏色標記）

### 風控調整
- 風險預設切換為 `passive_income`（回測最佳參數）
- Veto Engine 啟用（`relax_veto=false`）
- ADX 門檻 20、RSI 30/70

### 系統改善
- 餘額 API 修復（fallback 到 `/fapi/v2/balance` + `recvWindow` 放寬）
- 儀表板 5 秒自動刷新 + 交易所實際餘額顯示
- LINE 通知加入 [DEMO] 模式標記

---

## 2026-03-04 v3.1 健康檢查修復

### 嚴重修復
- **風控設定保護**：`_load_risk_defaults` 中 `pop()` 會破壞原始預設資料 → 改用 `get()` 非破壞性讀取
- **DB 實例統一**：`main.py` 與 API 各建一個 `DatabaseManager` → 注入共用實例（`set_db()`）
- **API Rate Limit 保護**：`system_status` 每次輪詢都建新 `BinanceFuturesClient` → 30 秒 TTL 快取
- **交易追蹤**：實盤下單未儲存 `exchange_order_id` → 補上交易所單號記錄

### 效能與穩定性
- **設定重載修復**：Launcher 改 `.env` 後啟動仍用舊值 → 級聯 reload 依賴模組
- **連線池**：每次 API 呼叫新建 `httpx.AsyncClient` → 共用連線池
- **線程安全**：`KlineCache` 加 `threading.Lock` 防止 WS/REST 並發寫入衝突
- **簽名清理**：`_sign()` 簡化回傳，移除冗餘 params dict

### 前端與雜項
- 前端 `localhost:8888` 硬編碼 → 動態 `window.location.hostname`
- Launcher API sync/async 風格統一
- `Signals.tsx` 不安全 type assertion 修正
- CORS 補上 8888 來源
- `.gitignore` 補上 build logs / WAL / temp 規則

---

## 安全提醒

- ⚠️ **不要把 .env 上傳到 Git**（已在 .gitignore 中）
- ⚠️ **API Key 只開合約交易權限，不開提幣**
- ⚠️ **先用 Demo/Testnet 測試至少 1-2 週再考慮實盤**
- ⚠️ **回測 ≠ 實盤，過去表現不代表未來**

---

**Made with 🤖 by TradingBrain v3.1**
