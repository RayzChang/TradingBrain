# TradingBrain Progress

## V9 Risk Overhaul (2026-03-22)

### Problem
OP 均值回歸 50x 槓桿、TP1 只有 0.24%（賺 2.37U），連手續費都不夠付。倉位太小（64U 保證金），槓桿太高，TP 太近。

### Changes
1. **策略槓桿上限** — `position_sizer.py`
   - Trend Following: 20x / Breakout: 25x / Mean Reversion: 15x
   - `leverage = min(coin_max_leverage, strategy_cap)`
   - 不再出現 OP 50x、BTC 125x 的瘋狂槓桿

2. **C 級信號不開倉** — `position_sizer.py`
   - 信心度 < 0.5（C tier）直接 reject
   - 系統自己都不確定的訊號不值得花錢試

3. **均值回歸最低風報比 1.0 → 1.5** — `exit_profiles.py`
   - 風報比不夠的均值回歸單直接不開

4. **手續費感知 TP 地板** — `stop_loss.py`
   - TP 最低百分比 = max(固定地板, 來回手續費 × 2.5)
   - `compute()` 新增 `leverage` 參數
   - `risk_manager.py` 傳入策略有效槓桿

5. **提高基礎保證金** — `position_sizer.py`
   - `DEFAULT_MARGIN_LOW`: 100 → 200（高槓桿幣種）
   - `DEFAULT_MARGIN_HIGH`: 500 → 600（低槓桿幣種）

### V8 → V9 Console & Notification Changes (2026-03-21)
- Console 輸出改造：loguru 過濾器只顯示 `console=True` 或 ERROR+
- 心跳改為 1 分鐘，顯示餘額/持倉/未實現盈虧/幣價
- 15m 分析批次輸出，只顯示有事件的幣種
- Telegram 啟動通知改全中文
- 開倉通知價格套用 `fmt_price()` 智能格式化
- pytest 不再發真的 Telegram 通知

### Validation
- `python -m pytest -q` → `98 passed`

---

## Runtime Tuning Override (2026-03-20 Signal Decay Diagnostics)

- Daily report now includes a signal-chain funnel built from `analysis_logs` plus archived trading-log markers.
  - candidates
  - regime gate blocks
  - MTF gate blocks
  - veto pass/block
  - pending created
  - trigger confirmed / expired
  - breakout retest hit / confirmed / expired
  - MTF re-check block
  - risk blocked
  - executed
- Added explicit observation-only markers for later daily summaries:
  - `REGIME_GATE_BLOCK`
  - `TRIGGER_CONFIRMED`
  - `TRIGGER_EXPIRED`
  - `BREAKOUT_EXPIRED_TIMEOUT`
- Daily markdown/history payload now persists:
  - signal bottleneck stage
  - candidate/executed strategy distribution
  - candidate/executed LONG-vs-SHORT distribution

## Phase Status Snapshot (2026-03-19)

| Phase | 名稱 | 狀態 | 備註 |
| --- | --- | --- | --- |
| 1 | Regime 重構 | complete | 2026-03-11 完成並通過驗證 |
| 2 | Breakout Retest | complete | 2026-03-14 已完成狀態機與 logging |
| 3 | MTF 對齊升級 | complete | 2026-03-14 已上線 4h/1h gate |
| 4 | Exit Template 拆分 | complete | 2026-03-14 已拆成三策略模板 |
| 5 | Position Sizing | complete | 2026-03-14 已有 conviction tier 與 risk weight |
| 6 | 研究型 Logging | complete | 2026-03-14 已落地 metadata 與 regime observation |

## Runtime Tuning Override (2026-03-19 P0/P1/P2 Consensus Fixes)

- P0: 結構止損的 ATR floor 保底已重新接回
  - [`C:\Users\RAYZ\Desktop\coding\tradingbrain\core\risk\stop_loss.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\core\risk\stop_loss.py)
  - 當 structure stop 太靠近 entry 時，會依策略 family 使用最小 ATR 距離拉開
- P0: runtime 資金規格已對齊 5000U
  - [`C:\Users\RAYZ\Desktop\coding\tradingbrain\config\settings.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\config\settings.py)
  - [`C:\Users\RAYZ\Desktop\coding\tradingbrain\.env`](C:\Users\RAYZ\Desktop\coding\tradingbrain\.env)
  - [`C:\Users\RAYZ\Desktop\coding\tradingbrain\config\risk_defaults.json`](C:\Users\RAYZ\Desktop\coding\tradingbrain\config\risk_defaults.json)
