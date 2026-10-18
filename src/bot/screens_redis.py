from redis.asyncio import Redis

from src.bot.screens import Screen, ScreenKind

DUE_KEY = "screens:due"


def _member(screen: Screen) -> str:
    return f"{screen.chat_id}:{screen.message_id}:{screen.kind.value}"


def _screen(member: bytes | str) -> Screen:
    text = member.decode() if isinstance(member, bytes) else member
    chat_id, message_id, kind = text.rsplit(":", 2)
    return Screen(int(chat_id), int(message_id), ScreenKind(kind))


class RedisScreenStore:
    """One sorted set: the member is `chat_id:message_id:kind`, the score the due unix time."""

    def __init__(self, client: Redis) -> None:
        self._redis = client

    async def add(self, screen: Screen, due_at: float) -> None:
        await self._redis.zadd(DUE_KEY, {_member(screen): due_at})

    async def update(self, screen: Screen, due_at: float) -> None:
        await self._redis.zadd(DUE_KEY, {_member(screen): due_at}, xx=True)

    async def remove(self, screen: Screen) -> None:
        await self._redis.zrem(DUE_KEY, _member(screen))

    async def due(self, now: float) -> list[Screen]:
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.zrangebyscore(DUE_KEY, "-inf", now)
            pipe.zremrangebyscore(DUE_KEY, "-inf", now)
            members, _ = await pipe.execute()
        return [_screen(member) for member in members]
