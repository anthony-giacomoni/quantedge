# ============================================================
#  QuantEdge — Configuration centrale
#  Modifie ce fichier pour adapter les paramètres à tes besoins
# ============================================================

import os
from dotenv import load_dotenv

load_dotenv()

# --- API Keys ---
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# --- Critères du screener (tes critères éprouvés) ---
SCREENER_CRITERIA = {
    "min_drawdown_from_ath": 0.30,      # Correction min depuis ATH (30%)
    "max_drawdown_from_ath": 0.50,      # Correction max depuis ATH (50%)
    "max_catalyst_days":     21,        # Catalyseur dans 3 semaines max
    "max_5d_return":         0.04,      # Pas de +4% sur 5 jours
    "min_short_interest":    0.05,      # Short interest min (5%)
    "max_short_interest":    0.15,      # Short interest max (15%)
}

# --- Univers d'actifs à screener ---
# Secteurs de force : énergie, semiconducteurs, défense, healthcare tech
WATCHLIST = {
    "Energie": [
        "SIE.DE",   # Siemens Energy
        "XOM",      # ExxonMobil
        "CVX",      # Chevron
        "TTE",      # TotalEnergies
        "BP",       # BP
        "ENPH",     # Enphase Energy
        "NEE",      # NextEra Energy
        "UEC",      # Uranium Energy Corp
        "CCJ",      # Cameco (uranium)
        "OXY",      # Occidental Petroleum
    ],
    "Semiconducteurs": [
        "NVDA",     # Nvidia
        "AMD",      # AMD
        "ASML",     # ASML
        "INTC",     # Intel
        "QCOM",     # Qualcomm
        "MRVL",     # Marvell
        "AMAT",     # Applied Materials
        "KLAC",     # KLA Corp
        "ON",       # ON Semiconductor
        "WOLF",     # Wolfspeed
    ],
    "Défense": [
        "LMT",      # Lockheed Martin
        "RTX",      # Raytheon
        "NOC",      # Northrop Grumman
        "GD",       # General Dynamics
        "RHM.DE",   # Rheinmetall
        "BA",       # Boeing
        "HII",      # Huntington Ingalls
        "LDOS",     # Leidos
    ],
    "Healthcare Tech": [
        "VEEV",     # Veeva Systems
        "ISRG",     # Intuitive Surgical
        "DXCM",     # Dexcom
        "ELV",      # Elevance Health
        "UNH",      # UnitedHealth
        "TDOC",     # Teladoc
        "GEHC",     # GE Healthcare
    ],
    "ETFs & Indices": [
        "XLE",      # S&P Energy ETF
        "SOXX",     # iShares Semis ETF
        "ITA",      # iShares Defense ETF
        "XBI",      # SPDR Biotech ETF
        "IWM",      # Russell 2000
    ],
}

# Tous les tickers à plat
ALL_TICKERS = [t for sector in WATCHLIST.values() for t in sector]

# --- Chemins ---
DB_PATH = "data/quantedge.db"

# --- Modèle Claude ---
CLAUDE_MODEL = "claude-sonnet-4-6"
CLAUDE_MAX_TOKENS = 1500
