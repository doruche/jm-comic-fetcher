# Validation

Checked on 2026-09-07 against the local Python 3.12.14 AstrBot/NapCat deployment.

- Offline automated tests: 35 passed. Generated-image PDF page order, inclusive
  chapter ranges, incomplete-download rejection, ordinary ZIP contents, streamed
  byte accounting (including retries and redirects), archive limits, allowlists,
  cleanup scope, queue bounds, timeout and unload cancellation are covered.
- Ruff lint and formatting checks passed.
- Nix devShell provides uv 0.12.5; Python and dependencies are managed by uv.
- `jmcomic==2.7.5` queried the user-selected nonsexual test comic `1451879` and
  returned 51 chapters. Missing chapter names are displayed as `Chapter N`.
- Real range download of chapters 1–2 completed: 21 + 18 = 39 PDF pages.
  The ordinary ZIP was 41,556,664 bytes and contained `001.pdf`, `002.pdf`,
  `chapters.txt`. ZIP integrity and PDF page counts passed local validation.
- Real cover download succeeded; its ZIP contained the original `cover.webp`
  and passed ZIP integrity verification.
- Runtime dependency installation was checked against the existing container:
  `uv pip check` reported all 172 installed packages compatible. The install
  upgraded anyio 4.14.2 to 4.15.1 and lxml 6.1.2 to 6.1.3 inside the container.
- AstrBot 4.27.5 loaded both this plugin and the migrated Ping plugin; OneBot
  reconnected. Deployment requirements omit multiline hashes for compatibility
  with AstrBot's dependency preflight parser (versions are still pinned).
- An independent subagent reviewed the source, deployment script and installed
  AstrBot/jmcomic APIs. Two findings (redirect accounting and admission shutdown)
  were fixed and regression-tested. Re-review: 35 tests passed, no new findings.

Pending recipient-side acceptance: confirm private and group file delivery,
open ZIP/PDF on the actual phone, and visually verify decoded page order/content.
No automated test sends QQ messages. These checks cannot be inferred from a
successful local download or adapter source inspection.
