# Implementation notes

The AstrBot entry point handles commands, access control, scheduling and delivery.
Heavy network and archive work runs in child Python processes so timeouts and
plugin unload can stop it. Each task launches the Python executable of a private
virtual environment; stdin/stdout carry one JSON request and result validated by
`protocol.py`. Success and failure results are mutually exclusive; archive paths
must be ZIP basenames. The service depends on a small `ComicClient` protocol and
plain `Page` descriptions, keeping upstream library objects inside `Client`.

The entry point, scheduler and runtime setup use only AstrBot APIs and the standard
library. Worker-only dependencies are never imported by the host. Workers use
Python isolated mode, adding only the plugin source root explicitly; host Python
search paths and user site-packages are excluded.

`pyproject.toml` declares dependencies and the official PyPI index. `uv.lock` pins
the same dependency graph for development and production. Initialization invokes
uv as an external tool to synchronize production packages into a private data
directory, without changing AstrBot packages or installer settings. See
[Installation](installation.md) for prerequisites and environment recovery.

All content commands share a bounded queue. `processes.py` owns process creation,
communication and process-group cleanup for both environment setup and workers.
Cancellation waits for cleanup even if the direct process has already exited or
cancellation is repeated. The plugin also owns its initialization task, so shutdown
cannot leave initialization installing packages or starting a new cleanup loop.
Content commands report that initialization is in progress until the runtime and
scheduler are ready; help/version do not require runtime readiness.
Background filesystem cleanup runs in an owned thread; unload waits for it before
a new instance can start. Removing an already-deleted directory is harmless.

State is not resumed after reload.
Images pass structural verification and complete pixel decoding (all frames),
with pixel limits checked before decoding. Valid JPEG/PNG files can still be
embedded without re-encoding. Failed/missing pages cancel remaining downloads and
fail the task without sending a partial archive. There is
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

## Task results and diagnostics

`state.json` is atomically replaced when a task finishes. It separately records
`generation`, `delivery`, `notification`, `outcome` and the final `stage`.
An adapter's successful file-send return immediately sets delivery to `accepted`;
a failed/cancelled completion notification does not undo that result. `accepted`
means only that the send API returned successfully, not recipient-side acceptance.

An explicit adapter rejection records `rejected`. An exception, timeout or
cancellation during a send records `unknown`, with outcome `uncertain`; users are
asked to check the chat before retrying. A text-only inspection succeeds only when
its result notification succeeds. No automatic send retry is performed.

The `success` field remains for retention and compatibility with older completion
files. Successful sends use success retention even if their follow-up text fails;
failed, cancelled and uncertain tasks use failure retention. State is a terminal
snapshot, not a crash-resumable journal: a hard process crash can leave no completion
file, which cleanup treats as an incomplete task.

Worker failures carry an originating stage (request, client, metadata, download,
decode, PDF or archive). Host logs associate diagnostics with the job ID and record
exception type, file/function/line and safe numeric details such as errno. Exception
messages, traceback locals, URLs, cookies and response bodies are not copied to
logs. Installer stderr is classified into bounded hints such as disk, certificate,
download, build, lockfile and unsupported-tool errors. Unexpected failures give
chat a safe stage-based message; expected user errors retain their useful explanation.
