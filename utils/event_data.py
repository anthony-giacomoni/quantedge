"""Source-labelled market-event/news provider boundary.

Provider hierarchy:
- EODHD when the local plan permits the endpoint.
- Official public macro calendars (BLS/Fed/ECB) when EODHD calendar access is unavailable.
- yfinance as a fallback for watchlist earnings and recent company news.

No future event dates are hard-coded in this module. Every displayed event is
retrieved at request time from a provider/official source and is fail-closed.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from html import unescape
from functools import lru_cache
import logging
import math
import re
import time
from typing import Dict, Iterable, List, Optional, Tuple

import requests
import yfinance as yf

from utils import eodhd


_BLS_ICS_URL = "https://www.bls.gov/schedule/news_release/bls.ics"
_FED_FOMC_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
_ECB_MPC_URL = "https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html"
_HTTP_HEADERS = {"User-Agent": "QuantEdge/1.0 (+local research dashboard)"}


_PROVIDER_CACHE_SECONDS = 15 * 60
_OFFICIAL_CACHE_SECONDS = 60 * 60
_PROVIDER_COOLDOWN_SECONDS = 30 * 60
_EODHD_COOLDOWN_UNTIL: Dict[str, float] = {}
_EODHD_COOLDOWN_ERROR: Dict[str, str] = {}
_YF_COOLDOWN_UNTIL = 0.0
_YF_COOLDOWN_ERROR: Optional[str] = None


def _cache_bucket(seconds: int) -> int:
    return int(time.time() // max(1, int(seconds)))


def _is_entitlement_error(error: Optional[str]) -> bool:
    text = (error or "").lower()
    return "403" in text or "forbidden" in text or "entitlement" in text


def _is_rate_limit_error(error: Optional[str]) -> bool:
    text = (error or "").lower()
    return "429" in text or "too many requests" in text or "rate limit" in text


def _dedupe_messages(values: Iterable[str]) -> List[str]:
    out: List[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def _call_eodhd_uncached(key: str, func, *args, **kwargs):
    now = time.monotonic()
    until = _EODHD_COOLDOWN_UNTIL.get(key, 0.0)
    if until > now:
        return None, _EODHD_COOLDOWN_ERROR.get(key) or f"{key}: EODHD entitlement cooldown active"

    payload = func(*args, **kwargs)
    error = eodhd.LAST_ERROR
    if payload is None and _is_entitlement_error(error):
        _EODHD_COOLDOWN_UNTIL[key] = now + _PROVIDER_COOLDOWN_SECONDS
        _EODHD_COOLDOWN_ERROR[key] = str(error)
    return payload, error


@lru_cache(maxsize=64)
def _eodhd_macro_cached(from_date: str, to_date: str, limit: int, bucket: int):
    return _call_eodhd_uncached(
        "economic-events", eodhd.get_economic_events, from_date, to_date, limit=limit
    )


@lru_cache(maxsize=64)
def _eodhd_earnings_cached(from_date: str, to_date: str, symbols: Tuple[str, ...], bucket: int):
    return _call_eodhd_uncached(
        "calendar/earnings", eodhd.get_earnings_calendar, from_date, to_date, list(symbols)
    )


@lru_cache(maxsize=256)
def _eodhd_news_cached(symbol: str, from_date: str, limit: int, bucket: int):
    return _call_eodhd_uncached(
        "news", eodhd.get_news, symbol, from_date=from_date, limit=limit
    )


class _YFinanceLogCapture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.ERROR)
        self.messages: List[str] = []

    def emit(self, record):
        try:
            self.messages.append(record.getMessage())
        except Exception:
            pass


def _call_yfinance(func):
    """Execute one yfinance request with a process-local 429 circuit breaker.

    Streamlit reruns keep imported modules alive, so the cooldown prevents the same
    watchlist from hammering Yahoo repeatedly after a rate-limit response. The
    yfinance logger is captured locally so 429s become structured provider state
    instead of terminal spam.
    """
    global _YF_COOLDOWN_UNTIL, _YF_COOLDOWN_ERROR

    now = time.monotonic()
    if _YF_COOLDOWN_UNTIL > now:
        return None, _YF_COOLDOWN_ERROR or "yfinance temporarily rate-limited", False

    logger = logging.getLogger("yfinance")
    capture = _YFinanceLogCapture()
    old_handlers = list(logger.handlers)
    old_propagate = logger.propagate
    old_level = logger.level
    logger.handlers = [capture]
    logger.propagate = False
    logger.setLevel(logging.ERROR)

    value = None
    error = None
    try:
        value = func()
    except Exception as exc:
        error = str(exc)
    finally:
        logger.handlers = old_handlers
        logger.propagate = old_propagate
        logger.setLevel(old_level)

    messages = " | ".join(capture.messages)
    combined = " | ".join(part for part in (error, messages) if part)
    if _is_rate_limit_error(combined):
        _YF_COOLDOWN_UNTIL = now + _PROVIDER_COOLDOWN_SECONDS
        _YF_COOLDOWN_ERROR = "yfinance rate-limited (HTTP 429); cooldown active"
        return None, _YF_COOLDOWN_ERROR, False
    if error:
        return None, f"yfinance unavailable ({error})", False
    return value, None, True


@lru_cache(maxsize=128)
def _yf_calendar_cached(symbol: str, bucket: int):
    return _call_yfinance(lambda: yf.Ticker(symbol).calendar)


@lru_cache(maxsize=128)
def _yf_news_cached(symbol: str, bucket: int):
    return _call_yfinance(lambda: yf.Ticker(symbol).news or [])


def clear_event_data_caches() -> None:
    """Reset process-local provider caches/cooldowns (used by tests and diagnostics)."""
    global _YF_COOLDOWN_UNTIL, _YF_COOLDOWN_ERROR
    _eodhd_macro_cached.cache_clear()
    _eodhd_earnings_cached.cache_clear()
    _eodhd_news_cached.cache_clear()
    _yf_calendar_cached.cache_clear()
    _yf_news_cached.cache_clear()
    _http_text_cached.cache_clear()
    _EODHD_COOLDOWN_UNTIL.clear()
    _EODHD_COOLDOWN_ERROR.clear()
    _YF_COOLDOWN_UNTIL = 0.0
    _YF_COOLDOWN_ERROR = None


def _as_date(value) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    # Provider timestamps may be Unix seconds or milliseconds.
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        raw = float(value)
        try:
            if abs(raw) > 1e11:  # milliseconds
                raw /= 1000.0
            return datetime.fromtimestamp(raw, tz=ZoneInfo("UTC")).date()
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    # Numeric timestamps sometimes arrive as strings.
    try:
        numeric = float(text)
        if math.isfinite(numeric) and text.replace(".", "", 1).isdigit():
            if abs(numeric) > 1e11:
                numeric /= 1000.0
            return datetime.fromtimestamp(numeric, tz=ZoneInfo("UTC")).date()
    except (ValueError, OverflowError, OSError):
        pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None


def _finite(value):
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _first_not_none(*values):
    for value in values:
        if value is not None:
            return value
    return None


def _flatten_records(payload) -> List[dict]:
    records: List[dict] = []
    if isinstance(payload, dict):
        record_keys = {"code", "date", "report_date", "reportDate", "type", "title"}
        if record_keys.intersection(payload.keys()):
            return [payload]
        for value in payload.values():
            records.extend(_flatten_records(value))
    elif isinstance(payload, list):
        for value in payload:
            records.extend(_flatten_records(value))
    return records


def _payload_structure_malformed(payload) -> bool:
    """Return True for a non-empty provider payload with no parseable record container.

    Empty lists/dicts can legitimately mean "no events". Non-empty payloads that
    cannot yield any records are treated as provider failures so fallbacks can run.
    """
    if payload is None or payload == [] or payload == {}:
        return False
    return not bool(_flatten_records(payload))


_MAJOR_TERMS = (
    "interest rate", "rate decision", "fomc", "federal reserve", "ecb",
    "inflation rate", "consumer price", "cpi", "core inflation", "pce price",
    "nonfarm payroll", "non-farm payroll", "employment situation", "unemployment rate",
    "gdp growth", "crude oil stocks", "crude oil inventories", "natural gas stocks",
)
_MODERATE_TERMS = (
    "producer price", "ppi", "retail sales", "pmi", "industrial production",
    "jobless claims", "employment change", "trade balance", "consumer confidence",
    "housing starts", "durable goods", "factory orders", "oil rig count", "jolts",
)
_ENERGY_TERMS = ("crude", "oil", "gas", "petroleum", "inventory", "inventories", "opec")


def classify_impact(event_type: str) -> str:
    text = (event_type or "").lower()
    if any(term in text for term in _MAJOR_TERMS):
        return "Major"
    if any(term in text for term in _MODERATE_TERMS):
        return "Moderate"
    return "Minor"


def classify_focus(event_type: str) -> str:
    text = (event_type or "").lower()
    if any(term in text for term in _ENERGY_TERMS):
        return "Energy"
    if any(term in text for term in (
        "interest rate", "fomc", "ecb", "inflation", "cpi", "pce", "payroll",
        "employment situation", "gdp", "unemployment", "producer price", "ppi",
    )):
        return "Macro"
    return "General"


@lru_cache(maxsize=32)
def _http_text_cached(url: str, timeout: int, bucket: int) -> Tuple[Optional[str], Optional[str]]:
    try:
        response = requests.get(url, headers=_HTTP_HEADERS, timeout=timeout)
        response.raise_for_status()
        return response.text, None
    except requests.RequestException as exc:
        return None, f"{url}: {exc}"


def _http_text(url: str, timeout: int = 8) -> Tuple[Optional[str], Optional[str]]:
    return _http_text_cached(url, int(timeout), _cache_bucket(_OFFICIAL_CACHE_SECONDS))


def _unfold_ics(text: str) -> List[str]:
    lines: List[str] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        if raw.startswith((" ", "\t")) and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def _parse_ics_dt(value: str, tzid: Optional[str] = None) -> Optional[datetime]:
    value = (value or "").strip()
    is_utc = value.endswith("Z")
    raw = value.rstrip("Z")
    for fmt in ("%Y%m%dT%H%M%S", "%Y%m%dT%H%M", "%Y%m%d"):
        try:
            dt = datetime.strptime(raw, fmt)
            if fmt == "%Y%m%d":
                return dt.replace(tzinfo=ZoneInfo("UTC"))
            if is_utc:
                return dt.replace(tzinfo=ZoneInfo("UTC"))
            if tzid:
                try:
                    return dt.replace(tzinfo=ZoneInfo(tzid))
                except Exception:
                    return None
            # Time without a declared timezone is ambiguous; fail closed rather
            # than silently treating a local release time as UTC.
            return None
        except ValueError:
            pass
    return None

def _bls_events(today: date, end: date) -> Tuple[List[dict], List[str]]:
    text, error = _http_text(_BLS_ICS_URL)
    if not text:
        return [], [error] if error else ["BLS calendar unavailable"]

    rows: List[dict] = []
    current: Dict[str, str] = {}
    for line in _unfold_ics(text):
        if line == "BEGIN:VEVENT":
            current = {}
        elif line == "END:VEVENT":
            dt = _parse_ics_dt(current.get("DTSTART", ""), current.get("DTSTART_TZID") or "America/New_York")
            title = unescape(current.get("SUMMARY", "")).replace("\\,", ",").strip()
            if dt and title and today <= dt.date() <= end:
                rows.append({
                    "date": dt.date().isoformat(),
                    "provider_datetime": dt.isoformat(),
                    "country": "US",
                    "event": title,
                    "impact": classify_impact(title),
                    "focus": classify_focus(title),
                    "estimate": None,
                    "previous": None,
                    "actual": None,
                    "unit": None,
                    "source": "BLS Official Calendar",
                })
            current = {}
        elif current is not None and ":" in line:
            raw_key, value = line.split(":", 1)
            parts = raw_key.split(";")
            key = parts[0]
            if key in {"DTSTART", "SUMMARY"}:
                current[key] = value
            if key == "DTSTART":
                for param in parts[1:]:
                    if param.upper().startswith("TZID="):
                        current["DTSTART_TZID"] = param.split("=", 1)[1]
    return rows, []


def _strip_html(text: str) -> str:
    text = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = unescape(text).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _fomc_events(today: date, end: date) -> Tuple[List[dict], List[str]]:
    """Return official FOMC decision dates from the Fed meeting calendar.

    The Fed page is not ordered strictly by year: the future-year section can
    appear after several historical sections. Therefore each requested year
    must be isolated by the *next year heading in document order*, not by
    assuming that ``year + 1`` immediately follows it.

    Only regular two-day meeting ranges are accepted. The economic event date
    is the second day, when the statement/press conference occurs.
    """
    html, error = _http_text(_FED_FOMC_URL)

    if not html:
        return [], [
            error
        ] if error else [
            "Federal Reserve calendar unavailable"
        ]

    text = _strip_html(html)

    months = [
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ]

    month_num = {
        month: i
        for i, month in enumerate(months, 1)
    }

    # A regular scheduled FOMC meeting is represented as a two-day range.
    # Requiring the range also prevents dates such as
    # "(Released August 19, 2026)" from being mistaken for meetings.
    meeting_pattern = re.compile(
        r"\b("
        + "|".join(months)
        + r")\s+"
        + r"(\d{1,2})"
        + r"\s*[-–]\s*"
        + r"(\d{1,2})"
        + r"\*?"
    )

    rows: List[dict] = []
    warnings: List[str] = []
    seen = set()

    for year in range(today.year, end.year + 1):
        # Stop at whichever FOMC-year heading actually comes next in the
        # document. The Fed page may be ordered 2026, 2025, ..., 2021, 2027.
        section_match = re.search(
            rf"\b{year}\s+FOMC Meetings\b"
            rf"(.*?)"
            rf"(?=\b\d{{4}}\s+FOMC Meetings\b|$)",
            text,
            flags=re.DOTALL,
        )

        if section_match is None:
            warnings.append(
                f"Federal Reserve calendar: {year} section not found"
            )
            continue

        section = section_match.group(1)

        for match in meeting_pattern.finditer(section):
            month, _first_day, last_day = match.groups()

            try:
                event_date = date(
                    year,
                    month_num[month],
                    int(last_day),
                )
            except ValueError:
                continue

            if not (
                today <= event_date <= end
            ):
                continue

            if event_date in seen:
                continue

            seen.add(event_date)

            rows.append({
                "date": event_date.isoformat(),
                "provider_datetime": event_date.isoformat(),
                "country": "US",
                "event": "FOMC Rate Decision / Press Conference",
                "impact": "Major",
                "focus": "Macro",
                "estimate": None,
                "previous": None,
                "actual": None,
                "unit": None,
                "source": "Federal Reserve Official Calendar",
            })

    return rows, warnings


def _ecb_events(today: date, end: date) -> Tuple[List[dict], List[str]]:
    html, error = _http_text(_ECB_MPC_URL)
    if not html:
        return [], [error] if error else ["ECB calendar unavailable"]
    text = _strip_html(html)
    # Capture each dated description up to the next date.
    pattern = re.compile(r"(\d{2}/\d{2}/\d{4})\s+(.*?)(?=\d{2}/\d{2}/\d{4}|$)")
    rows: List[dict] = []
    for raw_date, desc in pattern.findall(text):
        if "monetary policy" not in desc.lower():
            continue
        # Only the decision day / press-conference day, not Day 1.
        if "day 1" in desc.lower() and "press conference" not in desc.lower():
            continue
        try:
            event_date = datetime.strptime(raw_date, "%d/%m/%Y").date()
        except ValueError:
            continue
        if not (today <= event_date <= end):
            continue
        title = "ECB Monetary Policy Decision / Press Conference"
        rows.append({
            "date": event_date.isoformat(),
            "provider_datetime": event_date.isoformat(),
            "country": "EU",
            "event": title,
            "impact": "Major",
            "focus": "Macro",
            "estimate": None,
            "previous": None,
            "actual": None,
            "unit": None,
            "source": "ECB Official Calendar",
        })
    return rows, []


def _official_macro_events(today: date, end: date, countries: Iterable[str]) -> Tuple[List[dict], List[str]]:
    selected = {str(c).upper() for c in countries if str(c).strip()}
    rows: List[dict] = []
    warnings: List[str] = []
    if not selected or "US" in selected:
        for loader in (_bls_events, _fomc_events):
            part, errs = loader(today, end)
            rows.extend(part)
            warnings.extend(e for e in errs if e)
    if not selected or "EU" in selected:
        part, errs = _ecb_events(today, end)
        rows.extend(part)
        warnings.extend(e for e in errs if e)

    # Deduplicate exact source/date/event tuples.
    dedup = {}
    for row in rows:
        dedup[(row.get("date"), row.get("country"), row.get("event"), row.get("source"))] = row
    return list(dedup.values()), warnings


def _parse_eodhd_macro(payload, today: date, end: date, country_filter: set) -> List[dict]:
    rows = []
    for item in _flatten_records(payload):
        event_type = str(_first_not_none(item.get("type"), item.get("event"), item.get("title"), "")).strip()
        provider_datetime = _first_not_none(item.get("date"), item.get("datetime"))
        event_date = _as_date(provider_datetime)
        country = str(item.get("country") or item.get("countryCode") or "").upper().strip()
        if not event_type or event_date is None:
            continue
        if event_date < today or event_date > end:
            continue
        if country_filter and country not in country_filter:
            continue
        rows.append({
            "date": event_date.isoformat(),
            "provider_datetime": str(provider_datetime),
            "country": country or "N/A",
            "event": event_type,
            "impact": classify_impact(event_type),
            "focus": classify_focus(event_type),
            "estimate": _finite(_first_not_none(item.get("estimate"), item.get("forecast"))),
            "previous": _finite(item.get("previous")),
            "actual": _finite(item.get("actual")),
            "unit": item.get("unit"),
            "source": "EODHD Economic Events",
        })
    return rows


def get_upcoming_macro(days_ahead: int = 21, countries: Optional[Iterable[str]] = None) -> Dict:
    today = datetime.now(ZoneInfo("Europe/Paris")).date()
    end = today + timedelta(days=max(1, int(days_ahead)))
    country_filter = {str(c).upper() for c in (countries or []) if str(c).strip()}

    payload, eodhd_error = _eodhd_macro_cached(
        today.isoformat(), end.isoformat(), 1000, _cache_bucket(_PROVIDER_CACHE_SECONDS)
    )
    if payload is not None and not _payload_structure_malformed(payload):
        rows = _parse_eodhd_macro(payload, today, end, country_filter)
        impact_rank = {"Major": 0, "Moderate": 1, "Minor": 2}
        rows.sort(
            key=lambda r: (
                r["date"],
                impact_rank.get(r["impact"], 9),
                r["event"],
            )
        )

        if rows or payload in ([], {}):
            return {
                "events": rows,
                "from": today.isoformat(),
                "to": end.isoformat(),
                "error": None,
                "warnings": [],
                "source": "EODHD Economic Events",
            }

        eodhd_error = (
            eodhd_error
            or "EODHD economic-events payload contained no usable in-window records"
        )
    if payload is not None and _payload_structure_malformed(payload):
        eodhd_error = eodhd_error or "malformed EODHD economic-events payload"

    rows, official_warnings = _official_macro_events(today, end, country_filter)
    impact_rank = {"Major": 0, "Moderate": 1, "Minor": 2}
    rows.sort(key=lambda r: (r["date"], impact_rank.get(r["impact"], 9), r["event"]))
    warnings = []
    if eodhd_error:
        warnings.append(f"EODHD macro unavailable; official-calendar fallback active: {eodhd_error}")
    # The built-in official fallback intentionally covers US and EU only.
    # Never imply that GB/JP/CN/CA/AU are covered when EODHD is unavailable.
    official_supported = {"US", "EU"}
    unsupported_selected = sorted(country_filter - official_supported)
    if unsupported_selected:
        warnings.append(
            "Official-calendar fallback does not cover selected regions: "
            + ", ".join(unsupported_selected)
            + ". Those regions remain unavailable until the primary provider is accessible."
        )
    warnings.extend(official_warnings)
    no_rows_error = (
        eodhd_error
        or "; ".join(official_warnings)
        or (
            "No official fallback coverage for the selected regions"
            if country_filter and country_filter.isdisjoint(official_supported)
            else "No macro events found in the selected window"
        )
    )
    return {
        "events": rows,
        "from": today.isoformat(),
        "to": end.isoformat(),
        "error": None if rows else no_rows_error,
        "warnings": warnings,
        "source": "Official macro calendars (US/EU only)" if rows else "Unavailable",
    }


def _extract_yf_earnings_dates(calendar) -> List[datetime]:
    if calendar is None:
        return []
    values = None
    if isinstance(calendar, dict):
        for key in ("Earnings Date", "EarningsDate", "earningsDate"):
            if key in calendar:
                values = calendar[key]
                break
    else:
        try:
            if hasattr(calendar, "index") and "Earnings Date" in calendar.index:
                values = calendar.loc["Earnings Date"].tolist()
            elif hasattr(calendar, "columns") and "Earnings Date" in calendar.columns:
                values = calendar["Earnings Date"].tolist()
        except Exception:
            values = None
    if values is None:
        return []
    if not isinstance(values, (list, tuple, set)):
        values = [values]
    out = []
    for value in values:
        if hasattr(value, "to_pydatetime"):
            value = value.to_pydatetime()
        if isinstance(value, datetime):
            out.append(value)
        elif isinstance(value, date):
            out.append(datetime.combine(value, datetime.min.time()))
        else:
            try:
                out.append(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
            except ValueError:
                pass
    return out


def _yfinance_earnings(symbols: Iterable[str], today: date, end: date) -> Tuple[List[dict], List[str]]:
    rows: List[dict] = []
    errors: List[str] = []
    for symbol in symbols:
        calendar, provider_error, usable = _yf_calendar_cached(
            symbol, _cache_bucket(_PROVIDER_CACHE_SECONDS)
        )
        if not usable:
            errors.append(f"{symbol}: {provider_error or 'yfinance earnings unavailable'}")
            if _is_rate_limit_error(provider_error):
                # Stop immediately: the process-local cooldown will protect future reruns.
                remaining = [s for s in symbols if s != symbol]
                errors.extend(f"{s}: yfinance rate-limit cooldown active" for s in remaining)
                break
            continue
        dates = _extract_yf_earnings_dates(calendar)
        for dt in dates:
            d = dt.date()
            if today <= d <= end:
                rows.append({
                    "date": d.isoformat(),
                    "ticker": symbol,
                    "before_after_market": None,
                    "eps_estimate": None,
                    "currency": None,
                    "source": "yfinance Earnings Calendar",
                })
                break
    rows.sort(key=lambda r: (r["date"], r["ticker"]))
    return rows, errors


def get_upcoming_earnings(symbols: Iterable[str], days_ahead: int = 21) -> Dict:
    from utils.market_data import canonical_listing_ticker

    clean_symbols = []
    for symbol in symbols:
        s = canonical_listing_ticker(str(symbol or "").strip().upper())
        if s and s not in clean_symbols:
            clean_symbols.append(s)

    today = datetime.now(ZoneInfo("Europe/Paris")).date()
    end = today + timedelta(days=max(1, int(days_ahead)))
    if not clean_symbols:
        return {"events": [], "from": today.isoformat(), "to": end.isoformat(), "error": None, "warnings": [], "source": "No watchlist"}

    payload, eodhd_error = _eodhd_earnings_cached(
        today.isoformat(), end.isoformat(), tuple(clean_symbols), _cache_bucket(_PROVIDER_CACHE_SECONDS)
    )
    rows = []
    if payload is not None and not _payload_structure_malformed(payload):
        from utils.market_data import canonical_listing_ticker
        requested = {canonical_listing_ticker(s) for s in clean_symbols}
        for item in _flatten_records(payload):
            report_date_raw = _first_not_none(item.get("report_date"), item.get("reportDate"), item.get("date"))
            report_date = _as_date(report_date_raw)
            code = str(item.get("code") or item.get("symbol") or "").strip().upper()
            canonical_code = canonical_listing_ticker(code) if code else ""
            if report_date is None or report_date < today or report_date > end or not canonical_code:
                continue
            if canonical_code not in requested:
                continue
            rows.append({
                "date": report_date.isoformat(),
                "ticker": canonical_code,
                "before_after_market": item.get("before_after_market") or item.get("beforeAfterMarket") or item.get("BeforeAfterMarket"),
                "eps_estimate": _finite(_first_not_none(item.get("estimate"), item.get("eps_estimate"), item.get("epsEstimate"))),
                "currency": item.get("currency"),
                "source": "EODHD Earnings Calendar",
            })
        rows.sort(key=lambda r: (r["date"], r["ticker"]))

        if rows or payload in ([], {}):
            return {
                "events": rows,
                "from": today.isoformat(),
                "to": end.isoformat(),
                "error": None,
                "warnings": [],
                "source": "EODHD Earnings Calendar",
            }

        eodhd_error = (
            eodhd_error
            or "EODHD earnings payload contained no usable requested in-window records"
        )
    if payload is not None and _payload_structure_malformed(payload):
        eodhd_error = eodhd_error or "malformed EODHD earnings payload"

    yf_rows, yf_errors = _yfinance_earnings(clean_symbols, today, end)
    warnings = []
    if eodhd_error:
        warnings.append(f"EODHD earnings unavailable; yfinance fallback active: {eodhd_error}")
    warnings.extend(yf_errors)
    warnings = _dedupe_messages(warnings)
    # A successful yfinance query with zero dates is still a valid calendar result.
    # Do not turn "no earnings in this window" into a provider failure just because
    # the premium EODHD calendar endpoint is unavailable.
    yf_usable = len(yf_errors) < len(clean_symbols)
    return {
        "events": yf_rows,
        "from": today.isoformat(),
        "to": end.isoformat(),
        "error": None if (yf_rows or yf_usable) else (eodhd_error or "; ".join(yf_errors) or "No earnings source available"),
        "warnings": warnings,
        "source": "yfinance Earnings Calendar" if (yf_rows or yf_usable) else "Unavailable",
    }


def _yfinance_news(symbol: str, from_date: date, per_symbol: int) -> Tuple[List[dict], Optional[str]]:
    items, provider_error, usable = _yf_news_cached(
        symbol, _cache_bucket(_PROVIDER_CACHE_SECONDS)
    )
    if not usable:
        return [], f"{symbol}: {provider_error or 'yfinance news unavailable'}"
    items = items or []
    rows = []
    for item in items[: max(1, int(per_symbol)) * 2]:
        if not isinstance(item, dict):
            continue
        content = item.get("content") if isinstance(item.get("content"), dict) else item
        title = str(content.get("title") or item.get("title") or "").strip()
        if not title:
            continue
        published = content.get("pubDate") or item.get("providerPublishTime") or item.get("publishTime")
        publish_date = _as_date(published)
        today = datetime.now(ZoneInfo("Europe/Paris")).date()
        if publish_date is None or publish_date < from_date or publish_date > today:
            continue
        link = None
        canonical = content.get("canonicalUrl") if isinstance(content.get("canonicalUrl"), dict) else None
        if canonical:
            link = canonical.get("url")
        link = link or item.get("link")
        rows.append({
            "ticker": symbol,
            "date": publish_date.isoformat(),
            "title": title,
            "link": link,
            "sentiment": None,
            "source": "yfinance News",
        })
        if len(rows) >= per_symbol:
            break
    return rows, None


def get_recent_news(symbols: Iterable[str], days_back: int = 3, per_symbol: int = 4) -> Dict:
    from utils.market_data import canonical_listing_ticker

    clean_symbols = []
    for symbol in symbols:
        s = canonical_listing_ticker(str(symbol or "").strip().upper())
        if s and s not in clean_symbols:
            clean_symbols.append(s)
    clean_symbols = clean_symbols[:6]
    from_date_obj = datetime.now(ZoneInfo("Europe/Paris")).date() - timedelta(days=max(1, int(days_back)))
    from_date = from_date_obj.isoformat()

    rows = []
    errors = []
    warnings = []
    for symbol in clean_symbols:
        payload, eodhd_error = _eodhd_news_cached(
            symbol, from_date, max(1, int(per_symbol)), _cache_bucket(_PROVIDER_CACHE_SECONDS)
        )
        if payload is None:
            yf_rows, yf_error = _yfinance_news(symbol, from_date_obj, per_symbol)
            rows.extend(yf_rows)
            if yf_rows and eodhd_error:
                warnings.append(f"{symbol}: EODHD news unavailable; yfinance fallback active ({eodhd_error})")
            elif yf_error:
                errors.append(yf_error)
            elif eodhd_error:
                errors.append(f"{symbol}: {eodhd_error}")
            continue
        if _payload_structure_malformed(payload):
            yf_rows, yf_error = _yfinance_news(symbol, from_date_obj, per_symbol)
            rows.extend(yf_rows)
            warnings.append(f"{symbol}: malformed EODHD news payload; yfinance fallback active")
            if yf_error:
                errors.append(yf_error)
            continue
        today = datetime.now(ZoneInfo("Europe/Paris")).date()
        records = _flatten_records(payload)
        added = 0
        for item in records:
            title = str(item.get("title") or "").strip()
            published = item.get("date") or item.get("published_at") or item.get("timestamp")
            publish_date = _as_date(published)
            if not title or publish_date is None or publish_date < from_date_obj or publish_date > today:
                continue
            rows.append({
                "ticker": symbol,
                "date": publish_date.isoformat(),
                "title": title,
                "link": item.get("link"),
                "sentiment": item.get("sentiment"),
                "source": "EODHD News",
            })
            added += 1
        # A non-empty provider payload with no parseable/in-window dates is not a
        # trustworthy "no news" answer. Fall back rather than letting malformed
        # timestamps bypass the recency contract.
        if records and added == 0:
            yf_rows, yf_error = _yfinance_news(symbol, from_date_obj, per_symbol)
            rows.extend(yf_rows)
            warnings.append(f"{symbol}: EODHD news payload had no valid recent timestamps; yfinance fallback active")
            if yf_error:
                errors.append(yf_error)
    rows.sort(key=lambda r: str(r.get("date") or ""), reverse=True)
    return {
        "articles": rows,
        "errors": _dedupe_messages(errors),
        "warnings": _dedupe_messages(warnings),
        "source": "EODHD/yfinance News",
    }
