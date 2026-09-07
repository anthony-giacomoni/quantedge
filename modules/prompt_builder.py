# ============================================================
#  QuantEdge — Prompt Builder
#  Research prompt templates with explicit data-integrity constraints
# ============================================================

from typing import Dict, List
import re
from datetime import datetime
import pytz


DATA_INTEGRITY_GUARDRAIL = """

═══ DATA INTEGRITY RULES ═══
- This prompt does not provide a general-purpose live market/news feed.
- Treat explicitly supplied figures as inputs. Treat them as source-labelled when a provider/source is shown; source-labelled does not mean independently verified.
- Do not invent current prices, earnings dates, macro releases, contracts, filings, fund positioning, options activity, COT data or other time-sensitive facts.
- If the requested conclusion requires current information that is not supplied, DO NOT fabricate a ranking or recommendation. Return a concise missing-data checklist instead.
- Any valuation/peer assumptions must be clearly labelled as estimates, and do not calculate a DCF from invented financial-statement inputs.
"""

PROMPT_TEMPLATES = {

    "Trade Setup — Opportunity Scan": {
        "description": "Rule-based opportunity framework using only supplied candidate data",
        "template": """Date: {date}

You are a senior equity analyst at a global macro hedge fund covering energy, semiconductors, defence and healthcare.

Evaluate up to 3 candidate trade setups from the data supplied below. If no candidate-specific data is supplied, return only the inputs required to run the scan; do not invent tickers or current market facts.

SUPPLIED CANDIDATE DATA (user-supplied unless a provider/source is explicitly shown):
{context}

ENTRY CRITERIA (all must be met):
• No +4% move on the day or over the last 5 sessions (avoid chasing momentum)
• A dated catalyst may be used only if it is supplied with an explicit source/date in the input data
• OR a material thesis explicitly supported by the supplied data; do not invent current news
• Position size: €1,000–3,000 | Full exit on target, no pyramiding
• Exclude: pre-revenue biotech, FDA binary events as sole catalyst

FOR EACH SETUP:
1. Ticker + latest available price (use only a supplied/source-labelled price; otherwise mark N/A)
2. Entry / Stop / Target with % distances
3. Risk/Reward ratio (minimum 2.5:1)
4. Estimated holding period
5. Catalyst: exact nature + date if known
6. Market inefficiency: what is the consensus missing? Reference any relevant positioning data (short interest, options skew, COT if commodity)
7. Key invalidation: one condition that would void the thesis immediately

Priority universe: energy (oil majors, utilities, uranium), semiconductors (equipment + fabless), defence & aerospace, healthcare tech (SaaS, MedTech).

Format output as structured trade notes, not prose.""",
    },

    "Intrinsic Value vs Market Cap": {
        "description": "DCF + comparable multiples to identify mispriced assets",
        "template": """Date: {date}

You are a sell-side equity analyst. Perform a rapid valuation analysis on {ticker} ({name}).

Current market data:
- Price: {price}
- 5Y-high correction: {drawdown}
- 5-session return: {ret_5d}
- Short interest: {short_pct}
- Quote source/timestamp: {quote_source} / {quote_timestamp}
- History source/as-of: {history_source} / {history_as_of}
- Fundamentals source: {fundamentals_source}

VALUATION FRAMEWORK:

1. NORMALISED FCF / DCF INPUT CHECK
- Use supplied FCF, debt/cash, share-count and forecast inputs only.
- If those inputs are not supplied, list the missing inputs and mark DCF fair value unavailable.
- Do not manufacture a WACC, terminal growth rate or forward cash flow from the market-data snapshot alone.

2. COMPARABLE MULTIPLES
- EV/EBITDA vs sector median (LTM + NTM)
- P/E trailing + forward vs sector median
- P/FCF vs sector median
- EV/Sales if growth company
- → Premium or discount to peers (%)

3. SUM-OF-PARTS (if conglomerate or multi-segment)
- Break down business segments
- Apply segment-specific multiples
- → SOTP implied value

4. VERDICT
- Current market cap: [X]
- Implied fair value: [low] / [base] / [high]
- Upside/downside to base: [%]
- Margin of safety: adequate (>20%) / thin / negative
- Conviction: BUY / HOLD / AVOID with score /10

5. WHAT THE MARKET IS MISSING
One paragraph on the key factor the consensus is underweighting — be specific.""",
    },

    "Sector Deep Dive — Energy": {
        "description": "Macro energy view — Brent, TTF, OPEC, utilities, transition",
        "template": """Date: {date}

You are a senior commodities strategist with coverage of oil, gas and power markets.

Use only the supplied current observations below for time-sensitive claims. If they are missing, identify what data is required rather than supplying current levels from memory.

SUPPLIED CURRENT OBSERVATIONS (user-supplied unless sourced):
{context}

Provide a structured energy-sector framework with trade implications:

1. CRUDE OIL (Brent / WTI)
- Current level, technical structure (support/resistance)
- OPEC+ production stance and compliance
- EIA inventory trend (last 4 weeks)
- Demand outlook: China, US driving season, refinery margins
- → Directional bias + key level to watch

2. EUROPEAN NATURAL GAS (TTF)
- Storage fill rate vs 5-year average
- LNG import flows
- Weather forecast impact (heating demand)
- → Risk to winter pricing

3. URANIUM
- Spot vs term price spread
- Utility contracting pace
- Supply disruptions (Kazakhstan, Canada)
- → Structural bull/bear case

4. UTILITIES & RENEWABLES
- Rate sensitivity: impact of current Fed/ECB trajectory on valuations
- Power price outlook by region
- Grid investment cycle

5. TOP 3 ACTIONABLE TRADES
For each: ticker, thesis in 2 sentences, entry/stop/target, catalyst.""",
    },

    "Sector Deep Dive — Defence": {
        "description": "Defence sector view — budgets, contracts, geopolitics",
        "template": """Date: {date}

You are a defence & aerospace analyst.

Use only the supplied current observations below for time-sensitive claims. If they are missing, identify what data is required rather than supplying current facts from memory.

SUPPLIED CURRENT OBSERVATIONS (user-supplied unless sourced):
{context}

Provide a structured sector framework with trade implications:

1. BUDGET LANDSCAPE
- NATO 2% GDP target: current compliance by country
- US defence budget trajectory (continuing resolution risk)
- European rearmament: key programmes and beneficiaries

2. ORDER BOOK & BACKLOG
- Visibility on revenues: LMT, RTX, NOC, RHM.DE, AIR.PA
- Book-to-bill ratios trend
- Key contract decisions expected in next 3 months

3. GEOPOLITICAL DEMAND DRIVERS
- Active conflicts and equipment depletion rates
- Missile defence, drone warfare, cyber: fastest growing segments
- Nuclear deterrence modernisation cycle

4. VALUATIONS
- Sector P/E vs 10-year average
- FCF yield comparison across names
- Which names are pricing in the rearmament cycle, which are not?

5. TOP 3 TRADES
Ticker, thesis, entry/stop/target, catalyst + timing.""",
    },

    "Due Diligence — Pre-Entry Check": {
        "description": "5-minute check before entering a position",
        "template": """Date: {date}. Pre-entry due diligence on {ticker}.

I am considering entering {ticker} ({name}) at {price}.
Data provenance: quote {quote_source} at {quote_timestamp}; history {history_source} as of {history_as_of}; fundamentals {fundamentals_source}.
Additional user-supplied context (not independently verified unless sourced): {context}

Answer each section in under 100 words:

1. RED FLAGS
Any structural issue that invalidates the trade today? (debt covenant breach, dilution risk, lock-up expiry, audit issue, insider selling cluster)

2. EVENT RISK
Any binary event in the next 14 days that could gap the stock against me? (earnings, FDA, legal ruling, index rebalancing)

3. POSITIONING DATA
If recent 13F, short-position or options data is explicitly supplied, assess it. Otherwise mark positioning unavailable; do not infer what large funds are doing.

4. TECHNICAL STRUCTURE
Assess only technical levels explicitly supplied in the prompt/context. If VWAP, moving averages or support/resistance observations are not supplied, mark this section unavailable.

5. BETTER ALTERNATIVE
Compare peers only if peer observations are explicitly supplied. Otherwise state that a same-sector alternative cannot be ranked from the supplied data.

6. VERDICT
Go / No-go in one sentence. If No-go, suggest the trigger that would make it a Go.""",
    },

    "Post-Trade Analysis": {
        "description": "Structured debrief on a closed trade",
        "template": """Date: {date}. Post-trade analysis.

Trade details:
- Ticker: {ticker}
- Entry: {entry_price} on {entry_date}
- Exit: {exit_price} on {exit_date}
- P&L: {pnl}€
- Initial thesis: {notes}

1. THESIS ASSESSMENT
Was the original thesis correct? Did the catalyst materialise as expected?

2. EXECUTION QUALITY
Was the entry timing optimal? Was the exit too early / too late?

3. WHAT WENT RIGHT
Maximum 3 points.

4. WHAT WENT WRONG (or could have been better)
Maximum 3 points. Be precise — avoid generic answers.

5. LESSONS
Two concrete rules to apply to future similar setups.

6. PATTERN RECOGNITION
A single trade is not enough to establish a recurring pattern. If no multi-trade history is explicitly supplied, state that pattern recognition and sizing conclusions are unavailable. If a historical sample is supplied, describe the evidence and uncertainty; do not recommend increasing size solely from one trade.""",
    },
}


def fill_template(template: str, variables: Dict) -> str:
    now = datetime.now(pytz.timezone("Europe/Paris"))
    variables["date"] = now.strftime("%A %d %B %Y — %H:%M") + " Paris time"
    result = template
    for key, value in variables.items():
        result = result.replace(f"{{{key}}}", "N/A" if value is None or value == "" else str(value))
    # Never send unresolved template placeholders to the model: an absent input
    # is data-unavailable, not an invitation to infer a value.
    result = re.sub(r"\{[A-Za-z_][A-Za-z0-9_]*\}", "N/A", result)
    return result + DATA_INTEGRITY_GUARDRAIL


def get_template_names() -> List[str]:
    return list(PROMPT_TEMPLATES.keys())


def get_template(name: str) -> Dict:
    return PROMPT_TEMPLATES.get(name, {})
