# ============================================================
#  QuantEdge — Module Portfolio
#  Calculs P&L, statistiques, cumulative realised P&L
# ============================================================

import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import sys, os
import math

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.db import load_trades
from utils.market_data import (
    get_quote, get_fx_quote_to_eur, ticker_currency, ticker_market_zone,
)


# ── Couleurs du dashboard ─────────────────────────────────────
COLOR_WIN    = "#22c55e"   # vert
COLOR_LOSS   = "#ef4444"   # rouge
COLOR_OPEN   = "#f59e0b"   # amber — positions ouvertes
COLOR_BG     = "rgba(0,0,0,0)"  # transparent
COLOR_GRID   = "rgba(128,128,128,0.15)"

# Quote currency is resolved centrally in utils.market_data.


# ── Chargement & enrichissement ───────────────────────────────

def load_enriched_trades(db_path: str = "data/quantedge.db") -> pd.DataFrame:
    """
    Load trades and mark open positions using the latest available quote.

    Quotes are obtained through the single market-data abstraction and carry
    source/timestamp/staleness metadata per ticker. In this personal dataset,
    recorded entry prices and invested amounts are broker base-currency (EUR)
    values. The current quote is therefore translated to EUR first, then compared
    with the recorded EUR entry price. This matches the source data semantics and
    avoids mixing a USD/GBP market quote with a EUR broker cost basis.
    """
    df = load_trades(db_path)
    if df.empty:
        return df

    df["entry_date"] = pd.to_datetime(df["entry_date"])
    df["exit_date"] = pd.to_datetime(df["exit_date"], errors="coerce")

    # Columns are intentionally explicit so the UI can report quote quality per
    # position instead of relying on one global "last ticker" stale flag.
    for col in [
        "current_price_native", "current_price", "quote_currency", "provider_reported_currency",
        "listing_currency_expected", "price_unit_normalization", "quote_source",
        "quote_timestamp", "quote_stale", "quote_error", "market_zone",
        "fx_to_eur", "fx_source", "fx_timestamp", "fx_stale", "fx_error",
        "fx_fallback_reason", "pricing_stale", "pricing_error",
        "entry_price_eur",
    ]:
        if col not in df.columns:
            df[col] = None

    fx_cache = {}

    def _finite(value):
        if value is None:
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    for idx, row in df[df["status"] == "OPEN"].iterrows():
        reference_ticker = str(row["ticker"]).strip()
        instrument_type = str(row.get("instrument_type") or "DIRECT").upper()
        marking_ticker = str(row.get("marking_ticker") or "").strip() or None
        if instrument_type == "WRAPPER" and not marking_ticker:
            df.at[idx, "pnl"] = None
            df.at[idx, "pricing_stale"] = True
            df.at[idx, "pricing_error"] = "wrapper/product cannot be live-marked from reference underlying alone"
            continue
        ticker = marking_ticker or reference_ticker
        quote = get_quote(ticker) or {}
        native_price = _finite(quote.get("price"))
        expected_currency = ticker_currency(ticker)
        provider_currency = (quote.get("provider_reported_currency") or "").upper() or None
        currency = expected_currency
        market_zone = ticker_market_zone(ticker)

        df.at[idx, "current_price_native"] = native_price
        df.at[idx, "quote_currency"] = currency
        df.at[idx, "provider_reported_currency"] = provider_currency
        df.at[idx, "listing_currency_expected"] = expected_currency
        df.at[idx, "price_unit_normalization"] = quote.get("price_unit_normalization")
        df.at[idx, "market_zone"] = market_zone
        df.at[idx, "quote_source"] = quote.get("source")
        df.at[idx, "quote_timestamp"] = quote.get("timestamp")
        df.at[idx, "quote_stale"] = bool(quote.get("stale", True))
        df.at[idx, "quote_error"] = quote.get("error")

        errors = []
        if expected_currency == "UNKNOWN" or market_zone == "UNKNOWN":
            errors.append(f"unsupported exchange suffix for {ticker}")
        if provider_currency and expected_currency not in {"UNKNOWN", provider_currency}:
            errors.append(f"currency mismatch: listing map={expected_currency}, provider={provider_currency}")
        if native_price is None or native_price <= 0:
            errors.append("latest quote unavailable/invalid")
        if bool(quote.get("stale", True)):
            errors.append("latest quote is stale")
        if quote.get("error"):
            errors.append(f"quote error: {quote.get('error')}")

        direction = str(row.get("direction") or "").upper()
        if direction not in {"LONG", "SHORT"}:
            errors.append(f"invalid direction {direction or 'missing'}")

        entry_price_raw = _finite(row.get("entry_price"))
        entry_price_eur = None
        if entry_price_raw is not None and entry_price_raw > 0:
            # QuantEdge's personal trade ledger stores the broker cost basis in
            # EUR, even when the underlying is quoted in USD/GBP/etc.
            entry_price_eur = entry_price_raw
            df.at[idx, "entry_price_eur"] = round(entry_price_eur, 6)
        else:
            errors.append("invalid EUR entry price")

        qty = _finite(row.get("qty"))
        if qty is None or qty <= 0:
            invested = _finite(row.get("invested"))
            if invested is not None and invested > 0 and entry_price_eur is not None and entry_price_eur > 0:
                qty = invested / entry_price_eur
            else:
                errors.append("invalid/missing quantity")

        if errors:
            df.at[idx, "current_price"] = None
            df.at[idx, "pnl"] = None
            df.at[idx, "pricing_stale"] = True
            df.at[idx, "pricing_error"] = "; ".join(errors)
            continue

        if currency not in fx_cache:
            fx_cache[currency] = get_fx_quote_to_eur(currency)
        fx_quote = fx_cache.get(currency) or {}
        fx_rate = _finite(fx_quote.get("rate"))
        df.at[idx, "fx_to_eur"] = fx_rate
        df.at[idx, "fx_source"] = fx_quote.get("source")
        df.at[idx, "fx_timestamp"] = fx_quote.get("timestamp")
        df.at[idx, "fx_stale"] = bool(fx_quote.get("stale", True))
        df.at[idx, "fx_error"] = fx_quote.get("error")
        df.at[idx, "fx_fallback_reason"] = fx_quote.get("fallback_reason")
        df.at[idx, "pricing_stale"] = bool(quote.get("stale", True) or fx_quote.get("stale", True))

        if fx_rate is None or fx_rate <= 0 or bool(fx_quote.get("stale", True)) or fx_quote.get("error"):
            df.at[idx, "current_price"] = None
            df.at[idx, "pnl"] = None
            df.at[idx, "pricing_stale"] = True
            reason = fx_quote.get("error") or (
                "stale FX mark"
                if fx_quote.get("stale", True)
                else "FX unavailable/invalid"
            )
            df.at[idx, "pricing_error"] = (
                f"FX {currency}->EUR unavailable for current P&L: {reason}"
            )
            continue

        price_eur = round(native_price * fx_rate, 4)
        df.at[idx, "current_price"] = price_eur
        if direction == "LONG":
            entry_notional = entry_price_eur * qty
            invested = _finite(row.get("invested"))
            if invested is not None and invested > 0:
                tolerance = max(5.0, entry_notional * 0.02)
                if abs(invested - entry_notional) > tolerance:
                    df.at[idx, "pnl"] = None
                    df.at[idx, "pricing_stale"] = True
                    df.at[idx, "pricing_error"] = "broker invested amount inconsistent with entry price × quantity"
                    continue
                cost_basis_eur = invested
            else:
                cost_basis_eur = entry_notional
            pnl_eur = price_eur * qty - cost_basis_eur
        else:
            pnl_eur = (entry_price_eur - price_eur) * qty
        df.at[idx, "pnl"] = round(pnl_eur, 2)
        df.at[idx, "qty"] = round(qty, 6)
        df.at[idx, "pricing_error"] = None

    return df


