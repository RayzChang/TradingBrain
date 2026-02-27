"""
多參數組合回測 (Parameter Sweep Backtest) v3

目標: 找出每日 3-10% 收益的最佳參數組合。
三策略: 趨勢追蹤 + 均值回歸 + 突破（市場狀態自適應）

用法: python scripts/backtest_v3.py
"""

import asyncio
import sys
import io
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

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
BACKTEST_DAYS = 7
PRIMARY_TF = "15m"
TIMEFRAMES = ["15m", "1h", "4h"]
FEE_RATE = 0.0004
SLIPPAGE_RATE = 0.0005


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
        await asyncio.sleep(0.15)
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
        # 部分止盈
        self.partial_tp_price = partial_tp_price
        self.partial_taken = False
        self.remaining_size = size_usdt
        self.realized_partial = 0.0
        # Trailing stop
        self.trailing_stop_pct = trailing_stop_pct
        self.best_price = entry_price  # 追蹤最佳價格

    def check_exit(self, high, low, close, close_time):
        if not self.is_open:
            return False

        # 更新最佳價格 (trailing)
        if self.direction == "LONG":
            if high > self.best_price:
                self.best_price = high
                if self.trailing_stop_pct > 0 and self.partial_taken:
                    # trailing 只在部分止盈後啟動
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

        # 部分止盈
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

        # 止損
        if self.direction == "LONG" and low <= self.stop_loss:
            self._close(self.stop_loss, close_time, "STOP_LOSS")
            return True
        if self.direction == "SHORT" and high >= self.stop_loss:
            self._close(self.stop_loss, close_time, "STOP_LOSS")
            return True

        # 完整止盈
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

    def force_close(self, price, time_str):
        self._close(price, time_str, "FORCE_CLOSE")


