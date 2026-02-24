"""
市場數據採集模組 (REST API)

透過幣安 REST API 獲取歷史 K 線數據，並存為 Parquet 檔案。
所有請求經過全局 RateLimiter。
"""

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import httpx
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from loguru import logger

from config.settings import (
    BINANCE_REST_URL,
    KLINE_DATA_DIR,
    KLINE_TIMEFRAMES,
    DEFAULT_WATCHLIST,
)
from core.rate_limiter import RateLimiter


KLINE_COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "trades", "taker_buy_volume",
    "taker_buy_quote_volume", "ignore",
]


class MarketDataFetcher:
    """幣安合約 K 線數據採集器"""

    def __init__(self) -> None:
        self.limiter = RateLimiter.get_instance()
        self.base_url = BINANCE_REST_URL
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def fetch_klines(
        self,
        symbol: str,
        interval: str,
        limit: int = 500,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        從幣安獲取 K 線數據。

        Args:
            symbol: 交易對 (e.g. "BTCUSDT")
            interval: 時間框架 (e.g. "1h", "15m")
            limit: 每次請求的 K 線數量 (max 1500)
            start_time: 起始時間戳 (ms)
            end_time: 結束時間戳 (ms)

        Returns:
            DataFrame with OHLCV data
        """
        await self.limiter.acquire(weight=5)

        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": min(limit, 1500),
        }
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time

        client = await self._get_client()
        try:
            response = await client.get(
                f"{self.base_url}/fapi/v1/klines", params=params
            )
            self.limiter.update_from_headers(dict(response.headers))
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            logger.error(f"Failed to fetch klines {symbol} {interval}: {e}")
            return pd.DataFrame()

        if not data:
            return pd.DataFrame()

        df = pd.DataFrame(data, columns=KLINE_COLUMNS)

        for col in ["open", "high", "low", "close", "volume", "quote_volume",
                     "taker_buy_volume", "taker_buy_quote_volume"]:
            df[col] = df[col].astype(float)

        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
        df["close_time"] = pd.to_datetime(df["close_time"], unit="ms")
        df["trades"] = df["trades"].astype(int)
        df.drop(columns=["ignore"], inplace=True)

        return df

    async def fetch_klines_range(
        self,
        symbol: str,
        interval: str,
        days: int = 180,
    ) -> pd.DataFrame:
        """
        獲取指定天數的歷史 K 線（自動分頁）。

        Args:
            symbol: 交易對
            interval: 時間框架
            days: 要抓取的天數
        """
        all_dfs = []
        end_time = int(datetime.utcnow().timestamp() * 1000)
        start_time = int((datetime.utcnow() - timedelta(days=days)).timestamp() * 1000)
        current_start = start_time

        logger.info(f"Fetching {days} days of {interval} klines for {symbol}...")

        while current_start < end_time:
            df = await self.fetch_klines(
                symbol, interval, limit=1500,
                start_time=current_start, end_time=end_time,
            )
            if df.empty:
                break

            all_dfs.append(df)
            last_time = int(df["open_time"].iloc[-1].timestamp() * 1000)

            if last_time <= current_start:
                break
            current_start = last_time + 1

            await asyncio.sleep(0.1)

        if not all_dfs:
            logger.warning(f"No kline data fetched for {symbol} {interval}")
            return pd.DataFrame()

        result = pd.concat(all_dfs, ignore_index=True)
        result.drop_duplicates(subset=["open_time"], keep="last", inplace=True)
        result.sort_values("open_time", inplace=True)
        result.reset_index(drop=True, inplace=True)

        logger.info(
            f"Fetched {len(result)} {interval} klines for {symbol} "
            f"({result['open_time'].iloc[0]} -> {result['open_time'].iloc[-1]})"
        )
        return result

    def save_to_parquet(self, df: pd.DataFrame, symbol: str, interval: str) -> Path:
        """將 K 線 DataFrame 存為 Parquet 檔案"""
        KLINE_DATA_DIR.mkdir(parents=True, exist_ok=True)
        path = KLINE_DATA_DIR / f"{symbol}_{interval}.parquet"

        if path.exists():
            existing = pd.read_parquet(path)
            df = pd.concat([existing, df], ignore_index=True)
            df.drop_duplicates(subset=["open_time"], keep="last", inplace=True)
            df.sort_values("open_time", inplace=True)
            df.reset_index(drop=True, inplace=True)

        df.to_parquet(path, index=False)
        logger.debug(f"Saved {len(df)} klines to {path}")
        return path

    def load_from_parquet(self, symbol: str, interval: str) -> pd.DataFrame:
        """從 Parquet 載入 K 線數據"""
        path = KLINE_DATA_DIR / f"{symbol}_{interval}.parquet"
        if not path.exists():
            return pd.DataFrame()
        return pd.read_parquet(path)

    async def fetch_exchange_info(self) -> list[dict]:
        """獲取交易所資訊（交易對列表、最小下單額等）"""
        await self.limiter.acquire(weight=40)
        client = await self._get_client()

        try:
            response = await client.get(f"{self.base_url}/fapi/v1/exchangeInfo")
            self.limiter.update_from_headers(dict(response.headers))
            response.raise_for_status()
            data = response.json()
            symbols = data.get("symbols", [])
            logger.info(f"Exchange info: {len(symbols)} trading pairs")
            return symbols
        except Exception as e:
            logger.error(f"Failed to fetch exchange info: {e}")
            return []

    async def get_min_notional(self, symbol: str) -> float:
        """取得指定交易對的最小下單名義值"""
        symbols = await self.fetch_exchange_info()
        for s in symbols:
            if s["symbol"] == symbol:
                for f in s.get("filters", []):
                    if f["filterType"] == "MIN_NOTIONAL":
                        return float(f.get("notional", 5.0))
        return 5.0  # default fallback