- P1: 1m trigger 前會重新驗證當前 MTF 方向
  - [`C:\Users\RAYZ\Desktop\coding\tradingbrain\main.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\main.py)
  - 衝突時記錄 `MTF_RECHECK_BLOCK`
- P1: `position_check` 現在有 30 秒 timeout，避免卡住整個 scheduler
- P1: soft stop 現在支援 `1m 連續收破` 或 `5m 單根完整收破`
  - [`C:\Users\RAYZ\Desktop\coding\tradingbrain\core\execution\position_manager.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\core\execution\position_manager.py)
- P2: mean reversion 最低風報比提高到 `1.0`
  - [`C:\Users\RAYZ\Desktop\coding\tradingbrain\core\risk\exit_profiles.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\core\risk\exit_profiles.py)
- P2: signal strength 現在會影響 1m trigger 與 breakout retest confirm 嚴格度
- P2: 日內節奏規則補成 5000U balance-relative 分檔
  - `+1.6% / +3.0% / +4.0%`
  - `-1.2% / -2.0% / -3.0%`

## Runtime Tuning Override (2026-03-19 Short-Side Symmetry)

- Breakout SHORT pipeline aligned with LONG core gating in [`C:\Users\RAYZ\Desktop\coding\tradingbrain\core\strategy\breakout.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\core\strategy\breakout.py)
  - SHORT no longer hard-requires bearish DI dominance, RSI floor, or extra short-only volume multiplier
  - both LONG and SHORT now share the same hard gate structure:
    - Bollinger band break
    - volume confirmation
    - ADX rising
    - breakout candle body confirmation
  - bearish-specific context is still recorded as metadata:
    - `adx_neg_dominant`
    - `rsi_above_quality_floor`
    - `extra_volume_confirmed`
- Updated tests in [`C:\Users\RAYZ\Desktop\coding\tradingbrain\tests\test_breakout_filters.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\tests\test_breakout_filters.py)
  - SHORT now emits even when bearish DI stack is not dominant, as long as the shared core breakout conditions are valid
  - oversold flushes are no longer hard-blocked if the core breakout is valid
- Validation:
  - `python -m pytest tests/test_breakout_filters.py -q` -> `4 passed`
  - `python -m pytest tests/test_strategy.py -q` -> `6 passed`

## Runtime Tuning Override (2026-03-19 — Structure-First Exit Overhaul)

- Exit management upgraded from single-line stops to dual-layer protection:
  - `soft stop` = structure invalidation confirmed by candle closes
  - `hard stop` = catastrophic protection beyond the invalidation zone
- [`C:\Users\RAYZ\Desktop\coding\tradingbrain\core\risk\structure_levels.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\core\risk\structure_levels.py)
  - structure levels now derive wider structure zones instead of single-point assumptions
  - added stop-zone metadata and target-zone metadata
  - `BTC / ETH`-style large-cap symbols now get materially wider structural breathing room through zone width logic
- [`C:\Users\RAYZ\Desktop\coding\tradingbrain\core\risk\stop_loss.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\core\risk\stop_loss.py)
  - stop planning now returns both `soft_stop_loss` and `hard_stop_loss`
  - structure-based stops no longer get forced back to ATR-style stop placement
  - risk/reward checks are evaluated against the logical `soft stop`, while exchange protection uses the `hard stop`
- [`C:\Users\RAYZ\Desktop\coding\tradingbrain\core\execution\position_manager.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\core\execution\position_manager.py)
  - TP1 no longer auto-moves breakout/trend trades straight to breakeven
  - stop management now waits for confirmed soft-stop closes instead of a single wick touch
  - trailing upgraded from pure ATR-following to recent swing-based structure updates
  - hard stop still exits immediately when catastrophic protection is breached
- [`C:\Users\RAYZ\Desktop\coding\tradingbrain\core\execution\execution_engine.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\core\execution\execution_engine.py)
  - trades now persist `soft_stop_loss`, `hard_stop_loss`, stop-zone fields, and target-zone fields
  - exchange-managed stop orders now use `hard_stop_loss`
  - entry notifications now show both soft and hard stop levels
- [`C:\Users\RAYZ\Desktop\coding\tradingbrain\database\models.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\database\models.py)
- [`C:\Users\RAYZ\Desktop\coding\tradingbrain\database\db_manager.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\database\db_manager.py)
  - database schema extended for soft/hard stop and zone metadata
  - added protection update helper for stop progression and price extremes
- Validation:
  - `python -m pytest tests/test_risk.py -q` -> `21 passed`
  - `python -m pytest tests/test_position_manager.py -q` -> `2 passed`
  - `python -m pytest tests/test_execution.py -q` -> `7 passed`
  - `python -m pytest -q` -> `87 passed`
  - `python -m py_compile ...` -> passed

## Runtime Tuning Override (2026-03-19)

- Transitional-market MTF gate relaxed in [`C:\Users\RAYZ\Desktop\coding\tradingbrain\core\analysis\multi_timeframe.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\core\analysis\multi_timeframe.py)
  - added `LEAN_BULLISH / LEAN_BEARISH` normalization
  - `4h` and `1h` can now contribute partial directional confidence instead of forcing `CONFLICTING`
  - single-sided HTF direction now survives with reduced confidence instead of being discarded outright
