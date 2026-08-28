# ============================================================
#  QuantEdge — Module Analyse IA (Claude API)
#  Compatible Python 3.8
# ============================================================

from typing import Optional, Dict
import sys, os
from datetime import datetime
import pytz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.market_data import get_current_price, get_drawdown_from_ath, get_5d_return, get_ticker_info, get_fundamentals


def build_analysis_prompt(ticker: str, market_data: Dict, user_context: str = "") -> str:
    """
    Construit le prompt optimisé pour Claude.
    Injecte les vraies données de marché — Claude fait la thèse, pas la recherche.
    """
    current   = market_data.get("current_price", "N/A")
    ath       = market_data.get("ath", "N/A")
    drawdown  = market_data.get("drawdown_pct")
    ret_5d    = market_data.get("ret_5d")
    short_pct = market_data.get("short_pct")
    vol_rel   = market_data.get("rel_volume")
    spike     = market_data.get("spike_ratio")
    name      = market_data.get("name", ticker)
    sector    = market_data.get("sector", "N/A")
    industry  = market_data.get("industry", "N/A")

    dd_str    = f"{drawdown*100:.1f}%" if drawdown else "N/A"
    r5_str    = f"{ret_5d*100:+.1f}%" if ret_5d is not None else "N/A"
    si_str    = f"{short_pct*100:.1f}%" if short_pct else "N/A"
    vol_str   = f"{vol_rel:.1f}x" if vol_rel else "N/A"
    spike_str = f"{spike:+.2f}" if spike is not None else "N/A"

    # ── Fondamentaux réels EODHD (pas d'estimation du modèle) ──
    def _fmt(val, suffix=""):
        return f"{val}{suffix}" if val is not None else "N/A"

    fund = market_data.get("fundamentals", {}) or {}
    market_cap    = _fmt(fund.get("market_cap"))
    pe_ratio      = _fmt(fund.get("pe_ratio"))
    forward_pe    = _fmt(fund.get("forward_pe"))
    ev_ebitda     = _fmt(fund.get("ev_ebitda"))
    price_book    = _fmt(fund.get("price_to_book"))
    price_sales   = _fmt(fund.get("price_to_sales"))
    revenue       = _fmt(fund.get("revenue"))
    revenue_gr    = _fmt(fund.get("revenue_growth"))
    profit_margin = _fmt(fund.get("profit_margin"))
    roe           = _fmt(fund.get("return_on_equity"))

    now = datetime.now(pytz.timezone("Europe/Paris"))
    prompt = f"""Date & time: {now.strftime("%A %d %B %Y — %H:%M")} Paris time.

You are a senior equity analyst at a top-tier hedge fund covering energy, semiconductors, defence and healthcare.

═══ VERIFIED MARKET DATA (source: EODHD) ═══
Asset          : {name} ({ticker})
Sector         : {sector} / {industry}
Current price  : {current}
All-time high  : {ath}
ATH drawdown   : {dd_str}
5-day return   : {r5_str}
Short interest : {si_str}
Relative volume: {vol_str} (vs 20-day avg)
Spike ratio    : {spike_str} (5d return / 20d volatility)

═══ VERIFIED FUNDAMENTALS (source: EODHD) ═══
Market cap       : {market_cap}
P/E (trailing)   : {pe_ratio}
P/E (forward)    : {forward_pe}
EV/EBITDA        : {ev_ebitda}
Price/Book       : {price_book}
Price/Sales      : {price_sales}
Revenue (TTM)    : {revenue}
Revenue growth   : {revenue_gr}
Profit margin    : {profit_margin}
Return on equity : {roe}
{f"Additional context: {user_context}" if user_context else ""}

⚠️ DATA INTEGRITY RULE: only use the verified figures above for anything you present as a
fact or a metric. Where you compare against a sector median or peer group, clearly label
that comparison as your own estimate (you were not given verified peer data), never as
verified. Any field marked N/A above is genuinely unavailable — say so rather than
inferring a number.

═══ YOUR ANALYSIS ═══
Provide a COMPLETE and STRUCTURED trade note with exactly these sections:

**1. INVESTMENT THESIS — 2 sentences**
Why this opportunity exists and why the market has not yet priced it.

**2. CATALYST**
Identify a dated event (earnings, guidance update, regulatory decision, sector event) within the next 3 weeks that could unlock value.
If no clear catalyst exists, state it explicitly.

**3. TRADE SETUP**
- Entry: [price]
- Stop loss: [price] ([%] risk from entry)
- Target 1: [price] ([%] gain, [X]-day horizon)
- Target 2: [price] ([%] gain, [X]-day horizon)
- Risk/Reward ratio: [x]

**4. MARKET INEFFICIENCY**
What is the consensus missing? Be specific — reference positioning data (short interest, options skew, COT if commodity) if relevant.

**5. KEY RISKS**
2–3 reasons this trade could fail. Be honest and precise.

**6. VALUATION CHECK**
Using the verified fundamentals above, assess whether the asset looks cheap, fair, or expensive. Clearly flag any peer/sector comparison as your own estimate, not verified data.

**7. CONVICTION SCORE**
Score /10 with one-sentence justification.

Be precise, quantified and institutional. No generic statements."""

    return prompt


def call_claude_api(prompt: str, api_key: str) -> Optional[str]:
    """Appelle l'API Claude et retourne la réponse texte."""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}]
        )
        return message.content[0].text
    except Exception as e:
        return f"❌ Erreur API : {str(e)}"


def analyze_ticker(ticker: str, api_key: str, user_context: str = "") -> Dict:
    """
    Pipeline complet : récupère les données → construit le prompt → appelle Claude.
    Retourne un dict avec l'analyse et les données utilisées.
    """
    # 1. Données de marché
    price = get_current_price(ticker)
    dd_data = get_drawdown_from_ath(ticker)
    ret_5d = get_5d_return(ticker)
    info = get_ticker_info(ticker)
    fundamentals = get_fundamentals(ticker)

    market_data = {
        "name":          info.get("name", ticker),
        "sector":        info.get("sector", "N/A"),
        "industry":      fundamentals.get("industry", "N/A"),
        "current_price": price,
        "ath":           dd_data.get("ath") if dd_data else None,
        "drawdown_pct":  dd_data.get("drawdown_pct") if dd_data else None,
        "ret_5d":        ret_5d,
        "short_pct":     info.get("short_pct_float"),
        "rel_volume":    None,  # calculé dans le screener
        "spike_ratio":   None,  # calculé dans le screener
        "fundamentals":  fundamentals,
    }

    # 2. Prompt
    prompt = build_analysis_prompt(ticker, market_data, user_context)

    # 3. Appel Claude
    analysis = call_claude_api(prompt, api_key)

    return {
        "ticker":      ticker,
        "market_data": market_data,
        "prompt":      prompt,
        "analysis":    analysis,
    }
