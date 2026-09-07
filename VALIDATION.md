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

## Container recreation regression

A user acceptance task failed after the container was recreated at 22:30.
Direct reproduction inside that container showed `ModuleNotFoundError: jmcomic`:
packages previously installed into the old container layer were gone, while the
plugin's lightweight entry point did not trigger AstrBot's import-time recovery.

The entry point now validates the complete worker import graph so AstrBot can
install missing requirements. Workers also inherit resolved parent Python search
paths, covering installations that use an additional plugin dependency directory.
Unexpected worker exits expose only a missing-module identifier or exit code,
not raw stderr or credentials.

After the fix, 38 offline tests and Ruff passed; an independent subagent verified
the import-recovery contract and found no additional issues. Regression tests
include a real child interpreter with dependencies available only through parent
runtime path additions. Container startup logs confirmed automatic installation
was triggered by the missing worker dependency.

Integration verification then completed in the recreated container: AstrBot
automatically installed the seven missing/mismatched packages, loaded the plugin
and reconnected OneBot. `uv pip check` passed for all 172 installed packages.
The deployed `run_worker` downloaded chapter 1 of `1451879`, produced a 21-page
PDF in a 22,640,245-byte ZIP, and passed ZIP integrity/PDF page-count checks.
This verification used the container's Python and deployed files, not the host
development virtual environment. No QQ message was sent by the check.
