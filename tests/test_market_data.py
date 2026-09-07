import time

import pandas as pd

from utils import market_data
from utils import eodhd


def test_exchange_currency_mapping():
    assert market_data.ticker_currency("ENI.MI") == "EUR"
    assert market_data.ticker_currency("AIR.PA") == "EUR"
    assert market_data.ticker_currency("HSBA.L") == "GBP"
    assert market_data.ticker_currency("9988.HK") == "HKD"
    assert market_data.ticker_currency("2330.TW") == "TWD"
    assert market_data.ticker_currency("NFLX") == "USD"


def test_eodhd_none_falls_back_to_yfinance(monkeypatch):
    monkeypatch.setattr(market_data, "EODHD_KEY", "fake")
    monkeypatch.setattr(eodhd, "get_quote", lambda ticker: {
        "ticker": ticker, "price": None, "source": "EODHD", "timestamp": None,
        "stale": True, "error": "simulated outage",
    })
    monkeypatch.setattr(market_data, "_yfinance_quote", lambda ticker: {
        "ticker": ticker, "price": 120.0, "currency": "USD", "source": "yfinance",
        "timestamp": None, "age_hours": None, "stale": False, "error": None,
    })
    quote = market_data.get_quote("AON")
    assert quote["price"] == 120.0
    assert quote["source"] == "yfinance"
    assert "simulated outage" in quote["fallback_reason"]


def test_staleness_is_per_ticker(monkeypatch):
    from datetime import datetime, timezone
    stale_ts = int(datetime(2026,9,3,20,0,tzinfo=timezone.utc).timestamp())
    fresh_ts = int(datetime(2026,9,4,20,0,tzinfo=timezone.utc).timestamp())

    def fake_get(endpoint, params=None):
        if endpoint == "real-time/NFLX.US":
            return {"close": 100, "timestamp": stale_ts}
        if endpoint == "real-time/AON.US":
            return {"close": 200, "timestamp": fresh_ts}
        return None

    monkeypatch.setattr(eodhd, "_get", fake_get)
    q1 = eodhd.get_quote("NFLX")
    q2 = eodhd.get_quote("AON")
    assert q1["stale"] is True
    assert q2["stale"] is False
    assert eodhd.QUOTE_DEBUG_BY_TICKER["NFLX"]["stale"] is True
    assert eodhd.QUOTE_DEBUG_BY_TICKER["AON"]["stale"] is False

def test_five_session_return_uses_six_closes(monkeypatch):
    hist = pd.DataFrame({
        "High": [100, 101, 102, 103, 104, 105],
        "Low": [100, 101, 102, 103, 104, 105],
        "Close": [100, 101, 102, 103, 104, 105],
        "Volume": [1_000_000] * 6,
    })
    monkeypatch.setattr(market_data, "get_price_history_df", lambda ticker, years=1: hist)
    assert market_data.get_5d_return("TEST") == 0.05


def test_market_zone_mapping():
    assert market_data.ticker_market_zone("NFLX") == "USA"
    assert market_data.ticker_market_zone("ENI.MI") == "Europe"
    assert market_data.ticker_market_zone("HSBA.L") == "Europe"
    assert market_data.ticker_market_zone("9988.HK") == "Asia"
    assert market_data.ticker_market_zone("2330.TW") == "Asia"


def test_nan_and_inf_fundamentals_are_normalized_to_unavailable(monkeypatch):
    class FakeTicker:
        @property
        def info(self):
            return {
                "longName": "Bad Data Co",
                "totalRevenue": float("nan"),
                "marketCap": float("inf"),
                "shortPercentOfFloat": float("nan"),
                "trailingPE": 12.0,
            }
    monkeypatch.setattr(market_data.yf, "Ticker", lambda ticker: FakeTicker())
    f = market_data.get_fundamentals("BAD")
    assert f["_available"] is True
    assert f["revenue"] is None
    assert f["market_cap"] is None
    assert f["short_pct"] is None
    assert f["pe_ratio"] == 12.0


