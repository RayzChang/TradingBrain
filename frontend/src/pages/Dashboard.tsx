import { useEffect, useState, useCallback } from "react";
import { systemApi, tradesApi } from "../api";
import { Wallet, TrendingUp, Target, BarChart3 } from "lucide-react";
import StatCard from "../components/StatCard";
import KlineChart from "../components/KlineChart";
import DecisionPipeline from "../components/DecisionPipeline";

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

type StatusData = {
  mode: string;
  initial_balance: number;
  total_realized_pnl: number;
  daily_pnl: number;
  open_positions_count: number;
  exchange_balance?: number;
};

export default function Dashboard() {
  const [status, setStatus] = useState<StatusData | null>(null);
  const [openTrades, setOpenTrades] = useState<Trade[]>([]);
  const [totalUnrealized, setTotalUnrealized] = useState<number | null>(null);
  const [todayTrades, setTodayTrades] = useState<Trade[]>([]);
  const [err, setErr] = useState("");

  const fetchData = useCallback(() => {
    systemApi
      .status()
      .then((d) => {
        setStatus(d);
        setErr("");
      })
      .catch((e) => setErr(String(e)));
    tradesApi
      .openWithPnl()
      .then((r) => {
        setOpenTrades(r.open_trades as Trade[]);
        setTotalUnrealized(r.total_unrealized_pnl);
      })
      .catch(() => { });
    tradesApi
      .today()
      .then((t) => setTodayTrades(t as Trade[]))
      .catch(() => { });
  }, []);

  useEffect(() => {
    fetchData();
    const timer = setInterval(fetchData, 5000);
    return () => clearInterval(timer);
  }, [fetchData]);

  if (err)
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-[var(--red)] font-mono text-sm">⚠ 連線失敗：{err}</p>
      </div>
    );

  if (!status)
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center">
          <div className="shimmer w-48 h-4 rounded mb-3 mx-auto" />
          <div className="shimmer w-32 h-3 rounded mx-auto" />
        </div>
      </div>
    );

  const balance = status.exchange_balance ?? status.initial_balance;
  const closedToday = todayTrades.filter((t) => t.status === "CLOSED");
  const winCount = closedToday.filter((t) => (t.pnl ?? 0) > 0).length;
  const winRate = closedToday.length > 0 ? ((winCount / closedToday.length) * 100).toFixed(1) : "—";

  return (
    <div className="space-y-5">
      {/* 頂部統計卡片 */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          title="交易所餘額"
          value={`${balance.toFixed(2)}`}
          suffix=" U"
          icon={<Wallet size={16} />}
          color="cyan"
          delay={0}
        />
        <StatCard
          title="今日損益"
          value={`${status.daily_pnl >= 0 ? "+" : ""}${status.daily_pnl.toFixed(2)}`}
          suffix=" U"
          icon={<TrendingUp size={16} />}
          color={status.daily_pnl >= 0 ? "green" : "red"}
          trend={status.daily_pnl >= 0 ? "up" : "down"}
          delay={1}
        />
        <StatCard
          title="今日勝率"
          value={winRate}
          suffix={winRate !== "—" ? "%" : ""}
          icon={<Target size={16} />}
          color="purple"
          delay={2}
        />
        <StatCard
          title="未平倉數"
          value={String(status.open_positions_count)}
          icon={<BarChart3 size={16} />}
          color="default"
          delay={3}
        />
      </div>

      {/* K 線圖 + 決策管道 */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2">
          <KlineChart symbol="BTCUSDT" timeframe="15m" height={380} />
        </div>
        <DecisionPipeline />
      </div>

      {/* 累計損益 + 未實現 */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="glass-card p-4">
          <div className="relative z-10">
            <h3 className="text-xs uppercase tracking-widest text-[var(--text-secondary)] mb-2 font-medium">
              累計已實現損益
            </h3>
            <p
              className={`text-2xl font-bold font-mono ${status.total_realized_pnl >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"
                }`}
            >
              {status.total_realized_pnl >= 0 ? "+" : ""}
              {status.total_realized_pnl.toFixed(2)} U
            </p>
            <p className="text-xs text-[var(--text-dim)] mt-1 font-mono">
              初始 {status.initial_balance} U → 現在 {balance.toFixed(2)} U
            </p>
          </div>
        </div>
        {totalUnrealized !== null && (
          <div className="glass-card p-4">
            <div className="relative z-10">
              <h3 className="text-xs uppercase tracking-widest text-[var(--text-secondary)] mb-2 font-medium">
                未實現損益
              </h3>
              <p
                className={`text-2xl font-bold font-mono ${totalUnrealized >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"
                  }`}
              >
                {totalUnrealized >= 0 ? "+" : ""}
                {totalUnrealized.toFixed(2)} U
              </p>
            </div>
          </div>
        )}
      </div>

      {/* 持倉表 */}
      <div className="glass-card overflow-hidden">
        <div className="relative z-10">
          <div className="px-4 py-3 border-b border-[var(--border)]">
            <h3 className="text-xs uppercase tracking-widest text-[var(--text-secondary)] font-medium">
              活躍持倉 ({openTrades.length})
            </h3>
          </div>
          <div className="overflow-x-auto">
            <table className="cyber-table">
              <thead>
                <tr>
                  <th>交易對</th>
                  <th>方向</th>
                  <th className="text-right">進場價</th>
                  <th className="text-right">當前價</th>
                  <th className="text-right">止損</th>
                  <th className="text-right">止盈</th>
                  <th className="text-right">未實現損益</th>
                  <th>策略</th>
                  <th className="text-right">槓桿</th>
                </tr>
              </thead>
              <tbody>
                {openTrades.length === 0 && (
                  <tr>
                    <td colSpan={9} className="text-center py-8 text-[var(--text-dim)] font-mono text-xs">
                      目前無持倉 — 等待信號觸發
                    </td>
                  </tr>
                )}
                {openTrades.map((t) => (
                  <tr key={t.id}>
                    <td className="font-mono font-medium">{t.symbol}</td>
                    <td>
                      <span className={t.side === "LONG" ? "badge-long" : "badge-short"}>
                        {t.side === "LONG" ? "做多" : "做空"}
                      </span>
                    </td>
                    <td className="text-right font-mono">{t.entry_price}</td>
                    <td className="text-right font-mono">
                      {t.current_price != null ? t.current_price.toFixed(2) : "—"}
                    </td>
                    <td className="text-right font-mono text-[var(--text-dim)]">
                      {t.stop_loss != null ? t.stop_loss.toFixed(2) : "—"}
                    </td>
                    <td className="text-right font-mono text-[var(--text-dim)]">
                      {t.take_profit != null ? t.take_profit.toFixed(2) : "—"}
                    </td>
                    <td
                      className={`text-right font-mono font-medium ${t.unrealized_pnl != null
                        ? t.unrealized_pnl >= 0
                          ? "text-[var(--green)]"
                          : "text-[var(--red)]"
                        : ""
                        }`}
                    >
                      {t.unrealized_pnl != null
                        ? `${t.unrealized_pnl >= 0 ? "+" : ""}${t.unrealized_pnl.toFixed(2)}`
                        : "—"}
                    </td>
                    <td className="text-[var(--text-dim)] text-xs">{t.strategy_name ?? "—"}</td>
                    <td className="text-right font-mono">{t.leverage}x</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
