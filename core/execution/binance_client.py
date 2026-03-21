"""
幣安 USDT 合約 REST 客戶端（含 Testnet）

用於模擬/實盤：取得餘額與持倉、下市價單、掛止損/止盈。
所有請求經 RateLimiter 限流，簽名使用 HMAC SHA256。
"""

import decimal
import hashlib
import hmac
import time
from typing import Any, Optional

import httpx
from loguru import logger

from config.settings import (
    BINANCE_API_KEY,
    BINANCE_API_SECRET,
    BINANCE_REST_URL,
    BINANCE_TESTNET,
)
from core.rate_limiter import RateLimiter


def _round_quantity(quantity: float, step_size: float) -> str:
    """依交易所 stepSize 將數量捨入為合規字串"""
    if step_size <= 0:
        return f"{quantity:.8f}".rstrip("0").rstrip(".")
    # 計算小數位數
    ss = str(step_size).rstrip("0")
    if "." in ss:
        decimals = len(ss.split(".")[-1])
    else:
        decimals = 0
    # 捨入到 step 的倍數
    step = decimal.Decimal(str(step_size))
    q = decimal.Decimal(str(quantity))
    rounded = (q // step) * step
    return f"{float(rounded):.{decimals}f}".rstrip("0").rstrip(".")


class BinanceFuturesClient:
    """
    幣安 USDT 合約 API 客戶端（簽名請求）。
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> None:
        self.api_key = api_key or BINANCE_API_KEY
        self.api_secret = api_secret or BINANCE_API_SECRET
        self.base_url = (base_url or BINANCE_REST_URL).rstrip("/")
        self.limiter = RateLimiter.get_instance()
        self._client: Optional[httpx.AsyncClient] = None
        self._symbol_info_cache: dict[str, Any] = {}
        self._time_offset: int = 0  # 本地與伺服器的時間差 (ms)
        self._time_synced: bool = False
        self._time_sync_monotonic: float = 0.0
        self._time_sync_ttl_seconds: int = 30
        self._timestamp_safety_margin_ms: int = 250

    async def _get_client(self) -> httpx.AsyncClient:
        """取得共用 httpx 連線池（懶初始化）"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=15.0)
        return self._client

    async def _sync_time(self, force: bool = False) -> None:
        """同步本地時鐘與幣安伺服器，計算偏移量。"""
        if (
            not force
            and self._time_synced
            and (time.monotonic() - self._time_sync_monotonic) < self._time_sync_ttl_seconds
        ):
            return
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                local_before = int(time.time() * 1000)
                resp = await client.get(f"{self.base_url}/fapi/v1/time")
                local_after = int(time.time() * 1000)
                if resp.status_code == 200:
                    server_time = resp.json().get("serverTime", 0)
                    # 用請求中間點估算本地時間
                    local_mid = (local_before + local_after) // 2
                    self._time_offset = (
                        server_time - local_mid - self._timestamp_safety_margin_ms
                    )
                    self._time_sync_monotonic = time.monotonic()
                    logger.info(f"伺服器時間同步完成：偏移 {self._time_offset}ms")
                    self._time_synced = True
        except Exception as e:
            logger.warning(f"伺服器時間同步失敗: {e}，使用本地時間")

    @staticmethod
    def _is_timestamp_error(resp: httpx.Response) -> bool:
        """Binance 是否因本機時鐘偏移而拒絕這次請求。"""
        if resp.status_code != 400:
            return False
        try:
            payload = resp.json()
        except ValueError:
            payload = {}
        if payload.get("code") == -1021:
            return True
        text = resp.text or ""
        return "-1021" in text or "ahead of the server's time" in text

    def _sign(self, params: dict[str, Any]) -> str:
        """加入 timestamp、recvWindow 並計算 signature，回傳完整 query_string"""
        params = dict(params)
        # 使用校正後的時間戳
        params["timestamp"] = int(time.time() * 1000) + self._time_offset
        params.setdefault("recvWindow", 10000)  # 放寬容差，Demo 常有延遲
        query = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        sig = hmac.new(
            self.api_secret.encode("utf-8"),
            query.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"{query}&signature={sig}"

    async def _request(
        self,
        method: str,
        path: str,
        params: Optional[dict] = None,
        weight: int = 1,
        is_order: bool = False,
    ) -> dict[str, Any]:
        """發送簽名請求，遇到時鐘漂移會自動重同步並重試一次。"""
        if not self.api_key or not self.api_secret:
            raise ValueError("BINANCE_API_KEY / BINANCE_API_SECRET 未設定")
        url = f"{self.base_url}{path}"
        params = params or {}
        method_upper = method.upper()
        if method_upper not in {"GET", "POST", "DELETE"}:
            raise ValueError(f"Unsupported HTTP method: {method}")

        for attempt in range(2):
            await self._sync_time(force=attempt > 0)
            await self.limiter.acquire(weight=weight, is_order=is_order)
            query_string = self._sign(params)
            headers = {"X-MBX-APIKEY": self.api_key}
            full_url = f"{url}?{query_string}"
            client = await self._get_client()

            if method_upper == "GET":
                resp = await client.get(full_url, headers=headers)
            elif method_upper == "POST":
                resp = await client.post(full_url, headers=headers)
            else:
                resp = await client.delete(full_url, headers=headers)

            self.limiter.update_from_headers(dict(resp.headers))
            if resp.status_code == 200:
                return resp.json()

            if self._is_timestamp_error(resp) and attempt == 0:
                logger.warning(
                    f"Binance timestamp drift detected for {method_upper} {path}; resyncing and retrying once."
                )
                self._time_synced = False
                continue

            logger.error(
                f"Binance API error: {method} {path} -> {resp.status_code} | {resp.text}"
            )
            resp.raise_for_status()

        raise RuntimeError(f"Unreachable request flow for {method_upper} {path}")

    async def _get_exchange_info_symbol(self, symbol: str) -> Optional[dict]:
        """取得單一交易對的 exchangeInfo（帶快取）"""
        if symbol in self._symbol_info_cache:
            return self._symbol_info_cache[symbol]
        await self.limiter.acquire(weight=40)
        client = await self._get_client()
        resp = await client.get(f"{self.base_url}/fapi/v1/exchangeInfo")
        resp.raise_for_status()
        data = resp.json()
        for s in data.get("symbols", []):
            if s["symbol"] == symbol:
                self._symbol_info_cache[symbol] = s
                return s
        return None

    def _quantity_precision_from_filters(self, symbol_info: Optional[dict]) -> float:
        """從 LOT_SIZE 取得 stepSize"""
        if not symbol_info:
            return 1e-8
        for f in symbol_info.get("filters", []):
            if f.get("filterType") == "LOT_SIZE":
                return float(f.get("stepSize", "0.00001"))
        return 0.00001

    async def get_ticker_price(self, symbol: str) -> Optional[float]:
        """取得指定交易對最新價（GET /fapi/v1/ticker/price，公開接口）"""
        await self.limiter.acquire(weight=1)
        client = await self._get_client()
        resp = await client.get(f"{self.base_url}/fapi/v1/ticker/price", params={"symbol": symbol})
        resp.raise_for_status()
        data = resp.json()
        return float(data.get("price", 0)) if data.get("price") else None

    async def get_balance(self) -> float:
        """取得 USDT 錢包權益，優先用 /fapi/v2/balance（較輕量、Demo 相容性好）"""
        # 方法 1：/fapi/v2/balance（輕量端點）
        try:
            data = await self._request("GET", "/fapi/v2/balance", weight=5)
            if isinstance(data, list):
                for asset in data:
                    if asset.get("asset") == "USDT":
                        return float(asset.get("balance", 0))
        except Exception as e:
            logger.warning(f"get_balance via /fapi/v2/balance failed: {e}")

        # 方法 2：fallback 到 /fapi/v2/account
        try:
            data = await self._request("GET", "/fapi/v2/account", weight=5)
            for asset in data.get("assets", []):
                if asset.get("asset") == "USDT":
                    return float(asset.get("totalWalletBalance", 0))
        except Exception as e:
            logger.error(f"get_balance via /fapi/v2/account also failed: {e}")

        return 0.0

    async def get_positions(self) -> list[dict]:
        """取得所有未平倉部位（positionAmt != 0）"""
        data = await self._request("GET", "/fapi/v2/positionRisk", weight=5)
        positions = []
        for p in data:
            amt = float(p.get("positionAmt", 0))
            if amt != 0:
                positions.append({
                    "symbol": p.get("symbol"),
                    "positionAmt": amt,
                    "entryPrice": float(p.get("entryPrice", 0)),
                    "unRealizedProfit": float(p.get("unRealizedProfit", 0)),
                    "leverage": int(p.get("leverage", 1)),
                })
        return positions

    async def get_leverage_brackets(self, symbol: str) -> int:
        """Query Binance for the maximum leverage allowed for a symbol."""
        try:
            data = await self._request(
                "GET",
                "/fapi/v1/leverageBracket",
                params={"symbol": symbol},
                weight=1,
            )
            if data and isinstance(data, list):
                brackets = data[0].get("brackets", [])
                if brackets:
                    return int(brackets[0].get("initialLeverage", 20))
        except Exception as e:
            logger.warning(f"get_leverage_brackets({symbol}) failed: {e}")
        return 20

    async def set_leverage(self, symbol: str, leverage: int) -> None:
        """設定合約槓桿"""
        await self._request(
            "POST",
            "/fapi/v1/leverage",
            params={"symbol": symbol, "leverage": leverage},
            weight=1,
            is_order=True,
        )
        logger.info(f"Leverage set: {symbol} -> {leverage}x")

    async def set_margin_type(self, symbol: str, margin_type: str) -> None:
        """設定全倉/逐倉。margin_type 為 'CROSSED'（全倉）或 'ISOLATED'（逐倉）。"""
        try:
            await self._request(
                "POST",
                "/fapi/v1/marginType",
                params={"symbol": symbol, "marginType": margin_type.upper()},
                weight=1,
                is_order=True,
            )
            logger.info(f"Margin type set: {symbol} -> {margin_type}")
        except httpx.HTTPStatusError as e:
            if "-4046" in str(e.response.text):
                # 已經是目標模式，不需要変更 — 正常情況
                logger.debug(f"{symbol} 保證金模式已是 {margin_type}，無需變更")
            else:
                raise

    async def get_account_info(self) -> dict:
        """取得帳戶資訊（餘額、持倉、保證金模式等）"""
        return await self._request("GET", "/fapi/v2/account", weight=5)

    async def _format_quantity(self, symbol: str, quantity: float) -> str:
        """依交易所規則格式化數量"""
        info = await self._get_exchange_info_symbol(symbol)
        step = self._quantity_precision_from_filters(info)
        return _round_quantity(quantity, step)

    def supports_algo_orders(self) -> bool:
        """
        Return whether exchange-managed protective algo orders should be used.

        Binance demo futures currently rejects STOP_MARKET / TAKE_PROFIT_MARKET
        on the normal `/fapi/v1/order` endpoint with `-4120`, so we manage
        protective orders locally while running on Testnet.
        """
        return not BINANCE_TESTNET

    async def place_market_order(
        self,
        symbol: str,
        side: str,
        quantity_base: float,
    ) -> Optional[int]:
        """
        市價開倉。side 為 "BUY" 或 "SELL"。
        回傳 orderId，失敗回傳 None 並記錄日誌。
        """
        try:
            qty_str = await self._format_quantity(symbol, quantity_base)
            if float(qty_str) <= 0:
                logger.warning(f"place_market_order: 數量捨入後為 0, symbol={symbol}")
                return None
            data = await self._request(
                "POST",
                "/fapi/v1/order",
                params={
                    "symbol": symbol,
                    "side": side,
                    "type": "MARKET",
                    "quantity": qty_str,
                },
                weight=1,
                is_order=True,
            )
            order_id = data.get("orderId")
            logger.info(f"Market order filled: {symbol} {side} qty={qty_str} orderId={order_id}")
            return int(order_id) if order_id is not None else None
        except httpx.HTTPStatusError as e:
            logger.error(f"place_market_order HTTP error: {e.response.status_code} {e.response.text}")
            return None
        except Exception as e:
            logger.exception(f"place_market_order failed: {e}")
            return None

    async def place_stop_loss(
        self,
        symbol: str,
        side: str,
        quantity: float,
        stop_price: float,
        reduce_only: bool = True,
    ) -> Optional[int]:
        """掛止損單（STOP_MARKET）"""
        try:
            qty_str = await self._format_quantity(symbol, quantity)
            if float(qty_str) <= 0:
                return None
            params = {
                "symbol": symbol,
                "side": side,
                "type": "STOP_MARKET",
                "quantity": qty_str,
                "stopPrice": _round_quantity(stop_price, 0.01),
                "reduceOnly": "true" if reduce_only else "false",
                "closePosition": "false",
            }
            data = await self._request("POST", "/fapi/v1/order", params=params, weight=1, is_order=True)
            return int(data.get("orderId")) if data.get("orderId") else None
        except Exception as e:
            logger.warning(f"place_stop_loss failed: {e}")
            return None

    async def place_take_profit(
        self,
        symbol: str,
        side: str,
        quantity: float,
        stop_price: float,
        reduce_only: bool = True,
    ) -> Optional[int]:
        """掛止盈單（TAKE_PROFIT_MARKET）"""
        try:
            qty_str = await self._format_quantity(symbol, quantity)
            if float(qty_str) <= 0:
                return None
            params = {
                "symbol": symbol,
                "side": side,
                "type": "TAKE_PROFIT_MARKET",
                "quantity": qty_str,
                "stopPrice": _round_quantity(stop_price, 0.01),
                "reduceOnly": "true" if reduce_only else "false",
                "closePosition": "false",
            }
            data = await self._request("POST", "/fapi/v1/order", params=params, weight=1, is_order=True)
            return int(data.get("orderId")) if data.get("orderId") else None
        except Exception as e:
            logger.warning(f"place_take_profit failed: {e}")
            return None

    async def cancel_all_orders(self, symbol: str) -> bool:
        """取消指定交易對所有掛單（用於更新止損/止盈前清除舊單）"""
        try:
            await self._request(
                "DELETE", "/fapi/v1/allOpenOrders",
                params={"symbol": symbol}, weight=1, is_order=True,
            )
            logger.info(f"All open orders cancelled: {symbol}")
            return True
        except Exception as e:
            logger.warning(f"cancel_all_orders failed for {symbol}: {e}")
            return False

    async def get_open_orders(self, symbol: str) -> list[dict]:
        """取得指定交易對所有掛單"""
        try:
            data = await self._request(
                "GET", "/fapi/v1/openOrders",
                params={"symbol": symbol}, weight=1,
            )
            return data if isinstance(data, list) else []
        except Exception as e:
            logger.warning(f"get_open_orders failed for {symbol}: {e}")
            return []

    async def close_position_market(self, symbol: str, side: str, quantity: float) -> Optional[int]:
        """市價平倉（reduceOnly）。side 為平倉方向：多倉平倉用 SELL，空倉平倉用 BUY。"""
        try:
            qty_str = await self._format_quantity(symbol, quantity)
            if float(qty_str) <= 0:
                return None
            data = await self._request(
                "POST",
                "/fapi/v1/order",
                params={
                    "symbol": symbol,
                    "side": side,
                    "type": "MARKET",
                    "quantity": qty_str,
                    "reduceOnly": "true",
                },
                weight=1,
                is_order=True,
            )
            return int(data.get("orderId")) if data.get("orderId") else None
        except Exception as e:
            logger.error(f"close_position_market failed: {e}")
            return None