def test_structured_fx_quote_from_yfinance(monkeypatch):
    idx = pd.DatetimeIndex([pd.Timestamp.now(tz="UTC")])
    hist = pd.DataFrame({"Close": [0.9]}, index=idx)
    class FakeTicker:
        def history(self, period, interval=None):
            assert period == "5d"
            assert interval == "1h"
            return hist
    monkeypatch.setattr(market_data, "EODHD_KEY", None)
    monkeypatch.setattr(market_data.yf, "Ticker", lambda ticker: FakeTicker())
    fx = market_data.get_fx_quote_to_eur("USD")
    assert fx["rate"] == 0.9
    assert fx["source"] == "yfinance FX"
    assert fx["timestamp"] is not None
    assert fx["stale"] is False


def test_nonfinite_eodhd_price_falls_back(monkeypatch):
    monkeypatch.setattr(market_data, "EODHD_KEY", "fake")
    monkeypatch.setattr(eodhd, "get_quote", lambda ticker: {
        "ticker": ticker, "price": float("nan"), "source": "EODHD",
        "timestamp": None, "stale": False, "error": None,
    })
    monkeypatch.setattr(eodhd, "LAST_ERROR", None)
    monkeypatch.setattr(market_data, "_yfinance_quote", lambda ticker: {
        "ticker": ticker, "price": 123.0, "currency": "USD", "source": "yfinance",
        "timestamp": None, "age_hours": None, "stale": False, "error": None,
    })
    quote = market_data.get_quote("TEST")
    assert quote["price"] == 123.0
    assert "invalid/non-finite" in quote["fallback_reason"]


def test_nonfinite_yfinance_price_is_unavailable(monkeypatch):
    class FakeTicker:
        def history(self, period):
            idx = pd.DatetimeIndex([pd.Timestamp.now(tz="UTC")])
            return pd.DataFrame({"Close": [float("inf")]}, index=idx)
    monkeypatch.setattr(market_data.yf, "Ticker", lambda ticker: FakeTicker())
    quote = market_data._yfinance_quote("TEST")
    assert quote["price"] is None
    assert quote["stale"] is True


def test_unknown_exchange_suffix_fails_closed():
    assert market_data.ticker_currency("ABC.XYZ") == "UNKNOWN"
    assert market_data.ticker_market_zone("ABC.XYZ") == "UNKNOWN"
    assert market_data.ticker_currency("AAPL") == "USD"
    assert market_data.ticker_market_zone("AAPL") == "USA"


def test_australian_listing_mapping():
    assert market_data.ticker_currency("STO.AX") == "AUD"
    assert market_data.ticker_market_zone("STO.AX") == "Asia"


def test_normalize_eodhd_ticker_for_yfinance():
    assert market_data.normalize_yfinance_ticker("AAPL.US") == "AAPL"
    assert market_data.normalize_yfinance_ticker("ENR.XETRA") == "ENR.DE"
    assert market_data.normalize_yfinance_ticker("BA.LSE") == "BA.L"


def test_history_metadata_reports_yfinance_fallback(monkeypatch):
    idx = pd.date_range("2026-01-01", periods=10, freq="D")
    hist = pd.DataFrame({"Close": range(10, 20), "High": range(11, 21), "Low": range(9, 19), "Volume": [100]*10}, index=idx)
    monkeypatch.setattr(market_data, "EODHD_KEY", "fake")
    from utils import eodhd
    monkeypatch.setattr(eodhd, "get_eod_history", lambda ticker, years=5: None)
    monkeypatch.setattr(eodhd, "LAST_ERROR", "simulated EODHD outage")
    monkeypatch.setattr(market_data, "_yf_history", lambda ticker, period: hist)
    meta = market_data.get_price_history_with_meta("AAPL", 5)
    assert meta["source"] == "yfinance"
    assert meta["fallback_reason"] == "simulated EODHD outage"
    assert meta["as_of"] is not None


