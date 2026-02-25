"""
回測引擎 (Backtest Engine)

依歷史 K 線逐根模擬：技術分析 → 策略信號 → 風控倉位/止損止盈 → 模擬成交（滑點 + 手續費）。
不經過否決引擎；可選是否啟用絞肉機/策略內建 skip_on_chop。
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
from loguru import logger

from config.settings import KLINE_DATA_DIR
from core.analysis.engine import AnalysisEngine
from core.analysis.indicators import add_all_indicators
from core.strategy.base import TradeSignal
from core.strategy.trend_following import TrendFollowingStrategy
from core.strategy.mean_reversion import MeanReversionStrategy
from core.risk.position_sizer import PositionSizer
from core.risk.stop_loss import StopLossCalculator


@dataclass
class BacktestTrade:
    """單筆回測交易"""
    entry_time: str
    exit_time: str
    side: str
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    pnl_pct: float
    fee: float
    exit_reason: str  # "stop_loss" | "take_profit" | "signal_reverse" | "end"


@dataclass
class BacktestResult:
    """回測結果"""
    trades: list[BacktestTrade] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    initial_balance: float = 0.0
    final_balance: float = 0.0
    total_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    win_rate: float = 0.0
    n_trades: int = 0
    n_wins: int = 0


class BacktestEngine:
    """
    單一標的、單一時間框架回測。
    使用與實盤相同的策略與風控公式，不含否決引擎。
    """

    def __init__(
        self,
        symbol: str = "BTCUSDT",
        timeframe: str = "15m",
        initial_balance: float = 300.0,
        slippage_pct: float = 0.001,
        fee_rate: float = 0.0004,
        max_open_positions: int = 1,
    ) -> None:
        self.symbol = symbol
        self.timeframe = timeframe
        self.initial_balance = initial_balance
        self.slippage_pct = slippage_pct
        self.fee_rate = fee_rate
        self.max_open_positions = max_open_positions

        self.analysis_engine = AnalysisEngine()
        self.strategies = [
            TrendFollowingStrategy(adx_min=25.0, skip_on_chop=True),
            MeanReversionStrategy(rsi_oversold=30, rsi_overbought=70, skip_on_chop=True),
        ]
        self.position_sizer = PositionSizer(db=None)
        self.stop_loss_calc = StopLossCalculator(db=None)

        self._default_risk_params = {
            "max_risk_per_trade": 0.02,
            "min_notional_value": 10,
            "max_leverage": 5,
            "stop_loss_atr_mult": 1.5,
            "take_profit_atr_mult": 2.25,
            "min_risk_reward": 1.5,
        }

    def load_data(self, source: str | Path | pd.DataFrame) -> pd.DataFrame:
        """
        載入 K 線。source 可為 Parquet 路徑、檔名、或 DataFrame。
        """
        if isinstance(source, pd.DataFrame):
            df = source.copy()
        elif isinstance(source, (str, Path)):
            path = Path(source)
            if not path.is_absolute():
                path = KLINE_DATA_DIR / path
            if not path.exists():
                path = KLINE_DATA_DIR / f"{self.symbol}_{self.timeframe}.parquet"
            if not path.exists():
                raise FileNotFoundError(f"Kline data not found: {path}")
            df = pd.read_parquet(path)
        else:
            raise TypeError("source must be DataFrame or path")

        for col in ("open", "high", "low", "close", "volume"):
            if col not in df.columns:
                raise ValueError(f"Missing column: {col}")
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.dropna(subset=["open", "high", "low", "close"])
        df = df.sort_values("open_time" if "open_time" in df.columns else df.index.name or df.index)
        df = df.reset_index(drop=True)
        return df

    def run(self, df: pd.DataFrame) -> BacktestResult:
        """
        執行回測。df 需含 open, high, low, close, volume。
        """
        if len(df) < 100:
            logger.warning("Not enough bars for backtest")
            return BacktestResult(initial_balance=self.initial_balance, final_balance=self.initial_balance)

        balance = self.initial_balance
        position: dict[str, Any] | None = None  # side, entry_price, quantity, sl, tp, entry_time, entry_idx
        trades: list[BacktestTrade] = []
        equity_curve: list[float] = [balance]

        lookback = 100
        for i in range(lookback, len(df)):
            window = df.iloc[: i + 1].copy()
            row = window.iloc[-1]
            o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
            atr = None

            # 先檢查既有持倉是否觸及止損/止盈
            if position:
                pos_side = position["side"]
                sl = position["sl"]
                tp = position["tp"]
                qty = position["quantity"]
                entry_price = position["entry_price"]
                entry_time = str(position["entry_time"])
                exit_price = None
                exit_reason = None

                if pos_side == "LONG":
                    if l <= sl:
                        exit_price = sl * (1 - self.slippage_pct)
                        exit_reason = "stop_loss"
                    elif h >= tp:
                        exit_price = tp * (1 + self.slippage_pct)
                        exit_reason = "take_profit"
                else:
                    if h >= sl:
                        exit_price = sl * (1 + self.slippage_pct)
                        exit_reason = "stop_loss"
                    elif l <= tp:
                        exit_price = tp * (1 - self.slippage_pct)
                        exit_reason = "take_profit"

                if exit_price is not None and exit_reason:
                    fee = (entry_price * qty + exit_price * qty) * self.fee_rate
                    pnl = (exit_price - entry_price) * qty if pos_side == "LONG" else (entry_price - exit_price) * qty
                    pnl -= fee
                    pnl_pct = (pnl / (entry_price * qty)) * 100
                    balance += pnl
                    trades.append(
                        BacktestTrade(
                            entry_time=entry_time,
                            exit_time=str(i),
                            side=pos_side,
                            entry_price=entry_price,
                            exit_price=exit_price,
                            quantity=qty,
                            pnl=pnl,
                            pnl_pct=pnl_pct,
                            fee=fee,
                            exit_reason=exit_reason,
                        )
                    )
                    position = None

            # 若無持倉且未達最大倉位，嘗試產生信號並開倉
            if position is None:
                result = self.analysis_engine.analyze_single(
                    self.symbol, self.timeframe, window
                )
                if result.df_enriched is not None and len(result.df_enriched) > 0:
                    atr = float(result.df_enriched["atr"].iloc[-1]) if "atr" in result.df_enriched.columns else (h - l)
                else:
                    atr = h - l if (h - l) > 0 else c * 0.01

                candidates: list[TradeSignal] = []
                for st in self.strategies:
                    candidates.extend(st.evaluate_single(self.symbol, self.timeframe, result))

                if candidates:
                    sig = candidates[0]
                    if sig.signal_type in ("LONG", "SHORT"):
                        size_result = self.position_sizer.compute(
                            balance=balance,
                            entry_price=c,
                            atr=atr,
                            direction=sig.signal_type,
                        )
                        sl_result = self.stop_loss_calc.compute(
                            entry_price=c, atr=atr, direction=sig.signal_type
                        )
                        if not size_result.rejected and not sl_result.rejected and size_result.size_usdt >= 10:
                            fill_price = c * (1 + self.slippage_pct) if sig.signal_type == "LONG" else c * (1 - self.slippage_pct)
                            qty = size_result.size_usdt / fill_price
                            fee_open = size_result.size_usdt * self.fee_rate
                            balance -= fee_open
                            position = {
                                "side": sig.signal_type,
                                "entry_price": fill_price,
                                "quantity": qty,
                                "sl": sl_result.stop_loss,
                                "tp": sl_result.take_profit,
                                "entry_time": str(i),
                                "entry_idx": i,
                            }

            equity_curve.append(balance)

        # 若回測結束仍持倉，以最後收盤價平倉
        if position:
            c = float(df.iloc[-1]["close"])
            entry_price = position["entry_price"]
            qty = position["quantity"]
            pos_side = position["side"]
            exit_price = c * (1 - self.slippage_pct) if pos_side == "LONG" else c * (1 + self.slippage_pct)
            fee = (entry_price * qty + exit_price * qty) * self.fee_rate
            pnl = (exit_price - entry_price) * qty if pos_side == "LONG" else (entry_price - exit_price) * qty
            pnl -= fee
            balance += pnl
            trades.append(
                BacktestTrade(
                    entry_time=position["entry_time"],
                    exit_time=str(len(df) - 1),
                    side=pos_side,
                    entry_price=entry_price,
                    exit_price=exit_price,
                    quantity=qty,
                    pnl=pnl,
                    pnl_pct=(pnl / (entry_price * qty)) * 100,
                    fee=fee,
                    exit_reason="end",
                )
            )

        n_wins = sum(1 for t in trades if t.pnl > 0)
        n_trades = len(trades)
        win_rate = (n_wins / n_trades * 100) if n_trades else 0
        total_return_pct = (balance - self.initial_balance) / self.initial_balance * 100 if self.initial_balance else 0

        peak = self.initial_balance
        max_dd = 0.0
        for eq in equity_curve:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak * 100 if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd

        return BacktestResult(
            trades=trades,
            equity_curve=equity_curve,
            initial_balance=self.initial_balance,
            final_balance=balance,
            total_return_pct=total_return_pct,
            max_drawdown_pct=max_dd,
            win_rate=win_rate,
            n_trades=n_trades,
            n_wins=n_wins,
        )