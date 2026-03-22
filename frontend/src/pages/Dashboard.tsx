import { useEffect, useState } from "react";
import { Wallet, TrendingUp, Target, BarChart3 } from "lucide-react";

import { systemApi, tradesApi } from "../api";
import DecisionPipeline from "../components/DecisionPipeline";
import KlineChart from "../components/KlineChart";
import StatCard from "../components/StatCard";

type Trade = {
  id: number;
  symbol: string;
  side: string;
  entry_price: number;
  quantity: number;
  leverage: number;
  status: string;
  pnl?: number | null;
  stop_loss?: number | null;
  take_profit?: number | null;
  soft_stop_loss?: number | null;
  hard_stop_loss?: number | null;
  soft_stop_required_closes?: number | null;
  stop_zone_low?: number | null;
  stop_zone_high?: number | null;
  tp1_price?: number | null;
  tp1_zone_low?: number | null;
  tp1_zone_high?: number | null;
  tp2_price?: number | null;
  tp2_zone_low?: number | null;
  tp2_zone_high?: number | null;
  tp3_price?: number | null;
  tp3_zone_low?: number | null;
  tp3_zone_high?: number | null;
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
  exchange_balance?: number | null;
};

function formatPrice(value?: number | null): string {
  if (value == null || Number.isNaN(value)) {
    return "--";
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

function renderProtection(trade: Trade) {
  const softStop = trade.soft_stop_loss ?? trade.stop_loss;
  const hardStop = trade.hard_stop_loss ?? trade.stop_loss;
  const stopZone = formatZone(trade.stop_zone_low, trade.stop_zone_high);
  const closeRule =
    trade.soft_stop_required_closes && trade.soft_stop_required_closes > 0
      ? `${trade.soft_stop_required_closes} 根收破`
      : null;

  return (
    <div className="space-y-1 text-right">
      <div className="font-mono text-xs text-[var(--text-primary)]">Soft {formatPrice(softStop)}</div>
      <div className="font-mono text-xs text-[var(--text-dim)]">Hard {formatPrice(hardStop)}</div>
      {stopZone && <div className="text-[11px] text-[var(--text-dim)]">Zone {stopZone}</div>}
      {closeRule && <div className="text-[11px] text-[var(--text-dim)]">{closeRule}</div>}
    </div>
  );
}

function renderTargets(trade: Trade) {
  const tp1Zone = formatZone(trade.tp1_zone_low, trade.tp1_zone_high);
  const tp2Zone = formatZone(trade.tp2_zone_low, trade.tp2_zone_high);
  const tp3Zone = formatZone(trade.tp3_zone_low, trade.tp3_zone_high);

  return (
    <div className="space-y-1 text-right">
      <div className="font-mono text-xs text-[var(--text-primary)]">TP1 {formatPrice(trade.tp1_price ?? trade.take_profit)}</div>
      <div className="font-mono text-xs text-[var(--text-dim)]">TP2 {formatPrice(trade.tp2_price)}</div>
      <div className="font-mono text-xs text-[var(--text-dim)]">TP3 {formatPrice(trade.tp3_price)}</div>
      {(tp1Zone || tp2Zone || tp3Zone) && (
        <div className="space-y-0.5 text-[11px] text-[var(--text-dim)]">
          {tp1Zone && <div>Z1 {tp1Zone}</div>}
          {tp2Zone && <div>Z2 {tp2Zone}</div>}
          {tp3Zone && <div>Z3 {tp3Zone}</div>}
        </div>
      )}
    </div>
  );
}

export default function Dashboard() {
  const [status, setStatus] = useState<StatusData | null>(null);
  const [openTrades, setOpenTrades] = useState<Trade[]>([]);
  const [totalUnrealized, setTotalUnrealized] = useState<number | null>(null);
  const [todayTrades, setTodayTrades] = useState<Trade[]>([]);
  const [chartHeight, setChartHeight] = useState(380);
  const [err, setErr] = useState("");

  useEffect(() => {
    let cancelled = false;

    const fetchData = async () => {
      try {
        const [statusData, openData, todayData] = await Promise.all([
          systemApi.status(),
          tradesApi.openWithPnl(),
          tradesApi.today(),
        ]);
        if (cancelled) {
          return;
        }
        setStatus(statusData);
        setOpenTrades(openData.open_trades as Trade[]);
        setTotalUnrealized(openData.total_unrealized_pnl);
        setTodayTrades(todayData as Trade[]);
        setErr("");
      } catch (error) {
        if (!cancelled) {
          setErr(error instanceof Error ? error.message : String(error));
        }
      }
    };

    fetchData();
    const timer = window.setInterval(fetchData, 5000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  if (err) {
    return (
      <div className="flex h-64 items-center justify-center">
        <p className="font-mono text-sm text-[var(--red)]">Dashboard load failed: {err}</p>
      </div>
    );
  }

  if (!status) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="text-center">
          <div className="mx-auto mb-3 h-4 w-48 rounded shimmer" />
          <div className="mx-auto h-3 w-32 rounded shimmer" />
        </div>
      </div>
    );
  }

  const balance = status.exchange_balance ?? status.initial_balance;
  const closedToday = todayTrades.filter((trade) => trade.status === "CLOSED");
  const winCount = closedToday.filter((trade) => (trade.pnl ?? 0) > 0).length;
  const winRate = closedToday.length > 0 ? ((winCount / closedToday.length) * 100).toFixed(1) : "0.0";

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard title="Balance" value={balance.toFixed(2)} suffix=" U" icon={<Wallet size={16} />} color="cyan" delay={0} />
        <StatCard
          title="Daily PnL"
          value={`${status.daily_pnl >= 0 ? "+" : ""}${status.daily_pnl.toFixed(2)}`}
          suffix=" U"
          icon={<TrendingUp size={16} />}
          color={status.daily_pnl >= 0 ? "green" : "red"}
          trend={status.daily_pnl >= 0 ? "up" : "down"}
          delay={1}
        />
        <StatCard title="Win Rate" value={winRate} suffix="%" icon={<Target size={16} />} color="purple" delay={2} />
        <StatCard title="Open Positions" value={String(status.open_positions_count)} icon={<BarChart3 size={16} />} color="default" delay={3} />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3 lg:items-start">
        <div className="lg:col-span-2">
          <KlineChart symbol="BTCUSDT" timeframe="15m" height={380} onHeightChange={setChartHeight} />
        </div>
        <div className="w-full" style={{ height: chartHeight ? `${chartHeight}px` : "auto" }}>
          <DecisionPipeline />
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="glass-card p-4">
          <div className="relative z-10">
            <h3 className="mb-2 text-xs font-medium uppercase tracking-widest text-[var(--text-secondary)]">Realized PnL</h3>
            <p className={`font-mono text-2xl font-bold ${status.total_realized_pnl >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"}`}>
              {status.total_realized_pnl >= 0 ? "+" : ""}
              {status.total_realized_pnl.toFixed(2)} U
            </p>
            <p className="mt-1 font-mono text-xs text-[var(--text-dim)]">Initial: {status.initial_balance.toFixed(2)} U</p>
          </div>
        </div>
        {totalUnrealized !== null && (
          <div className="glass-card p-4">
            <div className="relative z-10">
              <h3 className="mb-2 text-xs font-medium uppercase tracking-widest text-[var(--text-secondary)]">Unrealized PnL</h3>
              <p className={`font-mono text-2xl font-bold ${totalUnrealized >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"}`}>
                {totalUnrealized >= 0 ? "+" : ""}
                {totalUnrealized.toFixed(2)} U
              </p>
            </div>
          </div>
        )}
      </div>

      <div className="glass-card overflow-hidden">
        <div className="relative z-10">
          <div className="border-b border-[var(--border)] px-4 py-3">
            <h3 className="text-xs font-medium uppercase tracking-widest text-[var(--text-secondary)]">Open Trades ({openTrades.length})</h3>
          </div>
          <div className="overflow-x-auto">
            <table className="cyber-table">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Side</th>
                  <th className="text-right">Entry</th>
                  <th className="text-right">Current</th>
                  <th className="text-right">Protection</th>
                  <th className="text-right">Targets</th>
                  <th className="text-right">Unrealized</th>
                  <th>Strategy</th>
                  <th className="text-right">Leverage</th>
                </tr>
              </thead>
              <tbody>
                {openTrades.length === 0 && (
                  <tr>
                    <td colSpan={9} className="py-8 text-center font-mono text-xs text-[var(--text-dim)]">
                      No open trades.
                    </td>
                  </tr>
                )}
                {openTrades.map((trade) => (
                  <tr key={trade.id}>
                    <td className="font-mono font-medium">{trade.symbol}</td>
                    <td>
                      <span className={trade.side === "LONG" ? "badge-long" : "badge-short"}>{trade.side}</span>
                    </td>
                    <td className="text-right font-mono">{formatPrice(trade.entry_price)}</td>
                    <td className="text-right font-mono">{formatPrice(trade.current_price)}</td>
                    <td>{renderProtection(trade)}</td>
                    <td>{renderTargets(trade)}</td>
                    <td className={`text-right font-mono font-medium ${trade.unrealized_pnl != null ? (trade.unrealized_pnl >= 0 ? "text-[var(--green)]" : "text-[var(--red)]") : ""}`}>
                      {trade.unrealized_pnl != null ? `${trade.unrealized_pnl >= 0 ? "+" : ""}${trade.unrealized_pnl.toFixed(2)}` : "--"}
                    </td>
                    <td className="text-xs text-[var(--text-dim)]">{trade.strategy_name ?? "--"}</td>
                    <td className="text-right font-mono">{trade.leverage}x</td>
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