def test_exchange_calendar_mapping_is_listing_specific():
    assert market_data.ticker_exchange_calendar("AAPL") == "XNYS"
    assert market_data.ticker_exchange_calendar("0700.HK") == "XHKG"
    assert market_data.ticker_exchange_calendar("2330.TW") == "XTAI"
    assert market_data.ticker_exchange_calendar("STO.AX") == "XASX"
    assert market_data.ticker_exchange_calendar("ABC.XYZ") is None


def test_hong_kong_and_tokyo_holidays_are_not_conflated():
    # 2 Jan 2026: Hong Kong has a session while Tokyo is closed.
    import pandas as pd
    hk_noon_utc = pd.Timestamp("2026-01-02T03:00:00Z")
    assert market_data.is_ticker_market_open("0700.HK", hk_noon_utc) is True
    from modules import screener
    regional = screener.get_market_status(hk_noon_utc)
    assert regional["zones"]["Asia"] is True  # Region is open because Hong Kong is trading even though Tokyo is closed.


def test_london_yfinance_quote_is_normalized_from_pence_to_gbp(monkeypatch):
    idx = pd.DatetimeIndex([pd.Timestamp.now(tz="UTC")])
    hist = pd.DataFrame({"Close": [542.5]}, index=idx)  # 542.5 GBp = £5.425
    class FakeTicker:
        def history(self, period): return hist
    monkeypatch.setattr(market_data.yf, "Ticker", lambda ticker: FakeTicker())
    quote = market_data._yfinance_quote("BP.L")
    assert quote["currency"] == "GBP"
    assert quote["price"] == 5.425
    assert quote["price_unit_normalization"] == "GBp→GBP /100"


def test_london_eodhd_quote_is_normalized_from_venue_pence_to_gbp(monkeypatch):
    # This unit test verifies GBp -> GBP normalization only. Freshness and
    # provider fallback are covered separately, so keep this test deterministic
    # and forbid accidental network/yfinance use.
    monkeypatch.setattr(market_data, "EODHD_KEY", "fake")
    monkeypatch.setattr(
        market_data,
        "is_market_timestamp_stale",
        lambda *args, **kwargs: False,
    )
    monkeypatch.setattr(
        market_data,
        "_yfinance_quote",
        lambda ticker: (
            _ for _ in ()
        ).throw(
            AssertionError(
                "London normalization test must not fall back to yfinance"
            )
        ),
    )
    monkeypatch.setattr(eodhd, "get_quote", lambda ticker: {
        "ticker": ticker,
        "price": 1911.0,
        "source": "EODHD delayed quote",
        "timestamp": "2026-09-04T15:30:00+00:00",
        "stale": False,
        "error": None,
    })

    quote = market_data.get_quote("GSK.L")

    assert quote["currency"] == "GBP"
    assert quote["price"] == 19.11
    assert quote["source"] == "EODHD delayed quote"
    assert quote["price_unit_normalization"] == "GBp→GBP /100"


def test_london_history_is_normalized_to_gbp(monkeypatch):
    idx = pd.date_range("2026-01-01", periods=6, freq="D")
    hist = pd.DataFrame({
        "Open":[500,501,502,503,504,505], "High":[510,511,512,513,514,515],
        "Low":[490,491,492,493,494,495], "Close":[500,501,502,503,504,505],
        "Volume":[100]*6,
    }, index=idx)
    monkeypatch.setattr(market_data, "EODHD_KEY", None)
    monkeypatch.setattr(market_data, "_yf_history", lambda ticker, period: hist)
    monkeypatch.setattr(market_data, "is_market_timestamp_stale", lambda *args, **kwargs: False)
    meta = market_data.get_price_history_with_meta("BP.L", 5)
    assert meta["data"]["Close"].iloc[-1] == 5.05
    assert meta["data"]["High"].iloc[-1] == 5.15
    assert market_data.get_5d_return("BP.L") == 0.01


def test_empty_ticker_fails_closed():
    assert market_data.ticker_currency("") == "UNKNOWN"
    assert market_data.ticker_market_zone("") == "UNKNOWN"
    assert market_data.ticker_exchange_calendar("") is None


