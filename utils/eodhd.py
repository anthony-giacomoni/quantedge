# ============================================================
#  QuantEdge — EODHD API Wrapper
#  Replaces yfinance for all market data
# ============================================================

import urllib.request
import urllib.parse
import urllib.error
import json
import os
from typing import Optional, Dict, List
from datetime import datetime, timedelta

API_KEY = os.getenv("EODHD_API_KEY")
BASE    = "https://eodhd.com/api"

if not API_KEY:
    raise RuntimeError(
        "EODHD_API_KEY manquante. Ajoute-la dans ton fichier .env "
        "(EODHD_API_KEY=ta_cle_ici)."
    )

# Dernière erreur rencontrée, pour que l'UI puisse afficher *pourquoi* un
# appel a échoué plutôt que juste "pas de données". Réinitialisée à chaque _get().
LAST_ERROR: Optional[str] = None


def _get(endpoint: str, params: Dict = {}) -> Optional[dict]:
    global LAST_ERROR
    LAST_ERROR = None
    params["api_token"] = API_KEY
    params["fmt"]       = "json"
    url = f"{BASE}/{endpoint}?{urllib.parse.urlencode(params)}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "QuantEdge/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            pass
        if e.code == 403:
            LAST_ERROR = (
                f"403 Forbidden sur '{endpoint}' — soit ta clé n'a pas accès à cet "
                f"endpoint (le temps réel 'real-time' nécessite parfois un add-on "
                f"séparé du plan EOD de base), soit la clé n'est pas/plus activée. "
                f"Réponse EODHD : {body or '(vide)'}"
            )
        elif e.code == 401:
            LAST_ERROR = f"401 Unauthorized sur '{endpoint}' — clé API invalide. Réponse : {body or '(vide)'}"
        elif e.code == 429:
            LAST_ERROR = f"429 Too Many Requests sur '{endpoint}' — limite de débit atteinte."
        else:
            LAST_ERROR = f"HTTP {e.code} sur '{endpoint}' : {body or '(vide)'}"
        print(f"EODHD error {endpoint}: {LAST_ERROR}")
        return None
    except Exception as e:
        LAST_ERROR = f"Erreur réseau sur '{endpoint}' : {e}"
        print(f"EODHD error {endpoint}: {LAST_ERROR}")
        return None


def _ticker(ticker: str) -> str:
    """Convert ticker to EODHD format."""
    # European ETFs
    if ticker.endswith(".PA"):   return ticker.replace(".PA", ".PA")
    if ticker.endswith(".DE"):   return ticker.replace(".DE", ".XETRA")
    if ticker.endswith(".MI"):   return ticker.replace(".MI", ".MI")
    if ticker.endswith(".AS"):   return ticker.replace(".AS", ".AS")
    if ticker.endswith(".MC"):   return ticker.replace(".MC", ".MC")
    if ticker.endswith(".L"):    return ticker.replace(".L", ".LSE")
    if ticker.endswith(".HK"):   return ticker
    if ticker.endswith(".TW"):   return ticker
    # US stocks — add .US
    if "." not in ticker:        return f"{ticker}.US"
    return ticker


def get_usd_eur_rate() -> Optional[float]:
    """
    Retourne le taux de conversion USD → EUR (combien d'euros pour 1 dollar).
    Utilise la paire forex EURUSD d'EODHD : EURUSD = combien de USD pour 1 EUR,
    donc USD→EUR = 1 / EURUSD.
    """
    data = _get("real-time/EURUSD.FOREX")
    rate = None
    if isinstance(data, dict):
        rate = data.get("close") or data.get("last")
    if not rate:
        eod = _get("eod/EURUSD.FOREX", {"limit": 1})
        if isinstance(eod, list) and eod:
            rate = eod[-1].get("close")
    if not rate:
        return None
    try:
        return round(1 / float(rate), 6)
    except (ValueError, ZeroDivisionError):
        return None


import time as _time

IS_STALE_PRICE: bool = False  # True si le prix affiché date de plus d'un jour de bourse
LAST_QUOTE_DEBUG: dict = {}   # dernier appel get_current_price : ticker/price/timestamp/age_hours/source


