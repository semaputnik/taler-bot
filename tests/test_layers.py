"""Layer rules from CLAUDE.md that a plain import scan can enforce."""

import re
from pathlib import Path

SRC = Path(__file__).parent.parent / "src"


def imports_of(package: str) -> set[str]:
    found: set[str] = set()
    for path in (SRC / package).rglob("*.py"):
        found |= set(re.findall(r"^\s*(?:from|import)\s+([\w.]+)", path.read_text(), re.M))
    return found


def test_usecases_and_database_do_not_import_aiogram_or_the_bot():
    for package in ("usecases", "database"):
        offenders = {m for m in imports_of(package) if m.split(".")[0] == "aiogram" or ".bot" in m}
        assert not offenders, (package, offenders)


def test_only_the_database_package_imports_sqlalchemy():
    for package in ("usecases", "bot", "domain", "config"):
        assert not {m for m in imports_of(package) if m.startswith("sqlalchemy")}, package
