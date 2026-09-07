import json
import re
import shutil
import time
import uuid
from pathlib import Path

from .config import MIB, Config
from .models import UserError


class GuardedWriter:
    """Check free space on each write, including PDF and ZIP output."""

    def __init__(self, file, minimum_free: int, maximum_size: int | None = None):
        self.file = file
        self.minimum_free = minimum_free
        self.maximum_size = maximum_size

    def write(self, data):
        if self.maximum_size is not None and self.file.tell() + len(data) > self.maximum_size:
            raise UserError("The final ZIP exceeds max_archive_mib; select fewer chapters.")
        if shutil.disk_usage(Path(self.file.name).parent).free - len(data) < self.minimum_free:
            raise UserError("Not enough free disk space (min_free_disk_mib).")
        return self.file.write(data)

    def __getattr__(self, name):
        return getattr(self.file, name)


def ensure_space(path: Path, config: Config) -> None:
    if shutil.disk_usage(path).free < config.min_free_disk_mib * MIB:
        raise UserError("Not enough free disk space (min_free_disk_mib).")


class Storage:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.jobs = self.root / "jobs"
        self.jobs.mkdir(parents=True, exist_ok=True)

    def create(self, config: Config) -> Path:
        ensure_space(self.jobs, config)
        path = self.jobs / uuid.uuid4().hex
        path.mkdir(mode=0o700)
        return path

    def finish(self, path: Path, success: bool) -> None:
        (path / "state.json").write_text(
            json.dumps({"finished_at": time.time(), "success": success}), encoding="utf-8"
        )

    def cleanup(self, config: Config, active: set[Path]) -> int:
        removed = 0
        for path in self.jobs.iterdir():
            if (
                not re.fullmatch(r"[0-9a-f]{32}", path.name)
                or path.is_symlink()
                or not path.is_dir()
                or path in active
            ):
                continue
            try:
                state = json.loads((path / "state.json").read_text(encoding="utf-8"))
                age = time.time() - float(state["finished_at"])
                hours = (
                    config.success_retention_hours
                    if state["success"] is True
                    else config.failure_retention_hours
                )
            except (OSError, ValueError, KeyError, TypeError):
                # Incomplete jobs from a previous process are failures, never resumed.
                age = time.time() - path.stat().st_mtime
                hours = config.failure_retention_hours
            if age > hours * 3600:
                shutil.rmtree(path)
                removed += 1
        return removed
