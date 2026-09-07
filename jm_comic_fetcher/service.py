import asyncio
import json
from pathlib import Path
from typing import Protocol

from .archive import make_pdf, make_zip
from .config import Config
from .diagnostics import phase
from .models import Chapter, Comic, Page, Request, UserError
from .protocol import WorkerResult


class ComicClient(Protocol):
    """page/cover return complete, validated image files owned by this job."""

    async def comic(self, comic_id: str) -> Comic: ...
    async def chapter_images(self, chapter: Chapter) -> list[Page]: ...
    async def page(self, detail: Page, path: Path) -> Path: ...
    async def cover(self, comic_id: str, directory: Path) -> Path: ...


async def execute(
    request: Request, config: Config, directory: Path, client: ComicClient
) -> WorkerResult:
    with phase("metadata"):
        comic = await client.comic(request.comic_id)
    if request.action == "brief":
        lines = [
            f"{comic.title}\nID: {comic.id}",
            f"Description: {comic.description or 'No description available.'}",
            f"Chapters ({len(comic.chapters)}):",
            *(f"{chapter.index}. {chapter.title}" for chapter in comic.chapters),
        ]
        return WorkerResult("ok", "\n".join(lines))
    if request.action == "cover":
        with phase("download"):
            cover = await client.cover(comic.id, directory)
        archive = directory / f"JM_{comic.id}_cover.zip"
        with phase("archive"):
            make_zip([cover], archive, config)
        return WorkerResult("ok", f"Cover: {comic.title}", archive.name)
    if request.action != "fetch":
        raise UserError("Unsupported task.")

    selected = request.select(comic, config.max_chapters)
    # Resolve every selected chapter before downloading; keep this snapshot's order.
    plan = []
    pages = 0
    for chapter in selected:
        with phase("metadata"):
            images = await client.chapter_images(chapter)
        if not images:
            raise UserError(f"Chapter {chapter.index} contains no pages.")
        pages += len(images)
        if pages > config.max_pages:
            raise UserError(f"Select at most {config.max_pages} pages per task.")
        plan.append((chapter, images))
    (directory / "selection.json").write_text(
        json.dumps({"chapters": [c.index for c in selected], "pages": pages}), encoding="utf-8"
    )
    pdf_dir = directory / "pdf"
    pdf_dir.mkdir()
    files = []
    semaphore = asyncio.Semaphore(config.image_concurrency)

    async def download(detail, path):
        async with semaphore:
            with phase("download"):
                return await client.page(detail, path)

    for chapter, images in plan:
        image_dir = directory / "images" / f"{chapter.index:03d}"
        image_dir.mkdir(parents=True)
        tasks = [
            asyncio.create_task(download(detail, image_dir / f"{i:04d}"))
            for i, detail in enumerate(images, 1)
        ]
        try:
            paths = await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        pdf = pdf_dir / f"{chapter.index:03d}.pdf"
        with phase("pdf"):
            make_pdf(paths, pdf, config)
        files.append(pdf)
        # PDFs are now durable for this task; release intermediate images early.
        for path in paths:
            path.unlink()
        image_dir.rmdir()
    contents = directory / "chapters.txt"
    contents.write_text(
        f"{comic.title}\nID: {comic.id}\n\n"
        + "\n".join(f"{c.index:03d}.pdf: {c.title}" for c in selected),
        encoding="utf-8",
    )
    archive = directory / f"JM_{comic.id}_{selected[0].index}-{selected[-1].index}.zip"
    with phase("archive"):
        make_zip([*files, contents], archive, config)
    return WorkerResult(
        "ok", f"Completed: {len(selected)} chapters, {pages} pages.\n{comic.title}", archive.name
    )
