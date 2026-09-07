# Implementation notes

The AstrBot entry point handles commands, access control, scheduling and delivery.
Heavy network and archive work runs in child Python processes so timeouts and
plugin unload can stop it. Workers inherit the parent's dependency search paths.

Runtime requirements are generated from `project.dependencies` by a standard
library TOML reader. AstrBot installs missing dependencies through its native
requirements mechanism. The entry point validates the worker import graph to
trigger that mechanism before accepting commands. It does not install packages
or reload shared modules itself.

The developer's `uv.lock` is separate from the plugin's host-facing requirements:
it locks a standalone environment, whereas requirements preserve the declared
compatibility ranges. Sharing a Python environment still requires compatibility
testing when dependencies or the host image change.

All content commands share a bounded queue. State is not resumed after reload.
Failed/missing pages fail the task without sending a partial archive. There is
no cross-task download cache or automatic upload retry.

AstrBot supplies a plugin data directory. Private `jobs/<uuid>/` directories
(0700) hold intermediate images, numbered PDFs, selection metadata, final ZIP
and completion state. Completed archives are hard-linked to
`deliveries/<uuid>/` (0711 directories, 0644 files), allowing a NapCat process
under a different Unix UID to read only the published archive. Expiration cleanup
removes both links, skipping active jobs, symlinks and unrelated directories.

Files are retained after the send API returns because that return does not prove
that the recipient has finished downloading. Download budgets count streamed
image bodies, including retries and redirects; final archive size and disk
space have separate guards.
