# JM Comic Fetcher

An AstrBot plugin for querying comic information and downloading selected chapters
as PDF files in a ZIP archive. Uses [jmcomic](https://github.com/hect0x7/JMComic-Crawler-Python)
and currently supports OneBot/NapCat.

## Usage

```text
/jmcomic help
/jmcomic inspect <comic_id> brief
/jmcomic inspect <comic_id> cover
/jmcomic fetch <comic_id>
/jmcomic fetch <comic_id> 3
/jmcomic fetch <comic_id> --from 2 --to 4
```

- `brief` returns the title, description and numbered chapter list.
- `cover` returns the original cover image in a ZIP.
- `fetch` returns one PDF per selected chapter, packed into one ZIP with a chapter index.
- Chapter numbers start at **1** and match `inspect brief`. Omit the chapter or
  use `0` to select all chapters, subject to configured limits.
- Ranges include both endpoints. Supply both `--from` and `--to`; do not combine
  them with a positional chapter.
- `/jmcomic random` is reserved but not implemented.

Command help and status messages are in English. Archives are ordinary ZIP files
and require no password. Use content you are entitled to access and share.

## Installation and configuration

Requires Python 3.12–3.14 and AstrBot with `GreedyStr` command support.

Install through AstrBot's plugin manager, or copy this repository's plugin files
into `data/plugins/astrbot_plugin_jm_comic_fetcher/` and reload the plugin.
Keep `requirements.txt` with the plugin so AstrBot can install missing dependencies.
Do not copy your development `.venv`.

In the plugin's WebUI configuration:

1. Add your QQ user ID to `allowed_user_ids`.
2. For group use, also add the group ID to `allowed_group_ids`.
3. Save and reload the plugin.

Empty allowlists deny content commands. Defaults allow one running task,
up to 10 selected chapters and a 100 MiB final ZIP. Other limits and network
options are described in [Configuration](docs/configuration.md).

For Docker deployments, AstrBot and NapCat must be able to read attachment files
at the same absolute path, normally through a shared `/AstrBot/data` mount.

## Development

```bash
nix develop
uv sync --locked
uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked python scripts/requirements.py --check
```

Nix provides a pinned uv; uv manages Python, `.venv` and the development lockfile.
If uv is already installed, entering the Nix shell is optional.

Declare runtime dependencies once in `pyproject.toml`. After changing them:

```bash
uv lock
uv run --locked python scripts/requirements.py
```

`requirements.txt` is generated from the **direct dependencies and version ranges**.
Do not edit it by hand. `uv.lock` pins the development environment; its complete
dependency graph is not imposed on AstrBot's shared Python environment.

## License

[MIT](LICENSE). Third-party dependencies and content retain their own licenses.
