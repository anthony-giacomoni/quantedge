from datetime import datetime, timezone, timedelta

import pytest

from modules import news
from utils import event_data




@pytest.fixture(autouse=True)
def _reset_event_provider_state():
    event_data.clear_event_data_caches()
    yield
    event_data.clear_event_data_caches()


def _date_in(days):
    return (datetime.now(timezone.utc).date() + timedelta(days=days)).isoformat()


def test_macro_events_are_provider_supplied_and_classified(monkeypatch):
    payload = [
        {"date": _date_in(2) + " 12:30:00", "country": "US", "type": "Consumer Price Index CPI", "estimate": 2.7, "previous": 2.6},
        {"date": _date_in(3), "country": "US", "type": "Crude Oil Stocks Change", "estimate": -1.0, "previous": 0.5},
        {"date": _date_in(4), "country": "FR", "type": "Business Confidence"},
    ]
    monkeypatch.setattr(event_data.eodhd, "get_economic_events", lambda *a, **k: payload)
    monkeypatch.setattr(event_data.eodhd, "LAST_ERROR", None)
    out = event_data.get_upcoming_macro(days_ahead=7, countries=["US"])
    assert len(out["events"]) == 2
    assert out["events"][0]["impact"] == "Major"
    assert any(e["focus"] == "Energy" for e in out["events"])
    assert all(e["source"] == "EODHD Economic Events" for e in out["events"])
    assert out["events"][0]["provider_datetime"].endswith("12:30:00")


def test_macro_provider_failure_uses_official_fallback(monkeypatch):
    monkeypatch.setattr(event_data.eodhd, "get_economic_events", lambda *a, **k: None)
    monkeypatch.setattr(event_data.eodhd, "LAST_ERROR", "403 Forbidden")
    row = {
        "date": _date_in(2), "provider_datetime": _date_in(2), "country": "US",
        "event": "Consumer Price Index", "impact": "Major", "focus": "Macro",
        "estimate": None, "previous": None, "actual": None, "unit": None,
        "source": "BLS Official Calendar",
    }
    monkeypatch.setattr(event_data, "_official_macro_events", lambda *a, **k: ([row], []))
    out = event_data.get_upcoming_macro(days_ahead=21, countries=["US"])
    assert out["events"] == [row]
    assert out["error"] is None
    assert any("fallback active" in w for w in out["warnings"])


def test_macro_all_sources_failure_fails_closed(monkeypatch):
    monkeypatch.setattr(event_data.eodhd, "get_economic_events", lambda *a, **k: None)
    monkeypatch.setattr(event_data.eodhd, "LAST_ERROR", "calendar unavailable")
    monkeypatch.setattr(event_data, "_official_macro_events", lambda *a, **k: ([], ["official unavailable"]))
    out = event_data.get_upcoming_macro(days_ahead=21, countries=["US"])
    assert out["events"] == []
    assert out["error"] == "calendar unavailable"


def test_earnings_are_bounded_to_supplied_future_window(monkeypatch):
    payload = [
        {"report_date": _date_in(2), "code": "NFLX.US", "estimate": 1.23},
        {"report_date": _date_in(40), "code": "AON.US", "estimate": 2.34},
    ]
    monkeypatch.setattr(event_data.eodhd, "get_earnings_calendar", lambda *a, **k: payload)
    monkeypatch.setattr(event_data.eodhd, "LAST_ERROR", None)
    out = event_data.get_upcoming_earnings(["NFLX", "AON"], days_ahead=21)
    assert [e["ticker"] for e in out["events"]] == ["NFLX"]


def test_earnings_403_falls_back_to_yfinance(monkeypatch):
    monkeypatch.setattr(event_data.eodhd, "get_earnings_calendar", lambda *a, **k: None)
    monkeypatch.setattr(event_data.eodhd, "LAST_ERROR", "403 Forbidden")
    row = {"date": _date_in(3), "ticker": "NFLX", "before_after_market": None, "eps_estimate": None, "currency": None, "source": "yfinance Earnings Calendar"}
    monkeypatch.setattr(event_data, "_yfinance_earnings", lambda *a, **k: ([row], []))
    out = event_data.get_upcoming_earnings(["NFLX"], days_ahead=21)
    assert out["events"] == [row]
    assert out["error"] is None
    assert any("fallback active" in w for w in out["warnings"])


