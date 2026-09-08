# Configuration

Configure the plugin in AstrBot WebUI. `_conf_schema.json` declares defaults; the
actual JSON configuration is maintained by AstrBot outside the source tree.
Save and reload the plugin to apply changes. Each loaded instance uses immutable
settings; running/queued jobs are cancelled on reload rather than silently changing
their limits. Empty blocklists allow content commands; help and version remain
available even for blocked users/groups. A blocked user is denied in private chats
and all groups; a blocked group denies every user's content commands in that group.
The plugin does not verify QQ friendship or group membership. AstrBot's own access
restrictions and wake rules continue to apply.

Since v0.3.0, `allowed_user_ids` and `allowed_group_ids` are ignored, not migrated.
Both new blocklists default to empty, including on upgrades from old configurations.

| Setting | Default | Meaning |
| --- | --- | --- |
| `blocked_user_ids` | `[]` | QQ user IDs as strings; denied in private chats and all groups |
| `blocked_group_ids` | `[]` | QQ group IDs as strings; denies content commands for everyone in these groups |
| `max_running` | 1 | Concurrent task processes, maximum 8 |
| `max_queued` | 3 | Additional waiting tasks; 0 disables extra queue capacity |
| `max_pending_per_user` | 1 | Running + waiting tasks per QQ user |
| `timeout_seconds` | 1800 | Running task timeout including upload, excluding queue wait |
| `image_concurrency` | 3 | Concurrent image requests per task, maximum 16 |
| `request_timeout_seconds` | 30 | Network request timeout |
| `max_retries` | 2 | Retries after the first attempt, maximum 5; metadata applies per domain |
| `max_chapters` | 10 | Selected chapters per task |
| `max_pages` | 500 | Selected pages per task, checked before image downloads |
| `max_download_mib` | 300 | Cumulative streamed image response bytes, including failed retries |
| `max_archive_mib` | 100 | Maximum final ZIP size; oversized archives are not sent |
| `min_free_disk_mib` | 1024 | Free space floor checked before tasks and during bulk writes |
| `max_image_megapixels` | 40 | Maximum pixels decoded from one image |
| `success_retention_hours` | 1 | Retention after adapter-reported successful delivery, even if completion notification fails |
| `failure_retention_hours` | 24 | Retention of failed, interrupted or unconfirmed task files |
| `cleanup_interval_minutes` | 30 | Expired task cleanup frequency |
| `proxy_url` | `""` | Optional HTTP(S) proxy; empty requests direct image connections |
| `api_domains` | `[]` | Optional API hostnames without scheme/path; empty uses upstream defaults |

1 MiB = 1,048,576 bytes. The download counter covers image response bodies, not
metadata, headers or TCP/TLS overhead. PDF and ZIP generation also need disk
space; download size alone is not a disk quota. Free-space checks are best effort
when other processes share the same disk. The worker process timeout is the final
bound for upstream domain retries, image processing and archive generation.
