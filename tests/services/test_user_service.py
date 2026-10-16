import pytest

from src.exception import UserNotFound
from src.services.user import UserService


async def test_ensure_creates_a_stranger_who_is_not_allowed(make_uow):
    user = await UserService(make_uow).ensure(7, "ann", "Ann")

    assert (user.id, user.username, user.is_allowed) == (7, "ann", False)


async def test_ensure_refreshes_names_and_keeps_access(make_uow):
    service = UserService(make_uow)
    await service.ensure(7, "old", "Ann")
    await service.allow(7)

    user = await service.ensure(7, "new", "Anna")

    assert (user.username, user.first_name, user.is_allowed) == ("new", "Anna", True)


async def test_allow_of_an_unknown_user_is_an_app_exception(make_uow):
    with pytest.raises(UserNotFound):
        await UserService(make_uow).allow(404)
