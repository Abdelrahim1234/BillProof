"""Admin CLI: scan tracked repo files for a real SAS-signed URL pattern.

CLAUDE_FINAL_DEMO_HARDENING_PROMPT Fix 2: "Run a tracked-file secret scan and
fail the build when a real SAS token pattern appears outside an explicitly
fake test fixture. Never print a discovered token while reporting the scan."

A real signature is multiple SAS parameters (sig=, sv=, se=, sp=, sr=, spr=,
st=, skoid=, sktid=) co-occurring in one query string -- a single "sig="
substring alone is too weak a signal and produces false positives (it's also
a common English-adjacent token). Files under tests/ are exempted: that is
where an explicitly fake fixture is expected to live (see
tests/unit/test_manifest_sanitization.py's _FAKE_SIGNED_URL). Never prints
the matched text, only the file and line number.

Usage: uv run python scripts/secret_scan.py
Exit 0: clean. Exit 1: a real-looking SAS pattern was found outside tests/.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EXEMPT_DIRS = {"tests", ".venv", "__pycache__", "node_modules", ".git"}
_TEXT_EXTENSIONS = {".py", ".json", ".csv", ".md", ".txt", ".env", ".yaml", ".yml", ".toml"}

# A real signature is several SAS params joined as an actual query string --
# "name=value&name=value&..." with no whitespace -- not just the parameter
# names appearing in prose (e.g. this very file's own docstring/detector
# list, which names them comma-and-space separated).
_SAS_QUERY_PATTERN = re.compile(
    r"(?:\b(?:sig|sv|se|sp|sr|spr|st|skoid|sktid)=[^&\s\"']+(?:&|$)){3,}"
)


def _is_exempt(path: Path) -> bool:
    return any(part in EXEMPT_DIRS for part in path.relative_to(REPO_ROOT).parts)


def _looks_like_real_sas(line: str) -> bool:
    return bool(_SAS_QUERY_PATTERN.search(line)) and "sig=" in line


def scan() -> list[tuple[Path, int]]:
    findings = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in _TEXT_EXTENSIONS or _is_exempt(path):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if _looks_like_real_sas(line):
                findings.append((path.relative_to(REPO_ROOT), i))
    return findings


def main() -> int:
    findings = scan()
    if not findings:
        print("secret scan: clean (no SAS-signed URL pattern found outside tests/)")
        return 0
    print(f"secret scan: FOUND {len(findings)} possible SAS-signed URL(s) -- token value never printed:")
    for path, line_no in findings:
        print(f"  {path}:{line_no}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
