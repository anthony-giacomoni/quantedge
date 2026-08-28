# ============================================================
#  QuantEdge — Market Data (EODHD primary, yfinance fallback)
#  Compatible Python 3.8
# ============================================================

from typing import Optional, Dict, List
import os
import pandas as pd

import yfinance as yf

# Use EODHD if key available, else yfinance — for PRICE data only.
# Fundamentals (name, sector, P/E, EV/EBITDA, revenue, short interest) always
# go through yfinance below: EODHD's 'fundamentals' endpoint returns 403 on
# the All-World plan (it requires the separate Fundamentals Data Feed or
# All-In-One plan), while EOD/real-time price endpoints work fine on it.
EODHD_KEY = os.getenv("EODHD_API_KEY")


def get_fundamentals(ticker: str) -> Dict:
    """
    Fondamentaux via yfinance (gratuit, pas de restriction de plan) — noms de
    clés alignés sur ce qu'EODHD renvoyait, pour que le reste du code (screener,
    ai_analysis) n'ait rien à changer.
    """
    try:
        info = yf.Ticker(ticker).info
    except Exception:
        return {}
    if not info:
        return {}
    return {
        "name":             info.get("longName", ticker),
        "sector":           info.get("sector", "N/A"),
        "industry":         info.get("industry", "N/A"),
        "market_cap":       info.get("marketCap"),
        "pe_ratio":         info.get("trailingPE"),
        "forward_pe":       info.get("forwardPE"),
        "ev_ebitda":        info.get("enterpriseToEbitda"),
        "price_to_book":    info.get("priceToBook"),
        "price_to_sales":   info.get("priceToSalesTrailing12Months"),
        "revenue":          info.get("totalRevenue"),
        "revenue_growth":   info.get("revenueGrowth"),
        "profit_margin":    info.get("profitMargins"),
        "return_on_equity": info.get("returnOnEquity"),
        "short_pct":        info.get("shortPercentOfFloat"),
        "description":      (info.get("longBusinessSummary") or "")[:500],
    }


def get_ticker_info(ticker: str) -> Dict:
    """Alias for get_fundamentals — used by ai_analysis and screener."""
    f = get_fundamentals(ticker)
    return {
        "name":            f.get("name", ticker),
        "sector":          f.get("sector", "N/A"),
        "short_pct_float": f.get("short_pct"),
        "pe_ratio":        f.get("pe_ratio"),
        "ev_ebitda":       f.get("ev_ebitda"),
        "revenue":         f.get("revenue"),
    }


