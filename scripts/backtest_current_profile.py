"""
Faster 30-day backtest using the current strategy routing and exit profiles.

This version avoids re-running full indicator calculation on every candle. It:
- reuses cached Binance klines when available
- precomputes enriched data once per symbol / timeframe
- slices prepared windows with searchsorted instead of dataframe filtering
- builds lightweight AnalysisResult / FullAnalysis objects from precomputed data
"""

import asyncio
import os
import sys
import time
from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
import pandas as pd
from loguru import logger

from core.analysis.candlestick import detect_all_patterns
from core.analysis.chop_detector import detect_chop
from core.analysis.divergence import detect_all_divergences
from core.analysis.engine import AnalysisResult, FullAnalysis
from core.analysis.fibonacci import get_fib_summary
from core.analysis.indicators import add_all_indicators, get_indicator_summary, get_trend_direction
from core.analysis.multi_timeframe import (
    MTFAnalysis,
    TimeframeAlignment,
    analyze_multi_timeframe,
    check_htf_rsi_confirmation,
)
from core.risk.position_sizer import PositionSizer
from core.risk.stop_loss import StopLossCalculator
from core.strategy.breakout import BreakoutStrategy
from core.strategy.mean_reversion import MeanReversionStrategy
from core.strategy.trend_following import TrendFollowingStrategy


KLINE_COLUMNS = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "trades",
    "taker_buy_volume",
    "taker_buy_quote_volume",
    "ignore",
]

SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "ADAUSDT",
    "DOGEUSDT",
    "AVAXUSDT",
    "DOTUSDT",
    "LINKUSDT",
]

BACKTEST_DAYS = 30
PRIMARY_TF = "15m"
TIMEFRAMES = ["15m", "1h", "4h"]
FEE_RATE = 0.0004
SLIPPAGE_RATE = 0.0005
INITIAL_BALANCE = 5000.0
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "klines"
WINDOW_BARS = 200
MIN_BARS = 50
FAST_MODE = os.getenv("BACKTEST_FAST_MODE", "true").lower() == "true"

PARAMS = {
    "adx_min": 22,
    "rsi_oversold": 30,
    "rsi_overbought": 70,
    "risk_per_trade": 0.03,
    "sl_atr_mult": 1.5,
    "tp1_atr_mult": 2.0,
    "tp2_atr_mult": 3.0,
    "tp3_atr_mult": 4.5,
    "max_leverage": 5,
    "max_positions": 3,
    "cooldown_sec": 7200,
    "daily_loss_limit": 0.06,
}

MEAN_REVERSION_PARAMS = {
    "sl_atr_mult": 1.25,
    "tp1_atr_mult": 1.0,
    "tp2_atr_mult": 1.8,
    "tp1_close_pct": 0.75,
}

TP1_CLOSE_PCT = 0.30
TP2_CLOSE_PCT = 0.30


class BacktestRiskParamsDB:
    """Tiny adapter so backtests can reuse runtime risk calculators."""

    def get_risk_params(self) -> dict:
        return {
            "max_risk_per_trade": PARAMS["risk_per_trade"],
            "min_notional_value": 10,
            "max_leverage": PARAMS["max_leverage"],
            "max_open_positions": PARAMS["max_positions"],
            "stop_loss_atr_mult": PARAMS["sl_atr_mult"],
            "take_profit_atr_mult": 2.25,
            "tp1_atr_mult": PARAMS["tp1_atr_mult"],
            "tp2_atr_mult": PARAMS["tp2_atr_mult"],
            "min_risk_reward": 1.5,
            "mean_reversion_stop_loss_atr_mult": MEAN_REVERSION_PARAMS["sl_atr_mult"],
            "mean_reversion_tp1_atr_mult": MEAN_REVERSION_PARAMS["tp1_atr_mult"],
            "mean_reversion_tp2_atr_mult": MEAN_REVERSION_PARAMS["tp2_atr_mult"],
            "mean_reversion_min_risk_reward": 1.2,
        }


