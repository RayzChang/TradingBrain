"""
技術指標計算模組

使用 ta 庫計算所有核心技術指標。
輸入 DataFrame 必須包含: open, high, low, close, volume 欄位。
所有函數返回帶有新增指標欄位的 DataFrame。
"""

import pandas as pd
import ta
from ta.momentum import RSIIndicator, StochRSIIndicator
from ta.trend import MACD, EMAIndicator, SMAIndicator, ADXIndicator
from ta.volatility import BollingerBands, AverageTrueRange
from ta.volume import OnBalanceVolumeIndicator, VolumeWeightedAveragePrice
from loguru import logger


def _safe_round(value, digits: int = 4):
    """Return a rounded float when possible, otherwise None."""
    try:
        value_f = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(value_f):
        return None
    return round(value_f, digits)


def add_all_indicators(df: pd.DataFrame, verbose: bool = False) -> pd.DataFrame:
    """
    一次計算所有核心技術指標。

    Args:
        df: 必須包含 open, high, low, close, volume 欄位
        verbose: 是否記錄計算日誌

    Returns:
        DataFrame with all indicator columns added
    """
    if df.empty or len(df) < 30:
        logger.warning("Not enough data for indicator calculation")
        return df

    df = df.copy()
    df = add_rsi(df)
    df = add_macd(df)
    df = add_bollinger_bands(df)
    df = add_ema(df)
    df = add_sma(df)
    df = add_atr(df)
    df = add_adx(df)
    df = add_obv(df)
    df = add_stoch_rsi(df)

    if "open_time" in df.columns:
        df = add_vwap(df)

    if verbose:
        logger.debug(f"Indicators calculated: {len(df)} candles, {len(df.columns)} columns")

    return df


def add_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """RSI (Relative Strength Index) — 超買(>70)/超賣(<30)判定"""
    df = df.copy()
    rsi = RSIIndicator(close=df["close"], window=period)
    df["rsi"] = rsi.rsi()
    return df