- Trend direction classification upgraded in [`C:\Users\RAYZ\Desktop\coding\tradingbrain\core\analysis\indicators.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\core\analysis\indicators.py)
  - `get_trend_direction()` now returns lean tiers before falling back to `NEUTRAL`
- MTF hard gate simplified in [`C:\Users\RAYZ\Desktop\coding\tradingbrain\core\strategy\base.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\core\strategy\base.py)
  - non-ranging strategies only hard-block when there is no `recommended_direction`
  - MTF confidence now scales signal strength instead of killing transitional setups outright
  - `RANGING`-only bypass remains intact
- Transitional-regime deadlock reduced in [`C:\Users\RAYZ\Desktop\coding\tradingbrain\core\strategy\trend_following.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\core\strategy\trend_following.py) and [`C:\Users\RAYZ\Desktop\coding\tradingbrain\core\strategy\breakout.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\core\strategy\breakout.py)
  - `trend_following` and `breakout` now allow both `TRENDING` and `RANGING`
  - non-preferred regime execution in [`C:\Users\RAYZ\Desktop\coding\tradingbrain\core\strategy\base.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\core\strategy\base.py) applies a `0.7x` strength penalty instead of hard-blocking
- Mean reversion risk-reward threshold relaxed in [`C:\Users\RAYZ\Desktop\coding\tradingbrain\core\risk\exit_profiles.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\core\risk\exit_profiles.py)
  - `min_risk_reward: 1.2 -> 0.8`
- Strategy entry gauntlet relaxed for weak/transitional markets
  - [`C:\Users\RAYZ\Desktop\coding\tradingbrain\core\strategy\trend_following.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\core\strategy\trend_following.py)
    - `adx_min: 25 -> 20`
    - RSI windows widened to `45~72` for LONG and `28~55` for SHORT
    - confluence no longer hard-gates entry
    - MACD only needs directional sign, not rising/falling acceleration
    - recent EMA cross window widened from `5` to `10` bars
  - [`C:\Users\RAYZ\Desktop\coding\tradingbrain\core\strategy\mean_reversion.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\core\strategy\mean_reversion.py)
    - reversal OR confirmation can now trigger entry
    - single-confirmation entries receive a `0.75x` strength penalty
  - [`C:\Users\RAYZ\Desktop\coding\tradingbrain\core\strategy\breakout.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\core\strategy\breakout.py)
    - `adx_rising_bars: 3 -> 2`
- Chop detector relaxed in [`C:\Users\RAYZ\Desktop\coding\tradingbrain\core\analysis\chop_detector.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\core\analysis\chop_detector.py)
  - `adx_threshold: 20 -> 17`
  - `false_breakout_threshold: 4 -> 6`
  - trigger score: `0.5 -> 0.6`
  - cooldown: `60/30 -> 30/15`
- Validation:
  - `python -m pytest -q` -> `83 passed`

## Runtime Tuning Override (2026-03-18)

- Structure TP floor protection added in [`C:\Users\RAYZ\Desktop\coding\tradingbrain\core\risk\stop_loss.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\core\risk\stop_loss.py)
  - structure TP can no longer replace ATR TP with a closer target
  - `LONG`: keeps the farther of `structure_tp` and ATR TP
  - `SHORT`: keeps the farther of `structure_tp` and ATR TP
- Mean reversion trigger logic relaxed in [`C:\Users\RAYZ\Desktop\coding\tradingbrain\core\strategy\mean_reversion.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\core\strategy\mean_reversion.py)
  - `long_rsi_ceiling: 26 -> 35`
  - `short_rsi_floor: 74 -> 65`
  - removed `close >= ema21` / `close <= ema21` from reversal confirmation
