import pytest

from src.database.dto.user import NewUserDTO


async def test_writes_without_commit_are_not_visible_to_a_new_unit_of_work(make_uow):
    async with make_uow() as uow:
        await uow.users.upsert(NewUserDTO(id=1, username="ann", first_name="Ann"))

    async with make_uow() as uow:
        assert await uow.users.get(1) is None


async def test_writes_with_commit_are_visible_to_a_new_unit_of_work(make_uow):
    async with make_uow() as uow:
        await uow.users.upsert(NewUserDTO(id=1, username="ann", first_name="Ann"))
        await uow.commit()

    async with make_uow() as uow:
        user = await uow.users.get(1)
    assert user is not None
    assert (user.username, user.first_name, user.is_allowed) == ("ann", "Ann", False)


async def test_an_exception_inside_the_block_rolls_back(make_uow):
    with pytest.raises(RuntimeError):
        async with make_uow() as uow:
            await uow.users.upsert(NewUserDTO(id=1, username=None, first_name=None))
            raise RuntimeError

    async with make_uow() as uow:
        assert await uow.users.get(1) is None


async def test_upsert_refreshes_names_and_keeps_access(make_uow):
    async with make_uow() as uow:
        await uow.users.upsert(NewUserDTO(id=1, username="old", first_name="Ann"))
        await uow.users.set_allowed(1, True)
        await uow.commit()

    async with make_uow() as uow:
        user = await uow.users.upsert(NewUserDTO(id=1, username="new", first_name="Anna"))
        await uow.commit()

    assert (user.username, user.first_name, user.is_allowed) == ("new", "Anna", True)


async def test_set_allowed_on_unknown_user_returns_none(make_uow):
    async with make_uow() as uow:
        assert await uow.users.set_allowed(404, True) is None
