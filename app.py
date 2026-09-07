# ============================================================
#  QuantEdge — Dashboard principal (Streamlit)
#  Lancement : streamlit run app.py
# ============================================================

import streamlit as st
import pandas as pd
import sys, os
import sqlite3

from utils.runtime import configure_runtime
configure_runtime()

from dotenv import load_dotenv
load_dotenv()

# Chemin absolu pour les imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.db import (
    init_database, trades_already_loaded, save_ai_analysis, load_ai_analysis_history, load_trades
)
from utils.seed_trades import seed
from modules.portfolio import (
    load_enriched_trades,
    compute_stats,
    build_cumulative_realised_pnl,
    build_pnl_bars,
    build_sector_pie,
    format_trades_table,
)
from config import DB_PATH, CLAUDE_MODEL, CLAUDE_MAX_TOKENS
from utils.market_data import get_last_error
from modules.ai_analysis import SYSTEM_DATA_INTEGRITY

# ── Config Streamlit ──────────────────────────────────────────
st.set_page_config(
    page_title="QuantEdge",
    page_icon="▲",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS professionnel ────────────────────────────────────────
import pathlib
css_path = pathlib.Path(__file__).parent / "assets" / "style.css"
if css_path.exists():
    st.markdown(f"<style>{css_path.read_text()}</style>", unsafe_allow_html=True)


# ── Init base de données ──────────────────────────────────────
# init_database() est toujours appelée (pas de cache) car elle utilise
# CREATE TABLE IF NOT EXISTS : ça ne coûte rien de la rappeler à chaque
# lancement, et ça garantit que les nouvelles tables (ex: universe_cache)
# sont bien créées même sur une DB existante, sans devoir vider le cache
# Streamlit manuellement après une mise à jour du code.
init_database(DB_PATH)

@st.cache_resource
def setup_seed():
    if not trades_already_loaded(DB_PATH):
        seed(DB_PATH)
    return True

setup_seed()


# ── Sidebar ───────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## QUANTEDGE")
    st.markdown("**Anthony Giacomoni**")
    st.markdown("MSc Finance · EDHEC")
    st.divider()

    page = st.radio(
        "Navigation",
        ["Trading", "DCA", "AI Analysis", "News"],
        index=0,
    )
    st.divider()
    if st.button("↺ Rerun", use_container_width=True):
        st.rerun()
    st.caption("Click Rerun to fetch the latest available prices.")
    st.divider()
    st.caption("Data: EODHD (prices/news when available) · official macro calendars · yfinance (fundamentals/earnings fallback)")


# ============================================================
#  PAGE : PORTFOLIO
# ============================================================
if page == "Trading":

    st.title("Trading — Strategy-Tagged Trade Analytics")
    st.caption("Manually curated strategy-tagged trade dataset · personal analytics 2025-2026")

    # Chargement
    with st.spinner("Fetching latest available quotes..."):
        df = load_enriched_trades(DB_PATH)

    if df.empty:
        st.warning("No trades found. Restart the app.")
        st.stop()

    # Alert if the latest available quote for an open position could not be retrieved
    open_missing_price = df[(df["status"] == "OPEN") & (df["current_price"].isna())]
    if not open_missing_price.empty:
        last_err = get_last_error()
        tickers_str = ", ".join(open_missing_price["ticker"].tolist())
        msg = f"Latest quote unavailable for: **{tickers_str}** — P&L is not refreshed for those positions."
        if last_err:
            msg += f"\n\n`{last_err}`"
        st.warning(msg)

    # Price and FX freshness are tracked per position and evaluated against
    # that listing's representative market calendar, not a US-only clock.
    stale_col = "pricing_stale" if "pricing_stale" in df.columns else "quote_stale"
    stale_open = df[(df["status"] == "OPEN") & (df[stale_col] == True)]
    if not stale_open.empty:
        from modules.screener import get_market_status
        from utils.market_data import is_ticker_market_open

        market_status = get_market_status()
        stale_while_open = []
        stale_while_closed = []
        stale_unknown_status = []
        for r in stale_open.itertuples():
            quote_src = getattr(r, "quote_source", None) or "unknown quote source"
            fx_src = getattr(r, "fx_source", None)
            fx_stale = bool(getattr(r, "fx_stale", False))
            detail = f"{r.ticker} ({quote_src}" + (f", FX: {fx_src}" if fx_stale and fx_src else "") + ")"
            listing_open = is_ticker_market_open(r.ticker, market_status.get("minute_utc"))
            if listing_open is True:
                stale_while_open.append(detail)
            elif listing_open is False:
                stale_while_closed.append(detail)
            else:
                stale_unknown_status.append(detail)

        if stale_while_closed:
            st.info(
                "ℹ️ Relevant market closed — unrealised P&L uses the latest available mark for "
                + ", ".join(stale_while_closed) + "."
            )
        if stale_while_open:
            st.warning(
                "⚠️ Stale price/FX input detected while the relevant market is open for: "
                + ", ".join(stale_while_open) +
                ". P&L may not reflect the latest available market price."
            )
        if stale_unknown_status:
            st.warning(
                "⚠️ Stale pricing input with unavailable listing-calendar status for: "
                + ", ".join(stale_unknown_status) + "."
            )

    stats = compute_stats(df)

    if stats and not stats.get("closed_pnl_complete", True):
        st.error(
            "Closed-dataset metrics unavailable: "
            f"{stats.get('closed_positions_missing_pnl', 0)} closed trade(s) have no recorded broker P&L. "
            "Win rate, closed P&L and derived statistics are hidden until the record is complete."
        )

    # ── KPIs principaux ───────────────────────────────────────
    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        pnl = stats.get("total_pnl")
        if pnl is None:
            st.metric("Closed P&L", "N/A")
        else:
            st.metric("Closed P&L", f"+{pnl:.2f}€" if pnl >= 0 else f"{pnl:.2f}€")

    with col2:
        win_rate = stats.get("win_rate")
        st.metric("Dataset Win Rate", "N/A" if win_rate is None else f"{win_rate:.1f}%")

    with col3:
        st.metric("Closed Samples", f"{stats.get('closed_trades', 0)}")

    with col4:
        best_trade = stats.get("best_trade")
        st.metric("Best Trade", "N/A" if best_trade is None else f"{best_trade:+.2f}€")

    with col5:
        open_pnl = stats.get("open_pnl")
        open_complete = stats.get("open_pnl_complete", True)
        open_priced = stats.get("open_positions_priced", 0)
        open_total = stats.get("open_trades", 0)
        if open_pnl is None:
            sign, color, arrow, pnl_text = "", "#94a3b8", "", "N/A"
        else:
            sign = "+" if open_pnl >= 0 else ""
            color = "#ef4444" if open_pnl < 0 else "#22c55e"
            arrow = "↓" if open_pnl < 0 else "↑"
            pnl_text = f"{arrow} {sign}{open_pnl:.2f}€"
        st.markdown(
            f"""
            <div style="
                background: #13131f;
                border: 1px solid #1e1e35;
                border-radius: 6px;
                padding: 1rem 1.25rem;
            ">
                <div style="font-size:0.65rem; font-weight:600; text-transform:uppercase;
                            letter-spacing:0.1em; color:#334155; margin-bottom:0.3rem;">
                    Unrealised P&L{' (partial)' if not open_complete else ''}
                </div>
                <div style="font-size:1.4rem; font-weight:700; color:{color};
                            font-family:'JetBrains Mono', monospace;">
                    {pnl_text}
                </div>
                <div style="font-size:0.72rem; color:#64748b; margin-top:0.2rem;">
                    {open_priced}/{open_total} positions priced
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.divider()

    # ── Statistiques détaillées ───────────────────────────────
    with st.expander("Advanced Statistics", expanded=False):
        c1, c2, c3, c4 = st.columns(4)
        def _eur_metric(value, signed=False):
            if value is None:
                return "N/A"
            return f"{value:+.2f}€" if signed else f"{value:.2f}€"

        c1.metric("Avg. Win", _eur_metric(stats.get("avg_win"), signed=True))
        c2.metric("Avg. Loss", _eur_metric(stats.get("avg_loss")))
        pf = stats.get("profit_factor")
        c3.metric("Dataset Profit Factor", "N/A" if pf is None else f"{pf:.2f}x")
        avg_hold = stats.get("avg_duration_days")
        c4.metric(
            "Avg. Hold",
            "N/A" if avg_hold is None else f"{avg_hold:.0f} days",
        )
        c1.metric("Best Closed Sample", _eur_metric(stats.get("best_trade"), signed=True))
        c2.metric("Worst Trade", _eur_metric(stats.get("worst_trade")))
        c3.metric("Winning Trades", "N/A" if stats.get("wins") is None else stats.get("wins"))
        c4.metric("Losing Trades", "N/A" if stats.get("losses") is None else stats.get("losses"))

        open_inputs = df[df["status"] == "OPEN"].copy()
        if not open_inputs.empty:
            st.markdown("**Open-position pricing inputs**")
            pricing_cols = [
                "ticker", "current_price_native", "quote_currency", "pnl_native", "pnl_native_currency", "quote_source",
                "quote_timestamp", "quote_stale", "fx_to_eur", "fx_source",
                "fx_timestamp", "fx_stale", "fx_fallback_reason", "pricing_error",
            ]
            pricing = open_inputs[[c for c in pricing_cols if c in open_inputs.columns]].copy()
            pricing = pricing.rename(columns={
                "ticker": "Ticker", "current_price_native": "Native price",
                "quote_currency": "Currency", "pnl_native": "Native P&L", "pnl_native_currency": "P&L currency", "quote_source": "Quote source",
                "quote_timestamp": "Quote timestamp", "quote_stale": "Quote stale",
                "fx_to_eur": "FX→EUR", "fx_source": "FX source",
                "fx_timestamp": "FX timestamp", "fx_stale": "FX stale",
                "fx_fallback_reason": "FX fallback", "pricing_error": "Pricing error",
            })
            st.dataframe(pricing, use_container_width=True, hide_index=True)

    # ── Cumulative realised P&L ───────────────────────────────
    st.subheader("Cumulative Realised P&L")
    fig_eq = build_cumulative_realised_pnl(df)
    st.plotly_chart(fig_eq, use_container_width=True)

    # ── P&L bars + Secteur ────────────────────────────────────
    col_left, col_right = st.columns([2, 1])
    with col_left:
        st.subheader("P&L per Trade")
        fig_bars = build_pnl_bars(df)
        st.plotly_chart(fig_bars, use_container_width=True)
    with col_right:
        st.subheader("Net Realised P&L by Sector")
        fig_pie = build_sector_pie(df)
        st.plotly_chart(fig_pie, use_container_width=True)

    st.divider()

    # ── Tableau des trades ────────────────────────────────────
    st.subheader("All Trades")

    # Filtres
    f1, f2, f3 = st.columns(3)
    with f1:
        statut_filter = st.multiselect("Status", ["OPEN", "CLOSED"], default=["OPEN", "CLOSED"])
    with f2:
        sector_filter = st.multiselect("Sector", df["sector"].dropna().unique().tolist(),
                                        default=df["sector"].dropna().unique().tolist())
    with f3:
        direction_filter = st.multiselect("Direction", ["LONG", "SHORT"], default=["LONG", "SHORT"])

    filtered = df[
        df["status"].isin(statut_filter) &
        df["sector"].isin(sector_filter) &
        df["direction"].isin(direction_filter)
    ]

    table = format_trades_table(filtered)

    # Coloration P&L
    def color_pnl(val):
        if pd.isna(val):
            return "color: #f59e0b"  # amber pour ouvert
        return "color: #22c55e" if val >= 0 else "color: #ef4444"

    st.dataframe(table, use_container_width=True, hide_index=True, height=500)
    st.caption(
        "Reference / Underlying identifies the market exposure used for analytics. "
        "Recorded Entry/Exit are the trade-record instrument prices; for leveraged or derivative "
        "exposures they are not necessarily the underlying share price. Realised P&L is the broker-record value."
    )


# ============================================================
#  APPLICATION PAGES
# ============================================================
elif page == "DCA":
    st.title("DCA — Long Term Portfolio")
    st.caption("Long-term portfolio · ETFs & equities · cash-flow-aware performance")

    from modules.dca import (
        load_excel, compute_global_stats, get_file_info,
        build_evolution_curve, build_etf_evolution,
        build_projection, build_allocation_donut, get_all_produits,
        resolve_dca_source, DCADataError, save_uploaded_workbook, reconcile_latest_snapshot
    )
    import os

    # ── Upload ou fichier existant ───────────────────────────
    with st.sidebar:
        st.divider()
        st.markdown("**DCA File**")
        uploaded = st.file_uploader("Import DCA workbook", type=["xlsm", "xlsx"])
        if uploaded:
            try:
                save_uploaded_workbook(uploaded.getvalue(), uploaded.name)
            except DCADataError as exc:
                st.error(f"Import rejected; existing workbook was preserved: {exc}")
            else:
                st.success("✅ Workbook validated and imported")

    data_path, data_mode = resolve_dca_source()
    if data_path is None:
        st.warning("No DCA workbook found. Import `simu_invest.xlsm` from the sidebar.")
        st.stop()

    info = get_file_info(data_path)
    is_demo = data_mode == "demo"
    file_label = "anonymised demo dataset" if is_demo else f"personal {os.path.basename(data_path)}"
    if is_demo:
        st.info(
            "Demo mode — no private workbook is present. The figures below are the "
            "anonymised repository example, not your portfolio."
        )
    else:
        st.success("Personal DCA workbook loaded.")
    st.caption(f"📄 `{file_label}` — last modified: {info['modified']} · {info['size_kb']} KB")

    try:
        with st.spinner("Reading Excel file..."):
            df_dca = load_excel(data_path)
    except DCADataError as exc:
        st.error(f"Unable to read DCA data: {exc}")
        st.stop()

    stats = compute_global_stats(df_dca)

    # ── KPIs ─────────────────────────────────────────────────
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total Invested", f"{stats['total_inv']:,.0f}€")
    k2.metric("Current Value", f"{stats['total_val']:,.0f}€")
    k3.metric("Total P&L", f"{stats['pnl']:+,.0f}€")
    k4.metric("Money-weighted Return (XIRR)", f"{stats['xirr']*100:+.1f}%" if stats.get("xirr") is not None else "N/A")

    st.divider()

    # ── Courbe principale ─────────────────────────────────────
    st.subheader("Portfolio Growth")
    fig_evol = build_evolution_curve(df_dca)
    st.plotly_chart(fig_evol, use_container_width=True)

    # ── Allocation + Stats ────────────────────────────────────
    col_left, col_right = st.columns([1, 1])
    with col_left:
        fig_donut = build_allocation_donut(df_dca)
        st.plotly_chart(fig_donut, use_container_width=True)
    with col_right:
        st.subheader("Statistics")
        st.metric("DCA Duration", f"{stats['duree_mois']:.0f} mois")
        st.metric("Portfolio Snapshots", stats['n_observations'])

        st.metric("Value/Invested Ratio", f"{stats['ratio_val_inv']:.2f}x")
        st.caption(f"Période : {stats['date_debut']} → {stats['date_fin']}")
        reconciliation = reconcile_latest_snapshot(df_dca)
        if reconciliation.get("reconciled"):
            st.caption("Latest allocation reconciles to total portfolio value.")
        else:
            residual = reconciliation.get("residual")
            st.warning(
                "Latest product allocation does not fully reconcile to total portfolio value"
                + (f" (residual {residual:+,.2f}€)." if residual is not None else ".")
                + " Product-level analytics may be incomplete until the workbook mapping is updated."
            )

    st.divider()

    # ── ETF individuel ────────────────────────────────────────
    st.subheader("Product Position Value")
    tous_produits = get_all_produits(df_dca)
    produit_sel = st.selectbox("Select product", tous_produits)
    if produit_sel:
        from modules.dca import get_produit_stats
        col_map = {
            "iShares S&P 500 Acc":           "sp500_val",
            "iShares NASDAQ 100 Acc":         "nasdaq_val",
            "HSBC MSCI Emerging Markets Acc": "em_val",
            "VanEck Defense Acc":             "defense_val",
        }
        col_name = col_map.get(produit_sel, produit_sel)
        fig_etf = build_etf_evolution(df_dca, col_name)
        st.plotly_chart(fig_etf, use_container_width=True)

        ps = get_produit_stats(df_dca, produit_sel, excel_path=data_path)
        if ps:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Invested", f"{ps['investi']:,.0f}€" if ps.get("invested_available") else "N/A")
            c2.metric(
                "Current Value",
                f"{ps['valeur']:,.0f}€"
                if ps.get("valeur") is not None
                else "N/A",
            )
            c3.metric("P&L", f"{ps['pnl']:+,.0f}€" if ps.get("pnl") is not None else "N/A")
            c4.metric("Return", f"{ps['rendement']*100:+.1f}%" if ps.get("rendement") is not None else "N/A")
            if not ps.get("invested_available"):
                st.warning(ps.get("error") or "Invested amount unavailable for this product.")
            else:
                st.caption("Invested amount is reconciled against the workbook dashboard; no market-value fallback is used.")

    st.divider()

    # ── Projection ────────────────────────────────────────────
    st.subheader("Long-Term Projection")
    col_p1, col_p2 = st.columns(2)
    with col_p1:
        versement_proj = st.number_input(
            "Monthly contribution (€)", min_value=0, max_value=10000,
            value=int(stats['avg_monthly_contribution']), step=50,
        )
        st.caption("Prefilled from subsequent contributions only (initial funded capital excluded); edit it for your intended future contribution.")
    with col_p2:
        horizons = st.multiselect(
            "Horizons", [5, 10, 15, 20, 25, 30], default=[10, 20, 30]
        )
    if horizons:
        fig_proj = build_projection(
            total_val=stats['total_val'],
            versement_mensuel=versement_proj,
            horizons=horizons,
            current_invested=stats['total_inv'],
        )
        st.plotly_chart(fig_proj, use_container_width=True)
        taux_scenarios = [("Pessimiste 5%", 0.05), ("Base 8%", 0.08), ("Optimiste 11%", 0.11)]
        recap = {}
        for label, taux in taux_scenarios:
            taux_m = (1 + taux) ** (1/12) - 1
            row_vals = {}
            for h in sorted(horizons):
                v = stats['total_val']
                for m in range(h * 12):
                    v = v * (1 + taux_m) + versement_proj
                row_vals[f"{h} ans"] = f"{v:,.0f}€"
            recap[label] = row_vals
        st.dataframe(pd.DataFrame(recap).T, use_container_width=True)

    st.divider()
    st.caption("💡 To update: import a validated `.xlsm` or `.xlsx` workbook from the sidebar.")

    # ── AI Portfolio Analysis ─────────────────────────────────
    st.divider()
    st.subheader("AI Portfolio Analysis")

    import os as _os
    api_key_dca = _os.getenv("ANTHROPIC_API_KEY", "")

    if not api_key_dca:
        st.warning("API key not configured. Add `ANTHROPIC_API_KEY` to your `.env` file to enable AI analysis.")
    else:
        from modules.dca import build_ai_portfolio_prompt
        from modules.ai_analysis import call_claude_api

        dca_question = st.text_area(
            "Ask a question about this portfolio (optional)",
            placeholder="e.g. Is my allocation too concentrated in tech? Should I rebalance toward bonds given my horizon?",
            height=80,
            key="dca_ai_question",
        )

        if data_mode == "personal":
            st.caption("Privacy: clicking Run AI Analysis sends the displayed portfolio holdings/amounts and prompt to the Anthropic API. Nothing is sent until you click the button; successful responses are saved only in the local QuantEdge database.")
        else:
            st.caption("Clicking Run AI Analysis sends the anonymised demo figures and prompt to the Anthropic API.")

        if st.button("Run AI Analysis", type="primary", key="dca_ai_run"):
            base_prompt = build_ai_portfolio_prompt(stats, df_dca, dataset_mode=data_mode)
            full_prompt = (
                f"{base_prompt}\n\n═══ SPECIFIC QUESTION ═══\n{dca_question}"
                if dca_question else
                f"{base_prompt}\n\n═══ SPECIFIC QUESTION ═══\nGive a general assessment of allocation, "
                f"concentration risk and diversification given the time horizon."
            )
            from modules.ai_analysis import ClaudeAPIError
            try:
                with st.spinner("Calling Claude..."):
                    dca_answer = call_claude_api(full_prompt, api_key_dca)
            except ClaudeAPIError as exc:
                st.error(f"Claude API error: {exc}")
                dca_answer = None

            if dca_answer is not None:
                st.divider()
                st.markdown(dca_answer)
                try:
                    save_ai_analysis("dca_portfolio", dca_answer, CLAUDE_MODEL, DB_PATH, prompt=full_prompt, system_prompt=SYSTEM_DATA_INTEGRITY, max_tokens=CLAUDE_MAX_TOKENS)
                except (OSError, ValueError, sqlite3.Error) as exc:
                    st.error(f"Analysis generated but could not be saved: {exc}")
                else:
                    st.caption("Saved")

                with st.expander("View prompt sent to Claude", expanded=False):
                    st.code(full_prompt, language="markdown")


elif page == "AI Analysis":
    st.title("AI Analysis")
    st.caption("Build a prompt or auto-analyze a ticker with latest available market data")

    from modules.ai_analysis import analyze_ticker, collect_market_snapshot, call_claude_api, ClaudeAPIError
    from modules.prompt_builder import PROMPT_TEMPLATES, fill_template, get_template_names
    import hashlib
    import json
    import os

    api_key = os.getenv("ANTHROPIC_API_KEY", "")

    if not api_key:
        st.warning("API key not configured. Add your key to the `.env` file.")
        st.code("ANTHROPIC_API_KEY=your_anthropic_key_here", language="bash")
        st.stop()

    st.caption(
        "Privacy: prompts are sent to the Anthropic API only when you click "
        "a send/run button. Successful responses store the full user/system "
        "prompts locally, together with their hashes, model and request "
        "settings, in the private SQLite database."
    )

    def _save_analysis(label: str, answer: str, prompt: str):
        try:
            save_ai_analysis(label, answer, CLAUDE_MODEL, DB_PATH, prompt=prompt, system_prompt=SYSTEM_DATA_INTEGRITY, max_tokens=CLAUDE_MAX_TOKENS)
        except (OSError, ValueError, sqlite3.Error) as exc:
            st.error(f"Analysis generated but could not be saved: {exc}")
            return
        st.caption("Saved")

    mode = st.radio(
        "Mode",
        ["Build & Send — write or template a prompt yourself",
         "Ticker Deep Dive — auto-fetch market data for a ticker"],
        index=0,
        label_visibility="collapsed",
    )

    st.divider()

    # ══════════════════════════════════════════════════════════
    #  MODE 1 — BUILD & SEND (fusion de l'ancien Prompt Builder +
    #  Send & Analyse : un seul endroit pour construire ET envoyer,
    #  plus de bouton d'envoi dupliqué entre deux tabs séparés)
    # ══════════════════════════════════════════════════════════
    if mode.startswith("Build"):
        source = st.radio(
            "Start from", ["A template", "A blank prompt"],
            horizontal=True, key="build_source",
        )

        variables = {}
        template_name = None

        if source == "A template":
            template_name = st.selectbox("Template", get_template_names(), key="tpl")
            template_data = PROMPT_TEMPLATES[template_name]
            st.caption(f"*{template_data.get('description', '')}*")

            template_text = template_data.get("template", "")
            needs_ticker = "{ticker}" in template_text
            needs_trade = "{entry_price}" in template_text
            needs_context = "{context}" in template_text

            if needs_ticker:
                c1, c2 = st.columns([2, 1])
                with c1:
                    ticker_pb = st.text_input("Ticker", placeholder="NVDA, ENR.DE, TTE...", key="pb_ticker").strip().upper()
                    variables["ticker"] = ticker_pb
                with c2:
                    st.markdown("<br>", unsafe_allow_html=True)
                    fetch_clicked = st.button("Fetch data", use_container_width=True, key="pb_fetch")

                if fetch_clicked and ticker_pb:
                    with st.spinner("Fetching one coherent market snapshot..."):
                        try:
                            snapshot = collect_market_snapshot(ticker_pb)
                        except (ValueError, KeyError, TypeError) as exc:
                            st.error(f"Market-data error: {exc}")
                        else:
                            st.session_state["pb_snapshot"] = snapshot
                            st.session_state["pb_snapshot_ticker"] = ticker_pb
                            st.success(f"Data loaded: {snapshot.get('name') or ticker_pb}")

                snapshot = None
                if st.session_state.get("pb_snapshot_ticker") == ticker_pb:
                    snapshot = st.session_state.get("pb_snapshot") or {}
                if snapshot:
                    price = snapshot.get("current_price")
                    currency = snapshot.get("quote_currency") or ""
                    dd = snapshot.get("drawdown_pct")
                    ret5d = snapshot.get("ret_5d")
                    short_value = snapshot.get("short_pct")
                    fund = snapshot.get("fundamentals") or {}
                    variables.update({
                        "price": f"{price:.4g} {currency}" if price is not None else "N/A",
                        "name": snapshot.get("name") or ticker_pb,
                        "drawdown": f"{dd*100:.1f}%" if dd is not None else "N/A",
                        "ret_5d": f"{ret5d*100:+.1f}%" if ret5d is not None else "N/A",
                        "short_pct": f"{short_value*100:.1f}%" if short_value is not None else "N/A",
                        "quote_source": snapshot.get("quote_source") or "unavailable",
                        "quote_timestamp": snapshot.get("quote_timestamp") or "unavailable",
                        "history_source": snapshot.get("history_source") or "unavailable",
                        "history_as_of": snapshot.get("history_as_of") or "unavailable",
                        "fundamentals_source": fund.get("_source") or "yfinance",
                    })

            if needs_context:
                variables["context"] = st.text_area(
                    "Supplied current data / context",
                    placeholder="Paste candidate data or current observations here. Unsourced text is treated as user-supplied, not independently verified.",
                    height=110,
                    key=f"pb_context_{template_name}",
                )

            if needs_trade:
                c1, c2, c3, c4 = st.columns(4)
                variables["entry_price"] = c1.text_input("Recorded entry price", key="pb_entry")
                variables["entry_date"] = c2.text_input("Entry date", key="pb_edate")
                variables["exit_price"] = c3.text_input("Recorded exit price", key="pb_exit")
                variables["exit_date"] = c4.text_input("Exit date", key="pb_xdate")
                variables["pnl"] = st.text_input("Broker P&L (€)", key="pb_pnl")
                variables["notes"] = st.text_area("Initial thesis", height=80, key="pb_notes")

            rendered_prompt = fill_template(template_text, dict(variables))
            signature_payload = json.dumps({"template": template_name, "variables": variables}, sort_keys=True, default=str)
            signature = hashlib.sha256(signature_payload.encode()).hexdigest()[:12]
            st.divider()
            st.markdown("**Prompt preview** — edit freely before sending")
            prompt_text = st.text_area(
                "Prompt preview editor",
                value=rendered_prompt,
                height=280,
                key=f"build_prompt_tpl_{signature}",
                label_visibility="collapsed",
            )
        else:
            prompt_text = st.text_area(
                "Your prompt",
                placeholder="Write a free question or paste your own prompt...",
                height=280,
                key="build_prompt_blank",
            )

        if st.button("Send to Claude →", type="primary", key="build_send") and prompt_text:
            try:
                with st.spinner("Calling Claude..."):
                    answer = call_claude_api(prompt_text, api_key)
            except ClaudeAPIError as exc:
                st.error(f"Claude API error: {exc}")
                answer = None
            if answer is not None:
                st.divider()
                st.markdown(answer)
                label = variables.get("ticker") or (template_name[:20] if template_name else "free_prompt")
                _save_analysis(label, answer, prompt_text)

    # ══════════════════════════════════════════════════════════
    #  MODE 2 — TICKER DEEP DIVE (mode auto : données de marché
    #  injectées automatiquement, pas de construction manuelle)
    # ══════════════════════════════════════════════════════════
    else:
        st.markdown("Market data (price, 5Y-high drawdown, 5d return, short interest, fundamentals) "
                     "is fetched automatically and injected into the analysis — nothing to build by hand.")
        st.divider()

        c1, c2 = st.columns([2, 1])
        with c1:
            ticker_input = st.text_input("Ticker", placeholder="NVDA, ENR.DE, TTE, ASML...", key="t3_ticker")
        with c2:
            st.markdown("<br>", unsafe_allow_html=True)
            run_analysis = st.button("Run Analysis", type="primary", use_container_width=True, key="t3_run")

        user_context = st.text_area(
            "Additional context (optional)",
            placeholder="e.g. earnings in 10 days, recent insider buying...",
            height=80,
            key="t3_context"
        )

        if run_analysis and ticker_input:
            ticker_clean = ticker_input.strip().upper()
            try:
                with st.spinner(f"Fetching {ticker_clean} + calling Claude..."):
                    result = analyze_ticker(ticker_clean, api_key, user_context)
            except ClaudeAPIError as exc:
                st.error(f"Claude API error: {exc}")
                result = None

            if result is not None:
                md = result["market_data"]
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Price", f"{md['current_price']:.2f}" if md.get("current_price") is not None else "N/A")
                dd_val = md.get("drawdown_pct")
                m2.metric("5Y High Drawdown", f"{dd_val*100:.1f}%" if dd_val is not None else "N/A")
                r5 = md.get("ret_5d")
                m3.metric("5d Return", f"{r5*100:+.1f}%" if r5 is not None else "N/A")
                si = md.get("short_pct")
                m4.metric("Short Interest", f"{si*100:.1f}%" if si is not None else "N/A")
                if md.get("quote_stale"):
                    st.info(f"Quote source: {md.get('quote_source')} — latest available mark may be stale.")

                st.divider()
                st.markdown(result["analysis"])

                with st.expander("View prompt sent to Claude", expanded=False):
                    st.code(result["prompt"], language="markdown")

                _save_analysis(ticker_clean, result["analysis"], result["prompt"])

        elif run_analysis and not ticker_input:
            st.warning("Enter a ticker first.")

    # ── History ───────────────────────────────────────────────
    st.divider()
    st.subheader("Previous Analyses")
    try:
        hist_df = load_ai_analysis_history(20, DB_PATH)
    except (OSError, ValueError, sqlite3.Error) as exc:
        st.warning(f"Could not load analysis history: {exc}")
    else:
        if not hist_df.empty:
            st.dataframe(hist_df, use_container_width=True, hide_index=True)
        else:
            st.caption("No analyses saved yet.")



elif page == "News":
    st.title("News")
    st.caption("Market-moving events — official/provider macro data, central banks, earnings and recent headlines")

    from modules.news import collect_catalyst_snapshot, build_catalyst_analysis_prompt
    from modules.ai_analysis import call_claude_api, ClaudeAPIError
    from datetime import datetime as _dt, date as _date, timezone as _timezone
    from zoneinfo import ZoneInfo as _ZoneInfo
    from html import escape as _html_escape
    import os

    try:
        trade_df = load_trades(DB_PATH)
        default_watchlist = (
            trade_df.loc[trade_df["status"] == "OPEN", "ticker"].dropna().astype(str).str.upper().tolist()
            if not trade_df.empty and "status" in trade_df.columns else []
        )
    except (OSError, ValueError, sqlite3.Error, KeyError):
        default_watchlist = []

    with st.sidebar:
        st.divider()
        st.markdown("**Settings**")
        days_ahead = st.slider("Horizon (days)", 7, 30, 21, key="news_horizon")
        countries = st.multiselect(
            "Macro countries/regions",
            ["US", "EU", "GB", "JP", "CN", "DE", "FR", "CA", "AU"],
            default=["US", "EU", "GB", "JP", "CN"],
            key="news_countries",
        )
        impact_filter = st.multiselect(
            "Impact",
            ["Major", "Moderate", "Minor"],
            default=["Major", "Moderate"],
            key="news_impact",
        )
        watchlist_text = st.text_input(
            "Earnings / news watchlist",
            value=",".join(default_watchlist),
            help="Comma-separated Yahoo-style tickers. Open positions are prefilled.",
            key="news_watchlist",
        )
        include_recent = st.toggle("Recent news context", value=True, key="news_recent")

    watchlist = [x.strip().upper() for x in watchlist_text.split(",") if x.strip()]

    @st.cache_data(ttl=900, show_spinner=False)
    def _cached_catalysts(days, country_tuple, watch_tuple, recent_flag):
        return collect_catalyst_snapshot(
            days_ahead=days,
            countries=country_tuple,
            watchlist=watch_tuple,
            include_recent_news=recent_flag,
        )

    if st.sidebar.button("↺ Refresh events", use_container_width=True, key="news_refresh"):
        _cached_catalysts.clear()
        st.rerun()

    with st.spinner("Fetching source-labelled event feeds..."):
        snapshot = _cached_catalysts(days_ahead, tuple(countries), tuple(watchlist), bool(include_recent))

    macro_block = snapshot.get("macro") or {}
    earnings_block = snapshot.get("earnings") or {}
    recent_block = snapshot.get("recent_news") or {}
    all_macro = macro_block.get("events") or []
    # One bounded UI/AI payload: exactly what is displayed is eligible for Claude.
    macro = [e for e in all_macro if not impact_filter or e.get("impact") in impact_filter][:80]
    earnings = (earnings_block.get("events") or [])[:80]
    recent_news = (recent_block.get("articles") or [])[:12]

    warnings = []
    warnings.extend(macro_block.get("warnings") or [])
    warnings.extend(earnings_block.get("warnings") or [])
    warnings.extend(recent_block.get("warnings") or [])
    hard_errors = []
    for label, block in (("Macro", macro_block), ("Earnings", earnings_block)):
        err = block.get("error")
        if err:
            hard_errors.append(f"{label}: {err}")
    hard_errors.extend(recent_block.get("errors") or [])

    def _safe(value):
        return _html_escape(str(value if value is not None else ""))

    def _parse_day(value):
        if isinstance(value, _dt):
            return value.date()
        if isinstance(value, _date):
            return value
        text = str(value or "").strip()
        if not text:
            return None
        try:
            return _dt.fromisoformat(text.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                return _date.fromisoformat(text[:10])
            except ValueError:
                return None

    def _days_until(event):
        d = _parse_day(event.get("date"))
        if d is None:
            return None
        return (d - _dt.now(_ZoneInfo("Europe/Paris")).date()).days

    def _days_label(event):
        n = _days_until(event)
        if n is None:
            return "Scheduled"
        if n <= 0:
            return "Today"
        if n == 1:
            return "In 1d"
        return f"In {n}d"

    def _impact_color(event):
        return {
            "Major": "#ef4444",
            "Moderate": "#f59e0b",
            "Minor": "#22c55e",
        }.get(event.get("impact"), "#64748b")

    def _date_label(event, compact=False):
        d = _parse_day(event.get("date"))
        if d is None:
            return "Date unavailable"
        return d.strftime("%a %d %b" if compact else "%A %d %B")

    def _provider_time(event):
        raw = str(event.get("provider_datetime") or "").strip()
        if not raw or len(raw) <= 10:
            return None
        try:
            dt = _dt.fromisoformat(raw.replace("Z", "+00:00"))
            if dt.hour == 0 and dt.minute == 0 and "T00:00" not in raw and " 00:00" not in raw:
                return None
            return dt.strftime("%H:%M")
        except ValueError:
            match = __import__("re").search(r"(?:T|\s)(\d{2}:\d{2})", raw)
            return match.group(1) if match else None

    def _fact_line(event):
        bits = []
        estimate = event.get("estimate")
        previous = event.get("previous")
        unit = str(event.get("unit") or "").strip()
        if estimate is not None:
            bits.append(f"Estimate {estimate:g}{unit}")
        if previous is not None:
            bits.append(f"Previous {previous:g}{unit}")
        source = event.get("source")
        if source:
            bits.append(str(source))
        return " · ".join(bits) if bits else "Source-labelled scheduled event"

    # Header strip — same visual hierarchy as the original QuantEdge News page.
    today = _dt.now(_ZoneInfo("Europe/Paris")).date()
    cutoff = today + __import__("datetime").timedelta(days=int(days_ahead))
    st.markdown(
        f"""
        <div style="display:flex; justify-content:space-between; align-items:baseline;
                    border-bottom:1px solid #1e1e35; padding-bottom:10px; margin-bottom:20px;">
            <span style="font-size:0.72rem; color:#4a5568; text-transform:uppercase; letter-spacing:0.1em;">
                {_safe(today.strftime('%A %d %B'))} → {_safe(cutoff.strftime('%d %B %Y'))}
            </span>
            <span style="font-size:0.72rem; color:#4a5568;">
                {len(macro)} macro · {len(earnings)} earnings
            </span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Provider diagnostics are deliberately secondary: fallbacks are normal behaviour.
    if warnings or hard_errors:
        with st.expander("Data sources & fallbacks", expanded=False):
            st.caption(
                f"Macro: {macro_block.get('source') or 'Unavailable'} · "
                f"Earnings: {earnings_block.get('source') or 'Unavailable'} · "
                f"News: {recent_block.get('source') or 'Unavailable'}"
            )
            for warning in warnings[:12]:
                st.caption(f"• {warning}")
            for error in hard_errors[:8]:
                st.caption(f"• Unavailable: {error}")

    if not macro and not earnings and not recent_news:
        st.info("No source-labelled events or headlines match the selected window. No replacement dates are fabricated.")
    else:
        # Lead story — closest Major event, otherwise the closest available macro event.
        major_events = [e for e in macro if e.get("impact") == "Major"]
        lead = major_events[0] if major_events else (macro[0] if macro else None)

        if lead:
            color = _impact_color(lead)
            time_label = _provider_time(lead)
            when = _date_label(lead)
            if time_label:
                when += f" · {time_label} provider time"
            country = lead.get("country") or "Macro"
            focus = lead.get("focus") or "Macro"
            st.markdown(
                f"""
                <div style="
                    border-left:4px solid {color};
                    background:linear-gradient(90deg, rgba(239,68,68,0.07), transparent 62%);
                    padding:20px 24px;
                    margin-bottom:28px;
                    border-radius:4px;
                ">
                    <div style="font-size:0.68rem; font-weight:700; letter-spacing:0.14em;
                                text-transform:uppercase; color:{color}; margin-bottom:8px;">
                        {_safe(_days_label(lead))} · {_safe(country)} · {_safe(lead.get('impact') or 'Scheduled')}
                    </div>
                    <div style="font-size:1.5rem; font-weight:700; color:#f1f5f9;
                                letter-spacing:-0.01em; line-height:1.25; margin-bottom:8px;">
                        {_safe(lead.get('event') or 'Scheduled event')}
                    </div>
                    <div style="font-size:0.82rem; color:#94a3b8; margin-bottom:10px;">
                        {_safe(when)} · {_safe(focus)}
                    </div>
                    <div style="font-size:0.86rem; color:#cbd5e1; line-height:1.5;
                                border-top:1px solid #1e1e35; padding-top:10px;">
                        {_safe(_fact_line(lead))}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        rest = [e for e in macro if e is not lead]
        if rest:
            st.markdown(
                "<div style='font-size:0.68rem; font-weight:700; letter-spacing:0.14em; "
                "text-transform:uppercase; color:#4a5568; margin-bottom:12px;'>Also this period</div>",
                unsafe_allow_html=True,
            )
            for event in rest:
                color = _impact_color(event)
                time_label = _provider_time(event)
                left_date = _date_label(event, compact=True)
                left_time = time_label or "—"
                category = " · ".join(x for x in [event.get("country"), event.get("focus")] if x)
                st.markdown(
                    f"""
                    <div style="display:flex; gap:16px; align-items:flex-start;
                                padding:12px 0; border-bottom:1px solid #16162a;">
                        <div style="flex:0 0 96px; font-size:0.72rem; color:#64748b;
                                    font-family:'JetBrains Mono', monospace; padding-top:2px;">
                            {_safe(left_date)}<br>{_safe(left_time)}
                        </div>
                        <div style="flex:0 0 4px; align-self:stretch; background:{color}; border-radius:2px;"></div>
                        <div style="flex:1;">
                            <div style="font-size:0.9rem; font-weight:600; color:#e2e8f0; margin-bottom:3px;">
                                {_safe(event.get('event') or 'Scheduled event')}
                                <span style="font-size:0.68rem; font-weight:500; color:{color}; margin-left:8px;">
                                    {_safe(_days_label(event))}
                                </span>
                            </div>
                            <div style="font-size:0.76rem; color:#64748b; margin-bottom:4px;">
                                {_safe(category)} · {_safe(event.get('source') or 'Source unavailable')}
                            </div>
                            <div style="font-size:0.82rem; color:#94a3b8; line-height:1.4;">
                                {_safe(_fact_line(event))}
                            </div>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

        if earnings:
            st.markdown(
                "<div style='font-size:0.68rem; font-weight:700; letter-spacing:0.14em; "
                "text-transform:uppercase; color:#4a5568; margin-top:28px; margin-bottom:12px;'>"
                "Earnings calendar</div>",
                unsafe_allow_html=True,
            )
            rows = []
            for e in earnings:
                d = _parse_day(e.get("date"))
                n = (d - today).days if d else None
                due = "Today" if n == 0 else (f"In {n}d" if n is not None and n > 0 else "Scheduled")
                rows.append({
                    "Due In": due,
                    "Date": d.strftime("%d %b") if d else "N/A",
                    "Ticker": e.get("ticker") or "",
                    "Session": e.get("before_after_market") or "N/A",
                    "EPS Est.": e.get("eps_estimate"),
                    "Source": e.get("source") or "",
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        elif watchlist:
            st.caption("No provider-supplied earnings dates found for the watchlist in this window.")

        if include_recent and recent_news:
            st.markdown(
                "<div style='font-size:0.68rem; font-weight:700; letter-spacing:0.14em; "
                "text-transform:uppercase; color:#4a5568; margin-top:28px; margin-bottom:12px;'>"
                "Recent news context</div>",
                unsafe_allow_html=True,
            )
            st.caption("Headlines are recent context only — never treated as future scheduled events.")
            for article in recent_news[:12]:
                ticker = article.get("ticker") or "Market"
                source = article.get("source") or "Source unavailable"
                date_text = str(article.get("date") or "")[:19].replace("T", " ")
                title = article.get("title") or "Untitled headline"
                link = str(article.get("link") or "").strip()
                title_html = _safe(title)
                if link.startswith("http://") or link.startswith("https://"):
                    title_html = f"<a href='{_safe(link)}' target='_blank' style='color:#e2e8f0;text-decoration:none;'>{title_html}</a>"
                st.markdown(
                    f"""
                    <div style="padding:10px 0; border-bottom:1px solid #16162a;">
                        <div style="font-size:0.68rem; color:#64748b; font-family:'JetBrains Mono', monospace; margin-bottom:4px;">
                            {_safe(ticker)} · {_safe(date_text)} · {_safe(source)}
                        </div>
                        <div style="font-size:0.9rem; font-weight:600; color:#e2e8f0; line-height:1.4;">
                            {title_html}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    st.divider()
    st.subheader("AI Catalyst Analysis")
    st.caption("Claude receives only the source-labelled events/headlines displayed above and is explicitly instructed not to invent missing dates or catalysts.")

    if not macro and not earnings and not recent_news:
        st.caption("No supplied event data to analyse.")
    elif st.button("Analyse upcoming catalysts", type="primary", key="news_ai_analyse"):
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            st.warning("ANTHROPIC_API_KEY is not configured in the local .env file.")
        else:
            # Analyse exactly the same bounded snapshot the user can see.
            ai_snapshot = dict(snapshot)
            ai_snapshot["macro"] = dict(macro_block, events=macro)
            ai_snapshot["recent_news"] = dict(recent_block, articles=recent_news[:12])
            prompt = build_catalyst_analysis_prompt(ai_snapshot)
            try:
                with st.spinner("Calling Claude with the source-labelled catalyst snapshot..."):
                    answer = call_claude_api(prompt, api_key)
            except ClaudeAPIError as exc:
                st.error(f"Claude API error: {exc}")
            else:
                st.markdown(answer)
                try:
                    save_ai_analysis("NEWS_CATALYSTS", answer, CLAUDE_MODEL, DB_PATH, prompt=prompt, system_prompt=SYSTEM_DATA_INTEGRITY, max_tokens=CLAUDE_MAX_TOKENS)
                except (OSError, ValueError, sqlite3.Error) as exc:
                    st.warning(f"Analysis generated but could not be saved: {exc}")
                with st.expander("View supplied catalyst prompt", expanded=False):
                    st.code(prompt, language="markdown")
