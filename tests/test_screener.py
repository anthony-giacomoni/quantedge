from datetime import datetime

import pandas as pd

from modules import screener


def test_fundamentals_outage_is_not_zero_revenue(monkeypatch):
    n = 80
    closes = [100.0] * (n - 6) + [80, 79, 78, 77, 76, 75]
    hist = pd.DataFrame({
        "High": [130.0] * n,
        "Low": [70.0] * n,
        "Close": closes,
        "Volume": [500_000] * n,
    })
    monkeypatch.setattr(screener, "get_price_history_df", lambda ticker, years=5: hist)
    monkeypatch.setattr(screener, "get_ticker_info", lambda ticker: {
        "name": ticker,
        "short_pct_float": None,
        "revenue": None,
        "fundamentals_available": False,
        "fundamentals_error": "simulated yfinance outage",
    })

    data = screener.fetch_ticker_data("TEST")
    assert data["total_revenue"] is None
    passes, failed = screener.apply_filters(data)
    assert passes is False
    assert any("Fundamentals unavailable" in reason for reason in failed)
    assert not any("Revenue < $100M" in reason for reason in failed)


def test_short_interest_is_scoring_factor_not_filter():
    base = {
        "drawdown_pct": -0.40,
        "ret_5d": -0.02,
        "avg_volume": 500_000,
        "total_revenue": 1_000_000_000,
    }
    low_short = {**base, "short_pct": 0.0}
    mid_short = {**base, "short_pct": 0.15}
    assert screener.apply_filters(low_short) == screener.apply_filters(mid_short)
    assert screener.compute_score(low_short)["score_short_squeeze"] != screener.compute_score(mid_short)["score_short_squeeze"]


def test_us_market_status_handles_march_dst_gap():
    # 20 March 2026, 15:00 Paris = 10:00 New York (EDT), so NYSE is open.
    status = screener.get_market_status(datetime(2026, 3, 20, 15, 0))
    assert status["zones"]["USA"] is True


def test_us_market_status_respects_christmas_holiday():
    status = screener.get_market_status(datetime(2026, 12, 25, 16, 0))
    assert status["zones"]["USA"] is False
    assert status["holiday_aware"] is True


def test_nan_revenue_cannot_pass_filter():
    data = {
        "drawdown_pct": -0.40, "ret_5d": -0.02, "avg_volume": 500_000,
        "total_revenue": float("nan"), "rel_volume": 1.2,
    }
    passes, failed = screener.apply_filters(data)
    assert passes is False
    assert any("Fundamentals unavailable" in reason for reason in failed)


def test_nan_relative_volume_never_gets_max_score():
    data = {
        "drawdown_pct": -0.40, "ret_5d": -0.02, "avg_volume": 500_000,
        "total_revenue": 1_000_000_000, "rel_volume": float("nan"),
        "short_pct": 0.15, "dist_to_support": 0.1,
        "spike_ratio": None, "spike_percentile": None,
    }
    score = screener.compute_score(data)
    assert score["score_volume"] == 0
    assert score["score_volume"] != 100


def test_fetch_ticker_data_nan_volume_is_unavailable(monkeypatch):
    n = 80
    hist = pd.DataFrame({
        "High": [130.0] * n,
        "Low": [70.0] * n,
        "Close": [80.0] * (n - 6) + [79, 78, 77, 76, 75, 74],
        "Volume": [500_000.0] * (n - 1) + [float("nan")],
    })
    monkeypatch.setattr(screener, "get_price_history_df", lambda ticker, years=5: hist)
    monkeypatch.setattr(screener, "get_ticker_info", lambda ticker: {
        "name": ticker, "short_pct_float": 0.1, "revenue": 1_000_000_000,
        "fundamentals_available": True, "fundamentals_error": None,
    })
    data = screener.fetch_ticker_data("TEST")
    assert data["rel_volume"] is None
    score = screener.compute_score(data)
    assert score["score_volume"] == 0


def test_screener_uses_five_year_high_wording():
    assert "5Y High Drawdown" in list(screener.format_screener_results(pd.DataFrame([{
        "ticker":"X", "name":"X", "sector":"US Energy", "current_price":1,
        "drawdown_pct":-0.4, "ret_5d":0.0, "short_pct":None, "rel_volume":None,
        "spike_ratio":None, "score_total":50, "passes_filter":False
    }])).columns)


