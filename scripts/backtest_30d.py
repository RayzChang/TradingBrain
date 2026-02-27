"""
30 天回測 + 複利模擬 (Config D 最佳參數)
全部 10 幣種，含每日複利統計和最終報告。

用法: python scripts/backtest_30d.py
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
import pandas as pd
from loguru import logger

from core.analysis.engine import AnalysisEngine
from core.strategy.trend_following import TrendFollowingStrategy
from core.strategy.mean_reversion import MeanReversionStrategy
from core.strategy.breakout import BreakoutStrategy
from core.strategy.base import TradeSignal

KLINE_COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "trades", "taker_buy_volume",
    "taker_buy_quote_volume", "ignore",
]

# 全部 10 幣種
SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "DOTUSDT", "LINKUSDT",
]

BACKTEST_DAYS = 30
PRIMARY_TF = "15m"
TIMEFRAMES = ["15m", "1h", "4h"]
FEE_RATE = 0.0004
SLIPPAGE_RATE = 0.0005
INITIAL_BALANCE = 5000.0

# Config D 最佳參數
PARAMS = {
    "adx_min": 22, "rsi_oversold": 30, "rsi_overbought": 70,
    "risk_per_trade": 0.03, "sl_atr_mult": 1.5, "tp_atr_mult": 4.0,
    "max_leverage": 5, "max_positions": 3, "cooldown_sec": 7200,
    "daily_loss_limit": 0.06, "daily_profit_target": 0,
    "partial_tp_mult": 2.0, "trailing_pct": 0.015,
}


async def fetch_klines(client, symbol, interval, days):
    all_dfs = []
    end_time = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_time = end_time - days * 86400 * 1000
    current_start = start_time
    while current_start < end_time:
        params = {"symbol": symbol, "interval": interval, "limit": 1500,
                  "startTime": current_start, "endTime": end_time}
        try:
            resp = await client.get("https://fapi.binance.com/fapi/v1/klines", params=params)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"  WARN: {symbol} {interval} fetch failed: {e}")
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
        await asyncio.sleep(0.12)
    if not all_dfs:
        return pd.DataFrame()
    result = pd.concat(all_dfs, ignore_index=True)
    result.drop_duplicates(subset=["open_time"], keep="last", inplace=True)
    result.sort_values("open_time", inplace=True)
    result.reset_index(drop=True, inplace=True)
    return result


class Trade:
    def __init__(self, symbol, direction, entry_price, size_usdt,
                 stop_loss, take_profit, strategy, entry_time,
                 partial_tp_price=None, trailing_stop_pct=0):
        self.symbol = symbol
        self.direction = direction
        self.entry_price = entry_price
        self.size_usdt = size_usdt
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.strategy = strategy
        self.entry_time = entry_time
        self.exit_price = 0.0
        self.exit_time = ""
        self.pnl = 0.0
        self.exit_reason = ""
        self.is_open = True
        self.partial_tp_price = partial_tp_price
        self.partial_taken = False
        self.remaining_size = size_usdt
        self.realized_partial = 0.0
        self.trailing_stop_pct = trailing_stop_pct
        self.best_price = entry_price

    def check_exit(self, high, low, close, close_time):
        if not self.is_open:
            return False
        if self.direction == "LONG":
            if high > self.best_price:
                self.best_price = high
                if self.trailing_stop_pct > 0 and self.partial_taken:
                    new_sl = self.best_price * (1 - self.trailing_stop_pct)
                    if new_sl > self.stop_loss:
                        self.stop_loss = new_sl
        else:
            if low < self.best_price:
                self.best_price = low
                if self.trailing_stop_pct > 0 and self.partial_taken:
                    new_sl = self.best_price * (1 + self.trailing_stop_pct)
                    if new_sl < self.stop_loss:
                        self.stop_loss = new_sl
        if self.partial_tp_price and not self.partial_taken:
            if self.direction == "LONG" and high >= self.partial_tp_price:
                half = self.remaining_size * 0.5
                raw = (self.partial_tp_price - self.entry_price) / self.entry_price * half
                self.realized_partial += raw - half * FEE_RATE
                self.remaining_size -= half
                self.partial_taken = True
            elif self.direction == "SHORT" and low <= self.partial_tp_price:
                half = self.remaining_size * 0.5
                raw = (self.entry_price - self.partial_tp_price) / self.entry_price * half
                self.realized_partial += raw - half * FEE_RATE
                self.remaining_size -= half
                self.partial_taken = True
        if self.direction == "LONG" and low <= self.stop_loss:
            self._close(self.stop_loss, close_time, "STOP_LOSS")
            return True
        if self.direction == "SHORT" and high >= self.stop_loss:
            self._close(self.stop_loss, close_time, "STOP_LOSS")
            return True
        if self.direction == "LONG" and high >= self.take_profit:
            self._close(self.take_profit, close_time, "TAKE_PROFIT")
            return True
        if self.direction == "SHORT" and low <= self.take_profit:
            self._close(self.take_profit, close_time, "TAKE_PROFIT")
            return True
        return False

    def _close(self, exit_price, exit_time, reason):
        self.exit_price = exit_price
        self.exit_time = exit_time
        self.exit_reason = reason
        self.is_open = False
        if self.direction == "LONG":
            raw = (exit_price - self.entry_price) / self.entry_price * self.remaining_size
        else:
            raw = (self.entry_price - exit_price) / self.entry_price * self.remaining_size
        fee = self.remaining_size * FEE_RATE
        slip = self.remaining_size * SLIPPAGE_RATE
        self.pnl = self.realized_partial + raw - fee - slip


async def main():
    out = []
    def p(s=""):
        out.append(s)
        print(s)

    p("=" * 70)
    p("  TradingBrain v3 — 30-Day Backtest (Config D + 10 Symbols)")
    p(f"  Period: {BACKTEST_DAYS} days | Balance: {INITIAL_BALANCE} U")
    p(f"  Symbols: {len(SYMBOLS)} | Risk: {PARAMS['risk_per_trade']*100}%")
    p(f"  SL: {PARAMS['sl_atr_mult']} ATR | TP: {PARAMS['tp_atr_mult']} ATR")
    p(f"  Partial TP: {PARAMS['partial_tp_mult']} ATR | Trail: {PARAMS['trailing_pct']*100}%")
    p("=" * 70)

    p("\nFetching 30 days of data for 10 symbols (this takes a while)...")
    async with httpx.AsyncClient(timeout=30.0) as client:
        kline_data = {}
        for symbol in SYMBOLS:
            kline_data[symbol] = {}
            for tf in TIMEFRAMES:
                extra = 40 if tf == "4h" else (15 if tf == "1h" else 5)
                df = await fetch_klines(client, symbol, tf, BACKTEST_DAYS + extra)
                if not df.empty:
                    kline_data[symbol][tf] = df
                    p(f"  OK {symbol} {tf}: {len(df)}")
                else:
                    p(f"  MISS {symbol} {tf}")
                await asyncio.sleep(0.15)

    engine = AnalysisEngine()
    strategies = [
        TrendFollowingStrategy(adx_min=PARAMS["adx_min"], skip_on_chop=True),
        MeanReversionStrategy(rsi_oversold=PARAMS["rsi_oversold"],
                              rsi_overbought=PARAMS["rsi_overbought"], skip_on_chop=True),
        BreakoutStrategy(skip_on_chop=True),
    ]

    p("\nRunning 30-day simulation...")
    balance = INITIAL_BALANCE
    all_trades = []
    open_trades = []
    symbol_cooldown = {}
    daily_pnl = {}
    daily_balance = {}
    now_ts = datetime.now(timezone.utc).timestamp()
    backtest_start_ts = now_ts - BACKTEST_DAYS * 86400

    for symbol in SYMBOLS:
        if PRIMARY_TF not in kline_data[symbol]:
            continue
        primary_df = kline_data[symbol][PRIMARY_TF]
        if len(primary_df) < 100:
            continue

        for i in range(100, len(primary_df)):
            candle_time = primary_df.iloc[i]["open_time"]
            candle_ts = candle_time.timestamp()
            if candle_ts < backtest_start_ts:
                continue
            current_date = str(candle_time.date())
            candle = primary_df.iloc[i]

            for trade in list(open_trades):
                if trade.symbol == symbol:
                    closed = trade.check_exit(
                        float(candle["high"]), float(candle["low"]),
                        float(candle["close"]), str(candle_time))
                    if closed:
                        balance += trade.pnl
                        open_trades.remove(trade)
                        daily_pnl[current_date] = daily_pnl.get(current_date, 0) + trade.pnl

            daily_balance[current_date] = balance

            today_pnl = daily_pnl.get(current_date, 0)
            start_equity = balance - today_pnl
            if today_pnl < -(start_equity * PARAMS["daily_loss_limit"]):
                continue
            if len(open_trades) >= PARAMS["max_positions"]:
                continue

            mtf_klines = {}
            for tf in TIMEFRAMES:
                if tf not in kline_data[symbol]:
                    continue
                tf_df = kline_data[symbol][tf]
                mask = tf_df["open_time"] <= candle_time
                subset = tf_df[mask].tail(200)
                if len(subset) >= 50:
                    mtf_klines[tf] = subset
            if len(mtf_klines) < 2:
                continue

            try:
                full = engine.analyze_full(symbol, mtf_klines, PRIMARY_TF)
            except Exception:
                continue

            signals = []
            for strategy in strategies:
                sigs = strategy.evaluate_full(full, primary_tf=PRIMARY_TF)
                signals.extend(sigs)
            if not signals:
                continue

            best = max(signals, key=lambda s: s.strength)
            sig = best
            ck = (sig.symbol, sig.signal_type)
            if candle_ts - symbol_cooldown.get(ck, 0) < PARAMS["cooldown_sec"]:
                continue
            if any(t.symbol == symbol and t.is_open for t in open_trades):
                continue

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

            risk_amount = balance * PARAMS["risk_per_trade"]
            stop_dist = PARAMS["sl_atr_mult"] * atr
            stop_dist_pct = stop_dist / entry_price
            if stop_dist_pct <= 0:
                continue
            size_usdt = min(risk_amount / stop_dist_pct, balance * PARAMS["max_leverage"])
            if size_usdt < 10:
                continue

            tp_dist = PARAMS["tp_atr_mult"] * atr
            if sig.signal_type == "LONG":
                sl = entry_price - stop_dist
                tp = entry_price + tp_dist
                ptp = entry_price + PARAMS["partial_tp_mult"] * atr
            else:
                sl = entry_price + stop_dist
                tp = entry_price - tp_dist
                ptp = entry_price - PARAMS["partial_tp_mult"] * atr

            trade = Trade(symbol=symbol, direction=sig.signal_type,
                          entry_price=entry_price, size_usdt=round(size_usdt, 2),
                          stop_loss=round(sl, 4), take_profit=round(tp, 4),
                          strategy=sig.strategy_name, entry_time=str(candle_time),
                          partial_tp_price=round(ptp, 4),
                          trailing_stop_pct=PARAMS["trailing_pct"])
            open_trades.append(trade)
            all_trades.append(trade)
            symbol_cooldown[ck] = candle_ts

    for trade in list(open_trades):
        if trade.is_open and trade.symbol in kline_data and PRIMARY_TF in kline_data[trade.symbol]:
            last = kline_data[trade.symbol][PRIMARY_TF].iloc[-1]
            trade._close(float(last["close"]), str(last["open_time"]), "FORCE_CLOSE")
            balance += trade.pnl

    # === 輸出結果 ===
    closed = [t for t in all_trades if not t.is_open]
    wins = [t for t in closed if t.pnl > 0]
    losses = [t for t in closed if t.pnl <= 0]
    total_pnl = sum(t.pnl for t in closed)
    win_amt = sum(t.pnl for t in wins) if wins else 0
    loss_amt = sum(t.pnl for t in losses) if losses else 0
    pf = abs(win_amt / loss_amt) if loss_amt else float("inf")
    roi = total_pnl / INITIAL_BALANCE * 100

    p()
    p("=" * 70)
    p("  30-DAY BACKTEST RESULTS")
    p("=" * 70)
    p(f"  Initial: {INITIAL_BALANCE:.0f} U -> Final: {balance:.2f} U")
    p(f"  Total PnL: {total_pnl:+.2f} U | ROI: {roi:+.2f}%")
    p(f"  Daily avg ROI: {roi/BACKTEST_DAYS:+.2f}%")
    p(f"  Trades: {len(closed)} | Wins: {len(wins)} | Losses: {len(losses)}")
    p(f"  Win Rate: {len(wins)/len(closed)*100:.1f}%" if closed else "  No trades")
    p(f"  Profit Factor: {pf:.2f}")
    p(f"  Avg Win: {win_amt/len(wins):+.2f}" if wins else "  Avg Win: N/A")
    p(f"  Avg Loss: {loss_amt/len(losses):+.2f}" if losses else "  Avg Loss: N/A")
    p(f"  Daily avg trades: {len(closed)/BACKTEST_DAYS:.1f}")

    # 最大回撤
    peak = INITIAL_BALANCE
    max_dd = 0
    running = INITIAL_BALANCE
    for t in closed:
        running += t.pnl
        if running > peak:
            peak = running
        dd = (peak - running) / peak * 100
        if dd > max_dd:
            max_dd = dd
    p(f"  Max Drawdown: {max_dd:.1f}%")

    # 連勝/連虧
    streak_w = streak_l = max_sw = max_sl = 0
    for t in closed:
        if t.pnl > 0:
            streak_w += 1; streak_l = 0
            max_sw = max(max_sw, streak_w)
        else:
            streak_l += 1; streak_w = 0
            max_sl = max(max_sl, streak_l)
    p(f"  Max Win Streak: {max_sw} | Max Loss Streak: {max_sl}")

    # 每日明細
    p()
    p(f"  {'Date':<12} {'PnL':>10} {'Balance':>12} {'Trades':>7}")
    p("  " + "-" * 43)
    sorted_dates = sorted(daily_pnl.keys())
    cum = INITIAL_BALANCE
    win_days = loss_days = 0
    weekly_pnl = {}
    for date in sorted_dates:
        dpnl = daily_pnl[date]
        cum += dpnl
        # 當日交易數
        dt_trades = sum(1 for t in closed
                        if t.entry_time[:10] == date or (t.exit_time and t.exit_time[:10] == date))
        p(f"  {date:<12} {dpnl:>+10.2f} {cum:>12.2f} {dt_trades:>7}")
        if dpnl >= 0:
            win_days += 1
        else:
            loss_days += 1
        # 週統計
        dt = datetime.strptime(date, "%Y-%m-%d")
        week_key = f"W{dt.isocalendar()[1]}"
        weekly_pnl[week_key] = weekly_pnl.get(week_key, 0) + dpnl

    p()
    p(f"  Profitable Days: {win_days}/{win_days+loss_days} ({win_days/(win_days+loss_days)*100:.0f}%)" if win_days+loss_days else "")

    # 週統計
    p()
    p(f"  {'Week':<8} {'PnL':>12}")
    p("  " + "-" * 22)
    for wk in sorted(weekly_pnl.keys()):
        p(f"  {wk:<8} {weekly_pnl[wk]:>+12.2f}")

    # 策略分佈
    p()
    p(f"  {'Strategy':<22} {'N':>5} {'WR':>7} {'PnL':>12} {'AvgPnL':>10}")
    p("  " + "-" * 58)
    for strat in sorted(set(t.strategy for t in closed)):
        st = [t for t in closed if t.strategy == strat]
        sw = [t for t in st if t.pnl > 0]
        sp = sum(t.pnl for t in st)
        wr = len(sw)/len(st)*100 if st else 0
        ap = sp/len(st) if st else 0
        p(f"  {strat:<22} {len(st):>5} {wr:>6.1f}% {sp:>+12.2f} {ap:>+10.2f}")

    # 幣種分佈
    p()
    p(f"  {'Symbol':<12} {'N':>5} {'WR':>7} {'PnL':>12} {'AvgPnL':>10}")
    p("  " + "-" * 48)
    sym_results = []
    for sym in SYMBOLS:
        st = [t for t in closed if t.symbol == sym]
        if not st:
            continue
        sw = [t for t in st if t.pnl > 0]
        sp = sum(t.pnl for t in st)
        wr = len(sw)/len(st)*100 if st else 0
        ap = sp/len(st) if st else 0
        sym_results.append((sym, len(st), wr, sp, ap))
    sym_results.sort(key=lambda x: x[3], reverse=True)
    for sym, n, wr, sp, ap in sym_results:
        flag = " *" if sp > 0 else ""
        p(f"  {sym:<12} {n:>5} {wr:>6.1f}% {sp:>+12.2f} {ap:>+10.2f}{flag}")

    # 複利模擬
    p()
    p("=" * 70)
    p("  COMPOUND GROWTH PROJECTION (based on daily avg ROI)")
    p("=" * 70)
    daily_roi_avg = roi / BACKTEST_DAYS / 100
    projected = INITIAL_BALANCE
    p(f"  {'Period':<20} {'Balance':>12} {'Growth':>10}")
    p("  " + "-" * 44)
    for label, days in [("1 week", 7), ("2 weeks", 14), ("1 month", 30),
                         ("2 months", 60), ("3 months", 90)]:
        projected_b = INITIAL_BALANCE * ((1 + daily_roi_avg) ** days)
        growth = (projected_b / INITIAL_BALANCE - 1) * 100
        p(f"  {label:<20} {projected_b:>12.2f} {growth:>+9.1f}%")

    p()
    p("=" * 70)

    result_path = Path(__file__).parent / "backtest_30d_result.txt"
    with open(result_path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print(f"\n[Saved to {result_path}]")


if __name__ == "__main__":
    logger.remove()
    logger.add(lambda msg: None)
    asyncio.run(main())
