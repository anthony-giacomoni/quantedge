import pandas as pd
from modules import portfolio
from utils.db import init_database, insert_trade


def test_milan_quote_is_not_converted_as_usd(monkeypatch, tmp_path):
    db_path = str(tmp_path / "test.db")
    init_database(db_path)
    insert_trade({
        "ticker": "ENI.MI", "direction": "LONG", "qty": 1.0,
        "entry_price": 90.0, "entry_date": "2026-01-01",
        "exit_price": None, "exit_date": None, "pnl": None,
        "invested": 90.0, "status": "OPEN", "sector": "Energy", "notes": "",
    }, db_path)

    monkeypatch.setattr(portfolio, "get_quote", lambda ticker: {
        "ticker": ticker, "price": 100.0, "currency": "EUR", "source": "test",
        "timestamp": None, "stale": False, "error": None,
    })
    monkeypatch.setattr(portfolio, "get_fx_quote_to_eur", lambda currency: {"currency": currency, "rate": 1.0, "source": "identity", "timestamp": None, "stale": False, "error": None})

    df = portfolio.load_enriched_trades(db_path)
    row = df.iloc[0]
    assert row["quote_currency"] == "EUR"
    assert row["current_price"] == 100.0
    assert row["pnl"] == 10.0


def test_usd_quote_is_converted_to_eur_before_comparing_broker_eur_entry(monkeypatch, tmp_path):
    db_path = str(tmp_path / "test_usd.db")
    init_database(db_path)
    insert_trade({
        "ticker": "NFLX", "direction": "LONG", "qty": 1.0,
        "entry_price": 80.0, "entry_date": "2026-01-01",
        "exit_price": None, "exit_date": None, "pnl": None,
        "invested": 80.0, "status": "OPEN", "sector": "Tech", "notes": "",
    }, db_path)

    monkeypatch.setattr(portfolio, "get_quote", lambda ticker: {
        "ticker": ticker, "price": 100.0, "currency": "USD", "source": "test",
        "timestamp": None, "stale": False, "error": None,
    })
    monkeypatch.setattr(portfolio, "get_fx_quote_to_eur", lambda currency: {
        "currency": currency, "rate": 0.9, "source": "test FX",
        "timestamp": "2026-09-06T12:00:00+00:00", "stale": True, "error": None,
    })

    row = portfolio.load_enriched_trades(db_path).iloc[0]

    assert pd.isna(row["current_price"])
    assert row["entry_price_eur"] == 80.0
    assert pd.isna(row["pnl"])

    assert row["fx_source"] == "test FX"
    assert row["fx_timestamp"] == "2026-09-06T12:00:00+00:00"
    assert bool(row["fx_stale"]) is True
    assert bool(row["pricing_stale"]) is True
    assert "stale" in row["pricing_error"].lower()

def _insert_open(db_path, ticker="TEST", direction="LONG", qty=1.0, entry=100.0):
    insert_trade({
        "ticker": ticker, "direction": direction, "qty": qty,
        "entry_price": entry, "entry_date": "2026-01-01",
        "exit_price": None, "exit_date": None, "pnl": None,
        "invested": 100.0, "status": "OPEN", "sector": "Test", "notes": "",
    }, db_path)


def test_invalid_direction_is_not_treated_as_short(monkeypatch, tmp_path):
    db_path = str(tmp_path / "bad_side.db")
    init_database(db_path); _insert_open(db_path, direction="SIDEWAYS")
    monkeypatch.setattr(portfolio, "get_quote", lambda t: {"price": 110, "currency":"USD", "source":"test", "timestamp":"x", "stale":False, "error":None})
    monkeypatch.setattr(portfolio, "get_fx_quote_to_eur", lambda c: {"rate":1.0,"source":"test","timestamp":"x","stale":False,"error":None})
    row = portfolio.load_enriched_trades(db_path).iloc[0]
    assert row["pnl"] is None or __import__('pandas').isna(row["pnl"])
    assert "invalid direction" in row["pricing_error"]


