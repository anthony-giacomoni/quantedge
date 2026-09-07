from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
import hashlib
import shutil
import sqlite3

import pandas as pd
import pytest


def _write_dca_rows(path: Path, rows):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "data"
    ws.append(["date"] + [None] * 11)
    for dt, invested, value in rows:
        ws.append([dt, 10, 10, 10, 10, invested, 0, 20, 20, 20, 20, value])
    wb.save(path)
    wb.close()


def test_dca_zero_valuation_row_preserves_contribution_cashflow(tmp_path):
    from modules.dca import load_excel, calculate_xirr

    path = tmp_path / "cashflow_gap.xlsx"
    _write_dca_rows(path, [
        (datetime(2026, 1, 1), 1000.0, 1000.0),
        (datetime(2026, 2, 1), 2000.0, 0.0),
        (datetime(2026, 3, 1), 2000.0, 2200.0),
    ])
    df = load_excel(str(path))
    assert len(df) == 3
    assert pd.isna(df.loc[1, "total_val"])
    xirr = calculate_xirr(df)
    assert xirr is not None
    assert abs(xirr - 1.2154976108532285) < 1e-6


def test_dca_rejects_future_observed_snapshot(tmp_path):
    from modules.dca import load_excel, DCADataError

    path = tmp_path / "future.xlsx"
    _write_dca_rows(path, [(datetime(2099, 1, 1), 1000.0, 1100.0)])
    with pytest.raises(DCADataError, match="Future DCA observation"):
        load_excel(str(path))


def test_history_from_2020_is_unavailable_not_scored(monkeypatch):
    import utils.market_data as md

    idx = pd.to_datetime(["2020-01-02", "2020-01-03"])
    hist = pd.DataFrame({
        "Open": [10, 11], "High": [11, 12], "Low": [9, 10],
        "Close": [10.5, 11.5], "Volume": [100, 120],
    }, index=idx)
    monkeypatch.setattr(md, "EODHD_KEY", None)
    monkeypatch.setattr(md, "_yf_history", lambda ticker, period: hist)
    meta = md.get_price_history_with_meta("AAPL", years=5)
    assert meta["data"] is None
    assert meta["history_stale"] is True
    assert "stale history" in meta["error"]
    assert md.get_price_history_df("AAPL", years=5) is None


def test_impossible_ohlc_rows_are_rejected():
    import utils.market_data as md

    bad = pd.DataFrame({
        "Open": [100.0], "High": [90.0], "Low": [95.0],
        "Close": [100.0], "Volume": [1000.0],
    })
    assert md._sanitize_history_df("AAPL", bad) is None


def test_score_is_bounded_and_negative_support_distance_never_rewards():
    from modules.screener import compute_score

    scored = compute_score({
        "drawdown_pct": -0.38,
        "ret_5d": -0.05,
        "short_pct": 0.15,
        "rel_volume": 10,
        "dist_to_support": -1,
        "spike_ratio": -2,
        "spike_percentile": 1,
    })
    assert scored["score_support"] == 0
    assert 0 <= scored["score_total"] <= 100
    for key, value in scored.items():
        if key.startswith("score_"):
            assert 0 <= value <= 100


def test_fx_friday_mark_becomes_stale_after_sunday_reopen():
    from utils.market_calendar import is_fx_timestamp_stale

    friday_close = "2026-09-04T21:00:00Z"  # 17:00 New York (EDT)
    assert is_fx_timestamp_stale(friday_close, "2026-09-06T20:30:00Z") is False  # before 17:00 NY reopen
    assert is_fx_timestamp_stale(friday_close, "2026-09-06T22:30:00Z") is True   # after reopen


def test_stale_revenue_fx_cannot_decide_equity_eligibility(monkeypatch):
    import modules.screener as sc

    n = 40
    hist = pd.DataFrame({
        "High": [120.0] * n,
        "Low": [70.0] * n,
        "Close": [100.0] * (n - 6) + [82, 81, 80, 79, 78, 77],
        "Volume": [500_000.0] * n,
    })
    monkeypatch.setattr(sc, "get_price_history_df", lambda ticker, years=5: hist)
    monkeypatch.setattr(sc, "get_ticker_info", lambda ticker: {
        "name": ticker, "short_pct_float": 0.1,
        "revenue": 150_000_000, "instrument_type": "EQUITY",
        "financial_currency": "USD", "currency": "USD",
        "fundamentals_available": True, "fundamentals_error": None,
        "fundamentals_source": "yfinance",
    })
    monkeypatch.setattr(sc, "_reporting_currency_fx_to_eur", lambda currency: {
        "rate": 0.8, "source": "stale FX", "stale": True, "error": None,
    })
    data = sc.fetch_ticker_data("TEST")
    assert data["revenue_eur"] is None
    passes, failed = sc.apply_filters(data)
    assert passes is False
    assert any("Revenue FX unavailable" in x for x in failed)


