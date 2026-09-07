# Validation

## Current dependency policy (2026-09-07)

Deployment requirements now contain only direct declarations from
`pyproject.toml`, preserving their compatibility ranges. `uv.lock` remains the
standalone development lockfile. Pillow is declared directly because the plugin
imports it. The full transitive lock export described in older entries below
has been superseded.

The diagnosed WebUI failure was an in-process AnyIO version mix: installation
upgraded 4.14.2 to 4.15.1 after AstrBot had imported older modules. Its subsequently
loaded backend could not import `get_coro_name`; new interpreters worked, while
the existing WebUI returned HTTP 500. `pip check` alone could not detect this.

47 offline tests and Ruff pass. The opt-in `scripts/check_astrbot.py` ran two
independent clean containers based on image
`sha256:1db1792902be5ccecfb907a720ae22b233ebdc958854d860fc73d7f95a720637`.
Both rounds passed pip plan checks and actual AstrBot native auto-installation:
all 167 pre-existing distributions retained their versions, including AnyIO
4.14.2 and lxml 6.1.2. Repeated WebUI requests returned HTTP 200, real child
worker import/config processing passed, generated two-chapter PDF/ZIP processing
passed, and `pip check` passed. No production data or QQ accounts were mounted.

Independent read-only review found no blocking issues in dependency generation,
the container check or documentation split. The README's Python version range
was corrected to match project metadata.

The plugin was synchronized and only AstrBot was restarted in the existing
deployment. No Compose, account configuration or installed package versions
were changed. The fresh process successfully loaded the plugin with the already
installed AnyIO 4.15.1 and lxml 6.1.3. Five consecutive WebUI requests returned
HTTP 200; port 6199 was listening with an established OneBot connection.
The deployed worker and generated two-chapter PDF/ZIP check also passed, followed
by another HTTP 200. `uv pip check` passed for all 172 installed packages.
No real comic download or QQ send was performed for this recovery check.

These checks establish compatibility with this image and current resolved
dependencies, not arbitrary future releases or other plugin combinations.

## Earlier implementation checks

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

## Cross-container archive permissions

QQ acceptance task `80d1e093` generated its archive successfully, but NapCat
reported `EACCES` opening it: AstrBot ran as root, QQ/NapCat as UID/GID 1000,
and the task directory was intentionally 0700. This was a filesystem permission
failure, not a QQ allowlist or group-administrator requirement.

Completed archives are now hard-linked into traversal-only delivery directories
(0711) with readable final ZIPs (0644); job working directories remain 0700.
Expiration cleanup removes both links. Regression tests cover restrictive umask,
publication, symlink rejection, repeat publication and active/expired cleanup.
40 tests and Ruff passed; independent subagent review found no further issues.

Verified against the actual failed archive: `docker exec --user 1000:1000 napcat`
read ZIP magic `50 4b 03 04` from the new delivery path, while confirming the
original job directory was still inaccessible. No QQ send was made by this check;
recipient-side upload acceptance remains to be confirmed.
