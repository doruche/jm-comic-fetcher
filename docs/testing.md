# Integration testing

The normal `uv run --locked pytest -q` suite is offline and uses generated images.
It also checks that `requirements.txt` matches the direct declarations in
`pyproject.toml`.

## Native AstrBot installation

```bash
uv run --locked python scripts/check_astrbot.py --image soulter/astrbot:latest
```

This opt-in check needs Docker and network access to PyPI. It resolves the local
image ID once and runs two independent disposable containers without host ports,
QQ accounts or production data. Each round:

- checks pip's installation plan for changes to any existing host package;
- starts the real AstrBot process and exercises native missing-dependency recovery;
- checks that all previously installed packages retain their versions;
- requests the running WebUI repeatedly to exercise its loaded async backend;
- checks worker imports and generated two-chapter PDF/ZIP processing;
- runs pip's compatibility check.

The test uses no real comic downloads or QQ messages. Passing for one image does
not establish compatibility with every future image or plugin combination.
Use `--image` to check a specific version or image ID.

## QQ acceptance

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
