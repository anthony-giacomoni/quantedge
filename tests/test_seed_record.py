import pandas as pd

from utils.seed_trades import seed
from utils.db import load_trades


def test_seed_record_matches_documented_track_record(tmp_path):
    db_path = str(tmp_path / "seed.db")
    seed(db_path)
    df = load_trades(db_path)
    closed = df[df["status"] == "CLOSED"].copy()
    assert len(df) == 27
    assert len(closed) == 25
    assert int((closed["pnl"] > 0).sum()) == 24
    assert int((closed["pnl"] < 0).sum()) == 1
    assert round(float(closed["pnl"].sum()), 2) == 2210.61
    closed["entry_date"] = pd.to_datetime(closed["entry_date"])
    closed["exit_date"] = pd.to_datetime(closed["exit_date"])
    assert round(float((closed["exit_date"] - closed["entry_date"]).dt.days.mean()), 1) == 13.0


def test_siemens_energy_records_use_correct_listing_symbol(tmp_path):
    db_path=str(tmp_path/"seed_symbol.db"); seed(db_path); df=load_trades(db_path)
    rows=df[df["notes"].fillna("").str.contains("Siemens Energy",case=False)]
    assert not rows.empty
    assert set(rows["ticker"]) == {"ENR.DE"}
