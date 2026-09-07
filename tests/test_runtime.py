import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from jm_comic_fetcher import runtime


@pytest.fixture
def fake_setup(monkeypatch):
    installs = []

    async def command(arguments, environment):
        if arguments[1] == "sync":
            installs.append((arguments, environment))
            await asyncio.sleep(0.01)
            Path(environment["UV_PROJECT_ENVIRONMENT"]).mkdir(parents=True)

    monkeypatch.setattr(runtime, "checked_process", command)
    monkeypatch.setattr(runtime.shutil, "which", lambda *args, **kwargs: "/usr/bin/uv")
    return installs


async def test_concurrent_setup_and_reuse(tmp_path, fake_setup):
    first, second = runtime.Runtime(tmp_path), runtime.Runtime(tmp_path)
    await asyncio.gather(first.prepare(), second.prepare())
    await first.prepare()
    assert len(fake_setup) == 1
    assert (first.environment / ".ready").is_file()


async def test_failed_install_retries_from_clean_directory(tmp_path, monkeypatch):
    instance = runtime.Runtime(tmp_path)
    attempts = 0

    async def command(arguments, environment):
        nonlocal attempts
        if arguments[1] == "sync":
            attempts += 1
            assert not instance.environment.exists()
            instance.environment.mkdir()
            if attempts == 1:
                (instance.environment / "partial").touch()
                raise RuntimeError("interrupted")

    monkeypatch.setattr(runtime, "checked_process", command)
    monkeypatch.setattr(runtime.shutil, "which", lambda *args, **kwargs: "/usr/bin/uv")
    with pytest.raises(RuntimeError, match="interrupted"):
        await instance.prepare()
    assert not (instance.environment / ".ready").exists()
    await instance.prepare()
    assert attempts == 2
    assert not (instance.environment / "partial").exists()


async def test_corrupt_ready_environment_is_rebuilt(tmp_path, monkeypatch, fake_setup):
    instance = runtime.Runtime(tmp_path)
    await instance.prepare()
    command = runtime.checked_process
    calls = 0

    async def corrupt_once(arguments, environment):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise FileNotFoundError("base interpreter removed")
        await command(arguments, environment)

    monkeypatch.setattr(runtime, "checked_process", corrupt_once)
    await instance.prepare()
    assert len(fake_setup) == 2
    assert (instance.environment / ".ready").is_file()


async def test_installer_ignores_host_package_settings(tmp_path, monkeypatch, fake_setup):
    for name in (
        "UV_INDEX",
        "UV_INDEX_URL",
        "UV_CONFIG_FILE",
        "UV_PROJECT_ENVIRONMENT",
        "UV_EXTRA_INDEX_URL",
        "PIP_INDEX_URL",
        "PYTHONPATH",
        "PYTHONHOME",
        "VIRTUAL_ENV",
    ):
        monkeypatch.setenv(name, "host-setting")
    monkeypatch.setenv("HTTPS_PROXY", "http://network-proxy.invalid")
    instance = runtime.Runtime(tmp_path)
    await instance.prepare()
    arguments, environment = fake_setup[0]
    assert "--locked" in arguments and "--no-config" in arguments
    assert arguments[arguments.index("--default-index") + 1] == runtime.INDEX
    assert environment["UV_PROJECT_ENVIRONMENT"] == str(instance.environment)
    assert environment["HTTPS_PROXY"] == "http://network-proxy.invalid"
    assert not any(value == "host-setting" for value in environment.values())


def test_lock_and_interpreter_changes_select_new_environment(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "pyproject.toml").write_text("project")
    lock = source / "uv.lock"
    lock.write_text("first")
    monkeypatch.setattr(runtime, "ROOT", source)
    first = runtime.Runtime(tmp_path).environment
    lock.write_text("second")
    second = runtime.Runtime(tmp_path).environment
    assert first != second
    monkeypatch.setattr(sys, "version", "new base interpreter")
    assert runtime.Runtime(tmp_path).environment != second


async def test_missing_uv_has_actionable_error(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime.shutil, "which", lambda *args, **kwargs: None)
    with pytest.raises(RuntimeError, match="AstrBot's PATH"):
        await runtime.Runtime(tmp_path).prepare()


async def test_cancelled_installer_is_reaped(monkeypatch):
    process = AsyncMock()
    process.returncode = None
    entered = asyncio.Event()

    async def communicate():
        entered.set()
        await asyncio.Event().wait()

    process.communicate.side_effect = communicate
    kill = Mock()
    monkeypatch.setattr(runtime.os, "killpg", kill)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    task = asyncio.create_task(runtime.checked_process(["uv"], {}))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    kill.assert_called_once()
    process.wait.assert_awaited_once()


async def test_lock_wait_is_bounded(tmp_path, monkeypatch):
    import fcntl

    instance = runtime.Runtime(tmp_path)
    instance.root.mkdir()
    monkeypatch.setattr(runtime, "SETUP_TIMEOUT", 0.02)
    with (instance.root / "setup.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with pytest.raises(RuntimeError, match="timed out"):
            await instance.prepare()


def test_parent_import_graph_needs_only_standard_library():
    code = (
        f"import sys; sys.path.insert(0, {str(runtime.ROOT)!r}); "
        "import jm_comic_fetcher.tasks, jm_comic_fetcher.runtime; "
        "import json; print(json.dumps(sorted(sys.modules)))"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-c", code],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
        env={key: value for key, value in os.environ.items() if not key.startswith("PYTHON")},
    )
    modules = json.loads(result.stdout)
    assert not {"jmcomic", "httpx", "PIL", "img2pdf"}.intersection(modules)
