from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from openpyxl import Workbook


def _write_dca(path: Path, rows):
    wb = Workbook()
    ws = wb.active
    ws.title = "data"
    ws.append([f"c{i}" for i in range(1, 69)])
    for dt, total_inv, total_val in rows:
        row = [None] * 68
        row[0] = dt
        for i in range(1, 68):
            row[i] = 0
        row[5] = total_inv
        row[11] = total_val
        ws.append(row)
    wb.save(path)
    wb.close()


def test_fx_weekend_rejects_arbitrary_old_friday():
    from utils.market_calendar import is_fx_timestamp_stale
    now = "2026-09-06T20:00:00+00:00"
    assert is_fx_timestamp_stale("2026-08-28T20:00:00+00:00", now=now)
    assert not is_fx_timestamp_stale("2026-09-04T20:00:00+00:00", now=now)


def test_dca_out_of_order_sheet_preserves_cashflow(tmp_path):
    from modules.dca import load_excel, calculate_xirr

    path = tmp_path / "unsorted.xlsx"
    _write_dca(path, [
        (datetime(2025, 1, 1), 1000.0, 1000.0),
        (datetime(2025, 3, 1), 2000.0, 2200.0),
        (datetime(2025, 2, 1), 2000.0, 0.0),
    ])
    df = load_excel(str(path))
    assert list(df["date"].dt.strftime("%Y-%m-%d")) == [
        "2025-01-01", "2025-02-01", "2025-03-01"
    ]
    assert pd.isna(df.loc[1, "total_val"])
    assert calculate_xirr(df) == pytest.approx(1.2155, abs=5e-4)


def test_dca_ignores_future_non_increasing_template_rows(tmp_path):
    from modules.dca import load_excel

    path = tmp_path / "templates.xlsx"
    _write_dca(path, [
        (datetime(2025, 1, 1), 1000.0, 1000.0),
        (datetime(2026, 8, 1), 2000.0, 2200.0),
        (datetime(2030, 1, 1), 1500.0, 0.0),
    ])
    df = load_excel(str(path))
    assert len(df) == 2


def test_validator_rejects_oversized_unscanned_text(tmp_path):
    from scripts.validate_public_repo import validate

    folder = tmp_path / "modules"
    folder.mkdir()
    (folder / "huge.py").write_text(
        "A" * (2 * 1024 * 1024 + 10)
        + "\nOPENAI_API_KEY=not-a-placeholder\n"
    )
    assert any(
        "exceeds validator scan limit" in p
        for p in validate(tmp_path)
    )


def test_compute_stats_open_only_dataset():
    from modules.portfolio import compute_stats

    df = pd.DataFrame([
        {
            "status": "OPEN",
            "pnl": 12.5,
            "entry_date": pd.Timestamp("2026-01-01"),
            "exit_date": pd.NaT,
        },
        {
            "status": "OPEN",
            "pnl": None,
            "entry_date": pd.Timestamp("2026-01-02"),
            "exit_date": pd.NaT,
        },
    ])
    stats = compute_stats(df)
    assert stats["closed_trades"] == 0
    assert stats["total_pnl"] is None
    assert stats["open_trades"] == 2
    assert stats["open_positions_priced"] == 1
    assert stats["open_pnl"] == 12.5
    assert stats["open_pnl_complete"] is False


def test_scalar_helpers_do_not_hide_stale_state(monkeypatch):
    from utils import market_data

    monkeypatch.setattr(
        market_data,
        "get_quote",
        lambda _t: {"price": 100.0, "stale": True, "error": None},
    )
    assert market_data.get_current_price("AAPL") is None

    monkeypatch.setattr(
        market_data,
        "get_fx_quote_to_eur",
        lambda _c: {"rate": 0.9, "stale": True, "error": None},
    )
    assert market_data.get_fx_to_eur("USD") is None


def test_malformed_macro_payload_uses_fallback(monkeypatch):
    from utils import event_data

    monkeypatch.setattr(
        event_data,
        "_eodhd_macro_cached",
        lambda *a, **k: ({"unexpected": "garbage"}, None),
    )
    monkeypatch.setattr(
        event_data,
        "_official_macro_events",
        lambda *a, **k: ([{
            "date": "2026-09-10",
            "country": "US",
            "event": "Fallback event",
            "impact": "Major",
            "focus": "Macro",
            "estimate": None,
            "previous": None,
            "actual": None,
            "unit": None,
            "source": "Official",
        }], []),
    )
    out = event_data.get_upcoming_macro(21, ["US"])
    assert out["source"].startswith("Official macro calendars")
    assert out["events"][0]["event"] == "Fallback event"


def test_malformed_earnings_payload_uses_fallback(monkeypatch):
    from utils import event_data

    monkeypatch.setattr(
        event_data,
        "_eodhd_earnings_cached",
        lambda *a, **k: ({"unexpected": "garbage"}, None),
    )
    monkeypatch.setattr(
        event_data,
        "_yfinance_earnings",
        lambda *a, **k: ([{
            "date": "2026-09-15",
            "ticker": "AAPL",
            "before_after_market": None,
            "eps_estimate": None,
            "currency": None,
            "source": "yfinance Earnings Calendar",
        }], []),
    )
    out = event_data.get_upcoming_earnings(["AAPL"], 21)
    assert out["source"] == "yfinance Earnings Calendar"


def test_eodhd_earnings_filters_unrequested_symbols(monkeypatch):
    from utils import event_data

    monkeypatch.setattr(
        event_data,
        "_eodhd_earnings_cached",
        lambda *a, **k: ([{
            "report_date": "2026-09-15",
            "code": "MSFT.US",
            "estimate": 1.0,
        }], None),
    )
    out = event_data.get_upcoming_earnings(["AAPL"], 21)
    assert out["events"] == []


def test_ai_spike_percentile_excludes_current_observation():
    from modules.ai_analysis import _history_metrics

    n = 90
    close = pd.Series(np.linspace(100, 120, n))
    close.iloc[-1] = 108.0

    df = pd.DataFrame({
        "Close": close,
        "High": close + 1,
        "Low": close - 1,
        "Volume": np.linspace(1_000_000, 1_200_000, n),
    })

    out = _history_metrics(df)

    r5 = df["Close"].pct_change(5)
    vol = df["Close"].pct_change().rolling(20).std()
    hist_spikes = (r5 / (vol * np.sqrt(5))).dropna()

    expected = round(
        float(
            (hist_spikes.iloc[:-1] < out["spike_ratio"]).mean()
        ) * 100,
        1,
    )
    assert out["spike_percentile"] == expected
