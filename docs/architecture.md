# Implementation notes

The AstrBot entry point handles commands, access control, scheduling and delivery.
Heavy network and archive work runs in child Python processes so timeouts and
plugin unload can stop it. Each task launches the Python executable of a private
virtual environment; stdin/stdout carry one JSON request and result.

The entry point, scheduler and runtime setup use only AstrBot APIs and the standard
library. Worker-only dependencies are never imported by the host. Workers use
Python isolated mode, adding only the plugin source root explicitly; host Python
search paths and user site-packages are excluded.

`pyproject.toml` declares dependencies and the official PyPI index. `uv.lock` pins
the same dependency graph for development and production. Initialization invokes
uv as an external tool to synchronize production packages into a private data
directory, without changing AstrBot packages or installer settings. See
[Installation](installation.md) for prerequisites and environment recovery.

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