def test_recent_news_rejects_old_unix_timestamp(monkeypatch):
    import utils.event_data as ev

    ev.clear_event_data_caches()
    monkeypatch.setattr(ev, "_eodhd_news_cached", lambda *args, **kwargs: (None, "403"))
    monkeypatch.setattr(ev, "_yf_news_cached", lambda *args, **kwargs: ([{
        "title": "Very old story",
        "providerPublishTime": 1577880000,  # Jan 2020
        "link": "https://example.com/old",
    }], None, True))
    out = ev.get_recent_news(["AAPL"], days_back=5, per_symbol=2)
    assert out["articles"] == []


def test_malformed_eodhd_news_dates_trigger_yfinance_fallback(monkeypatch):
    import utils.event_data as ev

    ev.clear_event_data_caches()
    monkeypatch.setattr(ev, "_eodhd_news_cached", lambda *args, **kwargs: ([{
        "title": "Old provider row", "date": "2020-01-01"
    }], None))
    today = datetime.now().date().isoformat()
    monkeypatch.setattr(ev, "_yfinance_news", lambda *args, **kwargs: ([{
        "ticker": "AAPL", "date": today, "title": "Fallback story",
        "link": None, "sentiment": None, "source": "yfinance News",
    }], None))
    out = ev.get_recent_news(["AAPL"], days_back=5, per_symbol=2)
    assert [x["title"] for x in out["articles"]] == ["Fallback story"]
    assert any("no valid recent timestamps" in w for w in out["warnings"])


def test_zero_of_n_open_positions_is_na_not_zero():
    from modules.portfolio import compute_stats

    df = pd.DataFrame([
        {"status": "CLOSED", "pnl": 10.0, "entry_date": pd.Timestamp("2026-01-01"), "exit_date": pd.Timestamp("2026-01-02")},
        {"status": "OPEN", "pnl": None, "entry_date": pd.Timestamp("2026-02-01"), "exit_date": pd.NaT},
        {"status": "OPEN", "pnl": None, "entry_date": pd.Timestamp("2026-02-02"), "exit_date": pd.NaT},
    ])
    stats = compute_stats(df)
    assert stats["open_positions_priced"] == 0
    assert stats["open_trades"] == 2
    assert stats["open_pnl"] is None
    assert stats["open_pnl_complete"] is False


def test_wrapper_open_position_is_not_marked_from_reference_ticker(monkeypatch, tmp_path):
    from utils.db import init_database, insert_trade
    import modules.portfolio as portfolio

    db = tmp_path / "q.db"
    init_database(str(db))
    insert_trade({
        "ticker": "UNH", "direction": "SHORT", "qty": 1,
        "entry_price": 1.0, "entry_date": "2026-01-01",
        "exit_price": None, "exit_date": None, "pnl": None,
        "invested": 1.0, "status": "OPEN", "sector": "Healthcare",
        "notes": "wrapper", "instrument_type": "WRAPPER", "marking_ticker": None,
    }, str(db))
    monkeypatch.setattr(portfolio, "get_quote", lambda ticker: (_ for _ in ()).throw(AssertionError("must not mark underlying")))
    out = portfolio.load_enriched_trades(str(db))
    assert pd.isna(out.iloc[0]["pnl"])
    assert "cannot be live-marked" in out.iloc[0]["pricing_error"]


def test_provider_symbol_dialects_canonicalize_consistently():
    import utils.market_data as md

    assert md.canonical_listing_ticker("STO.AU") == "STO.AX"
    assert md.ticker_currency("STO.AU") == "AUD"
    assert md.ticker_exchange_calendar("STO.AU") == "XASX"
    assert md.canonical_listing_ticker("ENR.XETRA") == "ENR.DE"
    assert md.ticker_currency("ENR.XETRA") == "EUR"
    assert md.canonical_listing_ticker("BA.LSE") == "BA.L"
    assert md.ticker_currency("BA.LSE") == "GBP"