def test_unknown_suffix_does_not_silently_price_as_usd(monkeypatch, tmp_path):
    db_path = str(tmp_path / "unknown_suffix.db")
    init_database(db_path); _insert_open(db_path, ticker="ABC.XYZ")
    monkeypatch.setattr(portfolio, "get_quote", lambda t: {"price": 110, "currency":None, "source":"test", "timestamp":"x", "stale":False, "error":None})
    row = portfolio.load_enriched_trades(db_path).iloc[0]
    assert row["quote_currency"] == "UNKNOWN"
    assert "unsupported exchange suffix" in row["pricing_error"]


def test_compute_stats_marks_open_pnl_partial_when_unpriced():
    import pandas as pd
    df = pd.DataFrame([
        {"status":"CLOSED","pnl":10.0,"entry_date":pd.Timestamp("2026-01-01"),"exit_date":pd.Timestamp("2026-01-02"),"invested":100.0},
        {"status":"OPEN","pnl":5.0,"entry_date":pd.Timestamp("2026-01-03"),"exit_date":pd.NaT,"invested":100.0},
        {"status":"OPEN","pnl":None,"entry_date":pd.Timestamp("2026-01-04"),"exit_date":pd.NaT,"invested":100.0},
    ])
    stats = portfolio.compute_stats(df)
    assert stats["open_pnl"] == 5.0
    assert stats["open_positions_priced"] == 1
    assert stats["open_positions_unpriced"] == 1
    assert stats["open_pnl_complete"] is False
    assert stats["total_pnl_incl_open"] is None


def test_trade_table_distinguishes_reference_from_recorded_instrument_prices():
    import pandas as pd
    from modules.portfolio import format_trades_table
    df = pd.DataFrame([{
        "ticker": "UNH", "direction": "SHORT", "qty": None,
        "entry_price": 0.65, "entry_date": pd.Timestamp("2025-07-24"),
        "exit_price": 0.89, "exit_date": pd.Timestamp("2025-07-29"),
        "pnl": 46.0, "status": "CLOSED", "sector": "Healthcare Tech",
        "notes": "leveraged exposure",
    }])
    out = format_trades_table(df)
    assert "Reference / Underlying" in out.columns
    assert "Exposure" in out.columns
    assert "Recorded Entry" in out.columns
    assert "Recorded Exit" in out.columns
    assert "Broker P&L (€)" in out.columns
    assert out.loc[0, "Entry Date"] == "24/07/25"
    assert out.loc[0, "Exit Date"] == "29/07/25"


def test_short_uses_eur_current_mark_against_eur_broker_entry(monkeypatch, tmp_path):
    db_path = str(tmp_path / "short_usd.db")
    init_database(db_path)
    _insert_open(db_path, ticker="NFLX", direction="SHORT", qty=2.0, entry=100.0)
    monkeypatch.setattr(portfolio, "get_quote", lambda t: {
        "price": 90.0, "currency": "USD", "source": "test", "timestamp": "x", "stale": False, "error": None,
    })
    monkeypatch.setattr(portfolio, "get_fx_quote_to_eur", lambda c: {
        "rate": 0.8, "source": "fx", "timestamp": "x", "stale": False, "error": None,
    })
    row = portfolio.load_enriched_trades(db_path).iloc[0]
    # USD 90 * 0.8 = EUR 72; short entered at EUR 100 => +EUR 28 * 2.
    assert row["current_price"] == 72.0
    assert row["entry_price_eur"] == 100.0
    assert row["pnl"] == 56.0

def test_stats_do_not_publish_currency_mixed_average_roi():
    import pandas as pd
    df = pd.DataFrame([{
        "status": "CLOSED", "pnl": 10.0, "entry_date": pd.Timestamp("2026-01-01"),
        "exit_date": pd.Timestamp("2026-01-02"), "invested": 100.0,
    }])
    assert "avg_roi_pct" not in portfolio.compute_stats(df)


