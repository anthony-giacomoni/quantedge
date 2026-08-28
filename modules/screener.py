# ============================================================
#  QuantEdge — Module Screener (mondial + ratio Spike)
#  Compatible Python 3.8
# ============================================================

from typing import Optional, Dict, List, Tuple
import pandas as pd
import numpy as np
import time
import sys, os
from datetime import datetime
import pytz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.market_data import get_price_history_df, get_ticker_info

# ============================================================
#  UNIVERS MONDIAL
# ============================================================

UNIVERSE = {
    "US Energy": [
        "XOM", "CVX", "OXY", "VLO", "MPC", "PSX",
        "HAL", "SLB", "XLE", "UEC", "CCJ", "ENPH", "NEE",
    ],
    "US Semiconductors": [
        "NVDA", "AMD", "INTC", "QCOM", "MRVL", "AMAT",
        "KLAC", "ON", "WOLF", "MCHP", "MPWR", "SOXX", "SMH",
    ],
    "US Defence": [
        "LMT", "RTX", "NOC", "GD", "BA", "HII", "LDOS",
        "AXON", "KTOS", "HEI", "TDG", "ITA",
    ],
    "US Healthcare Tech": [
        "VEEV", "ISRG", "DXCM", "UNH", "ELV", "GEHC",
        "BSX", "EW", "HOLX", "IDXX", "ZBH",
    ],
    "US Cyber / Tech": [
        "ZS", "CRWD", "PANW", "FTNT", "NET", "OKTA",
        "DDOG", "MDB", "SNOW", "S",
    ],
    "EU Energy": [
        "SIE.DE", "TTE", "BP", "SHEL", "ENI.MI",
        "REP.MC", "ENEL.MI", "IBE.MC", "EDF.PA", "VIE.PA",
    ],
    "EU Defence": [
        "RHM.DE", "AIR.PA", "SAF.PA", "BA.L", "LDO.MI", "DASSAV.PA",
    ],
    "EU Industry / Tech": [
        "ASML", "SU.PA", "CAP.PA", "SAP", "STMPA.PA", "SIEGY",
    ],
    "EU Finance": [
        "BNP.PA", "GLE.PA", "ACA.PA", "DBK.DE", "HSBA.L", "AON",
    ],
    "Asia Tech": [
        "TSM", "SONY", "TM", "BABA", "BIDU", "9988.HK", "2330.TW",
    ],
    "Asia Energy": [
        "PTR", "SNP", "INPEY", "STO",
    ],
    "Global Commodities & ETFs": [
        "GLD", "SLV", "USO", "BNO", "URA", "COPX",
        "IWM", "EEM", "VGK", "EWJ", "MCHI", "EWY",
    ],
}

ALL_TICKERS = [t for sector_tickers in UNIVERSE.values() for t in sector_tickers]

CRITERIA = {
    "min_drawdown":   0.30,
    "max_drawdown":   0.55,
    "max_5d_return":  0.04,
    "min_short_pct":  0.05,
    "max_short_pct":  0.25,
    "min_revenue":    100e6,
    "min_avg_volume": 100000,
}


def get_wide_universe_from_cache(min_market_cap: float = 1_000_000_000,
                                  sectors: List[str] = None,
                                  db_path: str = "data/quantedge.db") -> Dict:
    """
    Filtre INSTANTANÉ sur le cache local (universe_cache), sans aucun appel
    réseau. Nécessite d'avoir lancé refresh_universe.py au moins une fois.

    Retourne un dict avec :
        - "tickers": liste des tickers survivants (sans suffixe EODHD)
        - "snapshot_date": date de la snapshot utilisée
        - "total_in_cache": nombre total de tickers dans cette snapshot
        - "cache_empty": True si aucune snapshot n'existe encore
    """
    from utils.db import load_universe_snapshot, get_latest_snapshot_date

    snapshot_date = get_latest_snapshot_date(db_path)
    if snapshot_date is None:
        return {"tickers": [], "snapshot_date": None, "total_in_cache": 0, "cache_empty": True}

    df = load_universe_snapshot(snapshot_date, db_path)
    total_in_cache = len(df)

    df = df[df["market_cap"].fillna(0) >= min_market_cap]
    if sectors:
        df = df[df["sector"].isin(sectors)]

    tickers = df["ticker"].apply(lambda t: t.split(".")[0] if t.endswith(".US") else t).tolist()

    return {
        "tickers": tickers,
        "snapshot_date": snapshot_date,
        "total_in_cache": total_in_cache,
        "cache_empty": False,
    }