- RANGING-only strategies now bypass strict directional MTF gate in [`C:\Users\RAYZ\Desktop\coding\tradingbrain\core\strategy\base.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\core\strategy\base.py)
  - avoids blocking `mean_reversion` when `4h/1h` are neutral
- Trend following crossover logic updated in [`C:\Users\RAYZ\Desktop\coding\tradingbrain\core\strategy\trend_following.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\core\strategy\trend_following.py)
  - no longer requires the EMA cross to happen on the current bar
  - now accepts a valid cross within the last `5` bars while structure remains intact
  - `close > prev_high` is now a strength bonus instead of a hard requirement
- `1m` trigger model relaxed in [`C:\Users\RAYZ\Desktop\coding\tradingbrain\main.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\main.py)
  - `trend_following`: core trigger + 3 choose 2 supports
  - `mean_reversion`: core trigger + 2 choose 1 supports
  - pending trigger window widened from `15` to `45` minutes
- Testnet fallback entry path removed from [`C:\Users\RAYZ\Desktop\coding\tradingbrain\main.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\main.py)
- Validation:
  - `python -m pytest -q` -> `78 passed`

## Phase Status Override (2026-03-14)

- Phase 4: `complete`
- Scope: split exit templates for `breakout / breakout_retest`, `trend_following`, and `mean_reversion`
- Shared profile source: [`C:\Users\RAYZ\Desktop\coding\tradingbrain\core\risk\exit_profiles.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\core\risk\exit_profiles.py)
- Updated modules:
  - [`C:\Users\RAYZ\Desktop\coding\tradingbrain\core\risk\stop_loss.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\core\risk\stop_loss.py)
  - [`C:\Users\RAYZ\Desktop\coding\tradingbrain\core\risk\structure_levels.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\core\risk\structure_levels.py)
  - [`C:\Users\RAYZ\Desktop\coding\tradingbrain\core\execution\position_manager.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\core\execution\position_manager.py)
  - [`C:\Users\RAYZ\Desktop\coding\tradingbrain\core\execution\execution_engine.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\core\execution\execution_engine.py)
- Validation:
  - `python -m pytest tests/test_risk.py -q` -> `17 passed`
  - `python -m pytest tests/test_execution.py -q` -> `7 passed`
  - `python -m pytest -q` -> `67 passed`
- Breakout correction: `stop_loss_atr_mult` and `STRUCTURE_STOP_FLOOR` for `breakout / breakout_retest` are both `2.0 ATR`
- Phase 5: `complete`
- Phase 5 scope:
  - strategy risk weights in [`C:\Users\RAYZ\Desktop\coding\tradingbrain\core\risk\position_sizer.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\core\risk\position_sizer.py)
  - signal strength multiplier from `TradeSignal.strength` with `1.3x` cap
  - simplified BTC/ETH same-direction correlation block in [`C:\Users\RAYZ\Desktop\coding\tradingbrain\core\strategy\signal_aggregator.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\core\strategy\signal_aggregator.py)
- Phase 5 validation:
  - `python -m pytest tests/test_risk.py -q` -> `18 passed`
  - `python -m pytest tests/test_strategy.py -q` -> `6 passed`
  - `python -m pytest -q` -> `69 passed`
- Phase 6: `complete`
- Phase 6 scope:
  - 15m analysis logs now include `regime`, `mtf_4h_direction`, `mtf_1h_direction`, `mtf_gate_passed`, `adx`, `bb_width`, `atr_ratio`
  - signal metadata now includes `strategy_risk_weight`, `entry_quality_filter_triggered`, `breakout_retest_status`
  - trades now persist `effective_risk_pct`, `sl_atr_mult`, `structure_stop_floor_triggered`
- Phase 6 validation:
  - `python -m pytest tests/test_risk.py -q` -> `18 passed`
  - `python -m pytest tests/test_execution.py -q` -> `7 passed`
  - `python -m pytest tests/test_strategy.py -q` -> `6 passed`
  - `python -m pytest tests/test_breakout_retest_flow.py -q` -> `3 passed`
  - `python -m pytest -q` -> `69 passed`
- Runtime note: backend restart pending for Phase 6 rollout.

## Runtime Tuning Override (2026-03-17)

- Breakout iteration: widened `breakout / breakout_retest` targets in [`C:\Users\RAYZ\Desktop\coding\tradingbrain\core\risk\exit_profiles.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\core\risk\exit_profiles.py)
  - `tp1_atr_mult = 1.5`
  - `tp2_atr_mult = 3.0`
  - `tp3_atr_mult = 4.5`
