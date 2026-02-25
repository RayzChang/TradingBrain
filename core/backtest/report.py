"""回測績效報告 — 彙總統計與文字報告"""

from core.backtest.engine import BacktestResult


def get_report_dict(result: BacktestResult) -> dict:
    """回傳可序列化的績效摘要"""
    return {
        "initial_balance": result.initial_balance,
        "final_balance": result.final_balance,
        "total_return_pct": round(result.total_return_pct, 2),
        "max_drawdown_pct": round(result.max_drawdown_pct, 2),
        "win_rate": round(result.win_rate, 1),
        "n_trades": result.n_trades,
        "n_wins": result.n_wins,
        "n_losses": result.n_trades - result.n_wins,
    }


def format_report(result: BacktestResult) -> str:
    """產生人類可讀的報告文字"""
    d = get_report_dict(result)
    lines = [
        "========== 回測報告 ==========",
        f"初始資金: {d['initial_balance']:.2f} USDT",
        f"最終資金: {d['final_balance']:.2f} USDT",
        f"總報酬率: {d['total_return_pct']:+.2f}%",
        f"最大回撤: {d['max_drawdown_pct']:.2f}%",
        f"交易次數: {d['n_trades']} (勝 {d['n_wins']} / 負 {d['n_losses']})",
        f"勝率: {d['win_rate']:.1f}%",
        "===============================",
    ]
    return "\n".join(lines)