def get_wide_universe(exchange: str = "US", min_market_cap: float = 1_000_000_000,
                       max_tickers: int = 500, progress_callback=None) -> List[str]:
    """
    Fallback LIVE (lent) : à utiliser seulement si le cache est vide, c'est
    à dire si refresh_universe.py n'a encore jamais été lancé. Sans le
    Screener API premium (non disponible sur tous les plans EODHD).

    Étape 1 : liste tous les tickers de la bourse (endpoint gratuit).
    Étape 2 : entonnoir de tri en cascade sur market cap (funnel_screen) —
              chaque ticker élimine ou survit avant de passer à l'étape
              suivante, ce qui limite les appels API coûteux.

    max_tickers limite le nombre de tickers testés à l'étape 1 pour garder
    un temps de scan raisonnable (une bourse US en compte plus de 10 000).
    Le calcul précis (drawdown, spike, etc.) se fait ensuite normalement
    dans fetch_ticker_data pour chaque survivant.
    """
    from utils.market_data import get_exchange_tickers, funnel_screen

    all_tickers = get_exchange_tickers(exchange=exchange)
    if not all_tickers:
        return []

    # On limite le nombre testé pour garder un temps de scan raisonnable
    candidates = all_tickers[:max_tickers]

    # funnel_screen retourne directement les tickers survivants (pas juste
    # leurs fondamentaux), pour éviter tout problème de correspondance.
    survivors = funnel_screen(
        candidates,
        min_market_cap=min_market_cap,
        progress_callback=progress_callback,
    )
    # fetch_ticker_data (yfinance) attend des tickers sans suffixe EODHD (.US)
    return [s.split(".")[0] if s.endswith(".US") else s for s in survivors]


# ============================================================
#  STATUT DES MARCHÉS
# ============================================================

def get_market_status() -> dict:
    paris_tz = pytz.timezone("Europe/Paris")
    now = datetime.now(paris_tz)
    heure_paris = now.strftime("%Hh%M")
    jour = now.weekday()
    h = now.hour + now.minute / 60.0

    if jour >= 5:
        jour_str = "Saturday" if jour == 5 else "Sunday"
        return {
            "any_open": False, "weekend": True,
            "message": f"🔴 Markets closed — {jour_str}. Reopening Monday at 09:00.",
            "zones": {}, "heure_paris": heure_paris,
        }

    zones = {
        "Asia":    1.0  <= h < 9.0,
        "Europe": 9.0  <= h < 17.5,
        "USA":    15.5 <= h < 22.0,
    }

    open_zones = [z for z, s in zones.items() if s]

    if not open_zones:
        return {
            "any_open": False, "weekend": False,
            "message": f"🔴 All markets closed — {heure_paris} Paris time. Next open: Asia at 01:00.",
            "zones": zones, "heure_paris": heure_paris,
        }

    lines = [f"Market hours — **{heure_paris}** Paris time\n"]
    for zone, is_open in zones.items():
        lines.append(f"- {zone} : {'🟢 Open' if is_open else '🔴 Closed'}")

    return {
        "any_open": True, "weekend": False,
        "message": "\n".join(lines),
        "zones": zones, "open_zones": open_zones,
        "heure_paris": heure_paris,
    }


def get_open_tickers(status: dict) -> List[str]:
    if not status.get("zones"):
        return ALL_TICKERS
    zones_open = status.get("open_zones", [])
    if not zones_open:
        return ALL_TICKERS
    open_tickers = []
    for sector, tickers in UNIVERSE.items():
        zone_match = any(z in sector for z in zones_open)
        is_global = "Commodities" in sector or "ETFs" in sector
        if zone_match or (is_global and "USA" in zones_open):
            open_tickers.extend(tickers)
    return open_tickers if open_tickers else ALL_TICKERS


# ============================================================
#  FETCH, FILTRES & SCORING
# ============================================================

