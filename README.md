# QuantEdge — Personal Quantitative Trading Dashboard

A full-stack trading dashboard combining live P&L tracking, a rule-based
screener, and an AI-powered analysis pipeline via the Anthropic Claude API.

Built as a personal project to track a real trade history and explore how
market data APIs and LLMs can be combined for investment research — not a
production trading system.

## Features

- **Trading** — live P&L tracking on a real personal trade history, equity
  curve, per-trade breakdown, sector allocation
- **DCA** — long-term ETF portfolio tracker reading directly from Excel, with
  30-year Monte Carlo-style projections across 3 scenarios and an AI
  portfolio review
- **AI Analysis** — two modes: *Build & Send* (template-based or free-form
  prompts sent to Claude) and *Ticker Deep Dive* (automatic market data
  injection — price, drawdown, fundamentals — into a structured trade note)
- **News** — rolling macro calendar (central banks, CPI/NFP, OPEC+, earnings)
  with market-moving event highlights

## Architecture — why two data sources

The project uses **two different market data providers**, each for what it
does well on the plan actually subscribed to:

| Data | Source | Why |
|---|---|---|
| Prices, historical OHLCV, drawdown | **EODHD** | Reliable EOD/real-time-delayed price data on the base "All-World" plan |
| Fundamentals (P/E, EV/EBITDA, revenue, sector, short interest) | **yfinance** | EODHD's `fundamentals` endpoint requires a separate, more expensive plan; yfinance provides the same data for free |

Both are abstracted behind a single module (`utils/market_data.py`), so the
rest of the codebase (screener, AI analysis, portfolio) never calls a
provider directly — it calls one consistent interface. This was a deliberate
trade-off: rather than paying for a bundled plan that includes premium
endpoints (Screener API, dedicated Fundamentals Feed) mostly unused outside
one feature, the project combines a paid plan with a free source where their
strengths overlap.

**Known limitation:** this means fundamentals and prices can come from
slightly different snapshots in time. For a personal research tool this is
an acceptable trade-off; it would not be for a production system.

## Stack

Python 3.8 · Streamlit · EODHD API · yfinance · Anthropic Claude API ·
SQLite · Plotly · openpyxl

## Setup

```bash
git clone https://github.com/anthony-giacomoni/quantedge.git
cd quantedge
pip install -r requirements.txt
```

Create a `.env` file at the project root (never committed — see
`.gitignore`):

```
ANTHROPIC_API_KEY=your_key_here
EODHD_API_KEY=your_key_here
```

Then run:

```bash
streamlit run app.py
```

See `DEMARRAGE.md` for a more detailed step-by-step guide (in French).

## Project structure

```
quantedge/
├── app.py                  # Streamlit entry point
├── config.py
├── refresh_universe.py     # Optional: builds a local ticker cache for wider screening
├── modules/
│   ├── portfolio.py         # P&L, equity curve, stats
│   ├── ai_analysis.py       # Claude API integration
│   ├── alerts.py            # Macro/earnings calendar data
│   ├── prompt_builder.py    # Institutional prompt templates
│   ├── dca.py                # Long-term ETF tracker (reads Excel)
│   └── screener.py          # Rule-based scoring engine
├── utils/
│   ├── db.py                 # SQLite helpers
│   ├── market_data.py        # Single abstraction over EODHD + yfinance
│   ├── eodhd.py               # EODHD API wrapper
│   └── seed_trades.py
└── assets/
    └── style.css
```

## Trade record

27 real trades tracked since January 2025 — 96% win rate on closed positions,
profit factor 24x, average holding period 12.6 days, across energy,
semiconductors, defence and healthcare sectors.

## Disclaimer

Personal project for portfolio/learning purposes. Not investment advice, not
a production trading system, and not audited for correctness beyond the
author's own use.
