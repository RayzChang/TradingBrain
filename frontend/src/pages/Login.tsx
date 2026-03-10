import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { setAuth } from "../api";

export default function Login() {
  const [user, setUser] = useState(localStorage.getItem("tb_username") || "admin");
  const [pass, setPass] = useState(localStorage.getItem("tb_password") || "");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const nav = useNavigate();

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    setBusy(true);
    setAuth(user.trim(), pass);
    const authHeader = "Basic " + btoa(`${user.trim()}:${pass}`);

    try {
      const response = await fetch("/api/system/status", {
        headers: { Authorization: authHeader },
      });
      if (!response.ok) {
        throw new Error("Unauthorized");
      }
      nav("/");
    } catch {
      setErr("Login failed. Check your dashboard username and password.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-[var(--bg)] px-4">
      <form onSubmit={submit} className="w-full max-w-sm rounded-lg border border-[var(--border)] bg-[var(--card)] p-6">
        <h2 className="mb-2 text-xl font-bold text-[var(--accent)]">TradingBrain Login</h2>
        <p className="mb-4 text-sm text-[var(--muted)]">Use the dashboard credentials from your <code>.env</code> file.</p>
        <input
          type="text"
          value={user}
          onChange={(e) => setUser(e.target.value)}
          placeholder="Dashboard username"
          autoComplete="username"
          className="mb-3 w-full rounded border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-[var(--text)]"
        />
        <input
          type="password"
          value={pass}
          onChange={(e) => setPass(e.target.value)}
          placeholder="Dashboard password"
          autoComplete="current-password"
          className="mb-4 w-full rounded border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-[var(--text)]"
        />
        {err && <p className="mb-2 text-sm text-[var(--red)]">{err}</p>}
        <button
          type="submit"
          disabled={busy || !user.trim() || !pass}
          className="w-full rounded bg-[var(--accent)] py-2 font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
        >
          {busy ? "Signing in..." : "Sign in"}
        </button>
      </form>
    </div>
  );
}
