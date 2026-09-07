import pandas as pd
from pathlib import Path

from utils.market_calendar import is_market_timestamp_stale
from utils import market_data
from modules import dca, portfolio, screener
from scripts.validate_public_repo import validate


def test_us_friday_quote_fresh_on_labor_day_monday():
    assert is_market_timestamp_stale("XNYS", "2026-09-04", "2026-09-07T12:00:00Z") is False


def test_non_session_provider_date_fails_closed():
    assert is_market_timestamp_stale("XNYS", "2026-09-05", "2026-09-07T12:00:00Z") is True


def test_previous_session_stale_once_next_session_has_opened():
    assert is_market_timestamp_stale("XNYS", "2026-09-04", "2026-09-08T15:00:00Z") is True


def test_compute_open_pnl_converts_native_mark_to_eur(monkeypatch):
    monkeypatch.setattr(market_data, "get_quote", lambda t: {"price":100.0,"currency":"USD","source":"x","timestamp":"x","stale":False})
    monkeypatch.setattr(market_data, "get_fx_quote_to_eur", lambda c: {"rate":0.8,"source":"fx","timestamp":"x","stale":False})
    out = market_data.compute_open_pnl("AAPL", 90.0, 10.0, invested=901.0)
    assert out["current_price_eur"] == 80.0
    assert out["pnl"] == -101.0


def test_compute_open_pnl_rejects_incoherent_broker_cost(monkeypatch):
    monkeypatch.setattr(market_data, "get_quote", lambda t: {"price":100.0,"currency":"USD"})
    monkeypatch.setattr(market_data, "get_fx_quote_to_eur", lambda c: {"rate":0.8})
    assert market_data.compute_open_pnl("AAPL", 90.0, 10.0, invested=2000.0) is None


def test_dca_monthly_prefill_excludes_initial_capital():
    df = pd.DataFrame({
        "date": pd.to_datetime(["2026-01-01","2026-02-01","2026-03-01"]),
        "total_inv": [10000.0,10500.0,11000.0],
        "total_val": [10000.0,10600.0,11200.0],
    })
    stats = dca.compute_global_stats(df)
    assert stats["initial_invested"] == 10000.0
    assert stats["gross_contributions"] == 1000.0
    assert stats["avg_monthly_contribution"] < 1000.0


def test_projection_zero_return_baseline_uses_invested_not_market_value():
    fig = dca.build_projection(12000.0, 100.0, horizons=[1], current_invested=10000.0)
    zero = [trace for trace in fig.data if "0% return" in trace.name][0]
    assert float(zero.y[0]) == 10000.0
    assert float(zero.y[-1]) == 11200.0


def test_screener_does_not_assume_quote_currency_is_reporting_currency(monkeypatch):
    idx = pd.date_range("2026-01-01", periods=30, freq="B")
    hist = pd.DataFrame({"Close":range(100,130),"High":range(101,131),"Low":range(99,129),"Volume":[1000]*30}, index=idx)
    monkeypatch.setattr(screener, "get_price_history_df", lambda *a, **k: hist)
    monkeypatch.setattr(screener, "get_ticker_info", lambda t: {"fundamentals_available":True,"revenue":200_000_000,"financial_currency":None,"currency":"USD","instrument_type":"EQUITY","name":"X"})
    row=screener.fetch_ticker_data("AAPL")
    assert row["revenue_currency"] is None
    assert row["revenue_eur"] is None


def test_validator_rejects_private_key_and_audit_variants(tmp_path):
    (tmp_path / "notes.pem").write_text("dummy")
    (tmp_path / "CHANGES_AUDIT_round99.md").write_text("audit")
    problems=validate(tmp_path)
    assert any("notes.pem" in x for x in problems)
    assert any("CHANGES_AUDIT_round99.md" in x for x in problems)


def test_public_wording_does_not_call_realised_pnl_an_equity_curve():
    text=(Path("README.md").read_text()+Path("app.py").read_text()+Path("modules/portfolio.py").read_text()).lower()
    assert "equity curve — cumulative" not in text
