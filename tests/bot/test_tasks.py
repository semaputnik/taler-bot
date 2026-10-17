import asyncio

from src.bot.tasks import TaskRegistry


async def test_is_running_is_true_only_while_the_named_task_runs():
    tasks = TaskRegistry()
    gate = asyncio.Event()
    tasks.spawn(gate.wait(), name="one")

    assert tasks.is_running("one")
    assert not tasks.is_running("two")
    gate.set()
    await tasks.drain()
    assert not tasks.is_running("one")
