import { useEffect, useState } from "react";
import { tradesApi } from "../api";

type Trade = {
  id: number;
  symbol: string;
  side: string;
  entry_price: number;
  exit_price?: number;
  quantity: number;
  leverage: number;
  status: string;
  pnl?: number;
  opened_at: string;
  closed_at?: string;
  stop_loss?: number | null;
  take_profit?: number | null;
  strategy_name?: string | null;
  current_price?: number | null;
  unrealized_pnl?: number | null;
};

export default function Trades() {
  const [open, setOpen] = useState<Trade[]>([]);
  const [today, setToday] = useState<Trade[]>([]);
  const [dailyPnl, setDailyPnl] = useState<number | null>(null);
  const [err, setErr] = useState("");

  const [totalUnrealized, setTotalUnrealized] = useState<number | null>(null);

  useEffect(() => {
    Promise.all([tradesApi.openWithPnl(), tradesApi.today(), tradesApi.dailyPnl()])
      .then(([pnlRes, t, d]) => {
        setOpen(pnlRes.open_trades as Trade[]);
        setTotalUnrealized(pnlRes.total_unrealized_pnl);
        setToday(t as Trade[]);
        setDailyPnl(d.daily_pnl);
      })
      .catch((e) => setErr(String(e)));
  }, []);

  if (err) return <p className="text-[var(--red)]">無法載入：{err}</p>;

  return (
    <div>
      <h2 className="text-xl font-bold mb-6">交易</h2>
      <div className="mb-4 flex flex-wrap gap-4">
        {dailyPnl !== null && (
          <p>
            今日已實現損益：<span className={dailyPnl >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"}>{dailyPnl >= 0 ? "+" : ""}{dailyPnl.toFixed(2)} USDT</span>
          </p>
        )}
        {totalUnrealized !== null && open.length > 0 && (
          <p>
            未實現損益：<span className={totalUnrealized >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"}>{totalUnrealized >= 0 ? "+" : ""}{totalUnrealized.toFixed(2)} USDT</span>
          </p>
        )}
      </div>

      <h3 className="font-semibold mb-2">未平倉 ({open.length})</h3>
      <p className="text-sm text-[var(--muted)] mb-2">含策略、預設止損/止盈與即時未實現損益（依當前價估算）</p>
      <div className="overflow-x-auto rounded-lg border border-[var(--border)] mb-6">
        <table className="w-full text-sm">
          <thead className="bg-[var(--card)]">
            <tr>
              <th className="text-left p-3">交易對</th>
              <th className="text-left p-3">方向</th>
              <th className="text-right p-3">數量</th>
              <th className="text-right p-3">進場價</th>
              <th className="text-right p-3">當前價</th>
              <th className="text-right p-3">止損</th>
              <th className="text-right p-3">止盈</th>
              <th className="text-right p-3">未實現損益</th>
              <th className="text-left p-3">策略</th>
              <th className="text-right p-3">槓桿</th>
              <th className="text-left p-3">開倉時間</th>
            </tr>
          </thead>
          <tbody>
            {open.length === 0 && (
              <tr>
                <td colSpan={11} className="p-6 text-center text-[var(--muted)]">無未平倉</td>
              </tr>
            )}
            {open.map((t) => (
              <tr key={t.id} className="border-t border-[var(--border)]">
                <td className="p-3">{t.symbol}</td>
                <td className={`p-3 ${t.side === "LONG" ? "text-[var(--green)]" : "text-[var(--red)]"}`}>{t.side}</td>
                <td className="p-3 text-right">{t.quantity}</td>
                <td className="p-3 text-right">{t.entry_price}</td>
                <td className="p-3 text-right">{t.current_price != null ? t.current_price.toFixed(2) : "-"}</td>
                <td className="p-3 text-right">{t.stop_loss != null ? t.stop_loss.toFixed(2) : "-"}</td>
                <td className="p-3 text-right">{t.take_profit != null ? t.take_profit.toFixed(2) : "-"}</td>
                <td className={`p-3 text-right ${t.unrealized_pnl != null ? (t.unrealized_pnl >= 0 ? "text-[var(--green)]" : "text-[var(--red)]") : ""}`}>
                  {t.unrealized_pnl != null ? (t.unrealized_pnl >= 0 ? "+" : "") + t.unrealized_pnl.toFixed(2) : "-"}
                </td>
                <td className="p-3 text-[var(--muted)]">{t.strategy_name ?? "-"}</td>
                <td className="p-3 text-right">{t.leverage}</td>
                <td className="p-3 text-[var(--muted)]">{t.opened_at?.slice(0, 19)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3 className="font-semibold mb-2">今日交易 ({today.length})</h3>
      <div className="overflow-x-auto rounded-lg border border-[var(--border)]">
        <table className="w-full text-sm">
          <thead className="bg-[var(--card)]">
            <tr>
              <th className="text-left p-3">交易對</th>
              <th className="text-left p-3">方向</th>
              <th className="text-right p-3">進場</th>
              <th className="text-right p-3">出場</th>
              <th className="text-right p-3">損益</th>
              <th className="text-left p-3">平倉時間</th>
            </tr>
          </thead>
          <tbody>
            {today.length === 0 && (
              <tr>
                <td colSpan={6} className="p-6 text-center text-[var(--muted)]">今日尚無交易</td>
              </tr>
            )}
            {today.filter((t) => t.status === "CLOSED").map((t) => (
              <tr key={t.id} className="border-t border-[var(--border)]">
                <td className="p-3">{t.symbol}</td>
                <td className={`p-3 ${t.side === "LONG" ? "text-[var(--green)]" : "text-[var(--red)]"}`}>{t.side}</td>
                <td className="p-3 text-right">{t.entry_price}</td>
                <td className="p-3 text-right">{t.exit_price ?? "-"}</td>
                <td className={`p-3 text-right ${(t.pnl ?? 0) >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"}`}>
                  {t.pnl != null ? (t.pnl >= 0 ? "+" : "") + t.pnl.toFixed(2) : "-"}
                </td>
                <td className="p-3 text-[var(--muted)]">{t.closed_at?.slice(0, 19)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
