import { Routes, Route, Navigate } from "react-router-dom";
import Sidebar from "./components/Sidebar";
import Dashboard from "./pages/Dashboard";
import Risk from "./pages/Risk";
import Signals from "./pages/Signals";
import Trades from "./pages/Trades";
import Login from "./pages/Login";
import MarketPage from "./pages/Market";
import ScreenerPage from "./pages/Screener";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/*" element={<AppLayout />} />
    </Routes>
  );
}

function AppLayout() {
  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <main className="flex-1 p-6 overflow-y-auto">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/market" element={<MarketPage />} />
          <Route path="/screener" element={<ScreenerPage />} />
          <Route path="/risk" element={<Risk />} />
          <Route path="/signals" element={<Signals />} />
          <Route path="/trades" element={<Trades />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}
