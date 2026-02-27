"""
Agent 循環報告 — 每輪結束後執行，將本輪結果推送到 LINE

在專案根目錄執行:
  venv\\Scripts\\python scripts\\agent_cycle_report.py
  venv\\Scripts\\python scripts\\agent_cycle_report.py "本輪改動：放寬 ADX、改用訓練型風控"
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from datetime import datetime, timezone
from database.db_manager import DatabaseManager
from notifications.line_notify import send_line_message


def main() -> None:
    db = DatabaseManager()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    daily_pnl = db.get_daily_pnl()
    total_pnl = db.get_total_realized_pnl()
    trades_today = db.get_trades_today()
    open_trades = db.get_open_trades()

    if daily_pnl >= 50 and daily_pnl <= 100:
        status = "今日達標"
    elif daily_pnl > 100:
        status = "今日超過目標上緣"
    else:
        status = "未達標，繼續循環"

    msg_lines = [
        "📋 TradingBrain Agent 循環報告",
        f"日期(UTC): {today}",
        f"今日已實現損益: {daily_pnl:+.2f} USDT",
        f"累計已實現損益: {total_pnl:+.2f} USDT",
        f"今日交易筆數: {len(trades_today)}",
        f"未平倉數: {len(open_trades)}",
        f"目標(50~100U/日): {status}",
    ]
    if len(sys.argv) > 1:
        change_summary = " ".join(sys.argv[1:]).strip()
        if change_summary:
            msg_lines.append(f"本輪改動: {change_summary}")
    msg_lines.append("—")
    msg_lines.append("(此為每輪循環結束後之通知)")

    text = "\n".join(msg_lines)
    ok = send_line_message(text)
    if ok:
        print("LINE 循環報告已發送")
    else:
        print("LINE 未設定或發送失敗，請檢查 .env 的 LINE_CHANNEL_ACCESS_TOKEN 與 LINE_USER_ID")


if __name__ == "__main__":
    main()