- Breakout SHORT setup relaxed in [`C:\Users\RAYZ\Desktop\coding\tradingbrain\core\strategy\breakout.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\core\strategy\breakout.py)
  - removed `close < ema21 < ema50`
  - removed `close < prev_low`
  - reduced short volume threshold from `1.8x` to `1.5x`
- Validation:
  - `python -m pytest tests/test_breakout_filters.py -q` -> `4 passed`
  - `python -m pytest tests/test_risk.py -q` -> `18 passed`
  - `python -m pytest -q` -> `70 passed`
- Runtime note: backend restart completed after this tuning batch.

## 文件用途

這份文件用來追蹤 TradingBrain V7 的六個 Phase 改造計畫與後續調整。
之後每完成一個 Phase，都要更新這份文件，至少補上：

- 實際完成的改動
- 驗證結果
- 是否允許進入下一個 Phase
- 當前風險或待補事項

說明：
- 目前專案已有一批先前的基線修復，例如編碼修復、Telegram 通知、結構型停損骨架、`15m` 候選加 `1m` 觸發、daily report log 等。
- 這些不列入下面六個 Phase 的完成進度。
- 六個 Phase 從本文件建立後開始正式追蹤。

## 當前總狀態

- 專案狀態：可執行，可進行 Testnet / Demo 觀察
- 目前進度：Phase 1 程式實作完成，進入 `1~2 天 Testnet` 驗證觀察期
- 下一步：持續收集 Phase 1 regime observation log，待觀察期結束後跑驗證報表
- Phase gate：Phase 1 驗證通過後，才能進入 Phase 2
- 補充：已依 `2026-03-10 UNIUSDT LONG` 個案分析，對 `trend_following` 加入 entry quality filter，降低高 RSI、貼近布林極值、以及過舊交叉訊號的追價進場
- 補充：已依 `2026-03-12 NEARUSDT / BTCUSDT breakout LONG` 個案分析，對結構型 stop 加入最小 ATR floor，避免 breakout 使用過近的微結構止損
- 補充：已修正 `STRUCTURE_STOP_FLOOR` 方向，先前版本對過近 LONG/SHORT 結構 stop 的保護方向相反，現已更正為真正拉遠 stop 的邏輯
- 補充：已依 2026-03-13 的 regime 驗證結果，加入 Phase 1 穩定化修正：3 根 15m K 棒最短持續時間 + `TRENDING -> RANGING` 需 `ADX < 18` 才允許切回

---

## Phase 1: Regime 重構

### 目標

把目前過度簡化的市場狀態判斷，升級為較穩定的三態模型：

- `TRENDING`
- `RANGING`
- `VOLATILE`

### 改動前

- [`C:\Users\RAYZ\Desktop\coding\tradingbrain\core\strategy\base.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\core\strategy\base.py)
- 目前主要接近：
  - `ADX >= 20 => trending`
  - 否則 `ranging`
- 幾乎沒有 `volatile` 狀態
- 也缺少多因子確認與切換緩衝

### 改動清單

- 重寫 `MarketRegime.detect()`
- 導入 `VOLATILE` 狀態
- Regime 判斷納入以下因子：
  - `ADX`
  - `DI+ / DI-` 差值
  - `BB width`
  - `ATR ratio`
  - `1h / 4h` 支持度
- 補上 regime 切換穩定機制，避免過度頻繁切換
- 讓所有策略都吃同一套 regime 輸出
- 在 veto 層支援 `volatile` 風險處理

### 預計修改檔案

- [`C:\Users\RAYZ\Desktop\coding\tradingbrain\core\strategy\base.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\core\strategy\base.py)
- [`C:\Users\RAYZ\Desktop\coding\tradingbrain\core\pipeline\veto_engine.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\core\pipeline\veto_engine.py)
- [`C:\Users\RAYZ\Desktop\coding\tradingbrain\core\analysis\indicators.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\core\analysis\indicators.py)
- 其他承接 regime 欄位的分析檔案

### 驗證條件

Phase 1 完成後，不可直接進入 Phase 2，必須先跑 `1~2 天 Testnet` 純觀察。

切換計算原則：
- 以主分析節點為準，建議採 `15m` 節點
- 同一幣種相鄰兩次主分析結果若 regime 改變，記為 1 次切換

通過條件：
- 任一單一幣種，單日切換次數 `<= 8`
- 全系統幣種單日切換次數的中位數 `<= 5`

未通過時不可進入下一階段，必須先回頭修正：
- hysteresis
- 最短持續時間
- 門檻敏感度
- HTF 權重
- volatile 誤判過高問題

### 當前狀態

- 狀態：`in_validation`
- 備註：程式實作與本地測試已完成，後端已重啟並開始收集 regime observation

### 實際完成內容（2026-03-11）

- 已把 `MarketRegime.detect()` 升級為多因子三態分類，實作於：
  - [`C:\Users\RAYZ\Desktop\coding\tradingbrain\core\strategy\base.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\core\strategy\base.py)
