# TradingBrain 加密貨幣自動交易系統

USDT 永續合約自動交易系統，具備 24/7 資訊管線、技術分析引擎、風險管理、和 React Web 儀表板。

## 快速開始

### 1. 環境設定

```bash
# 建立 Python 虛擬環境
python -m venv venv
venv\Scripts\activate  # Windows

# 安裝依賴
pip install -r requirements.txt
```

### 2. 配置

```bash
# 複製環境變數範本
copy .env.example .env

# 編輯 .env 填入你的 API 密鑰
```

### 3. 啟動

**完整系統（交易邏輯 + 儀表板 API）**

```bash
python main.py
```

**僅儀表板（前端開發用）**

```bash
# 終端 1：只開 API
python run_api_only.py

# 終端 2：前端
cd frontend && npm install && npm run dev
```

瀏覽器開啟 http://localhost:5173 ，預設帳密 `admin` / `changeme`（可在 .env 設定 DASHBOARD_USERNAME / DASHBOARD_PASSWORD）。

## 系統架構

- **技術指標觸發，資訊管線否決** — 技術面是開單唯一來源
- **全局 API 限流器** — 防止被交易所 Ban
- **風控參數可在 Web UI 即時調整** — 保守/穩健/積極一鍵切換
- **先回測 → 再模擬 → 最後實盤**

## 技術棧

- Python 3.11+ / FastAPI / APScheduler
- React 18 + TypeScript + TailwindCSS
- SQLite-WAL + Parquet
- ccxt + python-binance + ta（技術分析）

## AI 協作

本專案使用 AI 輔助開發。新 session 請先讀取 `AGENT_INSTRUCTIONS.md`。