def test_validator_rejects_all_reported_bypass_patterns(tmp_path):
    from scripts.validate_public_repo import validate

    (tmp_path / "nested" / "data").mkdir(parents=True)
    (tmp_path / "nested" / "data" / "private.csv").write_text("x")
    (tmp_path / ".pytest_cache").mkdir()
    (tmp_path / ".pytest_cache" / ".env").write_text("OPENAI_" + "API_KEY=REAL_SECRET_123456")
    (tmp_path / "htmlcov").mkdir()
    (tmp_path / "htmlcov" / "private.key").write_text("-----BEGIN " + "PRIVATE KEY-----")
    (tmp_path / "leak.txt").write_text("OPENAI_" + "API_KEY=REAL_SECRET_123456\n" + "person" + "@" + "gmail.com\n")
    (tmp_path / "tmp").mkdir()
    (tmp_path / "tmp" / ".coverage").write_text("machine path")
    problems = validate(tmp_path)
    joined = "\n".join(problems)
    assert "nested/data" in joined
    assert ".pytest_cache" in joined
    assert "htmlcov" in joined
    assert "non-placeholder OPENAI_API_KEY" in joined
    assert "potential personal email" in joined
    assert ".coverage" in joined


def test_public_release_builder_uses_allowlist(tmp_path):
    from scripts.build_public_release import build_public_tree
    from scripts.validate_public_repo import validate

    source = tmp_path / "source"
    shutil.copytree(Path.cwd(), source, ignore=shutil.ignore_patterns(".git", ".pytest_cache", "__pycache__"))
    (source / ".env").write_text("ANTHROPIC_" + "API_KEY=REAL_SECRET")
    (source / "data").mkdir(exist_ok=True)
    (source / "data" / "private.db").write_bytes(b"private")
    dest = tmp_path / "public"
    build_public_tree(source, dest)
    assert not (dest / ".env").exists()
    assert not (dest / "data").exists()
    assert validate(dest) == []


def test_sector_chart_includes_negative_net_pnl():
    from modules.portfolio import build_sector_pie

    df = pd.DataFrame([
        {"status": "CLOSED", "pnl": 100.0, "sector": "Energy"},
        {"status": "CLOSED", "pnl": -40.0, "sector": "Healthcare"},
    ])
    fig = build_sector_pie(df)
    xs = list(fig.data[0].x)
    assert any(x < 0 for x in xs)
    assert any(x > 0 for x in xs)
    assert fig.layout.title.text == "Net Realised P&L by Sector"


def test_ai_persistence_includes_system_prompt_hash_and_parameters(tmp_path):
    from utils.db import init_database, save_ai_analysis

    db = tmp_path / "ai.db"
    init_database(str(db))
    user_prompt = "input snapshot"
    system_prompt = "integrity rules"
    save_ai_analysis(
        "AAPL", "answer", "claude-sonnet-5", str(db),
        prompt=user_prompt, system_prompt=system_prompt, max_tokens=2000,
    )
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT prompt_hash, system_prompt, system_prompt_hash, max_tokens FROM ai_analyses"
    ).fetchone()
    conn.close()
    assert row[0] == hashlib.sha256(user_prompt.encode()).hexdigest()
    assert row[1] == system_prompt
    assert row[2] == hashlib.sha256(system_prompt.encode()).hexdigest()
    assert row[3] == 2000


def test_news_ai_uses_exact_displayed_headline_slice():
    app = Path("app.py").read_text()
    assert "for article in recent_news[:12]" in app
    assert 'articles=recent_news[:12]' in app


def test_wrapper_reference_rows_are_explicit_in_seed():
    from utils.seed_trades import TRADES

    wrappers = [t for t in TRADES if t.get("instrument_type") == "WRAPPER"]
    assert {(t["ticker"], t["entry_date"]) for t in wrappers} == {
        ("IWM", "2025-06-19"),
        ("UNH", "2025-07-24"),
        ("BZ=F", "2025-07-29"),
        ("XLE", "2026-02-25"),
    }
    assert all(t.get("marking_ticker") is None for t in wrappers)


def test_validator_rejects_dotenv_variants_and_env_directory(tmp_path):
    from scripts.validate_public_repo import validate
    (tmp_path / ".env.local").write_text("X=placeholder")
    (tmp_path / "env").mkdir()
    (tmp_path / "env" / "nested.txt").write_text("placeholder")
    problems = validate(tmp_path)
    assert any(".env.local" in p for p in problems)
    assert any("env" in p and "directory" in p for p in problems)


def test_compatibility_pnl_refuses_wrapper_before_provider_call(monkeypatch):
    from utils import market_data
    called = {"quote": 0}
    def fake_quote(_):
        called["quote"] += 1
        return {"price": 100.0, "currency": "USD"}
    monkeypatch.setattr(market_data, "get_quote", fake_quote)
    assert market_data.compute_open_pnl("UNH", 0.65, 10, direction="SHORT", instrument_type="WRAPPER") is None
    assert called["quote"] == 0


