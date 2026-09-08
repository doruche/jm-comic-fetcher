import asyncio
from dataclasses import replace
from io import BytesIO
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from jm_comic_fetcher.client import Client
from jm_comic_fetcher.config import Config
from jm_comic_fetcher.models import Chapter, Comic, Page, Request, UserError
from jm_comic_fetcher.service import execute


def image_bytes(format):
    output = BytesIO()
    Image.effect_noise((128, 128), 100).convert("RGB").save(output, format=format)
    return output.getvalue()


@pytest.mark.parametrize("format", ["JPEG", "PNG"])
async def test_corrupt_image_fails_before_archive(tmp_path, format):
    data = image_bytes(format)
    async with Client(Config()) as client:

        async def stream(url, path):
            path.write_bytes(data[: len(data) // 2])

        client.stream_image = stream
        client.comic = AsyncMock(
            return_value=Comic("123", "Fixture", "", (Chapter(1, "1", "One"),))
        )
        client.chapter_images = AsyncMock(return_value=[Page("https://test.invalid/page", 0)])
        with pytest.raises((OSError, SyntaxError)):
            await execute(Request("fetch", "123"), Config(), tmp_path, client)
        assert not list(tmp_path.glob("*.zip"))
        assert not list(tmp_path.rglob("*.pdf"))
        # Cover publication uses the same validation path.
        with pytest.raises((OSError, SyntaxError)):
            await client.cover("123", tmp_path)
        assert not list(tmp_path.glob("cover.jpg"))


async def test_pixel_limit_precedes_pixel_decode(tmp_path):
    path = tmp_path / "large.png"
    Image.new("RGB", (1024, 1024)).save(path)
    config = replace(Config(), max_image_megapixels=1)
    async with Client(config) as client:
        # A pixel limit error should be raised rather than decoding the large image.
        with pytest.raises(UserError, match="max_image_megapixels"):
            client.validate_image(path)


async def test_valid_jpeg_is_preserved_without_reencoding(tmp_path):
    data = image_bytes("JPEG")
    async with Client(Config()) as client:

        async def stream(url, path):
            path.write_bytes(data)

        client.stream_image = stream
        path = await client.page(Page("https://test.invalid/page", 0), tmp_path / "page")
        assert path.suffix == ".jpg" and path.read_bytes() == data


async def test_failed_page_cancels_other_downloads(tmp_path):
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    class ClientFixture:
        downloaded_bytes = 0

        async def comic(self, comic_id):
            return Comic(comic_id, "Fixture", "", (Chapter(1, "1", "One"),))

        async def chapter_images(self, chapter):
            return [Page("broken", 0), Page("slow", 0)]

        async def page(self, detail, path):
            if detail.url == "broken":
                await entered.wait()
                raise UserError("Broken page")
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    with pytest.raises(UserError, match="Broken page"):
        await execute(Request("fetch", "123"), Config(), tmp_path, ClientFixture())
    assert cancelled.is_set()
    assert not list(tmp_path.glob("*.zip"))
