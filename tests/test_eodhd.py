from utils import eodhd


def test_eodhd_quote_without_timestamp_is_conservatively_stale(monkeypatch):
    monkeypatch.setattr(eodhd, "_get", lambda endpoint, params=None: {"close":100.0,"timestamp":None} if endpoint.startswith("real-time/") else None)
    q=eodhd.get_quote("AAPL")
    assert q["price"] == 100.0
    assert q["timestamp"] is None
    assert q["stale"] is True
    assert "timestamp unavailable" in q["error"]


def test_eodhd_quote_normalizes_unix_timestamp(monkeypatch):
    from datetime import datetime, timezone
    # Friday 4 Sep is the latest NYSE session before Labor Day Monday 7 Sep 2026.
    ts=int(datetime(2026,9,4,20,0,tzinfo=timezone.utc).timestamp())
    monkeypatch.setattr(eodhd, "_get", lambda endpoint, params=None: {"close":100.0,"timestamp":ts})
    q=eodhd.get_quote("AAPL")
    assert isinstance(q["timestamp"],str) and "T" in q["timestamp"]
    assert q["stale"] is False


def test_eodhd_invalid_realtime_price_uses_eod_fallback(monkeypatch):
    def fake(endpoint, params=None):
        if endpoint.startswith("real-time/"): return {"close":float('nan'),"timestamp":None}
        if endpoint.startswith("eod/"): return [{"close":99.0,"date":"2026-09-05"}]
    monkeypatch.setattr(eodhd,"_get",fake)
    q=eodhd.get_quote("AAPL")
    assert q["price"] == 99.0
    assert q["source"] == "EODHD EOD fallback"
    assert q["stale"] is True


def test_eodhd_ticker_conversion_for_supported_exchanges():
    assert eodhd._ticker("ENR.DE") == "ENR.XETRA"
    assert eodhd._ticker("STO.AX") == "STO.AU"
    assert eodhd._ticker("AAPL") == "AAPL.US"


def test_eodhd_delayed_failure_reason_survives_successful_eod_fallback(monkeypatch):
    def fake(endpoint, params=None):
        if endpoint.startswith("real-time/"):
            eodhd.LAST_ERROR = "simulated delayed endpoint outage"
            return None
        eodhd.LAST_ERROR = None
        return [{"close": 99.0, "date": "2026-09-05"}]
    monkeypatch.setattr(eodhd, "_get", fake)
    q = eodhd.get_quote("AAPL")
    assert q["price"] == 99.0
    assert q["source"] == "EODHD EOD fallback"
    assert q["fallback_reason"] == "simulated delayed endpoint outage"


def test_eodhd_nan_eod_price_is_rejected(monkeypatch):
    def fake(endpoint, params=None):
        if endpoint.startswith("real-time/"):
            return {"close": float("nan"), "timestamp": None}
        return [{"close": float("nan"), "date": "2026-09-05"}]
    monkeypatch.setattr(eodhd, "_get", fake)
    q = eodhd.get_quote("AAPL")
    assert q["price"] is None
    assert q["stale"] is True


def test_eodhd_nan_fx_rate_is_rejected(monkeypatch):
    def fake(endpoint, params=None):
        if endpoint.startswith("real-time/"):
            return {"close": float("nan"), "timestamp": None}
        return [{"close": float("nan"), "date": "2026-09-05"}]
    monkeypatch.setattr(eodhd, "_get", fake)
    q = eodhd.get_usd_eur_quote()
    assert q["rate"] is None
    assert q["stale"] is True


def test_eodhd_provider_suffix_mapping_for_all_supported_listing_styles():
    expected = {
        "AIR.PA": "AIR.PA", "ENR.DE": "ENR.XETRA", "ENI.MI": "ENI.MI",
        "ASML.AS": "ASML.AS", "REP.MC": "REP.MC", "BA.L": "BA.LSE",
        "0700.HK": "0700.HK", "2330.TW": "2330.TW", "STO.AX": "STO.AU",
        "SHOP.TO": "SHOP.TO", "NESN.SW": "NESN.SW", "AAPL": "AAPL.US",
    }
    for src, dst in expected.items():
        assert eodhd._ticker(src) == dst


def test_eod_history_drops_nonfinite_nonpositive_and_malformed_rows(monkeypatch):
    rows = [
        {"date":"2026-01-01","close":100,"high":101,"low":99,"volume":10},
        {"date":"2026-01-02","close":float("nan"),"high":102,"low":98,"volume":10},
        {"date":"2026-01-03","close":0,"high":103,"low":97,"volume":10},
        "bad-row",
        {"date":"2026-01-04","close":105,"high":float("inf"),"low":104,"volume":-1},
    ]
    monkeypatch.setattr(eodhd, "_get", lambda endpoint, params=None: rows)
    out = eodhd.get_eod_history("AAPL")
    assert len(out) == 2
    assert [r["close"] for r in out] == [100.0, 105.0]
    assert out[-1]["high"] is None
    assert out[-1]["volume"] is None


def test_52w_stats_fail_closed_when_high_low_are_invalid(monkeypatch):
    rows = [{"date":"2026-01-01","close":100,"high":float("nan"),"low":float("nan") }]
    monkeypatch.setattr(eodhd, "_get", lambda endpoint, params=None: rows)
    assert eodhd.get_52w_stats("AAPL") is None


def test_calendar_earnings_maps_yahoo_symbols_to_eodhd(monkeypatch):
    from utils import eodhd
    seen = {}
    def fake_get(endpoint, params=None):
        seen["endpoint"] = endpoint
        seen["params"] = params
        return []
    monkeypatch.setattr(eodhd, "_get", fake_get)
    eodhd.get_earnings_calendar("2026-09-01", "2026-09-30", ["AAPL", "ENR.DE", "STO.AX"])
    assert seen["endpoint"] == "calendar/earnings"
    assert seen["params"]["symbols"] == "AAPL.US,ENR.XETRA,STO.AU"


def test_economic_events_wrapper_never_invents_dates(monkeypatch):
    from utils import eodhd
    seen = {}
    monkeypatch.setattr(eodhd, "_get", lambda endpoint, params=None: seen.update(endpoint=endpoint, params=params) or [])
    eodhd.get_economic_events("2026-09-07", "2026-09-28", limit=5000)
    assert seen["endpoint"] == "economic-events"
    assert seen["params"]["from"] == "2026-09-07"
    assert seen["params"]["to"] == "2026-09-28"
    assert seen["params"]["limit"] == 1000


def test_eodhd_403_message_is_endpoint_generic(monkeypatch):
    import io
    import urllib.error
    err = urllib.error.HTTPError("https://x", 403, "Forbidden", hdrs=None, fp=io.BytesIO(b"Forbidden"))
    monkeypatch.setattr(eodhd.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(err))
    monkeypatch.setattr(eodhd, "API_KEY", "x")
    assert eodhd._get("economic-events") is None
    assert "entitlement EODHD" in eodhd.LAST_ERROR
    assert "WebSocket" not in eodhd.LAST_ERROR

def test_eodhd_does_not_append_us_suffix_to_yahoo_future_or_fx_symbols():
    from utils import eodhd

    assert eodhd._ticker("BZ=F") == "BZ=F"
    assert eodhd._ticker("EURUSD=X") == "EURUSD=X"

    # Existing US-equity convention remains intact.
    assert eodhd._ticker("AAPL") == "AAPL.US"

