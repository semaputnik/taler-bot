"""`ReceiptService`: the receipt actions the bot offers (ADR-0001, ADR-0002).

Every write is one Unit of Work: load the aggregate, call one aggregate method, apply the
`ParseOutcome` to the catalog, save, keep the receipt's expense in step (ADR-0003), commit.
The service holds no receipt rule; a rule showing up here belongs on `Receipt`.

`parse` is the exception: it is three short Units of Work around one model call that holds no
transaction (CLAUDE.md "Code rules"), under a per-user lock so one user has one model call at a
time.
"""

import asyncio
import logging
import weakref
from dataclasses import replace
from typing import Any, Literal
from zoneinfo import ZoneInfo

from src.database.interfaces.uow import UnitOfWork, UnitOfWorkFactory
from src.domain.catalog import Catalog, PaymentSource
from src.domain.edits import Edit
from src.domain.enums import EditTarget, IssueResolution, ReceiptStatus
from src.domain.expense import Expense
from src.domain.normalize import PARSER_VERSION, normalize
from src.domain.parse import Parse, ParseOutcome
from src.domain.receipt import Photo, Receipt
from src.exception import (
    DuplicatePhoto,
    IntegrationException,
    InvalidIssueResolution,
    InvalidReceiptData,
    ReceiptNotFound,
    UserNotFound,
)
from src.integration.llm import ParserOutput, ReceiptParser
from src.integration.storage import PhotoStorage, StorageError
from src.services.results import (
    BulkResult,
    IssueCard,
    IssueLine,
    ItemRow,
    NewPhoto,
    ParseResult,
    PhotoRef,
    ReceiptCard,
    ReparseSummary,
)

logger = logging.getLogger(__name__)

_NAME_FIELDS = frozenset({"items.name_raw", "items.name_normalized"})
_EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