def test_fundamentals_non_dict_payload_is_unavailable(monkeypatch):
    class FakeTicker:
        @property
        def info(self):
            return "provider returned HTML instead of JSON"
    monkeypatch.setattr(market_data.yf, "Ticker", lambda ticker: FakeTicker())
    f = market_data.get_fundamentals("BAD")
    assert f["_available"] is False
    assert "invalid response type" in f["_error"]


def test_future_yfinance_daily_session_is_marked_stale(monkeypatch):
    idx = pd.DatetimeIndex([
        pd.Timestamp(
            "2099-01-02 00:00:00",
            tz="America/New_York",
        )
    ])
    hist = pd.DataFrame({"Close": [100.0]}, index=idx)

    class FakeTicker:
        def history(self, period):
            return hist

    monkeypatch.setattr(
        market_data.yf,
        "Ticker",
        lambda ticker: FakeTicker(),
    )
    monkeypatch.setattr(
        market_data,
        "is_ticker_market_open",
        lambda ticker: False,
    )

    seen = {}

    def fake_stale(calendar, timestamp, **kwargs):
        seen["timestamp"] = timestamp
        return True

    monkeypatch.setattr(
        market_data,
        "is_market_timestamp_stale",
        fake_stale,
    )

    q = market_data._yfinance_quote("AAPL")

    assert q["price"] == 100.0
    assert q["stale"] is True
    assert q["timestamp"] == "2099-01-02"
    assert q["age_hours"] is None
    assert seen["timestamp"] == "2099-01-02"


def test_future_yfinance_fx_is_marked_stale(monkeypatch):
    idx = pd.DatetimeIndex([pd.Timestamp.now(tz="UTC") + pd.Timedelta(hours=2)])
    hist = pd.DataFrame({"Close": [0.9]}, index=idx)
    class FakeTicker:
        def history(self, period, interval=None):
            assert period == "5d"
            assert interval == "1h"
            return hist
    monkeypatch.setattr(market_data, "EODHD_KEY", None)
    monkeypatch.setattr(market_data.yf, "Ticker", lambda ticker: FakeTicker())
    fx = market_data.get_fx_quote_to_eur("USD")
    assert fx["rate"] == 0.9
    assert fx["stale"] is True


def test_yfinance_history_sanitizes_nonpositive_and_nonfinite_closes(monkeypatch):
    idx = pd.to_datetime([
        "2026-01-02",
        "2026-01-05",
        "2026-01-06",
        "2026-01-07",
        "2026-01-08",
    ])
    hist = pd.DataFrame({
        "Open": [100.0, 1.0, 1.0, 1.0, 105.0],
        "Close": [100.0, float("nan"), 0.0, float("inf"), 105.0],
        "High": [101.0, 1.0, 1.0, 1.0, 106.0],
        "Low": [99.0, 1.0, 1.0, 1.0, 104.0],
        "Volume": [100, -1, 100, 100, 200],
    }, index=idx)
    class FakeTicker:
        def history(self, period): return hist
    monkeypatch.setattr(market_data.yf, "Ticker", lambda ticker: FakeTicker())
    cleaned = market_data._yf_history("AAPL", "1y")
    assert cleaned is not None
    assert cleaned["Close"].tolist() == [100.0, 105.0]
    assert (cleaned["Close"] > 0).all()


def test_funnel_normalizes_eodhd_ticker_before_yfinance(monkeypatch):
    seen = []
    def fake_fund(ticker):
        seen.append(ticker)
        return {"_available": True, "market_cap": 2_000_000_000}
    monkeypatch.setattr(market_data, "get_fundamentals", fake_fund)
    assert market_data.funnel_screen(["AAPL.US"]) == ["AAPL.US"]
    assert seen == ["AAPL"]

