import re
import shlex

from .models import Request, UserError

HELP = """JM Comic Fetcher
/jmcomic help
/jmcomic inspect <comic_id> <brief|cover>
/jmcomic fetch <comic_id> [chapter]
/jmcomic fetch <comic_id> --from <start> --to <end>
/jmcomic random

Chapter numbers are 1-based. Omit chapter or use 0 for all chapters.
Ranges include both endpoints; --from and --to must be used together.
Each chapter becomes one PDF; all PDFs are packed into one ordinary ZIP.
Cover returns an ordinary ZIP containing the cover image.
ZIP compression provides no encryption or detection protection.
Random is not implemented yet."""


def parse_command(raw: str) -> Request | None:
    try:
        args = shlex.split(raw)
    except ValueError as exc:
        raise UserError("Invalid quoting. Use /jmcomic help.") from exc
    if not args or args in (["help"], ["--help"], ["-h"]):
        return None
    if args == ["random"]:
        return Request("random", "")
    if len(args) < 2 or not re.fullmatch(r"[1-9][0-9]{0,17}", args[1]):
        raise UserError("A comic ID must be a positive integer. Use /jmcomic help.")
    action, comic_id, *rest = args
    if action == "inspect" and len(rest) == 1 and rest[0] in {"brief", "cover"}:
        return Request(rest[0], comic_id)
    if action != "fetch":
        raise UserError("Usage: /jmcomic inspect <comic_id> <brief|cover>")
    if not rest:
        return Request("fetch", comic_id)
    if len(rest) == 1 and re.fullmatch(r"[0-9]{1,8}", rest[0]):
        chapter = int(rest[0])
        return Request("fetch", comic_id, chapter, chapter)
    if len(rest) == 4:
        pairs = dict(zip(rest[::2], rest[1::2], strict=True))
        if set(pairs) == {"--from", "--to"} and all(
            re.fullmatch(r"[1-9][0-9]{0,7}", value) for value in pairs.values()
        ):
            start, end = int(pairs["--from"]), int(pairs["--to"])
            if start <= end:
                return Request("fetch", comic_id, start, end)
    raise UserError(
        "Use a non-negative chapter number OR --from <start> --to <end>. "
        "Range endpoints must be positive integers with start <= end."
    )


def split_text(text: str, limit: int = 1500) -> list[str]:
    """Bound message length without dropping long titles or chapter lists."""
    chunks = []
    while text:
        end = len(text) if len(text) <= limit else text.rfind("\n", 0, limit + 1)
        if end <= 0:
            end = limit
        chunks.append(text[:end])
        text = text[end:].lstrip("\n")
    return chunks
