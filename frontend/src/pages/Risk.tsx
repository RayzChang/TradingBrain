import { useEffect, useState } from "react";
import { riskApi } from "../api";

type Params = Record<string, unknown>;
type Presets = Record<string, { label?: string; [k: string]: unknown }>;

export default function Risk() {
  const [params, setParams] = useState<Params | null>(null);
  const [presets, setPresets] = useState<Presets>({});
  const [activePreset, setActivePreset] = useState<string | null>(null);
  const [err, setErr] = useState("");
  const [saving, setSaving] = useState<string | null>(null);

  const load = () => {
    setErr("");
    Promise.all([riskApi.getParams(), riskApi.getPresets()])
      .then(([p, pr]) => {
        setParams(p);
        setPresets(pr.presets as Presets);
        setActivePreset(pr.active_preset);
      })
      .catch((e) => setErr(String(e)));
  };

  useEffect(load, []);

  const setParam = async (name: string, value: unknown) => {
    setSaving(name);
    try {
      await riskApi.setParam(name, value);
      setParams((prev) => (prev ? { ...prev, [name]: value } : null));
    } catch (e) {
      setErr(String(e));
    } finally {
      setSaving(null);
    }
  };

  const loadPreset = async (preset: string) => {
    setErr("");
    try {
      await riskApi.loadPreset(preset);
      setActivePreset(preset);
      load();
    } catch (e) {
      setErr(String(e));
    }
  };

  if (err && !params) return <p className="text-[var(--red)]">無法載入：{err}</p>;
  if (!params) return <p className="text-[var(--muted)]">載入中…</p>;

  const keyOrder = [
    "max_risk_per_trade",
    "min_notional_value",
    "max_leverage",
    "stop_loss_atr_mult",
    "take_profit_atr_mult",
    "min_risk_reward",
    "max_daily_loss",
    "max_drawdown",
    "max_consecutive_losses",
    "cool_down_after_loss_sec",
  ];
  const labels: Record<string, string> = {
    max_risk_per_trade: "每筆風險%",
    min_notional_value: "最小下單額 (USDT)",
    max_leverage: "最大槓桿",
    stop_loss_atr_mult: "止損 ATR 倍數",
    take_profit_atr_mult: "止盈 ATR 倍數",
    min_risk_reward: "最低風報比",
    max_daily_loss: "每日虧損上限%",
    max_drawdown: "最大回撤%",
    max_consecutive_losses: "連虧冷卻筆數",
    cool_down_after_loss_sec: "冷卻秒數",
  };

  return (
    <div>
      <h2 className="text-xl font-bold mb-6">風控參數</h2>
      {err && <p className="text-[var(--red)] mb-4">{err}</p>}

      <div className="mb-6 flex gap-2 flex-wrap">
        {(["conservative", "moderate", "aggressive"] as const).map((preset) => (
          <button
            key={preset}
            onClick={() => loadPreset(preset)}
            className={`px-4 py-2 rounded border ${
              activePreset === preset
                ? "bg-[var(--accent)] border-[var(--accent)] text-white"
                : "border-[var(--border)] hover:bg-[var(--card)]"
            }`}
          >
            {presets[preset]?.label || preset}
          </button>
        ))}
      </div>

      <div className="space-y-4 max-w-2xl">
        {keyOrder.filter((k) => params[k] !== undefined).map((key) => (
          <div key={key} className="flex items-center justify-between gap-4 p-3 rounded bg-[var(--card)] border border-[var(--border)]">
            <label className="text-sm">{labels[key] || key}</label>
            {typeof params[key] === "number" ? (
              <input
                type="number"
                step={key.includes("mult") || key.includes("reward") ? 0.1 : key.includes("_sec") ? 1 : 0.01}
                value={params[key] as number}
                onChange={(e) => setParam(key, e.target.value.includes(".") ? parseFloat(e.target.value) : parseInt(e.target.value, 10))}
                disabled={saving === key}
                className="w-28 px-2 py-1 rounded bg-[var(--bg)] border border-[var(--border)] text-right"
              />
            ) : (
              <span className="text-[var(--muted)]">{String(params[key])}</span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
