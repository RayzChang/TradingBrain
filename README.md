# TradingBrain — 你的加密貨幣交易小幫手

> 用技術指標自動看盤、用風控保護本金，目標是穩健的被動收入。  
> **先回測 → 再模擬（Testnet）→ 最後才用真錢（實盤）**，一步都不能省。

---

## 這個程式在做什麼？（用白話說）

- **24 小時幫你看 K 線**：不用自己盯盤，程式會接交易所的即時數據。
- **幫你算技術指標**：例如 RSI、MACD、背離、斐波那契、多時間框架趨勢，你看不懂的圖表，程式幫你算。
- **用「否決權」過濾**：不會因為一則新聞就亂下單；只有技術面出現信號、且大環境（資金費率、恐懼貪婪指數等）沒亮紅燈時，才會考慮出手。
- **風控先於賺錢**：每筆虧多少、一天最多虧多少、連虧幾次要休息，都可以在儀表板裡調，嚴格控管風險。
- **模擬練功再上實盤**：先用幣安 Testnet（假錢）跑 2～4 週，確認邏輯沒問題，再考慮用真金白銀。

所以：**你需要準備的「個人數據」主要是兩類 — 交易所 API、以及（選用）LINE 通知**。下面按階段整理，並用最白話的方式說明怎麼填。

---

## 一、你需要準備的「個人數據」總覽（P1～P8）

| 項目 | 什麼時候需要 | 去哪裡拿 | 必填嗎 |
|------|--------------|----------|--------|
| **幣安 API Key** | 模擬交易（P8）與實盤（P9） | 幣安官網 → API 管理 | 要跑模擬/實盤就必填 |
| **幣安 API Secret** | 同上 | 建立 API 時一併產生，只顯示一次 | 同上 |
| **LINE Channel Access Token** | 每日報告、心跳異常通知（P8） | LINE Developers 建立 Messaging API 頻道 | 選填（不填就不發 LINE） |
| **LINE User ID** | 同上，指定要推給誰 | 用 LINE 登入後從 Developers 或 Bot 取得 | 選填 |
| **儀表板帳號密碼** | 登入 Web 風控頁（P6） | 自己設 | 建議改掉預設 |
| **SECRET_KEY** | API 後台用 | 自己設一組亂數 | 建議改 |

其餘如 `LOG_LEVEL`、`TRADING_INITIAL_BALANCE`、`TRADING_MODE`、`BINANCE_TESTNET` 在 `.env` 裡都有預設值，第一次可以不用改，之後想微調再動即可。

---

## 二、分階段說明：什麼時候要填什麼

### P1～P5：本地跑邏輯、不碰錢

- **不用填 API 或金鑰**也能跑：風控參數、技術分析、策略、排程都會動，只是不會真的下單。
- 若想先「感受一下」儀表板，可以只改 **儀表板帳密** 和（建議）**SECRET_KEY**，其餘先留空或預設。

### P6：Web 儀表板

- 要登入儀表板時，請在 `.env` 設定：
  - `DASHBOARD_USERNAME`、`DASHBOARD_PASSWORD`：改成你自己的帳密（預設是 `admin` / `changeme`）。
  - `SECRET_KEY`：隨便一組長字串（例如用密碼產生器），不要用預設的 `dev-secret-key-change-in-production`。

### P7：回測

- 回測只用本機的 K 線資料（Parquet）與設定，**不需要**幣安 API。
- 若還沒抓過 K 線，要先跑過 main 或單獨抓一次 K 線，讓 `data/klines/` 裡有對應的 `{symbol}_{timeframe}.parquet`。

### P8：模擬交易（Testnet）

