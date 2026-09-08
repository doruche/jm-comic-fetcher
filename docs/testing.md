# Integration testing

The normal `uv run --locked pytest -q` suite is offline and uses generated images.
It covers command/limit behavior, archives, scheduling and cancellation, installer
configuration isolation, concurrent setup, failed/corrupt environment recovery,
lock/Python changes, and separation from host Python dependencies. Regression
checks include real process groups whose parent exits before a descendant,
cancellation during spawn, cleanup threads that outlive their coroutine, truncated
JPEG/PNG rejection, invalid worker replies, and file delivery followed by failed
notifications. Tests use temporary files and generated images; they do not simulate
recipient-side QQ acceptance. Host initialization/shutdown ordering is also reviewed
against AstrBot's lifecycle source rather than recreated in a mock framework.

## GitHub Actions and local act

`.github/workflows/check.yml` runs the offline test suite and Ruff checks on Python
3.12, 3.13 and 3.14 for pushes and pull requests. The container integration check
below remains opt-in.

The Nix development shell includes act, pinned by `flake.lock`. With access to a
running Docker daemon, run these commands from this repository:

```bash
nix develop
act --list
act push -j test --matrix python:3.12 -P ubuntu-latest=catthehacker/ubuntu:act-latest
```

Omit `--matrix python:3.12` to run all three Python versions. The explicit runner
image avoids act's initial image-selection prompt. The first run downloads the
runner image, actions, Python and packages; it requires network access. act does
not send QQ messages or load production AstrBot data. It approximates GitHub's
runner and does not replace a successful run on GitHub itself.

## Independent AstrBot installation

```bash
uv run --locked python scripts/check_astrbot.py --image soulter/astrbot:latest
```

This opt-in check needs Docker access and network access to official PyPI. The
selected Linux image must contain Python 3.12–3.14 and uv >= 0.12.5, as documented
in [Installation](installation.md). It resolves the local image ID once and runs
two independent disposable containers without host ports, accounts or production
data. Source is mounted read-only. Each round:

- starts real AstrBot and loads the plugin without host dependency installation;
- builds and reuses the private environment despite conflicting host uv settings;
- checks that no host packages are added, removed or changed;
- requests the WebUI repeatedly to exercise its loaded async backend;
- runs the real worker and generated two-chapter PDF/ZIP processing in its venv.

No real comic downloads or QQ messages are sent. Run this from the plugin repository;
no external deployment files are used. Use `--image` to check a specific image and
`--rounds 1` for a single clean installation.

## QQ acceptance

After deployment, add your QQ user ID to `allowed_user_ids`; add the test group
to `allowed_group_ids` for group tests, then reload. Test private chat first.
Use the same wake prefix / bot mention that works for `/help`.

1. `/jmcomic help` — English help, no network request.
2. `/jmcomic inspect <comic_id> brief` — choose a comic you can access and inspect its
   actual chapter numbering before downloading.
3. `/jmcomic fetch <comic_id> 1` — one PDF plus chapter index in one ZIP.
4. `/jmcomic fetch <comic_id> --from 1 --to 2` — two PDFs in one ZIP, if those chapters
   exist; compare page order visually with the source.
5. `/jmcomic inspect <comic_id> cover` — cover image inside a ZIP.
6. Repeat an attachment send in the allowlisted group and open it on your phone.
7. `/jmcomic random` — an ID, description and numbered chapter list, with no
   attachment. Inspect the returned ID with `inspect <comic_id> brief` and compare.
   Repeated draws may repeat an ID; sampling covers the reported latest-list range.
8. Try a reversed range, missing argument and denied user/group (including random).

Do not make full-book downloads part of the routine test cycle. Increasing a limit
does not change the upstream's availability or the messaging platform's limits.