def test_bls_ics_timezone_parameter_is_preserved(monkeypatch):
    from utils import event_data
    ics = """BEGIN:VCALENDAR\nBEGIN:VEVENT\nDTSTART;TZID=America/New_York:20260911T083000\nSUMMARY:Consumer Price Index\nEND:VEVENT\nEND:VCALENDAR\n"""
    monkeypatch.setattr(event_data, "_http_text", lambda _url: (ics, None))
    rows, errors = event_data._bls_events(date(2026, 9, 7), date(2026, 9, 30))
    assert not errors
    assert rows[0]["provider_datetime"].endswith("-04:00")


def test_fomc_fallback_can_cross_year_boundary(monkeypatch):
    from utils import event_data
    html = """2026 FOMC Meetings December 15-16 Statement: 2027 FOMC Meetings January 26-27 Statement:"""
    monkeypatch.setattr(event_data, "_http_text", lambda _url: (html, None))
    rows, _ = event_data._fomc_events(date(2026, 12, 20), date(2027, 2, 1))
    assert [r["date"] for r in rows] == ["2027-01-27"]


def test_stats_exposes_duration_denominator():
    from modules import portfolio
    df = pd.DataFrame([
        {"status":"CLOSED","pnl":10.0,"entry_date":pd.Timestamp("2026-01-01"),"exit_date":pd.Timestamp("2026-01-03")},
        {"status":"CLOSED","pnl":5.0,"entry_date":pd.NaT,"exit_date":pd.NaT},
    ])
    stats = portfolio.compute_stats(df)
    assert stats["duration_samples"] == 1

def test_incomplete_ohlc_history_fails_closed_instead_of_skipping_session():
    import pandas as pd
    import utils.market_data as md

    n = 80
    dates = pd.date_range(
        "2026-01-01",
        periods=n,
        freq="B",
    )

    df = pd.DataFrame(
        {
            "Open": [99.0] * n,
            "High": [101.0] * n,
            "Low": [95.0] * n,
            "Close": [100.0] * n,
            "Volume": [1_000_000.0] * n,
        },
        index=dates,
    )

    # Exact hostile-audit case: latest session has a usable Close but
    # an incomplete High. This must not remain an economically usable
    # market observation.
    df.loc[df.index[-1], "High"] = float("nan")

    assert md._sanitize_history_df("AAPL", df) is None

def test_screener_rejects_incomplete_high_history_for_5y_high(monkeypatch):
    import pandas as pd
    from modules import screener

    n = 80
    dates = pd.date_range(
        "2026-01-01",
        periods=n,
        freq="B",
    )

    hist = pd.DataFrame(
        {
            "Open": [99.0] * n,
            "High": [101.0] * n,
            "Low": [95.0] * n,
            "Close": [100.0] * n,
            "Volume": [1_000_000.0] * n,
        },
        index=dates,
    )

    # Historical, not latest: Close-based metrics remain representable,
    # but the claim "5Y High" is not complete.
    hist.loc[hist.index[10], "High"] = float("nan")

    monkeypatch.setattr(
        screener,
        "get_price_history_df",
        lambda ticker, years=5: hist,
    )

    assert screener.fetch_ticker_data("AAPL") is None

def test_fomc_parser_does_not_relabel_historical_meetings_as_current_year(
    monkeypatch,
):
    from datetime import date
    from utils import event_data

    # Mirrors the important ordering property of the real Fed page:
    # current year, several historical years, then future year.
    html = """
    2026 FOMC Meetings
    January 27-28 Statement:
    Minutes: Released February 18, 2026
    March 17-18 Statement:
    June 16-17 Statement:
    July 28-29 Statement:
    September 15-16*
    October 27-28
    December 8-9*

    2025 FOMC Meetings
    September 16-17* Statement:

    2024 FOMC Meetings
    September 17-18* Statement:

    2023 FOMC Meetings
    September 19-20* Statement:

    2022 FOMC Meetings
    September 20-21* Statement:

    2021 FOMC Meetings
    September 21-22* Statement:

    2027 FOMC Meetings
    January 26-27
    """

    monkeypatch.setattr(
        event_data,
        "_http_text",
        lambda url: (html, None),
    )

    rows, warnings = event_data._fomc_events(
        date(2026, 9, 7),
        date(2026, 9, 28),
    )

    assert warnings == []

    assert [
        row["date"]
        for row in rows
    ] == [
        "2026-09-16",
    ]

    assert {
        row["event"]
        for row in rows
    } == {
        "FOMC Rate Decision / Press Conference",
    }

