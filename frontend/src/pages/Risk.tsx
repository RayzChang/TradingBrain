import { useEffect, useMemo, useState } from "react";

import { riskApi } from "../api";

type Params = Record<string, unknown>;
type PresetConfig = { label?: string; [k: string]: unknown };
type Presets = Record<string, PresetConfig>;

const presetOrder = ["conservative", "moderate", "passive_income", "aggressive", "training"];

const fieldLabels: Record<string, string> = {
  max_risk_per_trade: "單筆基準風險",
  min_notional_value: "最小名義倉位 (USDT)",
  max_open_positions: "最大同時持倉",
  max_leverage: "最大槓桿上限",
  dynamic_leverage: "動態槓桿",
  stop_loss_atr_mult: "ATR 止損倍數",
  take_profit_atr_mult: "ATR 止盈倍數",
  tp1_atr_mult: "TP1 ATR 倍數",
  tp2_atr_mult: "TP2 ATR 倍數",
  min_risk_reward: "最低風報比",
  max_daily_loss: "單日最大虧損",
  max_drawdown: "最大回撤",
  max_consecutive_losses: "最大連虧筆數",
  cool_down_after_loss_sec: "虧損後冷卻秒數",
  daily_profit_target: "單日目標收益",
};

function formatValue(value: unknown): string {
  if (typeof value === "boolean") {
    return value ? "Enabled" : "Disabled";
  }
  if (typeof value === "number") {
    return Number.isInteger(value) ? String(value) : String(value);
  }
  return String(value);
}

function coerceDraft(currentValue: unknown, draft: string): unknown {
  if (typeof currentValue === "boolean") {
    return draft === "true";
  }
  if (typeof currentValue === "number") {
    const parsed = draft.includes(".") ? parseFloat(draft) : parseInt(draft, 10);
    return Number.isNaN(parsed) ? currentValue : parsed;
  }
  const trimmed = draft.trim();
  if (trimmed === "") {
    return currentValue;
  }
  if (trimmed !== "auto" && !Number.isNaN(Number(trimmed))) {
    return trimmed.includes(".") ? parseFloat(trimmed) : parseInt(trimmed, 10);
  }
  return trimmed;
}

