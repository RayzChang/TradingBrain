import { useEffect, useState } from "react";

import { tradesApi } from "../api";

type Trade = {
  id: number;
  symbol: string;
  side: string;
  entry_price: number;
  exit_price?: number | null;
  quantity: number;
  leverage: number;
  status: string;
  pnl?: number | null;
  opened_at: string;
  closed_at?: string | null;
  stop_loss?: number | null;
  take_profit?: number | null;
  soft_stop_loss?: number | null;
  hard_stop_loss?: number | null;
  soft_stop_required_closes?: number | null;
  stop_zone_low?: number | null;
  stop_zone_high?: number | null;
  tp1_price?: number | null;
  tp2_price?: number | null;
  tp3_price?: number | null;
  strategy_name?: string | null;
  current_price?: number | null;
  unrealized_pnl?: number | null;
};

function formatPrice(value?: number | null): string {
  if (value == null || Number.isNaN(value)) {
    return "-";
  }
  const abs = Math.abs(value);
  const digits = abs >= 1000 ? 2 : abs >= 1 ? 4 : 6;
  return value.toFixed(digits);
}

function formatZone(low?: number | null, high?: number | null): string | null {
  if (low == null || high == null || Number.isNaN(low) || Number.isNaN(high)) {
    return null;
  }
  return `${formatPrice(low)} - ${formatPrice(high)}`;
}

export default function Trades() {
  const [open, setOpen] = useState<Trade[]>([]);
  const [today, setToday] = useState<Trade[]>([]);
  const [dailyPnl, setDailyPnl] = useState<number | null>(null);
  const [totalUnrealized, setTotalUnrealized] = useState<number | null>(null);
  const [err, setErr] = useState("");

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

  if (err) {
    return <p className="text-[var(--red)]">Trades load failed: {err}</p>;
  }

  return (
    <div>
      <h2 className="mb-6 text-xl font-bold">Trades</h2>
      <div className="mb-4 flex flex-wrap gap-4">
        {dailyPnl !== null && (
          <p>
            Daily PnL:{" "}
            <span className={dailyPnl >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"}>
              {dailyPnl >= 0 ? "+" : ""}
              {dailyPnl.toFixed(2)} USDT
            </span>
          </p>
        )}
        {totalUnrealized !== null && open.length > 0 && (
          <p>
            Unrealized:{" "}
            <span className={totalUnrealized >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"}>
              {totalUnrealized >= 0 ? "+" : ""}
              {totalUnrealized.toFixed(2)} USDT
            </span>
          </p>
        )}
      </div>

      <h3 className="mb-2 font-semibold">Open Positions ({open.length})</h3>
      <p className="mb-2 text-sm text-[var(--muted)]">
        顯示目前的雙層保護與目標梯隊，避免把 V7 的 soft/hard stop 看成舊版單線止損。
      </p>
      <div className="mb-6 overflow-x-auto rounded-lg border border-[var(--border)]">
        <table className="w-full text-sm">
          <thead className="bg-[var(--card)]">
            <tr>
              <th className="p-3 text-left">Symbol</th>
              <th className="p-3 text-left">Side</th>
              <th className="p-3 text-right">Qty</th>
              <th className="p-3 text-right">Entry</th>
              <th className="p-3 text-right">Current</th>
              <th className="p-3 text-right">Protection</th>
              <th className="p-3 text-right">Targets</th>
              <th className="p-3 text-right">Unrealized</th>
              <th className="p-3 text-left">Strategy</th>
              <th className="p-3 text-right">Lev</th>
              <th className="p-3 text-left">Opened</th>
            </tr>
          </thead>
          <tbody>
            {open.length === 0 && (
              <tr>
                <td colSpan={11} className="p-6 text-center text-[var(--muted)]">
                  No open positions.
                </td>
              </tr>
            )}
            {open.map((t) => {
              const stopZone = formatZone(t.stop_zone_low, t.stop_zone_high);
              return (
                <tr key={t.id} className="border-t border-[var(--border)]">
                  <td className="p-3">{t.symbol}</td>
                  <td className={`p-3 ${t.side === "LONG" ? "text-[var(--green)]" : "text-[var(--red)]"}`}>{t.side}</td>
                  <td className="p-3 text-right font-mono">{t.quantity}</td>
                  <td className="p-3 text-right font-mono">{formatPrice(t.entry_price)}</td>
                  <td className="p-3 text-right font-mono">{formatPrice(t.current_price)}</td>
                  <td className="p-3 text-right">
                    <div className="space-y-1 font-mono text-xs">
                      <div>Soft {formatPrice(t.soft_stop_loss ?? t.stop_loss)}</div>
                      <div className="text-[var(--muted)]">Hard {formatPrice(t.hard_stop_loss ?? t.stop_loss)}</div>
                      {stopZone && <div className="text-[var(--muted)]">Zone {stopZone}</div>}
                      {t.soft_stop_required_closes ? (
                        <div className="text-[var(--muted)]">{t.soft_stop_required_closes} 根收破</div>
                      ) : null}
                    </div>
                  </td>
                  <td className="p-3 text-right">
                    <div className="space-y-1 font-mono text-xs">
                      <div>TP1 {formatPrice(t.tp1_price ?? t.take_profit)}</div>
                      <div className="text-[var(--muted)]">TP2 {formatPrice(t.tp2_price)}</div>
                      <div className="text-[var(--muted)]">TP3 {formatPrice(t.tp3_price)}</div>
                    </div>
                  </td>
                  <td className={`p-3 text-right ${t.unrealized_pnl != null ? (t.unrealized_pnl >= 0 ? "text-[var(--green)]" : "text-[var(--red)]") : ""}`}>
                    {t.unrealized_pnl != null ? (t.unrealized_pnl >= 0 ? "+" : "") + t.unrealized_pnl.toFixed(2) : "-"}
                  </td>
                  <td className="p-3 text-[var(--muted)]">{t.strategy_name ?? "-"}</td>
                  <td className="p-3 text-right">{t.leverage}</td>
                  <td className="p-3 text-[var(--muted)]">{t.opened_at?.slice(0, 19)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <h3 className="mb-2 font-semibold">Today&apos;s Closed Trades ({today.filter((t) => t.status === "CLOSED").length})</h3>
      <div className="overflow-x-auto rounded-lg border border-[var(--border)]">
        <table className="w-full text-sm">
          <thead className="bg-[var(--card)]">
            <tr>
              <th className="p-3 text-left">Symbol</th>
              <th className="p-3 text-left">Side</th>
              <th className="p-3 text-right">Entry</th>
              <th className="p-3 text-right">Exit</th>
              <th className="p-3 text-right">PnL</th>
              <th className="p-3 text-left">Closed</th>
            </tr>
          </thead>
          <tbody>
            {today.filter((t) => t.status === "CLOSED").length === 0 && (
              <tr>
                <td colSpan={6} className="p-6 text-center text-[var(--muted)]">
                  No closed trades today.
                </td>
              </tr>
            )}
            {today
              .filter((t) => t.status === "CLOSED")
              .map((t) => (
                <tr key={t.id} className="border-t border-[var(--border)]">
                  <td className="p-3">{t.symbol}</td>
                  <td className={`p-3 ${t.side === "LONG" ? "text-[var(--green)]" : "text-[var(--red)]"}`}>{t.side}</td>
                  <td className="p-3 text-right">{formatPrice(t.entry_price)}</td>
                  <td className="p-3 text-right">{formatPrice(t.exit_price)}</td>
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
