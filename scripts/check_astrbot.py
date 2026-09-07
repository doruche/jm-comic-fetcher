"""Opt-in isolated-runtime integration check in disposable AstrBot containers."""

import argparse
import asyncio
import importlib.metadata
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

PLUGIN_NAME = "astrbot_plugin_jm_comic_fetcher"


def versions() -> dict[str, str]:
    return {
        dist.metadata["Name"].lower().replace("_", "-"): dist.version
        for dist in importlib.metadata.distributions()
        if dist.metadata["Name"]
    }


def require_unchanged(before: dict, after: dict) -> None:
    changed = {
        name: (version, after.get(name))
        for name, version in before.items()
        if after.get(name) != version
    }
    added = sorted(after.keys() - before.keys())
    if changed or added:
        raise AssertionError(f"Host packages changed: {changed}; added: {added}")


def web_status() -> int:
    # This test container has no host proxy or authentication credentials.
    with urllib.request.urlopen("http://127.0.0.1:6185/", timeout=2) as response:
        return response.status


async def check_worker_and_archive(directory: Path) -> None:
    import zipfile

    import pikepdf
    from PIL import Image

    from jm_comic_fetcher.config import Config
    from jm_comic_fetcher.models import (
        Chapter,
        Comic,
        Page,
        Request,
    )
    from jm_comic_fetcher.service import execute

    config = Config()

    class GeneratedComic:
        async def comic(self, _comic_id):
            return Comic(
                "123",
                "Generated comic",
                "Offline fixture",
                (
                    Chapter(1, "1", "First"),
                    Chapter(2, "2", "Second"),
                ),
            )

        async def chapter_images(self, chapter):
            return [Page(str(chapter.index), 0)]

        async def page(self, detail, path):
            image_path = path.with_suffix(".png")
            Image.new("RGB", (40 + int(detail.url), 60), "white").save(image_path)
            return image_path

    result = await execute(Request("fetch", "123"), config, directory, GeneratedComic())
    with zipfile.ZipFile(directory / result.archive) as archive:
        assert archive.testzip() is None
        assert archive.namelist() == ["001.pdf", "002.pdf", "chapters.txt"]
        for name in ("001.pdf", "002.pdf"):
            with archive.open(name) as source, pikepdf.Pdf.open(source) as pdf:
                assert len(pdf.pages) == 1


def inside() -> None:
    from dataclasses import replace

    source = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(source))
    from jm_comic_fetcher.config import Config
    from jm_comic_fetcher.models import Request
    from jm_comic_fetcher.runtime import Runtime, worker_environment
    from jm_comic_fetcher.tasks import run_worker

    os.chdir("/AstrBot")
    before = versions()
    runtime = Runtime(Path(f"/AstrBot/data/plugin_data/{PLUGIN_NAME}"))
    ready = runtime.environment / ".ready"
    # Exercise polluted installer configuration without changing AstrBot's package source.
    poison = Path("/tmp/host-packages")
    poison.mkdir()
    (poison / "jmcomic.py").write_text("raise RuntimeError('host dependency leaked')")
    os.environ["PYTHONPATH"] = str(poison)
    uv_config = Path.home() / ".config/uv/uv.toml"
    uv_config.parent.mkdir(parents=True, exist_ok=True)
    uv_config.write_text('index-url = "https://invalid.example/simple"\n')
    Path("data/cmd_config.json").write_text(json.dumps({"platform": [], "provider": []}))
    with tempfile.TemporaryDirectory(prefix="jm-integration-") as temporary:
        scratch = Path(temporary)
        log_path = scratch / "astrbot.log"
        with log_path.open("w") as log:
            process = subprocess.Popen([sys.executable, "main.py"], stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + 660
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise AssertionError("AstrBot exited during startup")
                    logs = log_path.read_text()
                    try:
                        if (
                            f"Plugin {PLUGIN_NAME} (" in logs
                            and ready.is_file()
                            and web_status() == 200
                        ):
                            break
                    except (OSError, urllib.error.URLError):
                        pass
                    time.sleep(1)
                else:
                    raise AssertionError("Plugin/WebUI did not become healthy")
                stamp = ready.stat().st_mtime_ns
                asyncio.run(runtime.prepare())
                assert ready.stat().st_mtime_ns == stamp, "Ready environment was recreated"
                require_unchanged(before, versions())
                assert not Path("/tmp/forbidden-venv").exists()
                artifacts = scratch / "artifacts"
                artifacts.mkdir()
                result = asyncio.run(
                    run_worker(
                        Request("brief", "123"),
                        replace(Config(), max_running=0),
                        artifacts,
                        runtime.python,
                    )
                )
                assert (
                    result.status == "error"
                    and result.text == "Config max_running must be an integer >= 1."
                ), result
                subprocess.run(
                    [
                        str(runtime.python),
                        "-I",
                        str(Path(__file__).resolve()),
                        "--fixture",
                        str(artifacts),
                    ],
                    check=True,
                    timeout=60,
                    env=worker_environment(),
                )
                for _ in range(5):
                    assert web_status() == 200
                assert "jmcomic" not in sys.modules
                require_unchanged(before, versions())
                logs = log_path.read_text()
                assert "Error in ASGI Framework" not in logs and "ImportError:" not in logs
                print(
                    json.dumps(
                        {
                            "result": "PASS",
                            "host_packages_preserved": len(before),
                            "webui": 200,
                            "isolated_worker": "PASS",
                            "archive": "PASS",
                            "reuse": "PASS",
                            "host_index_overrides_ignored": "PASS",
                        }
                    ),
                    flush=True,
                )
            except BaseException:
                print(log_path.read_text()[-12000:], file=sys.stderr)
                raise
            finally:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="soulter/astrbot:latest")
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--fixture", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--inside", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.fixture:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        asyncio.run(check_worker_and_archive(args.fixture))
        return
    if args.inside:
        inside()
        return
    if args.rounds < 1:
        parser.error("--rounds must be positive")
    root = Path(__file__).resolve().parents[1]
    # Resolve once so both clean rounds use exactly the same local image.
    image = subprocess.check_output(
        ["docker", "image", "inspect", args.image, "--format", "{{.Id}}"], text=True
    ).strip()
    for number in range(1, args.rounds + 1):
        print(f"Clean container round {number}/{args.rounds}: {image}", flush=True)
        name = f"jm-dependency-check-{uuid.uuid4().hex}"
        try:
            subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--name",
                    name,
                    "--pull",
                    "never",
                    "--env",
                    "PYTHONDONTWRITEBYTECODE=1",
                    "--env",
                    "UV_INDEX_URL=https://invalid.example/simple",
                    "--env",
                    "UV_PROJECT_ENVIRONMENT=/tmp/forbidden-venv",
                    "--mount",
                    f"type=bind,src={root},dst=/AstrBot/data/plugins/{PLUGIN_NAME},readonly",
                    "--entrypoint",
                    "python",
                    image,
                    f"/AstrBot/data/plugins/{PLUGIN_NAME}/scripts/check_astrbot.py",
                    "--inside",
                ],
                check=True,
                timeout=900,
            )
        finally:
            # A killed Docker CLI does not necessarily stop its container.
            # Remove only the uniquely named test container owned by this round.
            subprocess.run(
                ["docker", "rm", "--force", name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
            )


if __name__ == "__main__":
    main()
