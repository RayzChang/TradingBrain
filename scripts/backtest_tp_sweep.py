"""
TP1/TP2/TP3 參數掃描回測 — 找出最佳 TP 間距

測試多組 TP 參數，找出在當前市況下表現最好的組合。
用法: python scripts/backtest_tp_sweep.py
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
TP1_CLOSE_PCT = 0.30
TP2_CLOSE_PCT = 0.30

BASE_PARAMS = {
    "adx_min": 22, "rsi_oversold": 30, "rsi_overbought": 70,
    "risk_per_trade": 0.03, "sl_atr_mult": 1.5,
    "max_leverage": 5, "max_positions": 3, "cooldown_sec": 7200,
    "daily_loss_limit": 0.06, "daily_profit_target": 0,
}

TP_CONFIGS = [
    {"name": "A: TP1=1.5/TP2=2.0/TP3=4.0 (original)", "tp1": 1.5, "tp2": 2.0, "tp3": 4.0},
    {"name": "B: TP1=1.5/TP2=2.5/TP3=4.0 (wider TP2)", "tp1": 1.5, "tp2": 2.5, "tp3": 4.0},
    {"name": "C: TP1=2.0/TP2=3.0/TP3=4.5 (all wider)", "tp1": 2.0, "tp2": 3.0, "tp3": 4.5},
    {"name": "D: TP1=2.0/TP2=3.0/TP3=5.0 (wide TP3)", "tp1": 2.0, "tp2": 3.0, "tp3": 5.0},
    {"name": "E: v3-style 50% at 2.0 ATR + trail", "tp1": 0, "tp2": 2.0, "tp3": 4.0},
]


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
        except Exception:
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
                 stop_loss, tp1, tp2, tp3, atr, strategy, entry_time,
                 tp1_close_pct=0.3, tp2_close_pct=0.3):
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
        self.is_open = True
        self.exit_price = 0.0
        self.exit_time = ""
        self.pnl = 0.0
        self.exit_reason = ""
        self.tp_stage = 0
        self.remaining_size = size_usdt
        self.realized_partial = 0.0
        self.best_price = entry_price
        self.tp1_close_pct = tp1_close_pct
        self.tp2_close_pct = tp2_close_pct

    def check_exit(self, high, low, close, close_time):
        if not self.is_open:
            return False

        if self.direction == "LONG":
            self.best_price = max(self.best_price, high)
        else:
            self.best_price = min(self.best_price, low)

        # TP1
        if self.tp_stage == 0 and self.tp1 and self.tp1 > 0:
            if (self.direction == "LONG" and high >= self.tp1) or \
               (self.direction == "SHORT" and low <= self.tp1):
                close_size = self.size_usdt * self.tp1_close_pct
                if self.direction == "LONG":
                    raw = (self.tp1 - self.entry_price) / self.entry_price * close_size
                else:
                    raw = (self.entry_price - self.tp1) / self.entry_price * close_size
                self.realized_partial += raw - close_size * FEE_RATE
                self.remaining_size -= close_size
                self.stop_loss = self.entry_price
                self.tp_stage = 1

        # TP2
        if self.tp_stage <= 1 and self.tp2:
            tp2_triggered = (self.direction == "LONG" and high >= self.tp2) or \
                            (self.direction == "SHORT" and low <= self.tp2)
            if tp2_triggered and self.tp_stage == 0:
                # No TP1 defined, or TP1 was 0 - do TP2 directly (50% like v3)
                close_size = self.size_usdt * 0.5
                if self.direction == "LONG":
                    raw = (self.tp2 - self.entry_price) / self.entry_price * close_size
                else:
                    raw = (self.entry_price - self.tp2) / self.entry_price * close_size
                self.realized_partial += raw - close_size * FEE_RATE
                self.remaining_size -= close_size
                self.stop_loss = self.entry_price
                self.tp_stage = 2
            elif tp2_triggered and self.tp_stage == 1:
                close_size = self.size_usdt * self.tp2_close_pct
                if self.direction == "LONG":
                    raw = (self.tp2 - self.entry_price) / self.entry_price * close_size
                else:
                    raw = (self.entry_price - self.tp2) / self.entry_price * close_size
                self.realized_partial += raw - close_size * FEE_RATE
                self.remaining_size -= close_size
                self.stop_loss = self.tp1 if self.tp1 else self.entry_price
                self.tp_stage = 2

        # Trailing after TP2
        if self.tp_stage == 2 and self.atr > 0:
            if self.direction == "LONG":
                trailing_sl = self.best_price - self.atr
                if trailing_sl > self.stop_loss:
                    self.stop_loss = trailing_sl
            else:
                trailing_sl = self.best_price + self.atr
                if trailing_sl < self.stop_loss:
                    self.stop_loss = trailing_sl
        elif self.tp_stage == 1 and self.atr > 0:
            if self.direction == "LONG":
                trailing_sl = self.best_price - self.atr * 1.5
                if trailing_sl > self.stop_loss:
                    self.stop_loss = trailing_sl
            else:
                trailing_sl = self.best_price + self.atr * 1.5
                if trailing_sl < self.stop_loss:
                    self.stop_loss = trailing_sl

        # SL check
        if self.direction == "LONG" and low <= self.stop_loss:
            self._close(self.stop_loss, close_time, ["SL", "TRAIL_TP1", "TRAIL_TP2"][self.tp_stage])
            return True
        if self.direction == "SHORT" and high >= self.stop_loss:
            self._close(self.stop_loss, close_time, ["SL", "TRAIL_TP1", "TRAIL_TP2"][self.tp_stage])
            return True

        # TP3
        if self.tp_stage >= 1 and self.tp3:
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


def run_backtest(kline_data, engine, strategies, tp_config):
    tp1_mult = tp_config["tp1"]
    tp2_mult = tp_config["tp2"]
    tp3_mult = tp_config["tp3"]

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
            if today_pnl < -(start_equity * BASE_PARAMS["daily_loss_limit"]):
                continue
            if len(open_trades) >= BASE_PARAMS["max_positions"]:
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
            if candle_ts - symbol_cooldown.get(ck, 0) < BASE_PARAMS["cooldown_sec"]:
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

            risk_amount = balance * BASE_PARAMS["risk_per_trade"]
            stop_dist = BASE_PARAMS["sl_atr_mult"] * atr
            stop_dist_pct = stop_dist / entry_price
            if stop_dist_pct <= 0:
                continue
            size_usdt = min(risk_amount / stop_dist_pct, balance * BASE_PARAMS["max_leverage"])
            if size_usdt < 10:
                continue

            if sig.signal_type == "LONG":
                sl = entry_price - stop_dist
                tp1 = entry_price + tp1_mult * atr if tp1_mult else 0
                tp2 = entry_price + tp2_mult * atr
                tp3 = entry_price + tp3_mult * atr
            else:
                sl = entry_price + stop_dist
                tp1 = entry_price - tp1_mult * atr if tp1_mult else 0
                tp2 = entry_price - tp2_mult * atr
                tp3 = entry_price - tp3_mult * atr

            trade = Trade(
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
            trade._close(float(last["close"]), str(last["open_time"]), "FORCE")
            balance += trade.pnl

    closed = [t for t in all_trades if not t.is_open]
    wins = [t for t in closed if t.pnl > 0]
    losses = [t for t in closed if t.pnl <= 0]
    total_pnl = sum(t.pnl for t in closed)
    win_amt = sum(t.pnl for t in wins) if wins else 0
    loss_amt = sum(t.pnl for t in losses) if losses else 0
    pf = abs(win_amt / loss_amt) if loss_amt else 0
    roi = total_pnl / INITIAL_BALANCE * 100

    return {
        "trades": len(closed), "wins": len(wins),
        "win_rate": len(wins)/len(closed)*100 if closed else 0,
        "total_pnl": total_pnl, "roi": roi,
        "pf": pf, "balance": balance,
        "avg_win": win_amt/len(wins) if wins else 0,
        "avg_loss": loss_amt/len(losses) if losses else 0,
    }


async def main():
    print("=" * 80)
    print("  TP Parameter Sweep — Finding Best TP1/TP2/TP3 Settings")
    print("=" * 80)

    print("\nFetching 30 days of data...")
    async with httpx.AsyncClient(timeout=30.0) as client:
        kline_data = {}
        for symbol in SYMBOLS:
            kline_data[symbol] = {}
            for tf in TIMEFRAMES:
                extra = 40 if tf == "4h" else (15 if tf == "1h" else 5)
                df = await fetch_klines(client, symbol, tf, BACKTEST_DAYS + extra)
                if not df.empty:
                    kline_data[symbol][tf] = df
                    print(f"  OK {symbol} {tf}: {len(df)}")
                await asyncio.sleep(0.15)

    engine = AnalysisEngine()
    strategies = [
        TrendFollowingStrategy(adx_min=BASE_PARAMS["adx_min"], skip_on_chop=True),
        MeanReversionStrategy(rsi_oversold=BASE_PARAMS["rsi_oversold"],
                              rsi_overbought=BASE_PARAMS["rsi_overbought"], skip_on_chop=True),
        BreakoutStrategy(skip_on_chop=True),
    ]

    results = []
    for cfg in TP_CONFIGS:
        print(f"\nRunning: {cfg['name']}...")
        r = run_backtest(kline_data, engine, strategies, cfg)
        r["name"] = cfg["name"]
        results.append(r)
        print(f"  -> Trades={r['trades']} WR={r['win_rate']:.1f}% PnL={r['total_pnl']:+.0f} ROI={r['roi']:+.1f}% PF={r['pf']:.2f}")

    results.sort(key=lambda x: x["total_pnl"], reverse=True)

    out = []
    def p(s=""):
        out.append(s)
        print(s)

    p()
    p("=" * 100)
    p("  TP PARAMETER SWEEP RESULTS (30 days, 5000U, 10 symbols)")
    p("=" * 100)
    p(f"{'#':<3} {'Config':<50} {'Trades':>6} {'WR':>6} {'PnL':>10} {'ROI':>8} {'PF':>6} {'AvgW':>8} {'AvgL':>8}")
    p("-" * 106)
    for i, r in enumerate(results):
        p(f"{i+1:<3} {r['name']:<50} {r['trades']:>6} {r['win_rate']:>5.1f}% {r['total_pnl']:>+10.0f} {r['roi']:>+7.1f}% {r['pf']:>6.2f} {r['avg_win']:>+8.1f} {r['avg_loss']:>+8.1f}")

    p()
    best = results[0]
    p(f"  BEST: {best['name']}")
    p(f"  5000U -> {best['balance']:.0f}U ({best['roi']:+.1f}%)")

    result_path = Path(__file__).parent / "backtest_tp_sweep_result.txt"
    with open(result_path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print(f"\n[Saved to {result_path}]")


if __name__ == "__main__":
    logger.remove()
    logger.add(lambda msg: None)
    asyncio.run(main())
