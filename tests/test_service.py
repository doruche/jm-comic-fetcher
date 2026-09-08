import zipfile
from dataclasses import replace

import pikepdf
import pytest
from PIL import Image

from jm_comic_fetcher.config import Config
from jm_comic_fetcher.models import Chapter, Comic, Page, Request, UserError
from jm_comic_fetcher.service import execute


class FakeClient:
    def __init__(self, fail=False):
        self.fail = fail
        self.downloaded = []
        self.downloaded_bytes = 0

    async def comic(self, _id):
        return Comic(
            "123",
            "A test comic",
            "A description",
            (
                Chapter(1, "10", "Beginning"),
                Chapter(2, "20", "Middle"),
                Chapter(3, "30", "End"),
            ),
        )

    async def chapter_images(self, chapter):
        return [Page(f"{chapter.index}:{page}", 0) for page in (1, 2)]

    async def page(self, detail, path):
        detail = tuple(map(int, detail.url.split(":")))
        if self.fail and detail == (2, 2):
            raise UserError("A page failed.")
        self.downloaded.append(detail)
        output = path.with_suffix(".png")
        Image.new("RGB", (40 + detail[1], 60), "white").save(output)
        self.downloaded_bytes += output.stat().st_size
        return output

    async def cover(self, comic_id, directory):
        path = directory / "cover.png"
        Image.new("RGB", (40, 60), "blue").save(path)
        self.downloaded_bytes += path.stat().st_size
        return path


async def test_range_archive_and_page_order(tmp_path):
    client = FakeClient()
    result = await execute(Request("fetch", "123", 2, 3), Config(), tmp_path, client)
    with zipfile.ZipFile(tmp_path / result.archive) as archive:
        assert archive.namelist() == ["002.pdf", "003.pdf", "chapters.txt"]
        assert archive.testzip() is None
        assert all(info.compress_type == zipfile.ZIP_DEFLATED for info in archive.infolist())
        assert "Middle" in archive.read("chapters.txt").decode()
        with archive.open("002.pdf") as pdf_file, pikepdf.Pdf.open(pdf_file) as pdf:
            assert len(pdf.pages) == 2
            assert float(pdf.pages[0].mediabox[2]) < float(pdf.pages[1].mediabox[2])
    assert client.downloaded == [(2, 1), (2, 2), (3, 1), (3, 2)]
    assert not list((tmp_path / "images").rglob("*.png"))


async def test_failure_never_creates_final_archive(tmp_path):
    with pytest.raises(UserError):
        await execute(Request("fetch", "123", 2, 2), Config(), tmp_path, FakeClient(fail=True))
    assert not list(tmp_path.glob("*.zip"))


@pytest.mark.parametrize(
    "job_request,config",
    [
        (Request("fetch", "123", 4, 4), Config()),
        (Request("fetch", "123"), replace(Config(), max_chapters=2)),
        (Request("fetch", "123"), replace(Config(), max_pages=2)),
    ],
)
async def test_limits_before_image_download(tmp_path, job_request, config):
    client = FakeClient()
    with pytest.raises(UserError):
        await execute(job_request, config, tmp_path, client)
    assert not client.downloaded


async def test_inspect_modes(tmp_path):
    client = FakeClient()
    brief = await execute(Request("brief", "123"), Config(), tmp_path, client)
    assert "2. Middle" in brief.text and "A description" in brief.text
    assert list(tmp_path.iterdir()) == []
    result = await execute(Request("cover", "123"), Config(), tmp_path, client)
    with zipfile.ZipFile(tmp_path / result.archive) as archive:
        assert archive.namelist() == ["cover.png"]
        assert archive.read("cover.png") == (tmp_path / "cover.png").read_bytes()


@pytest.mark.parametrize("action", ["fetch", "cover"])
async def test_download_statistics_measure_only_download_batches(tmp_path, monkeypatch, action):
    from jm_comic_fetcher.protocol import WorkerResult

    # Two concurrent pages in each chapter take 2s and 3s of wall time.
    # The 88s gap between batches represents PDF processing, not download time.
    times = iter([10.0, 12.0, 100.0, 103.0] if action == "fetch" else [10.0, 12.0])
    monkeypatch.setattr("jm_comic_fetcher.service.perf_counter", lambda: next(times))
    client = FakeClient()
    client.downloaded_bytes = 77  # A prior operation must not enter this request's count.
    req = Request("fetch", "123", 1, 2) if action == "fetch" else Request("cover", "123")
    result = await execute(req, Config(), tmp_path, client)
    assert result.download.seconds == (5 if action == "fetch" else 2)
    assert result.download.received_bytes == client.downloaded_bytes - 77 > 0
    assert result.archive is not None
    assert WorkerResult.from_dict(result.to_dict()) == result