class ReceiptService:
    def __init__(
        self, uow_factory: UnitOfWorkFactory, storage: PhotoStorage, parser: ReceiptParser
    ) -> None:
        self._uow_factory = uow_factory
        self._storage = storage
        self._parser = parser
        # A lock lives while a parse holds or awaits it, so the registry does not grow.
        self._parse_locks: weakref.WeakValueDictionary[int, asyncio.Lock] = (
            weakref.WeakValueDictionary()
        )

    # --- photos ------------------------------------------------------------------------

    async def save_photo(self, user_id: int, data: bytes, photo: NewPhoto) -> ReceiptCard:
        """Store the photo's bytes, then start a `pending` receipt for it.

        A Telegram photo the user already sent is rejected before anything is written. The
        file goes to disk between two Units of Work, so no transaction is open during the
        write. If the second one fails the file stays (photos are never deleted).
        """
        async with self._uow_factory() as uow:
            unique_id = photo.telegram_file_unique_id
            if unique_id is not None and await uow.receipts.photo_exists(user_id, unique_id):
                raise DuplicatePhoto(unique_id)
            user = await uow.users.get(user_id)
            if user is None:
                raise UserNotFound(user_id)
            timezone = user.timezone

        path = _photo_path(photo, timezone)
        await self._storage.save(path, data)

        try:
            async with self._uow_factory() as uow:
                receipt = await uow.receipts.add(
                    Receipt.start(user_id, Photo(path=path, **photo.model_dump()))
                )
                await uow.commit()
        except Exception:
            logger.warning("Receipt was not saved; photo file left on disk: %s", path)
            raise
        async with self._uow_factory() as uow:
            return await _card(uow, receipt)

    # --- parsing -----------------------------------------------------------------------

    async def parse(self, user_id: int, receipt_id: int) -> ParseResult:
        """Read a receipt's photo with the model and store the parse: the first read of a
        `pending` receipt, or a re-parse of a `failed`, `parsed` or `not_receipt` one.

        1. Unit of Work: load, read the photo and the normalization context, `mark_parsing`.
        2. No transaction: read the file, call the model, `normalize`.
        3. Unit of Work: load again, `apply_parse`, mark a duplicate, save with the catalog.

        A model, storage or normalization failure ends the read (outcome `failed`); any other
        error ends it too and is re-raised. The receipt becomes `failed`, or, for a re-parse,
        goes back to its previous status and parse with the reason recorded (the aggregate
        decides). A cancelled task (shutdown) awaits no database work, so its receipt stays
        `parsing`; `recover_interrupted` fixes those at the next start.
        """
        lock = self._parse_locks.setdefault(user_id, asyncio.Lock())
        async with lock:
            return await self._parse(user_id, receipt_id)

    async def _parse(self, user_id: int, receipt_id: int) -> ParseResult:
        async with self._uow_factory() as uow:
            receipt = await _load(uow, user_id, receipt_id)
            receipt.mark_parsing()
            user = await uow.users.get(user_id)
            if user is None:
                raise UserNotFound(user_id)
            known_product_keys = set((await uow.catalog.get(user_id)).products)
            known_card_last4 = await uow.receipts.known_card_last4(user_id)
            await uow.receipts.save(receipt)
            await uow.commit()
            path, mime_type = receipt.photo.path, receipt.photo.mime_type
            received_at = receipt.photo.received_at
            timezone = user.timezone
        assert path is not None, f"receipt {receipt_id} has no stored photo"

        try:
            try:
                image = await self._storage.read(path)
                output = await self._parser.parse(image, mime_type or "image/jpeg")
                parse = _stamped(
                    normalize(
                        output.raw.model_dump(),
                        received_at=received_at,
                        timezone=timezone,
                        known_product_keys=known_product_keys,
                        known_card_last4=known_card_last4,
                        parser_version=PARSER_VERSION,
                        model=output.model,
                    ),
                    output,
                )
            except (IntegrationException, InvalidReceiptData) as error:
                return await self._fail(user_id, receipt_id, str(error))
            return await self._store_parse(user_id, receipt_id, parse)
        except Exception as error:  # not an expected failure: leave no receipt `parsing`
            try:
                await self._fail(user_id, receipt_id, f"unexpected error: {type(error).__name__}")
            except Exception:
                logger.exception("Receipt %s could not be marked failed", receipt_id)
            raise

    async def _store_parse(self, user_id: int, receipt_id: int, parse: Parse) -> ParseResult:
        async with self._uow_factory() as uow:
            receipt = await _load(uow, user_id, receipt_id)
            earlier = None
            if parse.receipt_key is not None:
                earlier = await uow.receipts.find_by_key(user_id, parse.receipt_key)
            outcome = receipt.apply_parse(parse, same_key_as=earlier.id if earlier else None)
            await _save_with_catalog(uow, receipt, outcome)
            await uow.commit()
            return ParseResult(
                card=await _card(uow, receipt),
                outcome=_OUTCOMES[receipt.status],
                duplicate_of=await _card(uow, earlier)
                if receipt.duplicate_of_id and earlier
                else None,
                issues=[
                    IssueLine(item_name=i.item_name, message=i.message)
                    for i in receipt.top_issues()
                ],
            )

    async def _fail(self, user_id: int, receipt_id: int, message: str) -> ParseResult:
        """End the read as failed in its own Unit of Work; the aggregate restores a re-parse."""
        async with self._uow_factory() as uow:
            receipt = await _load(uow, user_id, receipt_id)
            receipt.mark_failed(message)
            await uow.receipts.save(receipt)
            await uow.commit()
            return ParseResult(card=await _card(uow, receipt), outcome="failed", error=message)

    # --- changes to a receipt ----------------------------------------------------------

    async def edit_item(
        self, user_id: int, receipt_id: int, item_ref: str, field: str, value: Any
    ) -> ReceiptCard:
        """Keep `value` for an item field, now and after any later parse."""
        edit = Edit(target=EditTarget.ITEM, item_ref=item_ref, field=field, value=value)
        return await self._edit(user_id, receipt_id, edit)

    async def edit_header(
        self, user_id: int, receipt_id: int, field: str, value: Any
    ) -> ReceiptCard:
        edit = Edit(target=EditTarget.RECEIPT, field=field, value=value)
        return await self._edit(user_id, receipt_id, edit)

    async def resolve_issue(
        self, user_id: int, receipt_id: int, issue_id: int, resolution: str
    ) -> ReceiptCard:
        """Mark an active issue `confirmed`, `corrected` or `skipped`."""
        try:
            parsed = IssueResolution(resolution)
        except ValueError:
            raise InvalidIssueResolution(f"unknown resolution {resolution!r}") from None
        async with self._uow_factory() as uow:
            receipt = await _load(uow, user_id, receipt_id)
            receipt.resolve_issue(issue_id, parsed)
            await uow.receipts.save(receipt)
            await uow.commit()
            return await _card(uow, receipt)

    async def correct_issue(
        self, user_id: int, receipt_id: int, issue_id: int, value: Any
    ) -> ReceiptCard:
        """Answer an open issue with the right value: keep it as an edit and close the issue."""
        async with self._uow_factory() as uow:
            receipt = await _load(uow, user_id, receipt_id)
            receipt.correct_issue(issue_id, value)
            await _save_with_catalog(uow, receipt)
            await uow.commit()
            return await _card(uow, receipt)

    async def soft_delete(self, user_id: int, receipt_id: int) -> None:
        """Delete the receipt, then move its photo to the trash.

        The file moves after the commit and outside any transaction. If the move fails the
        receipt stays deleted and the photo stays where it was (photos are never erased).
        """
        async with self._uow_factory() as uow:
            receipt = await _load(uow, user_id, receipt_id)
            receipt.soft_delete()
            await uow.receipts.save(receipt)
            await _sync_expense(uow, receipt, None)
            await uow.commit()
            path = receipt.photo.path
        if path is None:
            return
        try:
            await self._storage.trash(path)
        except StorageError:
            logger.warning("Photo of deleted receipt %s was not moved to the trash", receipt_id)

    async def card(self, user_id: int, receipt_id: int) -> ReceiptCard:
        """The receipt's card; for a `duplicate` it carries the receipt it repeats."""
        async with self._uow_factory() as uow:
            receipt = await _load(uow, user_id, receipt_id)
            card = await _card(uow, receipt)
            if receipt.duplicate_of_id is None:
                return card
            original = await uow.receipts.get(receipt.duplicate_of_id)
            if original is None:
                return card
            return card.model_copy(update={"duplicate_of": await _card(uow, original)})

    # --- re-parse ----------------------------------------------------------------------

    async def reparse_candidates(self, user_id: int) -> ReparseSummary:
        """How many receipts a bulk re-parse could read: failed ones and outdated ones."""
        async with self._uow_factory() as uow:
            found = await uow.receipts.reparse_candidates(user_id, PARSER_VERSION)
        return ReparseSummary(
            failed_count=len(found.failed_ids),
            outdated_count=len(found.outdated_ids),
            parser_version=PARSER_VERSION,
        )

    async def reparse_many(
        self, user_id: int, reason: Literal["failed", "outdated"], limit: int = 50
    ) -> BulkResult:
        """Read up to `limit` candidates again, oldest first, one after the other.

        Each `parse` takes the per-user lock on its own, so a photo sent meanwhile is read
        right after the current receipt. One receipt's failure, expected or not, is counted and
        never stops the run; cancellation (shutdown) propagates.
        """
        async with self._uow_factory() as uow:
            found = await uow.receipts.reparse_candidates(user_id, PARSER_VERSION)
        ids = found.failed_ids if reason == "failed" else found.outdated_ids
        ok = failed = 0
        for receipt_id in ids[: max(limit, 0)]:
            try:
                result = await self.parse(user_id, receipt_id)
            except Exception:
                logger.exception("Re-parse of receipt %s failed unexpectedly", receipt_id)
                failed += 1
                continue
            if result.outcome == "failed":
                failed += 1
            else:
                ok += 1
        return BulkResult(ok=ok, failed=failed)

    async def recover_interrupted(self) -> int:
        """Start-up: end the reads the bot's last run left in `parsing`, for every user.

        Returns how many receipts were recovered, in one Unit of Work.
        """
        async with self._uow_factory() as uow:
            ids = await uow.receipts.parsing_ids()
            for receipt_id in ids:
                receipt = await uow.receipts.get(receipt_id)
                assert receipt is not None
                receipt.recover_interrupted()
                await uow.receipts.save(receipt)
            await uow.commit()
        if ids:
            logger.warning("Recovered %s receipt(s) left in parsing: marked interrupted", len(ids))
        return len(ids)

    async def items(self, user_id: int, receipt_id: int) -> list[ItemRow]:
        """The receipt's items in parse order, edits applied. A deleted receipt still answers."""
        async with self._uow_factory() as uow:
            receipt = await _load(uow, user_id, receipt_id)
        return [
            ItemRow(
                ref=i.ref,
                product_key=i.product_key,
                currency=receipt.header.currency,
                printed_name=i.printed_name,
                readable_name=i.readable_name,
                category=str(i.category),
                quantity=i.quantity,
                unit=i.unit,
                unit_price=i.unit_price,
                reference_price=i.reference_price,
                reference_unit=i.reference_unit,
                discount=i.discount,
                line_total=i.line_total,
                vat_rate=i.vat_rate,
            )
            for i in receipt.items
        ]

    async def review(self, user_id: int, receipt_id: int) -> list[IssueCard]:
        """The issues worth a look, in walk order (high first, then parse order). One load."""
        async with self._uow_factory() as uow:
            receipt = await _load(uow, user_id, receipt_id)
        cards = []
        for issue in receipt.reviewable_issues():
            assert issue.id is not None, "a stored issue has an id"
            correction = receipt.issue_correction(issue)
            item = receipt.item_of(issue)
            cards.append(
                IssueCard(
                    issue_id=issue.id,
                    severity=str(issue.severity),
                    source=str(issue.source),
                    issue_type=issue.issue_type,
                    field=issue.field,
                    item_name=item.readable_name if item is not None else issue.item_name,
                    product_key=item.product_key if item is not None else None,
                    renamable=item is not None and issue.field in _NAME_FIELDS,
                    message=issue.message,
                    editable=correction is not None,
                    input_kind=correction.input_kind if correction is not None else None,
                    current_value=receipt.current_value(issue),
                )
            )
        return cards

    async def photo(self, user_id: int, receipt_id: int) -> PhotoRef:
        """The receipt photo's Telegram file id and type (a deleted receipt's too)."""
        async with self._uow_factory() as uow:
            receipt = await _load(uow, user_id, receipt_id)
            photo = receipt.photo
            return PhotoRef(telegram_file_id=photo.telegram_file_id, mime_type=photo.mime_type)

    async def photo_bytes(self, user_id: int, receipt_id: int) -> bytes:
        """The stored file's bytes, read with no transaction open. `StorageError` if unreadable."""
        async with self._uow_factory() as uow:
            path = (await _load(uow, user_id, receipt_id)).photo.path
        if path is None:
            raise StorageError(f"receipt {receipt_id} has no stored photo")
        return await self._storage.read(path)

    async def _edit(self, user_id: int, receipt_id: int, edit: Edit) -> ReceiptCard:
        async with self._uow_factory() as uow:
            receipt = await _load(uow, user_id, receipt_id)
            receipt.record_edit(edit)
            if edit.target is EditTarget.RECEIPT:
                await _save_with_catalog(uow, receipt)  # the header moved: so does the expense
            else:
                await uow.receipts.save(receipt)
            await uow.commit()
            return await _card(uow, receipt)


