"""
策略改善回測模擬 (Strategy Improvement Backtest)

使用幣安公開 API 抓取歷史 K 線，在本地模擬 v2 策略的表現。
不需要 API Key，使用公開端點。

用法: python scripts/backtest_v2.py
"""

import asyncio
import sys
import os
from pathlib import Path
from datetime import datetime, timezone

# 把專案根目錄加入 path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
import pandas as pd
from loguru import logger

from core.analysis.engine import AnalysisEngine, FullAnalysis
from core.analysis.indicators import add_all_indicators
from core.strategy.trend_following import TrendFollowingStrategy
from core.strategy.mean_reversion import MeanReversionStrategy
from core.strategy.base import TradeSignal


# === 回測參數 ===
INITIAL_BALANCE = 5000.0
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
BACKTEST_DAYS = 7  # 模擬 7 天
PRIMARY_TF = "15m"
TIMEFRAMES = ["15m", "1h", "4h"]

# 穩健收入型風控參數
RISK_PARAMS = {
    "max_risk_per_trade": 0.015,
    "stop_loss_atr_mult": 2.0,
    "take_profit_atr_mult": 3.0,
    "max_leverage": 3,
    "max_open_positions": 2,
    "daily_profit_target": 0.02,   # 2% 鎖利
    "max_daily_loss": 0.03,        # 3% 停損
}

# v2 策略參數
STRATEGY_PARAMS = {
    "adx_min": 25,
    "rsi_oversold": 30,
    "rsi_overbought": 70,
    "skip_on_chop": True,
}

# 同標的冷卻秒數
SYMBOL_COOLDOWN_SEC = 4 * 3600  # 4 小時

# 手續費 + 滑點模擬
FEE_RATE = 0.0004  # 0.04% 單邊
SLIPPAGE_RATE = 0.001  # 0.1% 滑點


KLINE_COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "trades", "taker_buy_volume",
    "taker_buy_quote_volume", "ignore",
]


async def fetch_klines(client: httpx.AsyncClient, symbol: str, interval: str, days: int) -> pd.DataFrame:
    """從幣安公開 API 抓取歷史 K 線"""
    all_dfs = []
    end_time = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_time = end_time - days * 86400 * 1000
    current_start = start_time

    while current_start < end_time:
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": 1500,
            "startTime": current_start,
            "endTime": end_time,
        }
        try:
            resp = await client.get("https://fapi.binance.com/fapi/v1/klines", params=params)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning(f"Fetch {symbol} {interval} failed: {e}")
            break

        if not data:
            break

        df = pd.DataFrame(data, columns=KLINE_COLUMNS)
        for col in ["open", "high", "low", "close", "volume", "quote_volume",
                     "taker_buy_volume", "taker_buy_quote_volume"]:
            df[col] = df[col].astype(float)
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
        df["close_time"] = pd.to_datetime(df["close_time"], unit="ms")
        df["trades"] = df["trades"].astype(int)
        df.drop(columns=["ignore"], inplace=True)
        all_dfs.append(df)

        last_ms = int(df["open_time"].iloc[-1].timestamp() * 1000)
        if last_ms <= current_start:
            break
        current_start = last_ms + 1
        await asyncio.sleep(0.2)

    if not all_dfs:
        return pd.DataFrame()

    result = pd.concat(all_dfs, ignore_index=True)
    result.drop_duplicates(subset=["open_time"], keep="last", inplace=True)
    result.sort_values("open_time", inplace=True)
    result.reset_index(drop=True, inplace=True)
    return result


