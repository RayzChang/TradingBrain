"""
跑機器人前：查測試盤餘額、設定全倉/逐倉與槓桿

執行方式：
  python setup_testnet.py

會做三件事：
  1. 用 API 撈出你 Testnet 的 USDT 餘額與持倉，印在畫面上
  2. 若 .env 有設 MARGIN_TYPE（CROSSED=全倉 / ISOLATED=逐倉），就幫你寫入交易所
  3. 若 .env 有設 DEFAULT_LEVERAGE（數字），就幫你對監控的幣對設定該槓桿倍率

在 .env 可加（選填）：
  MARGIN_TYPE=CROSSED     # 全倉；改成 ISOLATED 則為逐倉
  DEFAULT_LEVERAGE=2      # 槓桿倍率，例如 2 或 5
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config.settings import BINANCE_TESTNET, DEFAULT_LEVERAGE, DEFAULT_WATCHLIST, MARGIN_TYPE
from core.execution.binance_client import BinanceFuturesClient


async def main():
    if not BINANCE_TESTNET:
        print("目前 BINANCE_TESTNET 為 false，此腳本僅建議在 Testnet 使用。")
        print("若仍要繼續請手動改 .env。")
        return

    client = BinanceFuturesClient()
    print("=" * 60)
    print("TradingBrain — 測試盤餘額與設定")
    print("=" * 60)

    # 1. 餘額
    try:
        balance = await client.get_balance()
        print(f"\n【餘額】USDT")
        print(f"  錢包權益: {balance:.2f} USDT")
    except Exception as e:
        print(f"  餘額取得失敗（不影響後續設定）: {e}")

    # 持倉
    try:
        positions = await client.get_positions()
        if positions:
            print(f"\n【目前持倉】共 {len(positions)} 筆")
            for p in positions:
                print(f"  {p['symbol']} 數量={p['positionAmt']} 槓桿={p['leverage']}x 未實現盈虧={p.get('unRealizedProfit', 0):.2f}")
        else:
            print("\n【目前持倉】無")
    except Exception as e:
        print(f"  持倉取得失敗（不影響後續設定）: {e}")

    # 2. 依 .env 設定全倉/逐倉與槓桿
    print(f"\n【.env 設定】MARGIN_TYPE={MARGIN_TYPE}（全倉=CROSSED 逐倉=ISOLATED）, DEFAULT_LEVERAGE={DEFAULT_LEVERAGE}x")
    symbols_to_set = DEFAULT_WATCHLIST[:10]  # 最多設 10 個，避免請求過多

    for symbol in symbols_to_set:
        try:
            await client.set_margin_type(symbol, MARGIN_TYPE)
        except Exception as e:
            err = str(e)
            if "No need to change" in err or "margin type" in err.lower() or "404" in err:
                pass
            else:
                print(f"  {symbol} 保證金模式: {e}")
        try:
            await client.set_leverage(symbol, DEFAULT_LEVERAGE)
        except Exception as e:
            print(f"  {symbol} 槓桿: {e}")

    print(f"\n已對 {len(symbols_to_set)} 個交易對套用：保證金={MARGIN_TYPE}，槓桿={DEFAULT_LEVERAGE}x")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
