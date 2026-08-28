# ============================================================
#  QuantEdge — Gestion de la base de données SQLite
# ============================================================

import sqlite3
import pandas as pd
from pathlib import Path


def get_connection(db_path: str = "data/quantedge.db") -> sqlite3.Connection:
    """Retourne une connexion SQLite. Crée le dossier si nécessaire."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  # accès par nom de colonne
    return conn


def init_database(db_path: str = "data/quantedge.db"):
    """Crée les tables si elles n'existent pas encore."""
    conn = get_connection(db_path)
    c = conn.cursor()

    # Table des trades
    c.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker          TEXT    NOT NULL,
            direction       TEXT    NOT NULL DEFAULT 'LONG',  -- LONG ou SHORT
            qty             REAL,
            entry_price     REAL    NOT NULL,
            entry_date      TEXT    NOT NULL,
            exit_price      REAL,
            exit_date       TEXT,
            pnl             REAL,
            invested        REAL,
            status          TEXT    NOT NULL DEFAULT 'OPEN',  -- OPEN ou CLOSED
            sector          TEXT,
            notes           TEXT,
            created_at      TEXT    DEFAULT (datetime('now'))
        )
    """)

    # Table de la watchlist personnalisée
    c.execute("""
        CREATE TABLE IF NOT EXISTS watchlist (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker      TEXT    NOT NULL UNIQUE,
            sector      TEXT,
            notes       TEXT,
            added_at    TEXT    DEFAULT (datetime('now'))
        )
    """)

    # Table des analyses IA sauvegardées
    c.execute("""
        CREATE TABLE IF NOT EXISTS ai_analyses (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker      TEXT    NOT NULL,
            analysis    TEXT    NOT NULL,
            model       TEXT,
            created_at  TEXT    DEFAULT (datetime('now'))
        )
    """)

    # Cache de l'univers scanné pour le Wide Scan (Opportunities).
    # Chaque exécution de refresh_universe.py ajoute une nouvelle "snapshot_date"
    # sans écraser les précédentes -> historique consultable dans le temps.
    c.execute("""
        CREATE TABLE IF NOT EXISTS universe_cache (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_date     TEXT    NOT NULL,
            ticker            TEXT    NOT NULL,
            name              TEXT,
            sector            TEXT,
            industry          TEXT,
            market_cap        REAL,
            pe_ratio          REAL,
            revenue           REAL,
            close_price       REAL,
            high_52w          REAL,
            low_52w           REAL,
            created_at        TEXT    DEFAULT (datetime('now'))
        )
    """)
    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_universe_cache_snapshot
        ON universe_cache (snapshot_date)
    """)
    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_universe_cache_ticker
        ON universe_cache (ticker)
    """)

    conn.commit()
    conn.close()
    print("✅ Base de données initialisée.")


def load_trades(db_path: str = "data/quantedge.db") -> pd.DataFrame:
    """Charge tous les trades depuis la DB."""
    conn = get_connection(db_path)
    df = pd.read_sql_query("SELECT * FROM trades ORDER BY entry_date DESC", conn)
    conn.close()
    return df


def insert_trade(trade: dict, db_path: str = "data/quantedge.db"):
    """Insère un trade. trade = dict avec les champs de la table."""
    conn = get_connection(db_path)
    c = conn.cursor()
    c.execute("""
        INSERT INTO trades
            (ticker, direction, qty, entry_price, entry_date,
             exit_price, exit_date, pnl, invested, status, sector, notes)
        VALUES
            (:ticker, :direction, :qty, :entry_price, :entry_date,
             :exit_price, :exit_date, :pnl, :invested, :status, :sector, :notes)
    """, trade)
    conn.commit()
    conn.close()


def trades_already_loaded(db_path: str = "data/quantedge.db") -> bool:
    """Vérifie si des trades sont déjà en base (pour éviter le double import)."""
    conn = get_connection(db_path)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM trades")
    count = c.fetchone()[0]
    conn.close()
    return count > 0


# ============================================================
#  UNIVERSE CACHE — snapshots pour le Wide Scan (Opportunities)
# ============================================================

def save_universe_snapshot(rows: list, snapshot_date: str, db_path: str = "data/quantedge.db"):
    """
    Enregistre une snapshot du filtre grossier (market cap, secteur, etc.)
    pour une date donnée. N'écrase pas les snapshots précédentes -> historique.
    rows: liste de dicts avec les clés ticker/name/sector/industry/market_cap/
          pe_ratio/revenue/close_price/high_52w/low_52w.
    """
    conn = get_connection(db_path)
    c = conn.cursor()
    for row in rows:
        row_full = {
            "snapshot_date": snapshot_date,
            "high_52w": None,
            "low_52w": None,
            **row,
        }
        c.execute("""
            INSERT INTO universe_cache
                (snapshot_date, ticker, name, sector, industry,
                 market_cap, pe_ratio, revenue, close_price, high_52w, low_52w)
            VALUES
                (:snapshot_date, :ticker, :name, :sector, :industry,
                 :market_cap, :pe_ratio, :revenue, :close_price, :high_52w, :low_52w)
        """, row_full)
    conn.commit()
    conn.close()


def get_latest_snapshot_date(db_path: str = "data/quantedge.db") -> str:
    """Retourne la date de la snapshot la plus récente, ou None si aucune."""
    conn = get_connection(db_path)
    c = conn.cursor()
    c.execute("SELECT MAX(snapshot_date) FROM universe_cache")
    row = c.fetchone()
    conn.close()
    return row[0] if row and row[0] else None


def load_universe_snapshot(snapshot_date: str = None, db_path: str = "data/quantedge.db") -> pd.DataFrame:
    """
    Charge une snapshot du cache univers. Si snapshot_date est None,
    charge la plus récente disponible. Retourne un DataFrame vide si
    aucune snapshot n'existe encore (le cache n'a jamais été rempli).
    """
    conn = get_connection(db_path)
    if snapshot_date is None:
        snapshot_date = get_latest_snapshot_date(db_path)
    if snapshot_date is None:
        conn.close()
        return pd.DataFrame()
    df = pd.read_sql_query(
        "SELECT * FROM universe_cache WHERE snapshot_date = ?",
        conn, params=(snapshot_date,)
    )
    conn.close()
    return df


def clear_old_snapshots(keep_last_n: int = 30, db_path: str = "data/quantedge.db"):
    """
    Supprime les snapshots au-delà des N dernières, pour éviter que la DB
    grossisse indéfiniment. À appeler périodiquement (ex: à chaque refresh).
    """
    conn = get_connection(db_path)
    c = conn.cursor()
    c.execute("SELECT DISTINCT snapshot_date FROM universe_cache ORDER BY snapshot_date DESC")
    dates = [r[0] for r in c.fetchall()]
    to_delete = dates[keep_last_n:]
    if to_delete:
        placeholders = ",".join("?" * len(to_delete))
        c.execute(f"DELETE FROM universe_cache WHERE snapshot_date IN ({placeholders})", to_delete)
        conn.commit()
    conn.close()