# --- helpers ---------------------------------------------------------------------------


_OUTCOMES: dict[ReceiptStatus, Literal["parsed", "not_receipt", "duplicate"]] = {
    ReceiptStatus.PARSED: "parsed",
    ReceiptStatus.NOT_RECEIPT: "not_receipt",
    ReceiptStatus.DUPLICATE: "duplicate",
}


def _stamped(parse: Parse, output: ParserOutput) -> Parse:
    return replace(
        parse,
        input_tokens=output.input_tokens,
        output_tokens=output.output_tokens,
        duration_ms=output.duration_ms,
    )


def _photo_path(photo: NewPhoto, timezone: str) -> str:
    """`yyyy/mm/receipt_<yyyy-MM-dd_HH-mm-ss>_<message_id>.<ext>` in the user's time zone."""
    local = photo.received_at.astimezone(ZoneInfo(timezone))
    extension = _EXTENSIONS.get(photo.mime_type or "", "jpg")
    return (
        f"{local:%Y/%m}/receipt_{local:%Y-%m-%d_%H-%M-%S}_{photo.telegram_message_id or 0}"
        f".{extension}"
    )


async def _load(uow: UnitOfWork, user_id: int, receipt_id: int) -> Receipt:
    receipt = await uow.receipts.get(receipt_id)
    if receipt is None or receipt.user_id != user_id:
        raise ReceiptNotFound(receipt_id)
    return receipt


