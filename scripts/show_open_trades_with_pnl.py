"""
顯示目前未平倉模擬單，並用 Binance USDT 合約現價估算未實現損益。

在專案根目錄執行:

    venv\Scripts\python scripts\show_open_trades_with_pnl.py
"""

import sys
from pathlib import Path

import httpx

# 專案根目錄
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database.db_manager import DatabaseManager  # noqa: E402


BINANCE_USDM_TICKER = "https://fapi.binance.com/fapi/v2/ticker/price"


def main() -> None:
    db = DatabaseManager()
    open_trades = db.get_open_trades()

    if not open_trades:
        print("目前沒有未平倉模擬單。")
        return

    symbols = sorted({t["symbol"] for t in open_trades})
    prices: dict[str, float] = {}

    with httpx.Client(timeout=5.0) as client:
        for sym in symbols:
            try:
                r = client.get(BINANCE_USDM_TICKER, params={"symbol": sym})
                r.raise_for_status()
                prices[sym] = float(r.json()["price"])
            except Exception as e:
                print(f"取得 {sym} 報價失敗: {e}")

    total_unreal = 0.0
    print("=" * 70)
    print("目前未平倉模擬單 (以 Binance USDT 合約現價估算)")
    print("=" * 70)
    for t in open_trades:
        sym = t["symbol"]
        side = t["side"]
        entry = float(t["entry_price"])
        qty = float(t["quantity"])
        cur = prices.get(sym)
        if not cur:
            continue
        if side == "LONG":
            pnl = (cur - entry) * qty
        else:
            pnl = (entry - cur) * qty
        total_unreal += pnl
        print(
            f"{sym:8s} {side:5s} entry={entry:.4f} cur={cur:.4f} "
            f"qty={qty:.4f}  未實現PnL={pnl:+.2f} U"
        )
    print("-" * 70)
    print(f"合計未實現PnL: {total_unreal:+.2f} U")


if __name__ == "__main__":
    main()

