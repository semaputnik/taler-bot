"""`ReceiptService`: the receipt actions the bot offers (ADR-0001, ADR-0002).

Every write is one Unit of Work: load the aggregate, call one aggregate method, apply the
`ParseOutcome` to the catalog, save, commit. The service holds no receipt rule; a rule showing
up here belongs on `Receipt`.

LLM hook point (not implemented): a future `parse(user_id, receipt_id)` loads the receipt in one
Unit of Work and closes it, calls the `ReceiptParser` with no transaction open (up to 120 s),
then opens a new Unit of Work. There, if `find_by_key(user_id, parse.receipt_key)` finds another
parsed receipt, it calls `Receipt.apply_parse` and then `mark_duplicate(found.id)`, so the
duplicate keeps its parse but never collides with the unique parsed key; otherwise it calls
`apply_parse` alone. Either way `_save_with_catalog` stores the result; `_apply_parse` is the
private path for the plain case.
"""

from typing import Any

from src.database.interfaces.uow import UnitOfWork, UnitOfWorkFactory
from src.domain.catalog import Catalog
from src.domain.edits import Edit
from src.domain.enums import EditTarget, IssueResolution
from src.domain.parse import Parse, ParseOutcome
from src.domain.receipt import Photo, Receipt
from src.exception import DuplicatePhoto, InvalidIssueResolution, ReceiptNotFound
from src.services.results import NewPhoto, ReceiptCard


class ReceiptService:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    # --- photos ------------------------------------------------------------------------

    async def save_photo(self, user_id: int, photo: NewPhoto) -> ReceiptCard:
        """Start a `pending` receipt for the photo.

        A Telegram photo the user already sent is rejected before anything is written.
        """
        async with self._uow_factory() as uow:
            unique_id = photo.telegram_file_unique_id
            if unique_id is not None and await uow.receipts.photo_exists(user_id, unique_id):
                raise DuplicatePhoto(unique_id)
            receipt = await uow.receipts.add(Receipt.start(user_id, Photo(**photo.model_dump())))
            await uow.commit()
            return await _card(uow, receipt)

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

    async def soft_delete(self, user_id: int, receipt_id: int) -> None:
        async with self._uow_factory() as uow:
            receipt = await _load(uow, user_id, receipt_id)
            receipt.soft_delete()
            await uow.receipts.save(receipt)
            await uow.commit()

    async def card(self, user_id: int, receipt_id: int) -> ReceiptCard:
        async with self._uow_factory() as uow:
            return await _card(uow, await _load(uow, user_id, receipt_id))

    async def _edit(self, user_id: int, receipt_id: int, edit: Edit) -> ReceiptCard:
        async with self._uow_factory() as uow:
            receipt = await _load(uow, user_id, receipt_id)
            receipt.record_edit(edit)
            await uow.receipts.save(receipt)
            await uow.commit()
            return await _card(uow, receipt)


# --- helpers ---------------------------------------------------------------------------


async def _load(uow: UnitOfWork, user_id: int, receipt_id: int) -> Receipt:
    receipt = await uow.receipts.get(receipt_id)
    if receipt is None or receipt.user_id != user_id:
        raise ReceiptNotFound(receipt_id)
    return receipt


async def _apply_parse(uow: UnitOfWork, receipt: Receipt, parse: Parse) -> None:
    outcome = receipt.apply_parse(parse)
    await _save_with_catalog(uow, receipt, outcome)


async def _save_with_catalog(uow: UnitOfWork, receipt: Receipt, outcome: ParseOutcome) -> None:
    """Save a receipt whose parse changed, and keep the catalog in step.

    Order matters: new stores and products must exist before the receipt's store and items
    refer to them; released products can only be deleted once the receipt's items stop
    referencing them.
    """
    catalog = await uow.catalog.get(receipt.user_id)
    _register(catalog, receipt)
    await uow.catalog.save(catalog)
    await uow.receipts.save(receipt)

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


def _register(catalog: Catalog, receipt: Receipt) -> None:
    parse = receipt.parse
    if parse is None or not parse.is_receipt or parse.store_key is None:
        return
    catalog.ensure_store(
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
    store_name = None
    if header.store_key is not None:
        store = (await uow.catalog.get(receipt.user_id)).stores.get(header.store_key)
        store_name = store.name if store is not None else None
    assert receipt.id is not None
    return ReceiptCard(
        receipt_id=receipt.id,
        status=str(receipt.status),
        store_name=store_name,
        purchased_at=header.purchased_at,
        currency=header.currency,
        total=header.total,
        payment_method=header.payment_method,
        card_brand=header.card_brand,
        card_last4=header.card_last4,
        item_count=len(receipt.items),
        open_issue_count=sum(1 for i in receipt.issues if i.resolution is IssueResolution.OPEN),
    )