def add_macd(
    df: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    """MACD — 趨勢動能指標，用於交叉信號和背離偵測"""
    df = df.copy()
    macd = MACD(close=df["close"], window_fast=fast, window_slow=slow, window_sign=signal)
    df["macd"] = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["macd_hist"] = macd.macd_diff()
    return df


def add_bollinger_bands(
    df: pd.DataFrame,
    period: int = 20,
    std_dev: float = 2.0,
) -> pd.DataFrame:
    """布林帶 — 波動率通道，觸及上下軌可作為均值回歸信號"""
    df = df.copy()
    bb = BollingerBands(close=df["close"], window=period, window_dev=std_dev)
    df["bb_upper"] = bb.bollinger_hband()
    df["bb_middle"] = bb.bollinger_mavg()
    df["bb_lower"] = bb.bollinger_lband()
    df["bb_width"] = bb.bollinger_wband()
    df["bb_pct"] = bb.bollinger_pband()
    return df


def add_ema(
    df: pd.DataFrame,
    periods: list[int] | None = None,
) -> pd.DataFrame:
    """EMA (Exponential Moving Average) — 趨勢方向判定"""
    df = df.copy()
    for p in (periods or [9, 21, 50, 200]):
        if len(df) >= p:
            ema = EMAIndicator(close=df["close"], window=p)
            df[f"ema_{p}"] = ema.ema_indicator()
    return df


def add_sma(
    df: pd.DataFrame,
    periods: list[int] | None = None,
) -> pd.DataFrame:
    """SMA (Simple Moving Average)"""
    df = df.copy()
    for p in (periods or [20, 50, 200]):
        if len(df) >= p:
            sma = SMAIndicator(close=df["close"], window=p)
            df[f"sma_{p}"] = sma.sma_indicator()
    return df


def add_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """ATR (Average True Range) — 波動率度量，用於動態止損和絞肉機偵測"""
    df = df.copy()
    atr = AverageTrueRange(
        high=df["high"], low=df["low"], close=df["close"], window=period
    )
    df["atr"] = atr.average_true_range()
    return df


def add_adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """ADX (Average Directional Index) — 趨勢強度 (>25=有趨勢, <20=無趨勢)"""
    df = df.copy()
    adx = ADXIndicator(
        high=df["high"], low=df["low"], close=df["close"], window=period
    )
    df["adx"] = adx.adx()
    df["adx_pos"] = adx.adx_pos()
    df["adx_neg"] = adx.adx_neg()
    return df


def add_obv(df: pd.DataFrame) -> pd.DataFrame:
    """OBV (On-Balance Volume) — 量能確認趨勢"""
    df = df.copy()
    obv = OnBalanceVolumeIndicator(close=df["close"], volume=df["volume"])
    df["obv"] = obv.on_balance_volume()
    return df


def add_vwap(df: pd.DataFrame) -> pd.DataFrame:
    """VWAP (Volume Weighted Average Price) — 機構級別的均價參考"""
    df = df.copy()
    try:
        vwap = VolumeWeightedAveragePrice(
            high=df["high"], low=df["low"],
            close=df["close"], volume=df["volume"],
        )
        df["vwap"] = vwap.volume_weighted_average_price()
    except Exception:
        df["vwap"] = (df["high"] + df["low"] + df["close"]) / 3
    return df


def add_stoch_rsi(
    df: pd.DataFrame,
    period: int = 14,
    smooth_k: int = 3,
    smooth_d: int = 3,
) -> pd.DataFrame:
    """Stochastic RSI — 更靈敏的超買超賣指標"""
    df = df.copy()
    stoch = StochRSIIndicator(
        close=df["close"], window=period,
        smooth1=smooth_k, smooth2=smooth_d,
    )
    df["stoch_rsi_k"] = stoch.stochrsi_k()
    df["stoch_rsi_d"] = stoch.stochrsi_d()
    return df


def get_trend_direction(df: pd.DataFrame) -> str:
    """
    根據 EMA 排列判定當前趨勢方向。

    Returns: "BULLISH", "BEARISH", or "NEUTRAL"
    """
    if df.empty or len(df) < 50:
        return "NEUTRAL"

    latest = df.iloc[-1]
    ema_9 = latest.get("ema_9")
    ema_21 = latest.get("ema_21")
    ema_50 = latest.get("ema_50")

    if any(v is None or pd.isna(v) for v in [ema_9, ema_21, ema_50]):
        return "NEUTRAL"

    if ema_9 > ema_21 > ema_50:
        return "BULLISH"
    elif ema_9 < ema_21 < ema_50:
        return "BEARISH"

    close = latest.get("close")
    if close is not None and not pd.isna(close):
        if close > ema_50 and ema_9 > ema_50:
            return "LEAN_BULLISH"
        if close < ema_50 and ema_9 < ema_50:
            return "LEAN_BEARISH"

    return "NEUTRAL"


def get_indicator_summary(df: pd.DataFrame) -> dict:
    """
    生成指標摘要（供儀表板和策略使用）。
    """
    if df.empty:
        return {}

    latest = df.iloc[-1]
    close = latest.get("close", 0)
    atr = latest.get("atr", 0)
    atr_ratio = None
    try:
        close_f = float(close)
        atr_f = float(atr)
        if close_f > 0 and not pd.isna(close_f) and not pd.isna(atr_f):
            atr_ratio = atr_f / close_f
    except (TypeError, ValueError):
        atr_ratio = None

    summary = {
        "trend": get_trend_direction(df),
        "close": _safe_round(close, 4),
        "rsi": _safe_round(latest.get("rsi", 0), 2),
        "macd_hist": _safe_round(latest.get("macd_hist", 0), 6),
        "bb_pct": _safe_round(latest.get("bb_pct", 0.5), 4),
        "bb_width": _safe_round(latest.get("bb_width", 0), 4),
        "atr": _safe_round(atr, 4),
        "atr_ratio": _safe_round(atr_ratio, 6),
        "adx": _safe_round(latest.get("adx", 0), 2),
        "adx_pos": _safe_round(latest.get("adx_pos", 0), 2),
        "adx_neg": _safe_round(latest.get("adx_neg", 0), 2),
        "ema_21": _safe_round(latest.get("ema_21"), 4),
        "ema_50": _safe_round(latest.get("ema_50"), 4),
    }
    return summary
