import { useEffect, useRef, useState } from "react";

interface StatCardProps {
    title: string;
    value: string | number;
    prefix?: string;
    suffix?: string;
    trend?: "up" | "down" | "neutral";
    icon?: React.ReactNode;
    color?: "cyan" | "green" | "red" | "purple" | "default";
    delay?: number;
}

const colorMap = {
    cyan: { border: "rgba(0, 240, 255, 0.3)", glow: "rgba(0, 240, 255, 0.08)" },
    green: { border: "rgba(0, 255, 136, 0.3)", glow: "rgba(0, 255, 136, 0.08)" },
    red: { border: "rgba(255, 68, 102, 0.3)", glow: "rgba(255, 68, 102, 0.08)" },
    purple: { border: "rgba(168, 85, 247, 0.3)", glow: "rgba(168, 85, 247, 0.08)" },
    default: { border: "var(--border)", glow: "transparent" },
};

export default function StatCard({
    title,
    value,
    prefix = "",
    suffix = "",
    trend,
    icon,
    color = "default",
    delay = 0,
}: StatCardProps) {
    const { border, glow } = colorMap[color];
    const [visible, setVisible] = useState(false);
    const prevValue = useRef(value);

    useEffect(() => {
        const timer = setTimeout(() => setVisible(true), delay * 100);
        return () => clearTimeout(timer);
    }, [delay]);

    useEffect(() => {
        prevValue.current = value;
    }, [value]);

    const trendArrow = trend === "up" ? "↑" : trend === "down" ? "↓" : "";
    const trendColor =
        trend === "up"
            ? "text-[var(--green)]"
            : trend === "down"
                ? "text-[var(--red)]"
                : "";

    return (
        <div
            className={`glass-card p-4 relative transition-all duration-500 ${visible ? "opacity-100 translate-y-0" : "opacity-0 translate-y-4"
                }`}
            style={{
                borderColor: border,
                boxShadow: `0 0 25px ${glow}`,
            }}
        >
            <div className="relative z-10">
                <div className="flex items-center justify-between mb-2">
                    <span className="text-xs text-[var(--text-secondary)] uppercase tracking-wider font-medium">
                        {title}
                    </span>
                    {icon && (
                        <span className="text-[var(--text-dim)] opacity-60">{icon}</span>
                    )}
                </div>
                <div className={`text-xl font-bold font-mono tracking-tight ${trendColor}`}>
                    <span className="count-up">
                        {prefix}{typeof value === 'number' ? value.toLocaleString() : value}{suffix}
                    </span>
                    {trendArrow && (
                        <span className="ml-1.5 text-sm">{trendArrow}</span>
                    )}
                </div>
            </div>
        </div>
    );
}
