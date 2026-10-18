import pytest


@pytest.fixture
def screen_ttl_minutes() -> int:
    return 0


async def test_with_the_ttl_at_zero_nothing_is_tracked(harness, allow_user):
    await allow_user(7)
    await harness.send_text("/start", user_id=7)

    await harness.sweep(after_minutes=600)

    assert not harness.screens.enabled
    assert harness.deleted_messages == []
