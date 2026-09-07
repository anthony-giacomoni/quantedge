# ============================================================
#  QuantEdge — EODHD API Wrapper
#  EODHD price/history provider used behind utils.market_data
# ============================================================

import urllib.request
import urllib.parse
import urllib.error
import json
import logging
import os
import math
import pandas as pd
from typing import Optional, Dict, List
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from utils.runtime import configure_runtime
from utils.market_calendar import is_market_timestamp_stale, is_fx_timestamp_stale

configure_runtime()
load_dotenv()
logger = logging.getLogger(__name__)

API_KEY = os.getenv("EODHD_API_KEY")
BASE    = "https://eodhd.com/api"

# Dernière erreur rencontrée, pour que l'UI puisse afficher *pourquoi* un
# appel a échoué plutôt que juste "pas de données". Réinitialisée à chaque _get().
LAST_ERROR: Optional[str] = None

_EODHD_CALENDAR_SUFFIX = {
    ".PA": "XPAR", ".DE": "XETR", ".MI": "XMIL", ".AS": "XAMS", ".MC": "XMAD",
    ".L": "XLON", ".HK": "XHKG", ".TW": "XTAI", ".AX": "XASX", ".TO": "XTSE", ".SW": "XSWX",
}


def _calendar_for_ticker(ticker: str) -> Optional[str]:
    upper = (ticker or "").upper().strip()

    if not upper:
        return None

    # Yahoo futures/FX dialects are not US-equity listings.
    if upper.endswith(("=F", "=X")):
        return None

    for suffix, calendar in _EODHD_CALENDAR_SUFFIX.items():
        if upper.endswith(suffix):
            return calendar

    return "XNYS" if "." not in upper else None




def _positive_finite(value) -> Optional[float]:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None



def _finite(value) -> Optional[float]:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _clean_eod_rows(rows) -> List[Dict]:
    """Keep chronologically ordered EOD rows with finite positive close prices."""
    if not isinstance(rows, list):
        return []
    cleaned = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        close = _positive_finite(row.get("close"))
        if close is None:
            continue
        date_value = row.get("date")
        if not date_value:
            continue
        item = dict(row)
        item["close"] = close
        for key in ("open", "high", "low"):
            value = _positive_finite(row.get(key))
            item[key] = value
        volume = _finite(row.get("volume"))
        item["volume"] = volume if volume is not None and volume >= 0 else None
        cleaned.append(item)
    cleaned.sort(key=lambda r: str(r.get("date")))
    return cleaned