class BacktestTrade:
    """模擬一筆交易"""
    def __init__(self, symbol: str, direction: str, entry_price: float,
                 size_usdt: float, leverage: int, stop_loss: float,
                 take_profit: float, strategy: str, entry_time: str):
        self.symbol = symbol
        self.direction = direction
        self.entry_price = entry_price
        self.size_usdt = size_usdt
        self.leverage = leverage
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.strategy = strategy
        self.entry_time = entry_time
        self.exit_price = 0.0
        self.exit_time = ""
        self.pnl = 0.0
        self.exit_reason = ""
        self.is_open = True

    def check_exit(self, high: float, low: float, close_time: str) -> bool:
        """檢查是否觸發止損或止盈"""
        if not self.is_open:
            return False

        if self.direction == "LONG":
            if low <= self.stop_loss:
                self._close(self.stop_loss, close_time, "STOP_LOSS")
                return True
            if high >= self.take_profit:
                self._close(self.take_profit, close_time, "TAKE_PROFIT")
                return True
        else:  # SHORT
            if high >= self.stop_loss:
                self._close(self.stop_loss, close_time, "STOP_LOSS")
                return True
            if low <= self.take_profit:
                self._close(self.take_profit, close_time, "TAKE_PROFIT")
                return True
        return False

    def _close(self, exit_price: float, exit_time: str, reason: str):
        self.exit_price = exit_price
        self.exit_time = exit_time
        self.exit_reason = reason
        self.is_open = False

        # 計算 PnL（含手續費和滑點）
        if self.direction == "LONG":
            raw_pnl = (self.exit_price - self.entry_price) / self.entry_price * self.size_usdt
        else:
            raw_pnl = (self.entry_price - self.exit_price) / self.entry_price * self.size_usdt

        fee_cost = self.size_usdt * FEE_RATE * 2  # 開平各一次
        slippage_cost = self.size_usdt * SLIPPAGE_RATE
        self.pnl = raw_pnl - fee_cost - slippage_cost


