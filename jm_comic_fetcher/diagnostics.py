"""Structured diagnostics without exception messages, URLs, locals or response bodies."""

import json
import logging
import re
import traceback
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

logger = logging.getLogger(__name__)
_stage = ContextVar("jm_stage", default="request")


@contextmanager
def phase(name: str):
    token = _stage.set(name)
    try:
        yield
    except Exception as exc:
        # Carry the originating stage across gather/client cleanup boundaries.
        if not hasattr(exc, "_jm_stage"):
            exc._jm_stage = name
        raise
    finally:
        _stage.reset(token)


def failure_stage(exc: Exception) -> str:
    return getattr(exc, "_jm_stage", _stage.get())


def _exception_details(exc: BaseException) -> dict:
    frames = traceback.extract_tb(exc.__traceback__)
    data = {
        "exception": type(exc).__name__,
        "frames": [
            {"file": Path(frame.filename).name, "function": frame.name, "line": frame.lineno}
            for frame in frames[-12:]
        ],
    }
    if isinstance(exc, OSError) and type(exc.errno) is int:
        data["errno"] = exc.errno
    if (
        isinstance(exc, ModuleNotFoundError)
        and exc.name
        and re.fullmatch(r"[A-Za-z0-9_.]+", exc.name)
    ):
        data["missing_module"] = exc.name
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if type(status) is int:
        data["http_status"] = status
    return data


def diagnostic(exc: Exception, *, task: str, stage: str) -> dict:
    data = {"task": task, "stage": stage, **_exception_details(exc)}
    causes = []
    seen = {id(exc)}
    cause = exc.__cause__
    while cause is not None and id(cause) not in seen and len(causes) < 3:
        seen.add(id(cause))
        causes.append(_exception_details(cause))
        cause = cause.__cause__
    if causes:
        data["causes"] = causes
    return data


def report(exc: Exception, *, task: str, stage: str) -> None:
    logger.warning("JM diagnostic %s", json.dumps(diagnostic(exc, task=task, stage=stage)))


def process_failure(stderr: bytes, *, task: str, stage: str, returncode: int) -> None:
    # Classify common uv failures without copying untrusted command output into logs.
    lowered = stderr.lower()
    hints = []
    for pattern, hint in (
        (b"no space left", "disk_full"),
        (b"permission denied", "permission_denied"),
        (b"certificate", "certificate"),
        (b"failed to download", "download"),
        (b"failed to build", "build"),
        (b"lockfile", "lockfile"),
        (b"unexpected argument", "unsupported_tool_version"),
        (b"no module named", "missing_module"),
        (b"timed out", "timeout"),
    ):
        if pattern in lowered:
            hints.append(hint)
    logger.warning("JM process task=%s stage=%s exit=%s hints=%s", task, stage, returncode, hints)


def _clean_details(info: dict) -> dict:
    exception = info.get("exception")
    if not isinstance(exception, str) or not re.fullmatch(r"[A-Za-z0-9_]+", exception):
        raise ValueError("Invalid exception name")
    frames = []
    for frame in info.get("frames", [])[-12:]:
        if (
            isinstance(frame, dict)
            and isinstance(frame.get("file"), str)
            and re.fullmatch(r"[A-Za-z0-9_.-]+", frame["file"])
            and isinstance(frame.get("function"), str)
            and re.fullmatch(r"[A-Za-z0-9_<>]+", frame["function"])
            and type(frame.get("line")) is int
        ):
            frames.append({key: frame[key] for key in ("file", "function", "line")})
    data = {"exception": exception, "frames": frames}
    for key in ("errno", "http_status"):
        if type(info.get(key)) is int:
            data[key] = info[key]
    missing = info.get("missing_module")
    if isinstance(missing, str) and re.fullmatch(r"[A-Za-z0-9_.]+", missing):
        data["missing_module"] = missing
    return data


def log_worker_diagnostic(stderr: bytes, task: str, stage: str) -> None:
    try:
        info = json.loads(stderr)
        if not isinstance(info, dict):
            raise ValueError("Invalid diagnostic")
        data = _clean_details(info)
        data["causes"] = [
            _clean_details(cause) for cause in info.get("causes", [])[:3] if isinstance(cause, dict)
        ]
        logger.warning("JM worker task=%s stage=%s diagnostic=%s", task, stage, json.dumps(data))
    except (ValueError, TypeError):
        logger.warning("JM worker task=%s stage=%s diagnostic unavailable", task, stage)
