import { useEffect, useState } from "react";
import { signalsApi } from "../api";

interface SignalRecord {
    symbol?: string;
    signal_type?: string;
    strategy_name?: string;
    strength?: number;
    was_vetoed?: number;
    veto_reason?: string;
    created_at?: string;
}

export default function DecisionPipeline() {
    const [signals, setSignals] = useState<SignalRecord[]>([]);

    useEffect(() => {
        signalsApi
            .list(8)
            .then((data) => setSignals(data as SignalRecord[]))
            .catch(() => { });
        const timer = setInterval(() => {
            signalsApi.list(8).then((data) => setSignals(data as SignalRecord[])).catch(() => { });
        }, 15000);
        return () => clearInterval(timer);
    }, []);

    return (
        <div className="glass-card p-4">
            <div className="relative z-10">
                <h3 className="text-xs uppercase tracking-widest text-[var(--text-secondary)] mb-3 font-medium">
                    決策管道
                </h3>

                {signals.length === 0 ? (
                    <div className="text-center py-6">
                        <div className="text-[var(--text-dim)] text-xs font-mono">
                            等待信號中...
                        </div>
                        <div className="mt-2 flex justify-center gap-1">
                            {[0, 1, 2].map((i) => (
                                <div
                                    key={i}
                                    className="w-1.5 h-1.5 rounded-full bg-[var(--neon-cyan)] pulse-glow"
                                    style={{ animationDelay: `${i * 0.3}s` }}
                                />
                            ))}
                        </div>
                    </div>
                ) : (
                    <div className="space-y-2 max-h-[280px] overflow-y-auto">
                        {signals.map((sig, i) => (
                            <div
                                key={`${sig.created_at}-${i}`}
                                className="flex items-center gap-2 py-1.5 px-2 rounded-md text-xs fade-up"
                                style={{
                                    animationDelay: `${i * 0.05}s`,
                                    background: sig.was_vetoed
                                        ? "rgba(255, 68, 102, 0.05)"
                                        : "rgba(0, 255, 136, 0.05)",
                                }}
                            >
                                {/* 狀態燈 */}
                                <div
                                    className="w-2 h-2 rounded-full flex-shrink-0"
                                    style={{
                                        background: sig.was_vetoed ? "var(--red)" : "var(--green)",
                                        boxShadow: sig.was_vetoed
                                            ? "0 0 6px var(--red)"
                                            : "0 0 6px var(--green)",
                                    }}
                                />
                                {/* 幣種 + 方向 */}
                                <span className="font-mono text-[var(--text)] font-medium">
                                    {sig.symbol}
                                </span>
                                <span
                                    className={
                                        sig.signal_type === "LONG"
                                            ? "badge-long"
                                            : sig.signal_type === "SHORT"
                                                ? "badge-short"
                                                : "text-[var(--text-dim)]"
                                    }
                                >
                                    {sig.signal_type === "LONG" ? "做多" : sig.signal_type === "SHORT" ? "做空" : sig.signal_type || "—"}
                                </span>
                                {/* 策略 */}
                                <span className="text-[var(--text-dim)] truncate flex-1">
                                    {sig.strategy_name || ""}
                                </span>
                                {/* 結果 */}
                                <span
                                    className="text-[0.65rem] font-mono flex-shrink-0"
                                    style={{ color: sig.was_vetoed ? "var(--red)" : "var(--green)" }}
                                >
                                    {sig.was_vetoed ? "否決" : "通過"}
                                </span>
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
}