def run_single_backtest(kline_data, engine, params, initial_balance=5000.0):
    """
    用指定參數跑一次回測，返回結果字典。
    """
    adx_min = params["adx_min"]
    rsi_low = params["rsi_oversold"]
    rsi_high = params["rsi_overbought"]
    risk_per_trade = params["risk_per_trade"]
    sl_mult = params["sl_atr_mult"]
    tp_mult = params["tp_atr_mult"]
    max_leverage = params["max_leverage"]
    max_positions = params["max_positions"]
    cooldown_sec = params["cooldown_sec"]
    daily_loss_limit = params["daily_loss_limit"]
    daily_profit_target = params["daily_profit_target"]
    partial_tp_mult = params.get("partial_tp_mult", 0)
    trailing_pct = params.get("trailing_pct", 0)

    strategies = [
        TrendFollowingStrategy(adx_min=adx_min, skip_on_chop=True),
        MeanReversionStrategy(rsi_oversold=rsi_low, rsi_overbought=rsi_high, skip_on_chop=True),
        BreakoutStrategy(skip_on_chop=True),
    ]

    balance = initial_balance
    all_trades = []
    open_trades = []
    symbol_cooldown = {}
    daily_pnl = {}
    daily_locked = set()

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

            # 檢查持倉
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

            # 每日限制
            if today_pnl < -(start_equity * daily_loss_limit):
                continue
            if daily_profit_target > 0 and today_pnl > 0 and today_pnl >= start_equity * daily_profit_target:
                if current_date not in daily_locked:
                    daily_locked.add(current_date)
                continue

            if len(open_trades) >= max_positions:
                continue

            # MTF 分析
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

            # 衝突解決
            best = max(signals, key=lambda s: s.strength)
            sig = best

            # 冷卻
            ck = (sig.symbol, sig.signal_type)
            if candle_ts - symbol_cooldown.get(ck, 0) < cooldown_sec:
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

            # 倉位計算
            risk_amount = balance * risk_per_trade
            stop_dist = sl_mult * atr
            stop_dist_pct = stop_dist / entry_price
            if stop_dist_pct <= 0:
                continue
            size_usdt = risk_amount / stop_dist_pct
            size_usdt = min(size_usdt, balance * max_leverage)
            if size_usdt < 10:
                continue

            tp_dist = tp_mult * atr

            if sig.signal_type == "LONG":
                sl = entry_price - stop_dist
                tp = entry_price + tp_dist
                partial_tp = entry_price + partial_tp_mult * atr if partial_tp_mult else None
            else:
                sl = entry_price + stop_dist
                tp = entry_price - tp_dist
                partial_tp = entry_price - partial_tp_mult * atr if partial_tp_mult else None

            trade = Trade(
                symbol=symbol, direction=sig.signal_type,
                entry_price=entry_price, size_usdt=round(size_usdt, 2),
                stop_loss=round(sl, 4), take_profit=round(tp, 4),
                strategy=sig.strategy_name, entry_time=str(candle_time),
                partial_tp_price=round(partial_tp, 4) if partial_tp else None,
                trailing_stop_pct=trailing_pct,
            )
            open_trades.append(trade)
            all_trades.append(trade)
            symbol_cooldown[ck] = candle_ts

    # 強制平倉
    for trade in list(open_trades):
        if trade.is_open and trade.symbol in kline_data and PRIMARY_TF in kline_data[trade.symbol]:
            last = kline_data[trade.symbol][PRIMARY_TF].iloc[-1]
            trade.force_close(float(last["close"]), str(last["open_time"]))
            balance += trade.pnl

    closed = [t for t in all_trades if not t.is_open]
    wins = [t for t in closed if t.pnl > 0]
    total_pnl = sum(t.pnl for t in closed)
    win_amount = sum(t.pnl for t in wins)
    loss_amount = sum(t.pnl for t in closed if t.pnl <= 0)
    win_rate = len(wins) / len(closed) * 100 if closed else 0
    pf = abs(win_amount / loss_amount) if loss_amount else float("inf")
    roi = total_pnl / initial_balance * 100

    return {
        "params": params,
        "trades": len(closed),
        "wins": len(wins),
        "win_rate": round(win_rate, 1),
        "total_pnl": round(total_pnl, 2),
        "roi_pct": round(roi, 2),
        "daily_roi": round(roi / BACKTEST_DAYS, 2),
        "profit_factor": round(pf, 2),
        "avg_win": round(win_amount / len(wins), 2) if wins else 0,
        "avg_loss": round(loss_amount / len([t for t in closed if t.pnl <= 0]), 2) if any(t.pnl <= 0 for t in closed) else 0,
        "daily_pnl": daily_pnl,
        "daily_locked": daily_locked,
        "all_trades": closed,
        "balance": round(balance, 2),
        "by_strategy": {},
    }


