import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from jm_comic_fetcher import tasks
from jm_comic_fetcher.config import Config
from jm_comic_fetcher.models import Request, UserError
from jm_comic_fetcher.storage import Storage


async def test_queue_and_user_limits_and_shutdown(tmp_path, monkeypatch):
    running = 0
    maximum = 0
    entered = asyncio.Event()

    async def worker(*args):
        nonlocal running, maximum
        running += 1
        maximum = max(maximum, running)
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            running -= 1

    monkeypatch.setattr(tasks, "run_worker", worker)
    manager = tasks.TaskManager(replace(Config(), max_queued=1), Storage(tmp_path))
    await manager.start()
    notify, deliver = AsyncMock(), AsyncMock()
    await manager.submit("1", Request("fetch", "123"), notify, deliver)
    await entered.wait()
    with pytest.raises(UserError, match="pending"):
        await manager.submit("1", Request("fetch", "123"), notify, deliver)
    await manager.submit("2", Request("fetch", "123"), notify, deliver)
    with pytest.raises(UserError, match="full"):
        await manager.submit("3", Request("fetch", "123"), notify, deliver)
    await asyncio.sleep(0)
    await manager.close()
    assert maximum == 1 and running == 0
    assert manager.pending == 0 and not manager.active
    deliver.assert_not_awaited()


async def test_timeout_cancels_worker_without_upload(tmp_path, monkeypatch):
    cancelled = asyncio.Event()

    async def worker(*args):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(tasks, "run_worker", worker)
    config = replace(Config(), timeout_seconds=0.02)
    manager = tasks.TaskManager(config, Storage(tmp_path))
    notify, deliver = AsyncMock(), AsyncMock()
    await manager.submit("1", Request("fetch", "123"), notify, deliver)
    await asyncio.gather(*manager.tasks)
    assert cancelled.is_set()
    assert "timed out" in notify.call_args.args[0]
    assert manager.pending == 0
    deliver.assert_not_awaited()
    await manager.close()


async def test_subprocess_is_reaped_on_cancellation(tmp_path, monkeypatch):
    process = AsyncMock()
    process.returncode = None
    process.kill = __import__("unittest.mock", fromlist=["Mock"]).Mock()
    entered = asyncio.Event()

    async def communicate(*args):
        entered.set()
        await asyncio.Event().wait()

    process.communicate.side_effect = communicate
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    task = asyncio.create_task(tasks.run_worker(Request("fetch", "123"), Config(), tmp_path))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    process.kill.assert_called_once()
    process.wait.assert_awaited_once()
