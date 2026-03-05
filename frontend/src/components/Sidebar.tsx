import { Link, useLocation } from "react-router-dom";
import {
    LayoutDashboard,
    LineChart,
    Search,
    ArrowLeftRight,
    Radio,
    Shield,
    ChevronLeft,
    ChevronRight,
} from "lucide-react";
import { useState } from "react";

const navItems = [
    { to: "/", icon: LayoutDashboard, label: "控制台", group: "main" },
    { to: "/market", icon: LineChart, label: "K線圖", group: "main" },
    { to: "/screener", icon: Search, label: "選幣器", group: "main" },
    { to: "/trades", icon: ArrowLeftRight, label: "交易", group: "sub" },
    { to: "/signals", icon: Radio, label: "信號", group: "sub" },
    { to: "/risk", icon: Shield, label: "風控", group: "sub" },
];

export default function Sidebar() {
    const loc = useLocation();
    const [collapsed, setCollapsed] = useState(false);

    const mainItems = navItems.filter(n => n.group === "main");
    const subItems = navItems.filter(n => n.group === "sub");

    return (
        <aside
            className={`h-screen sticky top-0 flex flex-col transition-all duration-300 ${collapsed ? "w-[68px]" : "w-[220px]"
                }`}
            style={{
                background: "var(--gradient-sidebar)",
                borderRight: "1px solid var(--border)",
            }}
        >
            {/* Logo */}
            <div className="flex items-center gap-3 px-4 py-5 border-b border-[var(--border)]">
                <div className="w-9 h-9 rounded-lg overflow-hidden pulse-glow flex-shrink-0 bg-[#050510]">
                    <img src="/brain-logo.png" alt="TradingBrain" className="w-full h-full object-cover" />
                </div>
                {!collapsed && (
                    <div className="overflow-hidden">
                        <h1 className="text-sm font-bold neon-text tracking-wider leading-none">
                            TradingBrain
                        </h1>
                        <span className="text-[0.6rem] text-[var(--text-dim)] font-mono">
                            交易大腦 v4
                        </span>
                    </div>
                )}
            </div>

            {/* 主導覽 */}
            <nav className="flex-1 py-4 px-2 flex flex-col gap-1">
                {mainItems.map(({ to, icon: Icon, label }) => {
                    const active = loc.pathname === to;
                    return (
                        <Link
                            key={to}
                            to={to}
                            className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-200 group ${active
                                ? "text-[var(--neon-cyan)]"
                                : "text-[var(--text-secondary)] hover:text-[var(--text)]"
                                }`}
                            style={
                                active
                                    ? {
                                        background: "rgba(0, 240, 255, 0.08)",
                                        borderLeft: "2px solid var(--neon-cyan)",
                                        boxShadow: "0 0 20px rgba(0, 240, 255, 0.05)",
                                    }
                                    : { borderLeft: "2px solid transparent" }
                            }
                        >
                            <Icon
                                size={18}
                                className={`flex-shrink-0 transition-all ${active ? "drop-shadow-[0_0_6px_rgba(0,240,255,0.5)]" : ""
                                    }`}
                            />
                            {!collapsed && <span>{label}</span>}
                        </Link>
                    );
                })}

                {/* 分隔線 */}
                <div className="my-3 mx-3 border-t border-[var(--border)]" />

                <div className={`text-[0.6rem] uppercase tracking-widest text-[var(--text-dim)] px-3 mb-1 ${collapsed ? 'hidden' : ''}`}>
                    數據中心
                </div>

                {subItems.map(({ to, icon: Icon, label }) => {
                    const active = loc.pathname === to;
                    return (
                        <Link
                            key={to}
                            to={to}
                            className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-all duration-200 ${active
                                ? "text-[var(--neon-purple)]"
                                : "text-[var(--text-dim)] hover:text-[var(--text-secondary)]"
                                }`}
                            style={
                                active
                                    ? {
                                        background: "rgba(168, 85, 247, 0.08)",
                                        borderLeft: "2px solid var(--neon-purple)",
                                    }
                                    : { borderLeft: "2px solid transparent" }
                            }
                        >
                            <Icon size={16} className="flex-shrink-0" />
                            {!collapsed && <span>{label}</span>}
                        </Link>
                    );
                })}
            </nav>

            {/* 底部狀態 + 收合按鈕 */}
            <div className="px-3 py-3 border-t border-[var(--border)]">
                {!collapsed && (
                    <div className="flex items-center gap-2 mb-2 px-1">
                        <div className="w-2 h-2 rounded-full bg-[var(--green)] animate-pulse" />
                        <span className="text-[0.65rem] text-[var(--text-dim)] font-mono">
                            運行中 · DEMO
                        </span>
                    </div>
                )}
                <button
                    onClick={() => setCollapsed(!collapsed)}
                    className="w-full flex items-center justify-center py-1.5 rounded-md hover:bg-[rgba(0,240,255,0.05)] text-[var(--text-dim)] transition-colors"
                >
                    {collapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
                </button>
            </div>
        </aside>
    );
}
