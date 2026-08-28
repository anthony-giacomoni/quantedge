# ============================================================
#  QuantEdge — Prompt Builder
#  Institutional-grade prompt templates
# ============================================================

from typing import Dict, List
from datetime import datetime
import pytz

PROMPT_TEMPLATES = {

    "Trade Setup — Opportunity Scan": {
        "description": "Institutional scan — best expected value / volatility setups today",
        "template": """Date: {date}

You are a senior equity analyst at a global macro hedge fund covering energy, semiconductors, defence and healthcare.

Identify 3 high-conviction trade setups with the best expected value / volatility ratio.

ENTRY CRITERIA (all must be met):
• No +4% move on the day or over the last 5 sessions (avoid chasing momentum)
• Dated catalyst within 3 weeks: earnings, guidance update, regulatory decision, sector event
• OR material news not yet reflected in price (information asymmetry)
• Position size: €1,000–3,000 | Full exit on target, no pyramiding
• Exclude: pre-revenue biotech, FDA binary events as sole catalyst

FOR EACH SETUP:
1. Ticker + current price (verify in real time)
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
- ATH correction: {drawdown}
- 5-day return: {ret_5d}
- Short interest: {short_pct}

VALUATION FRAMEWORK:

1. NORMALISED FCF ESTIMATE
- Estimate normalised free cash flow for next 12 months (strip one-offs)
- Apply sector-appropriate WACC
- Terminal growth rate assumption (justify vs GDP + sector growth)
- → Implied intrinsic value per share (DCF)

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

Provide a structured energy sector view with actionable trade implications:

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

Provide a structured sector view with trade implications:

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

Answer each section in under 100 words:

1. RED FLAGS
Any structural issue that invalidates the trade today? (debt covenant breach, dilution risk, lock-up expiry, audit issue, insider selling cluster)

2. EVENT RISK
Any binary event in the next 14 days that could gap the stock against me? (earnings, FDA, legal ruling, index rebalancing)

3. INSTITUTIONAL POSITIONING
What are large funds doing? Any recent 13F changes, notable short positions, unusual options activity?

4. TECHNICAL STRUCTURE
Is price at a meaningful level (support, VWAP, moving average confluence) or in no-man's land?

5. BETTER ALTERNATIVE
Is there a superior risk/reward in the same sector right now?

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
Does this trade fit a recurring pattern in my track record? If yes, what is the pattern and how can I size it more aggressively?""",
    },
}


def fill_template(template: str, variables: Dict) -> str:
    now = datetime.now(pytz.timezone("Europe/Paris"))
    variables["date"] = now.strftime("%A %d %B %Y — %H:%M") + " Paris time"
    result = template
    for key, value in variables.items():
        result = result.replace(f"{{{key}}}", str(value) if value else "N/A")
    return result


def get_template_names() -> List[str]:
    return list(PROMPT_TEMPLATES.keys())


def get_template(name: str) -> Dict:
    return PROMPT_TEMPLATES.get(name, {})
