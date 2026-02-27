const API_BASE = "/api";

function getAuth(): string {
  const u = localStorage.getItem("tb_username") || "admin";
  const p = localStorage.getItem("tb_password") || "changeme";
  return btoa(`${u}:${p}`);
}

export async function api<T>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      Authorization: `Basic ${getAuth()}`,
      "Content-Type": "application/json",
      ...options?.headers,
    },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || String(res.status));
  }
  return res.json();
}

export function setAuth(username: string, password: string) {
  localStorage.setItem("tb_username", username);
  localStorage.setItem("tb_password", password);
}

export const riskApi = {
  getParams: () => api<Record<string, unknown>>("/risk"),
  getPresets: () => api<{ presets: Record<string, unknown>; active_preset: string | null }>("/risk/presets"),
  setParam: (name: string, value: unknown) =>
    api("/risk/" + name, { method: "PUT", body: JSON.stringify({ value, changed_by: "dashboard" }) }),
  loadPreset: (preset: string) =>
    api("/risk/load-preset", { method: "POST", body: JSON.stringify({ preset }) }),
};

export const signalsApi = {
  list: (limit = 50) => api<unknown[]>("/signals?limit=" + limit),
};

export const tradesApi = {
  open: () => api<unknown[]>("/trades/open"),
  openWithPnl: () =>
    api<{ open_trades: unknown[]; total_unrealized_pnl: number }>("/trades/open-with-pnl"),
  today: () => api<unknown[]>("/trades/today"),
  dailyPnl: () => api<{ daily_pnl: number }>("/trades/daily-pnl"),
  recent: (limit = 20) => api<unknown[]>("/trades/recent?limit=" + limit),
};

export const systemApi = {
  status: () =>
    api<{
      mode: string;
      initial_balance: number;
      total_realized_pnl: number;
      daily_pnl: number;
      open_positions_count: number;
      exchange_balance?: number;
      last_updated?: string;
    }>("/system/status"),
};
