"""What handlers do with the screen registry, so each call site is one line."""

from aiogram.types import Message

from src.bot.screens import Screen, ScreenRegistry


def screen_of(message: Message) -> Screen:
    return Screen(message.chat.id, message.message_id)


async def track_sent(screens: ScreenRegistry, sent: Message) -> None:
    """Start the clock of a screen that was just sent."""
    await screens.track(screen_of(sent))


async def touch_tapped(screens: ScreenRegistry, message: Message) -> None:
    """A tap on a screen's button gives it another TTL."""
    await screens.touch(screen_of(message))
