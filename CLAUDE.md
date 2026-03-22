# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

TradingBrain V9 is a Binance Futures automated trading system (testnet/research-focused). It consists of a Python backend (trading engine + FastAPI), a React/TypeScript frontend dashboard, Telegram notifications, and structure-first trade management with soft/hard stops.

## Commands

### Backend
```bash
python main.py              # Start trading engine (port 8888)
python launcher.py          # Start control panel UI (port 8899)
python -m pytest -q         # Run all tests
python -m pytest tests/test_risk.py -q   # Run specific test file
```

### Frontend
```bash
cd frontend
npm run dev     # Dev server on port 5173 (proxies /api → port 8888)
npm run build   # tsc -b && vite build
npm run preview # Preview production build
```

### Database & Config
- SQLite DB: `data/trading_brain.db`
- Env config: `.env` (copy from `.env.example`)
- Risk params: `config/risk_defaults.json`
- Main settings: `config/settings.py` (API endpoints, dashboard auth, trading mode, watchlist)

## Architecture

### Signal Flow
```
WebSocket Kline Feed (core/data/)
  → Technical Analysis (core/analysis/)
  → Multi-Timeframe Gate: 4h → 1h → 15m → 1m
  → Strategy Stack (core/strategy/)
  → Veto Engine (core/pipeline/)
  → Risk Manager + Position Sizing (core/risk/)
  → Binance Execution (core/execution/)
  → Telegram Notifications + SQLite Logging
  → FastAPI Dashboard (api/)
```

### Multi-Timeframe (MTF) Logic
- **4h**: Regime classification — `TRENDING` / `RANGING` / `VOLATILE` using ADX, DI±, BB width, ATR ratio, CHOP
- **1h**: Direction filter (must align with 4h)
- **15m**: Setup detection (primary strategy signal)
- **1m**: Entry trigger confirmation

Hard gates at 4h/1h block invalid setups before 15m analysis runs.

### Three-Strategy Stack (`core/strategy/`)
1. **Trend Following** (`trend_following.py`) — EMA structure, ADX/DI, RSI, MACD; risk weight 0.8
2. **Breakout Retest** (`breakout_retest.py`) — Detects level breaks, waits for 1m retest (0.35% tolerance, 3-bar expiry); risk weight 1.0
3. **Mean Reversion** (`mean_reversion.py`) — RSI/Bollinger in ranging markets, quick exits; risk weight 0.7

### Breakout Retest State Machine (in `main.py`)
`BREAKOUT_PENDING` → `BREAKOUT_RETEST_HIT` → `BREAKOUT_CONFIRMED` (or expires after 3 bars)

Managed via `pending_entry` dict in the main orchestration loop.

### Risk Layer (`core/risk/`) — V9 Fixed-Margin Model
- **V9**: Fixed-margin position sizing ($200-600 per trade, scaled by coin max leverage tier)
- **V9**: Strategy-level leverage caps — Trend 20x / Breakout 25x / Mean Reversion 15x (overrides coin max)
- **V9**: C-tier signal rejection — signal strength < 0.5 auto-rejected, no junk trades
- **V9**: Fee-aware dynamic TP floor — TP minimums guarantee coverage of 2.5x round-trip fees
- **V9**: Mean reversion min risk-reward raised to 1.5 (from 1.0)
- Per-coin max leverage from Binance API (BTC 125x, ETH 100x, ATOM 20x, etc.)
- Full account balance as collateral (CROSSED mode, no balance division)
- Dynamic stop-loss observation mode (wick detection vs confirmed breakdown)
- Structure-first stop placement with ATR floor protection
- Correlation blocking (e.g., BTC LONG + ETH LONG cannot coexist)
- Regime hysteresis: 3+ bars minimum between regime switches
- Exit profiles differ per strategy — Breakout: `tp1=1.5 ATR / tp2=3.0 ATR / tp3=4.5 ATR`; Trend and Mean Reversion have separate configs

### Backend Directory Map
| Path | Purpose |
|------|---------|
| `main.py` | Trading engine orchestration, WebSocket feed, pending entry state |
| `launcher.py` | Control panel launcher (port 8899) |
| `api/app.py` | FastAPI app, HTTP Basic auth, routes for risk/signals/trades/system/backtest/klines |
| `config/settings.py` | All tuneable parameters (intervals, watchlist, leverage, DB path) |
| `core/analysis/` | Technical indicators: EMA, ATR, RSI, MACD, BB, CHOP, Divergence, Fibonacci, MTF |
| `core/strategy/` | Signal generation + base classes + aggregation |
| `core/execution/` | Binance client, order placement, position sync |
| `core/risk/` | Position sizing, stop logic, exit profiles, structure levels, risk manager |
| `core/pipeline/` | Scheduler, veto engine, funding rate/liquidation/fear-greed monitors |
| `core/data/` | WebSocket feed, market data fetcher, data storage |
| `core/brain/` | State management and manual overrides |
| `database/` | SQLite models (analysis logs, trades, regime observations) |
| `notifications/` | Telegram notification layer |
| `tests/` | Pytest suite (12 files, ~70 tests) |

### Frontend Directory Map
| Path | Purpose |
|------|---------|
| `frontend/src/App.tsx` | Router: `/`, `/login`, `/market`, `/screener`, `/risk`, `/signals`, `/trades` |
| `frontend/src/api.ts` | HTTP client with HTTP Basic auth header injection |
| `frontend/src/pages/` | Dashboard, Risk, Signals, Trades, Market, Screener, Login |
| `frontend/src/components/` | DecisionPipeline, KlineChart, Sidebar, StatCard |

Frontend uses Tailwind CSS for styling, Lightweight Charts for OHLC candles, Lucide for icons. Auth credentials stored in `localStorage`.

### Research Logging
The system records `REGIME_OBSERVATION` entries at each 15m analysis cycle, capturing regime, MTF gate status, indicator values, and trade metadata (effective risk %, SL ATR mult, structure stop floor trigger). This is intentional — used for backtesting and strategy tuning via `scripts/`.
