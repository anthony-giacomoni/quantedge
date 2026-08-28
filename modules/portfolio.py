# ============================================================
#  QuantEdge — Module Portfolio
#  Calculs P&L, statistiques, equity curve
# ============================================================

import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.db import load_trades
from utils.market_data import get_current_price, get_usd_eur_rate
from utils.eodhd import get_current_price as eodhd_price


# ── Couleurs du dashboard ─────────────────────────────────────
COLOR_WIN    = "#22c55e"   # vert
COLOR_LOSS   = "#ef4444"   # rouge
COLOR_OPEN   = "#f59e0b"   # amber — positions ouvertes
COLOR_BG     = "rgba(0,0,0,0)"  # transparent
COLOR_GRID   = "rgba(128,128,128,0.15)"

# Suffixes de tickers déjà cotés en EUR — pas de conversion nécessaire.
# Tout le reste (ex: NFLX, AON, sans suffixe) est traité comme coté en USD.
_EUR_QUOTED_SUFFIXES = (".PA", ".DE", ".AS", ".MC")


def _is_usd_quoted(ticker: str) -> bool:
    """Heuristique : un ticker sans suffixe de place EUR connue est en USD."""
    return not ticker.upper().endswith(_EUR_QUOTED_SUFFIXES)


# ── Chargement & enrichissement ───────────────────────────────

def load_enriched_trades(db_path: str = "data/quantedge.db") -> pd.DataFrame:
    """
    Charge les trades et ajoute le P&L latent pour les positions ouvertes.
    Les prix de tickers cotés en USD sont convertis en EUR avant le calcul,
    car entry_price / invested sont saisis en EUR dans ce projet.
    """
    df = load_trades(db_path)
    if df.empty:
        return df

    df["entry_date"] = pd.to_datetime(df["entry_date"])
    df["exit_date"]  = pd.to_datetime(df["exit_date"], errors="coerce")

    # Taux USD→EUR récupéré une seule fois pour tout le tableau (pas par ligne)
    usd_eur_rate = get_usd_eur_rate()

    # Unrealised P&L for open positions — EODHD primary
    for idx, row in df[df["status"] == "OPEN"].iterrows():
        try:
            price = eodhd_price(row["ticker"])
        except Exception:
            price = get_current_price(row["ticker"])

        # Conversion USD → EUR si nécessaire
        if price and _is_usd_quoted(row["ticker"]):
            if usd_eur_rate:
                price = round(price * usd_eur_rate, 4)
            else:
                # Pas de taux dispo : on ne calcule pas un P&L faux en mélangeant devises
                df.at[idx, "current_price"] = None
                continue

        qty = row["qty"]
        # Fallback qty from invested amount if missing
        if (qty is None or qty == 0) and row.get("invested") and row["entry_price"]:
            qty = round(float(row["invested"]) / float(row["entry_price"]), 4)
        
        if price and qty:
            if row["direction"] == "LONG":
                df.at[idx, "pnl"] = round((price - row["entry_price"]) * qty, 2)
            else:
                df.at[idx, "pnl"] = round((row["entry_price"] - price) * qty, 2)
            df.at[idx, "current_price"] = price
            df.at[idx, "qty"] = qty
        else:
            df.at[idx, "current_price"] = None

    return df


# ── Statistiques globales ─────────────────────────────────────

