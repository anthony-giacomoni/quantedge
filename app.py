# ============================================================
#  QuantEdge — Dashboard principal (Streamlit)
#  Lancement : streamlit run app.py
# ============================================================

import streamlit as st
import pandas as pd
import sys, os

# Load .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# Chemin absolu pour les imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.db import init_database, trades_already_loaded
from utils.seed_trades import seed
from modules.portfolio import (
    load_enriched_trades,
    compute_stats,
    build_equity_curve,
    build_pnl_bars,
    build_sector_pie,
    format_trades_table,
)
from config import DB_PATH

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
    st.caption("Data: EODHD (prices) · yfinance (fundamentals)")


# ============================================================
#  PAGE : PORTFOLIO
# ============================================================
if page == "Trading":

    st.title("Trading — Personal Track Record")
    st.caption("Real trades · personal track record 2025-2026")

    # Chargement
    with st.spinner("Fetching live prices..."):
        df = load_enriched_trades(DB_PATH)

    if df.empty:
        st.warning("No trades found. Restart the app.")
        st.stop()

    # Alerte si le prix live d'une position ouverte n'a pas pu être récupéré
    open_missing_price = df[(df["status"] == "OPEN") & (df["current_price"].isna())]
    if not open_missing_price.empty:
        try:
            from utils.market_data import get_last_error
            last_err = get_last_error()
        except Exception:
            last_err = None
        tickers_str = ", ".join(open_missing_price["ticker"].tolist())
        msg = f"Live price unavailable for: **{tickers_str}** — showing last known P&L instead."
        if last_err:
            msg += f"\n\n`{last_err}`"
        st.warning(msg)

    # Alerte si le prix EODHD renvoyé est périmé (timestamp > 36h) — ex: marché
    # fermé, données de la veille resservies. EODHD real-time est délayé de
    # 15min par nature ; ce n'est pas ça qui est signalé ici, seulement un
    # quote clairement obsolète (plus vieux qu'une session de bourse).
    try:
        from utils.market_data import is_stale_price
        if not df[df["status"] == "OPEN"].empty and is_stale_price():
            st.info(
                "ℹ️ Quote may be stale (older than one trading session) — likely "
                "because the market is closed or between sessions. P&L reflects "
                "the last available price, not necessarily today's live price."
            )
    except Exception:
        pass

    with st.expander("🔧 Debug: last quote info (temporary)", expanded=True):
        try:
            from utils.market_data import get_last_quote_debug
            st.json(get_last_quote_debug())
        except Exception as e:
            st.write(f"Debug error: {e}")

    stats = compute_stats(df)

    # ── KPIs principaux ───────────────────────────────────────
    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        pnl = stats.get("total_pnl", 0)
        color = "green" if pnl >= 0 else "red"
        st.metric("Closed P&L", f"+{pnl:.2f}€" if pnl >= 0 else f"{pnl:.2f}€")

    with col2:
        st.metric("Win Rate", f"{stats.get('win_rate', 0):.1f}%")

    with col3:
        st.metric("Closed Trades", f"{stats.get('closed_trades', 0)}")

    with col4:
        st.metric("Best Trade", f"+{stats.get('best_trade', 0):.2f}€")

    with col5:
        open_pnl = stats.get("open_pnl", 0)
        sign = "+" if open_pnl >= 0 else ""
        color = "#ef4444" if open_pnl < 0 else "#22c55e"
        arrow = "↓" if open_pnl < 0 else "↑"
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
                    Unrealised P&L
                </div>
                <div style="font-size:1.4rem; font-weight:700; color:{color};
                            font-family:'JetBrains Mono', monospace;">
                    {arrow} {sign}{open_pnl:.2f}€
                </div>
                <div style="font-size:0.72rem; color:#64748b; margin-top:0.2rem;">
                    {stats.get('open_trades', 0)} open positions
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.divider()

    # ── Statistiques détaillées ───────────────────────────────
    with st.expander("Advanced Statistics", expanded=False):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Avg. Win", f"+{stats.get('avg_win', 0):.2f}€")
        c2.metric("Avg. Loss", f"{stats.get('avg_loss', 0):.2f}€")
        c3.metric("Profit Factor", f"{stats.get('profit_factor', 0):.2f}x")
        c4.metric("Avg. ROI / trade", f"{stats.get('avg_roi_pct', 0):.2f}%")
        c1.metric("Avg. Hold", f"{stats.get('avg_duration_days', 0):.0f} jours")
        c2.metric("Worst Trade", f"{stats.get('worst_trade', 0):.2f}€")
        c3.metric("Winning Trades", stats.get("wins", 0))
        c4.metric("Losing Trades", stats.get("losses", 0))

    # ── Equity curve ──────────────────────────────────────────
    st.subheader("Equity Curve")
    fig_eq = build_equity_curve(df)
    st.plotly_chart(fig_eq, use_container_width=True)

    # ── P&L bars + Secteur ────────────────────────────────────
    col_left, col_right = st.columns([2, 1])
    with col_left:
        st.subheader("P&L per Trade")
        fig_bars = build_pnl_bars(df)
        st.plotly_chart(fig_bars, use_container_width=True)
    with col_right:
        st.subheader("Profits by Sector")
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


