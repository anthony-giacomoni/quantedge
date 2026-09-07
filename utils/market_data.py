# ============================================================
#  QuantEdge — Unified Market Data Layer
#  Python 3.11–3.12
# ============================================================

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Dict, List
import logging
import os
import math

import pandas as pd
import yfinance as yf
from dotenv import load_dotenv

from utils.runtime import configure_runtime
from utils.market_calendar import is_market_timestamp_stale, is_fx_timestamp_stale

configure_runtime()
load_dotenv()
logger = logging.getLogger(__name__)

EODHD_KEY = os.getenv("EODHD_API_KEY")

# Explicit quote-currency mapping by exchange suffix. Unsuffixed symbols in this
# project are US listings and therefore USD-quoted.
_SUFFIX_CURRENCY = {
    ".PA": "EUR", ".DE": "EUR", ".AS": "EUR", ".MC": "EUR", ".MI": "EUR",
    ".L": "GBP", ".HK": "HKD", ".TW": "TWD", ".AX": "AUD", ".TO": "CAD",
    ".SW": "CHF",
}


_SUFFIX_CALENDAR = {
    ".PA": "XPAR", ".DE": "XETR", ".AS": "XAMS", ".MC": "XMAD", ".MI": "XMIL",
    ".L": "XLON", ".HK": "XHKG", ".TW": "XTAI", ".AX": "XASX", ".TO": "XTSE",
    ".SW": "XSWX",
}

_SUFFIX_MARKET_ZONE = {
    ".PA": "Europe", ".DE": "Europe", ".AS": "Europe", ".MC": "Europe",
    ".MI": "Europe", ".L": "Europe", ".SW": "Europe",
    ".HK": "Asia", ".TW": "Asia", ".AX": "Asia",
    ".TO": "USA",  # North-American trading session proxy
}


def canonical_listing_ticker(ticker: str) -> str:
    """Normalize provider-specific exchange suffixes into QuantEdge's internal dialect."""
    upper = (ticker or "").upper().strip()
    if upper.endswith(".US"):
        return upper[:-3]
    mappings = {".AU": ".AX", ".XETRA": ".DE", ".LSE": ".L"}
    for src, dst in mappings.items():
        if upper.endswith(src):
            return upper[:-len(src)] + dst
    return upper


