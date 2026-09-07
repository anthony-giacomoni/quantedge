from pathlib import Path
import shutil
from scripts.validate_public_repo import validate

def _minimal_public_tree(root: Path):
    (root / 'examples').mkdir(parents=True)
    src = Path('examples/simu_invest_demo.xlsx')
    shutil.copy2(src, root / 'examples' / src.name)
    (root / '.env.example').write_text('ANTHROPIC_API_KEY=your_anthropic_key_here\nEODHD_' + 'API_KEY=your_eodhd_key_here\n')

def test_public_validator_accepts_only_demo_workbook_and_placeholders(tmp_path):
    _minimal_public_tree(tmp_path)
    assert validate(tmp_path) == []

def test_public_validator_rejects_private_workbooks_and_data(tmp_path):
    _minimal_public_tree(tmp_path)
    (tmp_path / 'private.xlsx').write_bytes(b'not-real-xlsx')
    (tmp_path / 'data').mkdir()
    problems = validate(tmp_path)
    assert any(('only the anonymised demo workbook' in p for p in problems))
    assert any(('forbidden path present: data' in p for p in problems))

def test_public_validator_rejects_real_api_assignments_but_not_examples(tmp_path):
    _minimal_public_tree(tmp_path)
    (tmp_path / 'leak.txt').write_text('EODHD_' + 'API_KEY=REALVALUE123456789\n')
    problems = validate(tmp_path)
    assert any(('non-placeholder EODHD_' + 'API_KEY' in p for p in problems))

def test_public_validator_rejects_anthropic_token_pattern(tmp_path):
    _minimal_public_tree(tmp_path)
    (tmp_path / 'leak.md').write_text('token ' + 'sk-' + 'ant-' + 'abcdefghijklmnopqrstuvwxyz')
    assert any(('secret-like token' in p for p in validate(tmp_path)))

def test_public_validator_rejects_local_machine_paths_in_text(tmp_path):
    _minimal_public_tree(tmp_path)
    leak = "/" + "Users" + "/private/Downloads/quantedge/data/private.xlsm"
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "private_helper.py").write_text(
        f'SOURCE = "{leak}"\n'
    )
    problems = validate(tmp_path)
    assert any("local machine path" in p for p in problems)


def test_public_validator_allows_generic_home_relative_setup_path(tmp_path):
    _minimal_public_tree(tmp_path)
    (tmp_path / "DEMARRAGE.md").write_text(
        "cd ~/Downloads/quantedge\n"
    )
    assert validate(tmp_path) == []

def test_validator_rejects_forbidden_directories_case_insensitively(tmp_path):
    from scripts.validate_public_repo import validate

    data_dir = tmp_path / "Data"
    venv_dir = tmp_path / ".VENV"

    data_dir.mkdir()
    venv_dir.mkdir()

    (data_dir / "private_positions.csv").write_text(
        "ticker,value\nAAPL,123\n"
    )
    (venv_dir / "note.txt").write_text(
        "runtime environment"
    )

    problems = validate(tmp_path)

    joined = "\n".join(problems)

    assert "Data" in joined
    assert ".VENV" in joined


def test_validator_rejects_embedded_binary_workbook_part(tmp_path):
    from pathlib import Path
    import shutil
    import zipfile

    from scripts.validate_public_repo import validate

    project_root = Path(__file__).resolve().parents[1]

    workbook = (
        tmp_path
        / "examples"
        / "simu_invest_demo.xlsx"
    )

    workbook.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    shutil.copy2(
        project_root
        / "examples"
        / "simu_invest_demo.xlsx",
        workbook,
    )

    payload = (
        b"EODHD_API_KEY"
        + b"="
        + b"REAL_PRIVATE_VALUE_123456789"
        + b"\n"
        + b"person.private@"
        + b"corp.invalid"
    )

    with zipfile.ZipFile(
        workbook,
        "a",
    ) as zf:
        zf.writestr(
            "xl/embeddings/private_payload.bin",
            payload,
        )

    problems = validate(tmp_path)

    assert any(
        "forbidden embedded/custom part" in problem
        and "xl/embeddings/private_payload.bin" in problem
        for problem in problems
    )


def test_validator_scans_non_xml_workbook_members_for_secrets(tmp_path):
    from pathlib import Path
    import shutil
    import zipfile

    from scripts.validate_public_repo import validate

    project_root = Path(__file__).resolve().parents[1]

    workbook = (
        tmp_path
        / "examples"
        / "simu_invest_demo.xlsx"
    )

    workbook.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    shutil.copy2(
        project_root
        / "examples"
        / "simu_invest_demo.xlsx",
        workbook,
    )

    payload = (
        b"EODHD_API_KEY"
        + b"="
        + b"REAL_PRIVATE_VALUE_123456789"
    )

    # Deliberately use a non-XML member outside the explicitly forbidden
    # embeddings/OLE/customXml paths. The generic bounded member scanner
    # must still detect the secret assignment.
    with zipfile.ZipFile(
        workbook,
        "a",
    ) as zf:
        zf.writestr(
            "xl/media/private_payload.bin",
            payload,
        )

    problems = validate(tmp_path)

    assert any(
        "non-placeholder EODHD_API_KEY" in problem
        and "xl/media/private_payload.bin" in problem
        for problem in problems
    )

