# ============================================================
#  QuantEdge — Module DCA Long Terme
#  Lit directement simu_invest.xlsm (feuille "data")
#  Compatible Python 3.8
# ============================================================

from typing import Optional, Dict, List, Tuple
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
import openpyxl
import os
import time

# ── Chemins ──────────────────────────────────────────────────
EXCEL_PATH = "data/simu_invest.xlsm"

# ── Mapping produits → colonnes data ─────────────────────────
# Colonne paire = valeur totale actuelle
PRODUITS_MAP = {
    "iShares Global Infrastructure Dist":    26,
    "iShares Agribusiness Acc":              28,
    "iShares MSCI India Acc":                30,
    "L&G Artificial Intelligence Acc":       32,
    "iShares MSCI World Small Cap Acc":      34,
    "iShares Core MSCI Europe Acc":          36,
    "iShares Physical Gold Acc":             38,
    "iShares Digital Security Acc":          40,
    "iShares Automation & Robotics Acc":     42,
    "iShares Global Clean Energy Dist":      44,
    "iShares Global Clean Energy Acc":       46,
    "Nvidia":                                48,
    "Xtrackers MSCI World ex USA Acc":       50,
    "iShares Global Water Acc":              52,
    "Global X Uranium Acc":                  54,
    "Cameco":                                56,
    "IonQ":                                  58,
    "iShares S&P 500 Health Care Acc":       60,
    "Vanguard FTSE All World Acc":           62,
    "iShares Global Aggregate Bond EUR Acc": 64,
    "VanEck Global Real Estate Acc":         66,
    "Schneider Electric":                    68,
}

ETF_PRINCIPAUX = {
    "iShares S&P 500 Acc":              {"inv": 2, "val": 8},
    "iShares NASDAQ 100 Acc":           {"inv": 3, "val": 9},
    "HSBC MSCI Emerging Markets Acc":   {"inv": 4, "val": 10},
    "VanEck Defense Acc":               {"inv": 5, "val": 11},
}

COLOR_BG   = "rgba(0,0,0,0)"
COLOR_GRID = "rgba(128,128,128,0.15)"
COLOR_GREEN = "#22c55e"
COLOR_RED   = "#ef4444"
COLOR_AMBER = "#f59e0b"
COLOR_BLUE  = "#0ea5e9"


# ============================================================
#  LECTURE DU FICHIER EXCEL
# ============================================================

def load_excel(path: str = EXCEL_PATH) -> Optional[pd.DataFrame]:
    """
    Lit la feuille 'data' de simu_invest.xlsm.
    Retourne un DataFrame avec toutes les lignes valides (Col L > 0).
    """
    if not os.path.exists(path):
        return None

    try:
        wb = openpyxl.load_workbook(path, keep_vba=True, data_only=True)
        ws = wb['data']

        rows = []
        for row in ws.iter_rows(min_row=2, max_row=300, values_only=True):
            if row[0] is None:
                continue
            # Garder uniquement les lignes avec valeur totale (col L = index 11)
            if row[11] is None or row[11] == 0:
                continue
            rows.append(row)

        if not rows:
            return None

        # Construire le DataFrame
        data = []
        for row in rows:
            entry = {
                "date":           pd.to_datetime(row[0]),
                "sp500_inv":      row[1] or 0,
                "nasdaq_inv":     row[2] or 0,
                "em_inv":         row[3] or 0,
                "defense_inv":    row[4] or 0,
                "total_inv":      row[5] or 0,
                "autre_inv":      row[6] or 0,
                "sp500_val":      row[7] or 0,
                "nasdaq_val":     row[8] or 0,
                "em_val":         row[9] or 0,
                "defense_val":    row[10] or 0,
                "total_val":      row[11] or 0,
            }
            # Autres produits
            for nom, col in PRODUITS_MAP.items():
                idx = col - 1  # 0-based
                entry[nom] = row[idx] if idx < len(row) and row[idx] else 0

            data.append(entry)

        df = pd.DataFrame(data)
        df = df.sort_values("date").reset_index(drop=True)
        return df

    except Exception as e:
        print(f"Erreur lecture Excel : {e}")
        return None


