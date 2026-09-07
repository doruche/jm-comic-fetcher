import asyncio
import os
import signal
import sys
from pathlib import Path

import pytest

from jm_comic_fetcher.processes import run_process


async def until(predicate):
    async with asyncio.timeout(5):
        while not predicate():  # noqa: ASYNC110 - observing an external process
            await asyncio.sleep(0.01)


def stopped(pid):
    try:
        return Path(f"/proc/{pid}/stat").read_text().split()[2] == "Z"
    except FileNotFoundError:
        return True


async def test_io_and_exit_code(tmp_path):
    result = await run_process(
        [
            sys.executable,
            "-c",
            "import sys; print(sys.stdin.read()); print('error', file=sys.stderr); sys.exit(7)",
        ],
        cwd=tmp_path,
        environment=dict(os.environ),
        input_data=b"request",
    )
    assert result.returncode == 7
    assert result.stdout == b"request\n" and result.stderr == b"error\n"


@pytest.mark.parametrize("parent_exits", [False, True])
async def test_timeout_stops_group_even_after_parent_exits(tmp_path, parent_exits):
    child_code = "import os,time; open('child','w').write(str(os.getpid())); time.sleep(60)"
    code = (
        "import subprocess,sys,os,time; open('parent','w').write(str(os.getpid())); "
        f"subprocess.Popen([sys.executable,'-c',{child_code!r}]); "
        + ("sys.exit(0)" if parent_exits else "time.sleep(60)")
    )

    # Exercise asyncio.timeout, which is the caller's actual cancellation mechanism.
    async def run():
        async with asyncio.timeout(1):
            await run_process(
                [sys.executable, "-c", code], cwd=tmp_path, environment=dict(os.environ)
            )

    task = asyncio.create_task(run())
    pid = None
    try:
        await until(lambda: (tmp_path / "child").exists() and (tmp_path / "child").stat().st_size)
        pid = int((tmp_path / "child").read_text())
        if parent_exits:
            parent = int((tmp_path / "parent").read_text())
            await until(lambda: stopped(parent))
            assert not task.done(), "The descendant must still hold the output pipe"
        with pytest.raises(TimeoutError):
            await task
        await until(lambda: stopped(pid))
    finally:
        if pid and not stopped(pid):
            os.kill(pid, signal.SIGKILL)
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_cancellation_during_spawn_does_not_lose_process(tmp_path, monkeypatch):
    create = asyncio.create_subprocess_exec
    acquired = asyncio.Event()
    release = asyncio.Event()
    processes = []

    async def delayed(*args, **kwargs):
        process = await create(*args, **kwargs)
        processes.append(process)
        acquired.set()
        await release.wait()
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", delayed)
    task = asyncio.create_task(
        run_process(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            cwd=tmp_path,
            environment=dict(os.environ),
        )
    )
    await acquired.wait()
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()  # Repeated cancellation must not cancel the reaper.
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert processes[0].returncode is not None


async def test_cancellation_wins_over_cleanup_failure():
    from jm_comic_fetcher.processes import wait_owned

    future = asyncio.get_running_loop().create_future()
    caller = asyncio.create_task(wait_owned(future))
    await asyncio.sleep(0)
    caller.cancel()
    await asyncio.sleep(0)
    future.set_exception(OSError("cleanup failed"))
    with pytest.raises(asyncio.CancelledError):
        await caller
