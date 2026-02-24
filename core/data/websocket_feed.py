"""
幣安 WebSocket 即時 K 線數據流

持續連線接收即時 K 線更新，維護記憶體快取供策略即時分析。
自動重連機制應對網路斷線。
"""

import asyncio
import json
from collections import defaultdict
from datetime import datetime
from typing import Any, Callable, Optional

import websockets
from loguru import logger

from config.settings import BINANCE_WS_URL, DEFAULT_WATCHLIST, KLINE_TIMEFRAMES


class KlineCache:
    """K 線記憶體快取 — 儲存最近 N 根 K 線供即時分析"""

    def __init__(self, max_candles: int = 200) -> None:
        self.max_candles = max_candles
        # {symbol: {timeframe: [candle_dicts]}}
        self._data: dict[str, dict[str, list[dict]]] = defaultdict(
            lambda: defaultdict(list)
        )

    def update(self, symbol: str, timeframe: str, candle: dict) -> None:
        """更新或新增一根 K 線"""
        candles = self._data[symbol][timeframe]

        if candles and candles[-1]["open_time"] == candle["open_time"]:
            candles[-1] = candle
        else:
            candles.append(candle)

        if len(candles) > self.max_candles:
            self._data[symbol][timeframe] = candles[-self.max_candles:]

    def get(self, symbol: str, timeframe: str) -> list[dict]:
        """取得指定交易對和時間框架的所有 K 線"""
        return self._data.get(symbol, {}).get(timeframe, [])

    def get_latest(self, symbol: str, timeframe: str) -> Optional[dict]:
        """取得最新一根 K 線"""
        candles = self.get(symbol, timeframe)
        return candles[-1] if candles else None

    def get_symbols(self) -> list[str]:
        """取得所有有數據的交易對"""
        return list(self._data.keys())


class BinanceWebSocketFeed:
    """
    幣安合約 WebSocket 即時數據流

    訂閱多個交易對的 K 線數據，透過回調函數通知上層模組。
    內建自動重連機制。
    """

    def __init__(
        self,
        symbols: Optional[list[str]] = None,
        timeframes: Optional[list[str]] = None,
        on_kline: Optional[Callable] = None,
    ) -> None:
        self.symbols = [s.lower() for s in (symbols or DEFAULT_WATCHLIST)]
        self.timeframes = timeframes or ["1m", "15m", "1h", "4h"]
        self.on_kline = on_kline

        self.cache = KlineCache()
        self._ws = None
        self._running = False
        self._reconnect_delay = 1.0
        self._max_reconnect_delay = 60.0

    def _build_streams(self) -> list[str]:
        """構建 WebSocket 訂閱的 stream 列表"""
        streams = []
        for symbol in self.symbols:
            for tf in self.timeframes:
                streams.append(f"{symbol}@kline_{tf}")
        return streams

    def _build_url(self) -> str:
        """構建 combined stream URL"""
        streams = self._build_streams()
        stream_str = "/".join(streams)
        return f"{BINANCE_WS_URL}/stream?streams={stream_str}"

    def _parse_kline(self, data: dict) -> dict:
        """解析幣安 K 線 WebSocket 數據"""
        k = data.get("k", {})
        return {
            "symbol": k.get("s", ""),
            "timeframe": k.get("i", ""),
            "open_time": k.get("t", 0),
            "open": float(k.get("o", 0)),
            "high": float(k.get("h", 0)),
            "low": float(k.get("l", 0)),
            "close": float(k.get("c", 0)),
            "volume": float(k.get("v", 0)),
            "close_time": k.get("T", 0),
            "quote_volume": float(k.get("q", 0)),
            "trades": int(k.get("n", 0)),
            "taker_buy_volume": float(k.get("V", 0)),
            "taker_buy_quote_volume": float(k.get("Q", 0)),
            "is_closed": k.get("x", False),
        }

    async def _handle_message(self, message: str) -> None:
        """處理收到的 WebSocket 訊息"""
        try:
            msg = json.loads(message)
            stream = msg.get("stream", "")
            data = msg.get("data", {})

            if "@kline_" in stream:
                candle = self._parse_kline(data)
                symbol = candle["symbol"]
                tf = candle["timeframe"]

                self.cache.update(symbol, tf, candle)

                if candle["is_closed"] and self.on_kline:
                    try:
                        await self.on_kline(candle) if asyncio.iscoroutinefunction(
                            self.on_kline
                        ) else self.on_kline(candle)
                    except Exception as e:
                        logger.error(f"on_kline callback error: {e}")

        except json.JSONDecodeError:
            logger.warning(f"Invalid WebSocket message: {message[:100]}")
        except Exception as e:
            logger.error(f"WebSocket message handling error: {e}")

    async def start(self) -> None:
        """啟動 WebSocket 連線（含自動重連）"""
        self._running = True
        url = self._build_url()

        stream_count = len(self.symbols) * len(self.timeframes)
        logger.info(
            f"WebSocket starting: {len(self.symbols)} symbols x "
            f"{len(self.timeframes)} timeframes = {stream_count} streams"
        )

        while self._running:
            try:
                async with websockets.connect(
                    url,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=5,
                    max_size=2**20,
                ) as ws:
                    self._ws = ws
                    self._reconnect_delay = 1.0
                    logger.info("WebSocket connected")

                    async for message in ws:
                        if not self._running:
                            break
                        await self._handle_message(message)

            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"WebSocket disconnected: {e}")
            except Exception as e:
                logger.error(f"WebSocket error: {e}")

            if self._running:
                logger.info(
                    f"WebSocket reconnecting in {self._reconnect_delay:.1f}s..."
                )
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(
                    self._reconnect_delay * 2, self._max_reconnect_delay
                )

        logger.info("WebSocket stopped")

    async def stop(self) -> None:
        """停止 WebSocket 連線"""
        self._running = False
        if self._ws:
            await self._ws.close()
            self._ws = None
        logger.info("WebSocket feed stopped")

    def update_symbols(self, symbols: list[str]) -> None:
        """
        更新監控的交易對列表。
        注意：需要重新連線才會生效。
        """
        self.symbols = [s.lower() for s in symbols]
        logger.info(f"WebSocket symbols updated: {len(self.symbols)} pairs")
