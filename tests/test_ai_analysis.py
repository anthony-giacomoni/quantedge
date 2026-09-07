import sys

import pytest

from modules.ai_analysis import build_analysis_prompt, call_claude_api, ClaudeAPIError


def test_prompt_labels_fundamentals_source_and_forbids_invented_catalyst():
    prompt = build_analysis_prompt("TEST", {
        "current_price": 100,
        "high_5y": 120,
        "drawdown_pct": -0.1667,
        "ret_5d": 0.01,
        "short_pct": 0.1,
        "rel_volume": None,
        "spike_ratio": None,
        "name": "Test Co",
        "sector": "Tech",
        "industry": "Software",
        "quote_source": "EODHD delayed quote",
        "fundamentals": {"_source": "yfinance", "market_cap": 1_000_000_000},
    })
    assert "PROVIDER-SOURCED FUNDAMENTALS (source: yfinance)" in prompt
    assert "Do NOT invent a dated catalyst" in prompt
    assert "source: EODHD)" not in prompt.split("PROVIDER-SOURCED FUNDAMENTALS", 1)[1][:80]


def test_claude_failure_raises_structured_error(monkeypatch):
    class BrokenAnthropicModule:
        class Anthropic:
            def __init__(self, api_key):
                raise RuntimeError("simulated outage")

    monkeypatch.setitem(sys.modules, "anthropic", BrokenAnthropicModule)
    with pytest.raises(ClaudeAPIError, match="simulated outage"):
        call_claude_api("hello", "fake-key")


def test_prompt_builder_templates_have_data_integrity_guardrail():
    from modules.prompt_builder import PROMPT_TEMPLATES, fill_template

    for item in PROMPT_TEMPLATES.values():
        prompt = fill_template(item["template"], {})
        assert "does not provide a general-purpose live market/news feed" in prompt
        assert "Do not invent current prices" in prompt


def test_prompt_keeps_quote_history_and_fundamental_provenance_separate():
    prompt = build_analysis_prompt("TEST", {
        "current_price":100,"quote_source":"EODHD delayed quote","quote_timestamp":"2026-09-06T12:00:00+00:00","quote_stale":False,
        "history_source":"yfinance","history_as_of":"2026-09-05T00:00:00+00:00",
        "high_5y":120,"drawdown_pct":-0.1667,"ret_5d":0.0,"short_pct":0.1,"rel_volume":1.0,"spike_ratio":0.0,
        "name":"Test","sector":"Tech","industry":"Software",
        "fundamentals":{"_source":"yfinance","_available":True,"market_cap":1},
    })
    assert "Source          : EODHD delayed quote" in prompt
    assert "PRICE HISTORY METRICS" in prompt and "Source          : yfinance" in prompt
    assert "PROVIDER-SOURCED FUNDAMENTALS (source: yfinance)" in prompt
    assert "A source label applies only to the section" in prompt


def test_analyze_ticker_uses_single_history_snapshot(monkeypatch):
    import pandas as pd
    from modules import ai_analysis
    calls = {"history":0}
    hist = pd.DataFrame({"Close":[100,99,98,97,96,95]+[95]*15,"High":[120]*21,"Volume":[100]*21})
    monkeypatch.setattr(ai_analysis,"get_quote",lambda t:{"price":95,"source":"q","timestamp":"x","stale":False,"error":None})
    def fake_history(t, years=5):
        calls["history"] += 1
        return {"data":hist,"source":"history-provider","as_of":"x","error":None}
    monkeypatch.setattr(ai_analysis,"get_price_history_with_meta",fake_history)
    monkeypatch.setattr(ai_analysis,"get_fundamentals",lambda t:{"_available":True,"_source":"yfinance","name":"X","short_pct":0.1})
    monkeypatch.setattr(ai_analysis,"call_claude_api",lambda prompt,key:"ok")
    result=ai_analysis.analyze_ticker("X","key")
    assert calls["history"] == 1
    assert result["market_data"]["history_source"] == "history-provider"


def test_call_claude_uses_config_and_system_guardrail(monkeypatch):
    import sys, types
    from modules import ai_analysis
    captured={}
    class Messages:
        def create(self, **kwargs):
            captured.update(kwargs)
            return types.SimpleNamespace(content=[types.SimpleNamespace(text="answer")])
    class Client:
        def __init__(self, api_key): self.messages=Messages()
    fake=types.SimpleNamespace(Anthropic=Client)
    monkeypatch.setitem(sys.modules,"anthropic",fake)
    assert ai_analysis.call_claude_api("hello","key") == "answer"
    assert captured["model"] == ai_analysis.CLAUDE_MODEL
    assert captured["max_tokens"] == ai_analysis.CLAUDE_MAX_TOKENS
    assert "Do not invent current prices" in captured["system"]


def test_ai_prompt_labels_quote_currency_and_unit_normalization():
    prompt = build_analysis_prompt("BP.L", {
        "current_price":5.425,"quote_currency":"GBP","quote_unit_normalization":"GBp→GBP /100",
        "quote_source":"yfinance","quote_timestamp":"2026-09-06T12:00:00+00:00","quote_stale":False,
        "history_source":"yfinance","history_as_of":"2026-09-05",
        "high_5y":6.0,"drawdown_pct":-0.0958,"ret_5d":0.01,"short_pct":None,"rel_volume":1.2,"spike_ratio":0.2,
        "name":"BP","sector":"Energy","industry":"Integrated Oil",
        "fundamentals":{"_source":"yfinance","_available":True},
    })
    assert "Latest price    : 5.425 GBP" in prompt
    assert "GBp→GBP /100" in prompt


def test_prompt_builder_never_leaves_unresolved_placeholders():
    from modules.prompt_builder import PROMPT_TEMPLATES, fill_template
    for item in PROMPT_TEMPLATES.values():
        prompt = fill_template(item["template"], {})
        import re
        assert re.search(r"\{[A-Za-z_][A-Za-z0-9_]*\}", prompt) is None


def test_current_data_templates_fail_closed_when_inputs_missing():
    from modules.prompt_builder import PROMPT_TEMPLATES, fill_template
    prompt = fill_template(PROMPT_TEMPLATES["Trade Setup — Opportunity Scan"]["template"], {})
    assert "do not invent tickers or current market facts" in prompt
    assert "missing-data checklist" in prompt


def test_collect_market_snapshot_uses_one_call_per_data_family(monkeypatch):
    import pandas as pd
    from modules import ai_analysis
    calls = {"quote": 0, "history": 0, "fund": 0}
    hist = pd.DataFrame({"Close": [100.0] * 21, "High": [110.0] * 21, "Volume": [100.0] * 21})
    def quote(t): calls["quote"] += 1; return {"price": 100, "source": "q", "currency": "USD"}
    def history(t, years=5): calls["history"] += 1; return {"data": hist, "source": "h", "as_of": "x"}
    def fund(t): calls["fund"] += 1; return {"_available": True, "_source": "yfinance", "name": "X"}
    monkeypatch.setattr(ai_analysis, "get_quote", quote)
    monkeypatch.setattr(ai_analysis, "get_price_history_with_meta", history)
    monkeypatch.setattr(ai_analysis, "get_fundamentals", fund)
    snap = ai_analysis.collect_market_snapshot(" x ")
    assert snap["name"] == "X"
    assert calls == {"quote": 1, "history": 1, "fund": 1}
