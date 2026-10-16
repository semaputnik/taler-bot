import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import (
    Receipt,
    ReceiptParse,
    ReceiptPhoto,
    User,
)
from src.domain.enums import ParseStatus
from tests.helpers import NOW


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