def get_file_info(path: str = EXCEL_PATH) -> Dict:
    """Infos sur le fichier Excel."""
    if not os.path.exists(path):
        return {"exists": False}
    mtime = os.path.getmtime(path)
    return {
        "exists":   True,
        "modified": pd.Timestamp(mtime, unit='s').strftime("%d/%m/%Y %H:%M"),
        "size_kb":  round(os.path.getsize(path) / 1024, 1),
    }


# ============================================================
#  STATISTIQUES GLOBALES
# ============================================================

def compute_global_stats(df: pd.DataFrame) -> Dict:
    """Calcule les stats globales depuis toutes les lignes."""
    if df.empty:
        return {}

    last = df.iloc[-1]
    first = df.iloc[0]

    total_inv = float(last["total_inv"])
    total_val = float(last["total_val"])
    pnl       = total_val - total_inv
    pnl_pct   = pnl / total_inv if total_inv > 0 else 0

    # Versement moyen
    n_versements = len(df)
    duree_mois = max(1, (last["date"] - first["date"]).days / 30)
    versement_moyen = total_inv / n_versements



    # Ratio valorisation
    ratio = total_val / total_inv if total_inv > 0 else 1

    # Best and worst periods (net market gain between two data points)
    df3 = df.copy()
    df3["val_chg"] = df3["total_val"].diff()
    df3["inv_chg"] = df3["total_inv"].diff()
    df3["net_gain"] = df3["val_chg"] - df3["inv_chg"]
    best_trade  = round(float(df3["net_gain"].max()), 2)
    worst_trade = round(float(df3["net_gain"].min()), 2)

    return {
        "total_inv":           round(total_inv, 2),
        "total_val":           round(total_val, 2),
        "pnl":                 round(pnl, 2),
        "pnl_pct":             round(pnl_pct, 4),
        "n_versements":        n_versements,
        "duree_mois":          round(duree_mois, 1),
        "versement_moyen":     round(versement_moyen, 2),
        "ratio_val_inv":       round(ratio, 3),
        "best_trade":          best_trade,
        "worst_trade":         worst_trade,
        "date_debut":          first["date"].strftime("%d/%m/%Y"),
        "date_fin":            last["date"].strftime("%d/%m/%Y"),
        "rendement_annualise": round(((ratio ** (12 / max(1, duree_mois))) - 1), 4),
    }


# ============================================================
#  GRAPHIQUES
# ============================================================

def build_evolution_curve(df: pd.DataFrame) -> go.Figure:
    """Courbe valeur totale vs montant investi dans le temps."""
    fig = go.Figure()

    # Zone entre investi et valeur (gain)
    fig.add_trace(go.Scatter(
        x=df["date"], y=df["total_val"],
        name="Current value",
        line=dict(color=COLOR_GREEN, width=2.5),
        fill="tonexty",
        fillcolor="rgba(34,197,94,0.15)",
        hovertemplate="<b>%{x|%b %Y}</b><br>Valeur : %{y:,.0f}€<extra></extra>",
    ))

    fig.add_trace(go.Scatter(
        x=df["date"], y=df["total_inv"],
        name="Total invested",
        line=dict(color=COLOR_BLUE, width=2, dash="dash"),
        hovertemplate="<b>%{x|%b %Y}</b><br>Investi : %{y:,.0f}€<extra></extra>",
    ))

    fig.update_layout(
        title=dict(text="Évolution du portfolio DCA", font=dict(size=15), x=0.02),
        xaxis=dict(showgrid=True, gridcolor=COLOR_GRID),
        yaxis=dict(title="Montant (€)", showgrid=True, gridcolor=COLOR_GRID, ticksuffix="€"),
        plot_bgcolor=COLOR_BG, paper_bgcolor=COLOR_BG,
        margin=dict(l=60, r=20, t=50, b=40),
        hovermode="x unified", height=350,
        legend=dict(orientation="h", x=0, y=1.1),
    )
    return fig


