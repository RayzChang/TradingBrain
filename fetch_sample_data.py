"""
抓一筆樣本資料 — 給你看程式抓到的數字長怎樣

不用開機器人、不用設 API Key，直接執行：
  python fetch_sample_data.py

會從幣安抓最近幾根 K 線、從 Alternative.me 抓恐懼貪婪指數，
印在畫面上。你可以對照 TradingView（選 Binance / Binance Futures）
同一時間、同一週期，數字應該會一樣。
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

# 讓腳本可以單獨執行，也能用專案的 config
sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx

# 用專案設定的網址（Testnet 或正式站，和 .env 的 BINANCE_TESTNET 一致）
try:
    from config.settings import BINANCE_REST_URL, BINANCE_TESTNET
except Exception:
    BINANCE_REST_URL = "https://fapi.binance.com"
    BINANCE_TESTNET = False

BINANCE_KLINES = f"{BINANCE_REST_URL}/fapi/v1/klines"
FEAR_GREED_URL = "https://api.alternative.me/fng/?limit=1"


def main():
    print("=" * 60)
    print("TradingBrain — 抓一筆樣本資料")
    print("=" * 60)
    print(f"資料來源: {BINANCE_REST_URL}")
    print(f"目前連線: {'Testnet（測試網）' if BINANCE_TESTNET else '正式站'}")
    print("  若要和 TradingView 的「Binance 正式站」對數字，請在 .env 設 BINANCE_TESTNET=false")
    print()

    # 1. K 線（BTCUSDT 15 分鐘，最近 5 根）
    print("【1】K 線（BTCUSDT 15m，最近 5 根）")
    print("    可以到 TradingView 選 Binance Futures → BTCUSDT → 15 分鐘，對一下時間與開高低收。")
    print()
    try:
        r = httpx.get(BINANCE_KLINES, params={"symbol": "BTCUSDT", "interval": "15m", "limit": 5}, timeout=10)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"    抓取失敗: {e}")
        data = []

    if data:
        # 幣安回傳: [ open_time, open, high, low, close, volume, ... ]
        print("    時間(UTC)              開盤      最高      最低      收盤      成交量")
        print("    " + "-" * 65)
        for candle in data:
            ts = int(candle[0])
            t_str = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
            o, h, l, c = float(candle[1]), float(candle[2]), float(candle[3]), float(candle[4])
            vol = float(candle[5])
            print(f"    {t_str}   {o:>10.2f} {h:>10.2f} {l:>10.2f} {c:>10.2f} {vol:>12.2f}")
        print()
    else:
        print("    沒有資料")
        print()

    # 2. 恐懼貪婪指數
    print("【2】恐懼貪婪指數（Alternative.me）")
    print("    系統用這個來「否決」：極度貪婪時不追多、極度恐懼時不追空。")
    print()
    try:
        r = httpx.get(FEAR_GREED_URL, timeout=10)
        r.raise_for_status()
        j = r.json()
        d = j.get("data", [{}])[0]
        value = int(d.get("value", 0))
        classification = d.get("classification", "N/A")
        print(f"    數值: {value} | 等級: {classification}")
        print()
    except Exception as e:
        print(f"    抓取失敗: {e}")
        print()

    print("=" * 60)
    print("上面這些就是程式會用到的「原始資料」。")
    print("若 K 線時間與數字和 TradingView 一致，就代表來源沒問題。")
    print("=" * 60)


if __name__ == "__main__":
    main()
