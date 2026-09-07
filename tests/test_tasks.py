import asyncio
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, Mock

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
    manager = tasks.TaskManager(
        replace(Config(), max_queued=1), Storage(tmp_path), Path(sys.executable)
    )
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
    manager = tasks.TaskManager(config, Storage(tmp_path), Path(sys.executable))
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
    kill = Mock()
    monkeypatch.setattr(tasks.os, "killpg", kill)
    entered = asyncio.Event()

    async def communicate(*args):
        entered.set()
        await asyncio.Event().wait()

    process.communicate.side_effect = communicate
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    task = asyncio.create_task(
        tasks.run_worker(Request("fetch", "123"), Config(), tmp_path, Path(sys.executable))
    )
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    kill.assert_called_once()
    process.wait.assert_awaited_once()


async def test_close_cancels_acceptance_notification(tmp_path):
    entered = asyncio.Event()

    async def notify(text):
        entered.set()
        await asyncio.Event().wait()

    manager = tasks.TaskManager(Config(), Storage(tmp_path), Path(sys.executable))
    await manager.submit("1", Request("brief", "123"), notify, AsyncMock())
    await entered.wait()
    await manager.close()
    assert manager.pending == 0 and not manager.active and not manager.tasks


async def test_close_before_first_task_step(tmp_path):
    manager = tasks.TaskManager(Config(), Storage(tmp_path), Path(sys.executable))
    await manager.submit("1", Request("brief", "123"), AsyncMock(), AsyncMock())
    await manager.close()
    assert manager.pending == 0 and not manager.active


def test_worker_does_not_inherit_parent_dependencies(tmp_path):
    poison = tmp_path / "poison"
    poison.mkdir()
    (poison / "jmcomic.py").write_text("raise RuntimeError('host package leaked')")
    script = """
import asyncio, sys
from dataclasses import replace
from pathlib import Path
sys.path.insert(0, sys.argv[3])
from jm_comic_fetcher.tasks import run_worker
from jm_comic_fetcher.config import Config
from jm_comic_fetcher.models import Request
result = asyncio.run(run_worker(
    Request('brief', '123'), replace(Config(), max_running=0),
    Path(sys.argv[1]), Path(sys.argv[2])
))
assert result == {'error': 'Config max_running must be an integer >= 1.'}, result
assert 'jmcomic' not in sys.modules
"""
    environment = dict(os.environ, PYTHONPATH=str(poison))
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path), sys.executable, str(poison)],
        env=environment,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


async def test_missing_dependency_error_is_actionable_and_redacted(tmp_path, monkeypatch):
    process = AsyncMock()
    process.returncode = 1
    process.communicate.return_value = (
        b"",
        b"secret proxy credentials\nModuleNotFoundError: No module named 'jmcomic'\n",
    )
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    with pytest.raises(UserError) as exc:
        await tasks.run_worker(Request("fetch", "123"), Config(), tmp_path, Path(sys.executable))
    assert (
        str(exc.value)
        == "Worker could not complete (missing dependency jmcomic); no archive was sent."
    )
