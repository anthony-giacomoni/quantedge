import pandas as pd

from utils import market_data, eodhd, event_data
from modules import screener


def test_stale_eodhd_quote_uses_fresh_yfinance_fallback(monkeypatch):
    monkeypatch.setattr(market_data, "EODHD_KEY", "fake")

    monkeypatch.setattr(eodhd, "get_quote", lambda ticker: {
        "ticker": ticker,
        "price": 100.0,
        "currency": "USD",
        "source": "EODHD delayed quote",
        "timestamp": "2026-09-03T20:00:00+00:00",
        "stale": True,
        "error": None,
    })

    monkeypatch.setattr(market_data, "_yfinance_quote", lambda ticker: {
        "ticker": ticker,
        "price": 101.0,
        "currency": "USD",
        "source": "yfinance",
        "timestamp": "2026-09-04T20:00:00+00:00",
        "stale": False,
        "error": None,
    })

    quote = market_data.get_quote("AAPL")

    assert quote["source"] == "yfinance"
    assert quote["price"] == 101.0
    assert "stale EODHD quote" in quote["fallback_reason"]


def test_stale_eodhd_quote_is_preserved_if_no_fresher_fallback(monkeypatch):
    monkeypatch.setattr(market_data, "EODHD_KEY", "fake")

    monkeypatch.setattr(eodhd, "get_quote", lambda ticker: {
        "ticker": ticker,
        "price": 100.0,
        "currency": "USD",
        "source": "EODHD delayed quote",
        "timestamp": "2026-09-03T20:00:00+00:00",
        "stale": True,
        "error": None,
    })

    monkeypatch.setattr(market_data, "_yfinance_quote", lambda ticker: {
        "ticker": ticker,
        "price": None,
        "currency": "USD",
        "source": "yfinance",
        "timestamp": None,
        "stale": True,
        "error": "offline",
    })

    quote = market_data.get_quote("AAPL")

    assert quote["source"] == "EODHD delayed quote"
    assert quote["price"] == 100.0
    assert quote["stale"] is True
    assert quote["fallback_reason"] == "offline"


def test_stale_eodhd_fx_uses_fresh_yfinance_fallback(monkeypatch):
    monkeypatch.setattr(market_data, "EODHD_KEY", "fake")

    monkeypatch.setattr(
        "utils.eodhd.get_usd_eur_quote",
        lambda: {
            "rate": 0.80,
            "source": "EODHD delayed FX",
            "timestamp": "2026-08-28T20:00:00+00:00",
            "stale": True,
            "error": None,
        },
    )

    idx = pd.DatetimeIndex([pd.Timestamp.now(tz="UTC")])
    hist = pd.DataFrame({"Close": [0.86]}, index=idx)

    class FakeTicker:
        def history(self, period, interval=None):
            assert period == "5d"
            assert interval == "1h"
            return hist

    monkeypatch.setattr(market_data.yf, "Ticker", lambda ticker: FakeTicker())

    fx = market_data.get_fx_quote_to_eur("USD")

    assert fx["source"] == "yfinance FX"
    assert fx["rate"] == 0.86
    assert fx["stale"] is False
    assert "stale EODHD FX" in fx["fallback_reason"]


def test_fundamentals_normalize_provider_specific_symbol(monkeypatch):
    seen = []

    class FakeTicker:
        @property
        def info(self):
            return {
                "longName": "BHP",
                "marketCap": 1_000_000_000,
            }

    def factory(symbol):
        seen.append(symbol)
        return FakeTicker()

    monkeypatch.setattr(market_data.yf, "Ticker", factory)

    out = market_data.get_fundamentals("BHP.AU")

    assert out["_available"] is True
    assert seen == ["BHP.AX"]


def test_wide_cache_normalizes_all_supported_eodhd_dialects(monkeypatch):
    monkeypatch.setattr(
        "utils.db.get_latest_snapshot_date",
        lambda db_path: "2026-09-07",
    )

    monkeypatch.setattr(
        "utils.db.load_universe_snapshot",
        lambda snapshot_date, db_path: pd.DataFrame([
            {"ticker": "AAPL.US", "market_cap": 2e9, "sector": "Tech"},
            {"ticker": "BHP.AU", "market_cap": 2e9, "sector": "Materials"},
            {"ticker": "ENR.XETRA", "market_cap": 2e9, "sector": "Energy"},
            {"ticker": "BA.LSE", "market_cap": 2e9, "sector": "Industrials"},
        ]),
    )

    out = screener.get_wide_universe_from_cache(db_path="x")

    assert out["tickers"] == [
        "AAPL",
        "BHP.AX",
        "ENR.DE",
        "BA.L",
    ]


def test_market_status_message_lists_each_region_once():
    out = screener.get_market_status(
        pd.Timestamp("2026-09-07T10:00:00Z")
    )

    for region in ("Asia", "Europe", "USA"):
        assert out["message"].count(f"- {region} :") == 1


def test_earnings_output_uses_canonical_symbol(monkeypatch):
    event_data.clear_event_data_caches()

    future = (
        pd.Timestamp.now(tz="Europe/Paris")
        + pd.Timedelta(days=2)
    ).date().isoformat()

    monkeypatch.setattr(
        event_data.eodhd,
        "get_earnings_calendar",
        lambda *args, **kwargs: [{
            "report_date": future,
            "code": "BHP.AU",
        }],
    )

    monkeypatch.setattr(event_data.eodhd, "LAST_ERROR", None)

    out = event_data.get_upcoming_earnings(
        ["BHP.AU"],
        days_ahead=7,
    )

    assert out["events"][0]["ticker"] == "BHP.AX"

def test_yahoo_special_symbols_fail_closed_instead_of_becoming_us_equities():
    import utils.market_data as md

    for ticker in ("BZ=F", "EURUSD=X"):
        assert md.ticker_currency(ticker) == "UNKNOWN"
        assert md.ticker_market_zone(ticker) == "UNKNOWN"
        assert md.ticker_exchange_calendar(ticker) is None

