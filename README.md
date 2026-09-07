# JM Comic Fetcher

An MIT-licensed personal AstrBot plugin for inspecting comic metadata and creating
chapter archives. Currently integrates directly with `jmcomic`; no external reader
server or multi-source framework is required.

## Commands

```text
/jmcomic help
/jmcomic inspect <comic_id> brief
/jmcomic inspect <comic_id> cover
/jmcomic fetch <comic_id>
/jmcomic fetch <comic_id> 0
/jmcomic fetch <comic_id> 3
/jmcomic fetch <comic_id> --from 2 --to 4
/jmcomic random
```

All command help and status/error messages are in English. Metadata retains its
original language. Chapter numbers are **1-based positions in `inspect brief`**,
not upstream chapter IDs. Omitted chapter or `0` means all chapters, subject to
configured limits. Ranges are inclusive; both options are required and cannot be
combined with a positional chapter. Invalid or out-of-range input is rejected.

`fetch` creates one PDF per selected chapter and one ZIP containing those PDFs
plus a UTF-8 `chapters.txt` index. Numeric PDF names preserve ordering and avoid
unsafe or duplicate upstream titles. `inspect brief` returns the title,
description (or an explicit missing-description message) and numbered chapters.
`inspect cover` sends the original cover image inside a ZIP, not an inline image.
`random` is a stub and makes no upstream request.

Archives use ordinary ZIP Deflate compression: **no password, no encryption, and
no claim of avoiding platform scanning or account restrictions**. Use only content
you are entitled to access and share. The MIT license covers this software, not
third-party content or dependencies.

## Development

```bash
nix develop
uv sync --locked
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

Nix pins only the development shell's `uv` through `flake.lock`. uv manages Python
(`.python-version`, currently 3.12), the local `.venv` and locked dependencies
(`uv.lock`). Python is not installed as a Nix shell package. If uv is already
available, entering the Nix shell is optional.

Maintain runtime dependencies in `pyproject.toml`. After intentionally changing
dependencies, update `uv.lock` and regenerate the committed deployment export:

```bash
uv lock
uv export --locked --no-dev --no-editable --no-emit-project \
  --no-hashes --format requirements-txt --output-file requirements.txt