async def run_backtest():
    """執行回測"""
    print("=" * 70)
    print("📊 TradingBrain v2 策略回測模擬")
    print(f"   回測天數: {BACKTEST_DAYS} 天")
    print(f"   初始資金: {INITIAL_BALANCE} USDT")
    print(f"   幣種: {', '.join(SYMBOLS)}")
    print(f"   ADX 門檻: {STRATEGY_PARAMS['adx_min']}")
    print(f"   RSI 超賣/超買: {STRATEGY_PARAMS['rsi_oversold']}/{STRATEGY_PARAMS['rsi_overbought']}")
    print(f"   SL: {RISK_PARAMS['stop_loss_atr_mult']} ATR / TP: {RISK_PARAMS['take_profit_atr_mult']} ATR")
    print(f"   每單風險: {RISK_PARAMS['max_risk_per_trade']*100}%")
    print(f"   最大槓桿: {RISK_PARAMS['max_leverage']}x")
    print(f"   每日鎖利: {RISK_PARAMS['daily_profit_target']*100}%")
    print(f"   每日停損: {RISK_PARAMS['max_daily_loss']*100}%")
    print(f"   同標的冷卻: {SYMBOL_COOLDOWN_SEC//3600} 小時")
    print("=" * 70)
    print()

    # 1. 抓取歷史 K 線
    print("⏳ 正在從幣安抓取歷史 K 線數據...")
    async with httpx.AsyncClient(timeout=30.0) as client:
        kline_data: dict[str, dict[str, pd.DataFrame]] = {}
        for symbol in SYMBOLS:
            kline_data[symbol] = {}
            for tf in TIMEFRAMES:
                # 多抓一些天數讓指標有足夠數據熱身
                extra_days = 30 if tf == "4h" else (10 if tf == "1h" else 3)
                df = await fetch_klines(client, symbol, tf, BACKTEST_DAYS + extra_days)
                if not df.empty:
                    kline_data[symbol][tf] = df
                    print(f"  ✅ {symbol} {tf}: {len(df)} 根 K 線")
                else:
                    print(f"  ❌ {symbol} {tf}: 無數據")
                await asyncio.sleep(0.3)

    # 2. 初始化策略和分析引擎
    engine = AnalysisEngine()
    trend_strategy = TrendFollowingStrategy(
        adx_min=STRATEGY_PARAMS["adx_min"],
        skip_on_chop=STRATEGY_PARAMS["skip_on_chop"],
    )
    mean_revert_strategy = MeanReversionStrategy(
        rsi_oversold=STRATEGY_PARAMS["rsi_oversold"],
        rsi_overbought=STRATEGY_PARAMS["rsi_overbought"],
        skip_on_chop=STRATEGY_PARAMS["skip_on_chop"],
    )
    strategies = [trend_strategy, mean_revert_strategy]

    # 3. 模擬回測
    print()
    print("⏳ 開始回測模擬...")

    balance = INITIAL_BALANCE
    all_trades: list[BacktestTrade] = []
    open_trades: list[BacktestTrade] = []
    symbol_cooldown: dict[tuple[str, str], float] = {}
    daily_pnl: dict[str, float] = {}
    daily_locked: set[str] = set()  # 已鎖利的日期

    # 取得回測開始時間（最近 BACKTEST_DAYS 天）
    now_ts = datetime.now(timezone.utc).timestamp()
    backtest_start_ts = now_ts - BACKTEST_DAYS * 86400

    for symbol in SYMBOLS:
        if PRIMARY_TF not in kline_data[symbol]:
            continue

        primary_df = kline_data[symbol][PRIMARY_TF]
        if len(primary_df) < 100:
            continue

        # 遍歷每根 15m K 線
        for i in range(100, len(primary_df)):
            candle_time = primary_df.iloc[i]["open_time"]
            candle_ts = candle_time.timestamp()

            # 只模擬最近 BACKTEST_DAYS 天
            if candle_ts < backtest_start_ts:
                continue

            current_date = str(candle_time.date())

            # 檢查持倉止損/止盈
            candle = primary_df.iloc[i]
            for trade in list(open_trades):
                if trade.symbol == symbol:
                    closed = trade.check_exit(
                        float(candle["high"]),
                        float(candle["low"]),
                        str(candle_time),
                    )
                    if closed:
                        balance += trade.pnl
                        open_trades.remove(trade)
                        daily_pnl[current_date] = daily_pnl.get(current_date, 0) + trade.pnl

            # 每日熔斷/鎖利檢查
            today_pnl = daily_pnl.get(current_date, 0)
            start_of_day_equity = balance - today_pnl

            # 每日虧損上限
            if today_pnl < -(start_of_day_equity * RISK_PARAMS["max_daily_loss"]):
                continue
            # 每日鎖利
            if today_pnl > 0 and today_pnl >= start_of_day_equity * RISK_PARAMS["daily_profit_target"]:
                if current_date not in daily_locked:
                    daily_locked.add(current_date)
                continue

            # 最大持倉數
            if len(open_trades) >= RISK_PARAMS["max_open_positions"]:
                continue

            # 準備 MTF 分析數據
            mtf_klines: dict[str, pd.DataFrame] = {}
            for tf in TIMEFRAMES:
                if tf not in kline_data[symbol]:
                    continue
                tf_df = kline_data[symbol][tf]
                # 只用回測時間點之前的數據
                mask = tf_df["open_time"] <= candle_time
                subset = tf_df[mask].tail(200)
                if len(subset) >= 50:
                    mtf_klines[tf] = subset

            if len(mtf_klines) < 2:
                continue

            # 執行完整 MTF 分析
            try:
                full = engine.analyze_full(symbol, mtf_klines, PRIMARY_TF)
            except Exception:
                continue

            # 評估策略信號（含 MTF 過濾）
            signals: list[TradeSignal] = []
            for strategy in strategies:
                sigs = strategy.evaluate_full(full, primary_tf=PRIMARY_TF)
                signals.extend(sigs)

            if not signals:
                continue

            # 衝突解決：同幣對 LONG+SHORT 只取最強
            directions = set(s.signal_type for s in signals)
            if "LONG" in directions and "SHORT" in directions:
                signals = [max(signals, key=lambda s: s.strength)]
            else:
                signals = [max(signals, key=lambda s: s.strength)]

            sig = signals[0]

            # 同標的冷卻
            cooldown_key = (sig.symbol, sig.signal_type)
            last_signal_ts = symbol_cooldown.get(cooldown_key, 0)
            if candle_ts - last_signal_ts < SYMBOL_COOLDOWN_SEC:
                continue

            # 已有同幣對持倉 → 跳過
            if any(t.symbol == symbol and t.is_open for t in open_trades):
                continue

            # 風控計算
            primary_result = full.single_tf_results.get(PRIMARY_TF)
            if not primary_result or primary_result.df_enriched is None:
                continue

            entry_price = float(primary_result.df_enriched["close"].iloc[-1])
            atr_val = primary_result.indicators.get("atr")
            if atr_val is None:
                continue
            atr = float(atr_val)
            if atr <= 0 or entry_price <= 0:
                continue

            # 倉位計算
            risk_amount = balance * RISK_PARAMS["max_risk_per_trade"]
            stop_distance_pct = (RISK_PARAMS["stop_loss_atr_mult"] * atr) / entry_price
            if stop_distance_pct <= 0:
                continue
            size_usdt = risk_amount / stop_distance_pct
            cap = balance * RISK_PARAMS["max_leverage"]
            size_usdt = min(size_usdt, cap)

            if size_usdt < 10:
                continue

            # 止損止盈
            sl_dist = RISK_PARAMS["stop_loss_atr_mult"] * atr
            tp_dist = RISK_PARAMS["take_profit_atr_mult"] * atr

            if sig.signal_type == "LONG":
                sl = entry_price - sl_dist
                tp = entry_price + tp_dist
            else:
                sl = entry_price + sl_dist
                tp = entry_price - tp_dist

            leverage = min(RISK_PARAMS["max_leverage"], max(1, int(size_usdt / balance)))

            trade = BacktestTrade(
                symbol=symbol,
                direction=sig.signal_type,
                entry_price=entry_price,
                size_usdt=round(size_usdt, 2),
                leverage=leverage,
                stop_loss=round(sl, 4),
                take_profit=round(tp, 4),
                strategy=sig.strategy_name,
                entry_time=str(candle_time),
            )
            open_trades.append(trade)
            all_trades.append(trade)
            symbol_cooldown[cooldown_key] = candle_ts

    # 強制平倉未平倉位（以最後一根 K 線收盤價）
    for trade in list(open_trades):
        if trade.is_open:
            if trade.symbol in kline_data and PRIMARY_TF in kline_data[trade.symbol]:
                last_candle = kline_data[trade.symbol][PRIMARY_TF].iloc[-1]
                trade._close(float(last_candle["close"]), str(last_candle["open_time"]), "FORCE_CLOSE")
                balance += trade.pnl

    # 4. 輸出結果
    print()
    print("=" * 70)
    print("📊 回測結果")
    print("=" * 70)

    closed_trades = [t for t in all_trades if not t.is_open]
    wins = [t for t in closed_trades if t.pnl > 0]
    losses = [t for t in closed_trades if t.pnl <= 0]
    tp_trades = [t for t in closed_trades if t.exit_reason == "TAKE_PROFIT"]
    sl_trades = [t for t in closed_trades if t.exit_reason == "STOP_LOSS"]

    total_pnl = sum(t.pnl for t in closed_trades)
    win_amount = sum(t.pnl for t in wins) if wins else 0
    loss_amount = sum(t.pnl for t in losses) if losses else 0
    win_rate = len(wins) / len(closed_trades) * 100 if closed_trades else 0
    avg_win = win_amount / len(wins) if wins else 0
    avg_loss = loss_amount / len(losses) if losses else 0
    profit_factor = abs(win_amount / loss_amount) if loss_amount != 0 else float("inf")
    roi = total_pnl / INITIAL_BALANCE * 100

    print(f"\n{'項目':<25} {'數值':>15}")
    print("-" * 42)
    print(f"{'初始資金':<25} {INITIAL_BALANCE:>12.2f} U")
    print(f"{'最終資金':<25} {balance:>12.2f} U")
    print(f"{'總損益':<25} {total_pnl:>+12.2f} U")
    print(f"{'投資報酬率':<25} {roi:>+11.2f}%")
    print(f"{'日均報酬率':<25} {roi/BACKTEST_DAYS:>+11.2f}%")
    print("-" * 42)
    print(f"{'總交易筆數':<25} {len(closed_trades):>12}")
    print(f"{'止盈筆數 (TP)':<25} {len(tp_trades):>12}")
    print(f"{'止損筆數 (SL)':<25} {len(sl_trades):>12}")
    print(f"{'勝率':<25} {win_rate:>11.1f}%")
    print(f"{'獲利因子':<25} {profit_factor:>11.2f}")
    print("-" * 42)
    print(f"{'平均獲利':<25} {avg_win:>+12.2f} U")
    print(f"{'平均虧損':<25} {avg_loss:>+12.2f} U")
    print(f"{'總獲利金額':<25} {win_amount:>+12.2f} U")
    print(f"{'總虧損金額':<25} {loss_amount:>+12.2f} U")
    print(f"{'日均交易筆數':<25} {len(closed_trades)/BACKTEST_DAYS:>11.1f}")

    # 每日明細
    print(f"\n{'日期':<12} {'損益':>10} {'累計':>12}")
    print("-" * 36)
    cum = 0
    for date in sorted(daily_pnl.keys()):
        pnl = daily_pnl[date]
        cum += pnl
        locked = " 🔒" if date in daily_locked else ""
        print(f"{date:<12} {pnl:>+10.2f} {cum:>+12.2f}{locked}")

    # 每個策略的分佈
    print(f"\n{'策略':<22} {'筆數':>6} {'勝率':>8} {'損益':>12}")
    print("-" * 50)
    for strat_name in set(t.strategy for t in closed_trades):
        strat_trades = [t for t in closed_trades if t.strategy == strat_name]
        strat_wins = [t for t in strat_trades if t.pnl > 0]
        strat_pnl = sum(t.pnl for t in strat_trades)
        wr = len(strat_wins) / len(strat_trades) * 100 if strat_trades else 0
        print(f"{strat_name:<22} {len(strat_trades):>6} {wr:>7.1f}% {strat_pnl:>+12.2f}")

    # 每個幣種的分佈
    print(f"\n{'幣種':<12} {'筆數':>6} {'勝率':>8} {'損益':>12}")
    print("-" * 40)
    for sym in SYMBOLS:
        sym_trades = [t for t in closed_trades if t.symbol == sym]
        if not sym_trades:
            continue
        sym_wins = [t for t in sym_trades if t.pnl > 0]
        sym_pnl = sum(t.pnl for t in sym_trades)
        wr = len(sym_wins) / len(sym_trades) * 100 if sym_trades else 0
        print(f"{sym:<12} {len(sym_trades):>6} {wr:>7.1f}% {sym_pnl:>+12.2f}")

    # 詳細交易記錄
    if closed_trades:
        print(f"\n📋 交易明細 (最近 20 筆)")
        print(f"{'幣種':<10} {'方向':<6} {'進場價':>10} {'出場價':>10} {'PnL':>10} {'原因':<12} {'策略':<18} {'進場時間':<20}")
        print("-" * 100)
        for t in closed_trades[-20:]:
            print(f"{t.symbol:<10} {t.direction:<6} {t.entry_price:>10.2f} {t.exit_price:>10.2f} {t.pnl:>+10.2f} {t.exit_reason:<12} {t.strategy:<18} {t.entry_time[:19]}")

    print()
    print("=" * 70)
    print("💡 提示: 這是使用改善後策略的模擬結果（離線回測，不含實時市場微結構）")
    print("=" * 70)


if __name__ == "__main__":
    import io
    logger.remove()
    logger.add(lambda msg: None)  # 抑制 loguru 輸出

    # 同時輸出到終端和文件
    result_path = Path(__file__).parent / "backtest_result.txt"
    class TeeWriter:
        def __init__(self, *writers):
            self.writers = writers
        def write(self, text):
            for w in self.writers:
                w.write(text)
        def flush(self):
            for w in self.writers:
                w.flush()

    f = open(result_path, "w", encoding="utf-8")
    sys.stdout = TeeWriter(sys.__stdout__, f)
    try:
        asyncio.run(run_backtest())
    finally:
        f.close()
        sys.stdout = sys.__stdout__
        print(f"\n[Result saved to {result_path}]")