- **必填**：
  - **幣安 Testnet API Key / Secret**  
    到 [Binance Futures Testnet](https://testnet.binancefuture.com/) 登入（或註冊 Testnet 帳號）→ 右上角頭像 → API Management → 建立 API，權限至少勾選「合約交易」；**不要勾提幣**。  
    把產生的 **API Key** 和 **Secret** 填進 `.env` 的 `BINANCE_API_KEY`、`BINANCE_API_SECRET`。
  - `.env` 裡 `BINANCE_TESTNET=true` 保持為 `true`，程式才會用 Testnet 而不是真錢。
- **選填**：
  - **LINE**：若希望每天收到「每日報告」、或系統異常時收到「心跳告警」，再填 `LINE_CHANNEL_ACCESS_TOKEN` 和 `LINE_USER_ID`（取得方式見下一段）。

### P9：實盤（真錢）

- 改用**正式站**的 API：到 [Binance 官網](https://www.binance.com/) → API 管理 → 建立 API，同樣只開「合約交易」、不開提幣，建議綁定 IP。
- 在 `.env` 把 `BINANCE_TESTNET=false`，並把 `BINANCE_API_KEY`、`BINANCE_API_SECRET` 換成正式站的 Key/Secret。
- 計畫建議先用 50U 跑約 2 週，穩定後再考慮加碼到 300U。

---

## 三、各項「個人數據」怎麼取得（白話步驟）

### 1. 幣安 API Key / Secret（模擬用：Testnet）

1. 打開：<https://testnet.binancefuture.com/>
2. 用 Email 或 GitHub 註冊/登入（這是**測試網**，不會用到你真實的幣安帳戶）。
3. 右上角頭像 → **API Management**。
4. 新增一組 API，名稱自訂（例如 `TradingBrain`）。
5. 權限只勾 **Enable Futures**（啟用合約）；**不要勾 Withdraw**。
6. 建立後會顯示 **API Key** 和 **Secret**；Secret 只會顯示一次，請複製存好。
7. 在專案根目錄的 `.env` 裡寫上：
   - `BINANCE_API_KEY=你複製的 API Key`
   - `BINANCE_API_SECRET=你複製的 Secret`
   - `BINANCE_TESTNET=true`（模擬階段保持 true）。

### 2. LINE 每日報告 / 心跳通知（選用）

1. 到 [LINE Developers](https://developers.line.biz/) 登入。
2. 建立一個 **Provider**（若還沒有），再建立一個 **Channel**，類型選 **Messaging API**。
3. 在該 Channel 的設定頁：
   - **Channel access token**（長期）：發行或重新發行，複製下來 → 貼到 `.env` 的 `LINE_CHANNEL_ACCESS_TOKEN`。
   - **Your user ID**：若頁面有顯示，可直接用；否則要用「讓 Bot 加你好友後，發一則訊息，再從 Webhook 或 Log 查你的 User ID」的方式取得，填進 `.env` 的 `LINE_USER_ID`。
4. LINE 免費方案約 200 則/月；程式設計成「每日一則報告 + 異常才發心跳」，一般用量不會爆。

### 3. 儀表板帳號密碼與 SECRET_KEY

- 在 `.env` 裡改：
  - `DASHBOARD_USERNAME=你要的帳號`
  - `DASHBOARD_PASSWORD=你要的密碼`
  - `SECRET_KEY=一組隨機長字串`（可線上產生一組 32 字元以上亂數）

---

## 四、第一次使用：從零到跑起來（白話步驟）

### 步驟 1： clone 專案 + 裝環境

```bash
# 把專案抓下來（若你還沒 clone）
git clone https://github.com/RayzChang/TradingBrain.git
cd TradingBrain

# 建立 Python 虛擬環境（等於幫這個專案單獨裝一套 Python 套件，不影響電腦其他程式）
python -m venv venv

# 啟動虛擬環境
# Windows:
venv\Scripts\activate
# Mac/Linux:
# source venv/bin/activate

# 安裝依賴（程式需要的一堆套件）
pip install -r requirements.txt
```

### 步驟 2： 建立並編輯 .env

```bash
# 複製範本（.env 不會被上傳到 Git，你的金鑰只存在自己電腦）
copy .env.example .env   # Windows
# cp .env.example .env   # Mac/Linux

# 用記事本或 VS Code 打開 .env，照上面「二、分階段」與「三、怎麼取得」把該填的填一填。
# 至少先改：DASHBOARD_USERNAME、DASHBOARD_PASSWORD、SECRET_KEY。
# 要跑模擬（P8）再填 BINANCE_API_KEY、BINANCE_API_SECRET，並確認 BINANCE_TESTNET=true。
```

### 步驟 3： 啟動程式

**方式 A：完整系統（建議）**  
程式會同時：跑 K 線、算指標、跑策略與風控、接 Testnet 下單（若已填 API）、並在背景開儀表板 API。

```bash
python main.py
```

**方式 B：只開儀表板（例如只想調風控、看交易紀錄）**

```bash
# 終端 1
python run_api_only.py

# 終端 2
cd frontend
npm install
npm run dev
```

瀏覽器打開：**http://localhost:5173**  
用你在 `.env` 設的 `DASHBOARD_USERNAME` / `DASHBOARD_PASSWORD` 登入。

### 步驟 4： 儀表板裡可以做的事

- **總覽**：看今日損益、未平倉、系統狀態。
- **風控參數**：調整每筆風險%、每日最大虧損、止損倍數等；可一鍵切換「保守 / 穩健 / 積極」方案（若按了沒反應，請確認已儲存或重新整理）。
- **信號 / 交易**：看最近產生的信號與交易紀錄。

---

## 五、重要提醒（安全與心態）

- **不要把 .env 上傳到 Git**：專案已把 `.env` 放在 `.gitignore`，只要你不手動加入，金鑰就不會進版本庫。
- **API 權限最小化**：只開「合約交易」，不開提幣；正式站建議綁定 IP，降低被盜用風險。
- **300U 當學費**：這是用來練系統、練風控的資金，不是保證獲利；被動收入是目標，但請先以「不爆倉、不亂加槓桿」為前提。
- **先 Testnet 再實盤**：P8 用假錢跑 2～4 週，確認邏輯與通知都正常，再考慮 P9 真錢。

---

## 六、專案結構與技術棧（給想細看的人）

- **技術指標觸發，資訊管線否決**：只有技術面給信號，資訊面只用來「擋掉不該做的單」。
- **全局 API 限流**：避免請求太頻繁被交易所 Ban。
- **風控可調**：保守 / 穩健 / 積極三套方案，並可在 Web 上即時改參數。
- **技術棧**：Python 3.11+、FastAPI、React 18 + TypeScript + Tailwind、SQLite-WAL、K 線存 Parquet。

---

## 七、AI 協作與進度

- 新開一個 AI session 時，請先讓 AI 讀 **`AGENT_INSTRUCTIONS.md`**，裡面有語言、版控、結束前要更新進度等規則。
- 專案進度與下一步寫在 **`PROJECT_STATUS.md`**；完整階段計畫在 **`PLAN.md`**。

---

祝你穩健邁向被動收入，有問題就查這份 README 或改 `.env` 對照表即可。
