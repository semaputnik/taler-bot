"""Layer rules from CLAUDE.md that a plain import scan can enforce."""

import re
from pathlib import Path

SRC = Path(__file__).parent.parent / "src"


def imports_of(package: str) -> set[str]:
    found: set[str] = set()
    for path in (SRC / package).rglob("*.py"):
        found |= set(re.findall(r"^\s*(?:from|import)\s+([\w.]+)", path.read_text(), re.M))
    return found


def test_usecases_package_is_gone():
    assert not (SRC / "usecases").exists()


def test_services_and_database_do_not_import_aiogram_or_the_bot():
    for package in ("services", "database"):
        offenders = {m for m in imports_of(package) if m.split(".")[0] == "aiogram" or ".bot" in m}
        assert not offenders, (package, offenders)


def test_only_the_database_package_imports_sqlalchemy():
    for package in ("services", "bot", "domain", "config"):
        assert not {m for m in imports_of(package) if m.startswith("sqlalchemy")}, package


def _bot_modules_importing(prefix: str) -> set[str]:
    return {
        path.relative_to(SRC).as_posix()
        for path in (SRC / "bot").rglob("*.py")
        if re.search(rf"^\s*(?:from|import)\s+{re.escape(prefix)}", path.read_text(), re.M)
    }


def test_bot_reaches_the_database_only_through_the_composition_root():
    # `bot/app.py` wires the SQLAlchemy Unit of Work into the services; everything else in
    # `bot` talks to services and their own result types.
    assert _bot_modules_importing("src.database") <= {"bot/app.py"}


def test_bot_never_imports_the_domain():
    assert not _bot_modules_importing("src.domain")


def test_domain_imports_no_other_layer_and_no_framework():
    forbidden = ("src.database", "src.services", "src.bot", "sqlalchemy", "pydantic")
    offenders = {m for m in imports_of("domain") if m.startswith(forbidden)}
    assert not offenders


def test_integration_imports_no_bot_services_or_database():
    forbidden = ("src.bot", "src.services", "src.database")
    offenders = {m for m in imports_of("integration") if m.startswith(forbidden)}
    assert not offenders


def test_tools_are_a_composition_root_that_never_import_the_bot():
    # `tools/` wires the SQLAlchemy Unit of Work itself, like `bot/app.py`, so it may import
    # `database`; it still must not reach into the bot or aiogram.
    offenders = {m for m in imports_of("tools") if m.startswith("src.bot") or m == "aiogram"}
    assert not offenders