def test_timestamped_quote_near_session_close_required_outside_session():
    from utils.market_calendar import is_market_timestamp_stale

    # NYSE closes at 20:00 UTC on 8 Sep 2026.
    # An early-session quote must not remain fresh after the close merely
    # because it belongs to the latest expected market session.
    assert is_market_timestamp_stale(
        "XNYS",
        "2026-09-08T14:00:00+00:00",
        now="2026-09-08T21:00:00+00:00",
        intraday_max_age_minutes=90,
    ) is True

    # A timestamp close to the completed session close remains acceptable.
    assert is_market_timestamp_stale(
        "XNYS",
        "2026-09-08T19:30:00+00:00",
        now="2026-09-08T23:00:00+00:00",
        intraday_max_age_minutes=90,
    ) is False

    # Same protection before the following session opens.
    assert is_market_timestamp_stale(
        "XNYS",
        "2026-09-08T14:00:00+00:00",
        now="2026-09-09T12:00:00+00:00",
        intraday_max_age_minutes=90,
    ) is True

def test_history_sanitizer_deduplicates_same_session_date(monkeypatch):
    idx = pd.DatetimeIndex([
        pd.Timestamp("2026-09-01 00:00:00"),
        pd.Timestamp("2026-09-01 12:00:00"),
        pd.Timestamp("2026-09-02 00:00:00"),
        pd.Timestamp("2026-09-03 00:00:00"),
        pd.Timestamp("2026-09-04 00:00:00"),
        pd.Timestamp("2026-09-08 00:00:00"),
    ])
    hist = pd.DataFrame({
        "Open":   [100, 101, 102, 103, 104, 105],
        "High":   [102, 103, 104, 105, 106, 107],
        "Low":    [99, 100, 101, 102, 103, 104],
        "Close":  [101, 102, 103, 104, 105, 106],
        "Volume": [1000, 1000, 1000, 1000, 1000, 1000],
    }, index=idx)

    cleaned = market_data._sanitize_history_df("AAPL", hist)

    assert cleaned is not None
    assert len(cleaned) == 5
    assert len(set(cleaned.index.date)) == 5

    # Keep the last chronological provider record for the duplicated session.
    assert cleaned.index[0] == pd.Timestamp("2026-09-01 12:00:00")
    assert cleaned["Close"].iloc[0] == 102

    # Five distinct sessions are insufficient for a five-session return:
    # six distinct closes are required.
    monkeypatch.setattr(
        market_data,
        "get_price_history_df",
        lambda ticker, years=1: cleaned,
    )
    assert market_data.get_5d_return("AAPL") is None

def test_yfinance_daily_bar_fails_closed_during_exchange_break(monkeypatch):
    import pandas as pd
    import utils.market_data as md

    # XHKG lunch break: the exchange is not open on this exact minute,
    # but the daily trading session has not completed.
    now = pd.Timestamp("2026-01-05T04:30:00Z")

    assert md.is_ticker_market_open(
        "0700.HK",
        now,
    ) is False

    assert md.is_ticker_session_in_progress(
        "0700.HK",
        now,
    ) is True

    hist = pd.DataFrame(
        {"Close": [100.0]},
        index=pd.DatetimeIndex([
            pd.Timestamp(
                "2026-01-05 00:00:00",
                tz="Asia/Hong_Kong",
            )
        ]),
    )

    class FakeTicker:
        def history(self, period):
            assert period == "5d"
            return hist

    monkeypatch.setattr(
        md.yf,
        "Ticker",
        lambda ticker: FakeTicker(),
    )

    # Force the exact condition demonstrated by the hostile audit.
    monkeypatch.setattr(
        md,
        "is_ticker_session_in_progress",
        lambda ticker: True,
    )

    monkeypatch.setattr(
        md,
        "is_market_timestamp_stale",
        lambda *args, **kwargs: (
            _ for _ in ()
        ).throw(
            AssertionError(
                "current daily session must fail closed before "
                "date-only freshness evaluation"
            )
        ),
    )

    quote = md._yfinance_quote("0700.HK")

    assert quote["price"] == 100.0
    assert quote["stale"] is True

