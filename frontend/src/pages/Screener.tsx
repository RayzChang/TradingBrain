import { useEffect, useState, useCallback } from "react";
import { TrendingUp, TrendingDown, ArrowRight } from "lucide-react";
import KlineChart from "../components/KlineChart";

/* ── Binance 24h Ticker 接口（公開） ── */
type TickerInfo = {
    symbol: string;
    lastPrice: number;
    priceChangePercent: number;
    volume: number;
    high: number;
    low: number;
    quoteVolume: number;
};

const SCREENER_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "ADAUSDT", "ATOMUSDT",
    "MATICUSDT", "DOTUSDT", "ARBUSDT", "OPUSDT", "AAVEUSDT",
    "UNIUSDT", "LTCUSDT", "FILUSDT", "INJUSDT", "APTUSDT",
];

export default function ScreenerPage() {
    const [tickers, setTickers] = useState<TickerInfo[]>([]);
    const [loading, setLoading] = useState(true);
    const [sortBy, setSortBy] = useState<"change" | "volume">("change");
    const [sortDir, setSortDir] = useState<"desc" | "asc">("desc");
    const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);

    const fetchTickers = useCallback(async () => {
        try {
            const res = await fetch("https://fapi.binance.com/fapi/v1/ticker/24hr");
            const data = await res.json();
            const filtered = (data as Array<Record<string, string>>)
                .filter((t) => SCREENER_SYMBOLS.includes(t.symbol))
                .map((t) => ({
                    symbol: t.symbol,
                    lastPrice: parseFloat(t.lastPrice),
                    priceChangePercent: parseFloat(t.priceChangePercent),
                    volume: parseFloat(t.volume),
                    high: parseFloat(t.highPrice),
                    low: parseFloat(t.lowPrice),
                    quoteVolume: parseFloat(t.quoteVolume),
                }));
            setTickers(filtered);
            setLoading(false);
        } catch {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchTickers();
        const timer = setInterval(fetchTickers, 5000);
        return () => clearInterval(timer);
    }, [fetchTickers]);

    const sorted = [...tickers].sort((a, b) => {
        const val = sortBy === "change" ? a.priceChangePercent - b.priceChangePercent : a.quoteVolume - b.quoteVolume;
        return sortDir === "desc" ? -val : val;
    });

    const toggleSort = (key: "change" | "volume") => {
        if (sortBy === key) setSortDir(sortDir === "desc" ? "asc" : "desc");
        else { setSortBy(key); setSortDir("desc"); }
    };

    return (
        <div className="space-y-4">
            <div className="flex items-center justify-between">
                <span className="text-xs text-[var(--text-dim)] uppercase tracking-widest">選幣器 — 合約市場 24h 概覽</span>
                {loading && <span className="text-xs text-[var(--text-dim)] animate-pulse">載入中...</span>}
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                {/* 漲跌排行榜 */}
                <div className="lg:col-span-2 glass-card overflow-hidden">
                    <div className="relative z-10">
                        <div className="overflow-x-auto">
                            <table className="cyber-table">
                                <thead>
                                    <tr>
                                        <th>交易對</th>
                                        <th className="text-right">最新價</th>
                                        <th className="text-right cursor-pointer select-none" onClick={() => toggleSort("change")}>
                                            24h 漲跌 {sortBy === "change" ? (sortDir === "desc" ? "↓" : "↑") : ""}
                                        </th>
                                        <th className="text-right">24h 最高</th>
                                        <th className="text-right">24h 最低</th>
                                        <th className="text-right cursor-pointer select-none" onClick={() => toggleSort("volume")}>
                                            成交額(U) {sortBy === "volume" ? (sortDir === "desc" ? "↓" : "↑") : ""}
                                        </th>
                                        <th></th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {sorted.map((t) => (
                                        <tr key={t.symbol} className={selectedSymbol === t.symbol ? "!bg-[rgba(0,240,255,0.05)]" : ""}>
                                            <td className="font-mono font-medium">{t.symbol.replace("USDT", "")}</td>
                                            <td className="text-right font-mono">{t.lastPrice.toLocaleString(undefined, { maximumFractionDigits: 4 })}</td>
                                            <td className={`text-right font-mono font-semibold ${t.priceChangePercent >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"}`}>
                                                {t.priceChangePercent >= 0 ? "+" : ""}{t.priceChangePercent.toFixed(2)}%
                                                {t.priceChangePercent >= 0 ? <TrendingUp size={12} className="inline ml-1" /> : <TrendingDown size={12} className="inline ml-1" />}
                                            </td>
                                            <td className="text-right font-mono text-[var(--text-dim)]">{t.high.toLocaleString(undefined, { maximumFractionDigits: 2 })}</td>
                                            <td className="text-right font-mono text-[var(--text-dim)]">{t.low.toLocaleString(undefined, { maximumFractionDigits: 2 })}</td>
                                            <td className="text-right font-mono text-[var(--text-dim)]">
                                                {t.quoteVolume >= 1e9 ? (t.quoteVolume / 1e9).toFixed(2) + "B" : t.quoteVolume >= 1e6 ? (t.quoteVolume / 1e6).toFixed(1) + "M" : t.quoteVolume.toFixed(0)}
                                            </td>
                                            <td>
                                                <button
                                                    onClick={() => setSelectedSymbol(selectedSymbol === t.symbol ? null : t.symbol)}
                                                    className="text-[var(--neon-cyan)] hover:text-white transition-colors"
                                                >
                                                    <ArrowRight size={14} />
                                                </button>
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>

                {/* 右側快速圖表 */}
                <div>
                    {selectedSymbol ? (
                        <KlineChart symbol={selectedSymbol} timeframe="15m" height={400} />
                    ) : (
                        <div className="glass-card flex items-center justify-center h-[400px]">
                            <div className="relative z-10 text-center">
                                <p className="text-[var(--text-dim)] text-sm">← 點擊幣種右側箭頭</p>
                                <p className="text-[var(--text-dim)] text-xs mt-1">查看即時 K 線圖</p>
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
