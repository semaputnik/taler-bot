from dataclasses import replace

from sqlalchemy import delete, exists, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.mapping import receipt as mapping
from src.database.models import (
    Receipt as ReceiptRow,
)
from src.database.models import (
    ReceiptEdit,
    ReceiptIssue,
    ReceiptItem,
    ReceiptParse,
    ReceiptPhoto,
    Store,
    StoreProduct,
)
from src.domain.enums import ReceiptStatus
from src.domain.receipt import Receipt
from src.exception import ForeignKeyViolationError


class SqlAlchemyReceiptRepository:
    """Loads and saves the whole `Receipt` aggregate (ADR-0001, ADR-0002).

    The photo and edits are append-only: `save` inserts the ones without an id. The aggregate
    says what else changed (`parse_changed`, `items_changed`), so the repository never diffs
    rows.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- aggregate -----------------------------------------------------------------------

    async def get(self, receipt_id: int) -> Receipt | None:
        """The whole aggregate, soft-deleted included: one query per table, 6 at most."""
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
        photo = await self._session.scalar(
            select(ReceiptPhoto)
            .where(ReceiptPhoto.receipt_id == receipt_id)
            .execution_options(**fresh)
        )
        assert photo is not None, f"receipt {receipt_id} has no photo"
        parse = await self._session.scalar(
            select(ReceiptParse)
            .where(ReceiptParse.receipt_id == receipt_id)
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
            .where(ReceiptIssue.parse_id == (parse.id if parse is not None else None))
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
            photo,
            parse,
            [(item, product) for item, product in items.all()],
            issues.all(),
            edits.all(),
        )

    async def add(self, receipt: Receipt) -> Receipt:
        """Insert a new receipt with all its parts; sets the ids on it and its parts."""
        values = mapping.receipt_values(receipt, store_id=await self._store_id(receipt))
        receipt.id = (
            await self._session.execute(
                insert(ReceiptRow).values(**values).returning(ReceiptRow.id)
            )
        ).scalar_one()
        await self._write_parts(receipt, new=True)
        return receipt

    async def save(self, receipt: Receipt) -> None:
        """Write what changed since the receipt was loaded.

        The header row is always updated. On `parse_changed` the parse row is upserted (kept
        in place when the receipt has one) and the items and issues are replaced; on
        `items_changed` only the items are; otherwise only issue resolutions are updated.
        New edits are appended.
        """
        assert receipt.id is not None
        store_id = await self._store_id(receipt)
        await self._session.execute(
            update(ReceiptRow)
            .where(ReceiptRow.id == receipt.id)
            .values(**mapping.receipt_values(receipt, store_id=store_id))
        )
        await self._write_parts(receipt, new=False)

    async def _write_parts(self, receipt: Receipt, *, new: bool) -> None:
        rebuild_issues = receipt.parse_changed or (new and receipt.parse is not None)
        rebuild_items = rebuild_issues or receipt.items_changed or (new and bool(receipt.items))

        await self._insert_photo(receipt)
        if rebuild_issues:
            await self._upsert_parse(receipt)
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

    async def _insert_photo(self, receipt: Receipt) -> None:
        photo = receipt.photo
        if photo.id is None:
            values = mapping.photo_values(photo, receipt=receipt)
            photo.id = (
                await self._session.execute(
                    insert(ReceiptPhoto).values(**values).returning(ReceiptPhoto.id)
                )
            ).scalar_one()

    async def _upsert_parse(self, receipt: Receipt) -> None:
        """Insert the receipt's parse row, or overwrite the one it has, keeping its id."""
        parse = receipt.parse
        if parse is None:  # nothing to store
            return
        values = mapping.parse_values(parse, receipt_id=receipt.id)
        statement = pg_insert(ReceiptParse).values(**values)
        parse_id = (
            await self._session.execute(
                statement.on_conflict_do_update(
                    index_elements=[ReceiptParse.receipt_id],
                    set_={k: v for k, v in values.items() if k != "receipt_id"},
                ).returning(ReceiptParse.id)
            )
        ).scalar_one()
        receipt.parse = replace(parse, id=parse_id)

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
        parse = receipt.parse
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
