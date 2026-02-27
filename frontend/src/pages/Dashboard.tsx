import { useEffect, useState, useCallback } from "react";
import { systemApi, tradesApi } from "../api";

export default function Dashboard() {
  const [status, setStatus] = useState<{
    mode: string;
    initial_balance: number;
    total_realized_pnl: number;
    daily_pnl: number;
    open_positions_count: number;
    exchange_balance?: number;
  } | null>(null);
  const [totalUnrealized, setTotalUnrealized] = useState<number | null>(null);
  const [err, setErr] = useState("");
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  const fetchData = useCallback(() => {
    systemApi
      .status()
      .then((d) => {
        setStatus(d);
        setLastUpdate(new Date());
        setErr("");
      })
      .catch((e) => setErr(String(e)));
    tradesApi
      .openWithPnl()
      .then((r) => setTotalUnrealized(r.total_unrealized_pnl))
      .catch(() => setTotalUnrealized(null));
  }, []);

  // 初始載入 + 每 5 秒自動刷新
  useEffect(() => {
    fetchData();
    const timer = setInterval(fetchData, 5000);
    return () => clearInterval(timer);
  }, [fetchData]);

  if (err) return <p className="text-[var(--red)]">無法載入：{err}</p>;
  if (!status) return <p className="text-[var(--muted)]">載入中…</p>;

  const equity = status.initial_balance + status.total_realized_pnl;
  const equityWithUnrealized = totalUnrealized != null ? equity + totalUnrealized : null;
  const exchangeBal = status.exchange_balance;

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-bold">總覽</h2>
        {lastUpdate && (
          <span className="text-xs text-[var(--muted)]">
            🔄 {lastUpdate.toLocaleTimeString()} 自動刷新中
          </span>
        )}
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <Card title="模式" value={status.mode.toUpperCase()} />
        {exchangeBal != null && exchangeBal > 0 ? (
          <Card title="交易所餘額" value={`${exchangeBal.toFixed(2)} USDT`} />
        ) : (
          <Card title="參考餘額" value={`${status.initial_balance} USDT`} />
        )}
        <Card
          title="今日已實現損益"
          value={`${status.daily_pnl >= 0 ? "+" : ""}${status.daily_pnl.toFixed(2)} USDT`}
          valueClass={status.daily_pnl >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"}
        />
        <Card title="未平倉數" value={String(status.open_positions_count)} />
        {totalUnrealized !== null && (
          <Card
            title="未實現損益"
            value={`${totalUnrealized >= 0 ? "+" : ""}${totalUnrealized.toFixed(2)} USDT`}
            valueClass={totalUnrealized >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"}
          />
        )}
      </div>
      <div className="mt-6 p-4 rounded-lg bg-[var(--card)] border border-[var(--border)]">
        <h3 className="font-semibold mb-2">累計已實現損益</h3>
        <p className={`text-2xl ${status.total_realized_pnl >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"}`}>
          {status.total_realized_pnl >= 0 ? "+" : ""}
          {status.total_realized_pnl.toFixed(2)} USDT
        </p>
        <p className="text-sm text-[var(--muted)] mt-1">
          權益參考 = {status.initial_balance} + {status.total_realized_pnl.toFixed(2)} = {equity.toFixed(2)} USDT
          {equityWithUnrealized != null && (
            <> · 含未實現 ≈ {equityWithUnrealized.toFixed(2)} USDT</>
          )}
        </p>
      </div>
    </div>
  );
}

function Card({
  title,
  value,
  valueClass = "",
}: {
  title: string;
  value: string;
  valueClass?: string;
}) {
  return (
    <div className="p-4 rounded-lg bg-[var(--card)] border border-[var(--border)]">
      <p className="text-sm text-[var(--muted)]">{title}</p>
      <p className={`text-lg font-semibold mt-1 ${valueClass}`}>{value}</p>
    </div>
  );
}