def _get(endpoint: str, params: Optional[Dict] = None) -> Optional[dict]:
    global LAST_ERROR
    LAST_ERROR = None
    if not API_KEY:
        LAST_ERROR = "EODHD_API_KEY missing"
        return None
    params = dict(params or {})
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
        except OSError as exc:
            logger.debug("Could not read EODHD HTTP error body: %s", exc)
        if e.code == 403:
            LAST_ERROR = (
                f"403 Forbidden sur '{endpoint}' — la clé actuelle n'est pas autorisée "
                f"à utiliser cet endpoint avec son entitlement EODHD. "
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
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        LAST_ERROR = f"Network/provider error on '{endpoint}': {exc}"
        logger.warning("EODHD %s", LAST_ERROR)
        return None



def _ticker(ticker: str) -> str:
    """Convert ticker to EODHD format."""

    # European ETFs / exchange dialects
    if ticker.endswith(".PA"):
        return ticker.replace(".PA", ".PA")

    if ticker.endswith(".DE"):
        return ticker.replace(".DE", ".XETRA")

    if ticker.endswith(".MI"):
        return ticker.replace(".MI", ".MI")

    if ticker.endswith(".AS"):
        return ticker.replace(".AS", ".AS")

    if ticker.endswith(".MC"):
        return ticker.replace(".MC", ".MC")

    if ticker.endswith(".L"):
        return ticker.replace(".L", ".LSE")

    if ticker.endswith(".HK"):
        return ticker

    if ticker.endswith(".TW"):
        return ticker

    if ticker.endswith(".AX"):
        return ticker[:-3] + ".AU"

    if ticker.endswith(".TO"):
        return ticker

    if ticker.endswith(".SW"):
        return ticker

    # Yahoo futures / FX dialects are not EODHD US equity symbols.
    # Do not fabricate ".US".
    if ticker.upper().endswith(("=F", "=X")):
        return ticker

    # Ordinary US stocks — add .US.
    if "." not in ticker:
        return f"{ticker}.US"

    return ticker



def get_usd_eur_quote() -> Dict:
    """Structured USD->EUR quote with source/freshness metadata."""
    import time as _time_local
    data = _get("real-time/EURUSD.FOREX")
    delayed_error = LAST_ERROR
    rate = None
    ts = None
    if isinstance(data, dict):
        rate = _positive_finite(data.get("close") or data.get("last"))
        ts = data.get("timestamp")
    if rate is not None:
        try:
            usd_eur = 1 / rate
            ts_num = float(ts) if ts is not None else None
            age_hours = ((_time_local.time() - ts_num) / 3600) if ts_num is not None else None
            timestamp = datetime.fromtimestamp(ts_num, tz=timezone.utc).isoformat() if ts_num is not None else None
            return {
                "rate": round(usd_eur, 8),
                "source": "EODHD delayed FX",
                "timestamp": timestamp,
                "age_hours": round(age_hours, 1) if age_hours is not None else None,
                "stale": True if timestamp is None else is_fx_timestamp_stale(timestamp),
                "error": None if timestamp is not None else "FX quote timestamp unavailable",
                "fallback_reason": None,
            }
        except (ValueError, TypeError, OSError) as exc:
            delayed_error = delayed_error or f"invalid delayed EURUSD payload: {exc}"
            logger.warning("Invalid EODHD delayed EURUSD quote: %s", exc)
    elif isinstance(data, dict):
        delayed_error = delayed_error or "invalid/non-positive delayed EURUSD quote"

    eod = _get("eod/EURUSD.FOREX", {"limit": 1})
    if isinstance(eod, list) and eod:
        eod_rate = _positive_finite(eod[-1].get("close"))
        if eod_rate is not None:
            try:
                usd_eur = 1 / eod_rate
                date_value = eod[-1].get("date")
                timestamp = None
                if date_value:
                    timestamp = datetime.fromisoformat(str(date_value)).replace(tzinfo=timezone.utc)
                age_hours = (datetime.now(timezone.utc) - timestamp).total_seconds() / 3600 if timestamp else None
                return {
                    "rate": round(usd_eur, 8), "source": "EODHD FX EOD fallback",
                    "timestamp": timestamp.isoformat() if timestamp else None,
                    "age_hours": round(age_hours, 1) if age_hours is not None else None,
                    "stale": True, "error": None,
                    "fallback_reason": delayed_error or "delayed FX quote unavailable; used EOD",
                }
            except (ValueError, TypeError, ZeroDivisionError) as exc:
                logger.warning("Invalid EODHD EOD EURUSD quote: %s", exc)

    return {
        "rate": None, "source": "EODHD FX", "timestamp": None,
        "age_hours": None, "stale": True,
        "error": delayed_error or LAST_ERROR or "USD/EUR FX unavailable",
        "fallback_reason": delayed_error,
    }


import time as _time

QUOTE_DEBUG_BY_TICKER: dict = {}

def get_quote(ticker: str) -> Dict:
    """Return a structured delayed/latest-available EODHD quote."""
    t = _ticker(ticker)
    data = _get(f"real-time/{t}")
    delayed_error = LAST_ERROR

    price_raw = None
    ts = None
    if isinstance(data, dict):
        price_raw = data.get("close") if data.get("close") is not None else data.get("last")
        ts = data.get("timestamp")
    elif isinstance(data, list) and data:
        price_raw = data[0].get("close")
        ts = data[0].get("timestamp")

    price_num = _positive_finite(price_raw)
    quote = None
    if price_num is not None:
        timestamp = None
        age_hours = None
        stale = True
        timestamp_error = None
        if ts is not None:
            try:
                ts_num = float(ts)
                timestamp = datetime.fromtimestamp(ts_num, tz=timezone.utc).isoformat()
                age_hours = (_time.time() - ts_num) / 3600
                stale = is_market_timestamp_stale(_calendar_for_ticker(ticker), timestamp, intraday_max_age_minutes=90)
            except (TypeError, ValueError, OSError) as exc:
                timestamp_error = f"invalid quote timestamp: {exc}"
                logger.warning("Invalid EODHD timestamp for %s: %s", ticker, exc)
        else:
            timestamp_error = "quote timestamp unavailable"
        quote = {
            "ticker": ticker, "price": price_num, "timestamp": timestamp,
            "age_hours": round(age_hours, 1) if age_hours is not None else None,
            "source": "EODHD delayed quote", "stale": stale,
            "error": timestamp_error,
            "fallback_reason": None,
        }
    else:
        if data is not None:
            delayed_error = delayed_error or "invalid/non-positive delayed quote"

        eod = _get(f"eod/{t}", {"limit": 1})
        if isinstance(eod, list) and eod:
            eod_price = _positive_finite(eod[-1].get("close"))
            if eod_price is not None:
                quote = {
                    "ticker": ticker, "price": eod_price,
                    "timestamp": eod[-1].get("date"), "age_hours": None,
                    "source": "EODHD EOD fallback", "stale": is_market_timestamp_stale(_calendar_for_ticker(ticker), eod[-1].get("date")),
                    "error": None,
                    "fallback_reason": delayed_error or "delayed quote unavailable; used EOD",
                }

    if quote is None:
        quote = {
            "ticker": ticker, "price": None, "timestamp": None,
            "age_hours": None, "source": "EODHD", "stale": True,
            "error": delayed_error or LAST_ERROR or "no usable quote returned",
            "fallback_reason": delayed_error,
        }

    QUOTE_DEBUG_BY_TICKER[ticker.upper()] = quote.copy()
    return quote


def get_eod_history(ticker: str, years: int = 5) -> Optional[List[Dict]]:
    """Validated end-of-day historical data."""
    t = _ticker(ticker)
    date_from = (datetime.now() - pd.DateOffset(years=years)).strftime("%Y-%m-%d")
    rows = _clean_eod_rows(_get(f"eod/{t}", {"from": date_from, "period": "d"}))
    return rows or None


def get_52w_stats(ticker: str) -> Optional[Dict]:
    """Return validated latest close and 52-week high/low from one EOD call."""
    t = _ticker(ticker)
    date_from = (datetime.now() - timedelta(days=370)).strftime("%Y-%m-%d")
    hist = _clean_eod_rows(_get(f"eod/{t}", {"from": date_from, "period": "d"}))
    if not hist:
        return None
    closes = [r["close"] for r in hist]
    highs = [r.get("high") for r in hist if r.get("high") is not None]
    lows = [r.get("low") for r in hist if r.get("low") is not None]
    if not highs or not lows:
        return None
    return {
        "close_price": round(closes[-1], 4),
        "high_52w": round(max(highs), 4),
        "low_52w": round(min(lows), 4),
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

# ── Event/news feeds ---------------------------------------------------------

def get_economic_events(from_date: str, to_date: str, limit: int = 1000):
    """Provider-native economic events payload for the requested date window."""
    return _get("economic-events", {
        "from": from_date,
        "to": to_date,
        "limit": max(1, min(int(limit), 1000)),
    })


def get_earnings_calendar(from_date: str, to_date: str, symbols: Optional[List[str]] = None):
    """Provider-native upcoming earnings payload for a date window."""
    params = {"from": from_date, "to": to_date}
    clean = []
    for symbol in symbols or []:
        s = str(symbol or "").strip().upper()
        if not s:
            continue
        mapped = _ticker(s)
        if mapped not in clean:
            clean.append(mapped)
    if clean:
        params["symbols"] = ",".join(clean)
    return _get("calendar/earnings", params)


def get_news(ticker: str, from_date: Optional[str] = None, limit: int = 10):
    """Provider-native recent financial-news payload for one ticker."""
    params = {
        "s": _ticker(str(ticker).strip().upper()),
        "limit": max(1, min(int(limit), 100)),
    }
    if from_date:
        params["from"] = from_date
    return _get("news", params)
