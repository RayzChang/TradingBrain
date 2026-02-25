import { Routes, Route, Navigate, Link, useLocation } from "react-router-dom";
import Dashboard from "./pages/Dashboard";
import Risk from "./pages/Risk";
import Signals from "./pages/Signals";
import Trades from "./pages/Trades";
import Login from "./pages/Login";

function Layout({ children }: { children: React.ReactNode }) {
  const loc = useLocation();
  const nav = [
    { to: "/", label: "總覽" },
    { to: "/risk", label: "風控參數" },
    { to: "/signals", label: "信號" },
    { to: "/trades", label: "交易" },
  ];
  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-[var(--border)] bg-[var(--card)] px-6 py-3 flex items-center justify-between">
        <h1 className="text-lg font-bold text-[var(--accent)]">TradingBrain</h1>
        <nav className="flex gap-4">
          {nav.map(({ to, label }) => (
            <Link
              key={to}
              to={to}
              className={
                loc.pathname === to
                  ? "text-[var(--accent)] font-semibold"
                  : "text-[var(--muted)] hover:text-[var(--text)]"
              }
            >
              {label}
            </Link>
          ))}
        </nav>
      </header>
      <main className="flex-1 p-6">{children}</main>
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/"
        element={
          <Layout>
            <Dashboard />
          </Layout>
        }
      />
      <Route
        path="/risk"
        element={
          <Layout>
            <Risk />
          </Layout>
        }
      />
      <Route
        path="/signals"
        element={
          <Layout>
            <Signals />
          </Layout>
        }
      />
      <Route
        path="/trades"
        element={
          <Layout>
            <Trades />
          </Layout>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
