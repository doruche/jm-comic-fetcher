"""Validated JSON boundary shared by the host and worker (standard library only)."""

import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from .config import MIB, Config
from .models import Request


class ProtocolError(ValueError):
    pass


@dataclass(frozen=True)
class WorkerRequest:
    request: Request
    config: Config
    directory: Path

    def to_dict(self) -> dict:
        return {
            "request": asdict(self.request),
            "config": self.config.worker_config(),
            "directory": str(self.directory),
        }

    @classmethod
    def from_dict(cls, value: object) -> "WorkerRequest":
        if not isinstance(value, dict) or set(value) != {"request", "config", "directory"}:
            raise ProtocolError("Invalid worker request fields")
        raw = value["request"]
        if not isinstance(raw, dict) or set(raw) != {"action", "comic_id", "start", "end"}:
            raise ProtocolError("Invalid content request fields")
        if raw["action"] not in ("brief", "cover", "fetch", "random"):
            raise ProtocolError("Invalid content action")
        if raw["action"] == "random":
            if raw["comic_id"] != "":
                raise ProtocolError("Random does not accept a comic ID")
        elif not isinstance(raw["comic_id"], str) or not re.fullmatch(
            r"[1-9][0-9]{0,17}", raw["comic_id"]
        ):
            raise ProtocolError("Invalid comic ID")
        if any(type(raw[key]) is not int or raw[key] < 0 for key in ("start", "end")):
            raise ProtocolError("Invalid chapter range")
        if (raw["start"] == 0 and raw["end"] != 0) or (raw["start"] > raw["end"]):
            raise ProtocolError("Invalid chapter range")
        if raw["action"] != "fetch" and (raw["start"] or raw["end"]):
            raise ProtocolError("Unexpected chapter range")
        directory = value["directory"]
        if not isinstance(directory, str) or not Path(directory).is_absolute():
            raise ProtocolError("Worker directory must be absolute")
        if not isinstance(value["config"], dict):
            raise ProtocolError("Invalid worker configuration")
        return cls(Request(**raw), Config.from_mapping(value["config"]), Path(directory))


@dataclass(frozen=True)
class DownloadStats:
    received_bytes: int
    seconds: float

    def summary(self) -> str:
        mib = self.received_bytes / MIB
        speed = f"{mib / self.seconds:.2f} MiB/s" if self.seconds > 0 else "N/A"
        return (
            f"Downloaded: {mib:.2f} MiB in {self.seconds:.2f} s - avg {speed}\n"
            "Includes image processing and retries; excludes packing and upload."
        )

    @classmethod
    def from_dict(cls, value: object) -> "DownloadStats":
        if not isinstance(value, dict) or set(value) != {"received_bytes", "seconds"}:
            raise ProtocolError("Invalid download statistics fields")
        size, seconds = value["received_bytes"], value["seconds"]
        if type(size) is not int or size < 0:
            raise ProtocolError("Invalid download byte count")
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0:
            raise ProtocolError("Invalid download duration")
        return cls(size, seconds)


@dataclass(frozen=True)
class WorkerResult:
    status: Literal["ok", "error"]
    text: str
    archive: str | None = None
    stage: str | None = None
    download: DownloadStats | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: object) -> "WorkerResult":
        if not isinstance(value, dict) or set(value) != {
            "status",
            "text",
            "archive",
            "stage",
            "download",
        }:
            raise ProtocolError("Invalid worker result fields")
        status, text, archive, stage = (
            value[key] for key in ("status", "text", "archive", "stage")
        )
        if status not in ("ok", "error") or not isinstance(text, str) or not text:
            raise ProtocolError("Invalid worker result status/text")
        if archive is not None and (
            not isinstance(archive, str) or not re.fullmatch(r"[A-Za-z0-9_-]+\.zip", archive)
        ):
            raise ProtocolError("Invalid archive filename")
        if stage is not None and (
            not isinstance(stage, str) or not re.fullmatch(r"[a-z_]+", stage)
        ):
            raise ProtocolError("Invalid worker failure stage")
        if (status == "ok" and stage is not None) or (
            status == "error" and (archive is not None or stage is None)
        ):
            raise ProtocolError("Contradictory worker result")
        download = value["download"]
        if download is not None:
            if status != "ok" or archive is None:
                raise ProtocolError("Download statistics require a successful archive")
            download = DownloadStats.from_dict(download)
        return cls(status, text, archive, stage, download)
