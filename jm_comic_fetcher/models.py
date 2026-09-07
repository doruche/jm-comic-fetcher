from dataclasses import dataclass


class UserError(Exception):
    """An expected failure safe to display in chat."""


@dataclass(frozen=True)
class Chapter:
    index: int
    id: str
    title: str


@dataclass(frozen=True)
class Comic:
    id: str
    title: str
    description: str
    chapters: tuple[Chapter, ...]


@dataclass(frozen=True)
class Request:
    action: str
    comic_id: str
    start: int = 0
    end: int = 0

    def select(self, comic: Comic, max_chapters: int) -> tuple[Chapter, ...]:
        total = len(comic.chapters)
        start, end = (1, total) if self.start == 0 else (self.start, self.end)
        if total == 0:
            raise UserError("No chapters are available.")
        if not 1 <= start <= end <= total:
            raise UserError(f"Chapter range must be between 1 and {total} (inclusive).")
        if end - start + 1 > max_chapters:
            raise UserError(f"Select at most {max_chapters} chapters per task.")
        return comic.chapters[start - 1 : end]
