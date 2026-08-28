# ============================================================
#  QuantEdge — Macro Alerts & Calendar Module
#  Compatible Python 3.8
# ============================================================

from typing import List, Dict
from datetime import datetime, date, timedelta
import pytz

# ============================================================
#  HARDCODED MACRO CALENDAR (manually maintained)
#  Sources: Fed, ECB, EIA, OPEC, BLS, BEA
# ============================================================

MACRO_EVENTS = [
    # ── CENTRAL BANKS ────────────────────────────────────────
    {
        "date":     "2026-09-10",
        "time":     "20:00",
        "event":    "Fed Rate Decision (FOMC)",
        "category": "Central Bank",
        "impact":   "🔴 Major",
        "sectors":  ["All"],
        "note":     "Market pricing -25bp. A hawkish surprise = sell-off in tech + energy.",
    },
    {
        "date":     "2026-09-11",
        "time":     "14:30",
        "event":    "Powell Press Conference",
        "category": "Central Bank",
        "impact":   "🔴 Major",
        "sectors":  ["All"],
        "note":     "Key forward guidance. Inflation wording = USD volatility.",
    },
    {
        "date":     "2026-09-12",
        "time":     "14:15",
        "event":    "ECB Rate Decision",
        "category": "Central Bank",
        "impact":   "🔴 Major",
        "sectors":  ["🇪🇺 EU Energy", "🇪🇺 EU Finance"],
        "note":     "Direct impact on European utilities and banks. Watch EUR/USD.",
    },
    {
        "date":     "2026-09-17",
        "time":     "14:30",
        "event":    "BoE Rate Decision",
        "category": "Central Bank",
        "impact":   "🟡 Moderate",
        "sectors":  ["🇪🇺 EU Finance"],
        "note":     "Impact on GBP and UK banks (HSBC, Barclays).",
    },

    # ── US MACRO ─────────────────────────────────────────────
    {
        "date":     "2026-09-09",
        "time":     "14:30",
        "event":    "US CPI (August Inflation)",
        "category": "US Macro",
        "impact":   "🔴 Major",
        "sectors":  ["All"],
        "note":     "Consensus +2.9% YoY. Upside surprise = USD rebound, growth sell-off.",
    },
    {
        "date":     "2026-09-05",
        "time":     "14:30",
        "event":    "NFP (August Payrolls)",
        "category": "US Macro",
        "impact":   "🔴 Major",
        "sectors":  ["All"],
        "note":     "Non-Farm Payrolls. Consensus +175K. Key Fed pivot indicator.",
    },
    {
        "date":     "2026-09-18",
        "time":     "14:30",
        "event":    "US PPI (Producer Prices)",
        "category": "US Macro",
        "impact":   "🟡 Moderate",
        "sectors":  ["🇺🇸 US Energy", "🇺🇸 US Semiconductors"],
        "note":     "Leading inflation indicator. Impacts industrial margins.",
    },
    {
        "date":     "2026-09-25",
        "time":     "14:30",
        "event":    "US GDP Q2 (revised)",
        "category": "US Macro",
        "impact":   "🟡 Moderate",
        "sectors":  ["All"],
        "note":     "Final Q2 revision. A surprise = repricing of risk assets.",
    },

    # ── ENERGY / OPEC ────────────────────────────────────────
    {
        "date":     "2026-09-04",
        "time":     "16:30",
        "event":    "EIA Crude Inventories (weekly)",
        "category": "Energy",
        "impact":   "🟡 Moderate",
        "sectors":  ["🇺🇸 US Energy", "🇪🇺 EU Energy", "🌍 Global Commodities & ETFs"],
        "note":     "Weekly EIA release. Inventory change = ±2% Brent/WTI move.",
    },
    {
        "date":     "2026-09-11",
        "time":     "16:30",
        "event":    "EIA Crude Inventories (weekly)",
        "category": "Energy",
        "impact":   "🟡 Moderate",
        "sectors":  ["🇺🇸 US Energy", "🇪🇺 EU Energy"],
        "note":     "Weekly tracking. Context: OPEC+ production cuts.",
    },
    {
        "date":     "2026-09-15",
        "time":     "12:00",
        "event":    "OPEC+ Meeting (monitoring)",
        "category": "Energy",
        "impact":   "🔴 Major",
        "sectors":  ["🇺🇸 US Energy", "🇪🇺 EU Energy", "🌍 Global Commodities & ETFs"],
        "note":     "Production quota decision. A surprise cut = Brent +5%. Direct impact on SIE.DE, TTE, XOM.",
    },
    {
        "date":     "2026-09-18",
        "time":     "16:30",
        "event":    "EIA Crude Inventories (weekly)",
        "category": "Energy",
        "impact":   "🟡 Moderate",
        "sectors":  ["🇺🇸 US Energy", "🇪🇺 EU Energy"],
        "note":     "Post-OPEC. Confirms or contradicts the production decision.",
    },
    {
        "date":     "2026-09-08",
        "time":     "11:00",
        "event":    "TTF Gas Price (Eurostat release)",
        "category": "Energy",
        "impact":   "🟡 Moderate",
        "sectors":  ["🇪🇺 EU Energy"],
        "note":     "European natural gas benchmark. Direct impact on EDF, Enel, Iberdrola.",
    },

    # ── SEMICONDUCTORS / TECH ────────────────────────────────
    {
        "date":     "2026-09-10",
        "time":     "22:00",
        "event":    "NVIDIA GTC Conference (keynote)",
        "category": "Tech / Semis",
        "impact":   "🔴 Major",
        "sectors":  ["🇺🇸 US Semiconductors"],
        "note":     "Next-gen GPU announcements. Major catalyst for NVDA + ecosystem (AMAT, KLAC, ASML).",
    },
    {
        "date":     "2026-09-20",
        "time":     "14:00",
        "event":    "SIA Report (Semi Industry Association)",
        "category": "Tech / Semis",
        "impact":   "🟡 Moderate",
        "sectors":  ["🇺🇸 US Semiconductors", "🇪🇺 EU Industry / Tech"],
        "note":     "Global semi sales. Industry cycle indicator.",
    },

    # ── DEFENCE ──────────────────────────────────────────────
    {
        "date":     "2026-09-13",
        "time":     "09:00",
        "event":    "EU Defence Summit (Brussels)",
        "category": "Defence",
        "impact":   "🟡 Moderate",
        "sectors":  ["🇪🇺 EU Defence", "🇺🇸 US Defence"],
        "note":     "European defence budget announcements. Catalyst for RHM.DE, AIR.PA, SAF.PA.",
    },
    {
        "date":     "2026-09-22",
        "time":     "15:00",
        "event":    "US Defence Budget (Congress vote)",
        "category": "Defence",
        "impact":   "🟡 Moderate",
        "sectors":  ["🇺🇸 US Defence"],
        "note":     "F-35, missile and cyber contract allocation. Impact on LMT, RTX, NOC.",
    },
]