def compute_stats(df: pd.DataFrame) -> dict:
    """
    Calcule toutes les statistiques du track record.
    """
    closed = df[df["status"] == "CLOSED"].copy()
    opened = df[df["status"] == "OPEN"].copy()

    if closed.empty:
        return {}

    pnl_values = closed["pnl"].dropna()

    wins  = closed[closed["pnl"] > 0]
    losses = closed[closed["pnl"] < 0]
    flat  = closed[closed["pnl"] == 0]

    win_rate   = len(wins) / len(closed) * 100 if len(closed) > 0 else 0
    total_pnl  = pnl_values.sum()
    avg_win    = wins["pnl"].mean() if not wins.empty else 0
    avg_loss   = losses["pnl"].mean() if not losses.empty else 0
    profit_factor = abs(wins["pnl"].sum() / losses["pnl"].sum()) if not losses.empty else float("inf")

    # Durée moyenne des trades
    closed_with_dates = closed.dropna(subset=["entry_date", "exit_date"])
    if not closed_with_dates.empty:
        durations = (closed_with_dates["exit_date"] - closed_with_dates["entry_date"]).dt.days
        avg_duration = durations.mean()
    else:
        avg_duration = 0

    # P&L latent positions ouvertes
    open_pnl = opened["pnl"].dropna().sum() if not opened.empty else 0

    # ROI moyen par trade
    closed_with_inv = closed.dropna(subset=["invested"])
    avg_roi = (closed_with_inv["pnl"] / closed_with_inv["invested"]).mean() * 100 if not closed_with_inv.empty else 0

    return {
        "total_trades":    len(df),
        "closed_trades":   len(closed),
        "open_trades":     len(opened),
        "wins":            len(wins),
        "losses":          len(losses),
        "flat":            len(flat),
        "win_rate":        round(win_rate, 1),
        "total_pnl":       round(total_pnl, 2),
        "open_pnl":        round(open_pnl, 2),
        "total_pnl_incl_open": round(total_pnl + open_pnl, 2),
        "avg_win":         round(avg_win, 2),
        "avg_loss":        round(avg_loss, 2),
        "profit_factor":   round(profit_factor, 2),
        "best_trade":      round(closed["pnl"].max(), 2),
        "worst_trade":     round(closed["pnl"].min(), 2),
        "avg_roi_pct":     round(avg_roi, 2),
        "avg_duration_days": round(avg_duration, 1),
    }


# ── Equity Curve ──────────────────────────────────────────────

def build_equity_curve(df: pd.DataFrame) -> go.Figure:
    """
    Equity curve : P&L cumulé dans le temps sur les trades clôturés.
    """
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
        name="Equity curve",
    ))

    # Ligne zéro
    fig.add_hline(y=0, line_dash="dash", line_color="rgba(128,128,128,0.4)", line_width=1)

    fig.update_layout(
        title=dict(text="Equity Curve — Cumulative P&L", font=dict(size=15), x=0.02),
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
    """
    Donut chart : P&L positif par secteur.
    """
    closed = df[(df["status"] == "CLOSED") & (df["pnl"] > 0)].copy()
    by_sector = closed.groupby("sector")["pnl"].sum().reset_index()
    by_sector.columns = ["sector", "pnl"]

    fig = go.Figure(go.Pie(
        labels=by_sector["sector"],
        values=by_sector["pnl"],
        hole=0.55,
        textinfo="none",
        hovertemplate="<b>%{label}</b><br>P&L: %{value:.2f}€ (%{percent})<extra></extra>",
        marker=dict(colors=px.colors.qualitative.Set2),
    ))

    fig.update_layout(
        title=dict(text="Profits by Sector", font=dict(size=15), x=0.02),
        paper_bgcolor=COLOR_BG,
        margin=dict(l=20, r=20, t=50, b=20),
        height=300,
        showlegend=True,
        legend=dict(orientation="v", x=1.02, y=0.5),
    )
    return fig


# ── Tableau des trades ────────────────────────────────────────

def format_trades_table(df: pd.DataFrame) -> pd.DataFrame:
    """
    Formatte le DataFrame pour affichage Streamlit.
    """
    display_cols = {
        "ticker":       "Ticker",
        "direction":    "Dir.",
        "qty":          "Qty",
        "entry_price":  "Entry",
        "entry_date":   "Entry Date",
        "exit_price":   "Exit",
        "exit_date":    "Exit Date",
        "pnl":          "P&L (€)",
        "status":       "Status",
        "sector":       "Sector",
    }
    out = df[[c for c in display_cols if c in df.columns]].copy()
    out = out.rename(columns=display_cols)

    if "Date entrée" in out.columns:
        out["Date entrée"] = pd.to_datetime(out["Date entrée"]).dt.strftime("%d/%m/%y")
    if "Date sortie" in out.columns:
        out["Date sortie"] = pd.to_datetime(out["Date sortie"]).dt.strftime("%d/%m/%y")

    return out
