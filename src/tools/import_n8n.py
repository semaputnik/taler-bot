"""One-off import of the n8n Receipts Bot history for one user (issue #85, #86).

    python -m src.tools.import_n8n <export dir> --user-id <telegram id>

The export directory holds `receipt_payments.json` and `store_products.json`, each a list of
n8n data-table rows (the other n8n tables are ignored). The import writes, for an existing
user:

1. the catalog, in one Unit of Work: a payee per store key and a product per `store_products`
   row, with the hand-edited name and category (rows whose key exists are left alone);
2. every payment, in id order and each in its own Unit of Work, as a receipt whose parse is
   recomputed by `normalize` with the context n8n had at the time, stored by the same service
   function a live parse uses (catalog, receipt, expense). A payment that has a receipt with
   `source_ref = n8n:<id>` is skipped, so a rerun adds only the new rows.

This is a second composition root (like `bot/app.py`): it wires the Unit of Work itself and
never touches the bot, Redis or the LLM. At the end it prints the counts and every field where
the port disagrees with the n8n columns (a column n8n left empty is not compared).
"""

import argparse
import asyncio
import json
import logging
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from src.config.settings import Settings
from src.database.engine import create_engine, create_sessionmaker
from src.database.interfaces.uow import UnitOfWork, UnitOfWorkFactory
from src.database.uow.sqlalchemy import SqlAlchemyUnitOfWork
from src.domain.catalog import Catalog
from src.domain.enums import ProductCategory, ReceiptStatus
from src.domain.normalize import normalize
from src.domain.receipt import Photo, Receipt
from src.exception import AppException, UserNotFound
from src.services.receipt import save_with_catalog

logger = logging.getLogger(__name__)

PAYMENTS_FILE = "receipt_payments.json"
PRODUCTS_FILE = "store_products.json"


class ImportAborted(AppException):
    """The import stopped; the Units of Work before the failing payment are committed."""


@dataclass
class ImportReport:
    payees_added: int = 0
    payees_skipped: int = 0
    products_added: int = 0
    products_skipped: int = 0
    receipts_added: int = 0
    receipts_skipped: int = 0
    expenses_added: int = 0
    expenses_skipped: int = 0
    differences: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        counts = [
            f"payees: {self.payees_added} added, {self.payees_skipped} skipped",
            f"products: {self.products_added} added, {self.products_skipped} skipped",
            f"receipts: {self.receipts_added} added, {self.receipts_skipped} skipped",
            f"expenses: {self.expenses_added} added, {self.expenses_skipped} skipped",
        ]
        if not self.differences:
            return [*counts, "no differences from the n8n columns"]
        return [*counts, f"{len(self.differences)} difference(s) from the n8n columns:"] + [
            f"  {line}" for line in self.differences
        ]


# --- reading the export ------------------------------------------------------------------


def _read_rows(export_dir: Path, name: str) -> list[dict[str, Any]]:
    path = export_dir / name
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ImportAborted(f"cannot read {path}: {error}") from error
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ImportAborted(f"{path} must be a list of row objects")
    return rows


def _moment(value: str | None) -> datetime | None:
    if value is None:
        return None
    moment = datetime.fromisoformat(value)
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment


