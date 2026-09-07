from pathlib import Path
import sqlite3

import pandas as pd

from modules.prompt_builder import get_template
from utils.market_calendar import is_market_timestamp_stale
from utils.seed_trades import TRADES


def test_market_calendar_rejects_future_session_label_before_open():
    # Tue 8 Sep 2026 before NYSE open: Mon 7 Sep is Labor Day, so Fri 4 Sep is latest expected.
    assert is_market_timestamp_stale("XNYS", "2026-09-08", "2026-09-08T12:00:00Z") is True
    assert is_market_timestamp_stale("XNYS", "2026-09-04", "2026-09-08T12:00:00Z") is False


def test_yfinance_daily_bar_uses_session_label_outside_market_hours(monkeypatch):
    import utils.market_data as md

    idx = pd.DatetimeIndex([
        pd.Timestamp(
            "2026-09-08 00:00:00",
            tz="America/New_York",
        )
    ])
    hist = pd.DataFrame({"Close": [100.0]}, index=idx)

    class FakeTicker:
        def history(self, period):
            assert period == "5d"
            return hist

    monkeypatch.setattr(
        md.yf,
        "Ticker",
        lambda ticker: FakeTicker(),
    )
    monkeypatch.setattr(
        md,
        "is_ticker_market_open",
        lambda ticker: False,
    )

    seen = {}

    def fake_stale(
        calendar,
        timestamp,
        now=None,
        fallback_hours=36.0,
        intraday_max_age_minutes=None,
    ):
        seen["calendar"] = calendar
        seen["timestamp"] = timestamp
        seen["limit"] = intraday_max_age_minutes
        return False

    monkeypatch.setattr(
        md,
        "is_market_timestamp_stale",
        fake_stale,
    )

    quote = md._yfinance_quote("AON")

    assert quote["stale"] is False
    assert quote["timestamp"] == "2026-09-08"
    assert quote["age_hours"] is None
    assert seen == {
        "calendar": "XNYS",
        "timestamp": "2026-09-08",
        "limit": None,
    }


def test_yfinance_daily_bar_fails_closed_while_market_is_open(monkeypatch):
    import utils.market_data as md

    idx = pd.DatetimeIndex([
        pd.Timestamp(
            "2026-09-08 00:00:00",
            tz="America/New_York",
        )
    ])
    hist = pd.DataFrame({"Close": [100.0]}, index=idx)

    class FakeTicker:
        def history(self, period):
            return hist

    monkeypatch.setattr(
        md.yf,
        "Ticker",
        lambda ticker: FakeTicker(),
    )
    monkeypatch.setattr(
        md,
        "is_ticker_market_open",
        lambda ticker: True,
    )
    monkeypatch.setattr(
        md,
        "is_market_timestamp_stale",
        lambda *args, **kwargs: (
            _ for _ in ()
        ).throw(
            AssertionError(
                "daily bar must not be treated as an intraday quote"
            )
        ),
    )

    quote = md._yfinance_quote("AON")

    assert quote["stale"] is True


def test_seed_uses_consistent_sector_taxonomy():
    sectors = {t["sector"] for t in TRADES}
    assert not sectors & {"Energie", "Semiconducteurs", "Défense", "Healthcare Tech", "Autre", "Tech", "Finance"}
    by_ticker = {}
    for t in TRADES:
        by_ticker.setdefault(t["ticker"], set()).add(t["sector"])
    assert by_ticker["EL"] == {"Consumer"}
    assert by_ticker["UNH"] == {"Healthcare"}
    assert by_ticker["NFLX"] == {"Communication Services"}
    assert by_ticker["PYPL"] == {"Financials"}
    assert by_ticker["AON"] == {"Financials"}


def test_db_init_migrates_legacy_sector_labels(tmp_path):
    from utils.db import init_database, get_connection

    db = tmp_path / "q.db"
    init_database(str(db))
    conn = get_connection(str(db))
    conn.execute(
        "INSERT INTO trades (ticker,direction,qty,entry_price,entry_date,pnl,invested,status,sector,notes) VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("UNH", "LONG", 1, 1, "2025-01-01", 1, 1, "CLOSED", "Healthcare Tech", "x"),
    )
    conn.execute(
        "INSERT INTO trades (ticker,direction,qty,entry_price,entry_date,pnl,invested,status,sector,notes) VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("NFLX", "LONG", 1, 1, "2025-01-01", 1, 1, "CLOSED", "Tech", "x"),
    )
    conn.commit(); conn.close()
    init_database(str(db))
    conn = sqlite3.connect(db)
    rows = dict(conn.execute("SELECT ticker, sector FROM trades").fetchall())
    conn.close()
    assert rows["UNH"] == "Healthcare"
    assert rows["NFLX"] == "Communication Services"


