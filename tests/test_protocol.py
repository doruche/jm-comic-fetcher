import asyncio
import json
import sys
from pathlib import Path

import pytest

from jm_comic_fetcher.config import Config
from jm_comic_fetcher.diagnostics import diagnostic, log_worker_diagnostic, phase
from jm_comic_fetcher.models import Request
from jm_comic_fetcher.protocol import ProtocolError, WorkerRequest, WorkerResult
from jm_comic_fetcher.tasks import run_worker


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "error", "stage": "download", "archive": "result.zip"},
        {"status": "ok", "stage": "download"},
        {"archive": "../result.zip"},
        {"archive": "/tmp/result.zip"},
        {"archive": 123},
        {"text": None},
        {"status": "unknown"},
    ],
)
def test_rejects_contradictory_or_unsafe_result(changes):
    data = WorkerResult("ok", "Done").to_dict()
    data.update(changes)
    with pytest.raises(ProtocolError):
        WorkerResult.from_dict(data)


@pytest.mark.parametrize("raw", [[], None, {"text": "legacy result"}])
def test_invalid_result_shape(raw):
    with pytest.raises(ProtocolError):
        WorkerResult.from_dict(raw)


@pytest.mark.parametrize(
    "changes",
    [
        {"action": "version"},
        {"comic_id": "../a"},
        {"start": True},
        {"start": 3, "end": 2},
        {"start": 0, "end": 2},
    ],
)
def test_worker_rejects_invalid_content_request(tmp_path, changes):
    data = WorkerRequest(Request("fetch", "123"), Config(), tmp_path).to_dict()
    data["request"].update(changes)
    with pytest.raises(ProtocolError):
        WorkerRequest.from_dict(data)


def test_random_worker_request_roundtrip(tmp_path):
    job = WorkerRequest(Request("random", ""), Config(), tmp_path)
    assert WorkerRequest.from_dict(job.to_dict()) == job


@pytest.mark.parametrize(
    "changes",
    [
        {"comic_id": "123"},
        {"comic_id": None},
        {"comic_id": 0},
        {"start": 1, "end": 1},
        {"action": "brief"},
        {"action": "fetch"},
        {"action": "cover"},
    ],
)
def test_random_does_not_relax_other_worker_validation(tmp_path, changes):
    data = WorkerRequest(Request("random", ""), Config(), tmp_path).to_dict()
    data["request"].update(changes)
    with pytest.raises(ProtocolError):
        WorkerRequest.from_dict(data)


def test_diagnostics_preserve_location_without_credentials(caplog):
    try:
        with phase("decode"):
            raise OSError(28, "secret cookie=abc https://user:password@example.org")
    except OSError as exc:
        data = diagnostic(exc, task="123", stage="decode")
    log_worker_diagnostic(json.dumps(data).encode(), "123", "decode")
    assert "decode" in caplog.text and "OSError" in caplog.text
    assert "test_protocol.py" in caplog.text and "28" in caplog.text
    assert "secret" not in caplog.text and "password" not in caplog.text


async def test_real_worker_reports_request_stage_without_host_dependencies(tmp_path, caplog):
    from dataclasses import replace

    result = await run_worker(
        Request("fetch", "123"), replace(Config(), max_running=0), tmp_path, Path(sys.executable)
    )
    assert result.status == "error" and result.stage == "request"
    assert "Config max_running" in result.text
    assert tmp_path.name in caplog.text and "config.py" in caplog.text


async def test_malformed_worker_reply_never_publishes(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock

    from jm_comic_fetcher import tasks
    from jm_comic_fetcher.processes import ProcessResult
    from jm_comic_fetcher.storage import Storage

    monkeypatch.setattr(tasks, "run_process", AsyncMock(return_value=ProcessResult(0, b"[]", b"")))
    manager = tasks.TaskManager(Config(), Storage(tmp_path), Path(sys.executable))
    deliver = AsyncMock()
    await manager.submit("1", Request("fetch", "123"), AsyncMock(), deliver)
    await asyncio.gather(*manager.tasks)
    deliver.assert_not_awaited()
    assert not list(manager.storage.deliveries.iterdir())
    await manager.close()


def test_wrapped_http_failure_keeps_safe_cause(caplog):
    import httpx

    from jm_comic_fetcher.models import UserError

    try:
        try:
            response = httpx.Response(
                503, request=httpx.Request("GET", "https://secret:password@example.org")
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise UserError("Download failed") from exc
    except UserError as exc:
        data = diagnostic(exc, task="job", stage="download")
    log_worker_diagnostic(json.dumps(data).encode(), "job", "download")
    assert "HTTPStatusError" in caplog.text and "503" in caplog.text
    assert "secret" not in caplog.text and "password" not in caplog.text
