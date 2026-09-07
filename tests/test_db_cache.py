from utils.db import init_database, save_universe_snapshot, load_universe_snapshot


def test_same_day_universe_snapshot_is_idempotent(tmp_path):
    db=str(tmp_path/"cache.db"); init_database(db)
    rows=[{"ticker":"AAPL.US","name":"Apple","sector":"Tech","industry":"Hardware","market_cap":1,"pe_ratio":1,"revenue":1,"close_price":1}]
    save_universe_snapshot(rows,"2026-09-06",db)
    save_universe_snapshot([{**rows[0],"close_price":2}],"2026-09-06",db)
    df=load_universe_snapshot("2026-09-06",db)
    assert len(df)==1
    assert float(df.iloc[0]["close_price"])==2.0


def test_init_database_migrates_only_siemens_energy_ticker(tmp_path):
    import sqlite3
    from utils.db import init_database, insert_trade
    db_path = str(tmp_path / "migration.db")
    init_database(db_path)
    base = {
        "direction":"LONG","qty":1,"entry_price":10,"entry_date":"2025-01-01",
        "exit_price":11,"exit_date":"2025-01-02","pnl":1,"invested":10,
        "status":"CLOSED","sector":"Energy",
    }
    insert_trade({**base,"ticker":"SIE.DE","notes":"Siemens Energy x1"}, db_path)
    insert_trade({**base,"ticker":"SIE.DE","notes":"Siemens AG deliberate control row"}, db_path)
    init_database(db_path)
    conn=sqlite3.connect(db_path)
    rows=conn.execute("SELECT ticker,notes FROM trades ORDER BY id").fetchall(); conn.close()
    assert rows[0][0] == "ENR.DE"
    assert rows[1][0] == "SIE.DE"


def test_init_database_migrates_estee_lauder_sector(tmp_path):
    from utils.db import init_database, insert_trade, load_trades
    db_path = str(tmp_path / "el_migration.db")
    init_database(db_path)
    insert_trade({
        "ticker":"EL", "direction":"LONG", "qty":None, "entry_price":69.40,
        "entry_date":"2025-06-24", "exit_price":72.40, "exit_date":"2025-07-01",
        "pnl":41.23, "invested":1001.0, "status":"CLOSED",
        "sector":"Healthcare Tech", "notes":"Estee Lauder — rebond sur correction",
    }, db_path)
    init_database(db_path)
    row = load_trades(db_path).iloc[0]
    assert row["sector"] == "Consumer"
