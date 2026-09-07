"""Fail CI when private/runtime artifacts, PII, or obvious secrets enter the public repo."""
from pathlib import Path
import os
import re
import sys
import zipfile

DEFAULT_ROOT = Path(__file__).resolve().parents[1]
ALLOWED_WORKBOOKS = {Path("examples/simu_invest_demo.xlsx")}
FORBIDDEN_DIR_NAMES = {".venv", "env", "data", "Screenshots", ".pytest_cache", "__pycache__", "htmlcov", "__MACOSX"}
FORBIDDEN_DIR_NAMES_CASEFOLD = {
    name.casefold()
    for name in FORBIDDEN_DIR_NAMES
}
FORBIDDEN_FILE_NAMES = {".env", ".DS_Store", ".coverage", ".Rhistory"}
FORBIDDEN_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".zip", ".patch", ".xlsm", ".pem", ".key", ".p12", ".pfx"}
SECRET_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_-]{12,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
]
KEY_ASSIGNMENT = re.compile(
    r"(?im)^\s*([A-Z][A-Z0-9_]*(?:API_KEY|ACCESS_TOKEN|AUTH_TOKEN|SECRET|PASSWORD|PRIVATE_KEY))\s*=\s*['\"]?([^\s'\"#]+)"
)

INLINE_KEY_ASSIGNMENT = re.compile(
    r"(?i)\b([A-Z][A-Z0-9_]*(?:API_KEY|ACCESS_TOKEN|AUTH_TOKEN|SECRET|PASSWORD|PRIVATE_KEY))\s*=\s*['\"]?([^\s'\"<]+)"
)

EMAIL_PATTERN = re.compile(r"(?i)\b[A-Z0-9._%+-]+@([A-Z0-9.-]+\.[A-Z]{2,})\b")
LOCAL_MACHINE_PATH_PATTERNS = (
    re.compile(r"(?i)(?:file://)?/users/[A-Za-z0-9._-]+(?:/|$)"),
    re.compile(r"(?i)(?:file://)?/home/[A-Za-z0-9._-]+(?:/|$)"),
    re.compile(r"(?i)(?:file:///)?[A-Z]:[\\/]+users[\\/]+[A-Za-z0-9._-]+(?:[\\/]|$)"),
)
ALLOWED_EMAIL_DOMAINS = {"example.com", "eodhistoricaldata.com"}
PLACEHOLDER_MARKERS = (
    "your_", "replace", "placeholder", "example", "changeme", "<", "${",
    "os.getenv", "getenv(", "environ[", "dummy", "test_key",
)
TEXT_SUFFIXES = {".py", ".md", ".txt", ".yml", ".yaml", ".toml", ".example", ".ini", ".cfg", ".sh", ".command", ".json", ".csv", ".xml", ".html", ".htm", ".js", ".css", ""}
MAX_TEXT_SCAN_BYTES = 2 * 1024 * 1024

MAX_WORKBOOK_ENTRIES = 256
MAX_WORKBOOK_MEMBER_BYTES = 4 * 1024 * 1024
MAX_WORKBOOK_TOTAL_UNCOMPRESSED_BYTES = 16 * 1024 * 1024


def _is_placeholder(value: str) -> bool:
    v = value.strip().lower()
    return not v or any(marker in v for marker in PLACEHOLDER_MARKERS)


def _validate_demo_workbook(path: Path, rel: Path) -> list[str]:
    """Reject workbook features/metadata that can leak local/private context."""
    problems: list[str] = []

    legacy_forbidden_parts = (
        "externallinks/",
        "vbaproject",
        "connections.xml",
    )

    private_container_parts = (
        "xl/embeddings/",
        "xl/oleobjects/",
        "customxml/",
    )

    needles = (
        b"/users/",
        b"c:\\users\\",
        b"file:///",
        b"/downloads/",
        b"anthony giacomoni",
    )

    try:
        with zipfile.ZipFile(path) as zf:
            infos = [
                info
                for info in zf.infolist()
                if not info.is_dir()
            ]

            if len(infos) > MAX_WORKBOOK_ENTRIES:
                problems.append(
                    f"demo workbook has too many archive members: "
                    f"{rel} ({len(infos)})"
                )
                return problems

            total_uncompressed = sum(
                max(0, info.file_size)
                for info in infos
            )

            if (
                total_uncompressed
                > MAX_WORKBOOK_TOTAL_UNCOMPRESSED_BYTES
            ):
                problems.append(
                    f"demo workbook exceeds uncompressed scan limit: "
                    f"{rel}"
                )
                return problems

            for info in infos:
                original_name = info.filename
                normalised_name = (
                    original_name
                    .replace("\\", "/")
                )

                lower_name = normalised_name.casefold()
                path_parts = [
                    part
                    for part in normalised_name.split("/")
                    if part
                ]

                if (
                    normalised_name.startswith("/")
                    or ".." in path_parts
                ):
                    problems.append(
                        f"demo workbook contains unsafe archive path: "
                        f"{rel}:{original_name}"
                    )
                    continue

                if any(
                    part in lower_name
                    for part in legacy_forbidden_parts
                ):
                    problems.append(
                        f"demo workbook contains "
                        f"external/macro connection artifact: "
                        f"{rel}:{original_name}"
                    )

                if any(
                    part in lower_name
                    for part in private_container_parts
                ):
                    problems.append(
                        f"demo workbook contains forbidden "
                        f"embedded/custom part: "
                        f"{rel}:{original_name}"
                    )

                if info.file_size > MAX_WORKBOOK_MEMBER_BYTES:
                    problems.append(
                        f"demo workbook member exceeds scan limit: "
                        f"{rel}:{original_name}"
                    )
                    continue

                # Scan every bounded member, not only XML/RELS. XLSX is a ZIP
                # container and ASCII secrets can exist inside binary members.
                raw_blob = zf.read(info)
                blob = raw_blob.lower()

                if any(
                    needle in blob
                    for needle in needles
                ):
                    problems.append(
                        f"demo workbook contains "
                        f"local/personal metadata reference: "
                        f"{rel}:{original_name}"
                    )

                text = raw_blob.decode(
                    "utf-8",
                    errors="ignore",
                )

                for pattern in SECRET_PATTERNS:
                    if pattern.search(text):
                        problems.append(
                            f"demo workbook contains secret-like token: "
                            f"{rel}:{original_name}"
                        )

                for match in INLINE_KEY_ASSIGNMENT.finditer(text):
                    key_name, value = match.groups()

                    if not _is_placeholder(value):
                        problems.append(
                            f"demo workbook contains non-placeholder "
                            f"{key_name}: {rel}:{original_name}"
                        )

                for match in EMAIL_PATTERN.finditer(text):
                    domain = match.group(1).lower()

                    if domain not in ALLOWED_EMAIL_DOMAINS:
                        problems.append(
                            f"demo workbook contains potential "
                            f"personal email address: "
                            f"{rel}:{original_name}"
                        )
                        break

    except (
        OSError,
        zipfile.BadZipFile,
        KeyError,
        RuntimeError,
    ) as exc:
        problems.append(
            f"demo workbook is not a valid clean xlsx archive: "
            f"{rel} ({exc})"
        )

    return problems

