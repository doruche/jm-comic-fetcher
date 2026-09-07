"""Private, lockfile-controlled worker environments. No third-party host imports."""

import asyncio
import fcntl
import hashlib
import json
import os
import platform
import shutil
import signal
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = "https://pypi.org/simple"
SETUP_TIMEOUT = 600


def worker_environment() -> dict[str, str]:
    # Preserve networking/certificates, but never inherit Python/package-manager settings.
    return {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("PYTHON", "UV_", "PIP_"))
        and key not in {"VIRTUAL_ENV", "CONDA_PREFIX"}
    }


def worker_command(python: Path, *, probe: bool = False) -> list[str]:
    # -I excludes cwd, PYTHONPATH and user site-packages. Only our source is added.
    code = f"import sys; sys.path.insert(0, {str(ROOT)!r}); "
    code += (
        "import jm_comic_fetcher.worker"
        if probe
        else "from jm_comic_fetcher.worker import main; main()"
    )
    return [str(python), "-I", "-c", code]


async def checked_process(arguments: list[str], environment: dict[str, str]) -> None:
    process = await asyncio.create_subprocess_exec(
        *arguments,
        cwd=ROOT,
        env=environment,
        start_new_session=True,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        await process.communicate()
        if process.returncode:
            # Do not expose index/proxy credentials or arbitrary upstream output.
            raise RuntimeError(
                f"Worker environment command failed (exit {process.returncode}). "
                "Check PyPI connectivity, disk space and the supported Python/uv versions."
            )
    finally:
        if process.returncode is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await process.wait()


class Runtime:
    def __init__(self, data_directory: Path):
        base = Path(getattr(sys, "_base_executable", sys.executable)).resolve()
        stat = base.stat()
        identity = json.dumps(
            [
                str(base),
                stat.st_size,
                stat.st_mtime_ns,
                sys.version,
                platform.machine(),
                platform.libc_ver(),
            ]
        ).encode()
        digest = hashlib.sha256(identity)
        for name in ("pyproject.toml", "uv.lock"):
            digest.update((ROOT / name).read_bytes())
        self.root = data_directory / "runtime"
        self.environment = self.root / digest.hexdigest()[:24]
        self.python = self.environment / "bin" / "python"
        self.base = base

    async def prepare(self) -> None:
        """Serialize setup; publish readiness only after a real worker import succeeds."""
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            async with asyncio.timeout(SETUP_TIMEOUT):
                with (self.root / "setup.lock").open("a") as lock:
                    while True:
                        try:
                            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                            break
                        except BlockingIOError:
                            await asyncio.sleep(0.1)
                    await self._prepare_locked()
        except TimeoutError as exc:
            raise RuntimeError(
                "Worker environment setup timed out; reload the plugin to retry."
            ) from exc

    async def _prepare_locked(self) -> None:
        environment = worker_environment()
        ready = self.environment / ".ready"
        if ready.is_file():
            try:
                await checked_process(worker_command(self.python, probe=True), environment)
                return
            except (RuntimeError, OSError):
                ready.unlink()
        uv = shutil.which("uv", path=environment.get("PATH"))
        if uv is None:
            raise RuntimeError(
                "JM Comic Fetcher requires uv >= 0.12.5 on AstrBot's PATH. "
                "Install uv in the environment running AstrBot, then reload the plugin."
            )
        # An interrupted install is never reused. Other generations remain untouched.
        if self.environment.exists():
            shutil.rmtree(self.environment)
        environment["UV_PROJECT_ENVIRONMENT"] = str(self.environment)
        environment["UV_CACHE_DIR"] = str(self.root / "cache")
        await checked_process(
            [
                uv,
                "sync",
                "--project",
                str(ROOT),
                "--locked",
                "--no-default-groups",
                "--no-config",
                "--default-index",
                INDEX,
                "--python",
                str(self.base),
                "--no-python-downloads",
                "--no-install-project",
                "--link-mode",
                "copy",
            ],
            environment,
        )
        await checked_process(worker_command(self.python, probe=True), worker_environment())
        ready.touch()