def get_current_price(ticker: str) -> Optional[float]:
    """
    Current price via real-time (15-min delayed) endpoint. Uses the response's
    own 'timestamp' field to detect whether the quote is actually recent —
    rather than assuming freshness just because the endpoint responded, since
    EODHD can return HTTP 200 with a stale previous-session quote (e.g. when
    markets are closed or between sessions).
    """
    global IS_STALE_PRICE, LAST_QUOTE_DEBUG
    IS_STALE_PRICE = False
    t = _ticker(ticker)
    data = _get(f"real-time/{t}")

    price = None
    ts = None
    if isinstance(data, dict) and (data.get("close") or data.get("last")):
        price = data.get("close") or data.get("last")
        ts = data.get("timestamp")
    elif isinstance(data, list) and data and data[0].get("close"):
        price = data[0].get("close")
        ts = data[0].get("timestamp")

    if price is not None:
        age_hours = None
        # Un quote de plus de 36h (couvre un jour de bourse + weekend court)
        # est considéré périmé — ex: marché fermé, données de la veille resservies.
        if ts:
            age_hours = (_time.time() - float(ts)) / 3600
            if age_hours > 36:
                IS_STALE_PRICE = True
        LAST_QUOTE_DEBUG = {
            "ticker": ticker, "price": price, "timestamp": ts,
            "age_hours": round(age_hours, 1) if age_hours is not None else None,
            "source": "real-time", "is_stale": IS_STALE_PRICE,
        }
        return price

    # Fallback: last EOD (previous close, not live — real-time may not be on this plan)
    IS_STALE_PRICE = True
    eod = _get(f"eod/{t}", {"limit": 1})
    if isinstance(eod, list) and eod:
        fallback_price = float(eod[-1]["close"])
        LAST_QUOTE_DEBUG = {
            "ticker": ticker, "price": fallback_price, "timestamp": None,
            "age_hours": None, "source": "eod-fallback", "is_stale": True,
        }
        return fallback_price
    LAST_QUOTE_DEBUG = {"ticker": ticker, "price": None, "source": "none", "is_stale": True}
    return None


def get_eod_history(ticker: str, years: int = 5) -> Optional[List[Dict]]:
    """End-of-day historical data."""
    t = _ticker(ticker)
    date_from = (datetime.now() - timedelta(days=years*365)).strftime("%Y-%m-%d")
    return _get(f"eod/{t}", {"from": date_from, "period": "d"})


def get_52w_stats(ticker: str) -> Optional[Dict]:
    """
    Récupère en UN seul appel API le prix de clôture le plus récent et le
    haut/bas sur 1 an. Utilisé par refresh_universe.py pour ne pas doubler
    le nombre d'appels lors du remplissage du cache (pas besoin des 5 ans
    complets utilisés ailleurs par get_ath/get_drawdown_from_ath).
    """
    t = _ticker(ticker)
    date_from = (datetime.now() - timedelta(days=370)).strftime("%Y-%m-%d")
    hist = _get(f"eod/{t}", {"from": date_from, "period": "d"})
    if not hist or not isinstance(hist, list):
        return None
    try:
        closes = [float(d["close"]) for d in hist]
        highs  = [float(d["high"]) for d in hist]
        lows   = [float(d["low"]) for d in hist]
        return {
            "close_price": round(closes[-1], 4),
            "high_52w":    round(max(highs), 4),
            "low_52w":     round(min(lows), 4),
        }
    except (KeyError, ValueError, IndexError):
        return None


def get_ath(ticker: str) -> Optional[float]:
    """All-time high from 5-year history."""
    hist = get_eod_history(ticker, years=5)
    if not hist:
        return None
    return max(float(d["high"]) for d in hist)


def get_drawdown_from_ath(ticker: str) -> Optional[Dict]:
    """ATH drawdown calculation."""
    hist = get_eod_history(ticker, years=5)
    if not hist:
        return None
    ath     = max(float(d["high"]) for d in hist)
    current = float(hist[-1]["close"])
    return {
        "ath":          round(ath, 4),
        "current":      round(current, 4),
        "drawdown_pct": round((current - ath) / ath, 4),
    }


