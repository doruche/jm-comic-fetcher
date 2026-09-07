"""Private subprocess entry point. Input and output are validated JSON messages."""

import asyncio
import json
import sys

from .client import Client
from .diagnostics import diagnostic, failure_stage, phase
from .models import UserError
from .protocol import WorkerRequest, WorkerResult
from .service import execute


async def run(payload: object) -> WorkerResult:
    with phase("request"):
        job = WorkerRequest.from_dict(payload)
    with phase("client"):
        async with Client(job.config) as client:
            return await execute(job.request, job.config, job.directory, client)


def main() -> None:
    try:
        result = asyncio.run(run(json.load(sys.stdin)))
    except Exception as exc:
        stage = failure_stage(exc)
        # Deliberately omit messages/locals: upstream exceptions can contain credentials.
        print(json.dumps(diagnostic(exc, task="worker", stage=stage)), file=sys.stderr)
        text = str(exc) if isinstance(exc, UserError) else f"Task failed during {stage}."
        result = WorkerResult("error", text, stage=stage)
    print(json.dumps(result.to_dict(), ensure_ascii=True))


if __name__ == "__main__":
    main()
