import json
import os
import time
from dataclasses import replace

import httpx
import pytest

from jm_comic_fetcher.archive import make_zip
from jm_comic_fetcher.client import Client, DownloadBudget
from jm_comic_fetcher.config import Config
from jm_comic_fetcher.models import UserError
from jm_comic_fetcher.storage import Storage


class Chunks(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b"1234"
        yield b"5678"


async def test_stream_limit_counts_actual_bytes(tmp_path):
    async with Client(Config()) as client:
        await client.http.aclose()
        client.http = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda req: httpx.Response(200, stream=Chunks()))
        )
        client.budget = DownloadBudget(5)
        with pytest.raises(UserError, match="max_download"):
            await client.stream_image("https://test.invalid/image", tmp_path / "page")
        assert client.budget.received == 8
        assert (tmp_path / "page").read_bytes() == b"1234"


async def test_failed_response_bytes_count_on_retry(tmp_path):
    calls = 0

    def respond(req):
        nonlocal calls
        calls += 1
        return httpx.Response(503 if calls == 1 else 200, content=b"1234")

    async with Client(replace(Config(), max_retries=1)) as client:
        await client.http.aclose()
        client.http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        client.budget = DownloadBudget(6)
        with pytest.raises(UserError, match="max_download"):
            await client.stream_image("https://test.invalid/image", tmp_path / "page")
        assert calls == 2 and client.budget.received == 8


async def test_redirect_bodies_share_download_budget(tmp_path):
    def respond(req):
        if req.url.path == "/start":
            return httpx.Response(302, headers={"location": "/final"}, content=b"1234")
        return httpx.Response(200, content=b"5678")

    async with Client(Config()) as client:
        await client.http.aclose()
        client.http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        client.budget = DownloadBudget(6)
        with pytest.raises(UserError, match="max_download"):
            await client.stream_image("https://test.invalid/start", tmp_path / "page")
        assert client.budget.received == 8


def test_archive_limit_removes_partial(tmp_path):
    source = tmp_path / "random.bin"
    source.write_bytes(os.urandom(2 * 1024 * 1024))
    with pytest.raises(UserError, match="max_archive"):
        make_zip([source], tmp_path / "result.zip", replace(Config(), max_archive_mib=1))
    assert not (tmp_path / "result.zip").exists()
    assert not (tmp_path / "result.partial").exists()


def test_cleanup_owns_only_expired_job_directories(tmp_path):
    storage = Storage(tmp_path / "storage")
    expired = storage.create(Config())
    active = storage.create(Config())
    recent = storage.create(Config())
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep").write_text("keep")
    symlink = storage.jobs / ("f" * 32)
    symlink.symlink_to(outside, target_is_directory=True)
    unknown = storage.jobs / "not-a-job"
    unknown.mkdir()
    for path in (expired, active):
        (path / "state.json").write_text(
            json.dumps(
                {
                    "finished_at": time.time() - 7200,
                    "success": True,
                }
            )
        )
    assert storage.cleanup(Config(), {active}) == 1
    assert not expired.exists()
    assert active.exists() and recent.exists() and unknown.exists()
    assert (outside / "keep").read_text() == "keep"
