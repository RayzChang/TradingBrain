import { useState, useEffect } from "react";
import KlineChart from "../components/KlineChart";

const SYMBOL_GROUPS: Record<string, string[]> = {
    "熱門": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT"],
    "DeFi": ["AAVEUSDT", "UNIUSDT", "LINKUSDT", "AVAXUSDT", "ATOMUSDT"],
    "Layer2": ["MATICUSDT", "ARBUSDT", "OPUSDT"],
    "Meme": ["DOGEUSDT", "SHIBUSDT", "PEPEUSDT", "FLOKIUSDT"],
};

export default function MarketPage() {
    const [selectedSymbol, setSelectedSymbol] = useState("BTCUSDT");
    const [activeGroup, setActiveGroup] = useState("熱門");
    const [customInput, setCustomInput] = useState("");
    const [chartHeight, setChartHeight] = useState(550);

    useEffect(() => {
        const updateHeight = () => setChartHeight(Math.max(550, window.innerHeight - 170));
        updateHeight();
        window.addEventListener("resize", updateHeight);
        return () => window.removeEventListener("resize", updateHeight);
    }, []);

    const handleCustomSubmit = () => {
        let sym = customInput.trim().toUpperCase();
        if (!sym) return;
        // 自動加 USDT 後綴
        if (!sym.endsWith("USDT") && !sym.endsWith("BUSD") && !sym.endsWith("BTC")) {
            sym = sym + "USDT";
        }
        setSelectedSymbol(sym);
        setCustomInput("");
    };

    const symbols = SYMBOL_GROUPS[activeGroup] || SYMBOL_GROUPS["熱門"];

    return (
        <div className="space-y-4">
            {/* 分類 */}
            <div className="flex items-center gap-2 flex-wrap">
                <span className="text-xs text-[var(--text-dim)] uppercase tracking-widest mr-1">市場</span>
                {Object.keys(SYMBOL_GROUPS).map((group) => (
                    <button key={group} onClick={() => setActiveGroup(group)}
                        className={`px-2.5 py-1 text-xs rounded-lg transition-all ${activeGroup === group ? "bg-[rgba(168,85,247,0.12)] text-[var(--neon-purple)] border border-[rgba(168,85,247,0.3)]" : "text-[var(--text-dim)] hover:text-[var(--text-secondary)] border border-transparent"}`}
                    >{group}</button>
                ))}
                {/* 自訂幣種 */}
                <div className="flex items-center gap-1 ml-2">
                    <input
                        type="text" value={customInput}
                        onChange={(e) => setCustomInput(e.target.value)}
                        onKeyDown={(e) => e.key === "Enter" && handleCustomSubmit()}
                        placeholder="輸入幣種 (例: FIL)..."
                        className="w-36 px-2 py-1 text-xs font-mono rounded-md bg-[var(--bg-card)] border border-[var(--border)] text-[var(--text)] placeholder:text-[var(--text-dim)] focus:border-[var(--neon-cyan)] focus:outline-none"
                    />
                    <button onClick={handleCustomSubmit}
                        className="px-2 py-1 text-xs rounded-md bg-[rgba(0,240,255,0.1)] text-[var(--neon-cyan)] border border-[rgba(0,240,255,0.2)] hover:bg-[rgba(0,240,255,0.2)] transition-all"
                    >搜尋</button>
                </div>
            </div>

            {/* 幣種列 */}
            <div className="flex items-center gap-1.5 flex-wrap">
                {symbols.map((sym) => (
                    <button key={sym} onClick={() => setSelectedSymbol(sym)}
                        className={`px-3 py-1.5 rounded-lg text-xs font-mono transition-all ${selectedSymbol === sym ? "bg-[rgba(0,240,255,0.12)] text-[var(--neon-cyan)] border border-[rgba(0,240,255,0.3)] shadow-[0_0_12px_rgba(0,240,255,0.1)]" : "text-[var(--text-dim)] hover:text-[var(--text-secondary)] border border-transparent hover:border-[var(--border)]"}`}
                    >{sym.replace("USDT", "")}</button>
                ))}
            </div>

            {/* 主圖 */}
            <KlineChart symbol={selectedSymbol} timeframe="15m" height={chartHeight} />
        </div>
    );
}