async def main():
    print("=" * 70)
    print("  TradingBrain v3 Multi-Parameter Backtest")
    print("  Target: 3-10% daily return")
    print("=" * 70)

    # 抓取數據
    print("\nFetching historical data...")
    async with httpx.AsyncClient(timeout=30.0) as client:
        kline_data = {}
        for symbol in SYMBOLS:
            kline_data[symbol] = {}
            for tf in TIMEFRAMES:
                extra = 30 if tf == "4h" else (10 if tf == "1h" else 3)
                df = await fetch_klines(client, symbol, tf, BACKTEST_DAYS + extra)
                if not df.empty:
                    kline_data[symbol][tf] = df
                    print(f"  OK {symbol} {tf}: {len(df)} candles")
                await asyncio.sleep(0.2)

    engine = AnalysisEngine()

    # 參數組合
    configs = [
        {
            "name": "A: Aggressive (5x, 3% risk, partial TP)",
            "adx_min": 20, "rsi_oversold": 30, "rsi_overbought": 70,
            "risk_per_trade": 0.03, "sl_atr_mult": 1.5, "tp_atr_mult": 3.0,
            "max_leverage": 5, "max_positions": 3, "cooldown_sec": 7200,
            "daily_loss_limit": 0.06, "daily_profit_target": 0.10,
            "partial_tp_mult": 1.5, "trailing_pct": 0.01,
        },
        {
            "name": "B: High Leverage (8x, 4% risk, partial TP)",
            "adx_min": 20, "rsi_oversold": 30, "rsi_overbought": 70,
            "risk_per_trade": 0.04, "sl_atr_mult": 1.5, "tp_atr_mult": 3.5,
            "max_leverage": 8, "max_positions": 3, "cooldown_sec": 5400,
            "daily_loss_limit": 0.08, "daily_profit_target": 0.15,
            "partial_tp_mult": 1.5, "trailing_pct": 0.012,
        },
        {
            "name": "C: Fast Rotation (5x, 3% risk, short cooldown)",
            "adx_min": 18, "rsi_oversold": 28, "rsi_overbought": 72,
            "risk_per_trade": 0.03, "sl_atr_mult": 1.2, "tp_atr_mult": 2.5,
            "max_leverage": 5, "max_positions": 4, "cooldown_sec": 3600,
            "daily_loss_limit": 0.06, "daily_profit_target": 0.12,
            "partial_tp_mult": 1.2, "trailing_pct": 0.008,
        },
        {
            "name": "D: Wide TP (5x, 3% risk, let profits run)",
            "adx_min": 22, "rsi_oversold": 30, "rsi_overbought": 70,
            "risk_per_trade": 0.03, "sl_atr_mult": 1.5, "tp_atr_mult": 4.0,
            "max_leverage": 5, "max_positions": 3, "cooldown_sec": 7200,
            "daily_loss_limit": 0.06, "daily_profit_target": 0,  # 不鎖利，讓利潤跑
            "partial_tp_mult": 2.0, "trailing_pct": 0.015,
        },
        {
            "name": "E: Conservative-Aggressive (5x, tight SL, high R:R)",
            "adx_min": 25, "rsi_oversold": 30, "rsi_overbought": 70,
            "risk_per_trade": 0.035, "sl_atr_mult": 1.0, "tp_atr_mult": 3.5,
            "max_leverage": 5, "max_positions": 3, "cooldown_sec": 5400,
            "daily_loss_limit": 0.07, "daily_profit_target": 0.10,
            "partial_tp_mult": 1.5, "trailing_pct": 0.01,
        },
    ]

    results = []
    for i, cfg in enumerate(configs):
        name = cfg.pop("name")
        print(f"\n--- Running config {name} ---")
        result = run_single_backtest(kline_data, engine, cfg, 5000.0)
        result["name"] = name
        results.append(result)
        cfg["name"] = name  # put back
        print(f"  Trades: {result['trades']} | WR: {result['win_rate']}% | "
              f"PnL: {result['total_pnl']:+.2f} | ROI: {result['roi_pct']:+.2f}% | "
              f"Daily: {result['daily_roi']:+.2f}% | PF: {result['profit_factor']}")

    # 排名
    results.sort(key=lambda r: r["total_pnl"], reverse=True)

    output_lines = []
    def out(s=""):
        output_lines.append(s)
        print(s)

    out()
    out("=" * 80)
    out("  RESULTS RANKING (by total PnL)")
    out("=" * 80)
    out(f"{'#':<3} {'Config':<50} {'Trades':>6} {'WR':>6} {'PnL':>10} {'ROI':>8} {'Daily':>8} {'PF':>6}")
    out("-" * 98)
    for i, r in enumerate(results):
        out(f"{i+1:<3} {r['name']:<50} {r['trades']:>6} {r['win_rate']:>5.1f}% {r['total_pnl']:>+10.2f} {r['roi_pct']:>+7.2f}% {r['daily_roi']:>+7.2f}% {r['profit_factor']:>6.2f}")

    # 最佳結果詳細報告
    best = results[0]
    out()
    out("=" * 80)
    out(f"  BEST CONFIG: {best['name']}")
    out("=" * 80)
    out(f"  Initial: 5000 U -> Final: {best['balance']} U")
    out(f"  Total PnL: {best['total_pnl']:+.2f} U | ROI: {best['roi_pct']:+.2f}%")
    out(f"  Daily ROI: {best['daily_roi']:+.2f}% | Trades: {best['trades']} | Win Rate: {best['win_rate']}%")
    out(f"  Avg Win: {best['avg_win']:+.2f} | Avg Loss: {best['avg_loss']:+.2f} | PF: {best['profit_factor']}")
    out()

    # 每日明細
    out(f"  {'Date':<12} {'PnL':>10} {'Cumulative':>12}")
    out("  " + "-" * 36)
    cum = 0
    for date in sorted(best["daily_pnl"].keys()):
        pnl = best["daily_pnl"][date]
        cum += pnl
        lock = " LOCKED" if date in best["daily_locked"] else ""
        out(f"  {date:<12} {pnl:>+10.2f} {cum:>+12.2f}{lock}")

    # 策略分佈
    if best["all_trades"]:
        out()
        out(f"  {'Strategy':<22} {'Trades':>6} {'WR':>8} {'PnL':>12}")
        out("  " + "-" * 50)
        for strat in set(t.strategy for t in best["all_trades"]):
            st = [t for t in best["all_trades"] if t.strategy == strat]
            sw = [t for t in st if t.pnl > 0]
            sp = sum(t.pnl for t in st)
            wr = len(sw) / len(st) * 100 if st else 0
            out(f"  {strat:<22} {len(st):>6} {wr:>7.1f}% {sp:>+12.2f}")

        # 幣種
        out()
        out(f"  {'Symbol':<12} {'Trades':>6} {'WR':>8} {'PnL':>12}")
        out("  " + "-" * 40)
        for sym in SYMBOLS:
            st = [t for t in best["all_trades"] if t.symbol == sym]
            if not st:
                continue
            sw = [t for t in st if t.pnl > 0]
            sp = sum(t.pnl for t in st)
            wr = len(sw) / len(st) * 100 if st else 0
            out(f"  {sym:<12} {len(st):>6} {wr:>7.1f}% {sp:>+12.2f}")

        # 最近交易
        out()
        out(f"  Trade Details (last 20):")
        out(f"  {'Symbol':<10} {'Dir':<6} {'Entry':>10} {'Exit':>10} {'PnL':>10} {'Reason':<12} {'Strategy':<18} {'Time':<19}")
        out("  " + "-" * 100)
        for t in best["all_trades"][-20:]:
            out(f"  {t.symbol:<10} {t.direction:<6} {t.entry_price:>10.2f} {t.exit_price:>10.2f} {t.pnl:>+10.2f} {t.exit_reason:<12} {t.strategy:<18} {t.entry_time[:19]}")

    # 最佳參數
    bp = best["params"]
    out()
    out("=" * 80)
    out("  RECOMMENDED risk_defaults.json (passive_income preset):")
    out("=" * 80)
    out(f'  "max_risk_per_trade": {bp["risk_per_trade"]},')
    out(f'  "stop_loss_atr_mult": {bp["sl_atr_mult"]},')
    out(f'  "take_profit_atr_mult": {bp["tp_atr_mult"]},')
    out(f'  "max_leverage": {bp["max_leverage"]},')
    out(f'  "max_open_positions": {bp["max_positions"]},')
    out(f'  "max_daily_loss": {bp["daily_loss_limit"]},')
    out(f'  "daily_profit_target": {bp["daily_profit_target"]},')
    out(f'  "partial_tp_atr_mult": {bp.get("partial_tp_mult", 0)},')
    out(f'  "trailing_stop_pct": {bp.get("trailing_pct", 0)},')
    out(f'  "cool_down_after_loss_sec": {bp["cooldown_sec"]},')

    # 寫入文件
    result_path = Path(__file__).parent / "backtest_v3_result.txt"
    with open(result_path, "w", encoding="utf-8") as f:
        f.write("\n".join(output_lines))
    print(f"\n[Results saved to {result_path}]")


if __name__ == "__main__":
    logger.remove()
    logger.add(lambda msg: None)
    asyncio.run(main())
