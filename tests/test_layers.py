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


def test_bot_reaches_the_database_only_through_the_composition_root():
    # `bot/app.py` wires the SQLAlchemy Unit of Work into the use cases; everything else in
    # `bot` talks to use cases and their own result types.
    offenders = {
        path.relative_to(SRC).as_posix()
        for path in (SRC / "bot").rglob("*.py")
        if path.name != "app.py" or path.parent != SRC / "bot"
        if re.search(r"^\s*(?:from|import)\s+src\.database", path.read_text(), re.M)
    }
    assert not offenders