def fetch_ticker_data(ticker: str) -> Optional[Dict]:
    """Récupère toutes les données + calcule le ratio Spike."""
    try:
        hist = get_price_history_df(ticker, years=5)

        if hist is None or hist.empty or len(hist) < 20:
            return None

        current_price = float(hist["Close"].iloc[-1])
        ath = float(hist["High"].max())
        drawdown = (current_price - ath) / ath

        # Rendements
        ret_5d = None
        if len(hist) >= 5:
            ret_5d = (current_price - float(hist["Close"].iloc[-5])) / float(hist["Close"].iloc[-5])

        ret_1d = None
        if len(hist) >= 2:
            ret_1d = (current_price - float(hist["Close"].iloc[-2])) / float(hist["Close"].iloc[-2])

        # Volume
        avg_volume = float(hist["Volume"].tail(20).mean())
        vol_today  = float(hist["Volume"].iloc[-1])
        rel_volume = vol_today / avg_volume if avg_volume > 0 else 1.0

        # Volatilité 20j annualisée
        returns = hist["Close"].pct_change().dropna()
        vol_20d = float(returns.tail(20).std())
        volatility_annual = vol_20d * (252 ** 0.5)

        # ── RATIO SPIKE ──────────────────────────────────────
        # Return/Volatilité sur 5 jours
        # Mesure l'efficacité du mouvement : un spike élevé = mouvement
        # fort ET propre (peu de bruit). Signal d'accumulation institutionnelle.
        # Positif = mouvement haussier net, négatif = vente panique
        spike_ratio = None
        if ret_5d is not None and vol_20d > 0:
            spike_ratio = round(ret_5d / vol_20d, 3)

        # ── SPIKE HISTORIQUE ─────────────────────────────────
        # Percentile du spike actuel vs historique 1 an
        # Un spike dans le top 10% baissier = opportunité de retournement
        spike_percentile = None
        if len(hist) >= 60 and vol_20d > 0:
            hist_returns_5d = hist["Close"].pct_change(5).dropna()
            hist_vol = returns.rolling(20).std().dropna()
            min_len = min(len(hist_returns_5d), len(hist_vol))
            if min_len > 20:
                hist_spikes = hist_returns_5d.iloc[-min_len:].values / (hist_vol.iloc[-min_len:].values + 1e-8)
                current_spike = spike_ratio if spike_ratio else 0
                spike_percentile = round(float((hist_spikes < current_spike).mean()) * 100, 1)

        # Support 52 semaines
        low_52w = float(hist["Low"].tail(252).min()) if len(hist) >= 252 else float(hist["Low"].min())
        dist_to_support = (current_price - low_52w) / low_52w if low_52w > 0 else 0.5

        # Fondamentaux — via la couche d'abstraction market_data (EODHD ou
        # yfinance selon la config), pas d'appel direct à yfinance ici.
        info = get_ticker_info(ticker)

        short_pct = float(info.get("short_pct_float") or 0)
        total_rev = info.get("revenue") or 0
        name      = info.get("name", ticker)

        our_sector = "Other"
        for s, tickers_list in UNIVERSE.items():
            if ticker in tickers_list:
                our_sector = s
                break

        return {
            "ticker":            ticker,
            "name":              name,
            "sector":            our_sector,
            "current_price":     round(current_price, 4),
            "ath":               round(ath, 4),
            "drawdown_pct":      round(drawdown, 4),
            "ret_5d":            round(ret_5d, 4) if ret_5d is not None else None,
            "ret_1d":            round(ret_1d, 4) if ret_1d is not None else None,
            "avg_volume":        round(avg_volume),
            "rel_volume":        round(rel_volume, 2),
            "volatility":        round(volatility_annual, 4),
            "vol_20d_daily":     round(vol_20d, 4),
            "spike_ratio":       spike_ratio,
            "spike_percentile":  spike_percentile,
            "dist_to_support":   round(dist_to_support, 4),
            "short_pct":         round(short_pct, 4),
            "total_revenue":     total_rev,
        }
    except Exception:
        return None