async def fetch_klines(client: httpx.AsyncClient, symbol: str, interval: str, days: int) -> pd.DataFrame:
    all_dfs: list[pd.DataFrame] = []
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
            response = await client.get(
                "https://fapi.binance.com/fapi/v1/klines",
                params=params,
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            print(f"  WARN: {symbol} {interval} fetch failed: {exc}")
            break

        if not data:
            break

        df = pd.DataFrame(data, columns=KLINE_COLUMNS)
        for column in (
            "open",
            "high",
            "low",
            "close",
            "volume",
            "quote_volume",
            "taker_buy_volume",
            "taker_buy_quote_volume",
        ):
            df[column] = df[column].astype(float)
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


def _cache_path(symbol: str, interval: str, days: int) -> Path:
    return CACHE_DIR / f"bt_{days}d_{symbol}_{interval}.parquet"


async def load_or_fetch_klines(
    client: httpx.AsyncClient,
    symbol: str,
    interval: str,
    days: int,
) -> pd.DataFrame:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_path(symbol, interval, days)
    if path.exists():
        try:
            return pd.read_parquet(path)
        except Exception:
            pass

    df = await fetch_klines(client, symbol, interval, days)
    if not df.empty:
        df.to_parquet(path, index=False)
    return df


@dataclass
class PreparedFrame:
    df: pd.DataFrame
    open_time_ns: list[int]


def prepare_frame(df: pd.DataFrame) -> PreparedFrame:
    enriched = add_all_indicators(df)
    open_time_ns = enriched["open_time"].astype("int64").tolist()
    return PreparedFrame(df=enriched, open_time_ns=open_time_ns)


class CurrentTrade:
    def __init__(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        size_usdt: float,
        stop_loss: float,
        tp1: float,
        tp2: float,
        tp3: float,
        atr: float,
        strategy: str,
        entry_time: str,
    ) -> None:
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

    @property
    def is_mean_reversion(self) -> bool:
        return self.strategy == "mean_reversion"

    def _realize_partial(self, exit_price: float, close_size: float) -> None:
        if self.direction == "LONG":
            raw = (exit_price - self.entry_price) / self.entry_price * close_size
        else:
            raw = (self.entry_price - exit_price) / self.entry_price * close_size
        self.realized_partial += raw - close_size * FEE_RATE
        self.remaining_size -= close_size

    def check_exit(self, high: float, low: float, close_time: str) -> bool:
        if not self.is_open:
            return False

        if self.direction == "LONG":
            self.best_price = max(self.best_price, high)
        else:
            self.best_price = min(self.best_price, low)

        if self.tp_stage == 0 and self.tp1:
            tp1_hit = (self.direction == "LONG" and high >= self.tp1) or (
                self.direction == "SHORT" and low <= self.tp1
            )
            if tp1_hit:
                close_pct = (
                    MEAN_REVERSION_PARAMS["tp1_close_pct"]
                    if self.is_mean_reversion
                    else TP1_CLOSE_PCT
                )
                self._realize_partial(self.tp1, self.size_usdt * close_pct)
                self.stop_loss = self.entry_price
                self.tp_stage = 1

        if self.tp_stage == 1 and self.tp2:
            tp2_hit = (self.direction == "LONG" and high >= self.tp2) or (
                self.direction == "SHORT" and low <= self.tp2
            )
            if tp2_hit:
                if self.is_mean_reversion:
                    self._close(self.tp2, close_time, "TP2")
                    return True

                self._realize_partial(self.tp2, self.size_usdt * TP2_CLOSE_PCT)
                self.stop_loss = self.tp1
                self.tp_stage = 2

        if not self.is_mean_reversion:
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

        if self.direction == "LONG" and low <= self.stop_loss:
            reason = ["STOP_LOSS", "TRAILING_SL_AFTER_TP1", "TRAILING_SL_AFTER_TP2"][
                min(self.tp_stage, 2)
            ]
            self._close(self.stop_loss, close_time, reason)
            return True
        if self.direction == "SHORT" and high >= self.stop_loss:
            reason = ["STOP_LOSS", "TRAILING_SL_AFTER_TP1", "TRAILING_SL_AFTER_TP2"][
                min(self.tp_stage, 2)
            ]
            self._close(self.stop_loss, close_time, reason)
            return True

        if not self.is_mean_reversion and self.tp_stage == 2 and self.tp3:
            tp3_hit = (self.direction == "LONG" and high >= self.tp3) or (
                self.direction == "SHORT" and low <= self.tp3
            )
            if tp3_hit:
                self._close(self.tp3, close_time, "TP3")
                return True

        return False

    def _close(self, exit_price: float, exit_time: str, reason: str) -> None:
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


def build_analysis_result(symbol: str, timeframe: str, window: pd.DataFrame) -> AnalysisResult:
    if FAST_MODE:
        return AnalysisResult(
            symbol=symbol,
            timeframe=timeframe,
            indicators=get_indicator_summary(window),
            divergences=[],
            fibonacci={"available": False},
            candle_patterns=[],
            chop=None,
            df_enriched=window,
        )

    return AnalysisResult(
        symbol=symbol,
        timeframe=timeframe,
        indicators=get_indicator_summary(window),
        divergences=detect_all_divergences(window, lookback=min(60, len(window))),
        fibonacci=get_fib_summary(window, lookback=min(100, len(window))),
        candle_patterns=detect_all_patterns(window, lookback=min(10, len(window))),
        chop=detect_chop(window),
        df_enriched=window,
    )


class SymbolBacktestAnalyzer:
    def __init__(self, symbol: str, prepared_by_tf: dict[str, PreparedFrame]) -> None:
        self.symbol = symbol
        self.prepared_by_tf = prepared_by_tf
        self._window_cache: dict[tuple[str, int], pd.DataFrame] = {}
        self._analysis_cache: dict[tuple[str, int], AnalysisResult] = {}

    def _end_idx_for_time(self, prepared: PreparedFrame, candle_time_ns: int) -> int:
        return bisect_right(prepared.open_time_ns, candle_time_ns) - 1

    def _window(self, tf: str, candle_time_ns: int) -> pd.DataFrame | None:
        prepared = self.prepared_by_tf.get(tf)
        if prepared is None:
            return None
        end_idx = self._end_idx_for_time(prepared, candle_time_ns)
        if end_idx + 1 < MIN_BARS:
            return None
        cache_key = (tf, end_idx)
        if cache_key in self._window_cache:
            return self._window_cache[cache_key]
        start_idx = max(0, end_idx + 1 - WINDOW_BARS)
        window = prepared.df.iloc[start_idx : end_idx + 1]
        self._window_cache[cache_key] = window
        return window

    def _analysis(self, tf: str, candle_time_ns: int) -> AnalysisResult | None:
        prepared = self.prepared_by_tf.get(tf)
        if prepared is None:
            return None
        end_idx = self._end_idx_for_time(prepared, candle_time_ns)
        if end_idx + 1 < MIN_BARS:
            return None
        cache_key = (tf, end_idx)
        if cache_key in self._analysis_cache:
            return self._analysis_cache[cache_key]
        window = self._window(tf, candle_time_ns)
        if window is None:
            return None
        result = build_analysis_result(self.symbol, tf, window)
        self._analysis_cache[cache_key] = result
        return result

    def build_full_analysis(self, candle_time_ns: int) -> FullAnalysis | None:
        single_tf_results: dict[str, AnalysisResult] = {}
        mtf_input: dict[str, pd.DataFrame] = {}

        for tf in TIMEFRAMES:
            result = self._analysis(tf, candle_time_ns)
            if result is None or result.df_enriched is None:
                continue
            single_tf_results[tf] = result
            mtf_input[tf] = result.df_enriched

        if len(single_tf_results) < 2 or PRIMARY_TF not in single_tf_results:
            return None

        full = FullAnalysis(
            symbol=self.symbol,
            primary_tf=PRIMARY_TF,
            single_tf_results=single_tf_results,
        )
        if FAST_MODE:
            full.mtf = analyze_precomputed_multi_timeframe(mtf_input)
            if full.mtf.recommended_direction:
                full.htf_rsi_confirmed = check_precomputed_htf_rsi_confirmation(
                    mtf_input,
                    full.mtf.recommended_direction,
                )
        else:
            full.mtf = analyze_multi_timeframe(mtf_input, PRIMARY_TF)
            if full.mtf.recommended_direction:
                full.htf_rsi_confirmed = check_htf_rsi_confirmation(
                    mtf_input,
                    full.mtf.recommended_direction,
                )
        return full


def analyze_precomputed_multi_timeframe(kline_data: dict[str, pd.DataFrame]) -> MTFAnalysis:
    details: dict[str, str] = {}
    trends: list[str] = []

    for tf in ["1d", "4h", "1h", "15m", "5m"]:
        if tf not in kline_data:
            continue
        df = kline_data[tf]
        if df.empty or len(df) < 50:
            details[tf] = "INSUFFICIENT"
            continue
        trend = get_trend_direction(df)
        details[tf] = trend
        trends.append(trend)

    if len(trends) < 2:
        return MTFAnalysis(
            alignment=TimeframeAlignment.INSUFFICIENT_DATA,
            details=details,
            confidence=0.0,
            recommended_direction=None,
        )

    bullish_count = trends.count("BULLISH")
    bearish_count = trends.count("BEARISH")
    total = len(trends)

    if bullish_count == total:
        return MTFAnalysis(
            alignment=TimeframeAlignment.ALIGNED_BULLISH,
            details=details,
            confidence=1.0,
            recommended_direction="LONG",
        )
    if bearish_count == total:
        return MTFAnalysis(
            alignment=TimeframeAlignment.ALIGNED_BEARISH,
            details=details,
            confidence=1.0,
            recommended_direction="SHORT",
        )

    htf_trends = []
    for tf in ["1d", "4h", "1h"]:
        if tf in details and details[tf] in ("BULLISH", "BEARISH"):
            htf_trends.append(details[tf])

    if not htf_trends:
        return MTFAnalysis(
            alignment=TimeframeAlignment.CONFLICTING,
            details=details,
            confidence=0.0,
            recommended_direction=None,
        )

    htf_bullish = htf_trends.count("BULLISH")
    htf_bearish = htf_trends.count("BEARISH")
    if htf_bullish > htf_bearish:
        direction = "LONG"
        confidence = htf_bullish / len(htf_trends) * (bullish_count / total)
    elif htf_bearish > htf_bullish:
        direction = "SHORT"
        confidence = htf_bearish / len(htf_trends) * (bearish_count / total)
    else:
        return MTFAnalysis(
            alignment=TimeframeAlignment.CONFLICTING,
            details=details,
            confidence=0.3,
            recommended_direction=None,
        )

    return MTFAnalysis(
        alignment=(
            TimeframeAlignment.ALIGNED_BULLISH
            if direction == "LONG"
            else TimeframeAlignment.ALIGNED_BEARISH
        ),
        details=details,
        confidence=round(confidence, 2),
        recommended_direction=direction,
    )


def check_precomputed_htf_rsi_confirmation(
    kline_data: dict[str, pd.DataFrame],
    direction: str,
) -> bool:
    for tf in ["4h", "1h"]:
        if tf not in kline_data:
            continue
        df = kline_data[tf]
        if df.empty or "rsi" not in df.columns:
            continue
        rsi = df["rsi"].iloc[-1]
        if pd.isna(rsi):
            continue
        if direction == "LONG" and rsi > 75:
            return False
        if direction == "SHORT" and rsi < 25:
            return False
    return True


def summarize_results(
    out: list[str],
    balance: float,
    all_trades: list[CurrentTrade],
) -> None:
    def p(text: str = "") -> None:
        out.append(text)
        print(text)

    closed = [trade for trade in all_trades if not trade.is_open]
    wins = [trade for trade in closed if trade.pnl > 0]
    losses = [trade for trade in closed if trade.pnl <= 0]
    total_pnl = sum(trade.pnl for trade in closed)
    roi = total_pnl / INITIAL_BALANCE * 100
    win_amt = sum(trade.pnl for trade in wins) if wins else 0.0
    loss_amt = sum(trade.pnl for trade in losses) if losses else 0.0
    pf = abs(win_amt / loss_amt) if loss_amt else float("inf")

    p()
    p("=" * 80)
    p("  30-DAY BACKTEST RESULTS (current profile)")
    p("=" * 80)
    p(f"  Initial: {INITIAL_BALANCE:.0f} U -> Final: {balance:.2f} U")
    p(f"  Total PnL: {total_pnl:+.2f} U | ROI: {roi:+.2f}%")
    p(f"  Daily avg ROI: {roi / BACKTEST_DAYS:+.2f}%")
    p(f"  Trades: {len(closed)} | Wins: {len(wins)} | Losses: {len(losses)}")
    if closed:
        p(f"  Win Rate: {len(wins) / len(closed) * 100:.1f}%")
    p(f"  Profit Factor: {pf:.2f}")
    if wins:
        p(f"  Avg Win: {win_amt / len(wins):+.2f}")
    if losses:
        p(f"  Avg Loss: {loss_amt / len(losses):+.2f}")

    reason_counts: dict[str, int] = {}
    reason_pnl: dict[str, float] = {}
    for trade in closed:
        reason_counts[trade.exit_reason] = reason_counts.get(trade.exit_reason, 0) + 1
        reason_pnl[trade.exit_reason] = reason_pnl.get(trade.exit_reason, 0.0) + trade.pnl

    p()
    p(f"  {'Exit Reason':<24} {'Count':>6} {'PnL':>12}")
    p("  " + "-" * 46)
    for reason in sorted(reason_counts):
        p(f"  {reason:<24} {reason_counts[reason]:>6} {reason_pnl[reason]:>+12.2f}")

    peak = INITIAL_BALANCE
    max_dd = 0.0
    running = INITIAL_BALANCE
    for trade in closed:
        running += trade.pnl
        if running > peak:
            peak = running
        dd = (peak - running) / peak * 100 if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
    p(f"\n  Max Drawdown: {max_dd:.1f}%")

    p()
    p(f"  {'Strategy':<22} {'N':>5} {'WR':>7} {'PnL':>12}")
    p("  " + "-" * 48)
    for strategy_name in sorted({trade.strategy for trade in closed}):
        subset = [trade for trade in closed if trade.strategy == strategy_name]
        subset_wins = [trade for trade in subset if trade.pnl > 0]
        strategy_pnl = sum(trade.pnl for trade in subset)
        wr = len(subset_wins) / len(subset) * 100 if subset else 0.0
        p(f"  {strategy_name:<22} {len(subset):>5} {wr:>6.1f}% {strategy_pnl:>+12.2f}")

    p()
    p(f"  {'Direction':<12} {'N':>5} {'WR':>7} {'PnL':>12}")
    p("  " + "-" * 38)
    for direction in ("LONG", "SHORT"):
        subset = [trade for trade in closed if trade.direction == direction]
        subset_wins = [trade for trade in subset if trade.pnl > 0]
        direction_pnl = sum(trade.pnl for trade in subset)
        wr = len(subset_wins) / len(subset) * 100 if subset else 0.0
        p(f"  {direction:<12} {len(subset):>5} {wr:>6.1f}% {direction_pnl:>+12.2f}")

    p()
    p(f"  {'Strategy / Dir':<22} {'N':>5} {'WR':>7} {'PnL':>12}")
    p("  " + "-" * 48)
    combos = sorted({(trade.strategy, trade.direction) for trade in closed})
    for strategy_name, direction in combos:
        subset = [
            trade
            for trade in closed
            if trade.strategy == strategy_name and trade.direction == direction
        ]
        subset_wins = [trade for trade in subset if trade.pnl > 0]
        combo_pnl = sum(trade.pnl for trade in subset)
        wr = len(subset_wins) / len(subset) * 100 if subset else 0.0
        label = f"{strategy_name} / {direction}"
        p(f"  {label:<22} {len(subset):>5} {wr:>6.1f}% {combo_pnl:>+12.2f}")


async def main() -> None:
    out: list[str] = []

    def p(text: str = "") -> None:
        out.append(text)
        print(text)

    start_at = time.perf_counter()
    p("=" * 80)
    p("  TradingBrain current-profile 30-Day Backtest")
    p("  Uses strategy-specific exits, including mean_reversion dedicated profile")
    p("=" * 80)
    p(f"  Period: {BACKTEST_DAYS} days | Balance: {INITIAL_BALANCE} U")
    p(f"  Mode: {'FAST' if FAST_MODE else 'FULL'}")
    p(f"  Symbols: {len(SYMBOLS)} | Risk/trade: {PARAMS['risk_per_trade'] * 100}%")
    p(f"  Trend/Breakout SL: {PARAMS['sl_atr_mult']} ATR")
    p(
        "  Mean reversion: SL=1.25 ATR | TP1=1.0 ATR (close 75%) | "
        "TP2=1.8 ATR | no TP3 / no trailing"
    )
    p("=" * 80)

    p("\nFetching 30 days of data...")
    async with httpx.AsyncClient(timeout=30.0) as client:
        raw_kline_data: dict[str, dict[str, pd.DataFrame]] = {}
        for symbol in SYMBOLS:
            raw_kline_data[symbol] = {}
            for tf in TIMEFRAMES:
                extra = 40 if tf == "4h" else (15 if tf == "1h" else 5)
                df = await load_or_fetch_klines(client, symbol, tf, BACKTEST_DAYS + extra)
                if not df.empty:
                    raw_kline_data[symbol][tf] = df
                    p(f"  OK {symbol} {tf}: {len(df)}")
                await asyncio.sleep(0.05)

    p("\nPreparing indicators once per symbol/timeframe...")
    prepared_data: dict[str, dict[str, PreparedFrame]] = {}
    analyzers: dict[str, SymbolBacktestAnalyzer] = {}
    for symbol in SYMBOLS:
        prepared_data[symbol] = {}
        for tf, df in raw_kline_data.get(symbol, {}).items():
            if df.empty:
                continue
            prepared_data[symbol][tf] = prepare_frame(df)
        analyzers[symbol] = SymbolBacktestAnalyzer(symbol, prepared_data[symbol])

    strategies = [
        TrendFollowingStrategy(adx_min=PARAMS["adx_min"], skip_on_chop=True),
        MeanReversionStrategy(
            rsi_oversold=PARAMS["rsi_oversold"],
            rsi_overbought=PARAMS["rsi_overbought"],
            skip_on_chop=True,
        ),
        BreakoutStrategy(skip_on_chop=True),
    ]
    risk_db = BacktestRiskParamsDB()
    position_sizer = PositionSizer(db=risk_db)
    stop_loss_calc = StopLossCalculator(db=risk_db)

    p("\nRunning simulation...")
    balance = INITIAL_BALANCE
    all_trades: list[CurrentTrade] = []
    open_trades: list[CurrentTrade] = []
    symbol_cooldown: dict[tuple[str, str], float] = {}
    daily_pnl: dict[str, float] = {}
    now_ts = datetime.now(timezone.utc).timestamp()
    backtest_start_ts = now_ts - BACKTEST_DAYS * 86400

    for symbol in SYMBOLS:
        if PRIMARY_TF not in prepared_data.get(symbol, {}):
            continue
        primary_prepared = prepared_data[symbol][PRIMARY_TF]
        primary_df = primary_prepared.df
        if len(primary_df) < 100:
            continue

        for i in range(100, len(primary_df)):
            candle_time = primary_df.iloc[i]["open_time"]
            candle_time_ns = int(pd.Timestamp(candle_time).value)
            candle_ts = candle_time.timestamp()
            if candle_ts < backtest_start_ts:
                continue
            current_date = str(candle_time.date())
            candle = primary_df.iloc[i]

            for trade in list(open_trades):
                if trade.symbol != symbol:
                    continue
                closed = trade.check_exit(
                    float(candle["high"]),
                    float(candle["low"]),
                    str(candle_time),
                )
                if closed:
                    balance += trade.pnl
                    open_trades.remove(trade)
                    daily_pnl[current_date] = daily_pnl.get(current_date, 0.0) + trade.pnl

            today_pnl = daily_pnl.get(current_date, 0.0)
            start_equity = balance - today_pnl
            if today_pnl < -(start_equity * PARAMS["daily_loss_limit"]):
                continue
            if len(open_trades) >= PARAMS["max_positions"]:
                continue

            full = analyzers[symbol].build_full_analysis(candle_time_ns)
            if full is None:
                continue

            signals = []
            for strategy in strategies:
                signals.extend(strategy.evaluate_full(full, primary_tf=PRIMARY_TF))
            if not signals:
                continue

            signal = max(signals, key=lambda sig: sig.strength)
            cooldown_key = (signal.symbol, signal.signal_type)
            if candle_ts - symbol_cooldown.get(cooldown_key, 0.0) < PARAMS["cooldown_sec"]:
                continue
            if any(t.symbol == symbol and t.is_open for t in open_trades):
                continue

            primary_result = full.single_tf_results.get(PRIMARY_TF)
            if not primary_result or primary_result.df_enriched is None:
                continue

            entry_price = float(primary_result.df_enriched["close"].iloc[-1])
            atr_value = primary_result.indicators.get("atr")
            if atr_value is None:
                continue
            atr = float(atr_value)
            if atr <= 0 or entry_price <= 0:
                continue

            sl_result = stop_loss_calc.compute(
                entry_price=entry_price,
                atr=atr,
                direction=signal.signal_type,
                strategy_name=signal.strategy_name,
                structure_df=primary_result.df_enriched.tail(WINDOW_BARS),
            )
            if sl_result.rejected:
                continue
            size_result = position_sizer.compute(
                balance=balance,
                entry_price=entry_price,
                atr=atr,
                direction=signal.signal_type,
                stop_loss_price=sl_result.stop_loss,
            )
            if size_result.rejected or size_result.size_usdt < 10:
                continue

            trade = CurrentTrade(
                symbol=symbol,
                direction=signal.signal_type,
                entry_price=entry_price,
                size_usdt=size_result.size_usdt,
                stop_loss=sl_result.stop_loss,
                tp1=sl_result.tp1,
                tp2=sl_result.tp2,
                tp3=sl_result.tp3,
                atr=atr,
                strategy=signal.strategy_name,
                entry_time=str(candle_time),
            )
            open_trades.append(trade)
            all_trades.append(trade)
            symbol_cooldown[cooldown_key] = candle_ts

    for trade in list(open_trades):
        if not trade.is_open:
            continue
        if trade.symbol not in prepared_data or PRIMARY_TF not in prepared_data[trade.symbol]:
            continue
        last = prepared_data[trade.symbol][PRIMARY_TF].df.iloc[-1]
        trade._close(float(last["close"]), str(last["open_time"]), "FORCE_CLOSE")
        balance += trade.pnl

    summarize_results(out, balance, all_trades)
    elapsed = time.perf_counter() - start_at
    p(f"\n  Runtime: {elapsed:.1f}s")

    result_name = (
        "backtest_current_profile_fast_result.txt"
        if FAST_MODE
        else "backtest_current_profile_result.txt"
    )
    result_path = Path(__file__).parent / result_name
    with open(result_path, "w", encoding="utf-8") as file:
        file.write("\n".join(out))
    print(f"\n[Saved to {result_path}]")


if __name__ == "__main__":
    logger.remove()
    logger.add(lambda msg: None)
    asyncio.run(main())