# ── Statistiques globales ─────────────────────────────────────

def compute_stats(df: pd.DataFrame) -> dict:
    """
    Compute statistics for the strategy-tagged dataset.
    """
    closed = df[df["status"] == "CLOSED"].copy()
    opened = df[df["status"] == "OPEN"].copy()

    # Open-position analytics remain meaningful even when a dataset has no
    # closed samples yet. Closed metrics become N/A rather than erasing the
    # open-position state entirely.

    # Closed-dataset metrics are only defensible when every closed trade
    # has a recorded broker P&L. Never silently shrink the denominator.
    closed_priced = int(closed["pnl"].notna().sum()) if not closed.empty else 0
    closed_missing_pnl = int(len(closed) - closed_priced)
    closed_pnl_complete = closed_missing_pnl == 0

    pnl_values = closed["pnl"].dropna() if not closed.empty else pd.Series(dtype=float)
    wins = closed[closed["pnl"] > 0] if not closed.empty else closed.copy()
    losses = closed[closed["pnl"] < 0] if not closed.empty else closed.copy()
    flat = closed[closed["pnl"] == 0] if not closed.empty else closed.copy()

    if closed.empty:
        win_rate = None
        total_pnl = None
        avg_win = None
        avg_loss = None
        profit_factor = None
        best_trade = None
        worst_trade = None
    elif closed_pnl_complete:
        win_rate = len(wins) / len(closed) * 100
        total_pnl = float(pnl_values.sum())
        avg_win = float(wins["pnl"].mean()) if not wins.empty else 0.0
        avg_loss = float(losses["pnl"].mean()) if not losses.empty else 0.0
        gross_profit = float(wins["pnl"].sum()) if not wins.empty else 0.0
        gross_loss = abs(float(losses["pnl"].sum())) if not losses.empty else 0.0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else (float("inf") if gross_profit > 0 else None)
        best_trade = float(closed["pnl"].max())
        worst_trade = float(closed["pnl"].min())
    else:
        win_rate = None
        total_pnl = None
        avg_win = None
        avg_loss = None
        profit_factor = None
        best_trade = None
        worst_trade = None

    # Durée moyenne des trades
    closed_with_dates = closed.dropna(subset=["entry_date", "exit_date"])
    if not closed_with_dates.empty:
        durations = (closed_with_dates["exit_date"] - closed_with_dates["entry_date"]).dt.days
        avg_duration = durations.mean()
        duration_samples = int(durations.notna().sum())
    else:
        avg_duration = None
        duration_samples = 0

    # Open P&L is complete only if every open position has a valid mark.
    open_priced = int(opened["pnl"].notna().sum()) if not opened.empty else 0
    open_unpriced = int(len(opened) - open_priced)
    open_pnl = float(opened["pnl"].dropna().sum()) if open_priced else (0.0 if opened.empty else None)
    open_pnl_complete = open_unpriced == 0

    return {
        "total_trades":    len(df),
        "closed_trades":   len(closed),
        "open_trades":     len(opened),
        "wins":            len(wins) if closed_pnl_complete else None,
        "losses":          len(losses) if closed_pnl_complete else None,
        "flat":            len(flat) if closed_pnl_complete else None,
        "closed_positions_priced": closed_priced,
        "closed_positions_missing_pnl": closed_missing_pnl,
        "closed_pnl_complete": closed_pnl_complete,
        "win_rate":        round(win_rate, 1) if win_rate is not None else None,
        "total_pnl":       round(total_pnl, 2) if total_pnl is not None else None,
        "open_pnl":        round(open_pnl, 2) if open_pnl is not None else None,
        "open_positions_priced": open_priced,
        "open_positions_unpriced": open_unpriced,
        "open_pnl_complete": open_pnl_complete,
        "total_pnl_incl_open": (
            round(total_pnl + open_pnl, 2)
            if closed_pnl_complete and open_pnl_complete and total_pnl is not None and open_pnl is not None
            else None
        ),
        "avg_win":         round(avg_win, 2) if avg_win is not None else None,
        "avg_loss":        round(avg_loss, 2) if avg_loss is not None else None,
        "profit_factor":   round(profit_factor, 2) if profit_factor is not None else None,
        "best_trade":      round(best_trade, 2) if best_trade is not None else None,
        "worst_trade":     round(worst_trade, 2) if worst_trade is not None else None,
        "avg_duration_days": (
            round(avg_duration, 1)
            if avg_duration is not None
            else None
        ),
        "duration_samples": duration_samples,
    }


