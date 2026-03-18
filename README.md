# TradingBrain V6

> 幣安合約自動交易研究系統 · Testnet 優先 · 可重播分析日誌

Python 後端 + FastAPI + React 儀表板，三策略自適應市場狀態，以完整決策鏈日誌為核心。

---

## 目錄

- [快速啟動](#快速啟動)
- [系統架構](#系統架構)
- [三大策略](#三大策略)
- [風控模型](#風控模型)
- [風控預設方案](#風控預設方案)
- [研究日誌](#研究日誌)
- [專案目錄](#專案目錄)

---

## 快速啟動

**後端（交易引擎）**
```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

**啟動器（推薦入口）**
```bash
python launcher.py
# → 控制台：http://localhost:8899
```

**前端開發模式**
```bash
cd frontend && npm install && npm run dev
# → http://localhost:5173（自動代理 API 至 :8888）
```

**測試**
```bash
python -m pytest -q   # 78 個測試，全過為正常
```

---

## 系統架構

```
WebSocket K 線串流
    │
    ▼
技術分析引擎（指標計算）
    │
    ▼
MTF 多時間框架門控
  4h → Regime 分類 + 大趨勢方向
  1h → 方向確認篩選
  15m → 進場 Setup 產生
  1m  → 進場觸發 / Breakout Retest 確認
    │
    ▼
三大策略評估 ──→ 否決引擎（Veto）
    │
    ▼
風控核心（止損 / 倉位 / 每日限額）
    │
    ▼
Binance 執行 ──→ Telegram 通知 ──→ SQLite 研究日誌
```

### Regime 分類

| 狀態 | 觸發條件 | 可用策略 |
|------|---------|---------|
| `TRENDING` | ADX ≥ 25、DI 擴張、BB 寬度適中 | Trend Following、Breakout |
| `RANGING` | ADX 低、BB 窄、方向不明 | Mean Reversion |
| `VOLATILE` | ATR ratio 過高、BB 過寬 | 全部暫停 |

---

## 三大策略

### 1. Trend Following — 趨勢跟蹤

適用：`TRENDING` Regime

| 條件 | 說明 |
|------|------|
| EMA 交叉 | EMA9/21 最近 5 根內交叉，且當前維持方向 |
| 趨勢堆疊 | EMA21 > EMA50、EMA50 上升、close > EMA50 |
| 動量確認 | ADX ≥ 25、DI+ > DI-、RSI 52–68、MACD histogram 正向擴大 |
| Confluence | K 線形態 / Fib 支撐 / RSI 背離，至少命中一項 |
| 加分項 | close 突破前高 → strength +0.1 |

風險比重：**0.8** · SL：1.5 ATR · TP3：5.0 ATR

---

### 2. Breakout Retest — 突破回測確認

適用：`TRENDING` Regime

```
15m BB 突破偵測
  ↓ 放量 ≥ 1.5x、ADX 連升 3 根、實體比 ≥ 35%
建立 Pending Entry（等待 1m 回測）
  ↓ 價格回到突破位 ±0.35% 帶內
1m 確認
  ↓ close 回突破方向 + 綠 K + 在 EMA9 上方
進場（45 分鐘內未確認則作廢）
```

風險比重：**1.0** · SL：2.0 ATR · TP3：4.5 ATR

---

### 3. Mean Reversion — 均值回歸

適用：`RANGING` Regime（豁免 MTF 4h/1h 方向門控）

| 條件 | 多單 | 空單 |
|------|------|------|
| BB 接觸 | close 距下軌 ≤ 2% | close 距上軌 ≤ 2% |
| RSI 極端 | RSI ≤ 35 | RSI ≥ 65 |
| 反轉確認 | 當根收漲 + 前根比較 | 當根收跌 + 前根比較 |
| 加分項 | 背離 / 看漲形態 | 背離 / 看跌形態 |

風險比重：**0.7** · SL：1.25 ATR · TP2 即最終出場

---

## 風控模型

### 倉位計算

```
有效風險 = max_risk_per_trade × 策略比重 × 信號強度倍數（上限 1.3x）
倉位大小（USDT） = 帳戶餘額 × 有效風險 / 止損距離%
```

### 止損與止盈

止損從市場結構（Swing Low/High + Fibonacci）計算，ATR 作為 Floor：

| 策略 | Stop ATR Floor | TP1 | TP2 | TP3 |
|------|---------------|-----|-----|-----|
| Breakout / Retest | 2.0 ATR | 1.5 | 3.0 | 4.5 |
| Trend Following | 1.2 ATR | 2.0 | 3.5 | 5.0 |
| Mean Reversion | 0.8 ATR | 1.0 | 1.8 | — |

> Structure 止盈只允許讓目標更遠（不允許比 ATR 模板更近），確保 RR 合理。

### TP 後追蹤機制

```
TP1 達標 → 平倉 25–40% → 止損移至成本（break-even）
TP2 達標 → 再平倉 25–35% → 止損移至 TP1
TP3 / Trailing SL → 剩餘倉位由 ATR trailing stop 追蹤
```

### 其他風控閘道

- **同標的冷卻**：同幣同方向 2 小時內不重複開倉
- **相關性封鎖**：BTCUSDT + ETHUSDT 不允許同方向同時持倉
- **每日損失上限** / **回撤熔斷** / **連續虧損冷卻**
- **否決引擎**：恐懼貪婪指數 / 資金費率 / 連環爆倉 / VOLATILE 市場 → 暫停開倉

---

## 風控預設方案

在 `config/risk_defaults.json` 設定 `"active_preset"`：

| 預設名稱 | 每單風險 | 最大槓桿 | 適合情境 |
|---------|---------|---------|---------|
| `conservative` 保守型 | 1% | 3x | 低波動期、資金保護優先 |
| `moderate` 穩健型 | 2% | 5x | 日常運行推薦 |
| `passive_income` 被動收入型 ⭐ | 3% | 5x | **當前啟用**，三階段止盈 |
| `aggressive` 積極型 | 4% | 10x | 高信心趨勢市 |
| `training` 訓練型 | 5% | 10x | Testnet 壓力測試 |

---

## 服務端口

| 服務 | 地址 |
|------|------|
| 交易引擎 + Dashboard API | `http://localhost:8888` |
| 啟動器控制台 | `http://localhost:8899` |
| 前端開發伺服器 | `http://localhost:5173` |

---

## 研究日誌

每根 15m K 線關閉時記錄完整決策鏈快照：

```
NO_SIGNAL
  └─ VETOED
       └─ PENDING_TRIGGER
            ├─ BREAKOUT_PENDING → BREAKOUT_RETEST_HIT → BREAKOUT_CONFIRMED
            └─ TRADED
```

```
logs/
├── trading_YYYY-MM-DD.log     # 完整運行日誌
└── daily_reports/             # 每日績效報告（UTC 00:00 自動產生）

data/
└── trading_brain.db           # SQLite（trades / signals / analysis_logs）
```

---

## 專案目錄

```
tradingbrain/
├── main.py                  # 交易引擎主程式（WebSocket + 策略 + 執行）
├── launcher.py              # 啟動器（控制台 UI + Bridge）
├── config/
│   ├── settings.py          # 所有可調參數（端口 / 幣種 / 槓桿）
│   └── risk_defaults.json   # 風控預設方案（切換 active_preset）
├── core/
│   ├── analysis/            # 技術指標（EMA / ATR / RSI / MACD / BB / CHOP / MTF）
│   ├── strategy/            # 三大策略 + Regime 分類 + 信號聚合器
│   ├── risk/                # 止損計算 / 倉位計算 / 出場模板 / 風控主管
│   ├── execution/           # Binance 客戶端 / 持倉管理 / TP-SL 追蹤
│   └── pipeline/            # 排程器 / 否決引擎 / 資金費率 / 恐懼貪婪
├── api/                     # FastAPI 路由（風控 / 信號 / 交易 / K 線）
├── frontend/                # React + Vite 儀表板
├── database/                # SQLite 模型與 DB 管理器
├── notifications/           # Telegram 通知層
├── tests/                   # Pytest 測試套件（78 個測試）
└── scripts/                 # 驗證與研究腳本
```

---

> **注意**：本系統以 Testnet / Demo 優先。正式實盤前請完成充分驗證，累積至少 30 筆已平倉交易後再評估策略有效性。