def test_open_tickers_maps_region_names_correctly():
    eu = screener.get_open_tickers({"open_zones": ["Europe"]})
    assert "ENI.MI" in eu
    assert "RHM.DE" in eu
    assert "NVDA" not in eu

    us = screener.get_open_tickers({"open_zones": ["USA"]})
    assert "NVDA" in us
    assert "GLD" in us
    assert "ENI.MI" not in us


def test_missing_five_session_return_fails_safely():
    data = {
        "drawdown_pct": -0.40, "ret_5d": None, "avg_volume": 500_000,
        "total_revenue": 1_000_000_000,
    }
    passes, failed = screener.apply_filters(data)
    assert passes is False
    assert any("5-session return unavailable" in x for x in failed)


def test_missing_optional_scores_do_not_receive_neutral_bonus():
    data = {
        "drawdown_pct": -0.40, "ret_5d": -0.02, "avg_volume": 500_000,
        "total_revenue": 1_000_000_000, "rel_volume": 1.0,
        "short_pct": None, "dist_to_support": 0.1,
        "spike_ratio": None, "spike_percentile": None,
    }
    score = screener.compute_score(data)
    assert score["score_short_squeeze"] == 0
    assert score["score_spike"] == 0


def test_etf_is_not_rejected_for_missing_corporate_revenue():
    data = {"drawdown_pct":-0.40,"ret_5d":-0.02,"avg_volume":500_000,
            "total_revenue":None,"instrument_type":"ETF"}
    passes, failed = screener.apply_filters(data)
    assert passes is True
    assert not any("revenue" in x.lower() for x in failed)


def test_equity_respects_100m_eur_equivalent_revenue_threshold():
    base = {"drawdown_pct":-0.40,"ret_5d":-0.02,"avg_volume":500_000,"instrument_type":"EQUITY", "total_revenue": 1}
    assert screener.apply_filters({**base,"revenue_eur":100_000_000})[0] is True
    assert screener.apply_filters({**base,"revenue_eur":99_999_999})[0] is False


def test_relative_volume_uses_previous_20_sessions_not_current_bar(monkeypatch):
    n = 30
    hist = pd.DataFrame({
        "High":[150.0]*n, "Low":[70.0]*n,
        "Close":[100.0]*(n-6)+[80,79,78,77,76,75],
        "Volume":[100.0]*(n-1)+[1000.0],
    })
    monkeypatch.setattr(screener, "get_price_history_df", lambda ticker, years=5: hist)
    monkeypatch.setattr(screener, "get_ticker_info", lambda ticker: {
        "name":ticker,"short_pct_float":None,"revenue":1.0,"instrument_type":"EQUITY",
        "fundamentals_available":True,"fundamentals_error":None,"fundamentals_source":"yfinance",
    })
    data = screener.fetch_ticker_data("TEST")
    assert data["avg_volume"] == 100
    assert data["rel_volume"] == 10.0


def test_market_open_selection_uses_listing_not_theme_bucket():
    us = screener.get_open_tickers({"open_zones":["USA"]})
    asia = screener.get_open_tickers({"open_zones":["Asia"]})
    # US-listed ADRs stay on the US calendar even if grouped thematically under Asia.
    assert "TSM" in us and "TSM" not in asia
    assert "0857.HK" in asia and "0857.HK" not in us
    assert "STO.AX" in asia


def test_static_universe_has_no_known_stale_or_mislabelled_symbols():
    assert "EDF.PA" not in screener.ALL_TICKERS
    assert "PTR" not in screener.ALL_TICKERS
    assert "SNP" not in screener.ALL_TICKERS
    assert "STO" not in screener.ALL_TICKERS
    assert "SIE.DE" not in screener.ALL_TICKERS
    assert "ENR.DE" in screener.ALL_TICKERS
    assert "DASSAV.PA" not in screener.ALL_TICKERS
    assert "AM.PA" in screener.ALL_TICKERS


def test_formatting_never_emits_nan_string():
    df = pd.DataFrame([{"ticker":"X","name":"X","sector":"US Energy","current_price":1,
        "drawdown_pct":float('nan'),"ret_5d":float('nan'),"short_pct":float('nan'),
        "rel_volume":float('nan'),"spike_ratio":float('nan'),"score_total":50,
        "data_coverage_pct":33.3,"passes_filter":False}])
    display = screener.format_screener_results(df)
    assert not display.astype(str).apply(lambda c: c.str.contains("nan", case=False).any()).any()


