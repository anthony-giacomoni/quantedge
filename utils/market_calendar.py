"""Exchange-session aware freshness helpers for provider timestamps."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional
from zoneinfo import ZoneInfo
import pandas as pd


def _as_utc(value) -> Optional[pd.Timestamp]:
    try:
        ts = pd.Timestamp(value)
        if pd.isna(ts):
            return None
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
        return ts
    except (TypeError, ValueError, OverflowError):
        return None


def is_market_timestamp_stale(calendar_name: Optional[str], provider_timestamp, now=None, fallback_hours: float = 36.0, intraday_max_age_minutes: Optional[float] = None) -> bool:
    """Return whether a quote timestamp predates the latest session expected by now.

    Date-only provider values (typical EOD rows) are treated as exchange-session
    labels rather than midnight UTC instants. Unknown calendars fall back to a
    conservative wall-clock age check. Future timestamps always fail closed.
    """
    if provider_timestamp is None:
        return True
    now_utc = _as_utc(now) if now is not None else pd.Timestamp.now(tz="UTC")
    if now_utc is None:
        return True

    raw = str(provider_timestamp).strip()
    date_only = len(raw) == 10 and raw[4:5] == "-" and raw[7:8] == "-"

    if not calendar_name:
        ts = _as_utc(provider_timestamp)
        if ts is None:
            return True
        age_hours = (now_utc - ts).total_seconds() / 3600
        return age_hours > fallback_hours or age_hours < -0.25

    try:
        import exchange_calendars as xcals
        cal = xcals.get_calendar(calendar_name)
        local_now = now_utc.tz_convert(cal.tz)
        today = local_now.normalize().tz_localize(None)

        if cal.is_session(today):
            session_open = cal.session_open(today).tz_convert("UTC")
            expected = today if now_utc >= session_open else cal.previous_session(today)
        else:
            expected = cal.date_to_session(today, direction="previous")

        if date_only:
            provider_session = pd.Timestamp(raw).normalize()
        else:
            provider_utc = _as_utc(provider_timestamp)
            if provider_utc is None:
                return True
            if provider_utc > now_utc + pd.Timedelta(minutes=15):
                return True
            provider_session = provider_utc.tz_convert(cal.tz).normalize().tz_localize(None)

        provider_session = pd.Timestamp(provider_session).normalize()
        if not cal.is_session(provider_session):
            return True
        # The provider mark must belong to exactly the latest session expected at
        # ``now``. A future session label before the open is not evidence of a
        # fresh quote, and an older session is stale.
        if provider_session != pd.Timestamp(expected).normalize():
            return True

        # Timestamped delayed quotes need an intraday-age guard even when the
        # venue has just closed or has not opened yet. Otherwise an early-session
        # mark from the latest session can remain "fresh" all night merely because
        # its session label is correct. Date-labelled EOD rows deliberately skip
        # this check because they represent the completed session as a whole.
        if intraday_max_age_minutes is not None and not date_only:
            provider_utc = _as_utc(provider_timestamp)
            if provider_utc is None:
                return True

            expected_open = cal.session_open(expected).tz_convert("UTC")
            expected_close = cal.session_close(expected).tz_convert("UTC")

            # During the regular-session time span (including exchange breaks),
            # freshness is measured from now.
            if expected_open <= now_utc <= expected_close:
                age_minutes = (now_utc - provider_utc).total_seconds() / 60
                if age_minutes > intraday_max_age_minutes:
                    return True
            else:
                # Before the next open / after the close / on holidays-weekends,
                # a timestamped quote must at least be close to the completed
                # session's closing time. The correct session label alone is not enough.
                minutes_before_close = (
                    expected_close - provider_utc
                ).total_seconds() / 60

                if minutes_before_close > intraday_max_age_minutes:
                    return True

        return False
    except (ValueError, TypeError, KeyError, OverflowError):
        ts = _as_utc(provider_timestamp)
        if ts is None:
            return True
        age_hours = (now_utc - ts).total_seconds() / 3600
        return age_hours > fallback_hours or age_hours < -0.25


def is_fx_timestamp_stale(provider_timestamp, now=None, intraday_max_age_hours: float = 6.0) -> bool:
    """Freshness check for spot-FX style 24/5 timestamps.

    The market is treated as closed from Friday 17:00 New York through Sunday
    17:00 New York. During that closure the latest Friday mark may remain fresh.
    Once Sunday trading reopens, wall-clock age applies again so a Friday mark
    cannot remain fresh into the new FX week. DST is handled by America/New_York.
    """
    ts = _as_utc(provider_timestamp)
    now_utc = _as_utc(now) if now is not None else pd.Timestamp.now(tz="UTC")
    if ts is None or now_utc is None:
        return True
    if ts > now_utc + pd.Timedelta(minutes=15):
        return True

    ny = ZoneInfo("America/New_York")
    now_ny = now_utc.tz_convert(ny)
    ts_ny = ts.tz_convert(ny)
    weekday = now_ny.weekday()  # Mon=0 ... Sun=6
    hour = now_ny.hour + now_ny.minute / 60.0
    market_closed = (weekday == 4 and hour >= 17.0) or weekday == 5 or (weekday == 6 and hour < 17.0)

    if market_closed:
        # During the weekend closure, only a mark from the immediately preceding
        # Friday is eligible. An arbitrary older Friday must never be treated as
        # fresh merely because its weekday matches.
        days_since_friday = (weekday - 4) % 7
        expected_friday = (now_ny - pd.Timedelta(days=days_since_friday)).date()
        if ts_ny.weekday() != 4 or ts_ny.date() != expected_friday:
            return True

        # Compare the provider mark with the conventional Friday 17:00 New York
        # close. This also rejects a very early Friday mark while allowing normal
        # delayed/EOD provider timestamps near the close.
        close_ny = pd.Timestamp(
            datetime(expected_friday.year, expected_friday.month, expected_friday.day, 17, 0, tzinfo=ny)
        )
        age_to_close_hours = (close_ny.tz_convert("UTC") - ts).total_seconds() / 3600
        return age_to_close_hours > intraday_max_age_hours or age_to_close_hours < -1.0

    age_hours = (now_utc - ts).total_seconds() / 3600
    return age_hours > intraday_max_age_hours or age_hours < -0.25
