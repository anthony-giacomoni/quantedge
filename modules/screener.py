# ============================================================
#  QuantEdge — Module Screener (mondial + ratio Spike)
#  Python 3.11–3.12
# ============================================================

from typing import Optional, Dict, List, Tuple
import pandas as pd
import numpy as np
import time
import logging
import math
import sys, os
from datetime import datetime
import pytz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.market_data import (
    get_price_history_df, get_ticker_info, get_fx_quote_to_eur,
    ticker_market_zone, is_ticker_market_open, canonical_listing_ticker,
)

logger = logging.getLogger(__name__)



def _finite(value):
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None

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
        "ENR.DE", "TTE", "BP", "SHEL", "ENI.MI",
        "REP.MC", "ENEL.MI", "IBE.MC", "VIE.PA",
    ],
    "EU Defence": [
        "RHM.DE", "AIR.PA", "SAF.PA", "BA.L", "LDO.MI", "AM.PA",
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
        "0857.HK", "0386.HK", "INPEY", "STO.AX",
    ],
    "Global Commodities & ETFs": [
        "GLD", "SLV", "USO", "BNO", "URA", "COPX",
        "IWM", "EEM", "VGK", "EWJ", "MCHI", "EWY",
    ],
}

ALL_TICKERS = [t for sector_tickers in UNIVERSE.values() for t in sector_tickers]

ETF_TICKERS = {
    "XLE", "SOXX", "SMH", "ITA",
    "GLD", "SLV", "USO", "BNO", "URA", "COPX",
    "IWM", "EEM", "VGK", "EWJ", "MCHI", "EWY",
}

