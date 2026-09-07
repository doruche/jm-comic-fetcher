# JM Comic Fetcher

An AstrBot plugin for querying comic information and downloading selected chapters
as PDF files in a ZIP archive. Uses [jmcomic](https://github.com/hect0x7/JMComic-Crawler-Python)
and currently supports OneBot/NapCat.

## Usage

```text
/jmcomic help
/jmcomic version
/jmcomic inspect <comic_id> brief
/jmcomic inspect <comic_id> cover
/jmcomic fetch <comic_id>
/jmcomic fetch <comic_id> 3
/jmcomic fetch <comic_id> --from 2 --to 4
```

- `version` shows the version, description, author and license name; no allowlist is required.
- `brief` returns the title, description and numbered chapter list.
- `cover` returns the original cover image in a ZIP.
- `fetch` returns one PDF per selected chapter, packed into one ZIP with a chapter index.
- Chapter numbers start at **1** and match `inspect brief`. Omit the chapter or
  use `0` to select all chapters, subject to configured limits.
- Ranges include both endpoints. Supply both `--from` and `--to`; do not combine
  them with a positional chapter.
- `/jmcomic random` is reserved but not implemented.

A successful file-send result remains successful if its follow-up notification fails.
If delivery cannot be confirmed, check the chat before retrying; sends are not
automatically retried.

Command help and status messages are in English. Archives are ordinary ZIP files
and require no password. Use content you are entitled to access and share.

## Installation and configuration

Supports Linux with Python 3.12–3.14, AstrBot with `GreedyStr` command support,
and **uv >= 0.12.5 available on the PATH of the process running AstrBot**.
See [Installation](docs/installation.md) for native and Docker setup.

Clone this repository into AstrBot's plugin directory as
`astrbot_plugin_jm_comic_fetcher`, or install its Git repository through AstrBot's
plugin manager, then reload. Keep `pyproject.toml` and `uv.lock` with the source;
do not copy a development `.venv`.

On initialization the plugin creates its own virtual environment in its AstrBot
plugin data directory and installs the locked production dependencies from official
PyPI. Initial setup needs network access and can take up to ten minutes. Subsequent
loads reuse the environment after checking worker imports. No business dependency
is installed into AstrBot's Python environment.

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
```

Nix provides pinned uv and act; uv manages Python, `.venv` and the lockfile.
If uv is already installed, entering the Nix shell is optional. act can run the
GitHub Actions checks locally; see [Testing](docs/testing.md).

Declare runtime dependencies in `pyproject.toml`, run `uv lock`, and commit both
files. `uv.lock` controls development and production; production excludes development
groups. The repository declares official PyPI as its default index. Plugin setup
also explicitly isolates installer settings from the host.

Run the offline tests and, for runtime changes, the disposable-container check in
[Testing](docs/testing.md). No parent repository or local deployment script is required.

## License

[MIT](LICENSE). Third-party dependencies and content retain their own licenses.
