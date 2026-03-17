# TradingBrain V6

TradingBrain V6 is a Binance Futures trading system for demo/testnet research. It combines a Python backend, FastAPI dashboard, React frontend, Telegram notifications, SQLite logging, and a phased strategy/risk framework focused on replayable analysis rather than black-box execution.

## Current State

- Runtime mode: testnet/demo-first
- Strategy stack:
  - `trend_following`
  - `breakout_retest`
  - `mean_reversion`
- Market model:
  - `4h` trend direction
  - `1h` direction filter
  - `15m` setup generation
  - `1m` entry trigger / breakout retest confirm
- Notifications: Telegram
- Research logging: enabled
- Progress tracker: [`PROGRESS.md`](./PROGRESS.md)

## What's New In V6

- Completed the six-phase refactor plan tracked in [`PROGRESS.md`](./PROGRESS.md)
- Added stricter multi-timeframe hard gates
- Rebuilt breakout entries around retest confirmation
- Split exit templates by strategy family
- Added strategy-weighted position sizing
- Added structure-stop ATR floor protection
- Added correlation blocking for BTC / ETH same-direction exposure
- Expanded daily and per-signal research logging for later review

## Strategy Overview

### 1. Trend Following

- Runs only in `TRENDING` regime
- Uses EMA structure, ADX/DI context, RSI, MACD, and entry quality filters
- Now blocks late trend entries that are too extended near Bollinger extremes

### 2. Breakout Retest

- Detects a valid `15m` breakout setup
- Queues a pending breakout instead of entering immediately
- Waits for `1m` retest confirmation
- Uses a wider breakout breathing room and breakout-specific exit profile

### 3. Mean Reversion

- Runs only in `RANGING` regime
- Uses RSI / Bollinger context with reversal confirmation
- Uses a shorter exit profile with faster partial profit-taking

## Risk Model

- Strategy-specific exit templates
- Structure-first stop placement with ATR floor protection
- Strategy-weighted risk sizing:
  - `breakout / breakout_retest = 1.0`
  - `trend_following = 0.8`
  - `mean_reversion = 0.7`
- Signal strength multiplier with cap
- Simplified correlation protection:
  - blocks same-direction `BTCUSDT` + `ETHUSDT`

## Notifications And Reporting

- Startup, trade, TP/SL, hourly summaries, and daily reports go to Telegram
- Daily reports are written to:
  - `logs/daily_reports`
- Agent research reports are written to:
  - `logs/daily_reports/agent_reports`

## Project Structure

- [`main.py`](./main.py): runtime orchestration
- [`core/analysis`](./core/analysis): indicators, MTF analysis
- [`core/strategy`](./core/strategy): strategy logic and signal aggregation
- [`core/risk`](./core/risk): sizing, stop logic, exit profiles
- [`core/execution`](./core/execution): Binance client and position management
- [`api`](./api): FastAPI routes
- [`frontend`](./frontend): React + Vite dashboard
- [`database`](./database): SQLite models and DB helpers
- [`notifications`](./notifications): Telegram notification layer
- [`scripts`](./scripts): validation and support scripts

## Quick Start

### Backend

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

### Frontend

```bash
cd frontend
npm install
npm run build
```

### Launcher

```bash
python launcher.py
```

## Key URLs

- Dashboard API: `http://localhost:8888`
- Launcher UI: `http://localhost:8899`

## Validation

Recent project-wide validation target:

```bash
python -m pytest -q
```

## Notes

- This repo is optimized for demo/testnet iteration first.
- Real-money usage should only happen after extended validation.
- Runtime logs and databases are intentionally excluded from version control.