- 已新增 `RegimeAssessment`，輸出：
  - `market_regime`
  - `regime_scores`
  - `regime_metrics`
  - `regime_reasons`
- Regime 依據已納入：
  - `ADX`
  - `DI+ / DI-` 差值
  - `BB width`
  - `ATR ratio`
  - `1h / 4h` 對齊支持度
  - `chop score`
- 已把 `VOLATILE` 接進 veto 流程：
  - [`C:\Users\RAYZ\Desktop\coding\tradingbrain\core\pipeline\veto_engine.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\core\pipeline\veto_engine.py)
- 已把 regime payload 傳入 signal veto 流程：
  - [`C:\Users\RAYZ\Desktop\coding\tradingbrain\core\strategy\signal_aggregator.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\core\strategy\signal_aggregator.py)
- 已補足 indicator summary，使主流程與 log 能取得 regime 所需欄位：
  - [`C:\Users\RAYZ\Desktop\coding\tradingbrain\core\analysis\indicators.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\core\analysis\indicators.py)
- 已在 `main.py` 每次 `15m` 主分析時寫入一筆 `REGIME_OBSERVATION`：
  - [`C:\Users\RAYZ\Desktop\coding\tradingbrain\main.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\main.py)
- 已新增 regime 驗證報表腳本，供 1~2 天後檢查切換次數：
  - [`C:\Users\RAYZ\Desktop\coding\tradingbrain\scripts\regime_validation_report.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\scripts\regime_validation_report.py)
- 已新增 Phase 1 回歸測試：
  - [`C:\Users\RAYZ\Desktop\coding\tradingbrain\tests\test_regime_phase1.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\tests\test_regime_phase1.py)

### 已完成驗證（2026-03-11）

- `python -m pytest -q`：`44 passed`
- `python -m pytest tests/test_regime_phase1.py -q`：`5 passed`
- `py_compile`：通過
- `python scripts/regime_validation_report.py`：可正常執行

### 尚未完成的驗證

- `1~2 天 Testnet` regime 切換觀察
- 驗證門檻：
  - 任一單一幣種單日切換次數 `<= 8`
  - 全系統中位數 `<= 5`
- 未完成前不得進入 Phase 2
- 備註：`2026-03-12` 已額外補上 `trend_following` 進場品質過濾，屬於 Phase 1 驗證期間的風險抑制調整，不改變 Phase gate
- 備註：`2026-03-12` 已額外補上結構 stop 最小 ATR floor，屬於 Phase 1 驗證期間的風險抑制調整，不改變 Phase gate
- 備註：`2026-03-13` 已額外補上 regime hysteresis，目的是壓低切換中位數與單幣過度抖動；待重啟並觀察新樣本後再重跑 validation report

---

## Phase 2: Breakout Retest + Retest Logging

### 目標

把 breakout 從「突破就追」改為「突破後等回踩確認」，並且從一開始就把 Retest 流程記錄下來。

### 改動前

- [`C:\Users\RAYZ\Desktop\coding\tradingbrain\core\strategy\breakout.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\core\strategy\breakout.py)
- 目前已有量能、動能、K 棒品質等過濾
- 但尚未形成完整的：
  - `pending breakout`
  - `retest`
  - `confirm`
  - `expire`
  狀態機

### 改動清單

- 偵測 breakout 後先建立 `pending breakout`
- 等待價格回踩 breakout level 附近
- 回踩成立後才確認進場
- 超過時限仍未成立則 `expire`
- 若條件反轉或失效則 `cancel`
- 導入 Retest 狀態 logging

### 必記錄狀態

- `BREAKOUT_PENDING`
- `BREAKOUT_RETEST_HIT`
- `BREAKOUT_CONFIRMED`
- `BREAKOUT_EXPIRED`
- `BREAKOUT_CANCELLED`

### 預計修改檔案

- [`C:\Users\RAYZ\Desktop\coding\tradingbrain\core\strategy\breakout.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\core\strategy\breakout.py)
- [`C:\Users\RAYZ\Desktop\coding\tradingbrain\main.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\main.py)
- [`C:\Users\RAYZ\Desktop\coding\tradingbrain\database\db_manager.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\database\db_manager.py)
- 必要時擴充 analysis log 結構

### 驗證條件

- 能清楚追蹤 pending -> retest -> confirm/expire/cancel 全流程
- 可統計：
  - pending 數量
  - retest 成功率
  - confirm 後勝率
  - expire 比例
