import asyncio
import json
import logging
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from .config import Config
from .models import Request, UserError
from .storage import Storage

logger = logging.getLogger(__name__)


async def run_worker(request: Request, config: Config, directory: Path) -> dict:
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "jm_comic_fetcher.worker",
        cwd=Path(__file__).resolve().parent.parent,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        payload = {
            "request": asdict(request),
            "config": config.worker_config(),
            "directory": str(directory),
        }
        output, _ = await process.communicate(json.dumps(payload).encode())
        if process.returncode:
            raise UserError("Worker exited unexpectedly; no archive was sent.")
        try:
            return json.loads(output)
        except (ValueError, UnicodeError) as exc:
            raise UserError("Worker returned an invalid result; no archive was sent.") from exc
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


class TaskManager:
    def __init__(self, config: Config, storage: Storage):
        self.config = config
        self.storage = storage
        self.slots = asyncio.Semaphore(config.max_running)
        self.owners = Counter()
        self.tasks: set[asyncio.Task] = set()
        self.active: set[Path] = set()
        self.pending = 0
        self.closed = False
        self.cleanup_task = None

    async def start(self) -> None:
        await asyncio.to_thread(self.storage.cleanup, self.config, set())
        self.cleanup_task = asyncio.create_task(self._clean_loop())

    async def submit(self, owner: str, request: Request, notify, deliver) -> str:
        if self.closed:
            raise UserError("Plugin is shutting down. Try again after reload.")
        if self.owners[owner] >= self.config.max_pending_per_user:
            raise UserError("You already have the maximum number of pending tasks.")
        if self.pending >= self.config.max_running + self.config.max_queued:
            raise UserError("The task queue is full. Try again later.")
        directory = self.storage.create(self.config)
        self.pending += 1
        self.owners[owner] += 1
        self.active.add(directory)
        try:
            await notify(
                f"Task {directory.name[:8]} accepted: {request.action} {request.comic_id}."
            )
            if self.closed:
                raise UserError("Plugin was reloaded before the task could start.")
        except BaseException:
            self._release(owner, directory, False)
            raise
        task = asyncio.create_task(self._execute(owner, request, directory, notify, deliver))
        self.tasks.add(task)

        def done(finished):
            self.tasks.discard(finished)
            # A task cancelled before its first step never enters _execute's finally.
            if directory in self.active:
                self._release(owner, directory, False)

        task.add_done_callback(done)
        return directory.name

    def _release(self, owner: str, directory: Path, success: bool) -> None:
        self.pending -= 1
        self.owners[owner] -= 1
        if self.owners[owner] == 0:
            del self.owners[owner]
        try:
            self.storage.finish(directory, success)
        finally:
            self.active.discard(directory)

    async def _execute(self, owner, request, directory, notify, deliver) -> None:
        success = False
        try:
            async with self.slots:
                async with asyncio.timeout(self.config.timeout_seconds):
                    result = await run_worker(request, self.config, directory)
                    if "error" in result:
                        raise UserError(result["error"])
                    if "archive" in result:
                        archive = directory / result["archive"]
                        if archive.resolve().parent != directory or not archive.is_file():
                            raise UserError("Worker produced an invalid archive path.")
                        await deliver(archive)
                    await notify(result["text"])
                    success = True
        except TimeoutError:
            await self._report(notify, f"Task {directory.name[:8]} timed out and was stopped.")
        except UserError as exc:
            await self._report(notify, f"Task {directory.name[:8]} failed: {exc}")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Task %s failed: %s", directory.name, type(exc).__name__)
            await self._report(
                notify,
                f"Task {directory.name[:8]} failed ({type(exc).__name__}); "
                "the upload may not have completed.",
            )
        finally:
            self._release(owner, directory, success)

    @staticmethod
    async def _report(notify, text):
        try:
            async with asyncio.timeout(15):
                await notify(text)
        except Exception as exc:
            logger.warning("Cannot report task failure: %s", type(exc).__name__)

    async def _clean_loop(self):
        while True:
            await asyncio.sleep(self.config.cleanup_interval_minutes * 60)
            try:
                await asyncio.to_thread(self.storage.cleanup, self.config, set(self.active))
            except OSError as exc:
                logger.warning("Job cleanup failed: %s", type(exc).__name__)

    async def close(self):
        self.closed = True
        tasks = list(self.tasks)
        if self.cleanup_task:
            tasks.append(self.cleanup_task)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
