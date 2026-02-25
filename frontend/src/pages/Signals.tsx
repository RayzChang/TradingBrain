import { useEffect, useState } from "react";
import { signalsApi } from "../api";

type Signal = {
  id: number;
  symbol: string;
  timeframe: string;
  signal_type: string;
  strength: number;
  strategy_name: string;
  was_vetoed: number;
  veto_reason: string | null;
  was_executed: number;
  created_at: string;
};

export default function Signals() {
  const [list, setList] = useState<Signal[]>([]);
  const [err, setErr] = useState("");

  useEffect(() => {
    signalsApi
      .list(80)
      .then(setList as (a: unknown) => void)
      .catch((e) => setErr(String(e)));
  }, []);

  if (err) return <p className="text-[var(--red)]">無法載入：{err}</p>;

  return (
    <div>
      <h2 className="text-xl font-bold mb-6">最近信號</h2>
      <div className="overflow-x-auto rounded-lg border border-[var(--border)]">
        <table className="w-full text-sm">
          <thead className="bg-[var(--card)]">
            <tr>
              <th className="text-left p-3">時間</th>
              <th className="text-left p-3">交易對</th>
              <th className="text-left p-3">週期</th>
              <th className="text-left p-3">方向</th>
              <th className="text-left p-3">策略</th>
              <th className="text-right p-3">強度</th>
              <th className="text-left p-3">否決</th>
              <th className="text-left p-3">執行</th>
            </tr>
          </thead>
          <tbody>
            {list.length === 0 && (
              <tr>
                <td colSpan={8} className="p-6 text-center text-[var(--muted)]">
                  尚無信號
                </td>
              </tr>
            )}
            {list.map((s) => (
              <tr key={s.id} className="border-t border-[var(--border)]">
                <td className="p-3 text-[var(--muted)]">{s.created_at?.slice(0, 19)}</td>
                <td className="p-3">{s.symbol}</td>
                <td className="p-3">{s.timeframe}</td>
                <td className={`p-3 font-medium ${s.signal_type === "LONG" ? "text-[var(--green)]" : "text-[var(--red)]"}`}>
                  {s.signal_type}
                </td>
                <td className="p-3">{s.strategy_name}</td>
                <td className="p-3 text-right">{typeof s.strength === "number" ? s.strength.toFixed(2) : "-"}</td>
                <td className="p-3">
                  {s.was_vetoed ? <span className="text-[var(--red)]">是 {s.veto_reason || ""}</span> : <span className="text-[var(--green)]">否</span>}
                </td>
                <td className="p-3">{s.was_executed ? "是" : "否"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