# ── Cumulative realised P&L ──────────────────────────────────

def build_cumulative_realised_pnl(df: pd.DataFrame) -> go.Figure:
    """Cumulative realised P&L over closed trades; not an account equity curve."""
    closed = df[df["status"] == "CLOSED"].dropna(subset=["exit_date", "pnl"]).copy()
    closed = closed.sort_values("exit_date")
    closed["cumulative_pnl"] = closed["pnl"].cumsum()

    fig = go.Figure()

    # Zone sous la courbe
    fig.add_trace(go.Scatter(
        x=closed["exit_date"],
        y=closed["cumulative_pnl"],
        mode="lines+markers",
        line=dict(color=COLOR_WIN, width=2.5),
        marker=dict(size=7, color=closed["pnl"].apply(lambda x: COLOR_WIN if x >= 0 else COLOR_LOSS)),
        fill="tozeroy",
        fillcolor="rgba(34,197,94,0.1)",
        hovertemplate="<b>%{x|%d %b %Y}</b><br>P&L cumulé : <b>+%{y:.2f}€</b><extra></extra>",
        name="Cumulative realised P&L",
    ))

    # Ligne zéro
    fig.add_hline(y=0, line_dash="dash", line_color="rgba(128,128,128,0.4)", line_width=1)

    fig.update_layout(
        title=dict(text="Cumulative Realised P&L", font=dict(size=15), x=0.02),
        xaxis=dict(title="", showgrid=True, gridcolor=COLOR_GRID),
        yaxis=dict(title="Cumulative P&L (€)", showgrid=True, gridcolor=COLOR_GRID, ticksuffix="€"),
        plot_bgcolor=COLOR_BG,
        paper_bgcolor=COLOR_BG,
        margin=dict(l=60, r=20, t=50, b=40),
        hovermode="x unified",
        showlegend=False,
        height=320,
    )
    return fig