def build_etf_evolution(df: pd.DataFrame, produit: str) -> go.Figure:
    """Évolution d'un ETF spécifique dans le temps."""
    if produit not in df.columns:
        return go.Figure()

    series = df[["date", produit]].copy()
    series = series[series[produit] > 0]

    if series.empty:
        return go.Figure()

    color = COLOR_GREEN if series[produit].iloc[-1] >= series[produit].iloc[0] else COLOR_RED

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=series["date"],
        y=series[produit],
        mode="lines+markers",
        line=dict(color=color, width=2.5),
        marker=dict(size=6),
        hovertemplate="<b>%{x|%d %b %Y}</b><br>Valeur : %{y:,.2f}€<extra></extra>",
    ))

    # Ligne de référence premier point
    first_val = float(series[produit].iloc[0])
    fig.add_hline(y=first_val, line_dash="dot",
                  line_color="rgba(128,128,128,0.4)",
                  annotation_text=f"Initial value: {first_val:,.0f}€")

    y_min = float(series[produit].min()) * 0.92
    y_max = float(series[produit].max()) * 1.05
    fig.update_layout(
        title=dict(text=f"Performance — {produit}", font=dict(size=14), x=0.02),
        xaxis=dict(showgrid=True, gridcolor=COLOR_GRID),
        yaxis=dict(title="Valeur (€)", showgrid=True, gridcolor=COLOR_GRID,
                   ticksuffix="€", range=[y_min, y_max]),
        plot_bgcolor=COLOR_BG, paper_bgcolor=COLOR_BG,
        margin=dict(l=60, r=20, t=50, b=40),
        height=320, showlegend=False,
    )
    return fig


def build_projection(
    total_val: float,
    versement_mensuel: float,
    horizons: List[int] = [10, 20, 30],
) -> go.Figure:
    """
    Projection DCA sur 10/20/30 ans.
    3 scénarios : pessimiste 5%, base 8%, optimiste 11%
    """
    scenarios = [
        ("Conservative (5%/yr)",  0.05, COLOR_RED),
        ("Base case (8%/yr)",        0.08, COLOR_AMBER),
        ("Optimistic (11%/yr)", 0.11, COLOR_GREEN),
    ]

    fig = go.Figure()
    max_horizon = max(horizons)

    for label, taux_annuel, color in scenarios:
        taux_mensuel = (1 + taux_annuel) ** (1/12) - 1
        valeurs = []
        mois_list = list(range(0, max_horizon * 12 + 1))

        val = total_val
        for m in mois_list:
            if m > 0:
                val = val * (1 + taux_mensuel) + versement_mensuel
            valeurs.append(val)

        annees = [m / 12 for m in mois_list]

        fig.add_trace(go.Scatter(
            x=annees, y=valeurs,
            name=label,
            line=dict(color=color, width=2.5),
            hovertemplate=f"<b>{label}</b><br>Dans %{{x:.0f}} ans : %{{y:,.0f}}€<extra></extra>",
        ))

    # Ligne "capital investi pur" sans rendement
    val_investi = [total_val + versement_mensuel * m for m in mois_list]
    fig.add_trace(go.Scatter(
        x=annees, y=val_investi,
        name="Capital invested (no return)",
        line=dict(color="rgba(128,128,128,0.6)", width=1.5, dash="dot"),
        hovertemplate="Capital investi : %{y:,.0f}€<extra></extra>",
    ))

    # Marqueurs aux horizons clés
    for horizon in horizons:
        fig.add_vline(
            x=horizon,
            line_dash="dash",
            line_color="rgba(128,128,128,0.3)",
            annotation_text=f"{horizon}y",
            annotation_position="top",
        )

    fig.update_layout(
        title=dict(text=f"Projection DCA — versement {versement_mensuel:,.0f}€/mois", font=dict(size=15), x=0.02),
        xaxis=dict(title="Years", showgrid=True, gridcolor=COLOR_GRID),
        yaxis=dict(title="Estimated value (€)", showgrid=True, gridcolor=COLOR_GRID,
                   tickformat=",.0f", ticksuffix="€"),
        plot_bgcolor=COLOR_BG, paper_bgcolor=COLOR_BG,
        margin=dict(l=80, r=20, t=50, b=50),
        hovermode="x unified", height=400,
        legend=dict(orientation="h", x=0, y=1.12),
    )
    return fig