export default function Risk() {
  const [params, setParams] = useState<Params | null>(null);
  const [presets, setPresets] = useState<Presets>({});
  const [activePreset, setActivePreset] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [err, setErr] = useState("");
  const [saving, setSaving] = useState<string | null>(null);

  const load = () => {
    setErr("");
    Promise.all([riskApi.getParams(), riskApi.getPresets()])
      .then(([p, pr]) => {
        setParams(p);
        setPresets(pr.presets as Presets);
        setActivePreset((p.active_preset as string) ?? pr.active_preset ?? null);
        setDrafts(
          Object.fromEntries(
            Object.entries(p).map(([key, value]) => [key, formatValue(value)])
          )
        );
      })
      .catch((e) => setErr(String(e)));
  };

  useEffect(load, []);

  const orderedPresetKeys = useMemo(
    () => Array.from(new Set([...presetOrder, ...Object.keys(presets)])),
    [presets]
  );

  const editableKeys = [
    "max_risk_per_trade",
    "min_notional_value",
    "max_open_positions",
    "max_leverage",
    "stop_loss_atr_mult",
    "take_profit_atr_mult",
    "tp1_atr_mult",
    "tp2_atr_mult",
    "min_risk_reward",
    "max_daily_loss",
    "max_drawdown",
    "max_consecutive_losses",
    "cool_down_after_loss_sec",
    "daily_profit_target",
  ];

  const saveDraft = async (name: string) => {
    if (!params) {
      return;
    }
    const currentValue = params[name];
    const nextValue = coerceDraft(currentValue, drafts[name] ?? formatValue(currentValue));
    if (nextValue === currentValue) {
      return;
    }

    setSaving(name);
    try {
      await riskApi.setParam(name, nextValue);
      setParams((prev) => (prev ? { ...prev, [name]: nextValue } : null));
      setDrafts((prev) => ({ ...prev, [name]: formatValue(nextValue) }));
      if (name === "active_preset" && typeof nextValue === "string") {
        setActivePreset(nextValue);
      }
    } catch (e) {
      setErr(String(e));
      setDrafts((prev) => ({ ...prev, [name]: formatValue(currentValue) }));
    } finally {
      setSaving(null);
    }
  };

  const loadPreset = async (preset: string) => {
    setErr("");
    try {
      await riskApi.loadPreset(preset);
      load();
    } catch (e) {
      setErr(String(e));
    }
  };

  if (err && !params) {
    return <p className="text-[var(--red)]">Risk page load failed: {err}</p>;
  }

  if (!params) {
    return <p className="text-[var(--muted)]">Loading risk settings...</p>;
  }

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold">Risk Control</h2>
          <p className="text-sm text-[var(--muted)]">
            這裡顯示目前真正生效的 preset 與風控參數，不再只保留舊版三個預設。
          </p>
        </div>
        <div className="rounded border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-sm">
          Active preset: <span className="font-semibold text-[var(--accent)]">{activePreset ?? "unknown"}</span>
        </div>
      </div>

      {err && <p className="mb-4 text-[var(--red)]">{err}</p>}

      <div className="mb-6 flex flex-wrap gap-2">
        {orderedPresetKeys
          .filter((preset) => presets[preset])
          .map((preset) => (
            <button
              key={preset}
              onClick={() => loadPreset(preset)}
              className={`rounded border px-4 py-2 text-left ${
                activePreset === preset
                  ? "border-[var(--accent)] bg-[var(--accent)] text-white"
                  : "border-[var(--border)] hover:bg-[var(--card)]"
              }`}
            >
              <div className="text-sm font-semibold">{presets[preset]?.label || preset}</div>
              <div className="text-xs opacity-80">{preset}</div>
            </button>
          ))}
      </div>

      <div className="space-y-4 max-w-3xl">
        {editableKeys.filter((key) => params[key] !== undefined).map((key) => {
          const value = params[key];
          const isBoolean = typeof value === "boolean";
          const step =
            key.includes("mult") || key.includes("reward") || key.includes("risk") || key.includes("drawdown")
              ? 0.1
              : key.includes("sec") || key.includes("positions")
                ? 1
                : 0.01;

          return (
            <div key={key} className="flex items-center justify-between gap-4 rounded border border-[var(--border)] bg-[var(--card)] p-3">
              <div>
                <label className="text-sm font-medium">{fieldLabels[key] || key}</label>
                <div className="text-xs text-[var(--muted)]">{key}</div>
              </div>
              {isBoolean ? (
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={Boolean(value)}
                    onChange={(e) => {
                      const checked = e.target.checked;
                      setDrafts((prev) => ({ ...prev, [key]: String(checked) }));
                      void (async () => {
                        setSaving(key);
                        try {
                          await riskApi.setParam(key, checked);
                          setParams((prev) => (prev ? { ...prev, [key]: checked } : null));
                        } catch (error) {
                          setErr(String(error));
                        } finally {
                          setSaving(null);
                        }
                      })();
                    }}
                    disabled={saving === key}
                  />
                  {Boolean(value) ? "Enabled" : "Disabled"}
                </label>
              ) : (
                <input
                  type="text"
                  value={drafts[key] ?? formatValue(value)}
                  onChange={(e) => setDrafts((prev) => ({ ...prev, [key]: e.target.value }))}
                  onBlur={() => {
                    void saveDraft(key);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      void saveDraft(key);
                    }
                  }}
                  disabled={saving === key}
                  step={step}
                  className="w-32 rounded border border-[var(--border)] bg-[var(--bg)] px-2 py-1 text-right"
                />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