# ── P&L par trade (barres) ───────────────────────────────────

def build_pnl_bars(df: pd.DataFrame) -> go.Figure:
    """
    Barres P&L par trade clôturé, colorées vert/rouge.
    """
    closed = df[df["status"] == "CLOSED"].dropna(subset=["pnl"]).copy()
    closed = closed.sort_values("entry_date")
    label = closed["ticker"] + " (" + closed["entry_date"].dt.strftime("%b %y") + ")"
    colors = closed["pnl"].apply(lambda x: COLOR_WIN if x >= 0 else COLOR_LOSS)

    fig = go.Figure(go.Bar(
        x=label,
        y=closed["pnl"],
        marker_color=colors,
        hovertemplate="<b>%{x}</b><br>P&L : %{y:+.2f}€<extra></extra>",
    ))

    fig.add_hline(y=0, line_color="rgba(128,128,128,0.4)", line_width=1)

    fig.update_layout(
        title=dict(text="P&L per Trade", font=dict(size=15), x=0.02),
        xaxis=dict(tickangle=-45, showgrid=False),
        yaxis=dict(title="P&L (€)", showgrid=True, gridcolor=COLOR_GRID, ticksuffix="€"),
        plot_bgcolor=COLOR_BG,
        paper_bgcolor=COLOR_BG,
        margin=dict(l=60, r=20, t=50, b=100),
        height=350,
    )
    return fig


# ── Répartition sectorielle ───────────────────────────────────

def build_sector_pie(df: pd.DataFrame) -> go.Figure:
    """Net realised P&L by sector, including both gains and losses."""
    closed = df[(df["status"] == "CLOSED") & df["pnl"].notna()].copy()
    by_sector = closed.groupby("sector", dropna=False)["pnl"].sum().reset_index()
    by_sector["sector"] = by_sector["sector"].fillna("Unclassified")
    by_sector = by_sector.sort_values("pnl", ascending=True)

    fig = go.Figure(go.Bar(
        x=by_sector["pnl"],
        y=by_sector["sector"],
        orientation="h",
        marker_color=by_sector["pnl"].apply(lambda x: COLOR_WIN if x >= 0 else COLOR_LOSS),
        hovertemplate="<b>%{y}</b><br>Net realised P&L: %{x:.2f}€<extra></extra>",
        name="Net realised P&L",
    ))
    fig.add_vline(x=0, line_dash="dash", line_color="rgba(128,128,128,0.4)", line_width=1)
    fig.update_layout(
        title=dict(text="Net Realised P&L by Sector", font=dict(size=15), x=0.02),
        xaxis=dict(title="Net realised P&L (€)", showgrid=True, gridcolor=COLOR_GRID),
        yaxis=dict(title=""),
        paper_bgcolor=COLOR_BG,
        plot_bgcolor=COLOR_BG,
        margin=dict(l=20, r=20, t=50, b=30),
        height=max(300, 48 * max(1, len(by_sector))),
        showlegend=False,
    )
    return fig


# ── Tableau des trades ────────────────────────────────────────

def format_trades_table(df: pd.DataFrame) -> pd.DataFrame:
    """
    Formatte le DataFrame pour affichage Streamlit.
    """
    display_cols = {
        "ticker":       "Reference / Underlying",
        "direction":    "Exposure",
        "qty":          "Qty",
        "entry_price":  "Recorded Entry",
        "entry_date":   "Entry Date",
        "exit_price":   "Recorded Exit",
        "exit_date":    "Exit Date",
        "pnl":          "Broker P&L (€)",
        "status":       "Status",
        "sector":       "Sector",
        "notes":        "Trade Note",
    }
    out = df[[c for c in display_cols if c in df.columns]].copy()
    out = out.rename(columns=display_cols)

    for column in ("Entry Date", "Exit Date"):
        if column in out.columns:
            parsed = pd.to_datetime(out[column], errors="coerce")
            out[column] = parsed.dt.strftime("%d/%m/%y").where(parsed.notna(), "")

    return out


# Backward-compatible alias; public UI/docs use the financially precise name.
build_equity_curve = build_cumulative_realised_pnl
