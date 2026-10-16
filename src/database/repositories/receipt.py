from datetime import date

from sqlalchemy import Date, cast, delete, exists, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.mapping import receipt as mapping
from src.database.models import (
    Receipt as ReceiptRow,
)
from src.database.models import (
    ReceiptEdit,
    ReceiptIssue,
    ReceiptItem,
    ReceiptMessage,
    ReceiptParse,
    ReceiptPhoto,
    Store,
    StoreProduct,
    User,
)
from src.domain.enums import ReceiptStatus
from src.domain.receipt import Receipt
from src.exception import ForeignKeyViolationError


class SqlAlchemyReceiptRepository:
    """Loads and saves the whole `Receipt` aggregate (ADR-0001).

    Photos, parses and edits are append-only: `save` inserts the ones without an id. The
    aggregate says what else changed (`current_parse_changed`, `items_changed`), so the
    repository never diffs rows.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- aggregate -----------------------------------------------------------------------

    async def get(self, receipt_id: int) -> Receipt | None:
        """The whole aggregate, soft-deleted included: one query per table."""
        found = (
            await self._session.execute(
                select(ReceiptRow, Store.store_key)
                .outerjoin(Store, Store.id == ReceiptRow.store_id)
                .where(ReceiptRow.id == receipt_id)
                .execution_options(populate_existing=True)
            )
        ).one_or_none()
        if found is None:
            return None
        row, store_key = found
        fresh = {"populate_existing": True}
        photos = await self._session.scalars(
            select(ReceiptPhoto)
            .where(ReceiptPhoto.receipt_id == receipt_id)
            .order_by(ReceiptPhoto.position, ReceiptPhoto.id)
            .execution_options(**fresh)
        )
        parses = await self._session.scalars(
            select(ReceiptParse)
            .where(ReceiptParse.receipt_id == receipt_id)
            .order_by(ReceiptParse.id)
            .execution_options(**fresh)
        )
        items = await self._session.execute(
            select(ReceiptItem, StoreProduct)
            .join(StoreProduct, StoreProduct.id == ReceiptItem.store_product_id)
            .where(ReceiptItem.receipt_id == receipt_id)
            .order_by(ReceiptItem.position)
            .execution_options(**fresh)
        )
        issues = await self._session.scalars(
            select(ReceiptIssue)
            .where(ReceiptIssue.parse_id == row.current_parse_id)
            .order_by(ReceiptIssue.id)
            .execution_options(**fresh)
        )
        edits = await self._session.scalars(
            select(ReceiptEdit)
            .where(ReceiptEdit.receipt_id == receipt_id)
            .order_by(ReceiptEdit.id)
            .execution_options(**fresh)
        )
        return mapping.receipt_from_rows(
            row,
            store_key,
            photos.all(),
            parses.all(),
            [(item, product) for item, product in items.all()],
            issues.all(),
            edits.all(),
        )

    async def add(self, receipt: Receipt) -> Receipt:
        """Insert a new receipt with all its parts; sets the ids on it and its parts."""
        values = mapping.receipt_values(receipt, store_id=await self._store_id(receipt))
        # The pointer needs the parse row, which needs this row: `_write` sets it.
        values["current_parse_id"] = None
        receipt.id = (
            await self._session.execute(
                insert(ReceiptRow).values(**values).returning(ReceiptRow.id)
            )
        ).scalar_one()
        await self._write(receipt, new=True)
        return receipt

    async def save(self, receipt: Receipt) -> None:
        """Write what changed since the receipt was loaded (see the class docstring)."""
        await self._write(receipt, new=False)

    async def _write(self, receipt: Receipt, *, new: bool) -> None:
        assert receipt.id is not None
        rebuild_issues = receipt.current_parse_changed or new
        rebuild_items = rebuild_issues or receipt.items_changed

        await self._insert_photos(receipt)
        await self._insert_parses(receipt)
        if not new or receipt.current_parse is not None:
            store_id = await self._store_id(receipt)
            await self._session.execute(
                update(ReceiptRow)
                .where(ReceiptRow.id == receipt.id)
                .values(**mapping.receipt_values(receipt, store_id=store_id))
            )
        if rebuild_items:
            await self._replace_items(receipt, new=new)
        if rebuild_issues:
            await self._replace_issues(receipt, new=new)
        else:
            await self._update_issue_resolutions(receipt)
        await self._insert_edits(receipt)
        receipt.mark_saved()

    async def _store_id(self, receipt: Receipt) -> int | None:
        """The receipt's store row, or None when the catalog has not got it (yet)."""
        key = receipt.header.store_key
        if key is None:
            return None
        return await self._session.scalar(
            select(Store.id).where(Store.user_id == receipt.user_id, Store.store_key == key)
        )

    async def _insert_photos(self, receipt: Receipt) -> None:
        for position, photo in enumerate(receipt.photos):
            if photo.id is None:
                values = mapping.photo_values(photo, receipt=receipt, position=position)
                photo.id = (
                    await self._session.execute(
                        insert(ReceiptPhoto).values(**values).returning(ReceiptPhoto.id)
                    )
                ).scalar_one()

    async def _insert_parses(self, receipt: Receipt) -> None:
        for parse in list(receipt.parses):
            if parse.id is None:
                values = mapping.parse_values(parse, receipt_id=receipt.id)
                parse_id = (
                    await self._session.execute(
                        insert(ReceiptParse).values(**values).returning(ReceiptParse.id)
                    )
                ).scalar_one()
                receipt.assign_parse_id(parse, parse_id)

    async def _replace_items(self, receipt: Receipt, *, new: bool) -> None:
        if not new:
            await self._session.execute(
                delete(ReceiptItem).where(ReceiptItem.receipt_id == receipt.id)
            )
        if not receipt.items:
            return
        keys = {item.product_key for item in receipt.items}
        found = await self._session.execute(
            select(StoreProduct.product_key, StoreProduct.id).where(
                StoreProduct.user_id == receipt.user_id,
                StoreProduct.product_key.in_(keys),
            )
        )
        product_ids = {key: product_id for key, product_id in found}
        missing = keys - product_ids.keys()
        if missing:
            raise ForeignKeyViolationError(f"products missing from the catalog: {sorted(missing)}")
        await self._session.execute(
            insert(ReceiptItem),
            [
                mapping.item_values(
                    item,
                    receipt_id=receipt.id,
                    position=position,
                    product_id=product_ids[item.product_key],
                )
                for position, item in enumerate(receipt.items)
            ],
        )

    async def _replace_issues(self, receipt: Receipt, *, new: bool) -> None:
        if not new:
            # Only the current parse's issues are active; the rest were replaced earlier.
            await self._session.execute(
                delete(ReceiptIssue).where(
                    ReceiptIssue.parse_id.in_(
                        select(ReceiptParse.id).where(ReceiptParse.receipt_id == receipt.id)
                    )
                )
            )
        # The database cleared `issue_id` on the edits that pointed at the deleted issues.
        for edit in receipt.edits:
            edit.issue_id = None
        parse = receipt.current_parse
        for issue in receipt.issues:
            assert parse is not None
            issue.id = (
                await self._session.execute(
                    insert(ReceiptIssue)
                    .values(**mapping.issue_values(issue, parse_id=parse.id))
                    .returning(ReceiptIssue.id)
                )
            ).scalar_one()

    async def _update_issue_resolutions(self, receipt: Receipt) -> None:
        rows = [
            {"id": i.id, "resolution": i.resolution.value, "resolved_at": i.resolved_at}
            for i in receipt.issues
            if i.id is not None
        ]
        if rows:
            await self._session.execute(update(ReceiptIssue), rows)

    async def _insert_edits(self, receipt: Receipt) -> None:
        for edit in receipt.edits:
            if edit.id is None:
                edit.id = (
                    await self._session.execute(
                        insert(ReceiptEdit)
                        .values(**mapping.edit_values(edit, receipt_id=receipt.id))
                        .returning(ReceiptEdit.id)
                    )
                ).scalar_one()

    # --- lookups -------------------------------------------------------------------------

    async def find_by_key(self, user_id: int, receipt_key: str) -> Receipt | None:
        """The user's parsed, not deleted receipt with this key (there is at most one)."""
        receipt_id = await self._session.scalar(
            select(ReceiptRow.id).where(
                ReceiptRow.user_id == user_id,
                ReceiptRow.receipt_key == receipt_key,
                ReceiptRow.status == ReceiptStatus.PARSED.value,
                ReceiptRow.deleted_at.is_(None),
            )
        )
        return await self._get_or_none(receipt_id)

    async def find_near(self, user_id: int, store_key: str, day: date) -> list[Receipt]:
        """Receipts of the same store on the same day (in the user's timezone), oldest first.

        Soft-deleted receipts and receipts merged into another one are not candidates.
        """
        ids = await self._session.scalars(
            select(ReceiptRow.id)
            .join(Store, Store.id == ReceiptRow.store_id)
            .join(User, User.id == ReceiptRow.user_id)
            .where(
                ReceiptRow.user_id == user_id,
                Store.store_key == store_key,
                ReceiptRow.deleted_at.is_(None),
                ReceiptRow.status != ReceiptStatus.MERGED.value,
                cast(func.timezone(User.timezone, ReceiptRow.purchased_at), Date) == day,
            )
            .order_by(ReceiptRow.purchased_at, ReceiptRow.id)
        )
        receipts = [await self._get_or_none(receipt_id) for receipt_id in ids.all()]
        return [r for r in receipts if r is not None]

    async def find_by_message(self, user_id: int, message_id: int) -> Receipt | None:
        """The receipt a bot message was linked to (soft-deleted included, like `get`)."""
        receipt_id = await self._session.scalar(
            select(ReceiptMessage.receipt_id).where(
                ReceiptMessage.user_id == user_id, ReceiptMessage.message_id == message_id
            )
        )
        return await self._get_or_none(receipt_id)

    async def link_message(self, receipt_id: int, user_id: int, message_id: int) -> None:
        await self._session.execute(
            insert(ReceiptMessage).values(
                receipt_id=receipt_id, user_id=user_id, message_id=message_id
            )
        )

    async def product_keys_in_items_elsewhere(
        self, user_id: int, product_keys: set[str], excluding_receipt_id: int
    ) -> set[str]:
        if not product_keys:
            return set()
        found = await self._session.scalars(
            select(StoreProduct.product_key)
            .join(ReceiptItem, ReceiptItem.store_product_id == StoreProduct.id)
            .where(
                StoreProduct.user_id == user_id,
                StoreProduct.product_key.in_(product_keys),
                ReceiptItem.receipt_id != excluding_receipt_id,
            )
            .distinct()
        )
        return set(found)

    async def photo_exists(self, user_id: int, telegram_file_unique_id: str) -> bool:
        return bool(
            await self._session.scalar(
                select(
                    exists().where(
                        ReceiptPhoto.user_id == user_id,
                        ReceiptPhoto.telegram_file_unique_id == telegram_file_unique_id,
                    )
                )
            )
        )

    async def _get_or_none(self, receipt_id: int | None) -> Receipt | None:
        return None if receipt_id is None else await self.get(receipt_id)
