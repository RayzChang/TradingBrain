"""
Market data fetcher for Binance Futures REST endpoints.

This module downloads historical kline data, can persist it as Parquet,
and reuses the shared rate limiter for all REST requests.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import httpx
import pandas as pd
from loguru import logger

from config.settings import BINANCE_REST_URL, KLINE_DATA_DIR
from core.rate_limiter import RateLimiter


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


class MarketDataFetcher:
    """Fetch and cache Binance Futures kline data."""

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
        """Fetch klines for a symbol and timeframe."""
        await self.limiter.acquire(weight=5)

        params: dict[str, int | str] = {
            "symbol": symbol,
            "interval": interval,
            "limit": min(limit, 1500),
        }
        if start_time is not None:
            params["startTime"] = start_time
        if end_time is not None:
            params["endTime"] = end_time

        client = await self._get_client()
        try:
            response = await client.get(
                f"{self.base_url}/fapi/v1/klines",
                params=params,
            )
            self.limiter.update_from_headers(dict(response.headers))
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            logger.error(f"Failed to fetch klines {symbol} {interval}: {exc}")
            return pd.DataFrame()

        if not data:
            return pd.DataFrame()

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
        return df

    async def fetch_klines_range(
        self,
        symbol: str,
        interval: str,
        days: int = 180,
    ) -> pd.DataFrame:
        """Fetch a historical kline range using paginated requests."""
        all_frames: list[pd.DataFrame] = []
        end_time = int(datetime.now(timezone.utc).timestamp() * 1000)
        start_time = int(
            (datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000
        )
        current_start = start_time

        logger.info(f"Fetching {days} days of {interval} klines for {symbol}...")

        while current_start < end_time:
            frame = await self.fetch_klines(
                symbol,
                interval,
                limit=1500,
                start_time=current_start,
                end_time=end_time,
            )
            if frame.empty:
                break

            all_frames.append(frame)
            last_time = int(frame["open_time"].iloc[-1].timestamp() * 1000)
            if last_time <= current_start:
                break

            current_start = last_time + 1
            await asyncio.sleep(0.1)

        if not all_frames:
            logger.warning(f"No kline data fetched for {symbol} {interval}")
            return pd.DataFrame()

        result = pd.concat(all_frames, ignore_index=True)
        result.drop_duplicates(subset=["open_time"], keep="last", inplace=True)
        result.sort_values("open_time", inplace=True)
        result.reset_index(drop=True, inplace=True)

        logger.info(
            f"Fetched {len(result)} {interval} klines for {symbol} "
            f"({result['open_time'].iloc[0]} -> {result['open_time'].iloc[-1]})"
        )
        return result

    def save_to_parquet(self, df: pd.DataFrame, symbol: str, interval: str) -> Path:
        """Persist kline data to a Parquet file."""
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
        """Load cached kline data from Parquet."""
        path = KLINE_DATA_DIR / f"{symbol}_{interval}.parquet"
        if not path.exists():
            return pd.DataFrame()
        return pd.read_parquet(path)

    async def fetch_exchange_info(self) -> list[dict]:
        """Fetch exchange metadata for tradable symbols and filters."""
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
        except Exception as exc:
            logger.error(f"Failed to fetch exchange info: {exc}")
            return []

    async def get_min_notional(self, symbol: str) -> float:
        """Return the minimum notional requirement for a symbol."""
        symbols = await self.fetch_exchange_info()
        for item in symbols:
            if item["symbol"] != symbol:
                continue
            for filter_item in item.get("filters", []):
                if filter_item["filterType"] == "MIN_NOTIONAL":
                    return float(filter_item.get("notional", 5.0))
        return 5.0
