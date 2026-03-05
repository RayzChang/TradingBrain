import { useEffect, useRef, useState, useCallback } from "react";
import {
    createChart,
    IChartApi,
    ISeriesApi,
    HistogramData,
    LineData,
    Time,
    CrosshairMode,
} from "lightweight-charts";
import { api } from "../api";

interface KlineChartProps {
    symbol?: string;
    timeframe?: string;
    height?: number;
}

const TF_OPTIONS = ["1m", "5m", "15m", "1h", "4h", "1d"];
const TF_LABELS: Record<string, string> = {
    "1m": "1分", "5m": "5分", "15m": "15分", "1h": "1時", "4h": "4時", "1d": "1日",
};

/* ═══ 技術指標計算 ═══ */
function calcEMA(closes: number[], period: number): (number | null)[] {
    const k = 2 / (period + 1);
    const r: (number | null)[] = [];
    let ema: number | null = null;
    for (let i = 0; i < closes.length; i++) {
        if (i < period - 1) r.push(null);
        else if (ema === null) { ema = closes.slice(0, period).reduce((a, b) => a + b, 0) / period; r.push(ema); }
        else { ema = (closes[i] - ema) * k + ema; r.push(ema); }
    }
    return r;
}

function calcMACD(closes: number[]) {
    const e12 = calcEMA(closes, 12), e26 = calcEMA(closes, 26);
    const ml: (number | null)[] = e12.map((v, i) => v !== null && e26[i] !== null ? v - e26[i]! : null);
    const valid = ml.filter(v => v !== null) as number[];
    const sigRaw = calcEMA(valid, 9);
    const sig: (number | null)[] = []; let si = 0;
    ml.forEach(m => { if (m === null) sig.push(null); else { sig.push(sigRaw[si] ?? null); si++; } });
    const hist = ml.map((m, i) => m !== null && sig[i] !== null ? m - sig[i]! : null);
    return { ml, sig, hist };
}

function calcRSI(closes: number[], p = 14): (number | null)[] {
    const r: (number | null)[] = [];
    if (closes.length < p + 1) return closes.map(() => null);
    let gS = 0, lS = 0;
    for (let i = 1; i <= p; i++) { const d = closes[i] - closes[i - 1]; d > 0 ? gS += d : lS += Math.abs(d); }
    let aG = gS / p, aL = lS / p;
    for (let i = 0; i < p; i++) r.push(null);
    r.push(aL === 0 ? 100 : 100 - 100 / (1 + aG / aL));
    for (let i = p + 1; i < closes.length; i++) {
        const d = closes[i] - closes[i - 1];
        aG = (aG * (p - 1) + (d > 0 ? d : 0)) / p;
        aL = (aL * (p - 1) + (d < 0 ? Math.abs(d) : 0)) / p;
        r.push(aL === 0 ? 100 : 100 - 100 / (1 + aG / aL));
    }
    return r;
}

function calcBollinger(closes: number[], period = 20, mult = 2) {
    const u: (number | null)[] = [], m: (number | null)[] = [], l: (number | null)[] = [];
    for (let i = 0; i < closes.length; i++) {
        if (i < period - 1) { u.push(null); m.push(null); l.push(null); }
        else {
            const sl = closes.slice(i - period + 1, i + 1);
            const mean = sl.reduce((a, b) => a + b, 0) / period;
            const std = Math.sqrt(sl.reduce((a, b) => a + (b - mean) ** 2, 0) / period);
            m.push(mean); u.push(mean + mult * std); l.push(mean - mult * std);
        }
    }
    return { upper: u, middle: m, lower: l };
}

type K = { time: number; open: number; high: number; low: number; close: number; volume: number };

