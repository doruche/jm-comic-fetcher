# Installation

## Requirements

- Linux, Python 3.12–3.14, and AstrBot with `GreedyStr` command support.
- uv >= 0.12.5 on AstrBot's PATH, with network access to `pypi.org` and
  `files.pythonhosted.org` for initial installation and dependency updates.
- A writable AstrBot plugin data directory with space for packages and archives.
- OneBot/NapCat for sending files. Both processes must see published attachments
  at the same absolute path; Docker deployments normally share `/AstrBot/data`.

The plugin repository is self-contained. It does not require any parent repository,
Compose file, sync script, Nix installation, or particular host directory layout.
Nix is an optional development convenience.

## Provide uv

For a native installation, install uv using the instructions at
<https://docs.astral.sh/uv/getting-started/installation/>. Make its executable
available on the PATH of the account/service that starts AstrBot, and verify
`uv --version` there. Installing it for an interactive shell does not necessarily
make it available to a system service. uv is an external executable; installing
it does not require installing plugin packages into AstrBot's Python environment.

For Docker, first check `uv --version` inside the AstrBot container. If the chosen
image already contains a supported uv, no image changes are necessary. Otherwise,
build a derived image with this Dockerfile and use that image for your AstrBot
service (pin the AstrBot image version or digest for reproducible deployments):

```dockerfile
ARG ASTRBOT_IMAGE=soulter/astrbot:latest
FROM ${ASTRBOT_IMAGE}
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /usr/local/bin/uv
```

Providing uv in the image survives container recreation. Installing uv only on
the Docker host does not provide it inside the container.

## Install the plugin

Install this repository through AstrBot's plugin manager, or clone it directly
into `<AstrBot data directory>/plugins/astrbot_plugin_jm_comic_fetcher` and reload.
Copying source files is also supported. Include `main.py`, `metadata.yaml`,
`_conf_schema.json`, `jm_comic_fetcher/`, `pyproject.toml` and `uv.lock`.
Do not copy development virtual environments or runtime data between machines.

Set the user/group allowlists in AstrBot's plugin configuration. See the README
for commands and [Configuration](configuration.md) for limits.

## Runtime ownership and recovery

The plugin obtains its data directory from AstrBot. `runtime/` below that directory
contains private environments and a package cache. Its source directory can be
read-only. Keep the data directory on a local filesystem supporting POSIX file locks.

Initialization uses `uv sync --locked --no-default-groups` with an explicit official
PyPI index, host configuration discovery disabled and package-manager environment
variables removed. Normal proxy and certificate settings are preserved. AstrBot's
package index configuration is neither read nor changed. There is no mirror or
shared-environment fallback, and uv will not download another Python interpreter.

A hash of `pyproject.toml`, `uv.lock` and the base Python identity selects an
environment. Setup is serialized with a file lock and only marked ready after
worker imports succeed. Failed/interrupted setup is rebuilt on the next reload;
a broken ready environment is also rebuilt. Setup has a ten-minute timeout.
An unchanged ready environment can be reused without uv or network access.

After changing Python or recreating the base image, the plugin checks the selected
environment and creates/rebuilds it when needed. Virtual environments still depend
on the base interpreter and OS libraries; they are not portable container images.
If setup fails, check uv availability, Python support, PyPI access and free disk
space, then reload. Source updates should be followed by a plugin reload.

Old environments are retained so an update cannot remove packages from an active
worker. To reclaim space or force a complete rebuild, unload the plugin, remove
only its `runtime/` directory, then load it again. Leave `jobs/` and `deliveries/`
alone unless you also intend to remove retained task files.