def test_recent_headline_is_not_relabelled_as_future_event(monkeypatch):
    monkeypatch.setattr(event_data.eodhd, "get_news", lambda *a, **k: [
        {"date": "2026-09-06T10:00:00Z", "title": "Company comments on demand", "link": "https://example.com"}
    ])
    monkeypatch.setattr(event_data.eodhd, "LAST_ERROR", None)
    out = event_data.get_recent_news(["NFLX"])
    assert out["articles"][0]["title"] == "Company comments on demand"
    assert "event" not in out["articles"][0]


def test_recent_news_403_falls_back_to_yfinance(monkeypatch):
    monkeypatch.setattr(event_data.eodhd, "get_news", lambda *a, **k: None)
    monkeypatch.setattr(event_data.eodhd, "LAST_ERROR", "403 Forbidden")
    row = {"ticker": "NFLX", "date": "2026-09-07T00:00:00Z", "title": "Fallback headline", "link": None, "sentiment": None, "source": "yfinance News"}
    monkeypatch.setattr(event_data, "_yfinance_news", lambda *a, **k: ([row], None))
    out = event_data.get_recent_news(["NFLX"])
    assert out["articles"] == [row]
    assert out["errors"] == []
    assert out["warnings"]


def test_bls_ics_parser_uses_only_supplied_dates(monkeypatch):
    future = datetime.now(timezone.utc).date() + timedelta(days=2)
    stamp = future.strftime("%Y%m%d") + "T083000"
    ics = f"BEGIN:VCALENDAR\nBEGIN:VEVENT\nDTSTART:{stamp}\nSUMMARY:Consumer Price Index\nEND:VEVENT\nEND:VCALENDAR"
    monkeypatch.setattr(event_data, "_http_text", lambda *a, **k: (ics, None))
    rows, errors = event_data._bls_events(datetime.now(timezone.utc).date(), future + timedelta(days=2))
    assert errors == []
    assert rows[0]["date"] == future.isoformat()
    assert rows[0]["source"] == "BLS Official Calendar"


def test_catalyst_ai_prompt_is_fail_closed_and_contains_only_supplied_dates():
    snapshot = {
        "macro": {"events": [{"date": "2099-01-02", "country": "US", "impact": "Major", "event": "CPI", "estimate": None, "previous": None, "focus": "Macro", "source": "BLS Official Calendar"}], "source": "Official macro calendars"},
        "earnings": {"events": [], "source": "yfinance Earnings Calendar"},
        "recent_news": {"articles": [], "source": "EODHD/yfinance News"},
    }
    prompt = news.build_catalyst_analysis_prompt(snapshot)
    assert "2099-01-02" in prompt
    assert "Do not invent any event, date" in prompt
    assert "No earnings events supplied" in prompt
    assert "No recent headlines supplied" in prompt
    assert "BLS Official Calendar" in prompt


def test_news_module_contains_no_hardcoded_2026_event_dates():
    from pathlib import Path
    text = Path("modules/news.py").read_text() + Path("utils/event_data.py").read_text()
    assert "2026-09" not in text
    assert "FOMC 10" not in text

def test_earnings_fallback_with_no_dates_is_not_reported_as_provider_failure(monkeypatch):
    monkeypatch.setattr(event_data.eodhd, "get_earnings_calendar", lambda *a, **k: None)
    monkeypatch.setattr(event_data.eodhd, "LAST_ERROR", "403 Forbidden")
    # Successful yfinance lookup, simply no earnings inside the selected window.
    monkeypatch.setattr(event_data, "_yfinance_earnings", lambda *a, **k: ([], []))
    out = event_data.get_upcoming_earnings(["NFLX"], days_ahead=7)
    assert out["events"] == []
    assert out["error"] is None
    assert out["source"] == "yfinance Earnings Calendar"
    assert any("fallback active" in w for w in out["warnings"])