- Log 必須足以支援兩週後研究 Breakout Retest 是否有效

### 當前狀態

- 狀態：`pending`
- 備註：等待 Phase 1 驗證通過

---

## Phase 3: MTF 對齊升級 + 簡化版相關性控管

### 目標

把目前已有的 `15m` 候選加 `1m` 觸發，升級為更清楚的四層 MTF 架構，並提前加入最重要的簡化版相關性保護。

### 改動前

- 目前已有：
  - `15m / 1h / 4h` 判方向
  - `1m` 做進場觸發
- 但四層分工仍不夠明確
- 尚未限制 `BTC / ETH` 同方向同時持倉

### 改動清單

- 明確定義四層職責：
  - `4h`：大趨勢
  - `1h`：方向過濾
  - `15m`：setup
  - `1m`：進場
- 補強 log，讓每一層的放行與阻擋都可追溯
- 導入簡化版相關性控管：
  - `BTCUSDT` 與 `ETHUSDT`
  - 不可同時持有同方向單

### 預計修改檔案

- [`C:\Users\RAYZ\Desktop\coding\tradingbrain\main.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\main.py)
- [`C:\Users\RAYZ\Desktop\coding\tradingbrain\core\strategy\base.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\core\strategy\base.py)
- [`C:\Users\RAYZ\Desktop\coding\tradingbrain\core\strategy\signal_aggregator.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\core\strategy\signal_aggregator.py)
- 其他 MTF 分析檔案

### 驗證條件

- 可清楚看出 `4h/1h/15m/1m` 各層決策責任
- Log 可指出哪一層放行或擋下
- `BTC LONG + ETH LONG` 不可同時存在
- `BTC SHORT + ETH SHORT` 不可同時存在

### 當前狀態

- 狀態：`pending`
- 備註：等待 Phase 2 完成

---

## Phase 4: Exit Template 三策略拆分

### 目標

把三種策略的出場模板徹底拆開，不再共用同一套 TP / SL / trailing 設計。

### 改動前

- [`C:\Users\RAYZ\Desktop\coding\tradingbrain\core\risk\stop_loss.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\core\risk\stop_loss.py)
- `mean_reversion` 已經有較專屬的模板
- `breakout` 與 `trend_following` 仍偏共用

### 改動清單

- 為 `breakout` 建立專屬 exit template
- 為 `trend_following` 建立專屬 exit template
- 保留並整理 `mean_reversion` 的短打模板
- 確保 risk manager 與 position manager 都能吃到策略專屬設定

### 預計修改檔案

- [`C:\Users\RAYZ\Desktop\coding\tradingbrain\core\risk\stop_loss.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\core\risk\stop_loss.py)
- [`C:\Users\RAYZ\Desktop\coding\tradingbrain\core\risk\risk_manager.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\core\risk\risk_manager.py)
- [`C:\Users\RAYZ\Desktop\coding\tradingbrain\core\execution\position_manager.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\core\execution\position_manager.py)

### 驗證條件

- 三種策略不再共用同一套出場邏輯
- 回測與 log 可分策略對照 TP / SL / trailing 表現
- 可明確分析哪種出場模板最適合哪一種策略

### 當前狀態

- 狀態：`pending`
- 備註：等待 Phase 3 完成

---

## Phase 5: Position Sizing 升級

### 目標

把目前已完成一部分的結構型 sizing，升級為真正策略化、訊號化的資金分配模型。

### 改動前

- [`C:\Users\RAYZ\Desktop\coding\tradingbrain\core\risk\position_sizer.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\core\risk\position_sizer.py)
- 目前已有：
  - 結構止損距離優先
  - ATR 備援
  - 最大持倉數
  - 最大槓桿限制
- 但仍缺少：
  - `strategy risk weight`
  - `signal strength multiplier`
  - 進一步的相關性控制

### 改動清單

- 加入策略風險權重
- 加入訊號強度乘數
- 導入更完整的相關性資金限制
- 讓高品質單與普通單使用不同火力

### 預計修改檔案

- [`C:\Users\RAYZ\Desktop\coding\tradingbrain\core\risk\position_sizer.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\core\risk\position_sizer.py)
- [`C:\Users\RAYZ\Desktop\coding\tradingbrain\core\risk\risk_manager.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\core\risk\risk_manager.py)
- 視需要調整 signal / aggregator 對 signal strength 的輸出

### 驗證條件

- 不同策略的單筆火力不同
- 高品質訊號的倉位可大於普通訊號
- 相關性集中曝險受到實際控制