/* ═══ OHLCV Legend ═══ */
function OhlcvLegend({ data }: { data: K | null }) {
    if (!data) return null;
    const chg = data.close - data.open;
    const pct = data.open ? ((chg / data.open) * 100).toFixed(2) : "0.00";
    const c = chg >= 0 ? "var(--green)" : "var(--red)";
    const fmtVol = (v: number) => v >= 1e6 ? (v / 1e6).toFixed(2) + "M" : v >= 1e3 ? (v / 1e3).toFixed(1) + "K" : v.toFixed(0);
    return (
        <div className="absolute top-[40px] left-3 z-20 flex gap-3 text-[0.65rem] font-mono pointer-events-none flex-wrap" style={{ color: "var(--text-secondary)" }}>
            <span>O <b style={{ color: c }}>{data.open.toFixed(2)}</b></span>
            <span>H <b style={{ color: c }}>{data.high.toFixed(2)}</b></span>
            <span>L <b style={{ color: c }}>{data.low.toFixed(2)}</b></span>
            <span>C <b style={{ color: c }}>{data.close.toFixed(2)}</b></span>
            <span>Vol <b>{fmtVol(data.volume)}</b></span>
            <b style={{ color: c }}>{chg >= 0 ? "+" : ""}{pct}%</b>
        </div>
    );
}