def apply_filters(data: Dict) -> Tuple[bool, List[str]]:
    """Applique les critères de sélection."""
    failed = []

    dd = data.get("drawdown_pct", 0)
    if not (-CRITERIA["max_drawdown"] <= dd <= -CRITERIA["min_drawdown"]):
        failed.append(f"Drawdown {dd*100:.1f}% outside range [{CRITERIA['min_drawdown']*100:.0f}%-{CRITERIA['max_drawdown']*100:.0f}%]")

    r5 = data.get("ret_5d")
    if r5 is not None and r5 > CRITERIA["max_5d_return"]:
        failed.append(f"Recent run +{r5*100:.1f}% over 5d (max {CRITERIA['max_5d_return']*100:.0f}%)")

    if data.get("avg_volume", 0) < CRITERIA["min_avg_volume"]:
        failed.append(f"Insufficient avg volume ({data.get('avg_volume',0):,.0f} < {CRITERIA['min_avg_volume']:,})")

    if data.get("total_revenue", 0) < CRITERIA["min_revenue"]:
        failed.append("Revenue < $100M (pre-revenue excluded)")

    return len(failed) == 0, failed


def compute_score(data: Dict) -> Dict:
    """
    Score 0-100 sur 6 dimensions incluant le ratio Spike.

    Ratio Spike négatif = panique récente non justifiée par les fondamentaux
    → signal de retournement = bonus dans le score
    """
    # 1. Drawdown (idéal ~38%)
    dd = abs(data.get("drawdown_pct", 0))
    dd_score = max(0, 100 - abs(dd - 0.38) * 400)

    # 2. Momentum inversé (correction récente = opportunité)
    r5 = data.get("ret_5d", 0) or 0
    mom_score = max(0, min(100, 50 - r5 * 800))

    # 3. Short interest (squeeze potentiel, optimal 10-20%)
    si = data.get("short_pct", 0)
    si_score = max(0, 100 - abs(si - 0.15) * 500)

    # 4. Volume relatif (accumulation institutionnelle)
    rv = data.get("rel_volume", 1)
    vol_score = min(100, rv * 40)

    # 5. Support (proche du bas = meilleur R/R)
    dist = data.get("dist_to_support", 0.5)
    sup_score = max(0, 100 - dist * 200)

    # 6. Ratio Spike
    # Spike très négatif (panique) dans le bas du percentile historique
    # = signal fort de retournement prochain
    spike = data.get("spike_ratio")
    spike_pct = data.get("spike_percentile")
    spike_score = 50  # neutre par défaut
    if spike is not None and spike_pct is not None:
        if spike < -1.0 and spike_pct < 15:
            # Panique extrême, rare historiquement → très bon signal
            spike_score = 90
        elif spike < -0.5 and spike_pct < 30:
            # Vente forte mais pas extrême → bon signal
            spike_score = 75
        elif spike < 0:
            # Légère pression vendeuse → signal modéré
            spike_score = 60
        elif spike > 1.0:
            # Momentum très haussier → mauvais pour notre stratégie (déjà parti)
            spike_score = 20
        else:
            spike_score = 45

    # Score global pondéré (6 dimensions)
    total = (
        dd_score    * 0.25 +
        mom_score   * 0.20 +
        si_score    * 0.15 +
        vol_score   * 0.15 +
        sup_score   * 0.10 +
        spike_score * 0.15
    )

    return {
        "score_total":         round(total, 1),
        "score_drawdown":      round(dd_score, 1),
        "score_momentum":      round(mom_score, 1),
        "score_short_squeeze": round(si_score, 1),
        "score_volume":        round(vol_score, 1),
        "score_support":       round(sup_score, 1),
        "score_spike":         round(spike_score, 1),
    }


def run_screener(tickers=None, progress_callback=None) -> pd.DataFrame:
    """Lance le screener."""
    if tickers is None:
        tickers = ALL_TICKERS

    results = []
    errors  = 0
    passed_so_far = 0
    total   = len(tickers)

    for i, ticker in enumerate(tickers):
        if progress_callback:
            progress_callback(
                i / total,
                f"[{i+1}/{total}] analyzed · {passed_so_far} matched so far · checking {ticker}..."
            )

        data = fetch_ticker_data(ticker)
        if data is None:
            errors += 1
            time.sleep(0.1)
            continue

        passes, failed = apply_filters(data)
        if passes:
            passed_so_far += 1
        scores = compute_score(data)
        data.update(scores)
        data["passes_filter"]   = passes
        data["filter_failures"] = " | ".join(failed) if failed else ""
        results.append(data)
        time.sleep(0.15)

    if not results:
        return pd.DataFrame()

    df = pd.DataFrame(results)
    df["_errors"] = errors
    df = df.sort_values(["passes_filter", "score_total"], ascending=[False, False]).reset_index(drop=True)
    return df


