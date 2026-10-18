"""One suite over both screen stores; the Redis one runs against a real Redis (TEST_REDIS_URL)."""

import os

import pytest
from redis.asyncio import Redis

from src.bot.screens import MemoryScreenStore, Screen, ScreenKind
from src.bot.screens_redis import DUE_KEY, RedisScreenStore

TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6390/1")

A = Screen(chat_id=1, message_id=10, kind=ScreenKind.PLAIN)
B = Screen(chat_id=1, message_id=11, kind=ScreenKind.ENTRY)
C = Screen(chat_id=-5, message_id=12, kind=ScreenKind.PLAIN)


@pytest.fixture(params=["memory", "redis"])
async def store(request):
    if request.param == "memory":
        yield MemoryScreenStore()
        return
    client = Redis.from_url(TEST_REDIS_URL)
    await client.delete(DUE_KEY)
    yield RedisScreenStore(client)
    await client.delete(DUE_KEY)
    await client.aclose()


async def test_a_screen_is_due_once_its_time_has_come(store):
    await store.add(A, 100.0)

    assert await store.due(99.9) == []
    assert await store.due(100.0) == [A]


async def test_due_removes_what_it_returns(store):
    await store.add(A, 100.0)

    assert await store.due(200.0) == [A]
    assert await store.due(200.0) == []


async def test_due_is_ordered_by_time_and_leaves_later_screens(store):
    await store.add(B, 300.0)
    await store.add(A, 100.0)
    await store.add(C, 200.0)

    assert await store.due(250.0) == [A, C]
    assert await store.due(400.0) == [B]


async def test_update_moves_a_tracked_screen(store):
    await store.add(A, 100.0)

    await store.update(A, 500.0)

    assert await store.due(400.0) == []
    assert await store.due(500.0) == [A]


async def test_update_leaves_an_untracked_screen_untracked(store):
    await store.update(A, 500.0)

    assert await store.due(10_000.0) == []


async def test_remove_drops_the_screen(store):
    await store.add(A, 100.0)

    await store.remove(A)

    assert await store.due(1000.0) == []


async def test_add_again_replaces_the_time(store):
    await store.add(A, 100.0)
    await store.add(A, 900.0)

    assert await store.due(500.0) == []
    assert await store.due(900.0) == [A]


async def test_the_redis_store_uses_one_sorted_set_with_readable_members():
    client = Redis.from_url(TEST_REDIS_URL)
    await client.delete(DUE_KEY)
    try:
        await RedisScreenStore(client).add(C, 42.0)
        assert await client.zrange(DUE_KEY, 0, -1, withscores=True) == [(b"-5:12:plain", 42.0)]
    finally:
        await client.delete(DUE_KEY)
        await client.aclose()


async def test_tracked_tells_a_tracked_screen_from_an_untracked_one(store):
    await store.add(A, 100.0)

    assert await store.tracked(A)
    assert not await store.tracked(B)