def _finite_number(value) -> Optional[float]:
    """Normalize provider numerics: NaN/inf/unparseable become unavailable."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None

_QUOTE_DEBUG_BY_TICKER: Dict[str, Dict] = {}
_LAST_ERROR: Optional[str] = None




def listing_price_scale_to_currency(ticker: str) -> float:
    """Scale venue quote units into the canonical quote currency used by QuantEdge.

    London Stock Exchange ordinary-equity quotes are commonly expressed in GBp/pence.
    QuantEdge stores/compares prices in GBP, so `.L` venue price units are divided by 100.
    Other currently supported suffixes are already quoted in their canonical currency unit.
    """
    upper = canonical_listing_ticker(ticker)
    return 0.01 if upper.endswith(".L") else 1.0


def _normalize_listing_price(ticker: str, value) -> Optional[float]:
    number = _finite_number(value)
    if number is None:
        return None
    return number * listing_price_scale_to_currency(ticker)


def _normalize_history_price_units(ticker: str, df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy whose OHLC columns use the canonical quote-currency unit."""
    if df is None:
        return df
    scale = listing_price_scale_to_currency(ticker)
    if scale == 1.0:
        return df
    out = df.copy()
    for col in ("Open", "High", "Low", "Close", "Adj Close"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce") * scale
    return out


def ticker_currency(ticker: str) -> str:
    """Return expected quote currency; fail closed for empty/unknown listings."""
    upper = canonical_listing_ticker(ticker)

    if not upper:
        return "UNKNOWN"

    # Yahoo futures and FX symbols are not US equity listings.
    # They remain unsupported here until an explicit instrument-specific
    # currency/calendar contract exists.
    if upper.endswith(("=F", "=X")):
        return "UNKNOWN"

    for suffix, currency in _SUFFIX_CURRENCY.items():
        if upper.endswith(suffix):
            return currency

    return "USD" if "." not in upper else "UNKNOWN"




def ticker_market_zone(ticker: str) -> str:
    """Return representative listing zone; empty/unknown listings stay UNKNOWN."""
    upper = canonical_listing_ticker(ticker)

    if not upper:
        return "UNKNOWN"

    if upper.endswith(("=F", "=X")):
        return "UNKNOWN"

    for suffix, zone in _SUFFIX_MARKET_ZONE.items():
        if upper.endswith(suffix):
            return zone

    return "USA" if "." not in upper else "UNKNOWN"




def ticker_exchange_calendar(ticker: str) -> Optional[str]:
    """Return exchange calendar; empty/unknown listings fail closed."""
    upper = canonical_listing_ticker(ticker)

    if not upper:
        return None

    if upper.endswith(("=F", "=X")):
        return None

    for suffix, calendar in _SUFFIX_CALENDAR.items():
        if upper.endswith(suffix):
            return calendar

    return "XNYS" if "." not in upper else None



def is_ticker_market_open(ticker: str, now=None) -> Optional[bool]:
    """Holiday/DST-aware open state for the listing's actual exchange calendar."""
    calendar_name = ticker_exchange_calendar(ticker)
    if calendar_name is None:
        return None
    try:
        import exchange_calendars as xcals
        if now is None:
            minute = pd.Timestamp.now(tz="UTC").floor("min")
        else:
            minute = pd.Timestamp(now)
            if minute.tzinfo is None:
                minute = minute.tz_localize("UTC")
            else:
                minute = minute.tz_convert("UTC")
            minute = minute.floor("min")
        return bool(xcals.get_calendar(calendar_name).is_open_on_minute(minute))
    except (ValueError, TypeError, KeyError) as exc:
        logger.warning("Calendar lookup failed for %s (%s): %s", ticker, calendar_name, exc)
        return None


def is_ticker_session_in_progress(ticker: str, now=None) -> Optional[bool]:
    """Return whether ``now`` lies between the session open and close.

    Unlike ``is_ticker_market_open()``, this deliberately remains True during
    exchange breaks. It is used when deciding whether a daily bar for the
    current session is complete enough to act as a fallback quote.
    """
    calendar_name = ticker_exchange_calendar(ticker)
    if calendar_name is None:
        return None

    try:
        import exchange_calendars as xcals

        if now is None:
            minute = pd.Timestamp.now(tz="UTC").floor("min")
        else:
            minute = pd.Timestamp(now)
            if minute.tzinfo is None:
                minute = minute.tz_localize("UTC")
            else:
                minute = minute.tz_convert("UTC")
            minute = minute.floor("min")

        cal = xcals.get_calendar(calendar_name)
        local_day = (
            minute
            .tz_convert(cal.tz)
            .normalize()
            .tz_localize(None)
        )

        if not cal.is_session(local_day):
            return False

        session_open = cal.session_open(local_day).tz_convert("UTC")
        session_close = cal.session_close(local_day).tz_convert("UTC")

        return bool(
            session_open <= minute <= session_close
        )

    except (ValueError, TypeError, KeyError) as exc:
        logger.warning(
            "Session-span lookup failed for %s (%s): %s",
            ticker,
            calendar_name,
            exc,
        )
        return None


def normalize_yfinance_ticker(ticker: str) -> str:
    """Convert supported provider dialects into yfinance ticker syntax."""
    return canonical_listing_ticker(ticker)


def get_fundamentals(ticker: str) -> Dict:
    """
    Fundamentals via yfinance.

    Provider failures are represented explicitly with ``_available=False``;
    they are never silently converted to zero-valued financial metrics.
    """
    global _LAST_ERROR
    yf_ticker = normalize_yfinance_ticker(ticker)
    try:
        info = yf.Ticker(yf_ticker).info
    except Exception as exc:
        _LAST_ERROR = f"yfinance fundamentals unavailable for {ticker}: {exc}"
        return {"_available": False, "_source": "yfinance", "_error": str(exc)}

    if not info:
        _LAST_ERROR = f"yfinance fundamentals unavailable for {ticker}: empty response"
        return {"_available": False, "_source": "yfinance", "_error": "empty response"}
    if not isinstance(info, dict):
        _LAST_ERROR = f"yfinance fundamentals unavailable for {ticker}: invalid response type"
        return {"_available": False, "_source": "yfinance", "_error": "invalid response type"}

    return {
        "_available":       True,
        "_source":          "yfinance",
        "_error":           None,
        "name":             info.get("longName", ticker),
        "sector":           info.get("sector", "N/A"),
        "industry":         info.get("industry", "N/A"),
        "instrument_type":  (info.get("quoteType") or "").upper() or None,
        "currency":         (info.get("currency") or "").upper() or None,
        "financial_currency": (info.get("financialCurrency") or "").upper() or None,
        "market_cap":       _finite_number(info.get("marketCap")),
        "pe_ratio":         _finite_number(info.get("trailingPE")),
        "forward_pe":       _finite_number(info.get("forwardPE")),
        "ev_ebitda":        _finite_number(info.get("enterpriseToEbitda")),
        "price_to_book":    _finite_number(info.get("priceToBook")),
        "price_to_sales":   _finite_number(info.get("priceToSalesTrailing12Months")),
        "revenue":          _finite_number(info.get("totalRevenue")),
        "revenue_growth":   _finite_number(info.get("revenueGrowth")),
        "profit_margin":    _finite_number(info.get("profitMargins")),
        "return_on_equity": _finite_number(info.get("returnOnEquity")),
        "short_pct":        _finite_number(info.get("shortPercentOfFloat")),
        "description":      (info.get("longBusinessSummary") or "")[:500],
    }


def get_ticker_info(ticker: str) -> Dict:
    """Small fundamentals view used by the screener and AI analysis."""
    f = get_fundamentals(ticker)
    return {
        "name":                   f.get("name", ticker),
        "sector":                 f.get("sector", "N/A"),
        "short_pct_float":        f.get("short_pct"),
        "pe_ratio":               f.get("pe_ratio"),
        "ev_ebitda":              f.get("ev_ebitda"),
        "revenue":                f.get("revenue"),
        "instrument_type":        f.get("instrument_type"),
        "currency":               f.get("currency"),
        "financial_currency":     f.get("financial_currency"),
        "fundamentals_available": bool(f.get("_available", False)),
        "fundamentals_source":    f.get("_source", "yfinance"),
        "fundamentals_error":     f.get("_error"),
    }



def _sanitize_history_df(ticker: str, df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """
    Normalize OHLCV history and fail closed when the observed rows do not form
    the expected sequence of exchange sessions.
    """
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return None

    out = df.copy()

    for col in ("Open", "High", "Low", "Close", "Adj Close", "Volume"):
        if col in out.columns:
            out[col] = (
                pd.to_numeric(out[col], errors="coerce")
                .replace([math.inf, -math.inf], pd.NA)
            )

    if "Close" not in out.columns:
        return None

    # ------------------------------------------------------------
    # Normalize order and enforce one observation per market date.
    # ------------------------------------------------------------
    try:
        out = out.sort_index()

        session_index = pd.to_datetime(
            out.index,
            errors="coerce",
        )

        if pd.isna(session_index).any():
            return None

        session_dates = pd.Index(
            session_index.date
        )

        if session_dates.duplicated().any():
            out = out[
                ~session_dates.duplicated(
                    keep="last"
                )
            ]

            session_index = pd.to_datetime(
                out.index,
                errors="coerce",
            )

            if pd.isna(session_index).any():
                return None

            session_dates = pd.Index(
                session_index.date
            )

    except (TypeError, ValueError, AttributeError):
        return None

    # ------------------------------------------------------------
    # Exchange-session continuity.
    #
    # Row count alone is not sufficient for an "N sessions" metric.
    # If, for example, one XNYS session is completely absent, Close[-6]
    # must not silently move to an older date.
    #
    # Weekends and exchange holidays are naturally excluded by the real
    # exchange calendar rather than approximated with bdate_range().
    # ------------------------------------------------------------
    calendar_name = ticker_exchange_calendar(
        ticker
    )

    if calendar_name is not None:
        try:
            import exchange_calendars as xcals

            calendar = xcals.get_calendar(
                calendar_name
            )

            first_date = pd.Timestamp(
                session_dates[0]
            )

            last_date = pd.Timestamp(
                session_dates[-1]
            )

            expected_sessions = (
                calendar.sessions_in_range(
                    first_date,
                    last_date,
                )
            )

            expected_dates = pd.Index(
                pd.to_datetime(
                    expected_sessions
                ).date
            )

            # Exact ordered equality catches both:
            # - an expected exchange session missing entirely;
            # - an observation on a non-session date.
            if not session_dates.equals(
                expected_dates
            ):
                return None

        except (
            KeyError,
            TypeError,
            ValueError,
            AttributeError,
            OverflowError,
        ):
            # A known exchange calendar that cannot be validated must not
            # silently produce session-dependent quantitative metrics.
            return None

    # ------------------------------------------------------------
    # Close integrity.
    #
    # Missing/non-positive Close inside the six observations required for a
    # five-session return must fail before any row deletion can shift the
    # effective horizon.
    # ------------------------------------------------------------
    recent_close_raw = (
        pd.to_numeric(
            out["Close"],
            errors="coerce",
        )
        .replace(
            [math.inf, -math.inf],
            pd.NA,
        )
        .tail(6)
    )

    if len(out) >= 6:
        if bool(
            recent_close_raw.isna().any()
        ):
            return None

        if bool(
            (
                recent_close_raw.astype(float)
                <= 0
            ).any()
        ):
            return None

    out = out.dropna(
        subset=["Close"]
    )

    out = out[
        pd.to_numeric(
            out["Close"],
            errors="coerce",
        ) > 0
    ]

    if out.empty:
        return None

    for col in ("Open", "High", "Low"):
        if col in out.columns:
            numeric = pd.to_numeric(
                out[col],
                errors="coerce",
            )

            out.loc[
                numeric <= 0,
                col,
            ] = pd.NA

    if "Volume" in out.columns:
        numeric = pd.to_numeric(
            out["Volume"],
            errors="coerce",
        )

        out.loc[
            numeric < 0,
            "Volume",
        ] = pd.NA

    # Historical incomplete O/H/L values remain unavailable rather than
    # deleting the entire session. The latest session, however, must be a
    # complete and coherent OHLC observation.
    required_ohlc = (
        "Open",
        "High",
        "Low",
        "Close",
    )

    if not all(
        col in out.columns
        for col in required_ohlc
    ):
        return None

    o = pd.to_numeric(
        out["Open"],
        errors="coerce",
    )

    h = pd.to_numeric(
        out["High"],
        errors="coerce",
    )

    l = pd.to_numeric(
        out["Low"],
        errors="coerce",
    )

    c = pd.to_numeric(
        out["Close"],
        errors="coerce",
    )

    complete = (
        o.notna()
        & h.notna()
        & l.notna()
        & c.notna()
    )

    geometry_valid = (
        (h >= l)
        & (h >= o)
        & (h >= c)
        & (l <= o)
        & (l <= c)
    )

    if not bool(
        complete.iloc[-1]
        and geometry_valid.iloc[-1]
    ):
        return None

    invalid_geometry = (
        complete
        & (~geometry_valid)
    )

    if bool(
        invalid_geometry.any()
    ):
        out.loc[
            invalid_geometry,
            ["Open", "High", "Low"],
        ] = pd.NA

    return (
        out
        if not out.empty
        else None
    )



def _coerce_provider_timestamp(value) -> Optional[datetime]:
    """Convert provider index/timestamp values to a timezone-aware UTC datetime."""
    try:
        ts = pd.Timestamp(value)
        if pd.isna(ts):
            return None
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
        return ts.to_pydatetime()
    except (TypeError, ValueError, OverflowError):
        return None


def _yf_history(ticker: str, period: str) -> Optional[pd.DataFrame]:
    yf_ticker = normalize_yfinance_ticker(ticker)
    try:
        hist = yf.Ticker(yf_ticker).history(period=period)
        return _sanitize_history_df(ticker, hist)
    except Exception as exc:
        logger.warning("yfinance history unavailable for %s (%s): %s", yf_ticker, period, exc)
        return None


def _yfinance_quote(ticker: str) -> Dict:
    global _LAST_ERROR
    yf_ticker = normalize_yfinance_ticker(ticker)
    try:
        hist = yf.Ticker(yf_ticker).history(period="5d")
        if hist is None or hist.empty:
            raise ValueError("empty price history")
        price_raw = _normalize_listing_price(ticker, hist["Close"].iloc[-1])
        if price_raw is None or price_raw <= 0:
            raise ValueError("invalid/non-finite price")
        price = round(price_raw, 4)
        try:
            session_ts = pd.Timestamp(hist.index[-1])
            if pd.isna(session_ts):
                raise ValueError("missing session label")
            session_label = session_ts.date().isoformat()
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(
                f"invalid/missing daily-bar session label: {exc}"
            ) from exc

        # yfinance history(period="5d") uses daily bars. Its index is a
        # market-session label (midnight in the exchange timezone), not the
        # observation time of a delayed quote. Treating midnight as a real
        # quote timestamp makes a valid completed-session fallback appear stale
        # after the close.
        #
        # During an open session, fail closed: a daily bar does not provide a
        # trustworthy intraday observation timestamp. Outside the session,
        # freshness is evaluated from the date-only session label.
        session_in_progress = is_ticker_session_in_progress(ticker)
        stale = (
            True
            if session_in_progress is not False
            else is_market_timestamp_stale(
                ticker_exchange_calendar(ticker),
                session_label,
            )
        )

        quote = {
            "ticker": ticker,
            "price": price,
            "currency": ticker_currency(ticker),
            "provider_reported_currency": None,
            "listing_currency_expected": ticker_currency(ticker),
            "price_unit_normalization": "GBp→GBP /100" if listing_price_scale_to_currency(ticker) != 1.0 else None,
            "source": "yfinance",
            "timestamp": session_label,
            "age_hours": None,
            "stale": stale,
            "error": None,
        }
        _QUOTE_DEBUG_BY_TICKER[ticker.upper()] = quote.copy()
        return quote
    except Exception as exc:
        _LAST_ERROR = f"yfinance price unavailable for {ticker}: {exc}"
        quote = {
            "ticker": ticker, "price": None, "currency": ticker_currency(ticker),
            "source": "yfinance", "timestamp": None, "age_hours": None,
            "stale": True, "error": str(exc),
        }
        _QUOTE_DEBUG_BY_TICKER[ticker.upper()] = quote.copy()
        return quote


def get_quote(ticker: str) -> Dict:
    """
    Return a structured quote: price/currency/source/timestamp/stale/error.

    EODHD is primary when configured. If it returns no usable price, yfinance
    is attempted even when EODHD failed by returning ``None`` rather than by
    raising an exception.
    """
    global _LAST_ERROR

    expected_currency = ticker_currency(ticker)
    expected_calendar = ticker_exchange_calendar(ticker)

    # The unified market-data boundary must never certify an economic value
    # for an instrument whose currency/calendar contract is unknown.
    if expected_currency == "UNKNOWN" or expected_calendar is None:
        error = (
            f"unsupported instrument: ticker={ticker!r}, "
            f"currency={expected_currency}, calendar={expected_calendar}"
        )

        quote = {
            "ticker": ticker,
            "price": None,
            "currency": expected_currency,
            "source": "unsupported",
            "timestamp": None,
            "age_hours": None,
            "stale": True,
            "error": error,
        }

        _LAST_ERROR = error
        _QUOTE_DEBUG_BY_TICKER[ticker.upper()] = quote.copy()
        return quote

    eodhd_error = None
    stale_primary = None

    if EODHD_KEY:
        try:
            from utils import eodhd
            quote = eodhd.get_quote(ticker) or {}
            price = _normalize_listing_price(ticker, quote.get("price"))
            if price is not None and price > 0:
                quote["price"] = round(price, 4)
                provider_reported_currency = (quote.get("currency") or "").upper() or None
                quote["provider_reported_currency"] = provider_reported_currency
                quote["listing_currency_expected"] = ticker_currency(ticker)
                quote["currency"] = quote["listing_currency_expected"]
                quote["price_unit_normalization"] = "GBp→GBP /100" if listing_price_scale_to_currency(ticker) != 1.0 else None
                quote["stale"] = bool(
                    quote.get("stale", False)
                    or is_market_timestamp_stale(
                        ticker_exchange_calendar(ticker),
                        quote.get("timestamp"),
                        intraday_max_age_minutes=90,
                    )
                )

                if not quote["stale"] and not quote.get("error"):
                    _QUOTE_DEBUG_BY_TICKER[ticker.upper()] = quote.copy()
                    return quote

                stale_primary = quote.copy()
                eodhd_error = (
                    quote.get("error")
                    or f"stale EODHD quote timestamp={quote.get('timestamp')}"
                )
            else:
                eodhd_error = (
                    quote.get("error")
                    or eodhd.LAST_ERROR
                    or "invalid/non-finite EODHD quote"
                )
        except Exception as exc:
            eodhd_error = str(exc)
            logger.warning("EODHD quote path failed for %s: %s", ticker, exc)

    fallback = _yfinance_quote(ticker)

    if (
        fallback.get("price") is not None
        and not fallback.get("stale", True)
        and not fallback.get("error")
    ):
        if eodhd_error:
            fallback["fallback_reason"] = eodhd_error
        return fallback

    # Preserve the stale primary mark only when no fresher fallback exists.
    # Its stale metadata remains explicit for downstream fail-closed logic/UI.
    if stale_primary is not None:
        fallback_problem = (
            fallback.get("error")
            or (
                "yfinance fallback is also stale"
                if fallback.get("price") is not None
                else "yfinance fallback unavailable"
            )
        )
        stale_primary["fallback_reason"] = fallback_problem
        _QUOTE_DEBUG_BY_TICKER[ticker.upper()] = stale_primary.copy()
        return stale_primary

    if fallback.get("price") is not None:
        if eodhd_error:
            fallback["fallback_reason"] = eodhd_error
        return fallback

    if eodhd_error:
        fallback["error"] = f"EODHD: {eodhd_error}; yfinance: {fallback.get('error')}"
        _LAST_ERROR = fallback["error"]

    return fallback


def get_current_price(ticker: str) -> Optional[float]:
    """Compatibility wrapper that preserves the structured quote fail-closed contract."""
    quote = get_quote(ticker) or {}
    price = _finite_number(quote.get("price"))
    if price is None or price <= 0 or bool(quote.get("stale", True)) or quote.get("error"):
        return None
    return price


def get_quote_debug(ticker: Optional[str] = None):
    if ticker is not None:
        return _QUOTE_DEBUG_BY_TICKER.get(ticker.upper(), {})
    return dict(_QUOTE_DEBUG_BY_TICKER)


def get_last_quote_debug() -> dict:
    """Compatibility helper: return the most recently inserted quote debug."""
    if not _QUOTE_DEBUG_BY_TICKER:
        return {}
    return next(reversed(_QUOTE_DEBUG_BY_TICKER.values()))


def is_stale_price(ticker: Optional[str] = None) -> bool:
    """Return staleness for one ticker, or whether any cached quote is stale."""
    if ticker is not None:
        return bool(_QUOTE_DEBUG_BY_TICKER.get(ticker.upper(), {}).get("stale", False))
    return any(bool(q.get("stale")) for q in _QUOTE_DEBUG_BY_TICKER.values())


def get_last_error() -> Optional[str]:
    if _LAST_ERROR:
        return _LAST_ERROR
    if EODHD_KEY:
        try:
            from utils import eodhd
            return eodhd.LAST_ERROR
        except (ImportError, AttributeError) as exc:
            logger.debug("Unable to read EODHD last error: %s", exc)
    return None


def get_fx_quote_to_eur(currency: str) -> Dict:
    """Return a structured FX quote for converting one currency unit to EUR."""
    currency = (currency or "").upper()
    if currency == "EUR":
        return {
            "currency": "EUR", "rate": 1.0, "source": "identity",
            "timestamp": None, "age_hours": 0.0, "stale": False,
            "error": None, "fallback_reason": None,
        }

    eodhd_error = None
    stale_primary = None

    if currency == "USD" and EODHD_KEY:
        try:
            from utils.eodhd import get_usd_eur_quote

            quote = get_usd_eur_quote() or {}
            rate = _finite_number(quote.get("rate"))

            if rate is not None and rate > 0:
                normalized = {
                    **quote,
                    "currency": currency,
                    "rate": rate,
                    "fallback_reason": quote.get("fallback_reason"),
                }

                if not normalized.get("stale", True) and not normalized.get("error"):
                    return normalized

                stale_primary = normalized
                eodhd_error = (
                    normalized.get("error")
                    or f"stale EODHD FX timestamp={normalized.get('timestamp')}"
                )
            else:
                eodhd_error = quote.get("error")

        except Exception as exc:
            eodhd_error = str(exc)
            logger.warning("EODHD FX %s->EUR unavailable: %s", currency, exc)

    yf_quote = None

    try:
        # FX P&L requires a genuinely timestamped mark. Daily yfinance bars
        # are session labels and cannot satisfy the 24/5 intraday freshness
        # contract, so request hourly observations for the fallback.
        hist = yf.Ticker(f"{currency}EUR=X").history(
            period="5d",
            interval="1h",
        )

        if hist is not None and not hist.empty:
            rate = _finite_number(hist["Close"].iloc[-1])

            if rate is not None and rate > 0:
                timestamp = _coerce_provider_timestamp(hist.index[-1])

                if timestamp is None:
                    raise ValueError("invalid/missing FX timestamp")

                age_hours = (
                    datetime.now(timezone.utc) - timestamp
                ).total_seconds() / 3600

                yf_quote = {
                    "currency": currency,
                    "rate": round(rate, 8),
                    "source": "yfinance FX",
                    "timestamp": timestamp.isoformat(),
                    "age_hours": round(age_hours, 1),
                    "stale": is_fx_timestamp_stale(timestamp),
                    "error": None,
                    "fallback_reason": eodhd_error,
                }

                if not yf_quote["stale"]:
                    return yf_quote

        yf_error = (
            "empty or stale FX history"
            if yf_quote is None
            else "yfinance FX fallback is stale"
        )

    except Exception as exc:
        logger.warning("yfinance FX %s->EUR unavailable: %s", currency, exc)
        yf_error = str(exc)

    if stale_primary is not None:
        stale_primary["fallback_reason"] = yf_error
        return stale_primary

    if yf_quote is not None:
        return yf_quote

    error = "; ".join(x for x in [
        f"EODHD: {eodhd_error}" if eodhd_error else None,
        f"yfinance: {yf_error}",
    ] if x)

    return {
        "currency": currency,
        "rate": None,
        "source": None,
        "timestamp": None,
        "age_hours": None,
        "stale": True,
        "error": error or "FX unavailable",
        "fallback_reason": eodhd_error,
    }


def get_fx_to_eur(currency: str) -> Optional[float]:
    """Compatibility wrapper that never hides stale/unavailable FX metadata."""
    quote = get_fx_quote_to_eur(currency) or {}
    rate = _finite_number(quote.get("rate"))
    if rate is None or rate <= 0 or bool(quote.get("stale", True)) or quote.get("error"):
        return None
    return rate


def get_usd_eur_rate() -> Optional[float]:
    return get_fx_to_eur("USD")


def get_price_history_with_meta(ticker: str, years: int = 5) -> Dict:
    """Unified OHLCV history plus provenance; EODHD primary, yfinance fallback."""
    eodhd_error = None
    if EODHD_KEY:
        try:
            from utils import eodhd
            raw = eodhd.get_eod_history(ticker, years=years)
            if raw and isinstance(raw, list):
                df = pd.DataFrame(raw).rename(columns={
                    "date": "Date", "open": "Open", "high": "High",
                    "low": "Low", "close": "Close", "volume": "Volume",
                })
                df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
                df = df.dropna(subset=["Date"]).set_index("Date").sort_index()
                for col in ["Open", "High", "Low", "Close", "Volume"]:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors="coerce").replace([math.inf, -math.inf], pd.NA)
                df = _sanitize_history_df(ticker, df)
                if df is not None:
                    df = _normalize_history_price_units(ticker, df)
                if df is not None and not df.empty:
                    as_of_ts = pd.Timestamp(df.index[-1])
                    as_of = as_of_ts.isoformat()
                    history_stale = is_market_timestamp_stale(
                        ticker_exchange_calendar(ticker), as_of_ts.strftime("%Y-%m-%d")
                    )
                    if not history_stale:
                        return {
                            "data": df, "source": "EODHD EOD", "as_of": as_of,
                            "history_stale": False, "expected_calendar": ticker_exchange_calendar(ticker),
                            "error": None, "fallback_reason": None,
                        }
                    eodhd_error = f"stale EODHD history as_of={as_of}"
            if not eodhd_error:
                eodhd_error = eodhd.LAST_ERROR or "empty EODHD history"
        except Exception as exc:
            eodhd_error = str(exc)
            logger.warning("EODHD history unavailable for %s: %s", ticker, exc)

    df = _yf_history(ticker, period=f"{years}y")
    if df is None or df.empty:
        return {"data": None, "source": None, "as_of": None, "history_stale": True,
                "expected_calendar": ticker_exchange_calendar(ticker),
                "error": eodhd_error or "history unavailable", "fallback_reason": eodhd_error}
    df = _normalize_history_price_units(ticker, df)
    as_of_ts = pd.Timestamp(df.index[-1])
    as_of = as_of_ts.isoformat()
    history_stale = is_market_timestamp_stale(
        ticker_exchange_calendar(ticker), as_of_ts.strftime("%Y-%m-%d")
    )
    if history_stale:
        return {
            "data": None, "source": "yfinance", "as_of": as_of, "history_stale": True,
            "expected_calendar": ticker_exchange_calendar(ticker),
            "error": f"stale history as_of={as_of}", "fallback_reason": eodhd_error,
        }
    return {
        "data": df, "source": "yfinance", "as_of": as_of, "history_stale": False,
        "expected_calendar": ticker_exchange_calendar(ticker),
        "error": None, "fallback_reason": eodhd_error,
    }


def get_price_history_df(ticker: str, years: int = 5) -> Optional[pd.DataFrame]:
    """Compatibility wrapper returning only unified OHLCV history."""
    return get_price_history_with_meta(ticker, years=years).get("data")


def get_drawdown_from_5y_high(ticker: str) -> Optional[Dict]:
    hist = get_price_history_df(ticker, years=5)
    if hist is None or hist.empty:
        return None
    high_5y = _finite_number(hist["High"].max())
    current = _finite_number(hist["Close"].iloc[-1])
    if high_5y is None or current is None or high_5y <= 0:
        return None
    return {"high_5y": round(high_5y, 4), "current": round(current, 4),
            "drawdown_pct": round((current - high_5y) / high_5y, 4)}


def get_5d_return(ticker: str) -> Optional[float]:
    """Return over exactly five trading intervals (requires six valid closes)."""
    hist = get_price_history_df(ticker, years=1)
    if hist is None or len(hist) < 6:
        return None
    p_now = _finite_number(hist["Close"].iloc[-1])
    p_5d = _finite_number(hist["Close"].iloc[-6])
    if p_now is None or p_5d is None or p_5d <= 0:
        return None
    return round((p_now - p_5d) / p_5d, 4)


def get_period_high(ticker: str, years: int = 5) -> Optional[float]:
    hist = get_price_history_df(ticker, years=years)
    if hist is None or hist.empty:
        return None
    high = _finite_number(hist["High"].max())
    return round(high, 4) if high is not None else None


def get_exchange_tickers(exchange: str = "US", instrument_type: str = "common_stock") -> List[str]:
    if not EODHD_KEY:
        return []
    try:
        from utils.eodhd import get_exchange_tickers as _get_exchange_tickers
        return _get_exchange_tickers(exchange=exchange, instrument_type=instrument_type)
    except Exception as exc:
        logger.warning("Exchange ticker list unavailable for %s: %s", exchange, exc)
        return []


def funnel_screen(tickers, min_market_cap: float = 1_000_000_000, progress_callback=None) -> List[str]:
    survivors = []
    total = len(tickers)
    for i, ticker in enumerate(tickers):
        if progress_callback:
            progress_callback(i / max(total, 1), f"[{i+1}/{total}] Checking {ticker}...")
        yf_ticker = normalize_yfinance_ticker(ticker)
        fund = get_fundamentals(yf_ticker)
        if not fund.get("_available") or fund.get("market_cap") is None:
            continue
        try:
            if float(fund["market_cap"]) < min_market_cap:
                continue
        except (TypeError, ValueError):
            continue
        survivors.append(ticker)
    return survivors


DATA_SOURCE = "EODHD + yfinance fallback" if EODHD_KEY else "yfinance"


def compute_open_pnl(ticker: str, entry_price: float, qty: float,
                     direction: str = "LONG", invested: Optional[float] = None,
                     instrument_type: str = "DIRECT") -> Optional[Dict]:
    """Compatibility P&L helper for direct linear instruments only.

    ``entry_price`` and optional ``invested`` are broker-EUR fields in this
    project. Provider marks are native-currency values and are converted to EUR
    before comparison. For LONG positions, a coherent broker ``invested`` amount
    is the preferred cost basis because it can include execution fees.

    Wrapper/leveraged products deliberately fail closed here: a reference
    underlying quote cannot economically mark a different traded instrument.
    """
    if str(instrument_type or "DIRECT").upper() != "DIRECT":
        return None
    quote = get_quote(ticker) or {}
    price_native = _finite_number(quote.get("price"))
    entry = _finite_number(entry_price)
    quantity = _finite_number(qty)
    side = (direction or "").upper()
    currency = (quote.get("currency") or ticker_currency(ticker) or "").upper()
    if (
        price_native is None
        or entry is None
        or entry <= 0
        or quantity is None
        or quantity <= 0
        or side not in {"LONG", "SHORT"}
        or bool(quote.get("stale", True))
        or quote.get("error")
    ):
        return None

    fx = get_fx_quote_to_eur(currency) or {}
    fx_rate = _finite_number(fx.get("rate"))

    if (
        fx_rate is None
        or fx_rate <= 0
        or bool(fx.get("stale", True))
        or fx.get("error")
    ):
        return None
    current_value_eur = price_native * fx_rate * quantity
    if side == "LONG":
        broker_cost = _finite_number(invested)
        entry_notional = entry * quantity
        if broker_cost is not None and broker_cost > 0:
            tolerance = max(5.0, entry_notional * 0.02)
            if abs(broker_cost - entry_notional) > tolerance:
                return None
            cost_basis = broker_cost
        else:
            cost_basis = entry_notional
        pnl = current_value_eur - cost_basis
    else:
        pnl = (entry - price_native * fx_rate) * quantity
    return {
        "ticker": ticker, "current_price_native": price_native,
        "current_price_eur": round(price_native * fx_rate, 6),
        "pnl": round(pnl, 2), "quote": quote, "fx_quote": fx,
    }