def _scan_text(path: Path, rel: Path) -> list[str]:
    problems: list[str] = []
    try:
        if path.stat().st_size > MAX_TEXT_SCAN_BYTES:
            problems.append(f"text file exceeds validator scan limit: {rel}")
            return problems
        text = path.read_text(errors="ignore")
    except OSError:
        return problems
    for pattern in SECRET_PATTERNS:
        if pattern.search(text):
            problems.append(f"secret-like token in {rel}")
    for match in KEY_ASSIGNMENT.finditer(text):
        key_name, value = match.groups()
        if not _is_placeholder(value):
            problems.append(f"non-placeholder {key_name} assignment in {rel}")

    for match in INLINE_KEY_ASSIGNMENT.finditer(text):
        key_name, value = match.groups()
        if not _is_placeholder(value):
            problems.append(
                f"inline non-placeholder {key_name} assignment in {rel}"
            )
    for match in EMAIL_PATTERN.finditer(text):
        domain = match.group(1).lower()
        if domain not in ALLOWED_EMAIL_DOMAINS:
            problems.append(f"potential personal email address in {rel}")
            break
    if any(pattern.search(text) for pattern in LOCAL_MACHINE_PATH_PATTERNS):
        problems.append(f"local machine path in {rel}")
    return problems


def validate(root: Path) -> list[str]:
    """Recursively validate an exported public tree with no security blind-spot dirs."""
    root = Path(root).resolve()
    problems: list[str] = []

    for current, dirs, files in os.walk(root):
        current_path = Path(current)
        rel_dir = current_path.relative_to(root)

        # .git metadata is not part of a release artifact and can be huge. All other
        # runtime/cache directories are themselves forbidden, so pruning them cannot
        # hide a passing result.
        if ".git" in dirs:
            dirs.remove(".git")

        for dirname in list(dirs):
            rel = rel_dir / dirname if rel_dir != Path(".") else Path(dirname)
            if dirname.casefold() in FORBIDDEN_DIR_NAMES_CASEFOLD:
                if (
                    len(rel.parts) == 1
                    and dirname.casefold()
                    in {".venv", "data", "screenshots"}
                ):
                    problems.append(f"forbidden path present: {dirname}")
                else:
                    problems.append(f"forbidden directory: {rel}")
                dirs.remove(dirname)

        for filename in files:
            path = current_path / filename
            rel = path.relative_to(root)
            suffix = path.suffix.lower()
            upper_name = filename.upper()

            if filename == ".DS_Store":
                problems.append(f"forbidden OS metadata: {rel}")
                continue
            lower_name = filename.lower()
            if filename in FORBIDDEN_FILE_NAMES or ((lower_name.startswith(".env") or lower_name.endswith(".env")) and lower_name != ".env.example"):
                problems.append(f"forbidden environment file: {rel}")
                continue
            if upper_name.startswith("CHANGES_AUDIT") or "REMEDIATION" in upper_name or upper_name.startswith("QUANTEDGE_ROUND"):
                problems.append(f"forbidden internal audit/remediation artifact: {rel}")
                continue
            if suffix in FORBIDDEN_SUFFIXES:
                problems.append(f"forbidden artifact: {rel}")
                continue
            if suffix in {".xlsx", ".xls"} and rel not in ALLOWED_WORKBOOKS:
                problems.append(f"only the anonymised demo workbook may be public: {rel}")
                continue
            if rel in ALLOWED_WORKBOOKS and suffix == ".xlsx":
                problems.extend(_validate_demo_workbook(path, rel))
                continue

            if suffix in TEXT_SUFFIXES:
                problems.extend(_scan_text(path, rel))

    return sorted(set(problems))


def main(argv=None) -> int:
    argv = sys.argv if argv is None else argv
    root = Path(argv[1]).resolve() if len(argv) > 1 else DEFAULT_ROOT
    problems = validate(root)
    if problems:
        print("PUBLIC REPO VALIDATION FAILED")
        for problem in problems:
            print(f"- {problem}")
        return 1
    print("PUBLIC REPO VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
