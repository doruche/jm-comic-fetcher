import asyncio
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from jm_comic_fetcher import tasks
from jm_comic_fetcher.config import Config
from jm_comic_fetcher.models import Request, UserError
from jm_comic_fetcher.processes import ProcessResult
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
assert result.status == 'error', result
assert result.text == 'Config max_running must be an integer >= 1.', result
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
    result = ProcessResult(
        1, b"", b"secret proxy credentials\nModuleNotFoundError: No module named 'jmcomic'\n"
    )
    monkeypatch.setattr(tasks, "run_process", AsyncMock(return_value=result))
    with pytest.raises(UserError) as exc:
        await tasks.run_worker(Request("fetch", "123"), Config(), tmp_path, Path(sys.executable))
    assert (
        str(exc.value)
        == "Worker could not complete (missing dependency jmcomic); no archive was sent."
    )


async def test_unload_waits_for_cleanup_thread_before_reload(tmp_path, monkeypatch):
    import threading

    storage = Storage(tmp_path)
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    original = storage.cleanup
    calls = 0

    def cleanup(*args):
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            assert release.wait(5)
            try:
                return original(*args)
            finally:
                finished.set()
        assert finished.is_set(), "New initialization overlapped the old cleanup thread"
        return original(*args)

    monkeypatch.setattr(storage, "cleanup", cleanup)
    old = tasks.TaskManager(Config(), storage, Path(sys.executable))
    old.cleanup_task = asyncio.create_task(old._cleanup())
    async with asyncio.timeout(5):
        while not entered.is_set():  # noqa: ASYNC110 - observing a worker thread
            await asyncio.sleep(0.01)
    closing = asyncio.create_task(old.close())
    try:
        await asyncio.sleep(0.02)
        assert not closing.done() and not finished.is_set()
    finally:
        release.set()
        await closing
    new = tasks.TaskManager(Config(), storage, Path(sys.executable))
    await new.start()
    await new.close()


@pytest.mark.parametrize("notification_error", [OSError, TimeoutError, asyncio.CancelledError])
async def test_sent_archive_remains_success_when_notification_fails(
    tmp_path, monkeypatch, notification_error
):
    import json

    from jm_comic_fetcher.protocol import WorkerResult

    async def worker(request, config, directory, python):
        (directory / "result.zip").write_bytes(b"PK fixture")
        return WorkerResult("ok", "Completed", "result.zip")

    async def notify(text):
        if text == "Completed":
            raise notification_error()

    monkeypatch.setattr(tasks, "run_worker", worker)
    manager = tasks.TaskManager(Config(), Storage(tmp_path), Path(sys.executable))
    deliver = AsyncMock()
    job = await manager.submit("1", Request("fetch", "123"), notify, deliver)
    await asyncio.gather(*manager.tasks, return_exceptions=True)
    state = json.loads((manager.storage.jobs / job / "state.json").read_text())
    assert state["success"] is True and state["outcome"] == "succeeded"
    assert state["generation"] == "succeeded"
    assert state["delivery"] == "accepted" and state["notification"] == "unknown"
    deliver.assert_awaited_once()
    await manager.close()


@pytest.mark.parametrize(
    "failure,delivery,outcome",
    [
        (TimeoutError, "unknown", "uncertain"),
        (OSError, "unknown", "uncertain"),
        (asyncio.CancelledError, "unknown", "uncertain"),
    ],
)
async def test_unconfirmed_send_is_not_reported_as_definite_failure(
    tmp_path, monkeypatch, failure, delivery, outcome
):
    import json

    from jm_comic_fetcher.protocol import WorkerResult

    async def worker(request, config, directory, python):
        (directory / "result.zip").write_bytes(b"PK fixture")
        return WorkerResult("ok", "Completed", "result.zip")

    async def send(path):
        raise failure()

    monkeypatch.setattr(tasks, "run_worker", worker)
    manager = tasks.TaskManager(Config(), Storage(tmp_path), Path(sys.executable))
    notify = AsyncMock()
    job = await manager.submit("1", Request("fetch", "123"), notify, send)
    await asyncio.gather(*manager.tasks, return_exceptions=True)
    state = json.loads((manager.storage.jobs / job / "state.json").read_text())
    assert state["delivery"] == delivery and state["outcome"] == outcome
    assert state["success"] is False and state["generation"] == "succeeded"
    if failure != asyncio.CancelledError:
        assert "could not be confirmed" in notify.call_args.args[0]
    await manager.close()


async def test_explicit_send_rejection(tmp_path, monkeypatch):
    import json

    from jm_comic_fetcher.models import DeliveryRejected
    from jm_comic_fetcher.protocol import WorkerResult

    async def worker(request, config, directory, python):
        (directory / "result.zip").write_bytes(b"PK fixture")
        return WorkerResult("ok", "Completed", "result.zip")

    monkeypatch.setattr(tasks, "run_worker", worker)
    manager = tasks.TaskManager(Config(), Storage(tmp_path), Path(sys.executable))
    job = await manager.submit(
        "1",
        Request("fetch", "123"),
        AsyncMock(),
        AsyncMock(side_effect=DeliveryRejected("Unavailable")),
    )
    await asyncio.gather(*manager.tasks)
    state = json.loads((manager.storage.jobs / job / "state.json").read_text())
    assert state["delivery"] == "rejected" and state["outcome"] == "failed"
    await manager.close()


@pytest.mark.parametrize("fails", [False, True])
@pytest.mark.parametrize("job_request", [Request("brief", "123"), Request("random", "")])
async def test_text_result_requires_notification(tmp_path, monkeypatch, fails, job_request):
    import json

    from jm_comic_fetcher.protocol import WorkerResult

    monkeypatch.setattr(tasks, "run_worker", AsyncMock(return_value=WorkerResult("ok", "Summary")))

    async def notify(text):
        if fails and text == "Summary":
            raise TimeoutError()

    manager = tasks.TaskManager(Config(), Storage(tmp_path), Path(sys.executable))
    deliver = AsyncMock()
    job = await manager.submit("1", job_request, notify, deliver)
    await asyncio.gather(*manager.tasks)
    state = json.loads((manager.storage.jobs / job / "state.json").read_text())
    assert state["success"] is (not fails)
    assert state["delivery"] == "not_started"
    deliver.assert_not_awaited()
    await manager.close()
