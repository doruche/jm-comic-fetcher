import asyncio
import json
import logging
import re
from collections import Counter
from pathlib import Path

from .config import Config
from .diagnostics import log_worker_diagnostic, process_failure, report
from .models import DeliveryRejected, JobState, Request, UserError
from .processes import run_process, wait_owned
from .protocol import WorkerRequest, WorkerResult
from .runtime import worker_command, worker_environment
from .storage import Storage

logger = logging.getLogger(__name__)


async def run_worker(
    request: Request, config: Config, directory: Path, python: Path
) -> WorkerResult:
    payload = WorkerRequest(request, config, directory).to_dict()
    result = await run_process(
        worker_command(python),
        cwd=directory,
        environment=worker_environment(),
        input_data=json.dumps(payload).encode(),
    )
    if result.returncode:
        process_failure(
            result.stderr, task=directory.name, stage="worker", returncode=result.returncode
        )
        missing = re.search(
            rb"ModuleNotFoundError: No module named '([A-Za-z0-9_.]+)'", result.stderr
        )
        detail = (
            f"missing dependency {missing[1].decode('ascii')}"
            if missing
            else f"exit code {result.returncode}"
        )
        raise UserError(f"Worker could not complete ({detail}); no archive was sent.")
    try:
        message = WorkerResult.from_dict(json.loads(result.stdout))
        if message.status == "error":
            log_worker_diagnostic(result.stderr, directory.name, message.stage)
        return message
    except (ValueError, UnicodeError) as exc:
        raise UserError("Worker returned an invalid result; no archive was sent.") from exc


class TaskManager:
    def __init__(self, config: Config, storage: Storage, python: Path):
        self.config = config
        self.python = python
        self.storage = storage
        self.slots = asyncio.Semaphore(config.max_running)
        self.owners = Counter()
        self.tasks: set[asyncio.Task] = set()
        self.active: set[Path] = set()
        self.pending = 0
        self.closed = False
        self.cleanup_task = None

    async def start(self) -> None:
        if self.closed:
            return
        await self._cleanup()
        if self.closed:
            return
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
        task = asyncio.create_task(self._execute(owner, request, directory, notify, deliver))
        self.tasks.add(task)

        def done(finished):
            self.tasks.discard(finished)
            # A task cancelled before its first step never enters _execute's finally.
            if directory in self.active:
                self._release(owner, directory, JobState(outcome="cancelled"))

        task.add_done_callback(done)
        return directory.name

    def _release(self, owner: str, directory: Path, state: JobState) -> None:
        self.pending -= 1
        self.owners[owner] -= 1
        if self.owners[owner] == 0:
            del self.owners[owner]
        try:
            self.storage.finish(directory, state)
        except OSError as exc:
            report(exc, task=directory.name, stage="state")
        finally:
            self.active.discard(directory)

    async def _execute(self, owner, request, directory, notify, deliver) -> None:
        state = JobState()
        try:
            async with asyncio.timeout(30):
                await notify(
                    f"Task {directory.name[:8]} accepted: "
                    f"{request.action}{' ' + request.comic_id if request.comic_id else ''}."
                )
            state.stage = "queue"
            async with self.slots:
                async with asyncio.timeout(self.config.timeout_seconds):
                    state.stage = "generation"
                    state.generation = "running"
                    result = await run_worker(request, self.config, directory, self.python)
                    if result.status == "error":
                        state.stage = result.stage
                        raise UserError(result.text)
                    state.generation = "succeeded"
                    if result.archive is not None:
                        state.stage = "publication"
                        archive = directory / result.archive
                        if archive.resolve().parent != directory or not archive.is_file():
                            raise UserError("Worker produced an invalid archive path.")
                        published = self.storage.publish(archive)
                        state.stage = "delivery"
                        # Once the call begins, an exception/cancellation cannot prove non-delivery.
                        state.delivery = "unknown"
                        try:
                            await deliver(published)
                        except DeliveryRejected:
                            state.delivery = "rejected"
                            raise
                        state.delivery = "accepted"
                        state.outcome = "succeeded"
                    state.stage = "notification"
                    state.notification = "unknown"
                    await notify(result.text)
                    state.notification = "sent"
                    state.outcome = "succeeded"
        except asyncio.CancelledError:
            self._failed_state(state, cancelled=True)
            raise
        except Exception as exc:
            self._failed_state(state)
            report(exc, task=directory.name, stage=state.stage)
            if state.delivery == "accepted":
                # The archive was sent; a follow-up text failure cannot undo delivery.
                pass
            elif state.delivery == "unknown":
                await self._report(
                    notify,
                    f"Task {directory.name[:8]}: file delivery could not be confirmed. "
                    "Check the chat before retrying.",
                )
            elif state.notification == "unknown":
                await self._report(
                    notify,
                    f"Task {directory.name[:8]}: result notification could not be confirmed.",
                )
            elif isinstance(exc, TimeoutError):
                await self._report(notify, f"Task {directory.name[:8]} timed out and was stopped.")
            else:
                detail = str(exc) if isinstance(exc, UserError) else f"Error during {state.stage}."
                await self._report(notify, f"Task {directory.name[:8]} failed: {detail}")
        finally:
            self._release(owner, directory, state)

    @staticmethod
    def _failed_state(state: JobState, *, cancelled: bool = False) -> None:
        if state.generation == "running":
            state.generation = "cancelled" if cancelled else "failed"
        if state.delivery == "accepted":
            state.outcome = "succeeded"
        elif state.delivery == "unknown" or state.notification == "unknown":
            state.outcome = "uncertain"
        else:
            state.outcome = "cancelled" if cancelled else "failed"

    @staticmethod
    async def _report(notify, text):
        try:
            async with asyncio.timeout(15):
                await notify(text)
        except Exception as exc:
            logger.warning("Cannot report task failure: %s", type(exc).__name__)

    async def _cleanup(self):
        await wait_owned(
            asyncio.create_task(
                asyncio.to_thread(self.storage.cleanup, self.config, set(self.active))
            )
        )

    async def _clean_loop(self):
        while True:
            await asyncio.sleep(self.config.cleanup_interval_minutes * 60)
            try:
                await self._cleanup()
            except OSError as exc:
                logger.warning("Job cleanup failed: %s", type(exc).__name__)

    async def close(self):
        self.closed = True
        tasks = list(self.tasks)
        if self.cleanup_task:
            tasks.append(self.cleanup_task)
        for task in tasks:
            task.cancel()
        await wait_owned(asyncio.gather(*tasks, return_exceptions=True))
