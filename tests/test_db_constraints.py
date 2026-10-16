from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import (
    Receipt,
    ReceiptItem,
    ReceiptParse,
    ReceiptPhoto,
    Store,
    StoreProduct,
    User,
)
from src.domain.enums import ParseStatus, ReceiptStatus

NOW = datetime(2026, 10, 14, 18, 32, tzinfo=UTC)


async def make_user(session: AsyncSession, user_id: int = 1) -> User:
    user = User(id=user_id, is_allowed=True)
    session.add(user)
    await session.flush()
    return user


async def make_receipt(session: AsyncSession, user: User, **fields) -> Receipt:
    receipt = Receipt(user_id=user.id, **fields)
    session.add(receipt)
    await session.flush()
    return receipt


async def assert_rejected(session: AsyncSession, row) -> None:
    with pytest.raises(IntegrityError):
        # Added inside the savepoint, so its rollback also discards the rejected row.
        async with session.begin_nested():
            session.add(row)
            await session.flush()


async def test_parsed_receipt_key_is_unique_per_user(session: AsyncSession) -> None:
    user = await make_user(session)
    other = await make_user(session, 2)
    key = "mercadona|A-123|2026-10-14|47.85"
    await make_receipt(session, user, status=ReceiptStatus.PARSED, receipt_key=key)

    await make_receipt(session, other, status=ReceiptStatus.PARSED, receipt_key=key)
    await make_receipt(session, user, status=ReceiptStatus.AWAITING_MATCH, receipt_key=key)
    await make_receipt(session, user, status=ReceiptStatus.PARSED, receipt_key=key, deleted_at=NOW)
    await assert_rejected(
        session, Receipt(user_id=user.id, status=ReceiptStatus.PARSED, receipt_key=key)
    )


async def test_same_telegram_file_is_rejected(session: AsyncSession) -> None:
    user = await make_user(session)
    receipt = await make_receipt(session, user)

    def photo(unique_id: str | None, **fields) -> ReceiptPhoto:
        return ReceiptPhoto(
            receipt_id=receipt.id,
            user_id=user.id,
            telegram_file_unique_id=unique_id,
            received_at=NOW,
            **({"path": "2026/10/a.jpg"} | fields),
        )

    session.add(photo("AQADabc"))
    # Imported n8n photos have no Telegram id; NULLs must not collide.
    session.add_all([photo(None, drive_file_id="d1"), photo(None, drive_file_id="d2")])
    await session.flush()

    await assert_rejected(session, photo("AQADabc"))


async def test_photo_needs_a_location(session: AsyncSession) -> None:
    user = await make_user(session)
    receipt = await make_receipt(session, user)
    await assert_rejected(
        session, ReceiptPhoto(receipt_id=receipt.id, user_id=user.id, received_at=NOW)
    )


@pytest.mark.parametrize("value", ["ab12", "12 3"])
async def test_card_last4_is_four_digits(session: AsyncSession, value: str) -> None:
    user = await make_user(session)
    await assert_rejected(session, Receipt(user_id=user.id, card_last4=value))


async def test_merged_requires_target(session: AsyncSession) -> None:
    user = await make_user(session)
    target = await make_receipt(session, user, status=ReceiptStatus.PARSED)

    await make_receipt(session, user, status=ReceiptStatus.MERGED, merged_into_id=target.id)
    await assert_rejected(session, Receipt(user_id=user.id, status=ReceiptStatus.MERGED))
    await assert_rejected(
        session,
        Receipt(user_id=user.id, status=ReceiptStatus.PARSED, merged_into_id=target.id),
    )


async def test_unknown_status_and_category_are_rejected(session: AsyncSession) -> None:
    user = await make_user(session)
    await assert_rejected(session, Receipt(user_id=user.id, status="duplicate"))

    store = Store(user_id=user.id, store_key="lidl", name="Lidl")
    session.add(store)
    await session.flush()
    await assert_rejected(
        session,
        StoreProduct(
            user_id=user.id,
            store_id=store.id,
            product_key="lidl::pan",
            name="Pan",
            name_raw="PAN",
            category="bread",
        ),
    )


async def test_current_parse_round_trip(session: AsyncSession) -> None:
    user = await make_user(session)
    receipt = await make_receipt(session, user)
    parse = ReceiptParse(
        receipt_id=receipt.id,
        status=ParseStatus.OK,
        parser_version="test",
        photo_ids=[],
        raw_output={"is_receipt": True},
    )
    session.add(parse)
    await session.flush()

    receipt.current_parse_id = parse.id
    await session.flush()
    # Deleting the parse must not delete the receipt, only clear the pointer.
    await session.execute(delete(ReceiptParse).where(ReceiptParse.id == parse.id))
    await session.refresh(receipt)
    assert receipt.current_parse_id is None


async def test_deleting_user_cascades_but_products_in_use_are_protected(
    session: AsyncSession,
) -> None:
    user = await make_user(session)
    store = Store(user_id=user.id, store_key="lidl", name="Lidl")
    session.add(store)
    await session.flush()
    product = StoreProduct(
        user_id=user.id, store_id=store.id, product_key="lidl::pan", name="Pan", name_raw="PAN"
    )
    session.add(product)
    receipt = await make_receipt(session, user, store_id=store.id)
    session.add(
        ReceiptItem(
            receipt_id=receipt.id,
            store_product_id=product.id,
            position=0,
            name_raw="PAN",
            quantity=1,
            unit="pcs",
        )
    )
    await session.flush()

    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            await session.execute(delete(StoreProduct).where(StoreProduct.id == product.id))

    await session.execute(delete(User).where(User.id == user.id))
    for model in (Store, StoreProduct, Receipt, ReceiptItem):
        assert await session.scalar(select(func.count()).select_from(model)) == 0