### 當前狀態

- 狀態：`pending`
- 備註：等待 Phase 4 完成

---

## Phase 6: 研究型 Logging 與分析報表

### 目標

把系統的資料紀錄升級為可研究、可迭代、可回顧的報表型資料。

注意：
- Retest logging 已提前在 Phase 2 進行
- 這一階段是把整體研究資料補齊

### 改動前

- 目前已有：
  - analysis logs
  - daily report
  - trigger fail reason
- 但還不夠支援完整策略研究

### 改動清單

- 補 regime 切換摘要
- 補 trigger fail 統計
- 補 retest 成功 / 失敗統計
- 補分策略 / 分方向 / 分市場狀態報表
- 讓一兩週後可以直接分析：
  - 哪種 regime 最賺
  - 哪種 breakout 最有效
  - 哪種觸發最常失敗
  - 哪種出場模板效果最好

### 預計修改檔案

- [`C:\Users\RAYZ\Desktop\coding\tradingbrain\database\db_manager.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\database\db_manager.py)
- [`C:\Users\RAYZ\Desktop\coding\tradingbrain\main.py`](C:\Users\RAYZ\Desktop\coding\tradingbrain\main.py)
- [`C:\Users\RAYZ\Desktop\coding\tradingbrain\logs\daily_reports`](C:\Users\RAYZ\Desktop\coding\tradingbrain\logs\daily_reports)
- 報表或分析腳本相關檔案

### 驗證條件

- 不只保留 raw log
- 要能產出具研究價值的統計資料
- 一兩週後可直接用於策略優化回顧

### 當前狀態

- 狀態：`pending`
- 備註：等待前面所有核心 phase 完成

---

## Phase 狀態總表

| Phase | 名稱 | 狀態 | 備註 |
| --- | --- | --- | --- |
| 1 | Regime 重構 | complete | 正式 gate 排除高 Beta 幣種 `APTUSDT`，Phase 1 可進入 Phase 2 |
| 2 | Breakout Retest + Retest Logging | in_progress | Phase 2 第一版狀態機與 logging 已完成，等待人工確認程式碼後再重啟 |
| 3 | MTF 對齊升級 + 簡化版相關性控管 | in_progress | 4h/1h 嚴格硬門檻已完成，等待人工確認程式碼後再重啟 |
| 4 | Exit Template 三策略拆分 | pending | 等待 Phase 3 |
| 5 | Position Sizing 升級 | pending | 等待 Phase 4 |
| 6 | 研究型 Logging 與分析報表 | pending | 等待前面 phase 完成 |

---

## 更新規則

每完成一個 Phase，必須更新本文件以下欄位：

1. 該 Phase 的「當前狀態」
2. 實際完成的改動清單
3. 實際驗證方式與結果
4. 是否允許進入下一個 Phase
5. 若未通過，必須記錄卡住原因與修正方向

## 最近更新

- 2026-03-11：建立初版 `PROGRESS.md`，記錄六個 Phase 計畫、驗證門檻與當前狀態
- 2026-03-11：完成 Phase 1 程式實作，狀態改為 `in_validation`，並加入 regime 驗證腳本與測試結果
- 2026-03-14：`scripts/regime_validation_report.py` 新增 Phase 1 gate 排除幣種欄位，正式 gate 排除高 Beta 幣種 `APTUSDT`
- 2026-03-14：Phase 1 狀態更新為 `complete`
- 2026-03-14：Phase 2 準備開始，第一步先盤點 `core/strategy/breakout.py` 現行進場結構，不先修改策略程式
- 2026-03-14：Phase 2 第一版 `Breakout Retest` 狀態機已接入 `main.py`，包含 `BREAKOUT_PENDING / BREAKOUT_RETEST_HIT / BREAKOUT_CONFIRMED / BREAKOUT_EXPIRED`
- 2026-03-14：Retest 參數採用 `tolerance = 0.35%`、`expire_bars = 3`，confirmed 不使用 volume 門檻
- 2026-03-14：策略交易名稱在 confirm 後改為 `breakout_retest`，但尚未重啟後端，等待人工確認
- 2026-03-14：Phase 3 第一版完成，MTF 方向層改為只由 `4h + 1h` 決定，`15m` 不再參與方向投票
- 2026-03-14：`core/strategy/base.py` 新增 4h / 1h / recommended_direction 三條硬 gate，觸發時寫 `MTF_GATE_BLOCK: {symbol} {reason}`
- 2026-03-14：`testnet_fallback` 已明確停用，避免正式測試期間繞過 MTF 模型