# ============================================================
#  PAGES À VENIR (stubs)
# ============================================================
elif page == "DCA":
    st.title("DCA — Long Term Portfolio")
    st.caption("Passive investing · Global ETFs · Data from simu_invest.xlsm")

    from modules.dca import (
        load_excel, compute_global_stats, get_file_info,
        build_evolution_curve, build_etf_evolution,
        build_projection, build_allocation_donut, get_all_produits,
        EXCEL_PATH
    )
    import os

    # ── Upload ou fichier existant ───────────────────────────
    with st.sidebar:
        st.divider()
        st.markdown("**DCA File**")
        uploaded = st.file_uploader("Importer simu_invest.xlsm", type=["xlsm", "xlsx"])
        if uploaded:
            os.makedirs("data", exist_ok=True)
            with open(EXCEL_PATH, "wb") as f_up:
                f_up.write(uploaded.read())
            st.success("✅ File imported")

    info = get_file_info(EXCEL_PATH)
    if not info["exists"]:
        st.warning("No file found. Import your `simu_invest.xlsm` file from the sidebar.")
        st.stop()

    st.caption(f"📄 `simu_invest.xlsm` — last modified: {info['modified']} · {info['size_kb']} KB")

    with st.spinner("Reading Excel file..."):
        df_dca = load_excel(EXCEL_PATH)

    if df_dca is None or df_dca.empty:
        st.error("Unable to read the data. Check that the file contains a 'data' sheet.")
        st.stop()

    stats = compute_global_stats(df_dca)

    # ── KPIs ─────────────────────────────────────────────────
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total Invested", f"{stats['total_inv']:,.0f}€")
    k2.metric("Current Value", f"{stats['total_val']:,.0f}€")
    k3.metric("Total P&L", f"{stats['pnl']:+,.0f}€")
    k4.metric("Annualised Return", f"{stats['rendement_annualise']*100:+.1f}%")

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
        st.metric("Contributions", stats['n_versements'])

        st.metric("Value/Invested Ratio", f"{stats['ratio_val_inv']:.2f}x")
        st.caption(f"Période : {stats['date_debut']} → {stats['date_fin']}")

    st.divider()

    # ── ETF individuel ────────────────────────────────────────
    st.subheader("Product Performance")
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

        ps = get_produit_stats(df_dca, produit_sel)
        if ps:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Invested", f"{ps['investi']:,.0f}€")
            c2.metric("Current Value", f"{ps['valeur']:,.0f}€")
            c3.metric("P&L", f"{ps['pnl']:+,.0f}€")
            c4.metric("Return", f"{ps['rendement']*100:+.1f}%")
            if produit_sel not in ["iShares S&P 500 Acc", "iShares NASDAQ 100 Acc",
                                    "HSBC MSCI Emerging Markets Acc", "VanEck Defense Acc"]:
                st.caption("ℹ️ Invested = value at first purchase. For precise per-product tracking, use the Dashboard tab in your Excel file.")

    st.divider()

    # ── Projection ────────────────────────────────────────────
    st.subheader("Long-Term Projection")
    col_p1, col_p2 = st.columns(2)
    with col_p1:
        versement_proj = st.number_input(
            "Monthly contribution (€)", min_value=0, max_value=10000,
            value=int(stats['versement_moyen']), step=50,
        )
    with col_p2:
        horizons = st.multiselect(
            "Horizons", [5, 10, 15, 20, 25, 30], default=[10, 20, 30]
        )
    if horizons:
        fig_proj = build_projection(
            total_val=stats['total_val'],
            versement_mensuel=versement_proj,
            horizons=horizons,
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
    st.caption("💡 To update: import a new version of `simu_invest.xlsm` from the sidebar.")

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

        if st.button("Run AI Analysis", type="primary", key="dca_ai_run"):
            base_prompt = build_ai_portfolio_prompt(stats, df_dca)
            full_prompt = (
                f"{base_prompt}\n\n═══ SPECIFIC QUESTION ═══\n{dca_question}"
                if dca_question else
                f"{base_prompt}\n\n═══ SPECIFIC QUESTION ═══\nGive a general assessment of allocation, "
                f"concentration risk and diversification given the time horizon."
            )
            with st.spinner("Calling Claude..."):
                dca_answer = call_claude_api(full_prompt, api_key_dca)

            st.divider()
            st.markdown(dca_answer)

            try:
                from utils.db import get_connection
                conn = get_connection(DB_PATH)
                conn.execute(
                    "INSERT INTO ai_analyses (ticker, analysis, model) VALUES (?, ?, ?)",
                    ("dca_portfolio", dca_answer, "claude-sonnet-4-6"),
                )
                conn.commit()
                conn.close()
                st.caption("Saved")
            except Exception:
                pass

            with st.expander("View prompt sent to Claude", expanded=False):
                st.code(full_prompt, language="markdown")


elif page == "AI Analysis":
    st.title("AI Analysis")
    st.caption("Build a prompt or auto-analyze a ticker with live market data")

    from modules.ai_analysis import analyze_ticker, build_analysis_prompt, call_claude_api
    from modules.prompt_builder import PROMPT_TEMPLATES, fill_template, get_template_names
    from utils.market_data import get_current_price, get_drawdown_from_ath, get_5d_return, get_ticker_info
    import os

    api_key = os.getenv("ANTHROPIC_API_KEY", "")

    if not api_key:
        st.warning("API key not configured. Add your key to the `.env` file.")
        st.code("ANTHROPIC_API_KEY=sk-ant-your-key-here", language="bash")
        st.stop()

    def _save_analysis(label: str, answer: str):
        try:
            from utils.db import get_connection
            conn = get_connection(DB_PATH)
            conn.execute("INSERT INTO ai_analyses (ticker, analysis, model) VALUES (?, ?, ?)",
                         (label, answer, "claude-sonnet-4-6"))
            conn.commit()
            conn.close()
            st.caption("Saved")
        except Exception:
            pass

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
            needs_trade  = "{entry_price}" in template_text

            if needs_ticker:
                c1, c2 = st.columns([2, 1])
                with c1:
                    ticker_pb = st.text_input("Ticker", placeholder="NVDA, SIE.DE, TTE...", key="pb_ticker")
                    variables["ticker"] = ticker_pb
                with c2:
                    st.markdown("<br>", unsafe_allow_html=True)
                    if st.button("Fetch data", use_container_width=True, key="pb_fetch") and ticker_pb:
                        with st.spinner("Fetching..."):
                            price = get_current_price(ticker_pb)
                            dd    = get_drawdown_from_ath(ticker_pb)
                            ret5d = get_5d_return(ticker_pb)
                            info  = get_ticker_info(ticker_pb)
                        variables["price"]     = f"${price:.2f}" if price else "N/A"
                        variables["name"]      = info.get("name", ticker_pb)
                        variables["drawdown"]  = f"{dd['drawdown_pct']*100:.1f}%" if dd else "N/A"
                        variables["ret_5d"]    = f"{ret5d*100:+.1f}%" if ret5d else "N/A"
                        variables["short_pct"] = f"{info.get('short_pct_float', 0)*100:.1f}%" if info.get("short_pct_float") else "N/A"
                        st.success(f"Data loaded: {variables.get('name')} at {variables.get('price')}")

            if needs_trade:
                c1, c2, c3, c4 = st.columns(4)
                variables["entry_price"] = c1.text_input("Entry price", key="pb_entry")
                variables["entry_date"]  = c2.text_input("Entry date", key="pb_edate")
                variables["exit_price"]  = c3.text_input("Exit price", key="pb_exit")
                variables["exit_date"]   = c4.text_input("Exit date", key="pb_xdate")
                variables["pnl"]         = st.text_input("P&L (€)", key="pb_pnl")
                variables["notes"]       = st.text_area("Initial thesis", height=80, key="pb_notes")

            prompt_text = fill_template(template_text, variables)
            st.divider()
            st.markdown("**Prompt preview** — edit freely before sending")
            prompt_text = st.text_area("", value=prompt_text, height=280, key="build_prompt_tpl", label_visibility="collapsed")
        else:
            prompt_text = st.text_area(
                "Your prompt",
                placeholder="Write a free question or paste your own prompt...",
                height=280,
                key="build_prompt_blank",
            )

        if st.button("Send to Claude →", type="primary", key="build_send") and prompt_text:
            with st.spinner("Calling Claude..."):
                answer = call_claude_api(prompt_text, api_key)
            st.divider()
            st.markdown(answer)
            label = variables.get("ticker") or (template_name[:20] if template_name else "free_prompt")
            _save_analysis(label, answer)

    # ══════════════════════════════════════════════════════════
    #  MODE 2 — TICKER DEEP DIVE (mode auto : données de marché
    #  injectées automatiquement, pas de construction manuelle)
    # ══════════════════════════════════════════════════════════
    else:
        st.markdown("Market data (price, ATH drawdown, 5d return, short interest, fundamentals) "
                     "is fetched automatically and injected into the analysis — nothing to build by hand.")
        st.divider()

        c1, c2 = st.columns([2, 1])
        with c1:
            ticker_input = st.text_input("Ticker", placeholder="NVDA, SIE.DE, TTE, ASML...", key="t3_ticker")
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
            with st.spinner(f"Fetching {ticker_clean} + calling Claude..."):
                result = analyze_ticker(ticker_clean, api_key, user_context)

            md = result["market_data"]
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Price", f"${md['current_price']:.2f}" if md.get("current_price") else "N/A")
            dd_val = md.get("drawdown_pct")
            m2.metric("ATH Drawdown", f"{dd_val*100:.1f}%" if dd_val else "N/A")
            r5 = md.get("ret_5d")
            m3.metric("5d Return", f"{r5*100:+.1f}%" if r5 is not None else "N/A")
            si = md.get("short_pct")
            m4.metric("Short Interest", f"{si*100:.1f}%" if si else "N/A")

            st.divider()
            st.markdown(result["analysis"])

            with st.expander("View prompt sent to Claude", expanded=False):
                st.code(result["prompt"], language="markdown")

            _save_analysis(ticker_clean, result["analysis"])

        elif run_analysis and not ticker_input:
            st.warning("Enter a ticker first.")

    # ── History ───────────────────────────────────────────────
    st.divider()
    st.subheader("Previous Analyses")
    try:
        from utils.db import get_connection
        conn = get_connection(DB_PATH)
        hist_df = pd.read_sql_query(
            "SELECT ticker, model, created_at FROM ai_analyses ORDER BY created_at DESC LIMIT 20",
            conn
        )
        conn.close()
        if not hist_df.empty:
            st.dataframe(hist_df, use_container_width=True, hide_index=True)
        else:
            st.caption("No analyses saved yet.")
    except Exception:
        pass


elif page == "News":
    st.title("News")
    st.caption("Market-moving events — central banks, macro data, earnings")

    from modules.alerts import get_upcoming_events, get_impact_color, days_label

    with st.sidebar:
        st.divider()
        st.markdown("**Settings**")
        days_ahead    = st.slider("Horizon (days)", 7, 21, 21)
        show_macro    = st.toggle("Macro & Central Banks", value=True)
        show_earnings = st.toggle("Earnings", value=True)
        impact_filter = st.multiselect(
            "Min. impact",
            ["🔴 Major", "🟡 Moderate", "🟢 Minor"],
            default=["🔴 Major", "🟡 Moderate"]
        )

    data   = get_upcoming_events(days_ahead)
    today  = data["today"]
    cutoff = data["cutoff"]
    filtered_macro = [e for e in data["macro"] if e["impact"] in impact_filter] if show_macro else []

    st.markdown(
        f"""
        <div style="display:flex; justify-content:space-between; align-items:baseline;
                    border-bottom:1px solid #1e1e35; padding-bottom:10px; margin-bottom:20px;">
            <span style="font-size:0.72rem; color:#4a5568; text-transform:uppercase; letter-spacing:0.1em;">
                {today.strftime('%A %d %B')} → {cutoff.strftime('%d %B %Y')}
            </span>
            <span style="font-size:0.72rem; color:#4a5568;">
                {len(filtered_macro)} macro · {len(data['earnings']) if show_earnings else 0} earnings
            </span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if not filtered_macro and not (show_earnings and data["earnings"]):
        st.info(f"No events in the next {days_ahead} days matching your filters.")
        st.stop()

    # ── LEAD STORY : l'événement Major le plus proche ──────────
    major_events = [e for e in filtered_macro if "Major" in e["impact"]]
    lead = major_events[0] if major_events else (filtered_macro[0] if filtered_macro else None)

    if lead:
        lead_color = get_impact_color(lead["impact"])
        lead_date  = lead["event_date"].strftime("%A %d %B")
        st.markdown(
            f"""
            <div style="
                border-left: 4px solid {lead_color};
                background: linear-gradient(90deg, rgba(239,68,68,0.06), transparent 60%);
                padding: 20px 24px;
                margin-bottom: 28px;
                border-radius: 4px;
            ">
                <div style="font-size:0.68rem; font-weight:700; letter-spacing:0.14em;
                            text-transform:uppercase; color:{lead_color}; margin-bottom:8px;">
                    {days_label(lead['days_until'])} · {lead['category']}
                </div>
                <div style="font-size:1.5rem; font-weight:700; color:#f1f5f9;
                            letter-spacing:-0.01em; line-height:1.25; margin-bottom:8px;">
                    {lead['event']}
                </div>
                <div style="font-size:0.82rem; color:#94a3b8; margin-bottom:10px;">
                    {lead_date} at {lead['time']} Paris · {', '.join(lead['sectors'])}
                </div>
                <div style="font-size:0.9rem; color:#cbd5e1; line-height:1.5;
                            border-top:1px solid #1e1e35; padding-top:10px;">
                    {lead['note']}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # ── TIMELINE : le reste des événements macro, en rail chronologique ──
    rest = [e for e in filtered_macro if e is not lead]
    if rest:
        st.markdown(
            "<div style='font-size:0.68rem; font-weight:700; letter-spacing:0.14em; "
            "text-transform:uppercase; color:#4a5568; margin-bottom:12px;'>Also this period</div>",
            unsafe_allow_html=True,
        )
        for event in rest:
            color = get_impact_color(event["impact"])
            date_str = event["event_date"].strftime("%a %d %b")
            st.markdown(
                f"""
                <div style="
                    display:flex; gap:16px; align-items:flex-start;
                    padding: 12px 0; border-bottom: 1px solid #16162a;
                ">
                    <div style="flex:0 0 90px; font-size:0.72rem; color:#64748b;
                                font-family:'JetBrains Mono', monospace; padding-top:2px;">
                        {date_str}<br>{event['time']}
                    </div>
                    <div style="flex:0 0 4px; align-self:stretch; background:{color}; border-radius:2px;"></div>
                    <div style="flex:1;">
                        <div style="font-size:0.9rem; font-weight:600; color:#e2e8f0; margin-bottom:3px;">
                            {event['event']}
                            <span style="font-size:0.68rem; font-weight:500; color:{color}; margin-left:8px;">
                                {days_label(event['days_until'])}
                            </span>
                        </div>
                        <div style="font-size:0.78rem; color:#64748b; margin-bottom:4px;">
                            {event['category']} · {', '.join(event['sectors'])}
                        </div>
                        <div style="font-size:0.82rem; color:#94a3b8; line-height:1.4;">
                            {event['note']}
                        </div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    # ── EARNINGS ────────────────────────────────────────────────
    if show_earnings and data["earnings"]:
        st.markdown(
            "<div style='font-size:0.68rem; font-weight:700; letter-spacing:0.14em; "
            "text-transform:uppercase; color:#4a5568; margin-top:28px; margin-bottom:12px;'>"
            "Earnings calendar</div>",
            unsafe_allow_html=True,
        )
        rows = []
        for e in data["earnings"]:
            rows.append({
                "Due In":    days_label(e["days_until"]),
                "Date":      e["event_date"].strftime("%d %b"),
                "Ticker":    e["ticker"],
                "Company":   e["name"],
                "Consensus": e["consensus"],
                "Note":      e["note"],
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.divider()
    with st.expander("Why these indicators?", expanded=False):
        st.markdown("""
**Fed / ECB** — Rate decisions directly impact cost of capital and equity valuations.
A hawkish surprise sells off utilities (high debt) and growth stocks (higher discount rate).

**CPI / PPI** — Inflation determines the central bank trajectory.
A CPI surprise to the upside delays rate cuts → bond sell-off, pressure on multiples.

**NFP (Non-Farm Payrolls)** — US employment conditions the Fed stance.
Strong labour market = less accommodative Fed = pressure on valuations.

**EIA Crude Inventories** — Published every Wednesday.
Inventory draw = supply tension = Brent rallies = positive for energy (XOM, TTE, SIE.DE).

**OPEC+** — Production decisions set the Brent floor.
A surprise cut of 500K bbl/day = Brent +5–8% intraday.

**TTF European Gas** — European gas benchmark.
Direct impact on European utilities (EDF, Enel, Iberdrola) and industrial margins.
        """)