def test_news_page_restores_original_visual_hierarchy_without_manual_calendar():
    from pathlib import Path
    text = Path("app.py").read_text()
    news_section = text.split('elif page == "News":', 1)[1]
    assert 'st.title("News")' in news_section
    assert "Also this period" in news_section
    assert "border-left:4px solid" in news_section
    assert "linear-gradient" in news_section
    assert "Earnings calendar" in news_section
    assert "Recent news context" in news_section
    assert "modules.alerts" not in news_section
    assert "No replacement dates are fabricated" in news_section


def test_eodhd_calendar_403_is_cooled_down_across_reruns(monkeypatch):
    calls = {"n": 0}

    def denied(*args, **kwargs):
        calls["n"] += 1
        event_data.eodhd.LAST_ERROR = "403 Forbidden"
        return None

    monkeypatch.setattr(event_data.eodhd, "get_earnings_calendar", denied)
    monkeypatch.setattr(event_data, "_yfinance_earnings", lambda *a, **k: ([], []))

    first = event_data.get_upcoming_earnings(["AON"], days_ahead=21)
    second = event_data.get_upcoming_earnings(["AON"], days_ahead=21)

    assert calls["n"] == 1
    assert first["error"] is None
    assert second["error"] is None


def test_yfinance_429_opens_circuit_breaker_and_stops_watchlist_spam(monkeypatch):
    import logging

    eodhd_calls = {"n": 0}
    yf_calls = {"n": 0}

    def denied(*args, **kwargs):
        eodhd_calls["n"] += 1
        event_data.eodhd.LAST_ERROR = "403 Forbidden"
        return None

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        @property
        def calendar(self):
            yf_calls["n"] += 1
            logging.getLogger("yfinance").error("429 Client Error: Too Many Requests")
            return {}

    monkeypatch.setattr(event_data.eodhd, "get_earnings_calendar", denied)
    monkeypatch.setattr(event_data.yf, "Ticker", FakeTicker)

    out = event_data.get_upcoming_earnings(["AON", "NFLX"], days_ahead=21)
    again = event_data.get_upcoming_earnings(["AON", "NFLX"], days_ahead=21)

    assert eodhd_calls["n"] == 1
    assert yf_calls["n"] == 1  # NFLX is skipped once AON trips the circuit breaker.
    assert out["events"] == []
    assert out["source"] == "Unavailable"
    assert "429" in (out["error"] or "") or any("rate-limit" in w.lower() for w in out["warnings"])
    assert again["events"] == []


def test_yfinance_success_is_cached_across_reruns(monkeypatch):
    yf_calls = {"n": 0}
    future = datetime.now(timezone.utc) + timedelta(days=5)

    monkeypatch.setattr(event_data.eodhd, "get_earnings_calendar", lambda *a, **k: None)
    monkeypatch.setattr(event_data.eodhd, "LAST_ERROR", "403 Forbidden")

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        @property
        def calendar(self):
            yf_calls["n"] += 1
            return {"Earnings Date": [future]}

    monkeypatch.setattr(event_data.yf, "Ticker", FakeTicker)

    first = event_data.get_upcoming_earnings(["NFLX"], days_ahead=21)
    second = event_data.get_upcoming_earnings(["NFLX"], days_ahead=21)

    assert yf_calls["n"] == 1
    assert first["events"] == second["events"]
    assert first["events"][0]["ticker"] == "NFLX"


def test_official_http_calendar_is_cached_within_ttl(monkeypatch):
    calls = {"n": 0}

    class FakeResponse:
        text = "calendar"
        def raise_for_status(self):
            return None

    def fake_get(*args, **kwargs):
        calls["n"] += 1
        return FakeResponse()

    monkeypatch.setattr(event_data.requests, "get", fake_get)
    event_data.clear_event_data_caches()
    assert event_data._http_text("https://example.com/calendar")[0] == "calendar"
    assert event_data._http_text("https://example.com/calendar")[0] == "calendar"
    assert calls["n"] == 1
