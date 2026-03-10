"""
TradingBrain v4.1 — 30 天回測 (TP1/TP2/TP3 三階段止盈 + ATR 追蹤止損)

對比 v3 (50% partial TP + % trailing) vs v4.1 (30/30/40 TP + ATR trailing)

用法: python scripts/backtest_v4_tp123.py
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

KLINE_COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "trades", "taker_buy_volume",
    "taker_buy_quote_volume", "ignore",
]

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

CONFIGS = {
    "A_original": {
        "label": "A: TP1=1.0/TP2=2.0/TP3=4.0 (original, too tight)",
        "tp1_atr_mult": 1.0, "tp2_atr_mult": 2.0, "tp3_atr_mult": 4.0,
    },
    "B_wider": {
        "label": "B: TP1=1.5/TP2=2.5/TP3=4.0 (wider TP1)",
        "tp1_atr_mult": 1.5, "tp2_atr_mult": 2.5, "tp3_atr_mult": 4.0,
    },
    "C_v3style": {
        "label": "C: TP1=2.0/TP2=3.0/TP3=4.5 (v3-style wide)",
        "tp1_atr_mult": 2.0, "tp2_atr_mult": 3.0, "tp3_atr_mult": 4.5,
    },
    "D_aggressive": {
        "label": "D: TP1=2.0/TP2=3.5/TP3=5.0 (let profits run)",
        "tp1_atr_mult": 2.0, "tp2_atr_mult": 3.5, "tp3_atr_mult": 5.0,
    },
}

PARAMS = {
    "adx_min": 22, "rsi_oversold": 30, "rsi_overbought": 70,
    "risk_per_trade": 0.03, "sl_atr_mult": 1.5,
    "tp1_atr_mult": 2.0, "tp2_atr_mult": 3.0, "tp3_atr_mult": 4.5,
    "max_leverage": 5, "max_positions": 3, "cooldown_sec": 7200,
    "daily_loss_limit": 0.06, "daily_profit_target": 0,
}

TP1_CLOSE_PCT = 0.30
TP2_CLOSE_PCT = 0.30


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


class TradeV4:
    """v4.1 三階段止盈 + ATR 追蹤止損"""

    def __init__(self, symbol, direction, entry_price, size_usdt,
                 stop_loss, tp1, tp2, tp3, atr, strategy, entry_time):
        self.symbol = symbol
        self.direction = direction
        self.entry_price = entry_price
        self.size_usdt = size_usdt
        self.stop_loss = stop_loss
        self.tp1 = tp1
        self.tp2 = tp2
        self.tp3 = tp3
        self.atr = atr
        self.strategy = strategy
        self.entry_time = entry_time
        self.exit_price = 0.0
        self.exit_time = ""
        self.pnl = 0.0
        self.exit_reason = ""
        self.is_open = True

        self.tp_stage = 0
        self.remaining_size = size_usdt
        self.realized_partial = 0.0
        self.best_price = entry_price

    def check_exit(self, high, low, close, close_time):
        if not self.is_open:
            return False

        # Update best price
        if self.direction == "LONG":
            self.best_price = max(self.best_price, high)
        else:
            self.best_price = min(self.best_price, low)

        # TP1: close 30%, SL → entry (breakeven)
        if self.tp_stage == 0 and self.tp1:
            if (self.direction == "LONG" and high >= self.tp1) or \
               (self.direction == "SHORT" and low <= self.tp1):
                close_size = self.size_usdt * TP1_CLOSE_PCT
                if self.direction == "LONG":
                    raw = (self.tp1 - self.entry_price) / self.entry_price * close_size
                else:
                    raw = (self.entry_price - self.tp1) / self.entry_price * close_size
                self.realized_partial += raw - close_size * FEE_RATE
                self.remaining_size -= close_size
                self.stop_loss = self.entry_price
                self.tp_stage = 1

        # TP2: close 30%, SL → TP1
        if self.tp_stage == 1 and self.tp2:
            if (self.direction == "LONG" and high >= self.tp2) or \
               (self.direction == "SHORT" and low <= self.tp2):
                close_size = self.size_usdt * TP2_CLOSE_PCT
                if self.direction == "LONG":
                    raw = (self.tp2 - self.entry_price) / self.entry_price * close_size
                else:
                    raw = (self.entry_price - self.tp2) / self.entry_price * close_size
                self.realized_partial += raw - close_size * FEE_RATE
                self.remaining_size -= close_size
                self.stop_loss = self.tp1
                self.tp_stage = 2

        # Trailing stop after TP2 (ATR-based)
        if self.tp_stage == 2 and self.atr > 0:
            if self.direction == "LONG":
                trailing_sl = self.best_price - self.atr
                if trailing_sl > self.stop_loss:
                    self.stop_loss = trailing_sl
            else:
                trailing_sl = self.best_price + self.atr
                if trailing_sl < self.stop_loss:
                    self.stop_loss = trailing_sl

        # Trailing after TP1 (1.5 ATR distance)
        elif self.tp_stage == 1 and self.atr > 0:
            if self.direction == "LONG":
                trailing_sl = self.best_price - self.atr * 1.5
                if trailing_sl > self.stop_loss:
                    self.stop_loss = trailing_sl
            else:
                trailing_sl = self.best_price + self.atr * 1.5
                if trailing_sl < self.stop_loss:
                    self.stop_loss = trailing_sl

        # Stop loss check
        if self.direction == "LONG" and low <= self.stop_loss:
            reason = ["STOP_LOSS", "TRAILING_SL_TP1", "TRAILING_SL_TP2"][self.tp_stage]
            self._close(self.stop_loss, close_time, reason)
            return True
        if self.direction == "SHORT" and high >= self.stop_loss:
            reason = ["STOP_LOSS", "TRAILING_SL_TP1", "TRAILING_SL_TP2"][self.tp_stage]
            self._close(self.stop_loss, close_time, reason)
            return True

        # TP3: close remaining 40%
        if self.tp_stage == 2 and self.tp3:
            if (self.direction == "LONG" and high >= self.tp3) or \
               (self.direction == "SHORT" and low <= self.tp3):
                self._close(self.tp3, close_time, "TP3")
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

    p("=" * 80)
    p("  TradingBrain v4.1 — 30-Day Backtest")
    p("  TP1/TP2/TP3 三階段止盈 + ATR 追蹤止損")
    p("=" * 80)
    p(f"  Period: {BACKTEST_DAYS} days | Balance: {INITIAL_BALANCE} U")
    p(f"  Symbols: {len(SYMBOLS)} | Risk/trade: {PARAMS['risk_per_trade']*100}%")
    p(f"  SL: {PARAMS['sl_atr_mult']} ATR")
    p(f"  TP1: {PARAMS['tp1_atr_mult']} ATR (close 30%) → SL=breakeven")
    p(f"  TP2: {PARAMS['tp2_atr_mult']} ATR (close 30%) → SL=TP1, trail 1.0ATR")
    p(f"  TP3: {PARAMS['tp3_atr_mult']} ATR (close 40%)")
    p("=" * 80)

    p("\nFetching 30 days of data...")
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
                await asyncio.sleep(0.15)

    engine = AnalysisEngine()
    strategies = [
        TrendFollowingStrategy(adx_min=PARAMS["adx_min"], skip_on_chop=True),
        MeanReversionStrategy(rsi_oversold=PARAMS["rsi_oversold"],
                              rsi_overbought=PARAMS["rsi_overbought"], skip_on_chop=True),
        BreakoutStrategy(skip_on_chop=True),
    ]

    p("\nRunning simulation...")
    balance = INITIAL_BALANCE
    all_trades = []
    open_trades = []
    symbol_cooldown = {}
    daily_pnl = {}
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

            if sig.signal_type == "LONG":
                sl = entry_price - stop_dist
                tp1 = entry_price + PARAMS["tp1_atr_mult"] * atr
                tp2 = entry_price + PARAMS["tp2_atr_mult"] * atr
                tp3 = entry_price + PARAMS["tp3_atr_mult"] * atr
            else:
                sl = entry_price + stop_dist
                tp1 = entry_price - PARAMS["tp1_atr_mult"] * atr
                tp2 = entry_price - PARAMS["tp2_atr_mult"] * atr
                tp3 = entry_price - PARAMS["tp3_atr_mult"] * atr

            trade = TradeV4(
                symbol=symbol, direction=sig.signal_type,
                entry_price=entry_price, size_usdt=round(size_usdt, 2),
                stop_loss=round(sl, 4), tp1=round(tp1, 4),
                tp2=round(tp2, 4), tp3=round(tp3, 4),
                atr=atr, strategy=sig.strategy_name,
                entry_time=str(candle_time),
            )
            open_trades.append(trade)
            all_trades.append(trade)
            symbol_cooldown[ck] = candle_ts

    for trade in list(open_trades):
        if trade.is_open and trade.symbol in kline_data and PRIMARY_TF in kline_data[trade.symbol]:
            last = kline_data[trade.symbol][PRIMARY_TF].iloc[-1]
            trade._close(float(last["close"]), str(last["open_time"]), "FORCE_CLOSE")
            balance += trade.pnl

    # === Results ===
    closed = [t for t in all_trades if not t.is_open]
    wins = [t for t in closed if t.pnl > 0]
    losses = [t for t in closed if t.pnl <= 0]
    total_pnl = sum(t.pnl for t in closed)
    win_amt = sum(t.pnl for t in wins) if wins else 0
    loss_amt = sum(t.pnl for t in losses) if losses else 0
    pf = abs(win_amt / loss_amt) if loss_amt else float("inf")
    roi = total_pnl / INITIAL_BALANCE * 100

    p()
    p("=" * 80)
    p("  30-DAY BACKTEST RESULTS (v4.1 TP1/TP2/TP3)")
    p("=" * 80)
    p(f"  Initial: {INITIAL_BALANCE:.0f} U -> Final: {balance:.2f} U")
    p(f"  Total PnL: {total_pnl:+.2f} U | ROI: {roi:+.2f}%")
    p(f"  Daily avg ROI: {roi/BACKTEST_DAYS:+.2f}%")
    p(f"  Trades: {len(closed)} | Wins: {len(wins)} | Losses: {len(losses)}")
    if closed:
        p(f"  Win Rate: {len(wins)/len(closed)*100:.1f}%")
    p(f"  Profit Factor: {pf:.2f}")
    if wins:
        p(f"  Avg Win: {win_amt/len(wins):+.2f}")
    if losses:
        p(f"  Avg Loss: {loss_amt/len(losses):+.2f}")

    # Exit reason breakdown
    reason_counts = {}
    reason_pnl = {}
    for t in closed:
        reason_counts[t.exit_reason] = reason_counts.get(t.exit_reason, 0) + 1
        reason_pnl[t.exit_reason] = reason_pnl.get(t.exit_reason, 0) + t.pnl
    p()
    p(f"  {'Exit Reason':<20} {'Count':>6} {'PnL':>12} {'Avg':>10}")
    p("  " + "-" * 50)
    for reason in sorted(reason_counts.keys()):
        cnt = reason_counts[reason]
        rpnl = reason_pnl[reason]
        p(f"  {reason:<20} {cnt:>6} {rpnl:>+12.2f} {rpnl/cnt:>+10.2f}")

    # TP stage analysis
    tp_reached = {0: 0, 1: 0, 2: 0}
    for t in closed:
        tp_reached[t.tp_stage] = tp_reached.get(t.tp_stage, 0) + 1
    p()
    p(f"  TP Stage Distribution:")
    p(f"    Never reached TP1: {tp_reached.get(0, 0)}")
    p(f"    Reached TP1 (breakeven protected): {tp_reached.get(1, 0)}")
    p(f"    Reached TP2+ (profit locked): {tp_reached.get(2, 0)}")

    # Max drawdown
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
    p(f"\n  Max Drawdown: {max_dd:.1f}%")

    # Daily details
    p()
    p(f"  {'Date':<12} {'PnL':>10} {'Balance':>12}")
    p("  " + "-" * 36)
    sorted_dates = sorted(daily_pnl.keys())
    cum = INITIAL_BALANCE
    win_days = loss_days = 0
    for date in sorted_dates:
        dpnl = daily_pnl[date]
        cum += dpnl
        p(f"  {date:<12} {dpnl:>+10.2f} {cum:>12.2f}")
        if dpnl >= 0:
            win_days += 1
        else:
            loss_days += 1
    total_days = win_days + loss_days
    if total_days:
        p(f"\n  Profitable Days: {win_days}/{total_days} ({win_days/total_days*100:.0f}%)")

    # Strategy breakdown
    p()
    p(f"  {'Strategy':<22} {'N':>5} {'WR':>7} {'PnL':>12}")
    p("  " + "-" * 48)
    for strat in sorted(set(t.strategy for t in closed)):
        st = [t for t in closed if t.strategy == strat]
        sw = [t for t in st if t.pnl > 0]
        sp = sum(t.pnl for t in st)
        wr = len(sw)/len(st)*100 if st else 0
        p(f"  {strat:<22} {len(st):>5} {wr:>6.1f}% {sp:>+12.2f}")

    # Symbol breakdown
    p()
    p(f"  {'Symbol':<12} {'N':>5} {'WR':>7} {'PnL':>12}")
    p("  " + "-" * 38)
    sym_results = []
    for sym in SYMBOLS:
        st = [t for t in closed if t.symbol == sym]
        if not st:
            continue
        sw = [t for t in st if t.pnl > 0]
        sp = sum(t.pnl for t in st)
        wr = len(sw)/len(st)*100 if st else 0
        sym_results.append((sym, len(st), wr, sp))
    sym_results.sort(key=lambda x: x[3], reverse=True)
    for sym, n, wr, sp in sym_results:
        p(f"  {sym:<12} {n:>5} {wr:>6.1f}% {sp:>+12.2f}")

    # v3 vs v4.1 comparison note
    p()
    p("=" * 80)
    p("  v3 (舊版 50% partial + %trailing) 30天結果: 5000→13053 (+161%)")
    p(f"  v4.1 (TP1/TP2/TP3 + ATR trailing) 30天結果: 5000→{balance:.0f} ({roi:+.1f}%)")
    p("=" * 80)

    result_path = Path(__file__).parent / "backtest_v4_result.txt"
    with open(result_path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print(f"\n[Saved to {result_path}]")


if __name__ == "__main__":
    logger.remove()
    logger.add(lambda msg: None)
    asyncio.run(main())
