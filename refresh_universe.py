# ============================================================
#  QuantEdge — Rafraîchissement du cache d'univers (Wide Scan)
#
#  À lancer manuellement (ou via une tâche planifiée quotidienne) :
#      python refresh_universe.py
#      python refresh_universe.py --max-tickers 2000
#
#  Ce script fait le travail RÉSEAU LENT une seule fois : il télécharge
#  les fondamentaux de base (market cap, secteur, PE, revenu — via yfinance,
#  car l'endpoint fundamentals d'EODHD n'est pas inclus dans le plan All-World)
#  et le prix de clôture/haut-bas 1 an (via EODHD, qui fonctionne bien sur ce
#  plan) pour un grand nombre de tickers US, et les stocke dans
#  data/quantedge.db (table universe_cache) avec la date du jour.
#
#  L'app Streamlit (page Opportunities) lit ensuite ce cache pour un
#  filtre instantané, sans refaire ces appels réseau à chaque clic.
#  Seuls les quelques candidats qui passent le filtre sont revérifiés
#  en direct (prix, drawdown, 5d return) au moment du scan dans l'app.
# ============================================================

import sys
import os
import argparse
import time
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.eodhd import get_exchange_tickers, get_52w_stats
from utils.market_data import get_fundamentals
import utils.eodhd as eodhd_module
from utils.db import init_database, save_universe_snapshot, clear_old_snapshots
from config import DB_PATH


def main(max_tickers: int, exchange: str):
    print(f"── QuantEdge Universe Refresh — {date.today().isoformat()} ──")
    init_database(DB_PATH)

    print(f"Fetching ticker list for exchange '{exchange}'...")
    all_tickers = get_exchange_tickers(exchange=exchange)
    if not all_tickers:
        print(f"❌ No tickers returned. Last EODHD error: {eodhd_module.LAST_ERROR}")
        sys.exit(1)
    print(f"  {len(all_tickers)} tickers found on {exchange}.")

    candidates = all_tickers[:max_tickers]
    print(f"Fetching fundamentals + 52-week price stats for {len(candidates)} tickers "
          f"(2 API calls per ticker — this is the slow part)...")

    rows = []
    errors = 0
    start = time.time()

    for i, ticker in enumerate(candidates):
        fund = get_fundamentals(ticker)
        if fund and fund.get("market_cap"):
            price_stats = get_52w_stats(ticker) or {}
            rows.append({
                "ticker":      ticker,
                "name":        fund.get("name", ticker),
                "sector":      fund.get("sector"),
                "industry":    fund.get("industry"),
                "market_cap":  fund.get("market_cap"),
                "pe_ratio":    fund.get("pe_ratio"),
                "revenue":     fund.get("revenue"),
                "close_price": price_stats.get("close_price"),
                "high_52w":    price_stats.get("high_52w"),
                "low_52w":     price_stats.get("low_52w"),
            })
        else:
            errors += 1

        if (i + 1) % 100 == 0:
            elapsed = time.time() - start
            print(f"  [{i+1}/{len(candidates)}] {len(rows)} valid, "
                  f"{errors} errors, {elapsed:.0f}s elapsed")

    elapsed = time.time() - start
    print(f"Done in {elapsed:.0f}s. {len(rows)} tickers with usable fundamentals, "
          f"{errors} skipped (no data).")

    if not rows:
        print("❌ No valid data collected — nothing saved.")
        sys.exit(1)

    snapshot_date = date.today().isoformat()
    save_universe_snapshot(rows, snapshot_date, DB_PATH)
    print(f"✅ Saved {len(rows)} rows to universe_cache (snapshot: {snapshot_date}).")

    clear_old_snapshots(keep_last_n=30, db_path=DB_PATH)
    print("Old snapshots beyond the last 30 cleaned up.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Refresh the QuantEdge wide-scan universe cache.")
    parser.add_argument("--max-tickers", type=int, default=1000,
                         help="Number of tickers to fetch fundamentals for (default: 1000).")
    parser.add_argument("--exchange", type=str, default="US",
                         help="EODHD exchange code (default: US).")
    args = parser.parse_args()
    main(max_tickers=args.max_tickers, exchange=args.exchange)
