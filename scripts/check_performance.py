"""
Agent 監控腳本 — 快速查看當前績效與目標差距

在專案根目錄執行: venv\\Scripts\\python scripts\\check_performance.py
"""

import sys
from pathlib import Path

# 專案根目錄
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from datetime import datetime, timezone
from database.db_manager import DatabaseManager


def main() -> None:
    db = DatabaseManager()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    daily_pnl = db.get_daily_pnl()
    total_pnl = db.get_total_realized_pnl()
    trades_today = db.get_trades_today()
    open_trades = db.get_open_trades()

    print("=" * 50)
    print("TradingBrain 績效檢查")
    print("=" * 50)
    print(f"日期(UTC): {today}")
    print(f"今日已實現損益: {daily_pnl:+.2f} USDT")
    print(f"累計已實現損益: {total_pnl:+.2f} USDT")
    print(f"今日交易筆數: {len(trades_today)}")
    print(f"未平倉數: {len(open_trades)}")
    print("-" * 50)
    print("目標 (TARGET.md): Testnet 5000U → 每日平均 50~100 USDT")
    if daily_pnl >= 50 and daily_pnl <= 100:
        print("狀態: 今日達標")
    elif daily_pnl > 100:
        print("狀態: 今日超過目標上緣（可考慮加倉或維持）")
    else:
        print("狀態: 未達標，繼續執行 Agent 循環 (AGENT_LOOP.md)")
    print("=" * 50)


if __name__ == "__main__":
    main()
