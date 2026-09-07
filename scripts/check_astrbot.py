"""Opt-in integration check of native installation in disposable AstrBot containers."""

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
    if changed:
        raise AssertionError(f"Existing host packages changed: {changed}")


def web_status() -> int:
    # This test container has no host proxy or authentication credentials.
    with urllib.request.urlopen("http://127.0.0.1:6185/", timeout=2) as response:
        return response.status


async def check_worker_and_archive(directory: Path) -> None:
    import zipfile
    from dataclasses import replace

    import pikepdf
    from data.plugins.astrbot_plugin_jm_comic_fetcher.jm_comic_fetcher.config import Config
    from data.plugins.astrbot_plugin_jm_comic_fetcher.jm_comic_fetcher.models import (
        Chapter,
        Comic,
        Request,
    )
    from data.plugins.astrbot_plugin_jm_comic_fetcher.jm_comic_fetcher.service import execute
    from data.plugins.astrbot_plugin_jm_comic_fetcher.jm_comic_fetcher.tasks import run_worker
    from PIL import Image

    config = Config()
    async with asyncio.timeout(30):
        result = await run_worker(
            Request("brief", "123"), replace(config, max_running=0), directory
        )
    assert result == {"error": "Config max_running must be an integer >= 1."}, result

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
            return [chapter.index]

        async def page(self, detail, path):
            image_path = path.with_suffix(".png")
            Image.new("RGB", (40 + detail, 60), "white").save(image_path)
            return image_path

    result = await execute(Request("fetch", "123"), config, directory, GeneratedComic())
    with zipfile.ZipFile(directory / result["archive"]) as archive:
        assert archive.testzip() is None
        assert archive.namelist() == ["001.pdf", "002.pdf", "chapters.txt"]
        for name in ("001.pdf", "002.pdf"):
            with archive.open(name) as source, pikepdf.Pdf.open(source) as pdf:
                assert len(pdf.pages) == 1


def inside() -> None:
    os.chdir("/AstrBot")
    sys.path.insert(0, "/AstrBot")
    before = versions()
    requirements = Path(f"/AstrBot/data/plugins/{PLUGIN_NAME}/requirements.txt")
    with tempfile.TemporaryDirectory(prefix="astrbot-dependency-check-") as temporary:
        scratch = Path(temporary)
        report = scratch / "plan.json"
        plan = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--dry-run",
                "--report",
                str(report),
                "--index-url",
                "https://pypi.org/simple/",
                "-r",
                str(requirements),
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )
        if plan.returncode:
            raise AssertionError(plan.stderr[-4000:])
        planned = dict(before)
        for item in json.loads(report.read_text())["install"]:
            metadata = item["metadata"]
            planned[metadata["name"].lower().replace("_", "-")] = metadata["version"]
        require_unchanged(before, planned)
        print("PASS: install plan preserves all existing host packages", flush=True)

        # No user configuration, accounts, providers or real conversations are mounted.
        Path("data/cmd_config.json").write_text(
            json.dumps(
                {
                    "pypi_index_url": "https://pypi.org/simple/",
                    "platform": [],
                    "provider": [],
                }
            )
        )
        log_path = scratch / "astrbot.log"
        with log_path.open("w") as log:
            process = subprocess.Popen([sys.executable, "main.py"], stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + 180
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise AssertionError("AstrBot exited during startup")
                    try:
                        if web_status() == 200:
                            break
                    except (OSError, urllib.error.URLError):
                        pass
                    time.sleep(1)
                else:
                    raise AssertionError("WebUI did not become healthy")
                logs = log_path.read_text()
                assert f"Plugin {PLUGIN_NAME} (" in logs, "Plugin was not loaded"
                assert "missing dependencies; installing" in logs, "Expected native installation"
                require_unchanged(before, versions())
                artifacts = scratch / "artifacts"
                artifacts.mkdir()
                asyncio.run(check_worker_and_archive(artifacts))
                for _ in range(5):
                    assert web_status() == 200
                check = subprocess.run(
                    [sys.executable, "-m", "pip", "check"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                assert check.returncode == 0, check.stdout + check.stderr
                logs = log_path.read_text()
                assert "Error in ASGI Framework" not in logs and "ImportError:" not in logs
                print(
                    json.dumps(
                        {
                            "result": "PASS",
                            "host_packages_preserved": len(before),
                            "anyio": versions().get("anyio"),
                            "lxml": versions().get("lxml"),
                            "webui": 200,
                            "worker": "PASS",
                            "generated_archive": "PASS",
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
    parser.add_argument("--inside", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
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
                    "--mount",
                    f"type=bind,src={root},dst=/AstrBot/data/plugins/{PLUGIN_NAME},readonly",
                    "--entrypoint",
                    "python",
                    image,
                    f"/AstrBot/data/plugins/{PLUGIN_NAME}/scripts/check_astrbot.py",
                    "--inside",
                ],
                check=True,
                timeout=450,
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