def test_historical_reference_ticker_semantics_are_explicit():
    notes = {t["ticker"]: t["notes"] for t in TRADES}
    assert "reference/underlying" in notes["IWM"].lower()
    assert "reference/underlying" in notes["BZ=F"].lower()
    assert "reference/underlying" in notes["XLE"].lower()


def test_post_trade_template_cannot_infer_pattern_or_size_from_one_trade():
    text = get_template("Post-Trade Analysis")["template"]
    assert "single trade is not enough" in text
    assert "pattern recognition and sizing conclusions are unavailable" in text
    assert "size it more aggressively" not in text


def test_due_diligence_and_dcf_templates_fail_closed_for_missing_inputs():
    dd = get_template("Due Diligence — Pre-Entry Check")["template"]
    dcf = get_template("Intrinsic Value vs Market Cap")["template"]
    assert "mark this section unavailable" in dd
    assert "cannot be ranked from the supplied data" in dd
    assert "mark DCF fair value unavailable" in dcf
    assert "Do not manufacture a WACC" in dcf


def test_public_claims_do_not_call_curated_dataset_a_track_record():
    readme = Path("README.md").read_text()
    app = Path("app.py").read_text()
    assert "Strategy-Tagged Track Record" not in app
    assert "reproducible strategy-tagged personal trade dataset" not in readme
    assert "independently auditable track record" in readme
    assert "reference/underlying symbol" in readme


def test_dca_anthropic_privacy_disclosure_present():
    app = Path("app.py").read_text()
    readme = Path("README.md").read_text()
    assert "clicking Run AI Analysis sends the displayed portfolio holdings/amounts" in app
    assert "## AI and privacy" in readme
    assert "Anthropic is called only after an explicit user action" in readme


def test_open_pricing_input_columns_not_duplicated_in_app_source():
    app = Path("app.py").read_text()
    block = app.split('pricing_cols = [', 1)[1].split(']', 1)[0]
    assert block.count('"quote_timestamp"') == 1
    assert block.count('"quote_stale"') == 1
    assert block.count('"fx_to_eur"') == 1
    assert block.count('"fx_source"') == 1


def test_ai_analysis_persists_exact_prompt_and_hash(tmp_path):
    import hashlib
    import sqlite3
    from utils.db import init_database, save_ai_analysis

    db = tmp_path / "ai.db"
    init_database(str(db))
    prompt = "source-labelled prompt\nprice=123"
    save_ai_analysis("NVDA", "answer", "claude-sonnet-5", str(db), prompt=prompt)
    conn = sqlite3.connect(db)
    row = conn.execute("SELECT prompt, prompt_hash FROM ai_analyses").fetchone()
    conn.close()
    assert row[0] == prompt
    assert row[1] == hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def test_ai_analysis_schema_migrates_prompt_columns(tmp_path):
    import sqlite3
    from utils.db import init_database

    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE ai_analyses (id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT NOT NULL, analysis TEXT NOT NULL, model TEXT, created_at TEXT)")
    conn.commit(); conn.close()
    init_database(str(db))
    conn = sqlite3.connect(db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(ai_analyses)")}
    conn.close()
    assert {"prompt", "prompt_hash"} <= cols


def test_all_ai_save_paths_include_prompt_provenance():
    app = Path("app.py").read_text()
    assert 'prompt=full_prompt' in app
    assert 'prompt=prompt, system_prompt=SYSTEM_DATA_INTEGRITY' in app
    assert '_save_analysis(label, answer, prompt_text)' in app
    assert '_save_analysis(ticker_clean, result["analysis"], result["prompt"])' in app

def test_release_builder_rejects_unclassified_python_file(tmp_path):
    from pathlib import Path
    import shutil

    from scripts import build_public_release as builder

    project_root = Path(__file__).resolve().parents[1]
    source = tmp_path / "source"
    destination = tmp_path / "public"

    for rel in builder.PUBLIC_FILES:
        src = project_root / rel
        dst = source / rel
        dst.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        shutil.copy2(src, dst)

    private_candidate = (
        source
        / "modules"
        / "internal_candidate_notes.py"
    )

    private_candidate.write_text(
        'PRIVATE_NOTE = "not for public release"\n'
    )

    try:
        builder.build_public_tree(
            source,
            destination,
        )
    except RuntimeError as exc:
        message = str(exc)
        assert "unclassified public-source candidate" in message
        assert (
            "modules/internal_candidate_notes.py"
            in message
        )
    else:
        raise AssertionError(
            "unclassified Python file was silently released"
        )

    assert not destination.exists()