def test_open_tickers_exact_calendar_overrides_regional_proxy():
    import pandas as pd
    status=screener.get_market_status(pd.Timestamp("2026-01-02T03:00:00Z"))
    # Tokyo is closed, but Hong Kong is trading; regional aggregation must therefore report Asia open.
    assert status["zones"]["Asia"] is True
    open_tickers=screener.get_open_tickers(status)
    assert "0857.HK" in open_tickers


def test_static_etf_type_survives_fundamentals_provider_outage(monkeypatch):
    n = 30
    hist = pd.DataFrame({
        "High": [150.0] * n,
        "Low": [70.0] * n,
        "Close": [100.0] * (n - 6) + [80, 79, 78, 77, 76, 75],
        "Volume": [500_000.0] * n,
    })
    monkeypatch.setattr(screener, "get_price_history_df", lambda ticker, years=5: hist)
    monkeypatch.setattr(screener, "get_ticker_info", lambda ticker: {
        "name": ticker,
        "short_pct_float": None,
        "revenue": None,
        "instrument_type": None,
        "fundamentals_available": False,
        "fundamentals_error": "simulated outage",
    })
    data = screener.fetch_ticker_data("XLE")
    assert data["instrument_type"] == "ETF"
    assert screener.apply_filters(data)[0] is True


def test_unavailable_equity_fundamentals_reason_is_not_duplicated():
    data = {"drawdown_pct": -0.40, "ret_5d": -0.02, "avg_volume": 500_000,
            "instrument_type": "EQUITY", "total_revenue": None}
    passes, failed = screener.apply_filters(data)
    assert passes is False
    matches = [x for x in failed if "Fundamentals unavailable" in x]
    assert len(matches) == 1


def test_static_universe_is_unique_and_every_listing_is_supported():
    from utils.market_data import ticker_currency, ticker_market_zone, ticker_exchange_calendar
    assert len(screener.ALL_TICKERS) == len(set(screener.ALL_TICKERS))
    bad = []
    for ticker in screener.ALL_TICKERS:
        if (ticker_currency(ticker) == "UNKNOWN" or
                ticker_market_zone(ticker) == "UNKNOWN" or
                ticker_exchange_calendar(ticker) is None):
            bad.append(ticker)
    assert bad == []


def test_revenue_threshold_uses_financial_currency_fx(monkeypatch):
    n = 30
    hist = pd.DataFrame({
        "High": [150.0] * n, "Low": [70.0] * n,
        "Close": [100.0] * (n - 6) + [80, 79, 78, 77, 76, 75],
        "Volume": [500_000.0] * n,
    })
    monkeypatch.setattr(screener, "get_price_history_df", lambda ticker, years=5: hist)
    monkeypatch.setattr(screener, "get_ticker_info", lambda ticker: {
        "name": ticker, "short_pct_float": 0.1,
        "revenue": 120_000_000, "instrument_type": "EQUITY",
        "financial_currency": "USD", "currency": "USD",
        "fundamentals_available": True, "fundamentals_error": None,
        "fundamentals_source": "yfinance",
    })
    monkeypatch.setattr(screener, "_reporting_currency_fx_to_eur", lambda currency: {
        "rate": 0.8, "source": "test FX", "stale": False, "error": None,
    })
    data = screener.fetch_ticker_data("TEST")
    assert data["total_revenue"] == 120_000_000
    assert data["revenue_currency"] == "USD"
    assert data["revenue_eur"] == 96_000_000
    passes, failed = screener.apply_filters(data)
    assert passes is False
    assert any("below €100M equivalent" in x for x in failed)


def test_revenue_fx_unavailable_fails_closed_without_calling_revenue_zero():
    data = {
        "drawdown_pct": -0.40, "ret_5d": -0.02, "avg_volume": 500_000,
        "instrument_type": "EQUITY", "total_revenue": 500_000_000,
        "revenue_eur": None, "revenue_fx_error": "FX outage",
    }
    passes, failed = screener.apply_filters(data)
    assert passes is False
    assert any("Revenue FX unavailable" in x for x in failed)
    assert not any("below €100M" in x for x in failed)
