"""Tests for Binance client time sync and retry behavior."""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.execution.binance_client import BinanceFuturesClient


def _response(method: str, url: str, status_code: int, payload: dict) -> httpx.Response:
    request = httpx.Request(method, url)
    return httpx.Response(status_code, json=payload, request=request)


async def _request_retries_after_timestamp_drift() -> None:
    client = BinanceFuturesClient(
        api_key="key",
        api_secret="secret",
        base_url="https://example.com",
    )
    limiter = MagicMock()
    limiter.acquire = AsyncMock()
    limiter.update_from_headers = MagicMock()
    client.limiter = limiter

    http_client = MagicMock()
    http_client.post = AsyncMock(
        side_effect=[
            _response(
                "POST",
                "https://example.com/fapi/v1/order",
                400,
                {
                    "code": -1021,
                    "msg": "Timestamp for this request was 1000ms ahead of the server's time.",
                },
            ),
            _response(
                "POST",
                "https://example.com/fapi/v1/order",
                200,
                {"orderId": 123456},
            ),
        ]
    )

    client._get_client = AsyncMock(return_value=http_client)
    client._sync_time = AsyncMock()

    data = await client._request(
        "POST",
        "/fapi/v1/order",
        params={"symbol": "BTCUSDT", "side": "BUY", "type": "MARKET", "quantity": "0.01"},
        is_order=True,
    )

    assert data == {"orderId": 123456}
    assert http_client.post.await_count == 2
    assert client._sync_time.await_count == 2
    assert client._sync_time.await_args_list[0].kwargs == {"force": False}
    assert client._sync_time.await_args_list[1].kwargs == {"force": True}


def test_request_retries_after_timestamp_drift():
    asyncio.run(_request_retries_after_timestamp_drift())
