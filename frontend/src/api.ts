const API_BASE = "/api";

function getAuth(): string {
  const username = localStorage.getItem("tb_username") || "";
  const password = localStorage.getItem("tb_password") || "";
  return btoa(`${username}:${password}`);
}

export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const headers = new Headers(options?.headers);
  headers.set("Authorization", `Basic ${getAuth()}`);
  if (!headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
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

export function clearAuth() {
  localStorage.removeItem("tb_username");
  localStorage.removeItem("tb_password");
}

export const riskApi = {
  getParams: () => api<Record<string, unknown>>("/risk"),
  getPresets: () =>
    api<{ presets: Record<string, unknown>; active_preset: string | null }>("/risk/presets"),
  setParam: (name: string, value: unknown) =>
    api("/risk/" + name, { method: "PUT", body: JSON.stringify({ value, changed_by: "dashboard" }) }),
  loadPreset: (preset: string) => api("/risk/load-preset", { method: "POST", body: JSON.stringify({ preset }) }),
};

export const signalsApi = {
  list: (limit = 50) => api<unknown[]>("/signals?limit=" + limit),
};

export const tradesApi = {
  open: () => api<unknown[]>("/trades/open"),
  openWithPnl: () => api<{ open_trades: unknown[]; total_unrealized_pnl: number }>("/trades/open-with-pnl"),
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
      exchange_balance?: number | null;
      last_updated?: string;
    }>("/system/status"),
};

export const klinesApi = {
  get: (symbol: string, timeframe: string, limit = 300) =>
    api<{
      symbol: string;
      timeframe: string;
      klines: Array<{ time: number; open: number; high: number; low: number; close: number; volume: number }>;
      error?: string;
    }>(`/klines/${symbol}/${timeframe}?limit=${limit}`),
  tradeMarkers: (symbol: string) =>
    api<{
      symbol: string;
      markers: Array<{
        time: string;
        position: string;
        color: string;
        shape: string;
        text: string;
        type: string;
        price?: number;
      }>;
    }>(`/klines/${symbol}/trade-markers`),
};
