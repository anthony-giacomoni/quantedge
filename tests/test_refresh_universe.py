import pytest
import refresh_universe


def test_refresh_universe_normalizes_eodhd_symbol_for_yfinance(monkeypatch, tmp_path):
    captured = {"fund_tickers": [], "saved": None}
    monkeypatch.setattr(refresh_universe, "DB_PATH", str(tmp_path / "u.db"))
    monkeypatch.setattr(refresh_universe, "get_exchange_tickers", lambda exchange: ["AAPL.US"])
    def fake_fund(ticker):
        captured["fund_tickers"].append(ticker)
        return {"market_cap": 1_000_000_000, "name":"Apple", "sector":"Tech", "industry":"Hardware", "pe_ratio":20, "revenue":100}
    monkeypatch.setattr(refresh_universe, "get_fundamentals", fake_fund)
    monkeypatch.setattr(refresh_universe, "get_52w_stats", lambda ticker: {"close_price":100,"high_52w":120,"low_52w":80})
    monkeypatch.setattr(refresh_universe, "save_universe_snapshot", lambda rows, snapshot_date, db_path: captured.update(saved=rows))
    monkeypatch.setattr(refresh_universe, "clear_old_snapshots", lambda **kwargs: None)
    refresh_universe.main(max_tickers=1, exchange="US")
    assert captured["fund_tickers"] == ["AAPL"]
    assert captured["saved"][0]["ticker"] == "AAPL"
