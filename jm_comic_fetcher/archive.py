import shutil
import zipfile
from pathlib import Path

import img2pdf

from .config import MIB, Config
from .models import UserError
from .storage import GuardedWriter


def make_pdf(images: list[Path], output: Path, config: Config) -> None:
    if not images or any(not p.is_file() or p.stat().st_size == 0 for p in images):
        raise UserError("A chapter is incomplete; no archive was produced.")
    with output.open("wb") as file:
        img2pdf.convert(
            *map(str, images), outputstream=GuardedWriter(file, config.min_free_disk_mib * MIB)
        )


def make_zip(files: list[Path], output: Path, config: Config) -> None:
    """Ordinary Deflate ZIP. No passwords, encryption or obfuscation claims."""
    partial = output.with_suffix(".partial")
    try:
        with partial.open("w+b") as file:
            writer = GuardedWriter(
                file, config.min_free_disk_mib * MIB, config.max_archive_mib * MIB
            )
            with zipfile.ZipFile(writer, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                for path in files:
                    with path.open("rb") as source, archive.open(path.name, "w") as target:
                        shutil.copyfileobj(source, target, length=64 * 1024)
        partial.replace(output)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
