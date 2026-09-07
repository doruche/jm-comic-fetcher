from dataclasses import dataclass
from typing import Literal


class UserError(Exception):
    """An expected failure safe to display in chat."""


class DeliveryRejected(UserError):
    """The adapter explicitly reported that it could not accept the file send."""


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
class Page:
    url: str
    strips: int


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


@dataclass
class JobState:
    generation: Literal["not_started", "running", "succeeded", "failed", "cancelled"] = (
        "not_started"
    )
    delivery: Literal["not_started", "accepted", "rejected", "unknown"] = "not_started"
    notification: Literal["pending", "sent", "unknown"] = "pending"
    outcome: Literal["pending", "succeeded", "failed", "cancelled", "uncertain"] = "pending"
    stage: str = "acceptance"

    @property
    def success(self) -> bool:
        return self.outcome == "succeeded"