async def _apply_parse(uow: UnitOfWork, receipt: Receipt, parse: Parse) -> None:
    outcome = receipt.apply_parse(parse)
    await _save_with_catalog(uow, receipt, outcome)


async def _save_with_catalog(
    uow: UnitOfWork, receipt: Receipt, outcome: ParseOutcome | None = None
) -> None:
    """Save a receipt whose header or parse changed, and keep the catalog and the expense in
    step. `outcome` is given when the parse was set or replaced.

    Order matters: new payees, products and payment sources must exist before the receipt's
    payee and items and the expense's source refer to them; the expense follows the saved
    receipt; released products can only be deleted once the receipt's items stop referencing
    them.
    """
    catalog = await uow.catalog.get(receipt.user_id)
    if outcome is not None:
        _register(catalog, receipt)
    source = None
    if receipt.backs_expense:
        source = catalog.source_for(receipt.header.card_brand, receipt.header.card_last4)
    await uow.catalog.save(catalog)
    await uow.receipts.save(receipt)
    await _sync_expense(uow, receipt, source)
    if outcome is None:
        return

    # Only products this receipt introduced and no other receipt uses are removed.
    candidates = {
        key
        for key in outcome.product_keys_released
        if (product := catalog.products.get(key)) is not None
        and product.created_by_receipt_id == receipt.id
    }
    assert receipt.id is not None
    released = candidates - await uow.receipts.product_keys_in_items_elsewhere(
        receipt.user_id, candidates, receipt.id
    )
    if released:
        catalog.remove_unreferenced(released)
        await uow.catalog.save(catalog)