if EODHD_KEY:
    from utils.eodhd import (
        get_current_price,
        get_drawdown_from_ath,
        get_5d_return,
        get_ath,
        get_eod_history,
        get_usd_eur_rate,
        get_exchange_tickers,
    )
    import utils.eodhd as _eodhd_module

    def get_last_error() -> Optional[str]:
        """Retourne le dernier message d'erreur EODHD (403, 401, etc.), ou None."""
        return _eodhd_module.LAST_ERROR

    def is_stale_price() -> bool:
        """True si le dernier prix récupéré vient de la clôture (pas temps réel)."""
        return _eodhd_module.IS_STALE_PRICE

    def get_last_quote_debug() -> dict:
        """Détail brut du dernier appel get_current_price (diagnostic)."""
        return _eodhd_module.LAST_QUOTE_DEBUG

    def get_price_history_df(ticker: str, years: int = 5) -> Optional[pd.DataFrame]:
        """
        Historique OHLCV unifié (colonnes: Open/High/Low/Close/Volume, index
        DatetimeIndex), quelle que soit la source sous-jacente. Utilisé par
        le screener pour calculer drawdown/volatilité/spike sans dépendre
        directement d'EODHD ou de yfinance.
        """
        raw = get_eod_history(ticker, years=years)
        if not raw or not isinstance(raw, list):
            return None
        try:
            df = pd.DataFrame(raw)
            df = df.rename(columns={
                "date": "Date", "open": "Open", "high": "High",
                "low": "Low", "close": "Close", "volume": "Volume",
            })
            df["Date"] = pd.to_datetime(df["Date"])
            df = df.set_index("Date").sort_index()
            for col in ["Open", "High", "Low", "Close", "Volume"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            return df.dropna(subset=["Close"])
        except Exception:
            return None

    def funnel_screen(tickers, min_market_cap: float = 1_000_000_000, progress_callback=None) -> List[str]:
        """
        Entonnoir de filtrage en cascade sur market cap, via yfinance
        (get_fundamentals ne dépend plus d'EODHD — voir plus haut).
        """
        survivors = []
        total = len(tickers)
        for i, ticker in enumerate(tickers):
            if progress_callback:
                progress_callback(i / total, f"[{i+1}/{total}] Checking {ticker}...")
            fund = get_fundamentals(ticker)
            if not fund or fund.get("market_cap") is None:
                continue
            try:
                if float(fund["market_cap"]) < min_market_cap:
                    continue
            except (TypeError, ValueError):
                continue
            survivors.append(ticker)
        return survivors

    DATA_SOURCE = "EODHD"
else:
    def get_last_error() -> Optional[str]:
        return None

    def is_stale_price() -> bool:
        return False

    def get_last_quote_debug() -> dict:
        return {}

    def get_usd_eur_rate() -> Optional[float]:
        return None

    def get_exchange_tickers(exchange: str = "US", instrument_type: str = "common_stock") -> List[str]:
        return []

    def funnel_screen(tickers, min_market_cap=1_000_000_000, progress_callback=None) -> List[str]:
        survivors = []
        total = len(tickers)
        for i, ticker in enumerate(tickers):
            if progress_callback:
                progress_callback(i / total, f"[{i+1}/{total}] Checking {ticker}...")
            fund = get_fundamentals(ticker)
            if not fund or fund.get("market_cap") is None:
                continue
            try:
                if float(fund["market_cap"]) < min_market_cap:
                    continue
            except (TypeError, ValueError):
                continue
            survivors.append(ticker)
        return survivors

    # yfinance fallback (prix aussi, si pas de clé EODHD du tout)
    import time
    DATA_SOURCE = "yfinance"

    def get_price_history_df(ticker: str, years: int = 5) -> Optional[pd.DataFrame]:
        """Historique OHLCV unifié via yfinance (même contrat que la branche EODHD)."""
        try:
            hist = yf.Ticker(ticker).history(period=f"{years}y")
            if hist.empty:
                return None
            return hist
        except Exception:
            return None

    def get_current_price(ticker: str) -> Optional[float]:
        try:
            hist = yf.Ticker(ticker).history(period="2d")
            if not hist.empty:
                return round(float(hist["Close"].iloc[-1]), 4)
        except Exception:
            pass
        return None

    def get_drawdown_from_ath(ticker: str) -> Optional[Dict]:
        try:
            hist = yf.Ticker(ticker).history(period="5y")
            if hist.empty:
                return None
            ath     = float(hist["High"].max())
            current = float(hist["Close"].iloc[-1])
            return {"ath": round(ath,4), "current": round(current,4),
                    "drawdown_pct": round((current-ath)/ath,4)}
        except Exception:
            pass
        return None

    def get_5d_return(ticker: str) -> Optional[float]:
        try:
            hist = yf.Ticker(ticker).history(period="10d")
            if len(hist) < 2:
                return None
            p_now = float(hist["Close"].iloc[-1])
            p_5d  = float(hist["Close"].iloc[-5]) if len(hist)>=5 else float(hist["Close"].iloc[0])
            return round((p_now-p_5d)/p_5d, 4)
        except Exception:
            pass
        return None

    def get_ath(ticker: str, years: int = 5) -> Optional[float]:
        try:
            hist = yf.Ticker(ticker).history(period=f"{years}y")
            if not hist.empty:
                return round(float(hist["High"].max()), 4)
        except Exception:
            pass
        return None


def compute_open_pnl(ticker: str, entry_price: float,
                     qty: float, direction: str = "LONG") -> Optional[Dict]:
    price = get_current_price(ticker)
    if price is None or qty is None:
        return None
    pnl = (price-entry_price)*qty if direction=="LONG" else (entry_price-price)*qty
    pct = (price-entry_price)/entry_price if direction=="LONG" else (entry_price-price)/entry_price
    return {"current_price": price, "pnl": round(pnl,2), "pnl_pct": round(pct,4)}