def test_london_quote_is_normalized_then_converted_to_eur_against_eur_entry(monkeypatch, tmp_path):
    db_path = str(tmp_path / "london.db")
    init_database(db_path)
    insert_trade({
        "ticker": "BA.L", "direction": "LONG", "qty": 10.0,
        "entry_price": 20.0, "entry_date": "2026-01-01",  # broker EUR cost basis
        "exit_price": None, "exit_date": None, "pnl": None,
        "invested": 200.0, "status": "OPEN", "sector": "Defence", "notes": "",
    }, db_path)
    # Unified quote layer already returns canonical GBP units for .L.
    monkeypatch.setattr(portfolio, "get_quote", lambda t: {
        "price": 19.0, "currency": "GBP", "source": "test", "timestamp": "x", "stale": False, "error": None,
    })
    monkeypatch.setattr(portfolio, "get_fx_quote_to_eur", lambda c: {
        "rate": 1.15, "source": "fx", "timestamp": "x", "stale": False, "error": None,
    })
    row = portfolio.load_enriched_trades(db_path).iloc[0]
    assert row["entry_price_eur"] == 20.0
    assert row["current_price"] == 21.85
    assert row["pnl"] == 18.5

def test_compute_stats_fail_closed_when_closed_trade_missing_pnl():
    import pandas as pd
    from modules.portfolio import compute_stats

    df = pd.DataFrame([
        {"status":"CLOSED","pnl":10.0,"entry_date":pd.Timestamp("2026-01-01"),"exit_date":pd.Timestamp("2026-01-02"),"invested":100.0},
        {"status":"CLOSED","pnl":None,"entry_date":pd.Timestamp("2026-01-03"),"exit_date":pd.Timestamp("2026-01-04"),"invested":100.0},
        {"status":"OPEN","pnl":5.0,"entry_date":pd.Timestamp("2026-01-05"),"exit_date":pd.NaT,"invested":100.0},
    ])
    stats = compute_stats(df)
    assert stats["closed_pnl_complete"] is False
    assert stats["closed_positions_missing_pnl"] == 1
    assert stats["closed_positions_priced"] == 1
    assert stats["total_pnl"] is None
    assert stats["win_rate"] is None
    assert stats["wins"] is None
    assert stats["losses"] is None
    assert stats["profit_factor"] is None
    assert stats["best_trade"] is None
    assert stats["worst_trade"] is None
    assert stats["total_pnl_incl_open"] is None


def test_compute_stats_complete_closed_record_still_matches_expected():
    import pandas as pd
    from modules.portfolio import compute_stats

    df = pd.DataFrame([
        {"status":"CLOSED","pnl":10.0,"entry_date":pd.Timestamp("2026-01-01"),"exit_date":pd.Timestamp("2026-01-02"),"invested":100.0},
        {"status":"CLOSED","pnl":-2.0,"entry_date":pd.Timestamp("2026-01-03"),"exit_date":pd.Timestamp("2026-01-04"),"invested":100.0},
    ])
    stats = compute_stats(df)
    assert stats["closed_pnl_complete"] is True
    assert stats["total_pnl"] == 8.0
    assert stats["win_rate"] == 50.0
    assert stats["wins"] == 1
    assert stats["losses"] == 1
    assert stats["profit_factor"] == 5.0


def test_personal_open_positions_eur_cost_basis_regression_near_minus_960(monkeypatch, tmp_path):
    """Protect the personal-ledger EUR cost-basis convention against regression."""
    db_path = str(tmp_path / "open_positions.db")
    init_database(db_path)
    for trade in [
        {"ticker":"NFLX","direction":"LONG","qty":50.0,"entry_price":79.15,"invested":3958.50,"sector":"Tech"},
        {"ticker":"AON","direction":"LONG","qty":10.0,"entry_price":313.50,"invested":3136.00,"sector":"Finance"},
    ]:
        insert_trade({
            **trade, "entry_date":"2026-01-01", "exit_price":None, "exit_date":None,
            "pnl":None, "status":"OPEN", "notes":"",
        }, db_path)

    prices = {"NFLX":78.25, "AON":323.09}
    monkeypatch.setattr(portfolio, "get_quote", lambda ticker: {
        "ticker":ticker, "price":prices[ticker], "currency":"USD", "source":"test",
        "timestamp":"x", "stale":False, "error":None,
    })
    monkeypatch.setattr(portfolio, "get_fx_quote_to_eur", lambda currency: {
        "rate":0.858, "source":"test FX", "timestamp":"x", "stale":False, "error":None,
    })
    df = portfolio.load_enriched_trades(db_path)
    assert round(float(df["pnl"].sum()), 2) == -965.47
