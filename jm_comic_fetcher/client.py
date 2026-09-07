import asyncio
from pathlib import Path

import httpx
from jmcomic import AsyncJmApiClient, JmcomicText, JmImageTool, JmModuleConfig, JmOption
from PIL import Image

from .config import MIB, Config
from .models import Chapter, Comic, UserError
from .storage import GuardedWriter


class DownloadBudget:
    def __init__(self, maximum: int):
        self.maximum = maximum
        self.received = 0

    def consume(self, count: int) -> None:
        self.received += count
        if self.received > self.maximum:
            raise UserError("Download exceeds max_download_mib; select fewer chapters.")


class Client:
    """Upstream metadata API plus streamed, budgeted image downloads.

    Runs only inside a task process: upstream global state cannot affect AstrBot.
    """

    def __init__(self, config: Config):
        self.config = config
        JmModuleConfig.FLAG_ENABLE_JM_LOG = False
        option = JmOption.construct(
            {
                "log": False,
                "client": {
                    "retry_times": config.max_retries,
                    "timeout": config.request_timeout_seconds,
                    "domain": {"api": list(config.api_domains)},
                    "postman": {"meta_data": {"proxies": config.proxy_url or None}},
                },
            }
        )
        self.api = AsyncJmApiClient(option, max_clients=config.image_concurrency)
        self.http = httpx.AsyncClient(
            proxy=config.proxy_url or None,
            trust_env=False,
            timeout=config.request_timeout_seconds,
            follow_redirects=False,
            headers={**JmModuleConfig.APP_HEADERS_TEMPLATE, **JmModuleConfig.APP_HEADERS_IMAGE},
            limits=httpx.Limits(max_connections=config.image_concurrency),
        )
        self.budget = DownloadBudget(config.max_download_mib * MIB)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        try:
            await self.api.close()
        finally:
            await self.http.aclose()

    async def comic(self, comic_id: str) -> Comic:
        album = await self.api.get_album_detail(comic_id)
        return Comic(
            str(album.id),
            album.title,
            album.description,
            tuple(
                Chapter(i, str(item.id), item.title.strip() or f"Chapter {i}")
                for i, item in enumerate(album, 1)
            ),
        )

    async def chapter_images(self, chapter: Chapter):
        photo = await self.api.get_photo_detail(chapter.id, fetch_album=False)
        return list(photo)

    async def stream_image(self, url: str, path: Path) -> None:
        # Count bytes as they arrive, also on failed/retried responses. Never rely on HEAD.
        for attempt in range(self.config.max_retries + 1):
            try:
                current_url = url
                for redirect in range(6):
                    async with self.http.stream(
                        "GET", current_url, follow_redirects=False
                    ) as response:
                        with path.open("wb") as file:
                            writer = GuardedWriter(file, self.config.min_free_disk_mib * MIB)
                            async for chunk in response.aiter_bytes():
                                self.budget.consume(len(chunk))
                                if response.status_code == 200:
                                    writer.write(chunk)
                        if response.has_redirect_location:
                            if redirect == 5:
                                raise UserError("Too many image redirects.")
                            target = response.url.join(response.headers["location"])
                            if target.scheme not in {"http", "https"}:
                                raise UserError("Unsupported image redirect scheme.")
                            current_url = str(target)
                            continue
                        response.raise_for_status()
                        if path.stat().st_size == 0:
                            raise UserError("The upstream returned an empty image.")
                    return
            except httpx.HTTPError as exc:
                if attempt == self.config.max_retries:
                    raise UserError("Image download failed after retries.") from exc
                await asyncio.sleep(min(2**attempt, 4))

    def validate_image(self, path: Path) -> str:
        with Image.open(path) as image:
            if image.width * image.height > self.config.max_image_megapixels * 1_000_000:
                raise UserError("Image exceeds max_image_megapixels.")
            image.verify()
            return {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "GIF": ".gif"}.get(
                image.format, ".img"
            )

    async def cover(self, comic_id: str, directory: Path) -> Path:
        raw = directory / "cover.download"
        await self.stream_image(JmcomicText.get_album_cover_url(comic_id), raw)
        suffix = self.validate_image(raw)
        output = directory / f"cover{suffix}"
        raw.replace(output)
        return output

    async def page(self, detail, path: Path) -> Path:
        raw = path.with_suffix(".download")
        await self.stream_image(detail.download_url, raw)
        suffix = self.validate_image(raw)
        strips = JmImageTool.get_num_by_detail(detail)
        if strips == 0 and suffix in {".jpg", ".png"}:
            output = path.with_suffix(suffix)
            raw.replace(output)
            return output
        output = path.with_suffix(".png")
        with Image.open(raw) as image, output.open("wb") as file:
            # One image at a time is decoded; PDFs embed these files without loading all pixels.
            with image.convert("RGB") as rgb:
                JmImageTool.decode_and_save(
                    strips, rgb, GuardedWriter(file, self.config.min_free_disk_mib * MIB)
                )
        raw.unlink()
        return output