CRITERIA = {
    "min_drawdown":   0.30,
    "max_drawdown":   0.55,
    "max_5d_return":  0.04,
    # Short interest is intentionally a scoring factor, not a hard filter.
    # Equities require at least €100M-equivalent TTM revenue; ETFs are exempt.
    "min_revenue_eur": 100_000_000,
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

    tickers = df["ticker"].apply(canonical_listing_ticker).tolist()

    return {
        "tickers": tickers,
        "snapshot_date": snapshot_date,
        "total_in_cache": total_in_cache,
        "cache_empty": False,
    }


def get_wide_universe(exchange: str = "US", min_market_cap: float = 1_000_000_000,
                       max_tickers: int = 500, progress_callback=None) -> List[str]:
    """
    Fallback provider refresh (lent) : à utiliser seulement si le cache est vide, c'est
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
    return [canonical_listing_ticker(s) for s in survivors]


# ============================================================
#  STATUT DES MARCHÉS
# ============================================================

def get_market_status(now=None) -> dict:
    """Return holiday/DST-aware status across the supported listing calendars.

    A region is open when at least one supported exchange in that region is open;
    this avoids calling all of Asia closed just because Tokyo is on holiday while
    Hong Kong or Australia is trading.
    """
    paris_tz = pytz.timezone("Europe/Paris")
    if now is None:
        now_paris = datetime.now(paris_tz)
    elif getattr(now, "tzinfo", None) is None:
        now_paris = paris_tz.localize(now)
    else:
        now_paris = pd.Timestamp(now).tz_convert(paris_tz).to_pydatetime()

    import exchange_calendars as xcals
    minute_utc = pd.Timestamp(now_paris.astimezone(pytz.UTC)).floor("min")
    region_calendars = {
        "Asia": ["XHKG", "XTAI", "XASX", "XTKS"],
        "Europe": ["XPAR", "XETR", "XAMS", "XMAD", "XMIL", "XLON", "XSWX"],
        "USA": ["XNYS"],
    }
    exchange_states = {}
    zones = {}
    for region, names in region_calendars.items():
        states = {}
        for name in names:
            try:
                states[name] = bool(xcals.get_calendar(name).is_open_on_minute(minute_utc))
            except (ValueError, KeyError) as exc:
                logger.warning("Market calendar %s unavailable: %s", name, exc)
                states[name] = False
        exchange_states[region] = states
        zones[region] = any(states.values())

    heure_paris = now_paris.strftime("%Hh%M")
    open_zones = [z for z, is_open in zones.items() if is_open]
    lines = [f"Market hours — **{heure_paris}** Paris time"]
    for zone, is_open in zones.items():
        lines.append(f"- {zone} : {'🟢 Open' if is_open else '🔴 Closed'}")

    return {
        "any_open": bool(open_zones),
        "weekend": now_paris.weekday() >= 5,
        "message": "\n".join(lines),
        "zones": zones,
        "exchange_states": exchange_states,
        "open_zones": open_zones,
        "heure_paris": heure_paris,
        "minute_utc": minute_utc,
        "holiday_aware": True,
    }


def get_open_tickers(status: dict) -> List[str]:
    """Return tickers whose actual listing calendar is open at the status timestamp."""
    minute_utc = status.get("minute_utc")
    if minute_utc is None:
        zones_open = set(status.get("open_zones") or [])
        if not zones_open:
            return []
        return [t for t in ALL_TICKERS if ticker_market_zone(t) in zones_open]
    open_tickers = []
    for ticker in ALL_TICKERS:
        state = is_ticker_market_open(ticker, minute_utc)
        if state is True:
            open_tickers.append(ticker)
    return open_tickers


# ============================================================
#  FETCH, FILTRES & SCORING
# ============================================================

_REVENUE_FX_CACHE: Dict[str, Dict] = {}


def _reporting_currency_fx_to_eur(currency: str) -> Dict:
    currency = (currency or "").upper()
    if not currency:
        return {"rate": None, "source": None, "error": "financial currency unavailable"}
    if currency not in _REVENUE_FX_CACHE:
        _REVENUE_FX_CACHE[currency] = get_fx_quote_to_eur(currency) or {}
    return _REVENUE_FX_CACHE[currency]

def fetch_ticker_data(ticker: str) -> Optional[Dict]:
    """Récupère toutes les données + calcule le ratio Spike."""
    try:
        hist = get_price_history_df(ticker, years=5)

        if hist is None or hist.empty or len(hist) < 21:
            return None

        current_price = _finite(hist["Close"].iloc[-1])

        high_series = (
            pd.to_numeric(hist["High"], errors="coerce")
            .replace([np.inf, -np.inf], np.nan)
        )

        # "5Y High" requires complete High coverage across the history used.
        # max() silently ignores NaN, which could otherwise overstate data
        # completeness and produce a plausible but unsupported drawdown.
        high_5y = (
            _finite(high_series.max())
            if high_series.notna().all()
            else None
        )

        if current_price is None or high_5y is None or high_5y <= 0:
            return None

        drawdown = (current_price - high_5y) / high_5y

        # Returns: invalid provider numerics remain unavailable.
        ret_5d = None
        if len(hist) >= 6:
            p_5d = _finite(hist["Close"].iloc[-6])
            if p_5d is not None and p_5d > 0:
                ret_5d = (current_price - p_5d) / p_5d

        ret_1d = None
        if len(hist) >= 2:
            p_1d = _finite(hist["Close"].iloc[-2])
            if p_1d is not None and p_1d > 0:
                ret_1d = (current_price - p_1d) / p_1d

        # Relative volume = latest bar / mean of the *previous* 20 sessions.
        # The latest bar may be partial intraday; therefore this is a heuristic,
        # not evidence of institutional accumulation.
        volume_series = pd.to_numeric(hist["Volume"], errors="coerce").replace([np.inf, -np.inf], np.nan)
        avg_volume = _finite(volume_series.iloc[-21:-1].mean())
        vol_today = _finite(volume_series.iloc[-1])
        rel_volume = None
        if avg_volume is not None and avg_volume > 0 and vol_today is not None and vol_today >= 0:
            rel_volume = vol_today / avg_volume

        # 20-session annualised volatility
        returns = (pd.to_numeric(hist["Close"], errors="coerce")
                   .replace([np.inf, -np.inf], np.nan)
                   .pct_change()
                   .replace([np.inf, -np.inf], np.nan)
                   .dropna())
        vol_20d = _finite(returns.tail(20).std())
        volatility_annual = vol_20d * (252 ** 0.5) if vol_20d is not None else None

        # ── RATIO SPIKE ──────────────────────────────────────
        # Heuristic: 5-session return scaled by recent daily volatility.
        # This is a price-behaviour feature only; it does not establish cause,
        # institutional activity or fundamental justification.
        spike_ratio = None
        if ret_5d is not None and vol_20d is not None and vol_20d > 0:
            spike_ratio = round(ret_5d / (vol_20d * (5 ** 0.5)), 3)

        # ── SPIKE HISTORIQUE ─────────────────────────────────
        # Percentile of the current heuristic versus aligned historical observations.
        spike_percentile = None
        if len(hist) >= 60 and vol_20d is not None and vol_20d > 0:
            close_numeric = pd.to_numeric(hist["Close"], errors="coerce").replace([np.inf, -np.inf], np.nan)
            hist_returns_5d = close_numeric.pct_change(5)
            daily_returns = close_numeric.pct_change()
            hist_vol = daily_returns.rolling(20).std()
            aligned = pd.concat([hist_returns_5d.rename("r5"), hist_vol.rename("vol")], axis=1).dropna()
            aligned = aligned[aligned["vol"] > 0]
            if len(aligned) > 20 and spike_ratio is not None:
                hist_spikes = aligned["r5"] / (aligned["vol"] * (5 ** 0.5))
                # Compare the current observation only with *prior* history.
                # Including the current point in its own reference distribution
                # biases the percentile and weakens outlier interpretation.
                hist_reference = hist_spikes.iloc[:-1].dropna()
                if not hist_reference.empty:
                    spike_percentile = round(float((hist_reference < spike_ratio).mean()) * 100, 1)

        # Support 52 semaines. min() ignores NaN by default, so require full
        # Low coverage over the actual support window rather than pretending
        # that the minimum of the available subset is the observed support.
        low_window = (
            hist["Low"].tail(252)
            if len(hist) >= 252
            else hist["Low"]
        )
        low_window = (
            pd.to_numeric(low_window, errors="coerce")
            .replace([np.inf, -np.inf], np.nan)
        )

        low_52w = (
            _finite(low_window.min())
            if low_window.notna().all()
            else None
        )

        dist_to_support = (
            (current_price - low_52w) / low_52w
            if low_52w is not None and low_52w > 0
            else None
        )

        # Fundamentals come from the unified market-data boundary; the current
        # implementation sources this family from yfinance and exposes provenance.
        info = get_ticker_info(ticker)

        short_raw = info.get("short_pct_float")
        short_pct = _finite(short_raw)
        total_rev_native = _finite(info.get("revenue")) if info.get("fundamentals_available") else None
        instrument_type = (info.get("instrument_type") or "").upper() or ("ETF" if ticker in ETF_TICKERS else None)
        financial_currency = (info.get("financial_currency") or "").upper() or None
        revenue_eur = None
        revenue_fx_source = None
        revenue_fx_timestamp = None
        revenue_fx_stale = None
        revenue_fx_error = None
        if instrument_type not in {"ETF", "MUTUALFUND"} and total_rev_native is not None:
            fx_quote = _reporting_currency_fx_to_eur(financial_currency)
            revenue_fx = _finite(fx_quote.get("rate"))
            revenue_fx_source = fx_quote.get("source")
            revenue_fx_timestamp = fx_quote.get("timestamp")
            revenue_fx_stale = fx_quote.get("stale")
            revenue_fx_error = fx_quote.get("error")
            if revenue_fx is not None and revenue_fx > 0 and revenue_fx_stale is False:
                revenue_eur = total_rev_native * revenue_fx
            elif revenue_fx_stale:
                revenue_fx_error = revenue_fx_error or f"{financial_currency or 'unknown'}->EUR FX is stale"
            elif revenue_fx_error is None:
                revenue_fx_error = f"{financial_currency or 'unknown'}->EUR FX unavailable"
        name = info.get("name", ticker)

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
            "high_5y":           round(high_5y, 4),
            "drawdown_pct":      round(drawdown, 4),
            "ret_5d":            round(ret_5d, 4) if ret_5d is not None else None,
            "ret_1d":            round(ret_1d, 4) if ret_1d is not None else None,
            "avg_volume":        round(avg_volume) if avg_volume is not None else None,
            "rel_volume":        round(rel_volume, 2) if rel_volume is not None else None,
            "volatility":        round(volatility_annual, 4) if volatility_annual is not None else None,
            "vol_20d_daily":     round(vol_20d, 4) if vol_20d is not None else None,
            "spike_ratio":       spike_ratio,
            "spike_percentile":  spike_percentile,
            "dist_to_support":   round(dist_to_support, 4) if dist_to_support is not None else None,
            "short_pct":         round(short_pct, 4) if short_pct is not None else None,
            "total_revenue":     total_rev_native,
            "revenue_currency":  financial_currency,
            "revenue_eur":       revenue_eur,
            "revenue_fx_source": revenue_fx_source,
            "revenue_fx_timestamp": revenue_fx_timestamp,
            "revenue_fx_stale": revenue_fx_stale,
            "revenue_fx_error":  revenue_fx_error,
            "fundamentals_available": info.get("fundamentals_available", False),
            "fundamentals_error": info.get("fundamentals_error"),
            "fundamentals_source": info.get("fundamentals_source"),
            "instrument_type": instrument_type,
        }
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        logger.warning("Screener data calculation failed for %s: %s", ticker, exc)
        return None


def apply_filters(data: Dict) -> Tuple[bool, List[str]]:
    """Apply eligibility criteria; unavailable/invalid required data always fails safely."""
    failed = []

    dd = _finite(data.get("drawdown_pct"))
    if dd is None:
        failed.append("5Y-high drawdown unavailable")
    elif not (-CRITERIA["max_drawdown"] <= dd <= -CRITERIA["min_drawdown"]):
        failed.append(f"Drawdown {dd*100:.1f}% outside range [{CRITERIA['min_drawdown']*100:.0f}%-{CRITERIA['max_drawdown']*100:.0f}%]")

    r5 = _finite(data.get("ret_5d"))
    if r5 is None:
        failed.append("5-session return unavailable/invalid")
    elif r5 > CRITERIA["max_5d_return"]:
        failed.append(f"Recent run +{r5*100:.1f}% over 5 sessions (max {CRITERIA['max_5d_return']*100:.0f}%)")

    avg_volume = _finite(data.get("avg_volume"))
    if avg_volume is None:
        failed.append("Average volume unavailable/invalid")
    elif avg_volume < CRITERIA["min_avg_volume"]:
        failed.append(f"Insufficient avg volume ({avg_volume:,.0f} < {CRITERIA['min_avg_volume']:,})")

    instrument_type = (data.get("instrument_type") or "").upper()
    is_fund = instrument_type in {"ETF", "MUTUALFUND"}
    if not is_fund:
        revenue_native = _finite(data.get("total_revenue"))
        revenue_eur = _finite(data.get("revenue_eur"))
        if revenue_native is None:
            failed.append("Fundamentals unavailable — equity revenue eligibility not evaluated")
        elif revenue_eur is None:
            failed.append("Revenue FX unavailable — €-equivalent revenue eligibility not evaluated")
        elif revenue_eur < CRITERIA["min_revenue_eur"]:
            failed.append(f"TTM revenue below €{CRITERIA['min_revenue_eur']/1e6:.0f}M equivalent")

    return len(failed) == 0, failed


def compute_score(data: Dict) -> Dict:
    """
    Score 0-100 sur 6 dimensions incluant le ratio Spike.

    The spike component is a transparent mean-reversion heuristic based only
    on supplied price history; it does not infer the cause of the move.
    """
    # 1. Drawdown (idéal ~38%)
    dd_raw = _finite(data.get("drawdown_pct"))
    dd_score = 0 if dd_raw is None else max(0, min(100, 100 - abs(abs(dd_raw) - 0.38) * 400))

    # 2. Momentum inversé (correction récente = opportunité)
    r5 = _finite(data.get("ret_5d"))
    mom_score = 0 if r5 is None else max(0, min(100, 50 - r5 * 800))

    # 3. Short interest (squeeze potentiel, optimal 10-20%)
    si = _finite(data.get("short_pct"))
    si_score = 0 if si is None else max(0, min(100, 100 - abs(si - 0.15) * 500))

    # 4. Relative volume heuristic
    rv = _finite(data.get("rel_volume"))
    vol_score = 0 if rv is None or rv < 0 else min(100, rv * 40)

    # 5. Support (proche du bas = meilleur R/R)
    dist = _finite(data.get("dist_to_support"))
    sup_score = 0 if dist is None or dist < 0 else max(0, min(100, 100 - dist * 200))

    # 6. Ratio Spike
    # Spike très négatif (panique) dans le bas du percentile historique
    # = signal fort de retournement prochain
    spike = _finite(data.get("spike_ratio"))
    spike_pct = _finite(data.get("spike_percentile"))
    spike_score = 0  # unavailable data must never improve ranking
    if spike is not None and spike_pct is not None:
        if spike < -1.0 and spike_pct < 15:
            # Extreme negative standardized move -> high mean-reversion score
            spike_score = 90
        elif spike < -0.5 and spike_pct < 30:
            # Strong negative standardized move
            spike_score = 75
        elif spike < 0:
            # Mild negative standardized move
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
    dimensions = [dd_raw, r5, si, rv, dist, spike if spike_pct is not None else None]
    data_coverage_pct = round(sum(x is not None for x in dimensions) / len(dimensions) * 100, 1)

    return {
        "score_total":         round(max(0, min(100, total)), 1),
        "score_drawdown":      round(dd_score, 1),
        "score_momentum":      round(mom_score, 1),
        "score_short_squeeze": round(si_score, 1),
        "score_volume":        round(vol_score, 1),
        "score_support":       round(sup_score, 1),
        "score_spike":         round(spike_score, 1),
        "data_coverage_pct":   data_coverage_pct,
    }


def run_screener(tickers=None, progress_callback=None) -> pd.DataFrame:
    """Run the screener with a fresh per-scan reporting-currency FX cache."""
    _REVENUE_FX_CACHE.clear()
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
            "rel_volume", "spike_ratio", "score_total", "data_coverage_pct", "passes_filter"]

    display = df[[c for c in cols if c in df.columns]].copy()

    display["drawdown_pct"]  = display["drawdown_pct"].apply(lambda x: f"{_finite(x)*100:.1f}%" if _finite(x) is not None else "N/A")
    display["ret_5d"]        = display["ret_5d"].apply(lambda x: f"{_finite(x)*100:+.1f}%" if _finite(x) is not None else "N/A")
    display["short_pct"]     = display["short_pct"].apply(
        lambda x: f"{x*100:.1f}%" if pd.notna(x) else "N/A"
    )
    display["rel_volume"]    = display["rel_volume"].apply(lambda x: f"{x:.1f}x" if _finite(x) is not None else "N/A")
    display["spike_ratio"]   = display["spike_ratio"].apply(lambda x: f"{_finite(x):+.2f}" if _finite(x) is not None else "N/A")
    display["score_total"]   = display["score_total"].apply(lambda x: f"{_finite(x):.0f}/100" if _finite(x) is not None else "N/A")
    if "data_coverage_pct" not in display.columns:
        display["data_coverage_pct"] = None
    display["data_coverage_pct"] = display["data_coverage_pct"].apply(lambda x: f"{_finite(x):.0f}%" if _finite(x) is not None else "N/A")
    display["passes_filter"] = display["passes_filter"].apply(lambda x: "✅" if x else "❌")

    display.columns = ["Ticker", "Name", "Sector", "Price",
                       "5Y High Drawdown", "5d Return", "Short %",
                       "Rel. Volume", "Spike Ratio", "Score", "Data Coverage", "Criteria"]
    return display
