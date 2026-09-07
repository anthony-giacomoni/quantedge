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
            instrument_type TEXT    NOT NULL DEFAULT 'DIRECT',
            marking_ticker  TEXT,
            created_at      TEXT    DEFAULT (datetime('now'))
        )
    """)

    # Idempotent schema migration for reference/underlying vs traded instrument semantics.
    trade_cols = {row[1] for row in c.execute("PRAGMA table_info(trades)").fetchall()}
    if "instrument_type" not in trade_cols:
        c.execute("ALTER TABLE trades ADD COLUMN instrument_type TEXT NOT NULL DEFAULT 'DIRECT'")
    if "marking_ticker" not in trade_cols:
        c.execute("ALTER TABLE trades ADD COLUMN marking_ticker TEXT")

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
            prompt      TEXT,
            prompt_hash TEXT,
            system_prompt TEXT,
            system_prompt_hash TEXT,
            max_tokens INTEGER,
            created_at  TEXT    DEFAULT (datetime('now'))
        )
    """)

    # Idempotent migration for databases created before prompt provenance was stored.
    ai_cols = {row[1] for row in c.execute("PRAGMA table_info(ai_analyses)").fetchall()}
    if "prompt" not in ai_cols:
        c.execute("ALTER TABLE ai_analyses ADD COLUMN prompt TEXT")
    if "prompt_hash" not in ai_cols:
        c.execute("ALTER TABLE ai_analyses ADD COLUMN prompt_hash TEXT")
    if "system_prompt" not in ai_cols:
        c.execute("ALTER TABLE ai_analyses ADD COLUMN system_prompt TEXT")
    if "system_prompt_hash" not in ai_cols:
        c.execute("ALTER TABLE ai_analyses ADD COLUMN system_prompt_hash TEXT")
    if "max_tokens" not in ai_cols:
        c.execute("ALTER TABLE ai_analyses ADD COLUMN max_tokens INTEGER")

    # Cache optionnel pour les scans larges/offline. Une relance le même jour
    # remplace la snapshot de cette date afin d'éviter les doublons.
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

    # Idempotent data migration: older builds mislabeled Siemens Energy as SIE.DE
    # (Siemens AG). Only rows explicitly tagged Siemens Energy are changed.
    c.execute("""
        UPDATE trades
        SET ticker = 'ENR.DE'
        WHERE ticker = 'SIE.DE'
          AND lower(COALESCE(notes, '')) LIKE '%siemens energy%'
    """)

    # Idempotent metadata migration: Estée Lauder is Consumer, not Healthcare Tech.
    c.execute("""
        UPDATE trades
        SET sector = 'Consumer'
        WHERE ticker = 'EL'
          AND entry_date = '2025-06-24'
          AND lower(COALESCE(notes, '')) LIKE '%estee lauder%'
    """)

    # Idempotent taxonomy migration: use one consistent English sector vocabulary.
    sector_updates = {
        "Energie": "Energy",
        "Semiconducteurs": "Semiconductors",
        "Défense": "Defence",
        "Healthcare Tech": "Healthcare",
        "Autre": "Consumer",
        "Tech": "Technology",
        "Finance": "Financials",
    }
    for old_sector, new_sector in sector_updates.items():
        c.execute("UPDATE trades SET sector = ? WHERE sector = ?", (new_sector, old_sector))
    c.execute("UPDATE trades SET sector = 'Communication Services' WHERE ticker = 'NFLX'")
    c.execute("UPDATE trades SET sector = 'Financials' WHERE ticker = 'PYPL'")

    # Reference-ticker rows where the broker execution belonged to a wrapper/product.
    # These rows remain analytically useful but must never be live-marked from the underlying.
    for ref_ticker, entry_date in [
        ("IWM", "2025-06-19"),
        ("UNH", "2025-07-24"),
        ("BZ=F", "2025-07-29"),
        ("XLE", "2026-02-25"),
    ]:
        c.execute(
            "UPDATE trades SET instrument_type='WRAPPER', marking_ticker=NULL "
            "WHERE ticker=? AND entry_date=?",
            (ref_ticker, entry_date),
        )

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
    """Insert one strategy-sample row with explicit instrument-marking semantics."""
    payload = dict(trade)
    payload.setdefault("instrument_type", "DIRECT")
    payload.setdefault("marking_ticker", None)
    conn = get_connection(db_path)
    c = conn.cursor()
    c.execute("""
        INSERT INTO trades
            (ticker, direction, qty, entry_price, entry_date,
             exit_price, exit_date, pnl, invested, status, sector, notes,
             instrument_type, marking_ticker)
        VALUES
            (:ticker, :direction, :qty, :entry_price, :entry_date,
             :exit_price, :exit_date, :pnl, :invested, :status, :sector, :notes,
             :instrument_type, :marking_ticker)
    """, payload)
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
#  UNIVERSE CACHE — snapshots pour scans larges/offline
# ============================================================

def save_universe_snapshot(rows: list, snapshot_date: str, db_path: str = "data/quantedge.db"):
    """
    Enregistre une snapshot du filtre grossier pour une date donnée.
    Une relance le même jour remplace cette date (idempotence) sans dupliquer les lignes.
    rows: liste de dicts avec les clés ticker/name/sector/industry/market_cap/
          pe_ratio/revenue/close_price/high_52w/low_52w.
    """
    conn = get_connection(db_path)
    c = conn.cursor()
    c.execute("DELETE FROM universe_cache WHERE snapshot_date = ?", (snapshot_date,))
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


def save_ai_analysis(
    ticker: str, analysis: str, model: str, db_path: str = "data/quantedge.db",
    prompt: str = None, system_prompt: str = None, max_tokens: int = None,
) -> None:
    """Persist a successful AI analysis with user+system prompt provenance."""
    import hashlib

    prompt_text = None if prompt is None else str(prompt)
    system_text = None if system_prompt is None else str(system_prompt)
    prompt_hash = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest() if prompt_text is not None else None
    system_hash = hashlib.sha256(system_text.encode("utf-8")).hexdigest() if system_text is not None else None
    conn = get_connection(db_path)
    try:
        conn.execute(
            "INSERT INTO ai_analyses "
            "(ticker, analysis, model, prompt, prompt_hash, system_prompt, system_prompt_hash, max_tokens) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (ticker, analysis, model, prompt_text, prompt_hash, system_text, system_hash, max_tokens),
        )
        conn.commit()
    finally:
        conn.close()


def load_ai_analysis_history(limit: int = 20, db_path: str = "data/quantedge.db") -> pd.DataFrame:
    """Return metadata for recent successfully persisted analyses."""
    conn = get_connection(db_path)
    try:
        return pd.read_sql_query(
            "SELECT ticker, model, prompt_hash, system_prompt_hash, max_tokens, created_at FROM ai_analyses "
            "ORDER BY created_at DESC LIMIT ?",
            conn,
            params=(int(limit),),
        )
    finally:
        conn.close()