def build_allocation_donut(df: pd.DataFrame) -> go.Figure:
    """Donut allocation actuelle tous produits."""
    last = df.iloc[-1]

    labels, values = [], []

    # ETFs principaux
    for nom, cols in ETF_PRINCIPAUX.items():
        v = float(last.get(f"sp500_val" if "S&P 500" in nom else
                           f"nasdaq_val" if "NASDAQ" in nom else
                           f"em_val" if "Emerging" in nom else
                           f"defense_val", 0) or 0)
        # Récupération directe
        col_map = {"iShares S&P 500 Acc": "sp500_val",
                   "iShares NASDAQ 100 Acc": "nasdaq_val",
                   "HSBC MSCI Emerging Markets Acc": "em_val",
                   "VanEck Defense Acc": "defense_val"}
        v = float(last.get(col_map.get(nom, "sp500_val"), 0) or 0)
        if v > 0:
            labels.append(nom.replace(" Acc", "").replace("iShares ", "").replace("HSBC ", "").replace("VanEck ", ""))
            values.append(v)

    # Autres produits
    for nom in PRODUITS_MAP:
        v = float(last.get(nom, 0) or 0)
        if v > 50:
            short = nom.replace(" Acc", "").replace(" Dist", "").replace("iShares ", "").replace("Xtrackers ", "").replace("Vanguard ", "").replace("VanEck ", "").replace("Global X ", "").replace("L&G ", "").replace("HSBC ", "")
            labels.append(short)
            values.append(v)

    fig = go.Figure(go.Pie(
        labels=labels, values=values,
        hole=0.55,
        textinfo="none",
        hovertemplate="<b>%{label}</b><br>%{value:,.0f}€ (%{percent})<extra></extra>",
        marker=dict(colors=px.colors.qualitative.Set3),
    ))
    fig.update_layout(
        title=dict(text="Allocation actuelle", font=dict(size=15), x=0.02),
        paper_bgcolor=COLOR_BG,
        margin=dict(l=20, r=20, t=50, b=20),
        height=400, showlegend=False,
    )
    return fig


def load_invested_from_dashboard(path: str = EXCEL_PATH) -> Dict:
    """
    Reads invested amounts per product from the 'dashboard' sheet.
    This is the source of truth for invested amounts per product.
    """
    invested = {}
    try:
        wb = openpyxl.load_workbook(path, keep_vba=True, data_only=True)
        if 'dashboard' not in wb.sheetnames:
            return invested
        ws = wb['dashboard']
        # Dashboard: col B = product name, col C = invested amount
        # Rows 11-14: ETF principaux, rows 18+: autres produits
        for row in ws.iter_rows(min_row=11, max_row=50, values_only=True):
            name = row[1]  # col B
            inv  = row[2]  # col C
            if name and isinstance(inv, (int, float)) and inv > 0:
                invested[str(name).strip()] = float(inv)
    except Exception as e:
        pass
    return invested