def format_screener_results(df: pd.DataFrame) -> pd.DataFrame:
    """Formate pour affichage Streamlit."""
    if df.empty:
        return df

    cols = ["ticker", "name", "sector", "current_price",
            "drawdown_pct", "ret_5d", "short_pct",
            "rel_volume", "spike_ratio", "score_total", "passes_filter"]

    display = df[[c for c in cols if c in df.columns]].copy()

    display["drawdown_pct"]  = (display["drawdown_pct"] * 100).round(1).astype(str) + "%"
    display["ret_5d"]        = display["ret_5d"].apply(lambda x: f"{x*100:+.1f}%" if x is not None else "N/A")
    display["short_pct"]     = (display["short_pct"] * 100).round(1).astype(str) + "%"
    display["rel_volume"]    = display["rel_volume"].apply(lambda x: f"{x:.1f}x")
    display["spike_ratio"]   = display["spike_ratio"].apply(lambda x: f"{x:+.2f}" if x is not None else "N/A")
    display["score_total"]   = display["score_total"].apply(lambda x: f"{x:.0f}/100")
    display["passes_filter"] = display["passes_filter"].apply(lambda x: "✅" if x else "❌")

    display.columns = ["Ticker", "Name", "Sector", "Price",
                       "ATH Drawdown", "5d Return", "Short %",
                       "Rel. Volume", "Spike Ratio", "Score", "Criteria"]
    return display


def backtest_score_correlation(trades_df: pd.DataFrame) -> Dict:
    """
    Vérification honnête (pas un backtest complet) : recalcule le score_total
    tel qu'il aurait été au moment de l'entrée pour chaque trade CLOSED déjà
    en base, et calcule sa corrélation avec le P&L réalisé.

    Limites assumées, à dire telles quelles en entretien :
    - Échantillon petit (nombre de trades clôturés, ~25 ici) -> corrélation
      peu significative statistiquement, à présenter comme exploratoire.
    - Le score est recalculé a posteriori à partir de l'historique de prix
      disponible aujourd'hui pour la date d'entrée -> pas un vrai point-in-time
      backtest (les données fondamentales au moment T ne sont pas ré-simulées).
    - Sert à documenter honnêtement si les poids heuristiques (0.25/0.20/...)
      ont un lien observable avec la performance réelle, pas à les valider
      statistiquement.

    Retourne un dict avec la corrélation, le nombre de trades utilisés, et
    le détail par trade pour audit.
    """
    closed = trades_df[trades_df["status"] == "CLOSED"].dropna(subset=["pnl", "entry_price"]).copy()
    if closed.empty or len(closed) < 5:
        return {
            "correlation": None,
            "n_trades": len(closed),
            "note": "Not enough closed trades with valid P&L to compute a meaningful correlation (need >= 5).",
            "detail": [],
        }

    detail = []
    for _, row in closed.iterrows():
        data = fetch_ticker_data(row["ticker"])
        if data is None:
            continue
        scores = compute_score(data)
        detail.append({
            "ticker": row["ticker"],
            "entry_date": row["entry_date"],
            "score_total_now": scores["score_total"],  # score recalculé aujourd'hui, pas point-in-time
            "pnl": row["pnl"],
        })

    if len(detail) < 5:
        return {
            "correlation": None,
            "n_trades": len(detail),
            "note": "Not enough tickers with usable price history to compute a meaningful correlation (need >= 5).",
            "detail": detail,
        }

    detail_df = pd.DataFrame(detail)
    correlation = float(detail_df["score_total_now"].corr(detail_df["pnl"]))

    return {
        "correlation": round(correlation, 3),
        "n_trades": len(detail_df),
        "note": (
            "Exploratory only: small sample, and score is recalculated with "
            "today's price history rather than a true point-in-time backtest. "
            "Present as a directional signal, not statistical validation."
        ),
        "detail": detail,
    }
