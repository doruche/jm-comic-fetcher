"""Private subprocess entry point. Input is JSON on stdin; output is one JSON result."""

import asyncio
import json
import sys
from pathlib import Path

from .client import Client
from .config import Config
from .models import Request, UserError
from .service import execute


async def run(payload: dict) -> dict:
    config = Config.from_mapping(payload["config"])
    request = Request(**payload["request"])
    directory = Path(payload["directory"])
    async with Client(config) as client:
        return await execute(request, config, directory, client)


def main() -> None:
    try:
        result = asyncio.run(run(json.load(sys.stdin)))
    except UserError as exc:
        result = {"error": str(exc)}
    except Exception as exc:
        # Upstream exceptions may contain response bodies, cookies or proxy credentials.
        result = {
            "error": f"Task failed ({type(exc).__name__}). Check network or comic availability."
        }
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    main()