```

Offline tests use generated images and fake metadata; they never contact a comic
site or QQ. Real upstream availability and QQ delivery require separate manual
integration checks. Do not place downloaded material or personal configuration
in this repository; `local/` is ignored for temporary local experimentation.

The deployment export omits hashes because AstrBot 4.27.5's dependency preflight
does not parse uv's multiline hash entries correctly. Versions remain pinned;
the complete dependency hashes remain available in `uv.lock` for local uv installs.

## Deployment

Copy the plugin's runtime files into AstrBot's plugin directory using the name
`astrbot_plugin_jm_comic_fetcher` from `metadata.yaml`. Keep `main.py`, metadata,
`_conf_schema.json`, `requirements.txt` and `jm_comic_fetcher/` together. Install
`requirements.txt` in **AstrBot's Python environment**, then reload the plugin.
The entry point checks worker imports so AstrBot can automatically install missing
dependencies even when no command has run yet. Recreating a container removes
packages manually installed in its old writable layer; keep `requirements.txt`
with the deployed plugin for recovery, or bake dependencies into a derived image.
Worker processes inherit the parent's Python search paths, including any extra
plugin dependency directories configured by AstrBot.
No editable installation of this project is needed. Python 3.12 or newer and an
AstrBot version supporting `GreedyStr` command arguments are required.

The repository does not know where it is deployed. The optional synchronization
script and Compose file belong to your deployment project, not this repository.
Never copy `.venv`, `.git`, test artifacts or local credentials into deployment.
Never edit the deployment copy as the authoritative source.

This version targets OneBot/NapCat. AstrBot and NapCat must see generated files
at the **same absolute path**, normally by sharing `/AstrBot/data`. Group and
private file messages use AstrBot's file-message adapter. Actual QQ size and
upload restrictions may differ from the configured local limit.

## Configuration

Configure the plugin in AstrBot WebUI. `_conf_schema.json` declares defaults; the
actual JSON configuration is maintained by AstrBot outside the source tree.
Save and reload the plugin to apply changes. Each loaded instance uses immutable
settings; running/queued jobs are cancelled on reload rather than silently changing
their limits. Empty allowlists deny all content commands; help remains available.

| Setting | Default | Meaning |
| --- | --- | --- |
| `allowed_user_ids` | `[]` | QQ user IDs as strings; required in private and group chats |
| `allowed_group_ids` | `[]` | Additional group allowlist; groups require both checks |
| `max_running` | 1 | Concurrent task processes, maximum 8 |
| `max_queued` | 3 | Additional waiting tasks; 0 disables extra queue capacity |
| `max_pending_per_user` | 1 | Running + waiting tasks per QQ user |
| `timeout_seconds` | 1800 | Running task timeout including upload, excluding queue wait |
| `image_concurrency` | 3 | Concurrent image requests per task, maximum 16 |
| `request_timeout_seconds` | 30 | Network request timeout |
| `max_retries` | 2 | Retries after the first attempt, maximum 5; metadata applies per domain |
| `max_chapters` | 10 | Selected chapters per task |
| `max_pages` | 500 | Selected pages per task, checked before image downloads |
| `max_download_mib` | 300 | Cumulative streamed image response bytes, including failed retries |
| `max_archive_mib` | 100 | Maximum final ZIP size; oversized archives are not sent |
| `min_free_disk_mib` | 1024 | Free space floor checked before tasks and during bulk writes |
| `max_image_megapixels` | 40 | Maximum pixels decoded from one image |
| `success_retention_hours` | 1 | Retention after adapter-reported successful delivery |
| `failure_retention_hours` | 24 | Retention of failed/interrupted task files |
| `cleanup_interval_minutes` | 30 | Expired task cleanup frequency |
| `proxy_url` | `""` | Optional HTTP(S) proxy; empty requests direct image connections |
| `api_domains` | `[]` | Optional API hostnames without scheme/path; empty uses upstream defaults |

1 MiB = 1,048,576 bytes. The download counter covers image response bodies, not
metadata, headers or TCP/TLS overhead. PDF and ZIP generation also need disk
space; download size alone is not a disk quota. Free-space checks are best effort
when other processes share the same disk. The worker process timeout is the final
bound for upstream domain retries, image processing and archive generation.

## Task lifecycle and data

All content commands use the bounded queue, including brief and cover queries.
This prevents metadata calls from bypassing the task limits. Each job runs in its
own child process so the parent can stop it on timeout or plugin unload. Queue
and job state are not resumed after a restart. No cross-task download cache or
automatic upload retry is implemented in v0.1.

AstrBot supplies the plugin data directory. Only that directory is used for jobs:

```text
<plugin-data>/jobs/<random-task-id>/
├── images/          # temporary; removed after each chapter PDF is produced
├── pdf/             # numbered chapter PDFs
├── selection.json   # selected chapter positions and total pages
├── chapters.txt
├── JM_<id>_*.zip
└── state.json       # completion time and success/failure for retention
```

Any missing/failed page fails the task; no partial archive is sent. Generated
files are retained after upload because an adapter accepting a send request does
not prove the recipient has finished downloading it. Failed uploads are reported
without automatic retries (to avoid duplicate sends). Cleanup only removes expired
UUID job directories and skips symlinks, unknown directories and active jobs.

## Manual acceptance

After deployment, add your QQ user ID to `allowed_user_ids`; add the test group
to `allowed_group_ids` for group tests, then reload. Test private chat first.
Use the same wake prefix / bot mention that works for `/help`.

1. `/jmcomic help` — English help, no network request.
2. `/jmcomic inspect 1451879 brief` — inspect the user-selected test comic's actual
   chapter numbering before downloading. This ID is not hardcoded in the plugin.
3. `/jmcomic fetch 1451879 1` — one PDF plus chapter index in one ZIP.
4. `/jmcomic fetch 1451879 --from 1 --to 2` — two PDFs in one ZIP, if those chapters
   exist; compare page order visually with the source.
5. `/jmcomic inspect 1451879 cover` — cover image inside a ZIP.
6. Repeat an attachment send in the allowlisted group and open it on your phone.
7. Try a reversed range, missing argument, denied user/group and `/jmcomic random`.

Do not make full-book downloads part of the routine test cycle. Increasing a limit
does not change the upstream's availability or the messaging platform's limits.
