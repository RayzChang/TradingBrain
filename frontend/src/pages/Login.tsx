import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { setAuth } from "../api";

export default function Login() {
  const [user, setUser] = useState(localStorage.getItem("tb_username") || "admin");
  const [pass, setPass] = useState(localStorage.getItem("tb_password") || "changeme");
  const [err, setErr] = useState("");
  const nav = useNavigate();

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    setAuth(user, pass);
    const authHeader = "Basic " + btoa(`${user}:${pass}`);
    fetch("/api/system/status", { headers: { Authorization: authHeader } })
      .then((r) => (r.ok ? nav("/") : Promise.reject(new Error("Unauthorized"))))
      .catch(() => {
        setErr("登入失敗，請檢查帳密（預設 admin / changeme）");
      });
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-[var(--bg)]">
      <form onSubmit={submit} className="w-80 p-6 rounded-lg bg-[var(--card)] border border-[var(--border)]">
        <h2 className="text-xl font-bold mb-4 text-[var(--accent)]">TradingBrain 登入</h2>
        <input
          type="text"
          value={user}
          onChange={(e) => setUser(e.target.value)}
          placeholder="使用者名稱"
          className="w-full mb-3 px-3 py-2 rounded bg-[var(--bg)] border border-[var(--border)] text-[var(--text)]"
        />
        <input
          type="password"
          value={pass}
          onChange={(e) => setPass(e.target.value)}
          placeholder="密碼"
          className="w-full mb-4 px-3 py-2 rounded bg-[var(--bg)] border border-[var(--border)] text-[var(--text)]"
        />
        {err && <p className="text-[var(--red)] text-sm mb-2">{err}</p>}
        <button type="submit" className="w-full py-2 rounded bg-[var(--accent)] text-white font-semibold">
          登入
        </button>
      </form>
    </div>
  );
}