def _utc_text(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _money(value: object) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


# --- the catalog -------------------------------------------------------------------------


def _first(payments: Sequence[dict[str, Any]], store_key: str, column: str) -> str | None:
    return next(
        (p[column] for p in payments if p.get("storeKey") == store_key and p.get(column)), None
    )


def _fill_catalog(
    catalog: Catalog, products: Sequence[dict[str, Any]], payments: Sequence[dict[str, Any]]
) -> None:
    """Payees and products of the export; a key the catalog has stays as it is.

    A payee takes its details from the first payment of the store that has them, as a live
    parse would, so the legal name, tax id and address are there even though the catalog
    exists before any receipt.
    """
    names: dict[str, str] = {}
    for row in [*products, *payments]:
        key = row.get("storeKey")
        if key:
            names.setdefault(key, row.get("storeName") or key)
    for key, name in names.items():
        catalog.ensure_payee(
            key,
            name,
            _first(payments, key, "storeLegalName"),
            _first(payments, key, "storeTaxId"),
            _first(payments, key, "storeAddress"),
        )
    for row in products:
        catalog.ensure_product(
            row["storeKey"],
            row["productKey"],
            row["productNameRaw"],
            row["productName"],
            ProductCategory(row["category"]),
            row["unit"],
            source_ref=f"n8n:{row['id']}",
        )


# --- one payment -------------------------------------------------------------------------


def _differences(payment: dict[str, Any], receipt: Receipt) -> list[str]:
    """Where the port's result differs from the n8n columns; an empty column is not compared."""
    header = receipt.header
    n8n_key, n8n_store, n8n_total = (
        payment.get("receiptKey"),
        payment.get("storeKey"),
        payment.get("total"),
    )
    n8n_time = _moment(payment.get("purchasedAt"))
    checks = [
        ("receipt_key", n8n_key, header.receipt_key),
        ("purchased_at", n8n_time, header.purchased_at),
        ("store_key", n8n_store, header.store_key),
        ("total", None if n8n_total is None else _money(n8n_total), header.total),
        ("status", payment.get("status"), receipt.status.value),
    ]
    lines = []
    for name, theirs, ours in checks:
        if theirs is None:
            continue
        if name == "total" and ours is not None:
            ours = _money(ours)
        if ours is None or ours != theirs:
            show = _utc_text if name == "purchased_at" else str
            lines.append(
                f"payment {payment['id']} {name}: n8n {show(theirs)}, "
                f"port {'none' if ours is None else show(ours)}"
            )
    return lines


@dataclass
class _Context:
    """What n8n knew when it read the next payment."""

    timezone: str
    product_keys: set[str]
    card_last4: set[str]

    def learn(self, receipt: Receipt) -> None:
        self.product_keys |= {item.product_key for item in receipt.items}
        if receipt.status is ReceiptStatus.PARSED and receipt.header.card_last4:
            self.card_last4.add(receipt.header.card_last4)


async def _import_payment(
    uow: UnitOfWork,
    user_id: int,
    payment: dict[str, Any],
    context: _Context,
    report: ImportReport,
) -> None:
    ref = f"n8n:{payment['id']}"
    existing = await uow.receipts.find_by_source_ref(user_id, ref)
    if existing is not None:
        report.receipts_skipped += 1
        assert existing.id is not None
        if await uow.expenses.find_by_receipt(existing.id) is not None:
            report.expenses_skipped += 1
        context.learn(existing)
        return

    received_at = _moment(payment.get("receivedAt") or payment.get("createdAt"))
    if received_at is None:
        raise ImportAborted("the payment has no receivedAt")
    photo = Photo(
        received_at=received_at,
        telegram_message_id=payment.get("telegramMessageId"),
        drive_file_id=payment.get("driveFileId"),
        drive_url=payment.get("driveUrl"),
    )
    receipt = Receipt.start(user_id, photo)
    receipt.source_ref = ref
    status = payment.get("status")
    raw_json = payment.get("rawJson")

    if not raw_json:
        if status in ("parsed", "duplicate"):
            raise ImportAborted(f"a {status} payment has no rawJson")
        if status == "not_receipt":
            receipt.mark_not_receipt()
        elif status == "failed":
            receipt.mark_failed(payment.get("errorMessage") or "failed in n8n")
        await uow.receipts.add(receipt)  # `pending` stays pending
    else:
        parse = normalize(
            json.loads(raw_json),
            received_at=received_at,
            timezone=context.timezone,
            known_product_keys=context.product_keys,
            known_card_last4=context.card_last4,
            parser_version=payment["parserVersion"],
            model=payment.get("model"),
        )
        earlier = None
        if parse.receipt_key is not None:
            earlier = await uow.receipts.find_by_key(user_id, parse.receipt_key)
        # Added first, like a photo: the catalog and the expense refer to the receipt's id.
        await uow.receipts.add(receipt)
        outcome = receipt.apply_parse(parse, same_key_as=earlier.id if earlier else None)
        await save_with_catalog(uow, receipt, outcome)

    assert receipt.id is not None
    if await uow.expenses.find_by_receipt(receipt.id) is not None:
        report.expenses_added += 1
    report.receipts_added += 1
    report.differences += _differences(payment, receipt)
    context.learn(receipt)
    await uow.commit()


# --- the run -----------------------------------------------------------------------------


async def run_import(
    export_dir: Path, user_id: int, uow_factory: UnitOfWorkFactory
) -> ImportReport:
    """Import the export for `user_id`. `UserNotFound` before any write for an unknown user;
    `ImportAborted` (naming the payment) when a payment fails, the earlier ones stay."""
    payments = sorted(_read_rows(export_dir, PAYMENTS_FILE), key=lambda row: int(row["id"]))
    products = sorted(_read_rows(export_dir, PRODUCTS_FILE), key=lambda row: int(row["id"]))
    report = ImportReport()

    async with uow_factory() as uow:
        user = await uow.users.get(user_id)
        if user is None:
            raise UserNotFound(user_id)
        timezone = user.timezone
        catalog = await uow.catalog.get(user_id)
        payees_before = set(catalog.payees)
        products_before = set(catalog.products)
        # Products a previous run created from the export do not count as known: n8n knew
        # a product only once a payment had used it.
        known_keys = {k for k, p in catalog.products.items() if p.source_ref is None}
        known_card_last4 = await uow.receipts.known_card_last4(user_id)
        try:
            _fill_catalog(catalog, products, payments)
        except (KeyError, ValueError) as error:
            raise ImportAborted(f"store_products: {type(error).__name__}: {error}") from error
        await uow.catalog.save(catalog)
        await uow.commit()
    exported_payees = {r["storeKey"] for r in [*products, *payments] if r.get("storeKey")}
    report.payees_added = len(exported_payees - payees_before)
    report.payees_skipped = len(exported_payees & payees_before)
    exported_products = {r["productKey"] for r in products}
    report.products_added = len(exported_products - products_before)
    report.products_skipped = len(exported_products & products_before)

    context = _Context(timezone, known_keys, set(known_card_last4))
    for payment in payments:
        try:
            async with uow_factory() as uow:
                await _import_payment(uow, user_id, payment, context, report)
        except Exception as error:
            raise ImportAborted(
                f"payment {payment.get('id')}: {type(error).__name__}: {error}"
            ) from error
    return report


async def import_and_print(export_dir: Path, user_id: int, uow_factory: UnitOfWorkFactory) -> int:
    """Run the import and print the report; the process exit code."""
    try:
        report = await run_import(export_dir, user_id, uow_factory)
    except UserNotFound:
        print(f"error: no user {user_id}: nothing was written", file=sys.stderr)
        return 1
    except ImportAborted as error:
        print(f"error: {error}", file=sys.stderr)
        print("The payments before it are committed; fix the cause and run again.", file=sys.stderr)
        return 1
    print("\n".join(report.lines()))
    return 0


async def _main(export_dir: Path, user_id: int, settings: Settings) -> int:
    engine: AsyncEngine = create_engine(settings)
    session_factory = create_sessionmaker(engine)
    try:
        return await import_and_print(
            export_dir, user_id, lambda: SqlAlchemyUnitOfWork(session_factory)
        )
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import the n8n receipt history for one user.")
    parser.add_argument("export_dir", type=Path, help="directory with the n8n JSON export")
    parser.add_argument("--user-id", type=int, required=True, help="Telegram id of the user")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    settings = Settings()  # pyright: ignore[reportCallIssue]
    return asyncio.run(_main(args.export_dir, args.user_id, settings))


if __name__ == "__main__":
    sys.exit(main())