/* ═══ 主元件 ═══ */
export default function KlineChart({ symbol: initSym = "BTCUSDT", timeframe: initTf = "15m", height = 420 }: KlineChartProps) {
    const mainRef = useRef<HTMLDivElement>(null);
    const macdRef = useRef<HTMLDivElement>(null);
    const rsiRef = useRef<HTMLDivElement>(null);

    const mainChartRef = useRef<IChartApi | null>(null);
    const macdChartRef = useRef<IChartApi | null>(null);
    const rsiChartRef = useRef<IChartApi | null>(null);

    const cdlRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
    const volRef = useRef<ISeriesApi<"Histogram"> | null>(null);
    const ema7R = useRef<ISeriesApi<"Line"> | null>(null);
    const ema25R = useRef<ISeriesApi<"Line"> | null>(null);
    const ema99R = useRef<ISeriesApi<"Line"> | null>(null);
    const bbUR = useRef<ISeriesApi<"Line"> | null>(null);
    const bbMR = useRef<ISeriesApi<"Line"> | null>(null);
    const bbLR = useRef<ISeriesApi<"Line"> | null>(null);
    const mcdLR = useRef<ISeriesApi<"Line"> | null>(null);
    const mcdSR = useRef<ISeriesApi<"Line"> | null>(null);
    const mcdHR = useRef<ISeriesApi<"Histogram"> | null>(null);
    const rsiLR = useRef<ISeriesApi<"Line"> | null>(null);

    const [sym, setSym] = useState(initSym);
    const [tf, setTf] = useState(initTf);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState("");
    const [hover, setHover] = useState<K | null>(null);
    const [showEMA, setShowEMA] = useState(true);
    const [showBB, setShowBB] = useState(false);
    const [showMACD, setShowMACD] = useState(false);
    const [showRSI, setShowRSI] = useState(false);
    const rawRef = useRef<K[]>([]);

    useEffect(() => { setSym(initSym); }, [initSym]);

    const chartOpts = (bg = "transparent") => ({
        layout: { background: { color: bg }, textColor: "#6b7280", fontSize: 11, fontFamily: "'JetBrains Mono', monospace" },
        grid: { vertLines: { color: "rgba(100,120,180,0.06)" }, horzLines: { color: "rgba(100,120,180,0.06)" } },
        crosshair: {
            mode: CrosshairMode.Normal,
            vertLine: { color: "rgba(0,240,255,0.25)", style: 2, width: 1 as const, labelBackgroundColor: "#1a1a2e" },
            horzLine: { color: "rgba(0,240,255,0.25)", style: 2, width: 1 as const, labelBackgroundColor: "#1a1a2e" },
        },
        timeScale: { borderColor: "rgba(100,120,180,0.12)", timeVisible: true, secondsVisible: false, rightOffset: 3, minBarSpacing: 6 },
        rightPriceScale: { borderColor: "rgba(100,120,180,0.12)" },
    });

    /* ── 建主圖 ── */
    useEffect(() => {
        if (!mainRef.current) return;
        const mainH = showMACD && showRSI ? height - 200 : showMACD || showRSI ? height - 100 : height;
        const chart = createChart(mainRef.current, {
            ...chartOpts(), width: mainRef.current.clientWidth, height: mainH,
            rightPriceScale: { borderColor: "rgba(100,120,180,0.12)", scaleMargins: { top: 0.05, bottom: 0.18 } },
        });

        const cdl = chart.addCandlestickSeries({
            upColor: "#26a69a", downColor: "#ef5350", borderUpColor: "#26a69a", borderDownColor: "#ef5350",
            wickUpColor: "#26a69a", wickDownColor: "#ef5350",
        });
        const vol = chart.addHistogramSeries({ priceFormat: { type: "volume" }, priceScaleId: "vol" });
        chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });

        const ema7 = chart.addLineSeries({ color: "#f59e0b", lineWidth: 1, priceLineVisible: false, lastValueVisible: true, crosshairMarkerVisible: false, title: "MA7" });
        const ema25 = chart.addLineSeries({ color: "#a855f7", lineWidth: 1, priceLineVisible: false, lastValueVisible: true, crosshairMarkerVisible: false, title: "MA25" });
        const ema99 = chart.addLineSeries({ color: "#3b82f6", lineWidth: 1, priceLineVisible: false, lastValueVisible: true, crosshairMarkerVisible: false, title: "MA99" });

        const bbU = chart.addLineSeries({ color: "rgba(0,240,255,0.35)", lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
        const bbM = chart.addLineSeries({ color: "rgba(0,240,255,0.15)", lineWidth: 1, lineStyle: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
        const bbL = chart.addLineSeries({ color: "rgba(0,240,255,0.35)", lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });

        chart.subscribeCrosshairMove((p) => {
            if (!p.time || !rawRef.current.length) { setHover(null); return; }
            setHover(rawRef.current.find(k => k.time === (p.time as number)) || null);
        });

        mainChartRef.current = chart; cdlRef.current = cdl; volRef.current = vol;
        ema7R.current = ema7; ema25R.current = ema25; ema99R.current = ema99;
        bbUR.current = bbU; bbMR.current = bbM; bbLR.current = bbL;

        const onResize = () => { if (mainRef.current) chart.applyOptions({ width: mainRef.current.clientWidth }); };
        window.addEventListener("resize", onResize);
        return () => { window.removeEventListener("resize", onResize); chart.remove(); mainChartRef.current = null; };
    }, [height, showMACD, showRSI]);

    /* ── 建 MACD 子圖 ── */
    useEffect(() => {
        if (!showMACD || !macdRef.current) { macdChartRef.current = null; return; }
        const chart = createChart(macdRef.current, { ...chartOpts(), width: macdRef.current.clientWidth, height: 100 });
        const mcdL = chart.addLineSeries({ color: "#00f0ff", lineWidth: 1, priceLineVisible: false, lastValueVisible: true, title: "MACD" });
        const mcdS = chart.addLineSeries({ color: "#ff2d8a", lineWidth: 1, priceLineVisible: false, lastValueVisible: true, title: "Signal" });
        const mcdH = chart.addHistogramSeries({ priceLineVisible: false, lastValueVisible: false });
        macdChartRef.current = chart; mcdLR.current = mcdL; mcdSR.current = mcdS; mcdHR.current = mcdH;
        const onResize = () => { if (macdRef.current) chart.applyOptions({ width: macdRef.current.clientWidth }); };
        window.addEventListener("resize", onResize);
        return () => { window.removeEventListener("resize", onResize); chart.remove(); macdChartRef.current = null; };
    }, [showMACD]);

    /* ── 建 RSI 子圖 ── */
    useEffect(() => {
        if (!showRSI || !rsiRef.current) { rsiChartRef.current = null; return; }
        const chart = createChart(rsiRef.current, { ...chartOpts(), width: rsiRef.current.clientWidth, height: 100 });
        const rsi = chart.addLineSeries({ color: "#f59e0b", lineWidth: 1, priceLineVisible: false, lastValueVisible: true, title: "RSI" });
        rsiChartRef.current = chart; rsiLR.current = rsi;
        const onResize = () => { if (rsiRef.current) chart.applyOptions({ width: rsiRef.current.clientWidth }); };
        window.addEventListener("resize", onResize);
        return () => { window.removeEventListener("resize", onResize); chart.remove(); rsiChartRef.current = null; };
    }, [showRSI]);

    /* ── 數據載入 ── */
    const loadData = useCallback((refresh = false) => {
        if (!refresh) { setLoading(true); setError(""); }

        api<{ klines: K[]; error?: string }>(`/klines/${sym}/${tf}?limit=200`)
            .then((data) => {
                if (data.error || !data.klines?.length) {
                    setError(data.error || `找不到 ${sym} 的數據`);
                    setLoading(false);
                    return;
                }
                rawRef.current = data.klines;
                const closes = data.klines.map(k => k.close);
                const toLD = (v: (number | null)[], ks: K[]) => ks.map((k, i) => v[i] !== null ? { time: k.time as Time, value: v[i]! } : null).filter(Boolean) as LineData<Time>[];

                // 主圖
                cdlRef.current?.setData(data.klines.map(k => ({ time: k.time as Time, open: k.open, high: k.high, low: k.low, close: k.close })));
                volRef.current?.setData(data.klines.map(k => ({ time: k.time as Time, value: k.volume, color: k.close >= k.open ? "rgba(38,166,154,0.35)" : "rgba(239,83,80,0.35)" })));

                if (showEMA) {
                    ema7R.current?.setData(toLD(calcEMA(closes, 7), data.klines));
                    ema25R.current?.setData(toLD(calcEMA(closes, 25), data.klines));
                    ema99R.current?.setData(toLD(calcEMA(closes, 99), data.klines));
                } else { ema7R.current?.setData([]); ema25R.current?.setData([]); ema99R.current?.setData([]); }

                if (showBB) {
                    const b = calcBollinger(closes);
                    bbUR.current?.setData(toLD(b.upper, data.klines));
                    bbMR.current?.setData(toLD(b.middle, data.klines));
                    bbLR.current?.setData(toLD(b.lower, data.klines));
                } else { bbUR.current?.setData([]); bbMR.current?.setData([]); bbLR.current?.setData([]); }

                // MACD 子圖
                if (showMACD && mcdLR.current) {
                    const m = calcMACD(closes);
                    mcdLR.current.setData(toLD(m.ml, data.klines));
                    mcdSR.current?.setData(toLD(m.sig, data.klines));
                    mcdHR.current?.setData(data.klines.map((k, i) => m.hist[i] !== null ? { time: k.time as Time, value: m.hist[i]!, color: m.hist[i]! >= 0 ? "rgba(38,166,154,0.6)" : "rgba(239,83,80,0.6)" } : null).filter(Boolean) as HistogramData<Time>[]);
                }

                // RSI 子圖
                if (showRSI && rsiLR.current) {
                    rsiLR.current.setData(toLD(calcRSI(closes), data.klines));
                }

                if (!refresh) {
                    mainChartRef.current?.timeScale().fitContent();
                    macdChartRef.current?.timeScale().fitContent();
                    rsiChartRef.current?.timeScale().fitContent();
                }
                setLoading(false);
            })
            .catch((e) => { setError(`無法載入 ${sym}: ${e}`); setLoading(false); });
    }, [sym, tf, showEMA, showBB, showMACD, showRSI]);

    useEffect(() => { loadData(false); }, [loadData]);
    useEffect(() => { const t = setInterval(() => loadData(true), 1000); return () => clearInterval(t); }, [loadData]);

    /* ── 同步時間軸 ── */
    useEffect(() => {
        const main = mainChartRef.current;
        if (!main) return;
        const handler = (range: any) => {
            if (!range) return;
            macdChartRef.current?.timeScale().setVisibleLogicalRange(range);
            rsiChartRef.current?.timeScale().setVisibleLogicalRange(range);
        };
        main.timeScale().subscribeVisibleLogicalRangeChange(handler);
        return () => {
            main.timeScale().unsubscribeVisibleLogicalRangeChange(handler);
        };
    });

    const Btn = ({ label, on, onClick, c }: { label: string; on: boolean; onClick: () => void; c: string }) => (
        <button onClick={onClick}
            className={`px-2 py-0.5 text-[0.6rem] rounded font-mono transition-all border ${on ? "" : "text-[var(--text-dim)] border-transparent hover:border-[var(--border)]"}`}
            style={on ? { background: `${c}22`, borderColor: `${c}44`, color: c } : {}}
        >{label}</button>
    );

    return (
        <div className="glass-card overflow-hidden relative">
            {/* 頂部欄 */}
            <div className="flex items-center justify-between px-4 py-2 border-b border-[var(--border)] flex-wrap gap-1">
                <div className="flex items-center gap-2">
                    <h3 className="text-sm font-bold neon-text">{sym}</h3>
                    <div className="flex gap-0.5">
                        {TF_OPTIONS.map(t => (
                            <button key={t} onClick={() => setTf(t)}
                                className={`px-2 py-0.5 text-[0.6rem] rounded-md font-mono transition-all ${tf === t ? "bg-[rgba(0,240,255,0.12)] text-[var(--neon-cyan)] border border-[rgba(0,240,255,0.25)]" : "text-[var(--text-dim)] hover:text-[var(--text-secondary)] border border-transparent"}`}
                            >{TF_LABELS[t]}</button>
                        ))}
                    </div>
                </div>
                <div className="flex items-center gap-1">
                    <Btn label="MA" on={showEMA} onClick={() => setShowEMA(!showEMA)} c="#f59e0b" />
                    <Btn label="BOLL" on={showBB} onClick={() => setShowBB(!showBB)} c="#00f0ff" />
                    <Btn label="MACD" on={showMACD} onClick={() => setShowMACD(!showMACD)} c="#00f0ff" />
                    <Btn label="RSI" on={showRSI} onClick={() => setShowRSI(!showRSI)} c="#f59e0b" />
                    {loading && <span className="text-[0.55rem] text-[var(--text-dim)] animate-pulse ml-1">⟳</span>}
                </div>
            </div>

            <OhlcvLegend data={hover} />

            {/* 錯誤覆蓋 */}
            {error && (
                <div className="absolute inset-0 flex items-center justify-center z-30" style={{ background: "rgba(5,5,16,0.85)" }}>
                    <div className="text-center">
                        <p className="text-sm text-[var(--red)] font-mono mb-2">{error}</p>
                        <p className="text-xs text-[var(--text-dim)]">請確認幣種名稱是否正確（合約市場）</p>
                    </div>
                </div>
            )}

            {/* 主圖 */}
            <div ref={mainRef} />

            {/* MACD 子圖 */}
            {showMACD && (
                <div className="border-t border-[var(--border)]">
                    <span className="absolute left-3 text-[0.5rem] text-[var(--text-dim)] font-mono z-10 mt-0.5">MACD</span>
                    <div ref={macdRef} />
                </div>
            )}

            {/* RSI 子圖 */}
            {showRSI && (
                <div className="border-t border-[var(--border)]">
                    <span className="absolute left-3 text-[0.5rem] text-[var(--text-dim)] font-mono z-10 mt-0.5">RSI(14)</span>
                    <div ref={rsiRef} />
                </div>
            )}

            {/* 底部圖例 */}
            <div className="flex items-center gap-4 px-4 py-1.5 border-t border-[var(--border)] text-[0.55rem] font-mono text-[var(--text-dim)]">
                {showEMA && <>
                    <span className="flex items-center gap-1"><span className="w-3 h-[2px] bg-[#f59e0b] inline-block" /> MA7</span>
                    <span className="flex items-center gap-1"><span className="w-3 h-[2px] bg-[#a855f7] inline-block" /> MA25</span>
                    <span className="flex items-center gap-1"><span className="w-3 h-[2px] bg-[#3b82f6] inline-block" /> MA99</span>
                </>}
                {showBB && <span className="flex items-center gap-1"><span className="w-3 h-[2px] bg-[#00f0ff] inline-block opacity-50" /> BOLL(20,2)</span>}
                {showMACD && <>
                    <span className="flex items-center gap-1"><span className="w-3 h-[2px] bg-[#00f0ff] inline-block" /> MACD</span>
                    <span className="flex items-center gap-1"><span className="w-3 h-[2px] bg-[#ff2d8a] inline-block" /> Signal</span>
                </>}
                {showRSI && <span className="flex items-center gap-1"><span className="w-3 h-[2px] bg-[#f59e0b] inline-block" /> RSI(14)</span>}
                {!showEMA && !showBB && !showMACD && !showRSI && <span>點擊右上角按鈕啟用技術指標</span>}
            </div>
        </div>
    );
}