# ============================================================
#  EARNINGS CALENDAR (watchlist tickers)
#  Approximate dates — verify against earnings whispers
# ============================================================

EARNINGS_EVENTS = [
    {"date": "2026-09-04", "ticker": "VEEV",   "name": "Veeva Systems",      "consensus": "EPS $1.62",  "note": "Key FY27 guidance"},
    {"date": "2026-09-05", "ticker": "ZS",     "name": "Zscaler",            "consensus": "EPS $0.87",  "note": "ARR growth watch"},
    {"date": "2026-09-10", "ticker": "CRWD",   "name": "CrowdStrike",        "consensus": "EPS $0.95",  "note": "Post-incident recovery"},
    {"date": "2026-09-11", "ticker": "DDOG",   "name": "Datadog",            "consensus": "EPS $0.42",  "note": "Cloud spend indicator"},
    {"date": "2026-09-15", "ticker": "ADBE",   "name": "Adobe",              "consensus": "EPS $4.85",  "note": "AI monetization"},
    {"date": "2026-09-17", "ticker": "FDX",    "name": "FedEx",              "consensus": "EPS $5.40",  "note": "Macro proxy"},
    {"date": "2026-09-18", "ticker": "RHM.DE", "name": "Rheinmetall",        "consensus": "EPS €8.20",  "note": "EU defence order book"},
    {"date": "2026-09-22", "ticker": "SIE.DE", "name": "Siemens Energy",     "consensus": "EPS €0.45",  "note": "FY2027 guidance expected"},
    {"date": "2026-09-24", "ticker": "MU",     "name": "Micron Technology",  "consensus": "EPS $1.48",  "note": "DRAM cycle indicator"},
    {"date": "2026-09-25", "ticker": "CCL",    "name": "Carnival",           "consensus": "EPS $1.15",  "note": "Consumer spending proxy"},
]


# ============================================================
#  UTILITY FUNCTIONS
# ============================================================

def get_upcoming_events(days_ahead: int = 21) -> Dict:
    """
    Returns macro and earnings events within the next N days.
    """
    paris_tz = pytz.timezone("Europe/Paris")
    today = datetime.now(paris_tz).date()
    cutoff = today + timedelta(days=days_ahead)

    upcoming_macro = []
    for event in MACRO_EVENTS:
        event_date = datetime.strptime(event["date"], "%Y-%m-%d").date()
        if today <= event_date <= cutoff:
            days_until = (event_date - today).days
            upcoming_macro.append({**event, "days_until": days_until, "event_date": event_date})

    upcoming_earnings = []
    for event in EARNINGS_EVENTS:
        event_date = datetime.strptime(event["date"], "%Y-%m-%d").date()
        if today <= event_date <= cutoff:
            days_until = (event_date - today).days
            upcoming_earnings.append({**event, "days_until": days_until, "event_date": event_date})

    upcoming_macro    = sorted(upcoming_macro,    key=lambda x: x["event_date"])
    upcoming_earnings = sorted(upcoming_earnings, key=lambda x: x["event_date"])

    return {
        "macro":    upcoming_macro,
        "earnings": upcoming_earnings,
        "today":    today,
        "cutoff":   cutoff,
    }


def get_impact_color(impact: str) -> str:
    """Returns the CSS color matching an event's impact level."""
    if "Major" in impact:
        return "#ef4444"
    elif "Moderate" in impact:
        return "#f59e0b"
    return "#22c55e"


def days_label(days: int) -> str:
    """Formats the number of days remaining until an event."""
    if days == 0:
        return "🔴 Today"
    elif days == 1:
        return "🟠 Tomorrow"
    elif days <= 3:
        return f"🟡 In {days}d"
    else:
        return f"⚪ In {days}d"