def get_5d_return(ticker: str) -> Optional[float]:
    """5-day return."""
    t = _ticker(ticker)
    hist = _get(f"eod/{t}", {"limit": 10})
    if not hist or len(hist) < 5:
        return None
    price_now = float(hist[-1]["close"])
    price_5d  = float(hist[-5]["close"])
    return round((price_now - price_5d) / price_5d, 4)


def get_fundamentals(ticker: str) -> Dict:
    """Full fundamentals — PE, EV/EBITDA, revenue, short interest etc."""
    t    = _ticker(ticker)
    data = _get(f"fundamentals/{t}")
    if not data:
        return {}

    highlights = data.get("Highlights", {})
    valuation  = data.get("Valuation", {})
    stats      = data.get("SharesStats", {})
    general    = data.get("General", {})

    return {
        "name":             general.get("Name", ticker),
        "sector":           general.get("Sector", "N/A"),
        "industry":         general.get("Industry", "N/A"),
        "market_cap":       highlights.get("MarketCapitalization"),
        "pe_ratio":         highlights.get("PERatio"),
        "forward_pe":       highlights.get("ForwardPE"),
        "ev_ebitda":        valuation.get("EnterpriseValueEbitda"),
        "price_to_book":    highlights.get("PriceBookMRQ"),
        "price_to_sales":   highlights.get("PriceSalesTTM"),
        "revenue":          highlights.get("RevenueTTM"),
        "revenue_growth":   highlights.get("RevenueGrowth"),
        "profit_margin":    highlights.get("ProfitMargin"),
        "return_on_equity": highlights.get("ReturnOnEquityTTM"),
        "short_pct":        stats.get("ShortPercentFloat"),
        "description":      general.get("Description", "")[:500],
    }


def get_ticker_info(ticker: str) -> Dict:
    """Alias for get_fundamentals — used by ai_analysis."""
    f = get_fundamentals(ticker)
    return {
        "name":            f.get("name", ticker),
        "sector":          f.get("sector", "N/A"),
        "short_pct_float": f.get("short_pct"),
        "pe_ratio":        f.get("pe_ratio"),
        "ev_ebitda":       f.get("ev_ebitda"),
        "revenue":         f.get("revenue"),
    }


def get_exchange_tickers(exchange: str = "US", instrument_type: str = "common_stock") -> List[str]:
    """
    Liste tous les tickers d'une bourse via l'endpoint gratuit
    /api/exchange-symbol-list/{EXCHANGE} (pas le Screener premium).
    Retourne des tickers déjà au format EODHD (ex: 'AAPL.US').
    """
    data = _get(f"exchange-symbol-list/{exchange}", {"type": instrument_type})
    if not isinstance(data, list):
        return []
    tickers = []
    for row in data:
        code = row.get("Code")
        if code:
            tickers.append(f"{code}.{exchange}")
    return tickers


def funnel_screen(tickers: List[str], min_market_cap: float = 1_000_000_000,
                   progress_callback=None) -> List[str]:
    """
    Entonnoir de filtrage en cascade, sans le Screener API premium (non
    disponible sur tous les plans EODHD). À chaque étape, seuls les tickers
    ayant passé l'étape précédente consomment un appel API pour l'étape
    suivante — ça limite le nombre d'appels coûteux (fondamentaux) sur un
    grand univers de départ.

    Étape 1 — Market cap (1 appel fundamentals/ticker, le plus cher)
        -> Sous cette étape, tout ticker en dessous du seuil est éliminé.

    Retourne la liste des tickers survivants (au format EODHD, ex: 'AAPL.US').
    Le calcul drawdown/5d-return/spike se fait ensuite dans screener.py
    via fetch_ticker_data, comme pour la watchlist actuelle.
    """
    survivors = []
    total = len(tickers)
    for i, ticker in enumerate(tickers):
        if progress_callback:
            progress_callback(i / total, f"[{i+1}/{total}] Checking {ticker}...")

        fund = get_fundamentals(ticker)
        if not fund:
            continue

        market_cap = fund.get("market_cap")
        if market_cap is None:
            continue
        try:
            if float(market_cap) < min_market_cap:
                continue  # étape 1 échouée : dégagé, pas d'appel supplémentaire
        except (TypeError, ValueError):
            continue

        survivors.append(ticker)

    return survivors
