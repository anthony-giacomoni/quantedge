from pathlib import Path


def test_readme_avoids_disproved_claims():
    text = Path("README.md").read_text()
    assert "live P&L" not in text
    assert "Monte Carlo" not in text
    assert "Python 3.8" not in text
    assert "market-event prioritization" not in text


def test_public_copy_has_demo_and_env_template():
    assert Path("examples/simu_invest_demo.xlsx").exists()
    assert Path(".env.example").exists()

    gitignore = Path(".gitignore").read_text()
    assert ".env" in gitignore


def test_config_has_no_stale_catalyst_or_short_filter_claims():
    text = Path("config.py").read_text()
    assert "max_catalyst_days" not in text
    assert "min_short_interest" not in text
    assert "max_short_interest" not in text


def test_no_manual_news_calendar_module_remains():
    assert not Path("modules/alerts.py").exists()


def test_venv_is_ignored_and_python_range_is_bounded():
    gitignore = Path(".gitignore").read_text()
    assert ".venv/" in gitignore
    readme = Path("README.md").read_text()
    assert "Python 3.11–3.12" in readme
    assert "Python 3.11+" not in readme


def test_public_wording_uses_five_year_high_not_ath():
    public_text = "\n".join(Path(p).read_text() for p in [
        "README.md", "app.py", "modules/ai_analysis.py", "modules/prompt_builder.py"
    ])
    assert "All-time high" not in public_text
    assert "ATH Drawdown" not in public_text


def test_seed_has_no_ex_post_loss_exclusion_message():
    text = Path("utils/seed_trades.py").read_text()
    assert "non représentatif" not in text
    assert "PayPal x1" not in text


def test_internal_audit_logs_are_ignored_locally_and_forbidden_publicly():
    gitignore = Path(".gitignore").read_text()
    assert "CHANGES_AUDIT*.md" in gitignore

    from scripts.validate_public_repo import validate
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "CHANGES_AUDIT.md").write_text("local-only audit note")
        problems = validate(root)
        assert any("CHANGES_AUDIT.md" in problem for problem in problems)


def test_direct_runtime_dependencies_are_declared():
    from pathlib import Path
    req=Path("requirements.txt").read_text().lower()
    assert "certifi" in req


def test_no_obsolete_ticker_claims_or_old_news_claims():
    from pathlib import Path
    text="\n".join(Path(p).read_text(errors="ignore") for p in ["README.md","DEMARRAGE.md"])
    assert "SIE.DE" not in text
    assert "market-event prioritization" not in text.lower()
    assert "monte carlo" not in text.lower()


def test_public_validator_passes_sanitized_copy(tmp_path):
    import shutil
    import subprocess
    import sys

    source = Path.cwd()
    public = tmp_path / "quantedge_public"
    ignore = shutil.ignore_patterns(
        ".git", ".env", ".venv", "data", "CHANGES_AUDIT.md",
        "CHANGES_AUDIT*.md", "QUANTEDGE_*_REMEDIATION.md",
        ".pytest_cache", "__pycache__", ".coverage", "*.pyc", "*.pyo", "*.zip", "*.patch"
    )
    shutil.copytree(source, public, ignore=ignore)

    result = subprocess.run(
        [sys.executable, str(public / "scripts" / "validate_public_repo.py"), str(public)],
        cwd=public,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_navigation_restores_news_and_hides_standalone_screener():
    text = Path("app.py").read_text()
    assert '["Trading", "DCA", "AI Analysis", "News"]' in text
    assert 'elif page == "Screener"' not in text
    assert 'elif page == "News"' in text


def test_news_is_dynamic_not_manual_calendar():
    text = Path("README.md").read_text()
    assert "EODHD Economic Events" in text
    assert "does not ship a manually maintained future-event calendar" in text
    assert not Path("modules/alerts.py").exists()


def test_news_provider_fallbacks_and_rate_limit_controls_are_documented():
    readme = Path("README.md").read_text()
    assert "BLS / Federal Reserve / ECB" in readme
    assert "429 circuit breaker" in readme
    assert "cached yfinance" in readme.lower()
    assert "manually maintained future-event calendar" in readme


def test_readme_rule_score_is_really_reused_by_ai():
    readme = Path("README.md").read_text()
    ai = Path("modules/ai_analysis.py").read_text()
    assert "Rule-based setup scoring (backend)" in readme
    assert "compute_score" in ai and '"rule_score"' in ai


def test_no_stale_equity_curve_or_live_screener_comment():
    app = Path("app.py").read_text()
    screener = Path("modules/screener.py").read_text()
    assert "# ── Equity curve" not in app
    assert "Fallback LIVE" not in screener