async def _sync_expense(uow: UnitOfWork, receipt: Receipt, source: PaymentSource | None) -> None:
    """Make the receipt's expense mirror its header (ADR-0003).

    A receipt that backs an expense gets one on its first parse, and the existing one follows
    the header (and is reopened if it was deleted). Any other receipt (not a receipt, a repeat,
    deleted) has no live expense: an earlier one is deleted. `source` is the receipt's payment
    source, saved in the catalog already so that it has its id; None when the receipt backs no
    expense. The rule itself is on `Expense`; this only wires it.
    """
    assert receipt.id is not None
    expense = await uow.expenses.find_by_receipt(receipt.id)
    if not receipt.backs_expense:
        if expense is not None and expense.deleted_at is None:
            expense.soft_delete(receipt.deleted_at)
            await uow.expenses.save(expense)
        return
    assert source is not None
    user = await uow.users.get(receipt.user_id)
    if user is None:
        raise UserNotFound(receipt.user_id)
    facts = {
        "payee_key": receipt.header.store_key,
        "payment_source_id": source.id,
        "received_at": receipt.photo.received_at,
        "tz": ZoneInfo(user.timezone),
        "default_currency": user.default_currency,
    }
    if expense is None:
        await uow.expenses.add(
            Expense.from_receipt(receipt.user_id, receipt.id, receipt.header, **facts)
        )
        return
    if expense.deleted_at is not None:
        expense.restore()
    expense.sync_with_receipt(receipt.header, **facts)
    await uow.expenses.save(expense)


def _register(catalog: Catalog, receipt: Receipt) -> None:
    parse = receipt.parse
    if parse is None or not parse.is_receipt or parse.store_key is None:
        return
    catalog.ensure_payee(
        parse.store_key,
        parse.store_name or parse.store_key,
        parse.store_legal_name,
        parse.store_tax_id,
        parse.store_address,
    )
    for item in parse.items:
        catalog.ensure_product(
            parse.store_key,
            item.product_key,
            item.printed_name,
            item.readable_name,
            item.category,
            item.unit,
            created_by_receipt_id=receipt.id,
        )


async def _card(uow: UnitOfWork, receipt: Receipt) -> ReceiptCard:
    header = receipt.header
    assert receipt.id is not None
    catalog = await uow.catalog.get(receipt.user_id)
    store = catalog.payees.get(header.store_key) if header.store_key is not None else None
    expense = await uow.expenses.find_by_receipt(receipt.id)
    source = None
    if expense is not None and expense.payment_source_id is not None:
        source = catalog.payment_sources.get(expense.payment_source_id)
    return ReceiptCard(
        receipt_id=receipt.id,
        status=str(receipt.status),
        received_at=receipt.photo.received_at,
        deleted=receipt.deleted_at is not None,
        store_key=header.store_key,
        store_name=store.name if store is not None else None,
        purchased_at=header.purchased_at,
        currency=header.currency,
        total=header.total,
        payment_method=header.payment_method,
        card_brand=header.card_brand,
        card_last4=header.card_last4,
        can_reparse=receipt.can_reparse,
        error_message=receipt.error_message,
        expense_id=expense.id if expense is not None else None,
        expense_category=str(expense.category) if expense is not None else None,
        tags=list(expense.tags) if expense is not None else [],
        payment_source_name=source.name if source is not None else None,
        item_count=len(receipt.items),
        open_issue_count=sum(1 for i in receipt.issues if i.resolution is IssueResolution.OPEN),
        review_count=len(receipt.reviewable_issues()),
    )
