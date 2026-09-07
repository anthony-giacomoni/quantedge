"""Build a public QuantEdge tree from an exact file manifest, then validate it."""

from __future__ import annotations

from pathlib import Path

import argparse
import shutil

try:
    from scripts.validate_public_repo import validate
except ModuleNotFoundError:  # direct execution
    from validate_public_repo import validate


ROOT_FILES = {
    ".env.example",
    ".gitignore",
    ".python-version",
    "README.md",
    "DEMARRAGE.md",
    "app.py",
    "config.py",
    "refresh_universe.py",
    "requirements.txt",
    "requirements-dev.txt",
}

EXACT_FILES = {
    "examples/simu_invest_demo.xlsx",
}

# These rules classify source-like files that require an explicit release
# decision. They are NOT used for copying.
ALLOWED_TREE_RULES = {
    "assets": {".css"},
    "modules": {".py"},
    "utils": {".py"},
    "tests": {".py"},
    "scripts": {".py"},
    ".github/workflows": {".yml", ".yaml"},
}

# Exact manifest captured from the clean public candidate.
# New files do not become public automatically.
PUBLIC_TREE_FILES = {
    ".github/workflows/tests.yml",
    "assets/style.css",
    "modules/__init__.py",
    "modules/ai_analysis.py",
    "modules/dca.py",
    "modules/news.py",
    "modules/portfolio.py",
    "modules/prompt_builder.py",
    "modules/screener.py",
    "scripts/build_public_release.py",
    "scripts/validate_public_repo.py",
    "tests/conftest.py",
    "tests/test_adversarial_integrity.py",
    "tests/test_ai_analysis.py",
    "tests/test_db_cache.py",
    "tests/test_dca.py",
    "tests/test_documentation.py",
    "tests/test_eodhd.py",
    "tests/test_final_consolidation.py",
    "tests/test_financial_invariants.py",
    "tests/test_market_data.py",
    "tests/test_news.py",
    "tests/test_portfolio.py",
    "tests/test_prompt_builder.py",
    "tests/test_provider_freshness_and_symbols.py",
    "tests/test_provider_integrity.py",
    "tests/test_public_validator.py",
    "tests/test_refresh_universe.py",
    "tests/test_release_integrity.py",
    "tests/test_screener.py",
    "tests/test_seed_record.py",
    "tests/test_stale_release_integrity.py",
    "tests/test_terminal_hardening.py",
    "utils/__init__.py",
    "utils/db.py",
    "utils/eodhd.py",
    "utils/event_data.py",
    "utils/market_calendar.py",
    "utils/market_data.py",
    "utils/runtime.py",
    "utils/seed_trades.py",
}

PUBLIC_FILES = (
    ROOT_FILES
    | EXACT_FILES
    | PUBLIC_TREE_FILES
)


def _find_unclassified_candidates(source: Path) -> list[str]:
    """Return source-like files that have no explicit release classification."""
    source = Path(source).resolve()
    extras: list[str] = []

    for tree, suffixes in ALLOWED_TREE_RULES.items():
        base = source / tree

        if not base.is_dir():
            raise FileNotFoundError(
                f"required public directory missing: {tree}"
            )

        for src in base.rglob("*"):
            if not src.is_file():
                continue

            if src.suffix.lower() not in suffixes:
                continue

            rel = src.relative_to(source).as_posix()

            if rel not in PUBLIC_FILES:
                extras.append(rel)

    return sorted(set(extras))



def build_public_tree(source: Path, destination: Path) -> Path:
    source = Path(source).resolve()
    destination = Path(destination).resolve()

    unclassified = _find_unclassified_candidates(source)

    if unclassified:
        raise RuntimeError(
            "unclassified public-source candidate(s); "
            "explicit release decision required:\n- "
            + "\n- ".join(unclassified)
        )

    if destination.exists():
        shutil.rmtree(destination)

    destination.mkdir(parents=True)

    for rel in sorted(PUBLIC_FILES):
        src = source / rel

        # An allowlisted path is not enough: the object itself and every
        # directory between it and the source root must be non-symlinks.
        if src.is_symlink():
            raise RuntimeError(
                f"public source path is a symlink: {rel}"
            )

        parent = src.parent

        while parent != source:
            if parent.is_symlink():
                raise RuntimeError(
                    f"public source path has symlinked ancestor: {rel}"
                )

            parent = parent.parent

        try:
            resolved_src = src.resolve(strict=True)
        except FileNotFoundError:
            raise FileNotFoundError(
                f"required public file missing: {rel}"
            )

        try:
            resolved_src.relative_to(source)
        except ValueError:
            raise RuntimeError(
                f"public source resolves outside source tree: {rel}"
            )

        if not resolved_src.is_file():
            raise FileNotFoundError(
                f"required public file is not a regular file: {rel}"
            )

        dst = destination / rel
        dst.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        shutil.copy2(
            resolved_src,
            dst,
        )

    problems = validate(destination)

    if problems:
        raise RuntimeError(
            "public release validation failed:\n- "
            + "\n- ".join(problems)
        )

    return destination



def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("destination")
    parser.add_argument(
        "--source",
        default=str(
            Path(__file__).resolve().parents[1]
        ),
    )
    args = parser.parse_args()

    out = build_public_tree(
        Path(args.source),
        Path(args.destination),
    )

    print(out)
    print("PUBLIC RELEASE BUILD PASSED")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