def get_all_produits(df: pd.DataFrame) -> List[str]:
    """Liste tous les produits disponibles, triés par valeur décroissante."""
    last = df.iloc[-1]
    produits_vals = []

    col_map = {
        "iShares S&P 500 Acc":            "sp500_val",
        "iShares NASDAQ 100 Acc":          "nasdaq_val",
        "HSBC MSCI Emerging Markets Acc":  "em_val",
        "VanEck Defense Acc":              "defense_val",
    }
    for nom, col in col_map.items():
        v = float(last.get(col, 0) or 0)
        if v > 0:
            produits_vals.append((nom, v))

    for nom in PRODUITS_MAP:
        v = float(last.get(nom, 0) or 0)
        if v > 0:
            produits_vals.append((nom, v))

    produits_vals.sort(key=lambda x: -x[1])
    return [p[0] for p in produits_vals]


def get_produit_stats(df: pd.DataFrame, produit: str, excel_path: str = EXCEL_PATH) -> Dict:
    """
    Returns invested, current value and return for a product.
    Reads invested amounts from the dashboard sheet (source of truth).
    """
    col_map_inv = {
        "iShares S&P 500 Acc":            ("sp500_inv",  "sp500_val"),
        "iShares NASDAQ 100 Acc":          ("nasdaq_inv", "nasdaq_val"),
        "HSBC MSCI Emerging Markets Acc":  ("em_inv",     "em_val"),
        "VanEck Defense Acc":              ("defense_inv","defense_val"),
    }

    last = df.iloc[-1]

    if produit in col_map_inv:
        col_inv, col_val = col_map_inv[produit]
        investi = float(last.get(col_inv, 0) or 0)
        valeur  = float(last.get(col_val, 0) or 0)
    else:
        valeur = float(last.get(produit, 0) or 0)
        # Read from dashboard sheet (accurate invested amounts)
        dashboard_inv = load_invested_from_dashboard(excel_path)
        if produit in dashboard_inv:
            investi = dashboard_inv[produit]
        else:
            # Fallback: first non-zero value
            series = df[produit].replace(0, None).dropna()
            investi = float(series.iloc[0]) if not series.empty else 0

    pnl = valeur - investi
    rendement = pnl / investi if investi > 0 else 0

    return {
        "investi":   investi,
        "valeur":    valeur,
        "pnl":       pnl,
        "rendement": rendement,
    }


def build_ai_portfolio_prompt(stats: Dict, df: pd.DataFrame) -> str:
    """Builds the AI analysis prompt with real portfolio data."""
    last = df.iloc[-1]

    # Build positions summary
    positions = []
    col_map = {
        "iShares S&P 500 Acc": "sp500_val",
        "iShares NASDAQ 100 Acc": "nasdaq_val",
        "HSBC MSCI Emerging Markets Acc": "em_val",
        "VanEck Defense Acc": "defense_val",
    }
    for nom, col in col_map.items():
        v = float(last.get(col, 0) or 0)
        if v > 0:
            positions.append(f"  - {nom}: {v:,.0f}€")
    for nom in PRODUITS_MAP:
        v = float(last.get(nom, 0) or 0)
        if v > 50:
            positions.append(f"  - {nom}: {v:,.0f}€")

    positions_str = "\n".join(positions[:15])

    return f"""You are a senior portfolio manager at a private bank.
Analyse this long-term DCA portfolio and answer the specific question below.

═══ PORTFOLIO DATA ═══
Total invested    : {stats['total_inv']:,.0f}€
Current value     : {stats['total_val']:,.0f}€
Total P&L         : {stats['pnl']:+,.0f}€ ({stats['pnl_pct']*100:+.1f}%)
Annualised return : {stats['rendement_annualise']*100:+.1f}%
DCA duration      : {stats['duree_mois']:.0f} months
Contributions     : {stats['n_versements']}
Value/Invested    : {stats['ratio_val_inv']:.2f}x
Period            : {stats['date_debut']} → {stats['date_fin']}

TOP POSITIONS (current value):
{positions_str}

Be direct, specific and institutional. No generic advice."""
