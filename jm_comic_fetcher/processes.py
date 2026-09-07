"""Owned asynchronous work: cancellation finishes cleanup before returning."""

import asyncio
import os
import signal
from dataclasses import dataclass
from pathlib import Path


async def wait_owned[T](task: asyncio.Future[T]) -> T:
    """Wait for owned work even if its caller is cancelled, then propagate cancellation."""
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            break
    if cancelled:
        if not task.cancelled():
            task.exception()  # Retrieve failure while preserving the caller's cancellation.
        raise asyncio.CancelledError
    return task.result()


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: bytes
    stderr: bytes


async def run_process(
    arguments: list[str], *, cwd: Path, environment: dict[str, str], input_data: bytes = b""
) -> ProcessResult:
    """Run a private process group and reap it on success, failure or cancellation."""
    spawn = asyncio.create_task(
        asyncio.create_subprocess_exec(
            *arguments,
            cwd=cwd,
            env=environment,
            start_new_session=True,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    )
    process = None
    try:
        # Shield acquisition so cancellation cannot lose a just-created process.
        process = await asyncio.shield(spawn)
        output, errors = await process.communicate(input_data)
        return ProcessResult(process.returncode, output, errors)
    finally:

        async def reap():
            child = process if process is not None else await spawn
            # A dead parent may leave descendants holding pipes or writing files.
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            # Drain pipes as well as wait: wait alone can deadlock on buffered output.
            await child.communicate()
            await child.wait()

        await wait_owned(asyncio.create_task(reap()))
