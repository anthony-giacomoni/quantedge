# ============================================================
#  QuantEdge — Chargement initial du track record d'Anthony
#  29 trades réels (2025-2026)
#  À exécuter UNE SEULE FOIS : python utils/seed_trades.py
# ============================================================

from utils.db import init_database, insert_trade, trades_already_loaded

TRADES = [
    # ── TRADE 1 ─────────────────────────────────────────────
    {
        "ticker":      "UEC",
        "direction":   "LONG",
        "qty":         None,        # non précisé
        "entry_price": 6.27,
        "entry_date":  "2025-05-26",
        "exit_price":  7.00,
        "exit_date":   "2025-07-17",
        "pnl":         56.42,
        "invested":    501.00,
        "status":      "CLOSED",
        "sector":      "Energie",
        "notes":       "Uranium Energy Corp — correction ATH + catalyseur sectoriel",
    },
    # ── TRADE 2 ─────────────────────────────────────────────
    {
        "ticker":      "IWM",
        "direction":   "LONG",
        "qty":         None,
        "entry_price": 52.91,
        "entry_date":  "2025-06-19",
        "exit_price":  53.84,
        "exit_date":   "2025-06-24",
        "pnl":         15.58,
        "invested":    1001.00,
        "status":      "CLOSED",
        "sector":      "ETFs & Indices",
        "notes":       "Russell 2000 small cap",
    },
    # ── TRADE 3 ─────────────────────────────────────────────
    {
        "ticker":      "EL",
        "direction":   "LONG",
        "qty":         None,
        "entry_price": 69.40,
        "entry_date":  "2025-06-24",
        "exit_price":  72.40,
        "exit_date":   "2025-07-01",
        "pnl":         41.23,
        "invested":    1001.00,
        "status":      "CLOSED",
        "sector":      "Healthcare Tech",
        "notes":       "Estee Lauder — rebond sur correction",
    },
    # ── TRADE 4 ─────────────────────────────────────────────
    {
        "ticker":      "SIE.DE",
        "direction":   "LONG",
        "qty":         None,
        "entry_price": 93.08,
        "entry_date":  "2025-07-01",
        "exit_price":  95.64,
        "exit_date":   "2025-07-23",
        "pnl":         53.01,
        "invested":    2001.00,
        "status":      "CLOSED",
        "sector":      "Energie",
        "notes":       "Siemens Energy x1",
    },
    # ── TRADE 5 ─────────────────────────────────────────────
    {
        "ticker":      "UNH",
        "direction":   "LONG",
        "qty":         None,
        "entry_price": 245.25,
        "entry_date":  "2025-07-23",
        "exit_price":  239.50,
        "exit_date":   "2025-07-24",
        "pnl":         -95.76,
        "invested":    4000.18,
        "status":      "CLOSED",
        "sector":      "Healthcare Tech",
        "notes":       "UnitedHealth Group long — seule vraie perte du track record",
    },
    # ── TRADE 6 ─────────────────────────────────────────────
    {
        "ticker":      "UNH",
        "direction":   "SHORT",
        "qty":         None,
        "entry_price": 0.65,
        "entry_date":  "2025-07-24",
        "exit_price":  0.89,
        "exit_date":   "2025-07-29",
        "pnl":         46.00,
        "invested":    131.00,
        "status":      "CLOSED",
        "sector":      "Healthcare Tech",
        "notes":       "UnitedHealth Group SHORT x7.16 — recovery immédiate après la perte long",
    },
    # ── TRADE 7 ─────────────────────────────────────────────
    {
        "ticker":      "BZ=F",
        "direction":   "LONG",
        "qty":         None,
        "entry_price": 44.88,
        "entry_date":  "2025-07-29",
        "exit_price":  45.73,
        "exit_date":   "2025-07-31",
        "pnl":         15.94,
        "invested":    1001.00,
        "status":      "CLOSED",
        "sector":      "Energie",
        "notes":       "Brent crude oil",
    },
    # ── TRADE 8 ─────────────────────────────────────────────
    {
        "ticker":      "EXH1.PA",
        "direction":   "LONG",
        "qty":         None,
        "entry_price": 10.72,
        "entry_date":  "2025-07-31",
        "exit_price":  11.16,
        "exit_date":   "2025-09-26",
        "pnl":         131.20,
        "invested":    3217.00,
        "status":      "CLOSED",
        "sector":      "Energie",
        "notes":       "MSCI Europe Energy",
    },
    # ── TRADE 9 ─────────────────────────────────────────────
    {
        "ticker":      "NVDA",
        "direction":   "LONG",
        "qty":         None,
        "entry_price": 151.70,
        "entry_date":  "2025-11-25",
        "exit_price":  157.94,
        "exit_date":   "2025-12-02",
        "pnl":         80.28,
        "invested":    2001.00,
        "status":      "CLOSED",
        "sector":      "Semiconducteurs",
        "notes":       "Nvidia x1",
    },
    # ── TRADE 10 ────────────────────────────────────────────
    {
        "ticker":      "NVDA",
        "direction":   "LONG",
        "qty":         14,
        "entry_price": 155.60,
        "entry_date":  "2025-12-02",
        "exit_price":  160.76,
        "exit_date":   "2025-12-08",
        "pnl":         71.24,
        "invested":    2179.40,
        "status":      "CLOSED",
        "sector":      "Semiconducteurs",
        "notes":       "Nvidia x2 — 14 actions",
    },
    # ── TRADE 11 ────────────────────────────────────────────
    {
        "ticker":      "NVDA",
        "direction":   "LONG",
        "qty":         15,
        "entry_price": 158.54,
        "entry_date":  "2025-12-09",
        "exit_price":  159.52,
        "exit_date":   "2025-12-23",
        "pnl":         13.70,
        "invested":    2379.10,
        "status":      "CLOSED",
        "sector":      "Semiconducteurs",
        "notes":       "Nvidia x3 — 15 actions",
    },
    # ── TRADE 12 ────────────────────────────────────────────
    {
        "ticker":      "SK.PA",
        "direction":   "LONG",
        "qty":         20,
        "entry_price": 49.06,
        "entry_date":  "2025-12-23",
        "exit_price":  51.30,
        "exit_date":   "2026-01-08",
        "pnl":         39.88,
        "invested":    986.12,
        "status":      "CLOSED",
        "sector":      "Autre",
        "notes":       "SEB — 20 actions",
    },
    # ── TRADE 13 ────────────────────────────────────────────
    {
        "ticker":      "SIE.DE",
        "direction":   "LONG",
        "qty":         16,
        "entry_price": 127.95,
        "entry_date":  "2026-01-08",
        "exit_price":  134.50,
        "exit_date":   "2026-01-16",
        "pnl":         103.80,
        "invested":    2047.20,
        "status":      "CLOSED",
        "sector":      "Energie",
        "notes":       "Siemens Energy x2 — 16 actions",
    },
    # ── TRADE 14 ────────────────────────────────────────────
    {
        "ticker":      "NVDA",
        "direction":   "LONG",
        "qty":         16,
        "entry_price": 159.08,
        "entry_date":  "2026-01-08",
        "exit_price":  162.58,
        "exit_date":   "2026-01-15",
        "pnl":         54.00,
        "invested":    2546.28,
        "status":      "CLOSED",
        "sector":      "Semiconducteurs",
        "notes":       "Nvidia x4 — 16 actions",
    },
    # ── TRADE 15 ────────────────────────────────────────────
    {
        "ticker":      "NVDA",
        "direction":   "LONG",
        "qty":         17,
        "entry_price": 152.88,
        "entry_date":  "2026-01-20",
        "exit_price":  160.20,
        "exit_date":   "2026-01-28",
        "pnl":         122.44,
        "invested":    2599.96,
        "status":      "CLOSED",
        "sector":      "Semiconducteurs",
        "notes":       "Nvidia x5 — 17 actions",
    },
    # ── TRADE 16 ────────────────────────────────────────────
    # Note : double position Nvidia fermée le même jour (6/2)
    {
        "ticker":      "NVDA",
        "direction":   "LONG",
        "qty":         32,   # 17 + 15 actions combinées
        "entry_price": 149.00,  # prix moyen pondéré (151.31 & 145.86)
        "entry_date":  "2026-02-03",
        "exit_price":  156.80,
        "exit_date":   "2026-02-06",
        "pnl":         254.26,
        "invested":    4762.34,  # 2573.44 + 2188.9
        "status":      "CLOSED",
        "sector":      "Semiconducteurs",
        "notes":       "Nvidia x6 — double position : 17 actions (151.31→156.8) + 15 actions (145.86→156.8)",
    },
    # ── TRADE 17 ────────────────────────────────────────────
    {
        "ticker":      "MXWD.MI",
        "direction":   "LONG",
        "qty":         200,
        "entry_price": 11.18,
        "entry_date":  "2026-02-17",
        "exit_price":  11.52,
        "exit_date":   "2026-02-20",
        "pnl":         66.80,
        "invested":    2235.80,
        "status":      "CLOSED",
        "sector":      "Semiconducteurs",
        "notes":       "MSCI Global Semiconductors — 200 actions",
    },
    # ── TRADE 18 ────────────────────────────────────────────
    {
        "ticker":      "RHM.DE",
        "direction":   "LONG",
        "qty":         2,
        "entry_price": 1699.00,
        "entry_date":  "2026-02-23",
        "exit_price":  1709.50,
        "exit_date":   "2026-02-25",
        "pnl":         19.00,
        "invested":    3399.00,
        "status":      "CLOSED",
        "sector":      "Défense",
        "notes":       "Rheinmetall — 2 actions",
    },
    # ── TRADE 19 ────────────────────────────────────────────
    {
        "ticker":      "XLE",
        "direction":   "LONG",
        "qty":         100,
        "entry_price": 36.92,
        "entry_date":  "2026-02-25",
        "exit_price":  37.04,
        "exit_date":   "2026-02-26",
        "pnl":         10.50,
        "invested":    3692.50,
        "status":      "CLOSED",
        "sector":      "Energie",
        "notes":       "S&P US Energy Select Sector — 100 actions",
    },
    # ── TRADE 20 ────────────────────────────────────────────
    {
        "ticker":      "LMT",
        "direction":   "LONG",
        "qty":         7,
        "entry_price": 546.70,
        "entry_date":  "2026-02-26",
        "exit_price":  552.00,
        "exit_date":   "2026-02-27",
        "pnl":         35.10,
        "invested":    3827.90,
        "status":      "CLOSED",
        "sector":      "Défense",
        "notes":       "Lockheed Martin — 7 actions",
    },
    # ── TRADE 21 ────────────────────────────────────────────
    {
        "ticker":      "NVDA",
        "direction":   "LONG",
        "qty":         25,
        "entry_price": 152.72,
        "entry_date":  "2026-03-09",
        "exit_price":  160.60,
        "exit_date":   "2026-03-10",
        "pnl":         195.00,
        "invested":    3819.00,
        "status":      "CLOSED",
        "sector":      "Semiconducteurs",
        "notes":       "Nvidia x7 — 25 actions",
    },
    # ── TRADE 22 ────────────────────────────────────────────
    {
        "ticker":      "VEEV",
        "direction":   "LONG",
        "qty":         30,
        "entry_price": 144.30,
        "entry_date":  "2026-04-21",
        "exit_price":  161.95,
        "exit_date":   "2026-07-01",
        "pnl":         527.50,
        "invested":    4330.00,
        "status":      "CLOSED",
        "sector":      "Healthcare Tech",
        "notes":       "Veeva Systems — 30 actions. Meilleur trade clôturé du track record.",
    },
    # ── TRADE 23 — OUVERT ────────────────────────────────────
    {
        "ticker":      "NFLX",
        "direction":   "LONG",
        "qty":         50,
        "entry_price": 79.15,
        "entry_date":  "2026-04-21",
        "exit_price":  None,
        "exit_date":   None,
        "pnl":         None,
        "invested":    3958.50,
        "status":      "OPEN",
        "sector":      "Tech",
        "notes":       "Netflix — 50 actions. Position ouverte.",
    },
    # ── TRADE 24 ────────────────────────────────────────────
    # PayPal x1 supprimé : stop loss déclenché par frais cachés, non représentatif
    {
        "ticker":      "PYPL",
        "direction":   "LONG",
        "qty":         50,
        "entry_price": 39.16,
        "entry_date":  "2026-07-08",
        "exit_price":  41.865,
        "exit_date":   "2026-07-13",
        "pnl":         134.25,
        "invested":    1959.00,
        "status":      "CLOSED",
        "sector":      "Tech",
        "notes":       "PayPal x2 — rebond confirmé",
    },
    # ── TRADE 26 ────────────────────────────────────────────
    {
        "ticker":      "STLA",
        "direction":   "LONG",
        "qty":         400,
        "entry_price": 5.01,
        "entry_date":  "2026-07-15",
        "exit_price":  5.306,
        "exit_date":   "2026-07-29",
        "pnl":         117.40,
        "invested":    2005.00,
        "status":      "CLOSED",
        "sector":      "Autre",
        "notes":       "Stellantis — 400 actions",
    },
    # ── TRADE 27 ────────────────────────────────────────────
    {
        "ticker":      "ZS",
        "direction":   "LONG",
        "qty":         22,
        "entry_price": 135.31,
        "entry_date":  "2026-07-29",
        "exit_price":  140.04,
        "exit_date":   "2026-08-05",
        "pnl":         101.84,
        "invested":    2978.04,
        "status":      "CLOSED",
        "sector":      "Tech",
        "notes":       "Zscaler — 22 actions",
    },
    # ── TRADE 28 — OUVERT ────────────────────────────────────
    {
        "ticker":      "AON",
        "direction":   "LONG",
        "qty":         10,
        "entry_price": 313.50,
        "entry_date":  "2026-08-06",
        "exit_price":  None,
        "exit_date":   None,
        "pnl":         None,
        "invested":    3136.00,
        "status":      "OPEN",
        "sector":      "Finance",
        "notes":       "Aon — 10 actions. Position ouverte.",
    },
]


def seed(db_path: str = "data/quantedge.db"):
    init_database(db_path)

    if trades_already_loaded(db_path):
        print("⚠️  Des trades sont déjà en base. Seed annulé pour éviter les doublons.")
        print("    Supprime data/quantedge.db et relance si tu veux repartir de zéro.")
        return

    for trade in TRADES:
        insert_trade(trade, db_path)

    print(f"✅ {len(TRADES)} trades chargés en base.")
    print("   Dont 2 positions ouvertes : Netflix (NFLX) et Aon (AON).")
    print("   Note : PayPal x1 (-0.25€) exclu — stop loss sur frais cachés, non représentatif.")


if __name__ == "__main__":
    import sys
    import os
    # Permet d'exécuter depuis n'importe quel dossier
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    seed()
