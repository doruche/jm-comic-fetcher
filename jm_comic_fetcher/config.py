from dataclasses import asdict, dataclass, fields
from urllib.parse import urlsplit

from .models import UserError

MIB = 1024 * 1024


@dataclass(frozen=True)
class Config:
    blocked_user_ids: tuple[str, ...] = ()
    blocked_group_ids: tuple[str, ...] = ()
    max_running: int = 1
    max_queued: int = 3
    max_pending_per_user: int = 1
    timeout_seconds: int = 1800
    image_concurrency: int = 3
    request_timeout_seconds: int = 30
    max_retries: int = 2
    max_chapters: int = 10
    max_pages: int = 500
    max_download_mib: int = 300
    max_archive_mib: int = 100
    min_free_disk_mib: int = 1024
    max_image_megapixels: int = 40
    success_retention_hours: int = 1
    failure_retention_hours: int = 24
    cleanup_interval_minutes: int = 30
    proxy_url: str = ""
    api_domains: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, raw: dict) -> "Config":
        values = {}
        defaults = cls()
        for field in fields(cls):
            name = field.name
            default = getattr(defaults, name)
            value = raw.get(name, default)
            if isinstance(default, tuple):
                if not isinstance(value, (tuple, list)) or not all(
                    isinstance(item, str) for item in value
                ):
                    raise UserError(f"Config {name} must be a list of strings.")
                value = tuple(item.strip() for item in value if item.strip())
                if name.startswith("blocked_") and any(
                    not x.isascii() or not x.isdigit() for x in value
                ):
                    raise UserError(f"Config {name} must contain numeric IDs as strings.")
                if name == "api_domains" and any(
                    not x or any(c in x for c in "/:@?# ") for x in value
                ):
                    raise UserError("Config api_domains must contain hostnames, without schemes.")
            elif isinstance(default, int):
                lower = 0 if name in {"max_queued", "max_retries"} else 1
                if type(value) is not int or value < lower:
                    raise UserError(f"Config {name} must be an integer >= {lower}.")
            elif not isinstance(value, str):
                raise UserError(f"Config {name} must be a string.")
            values[name] = value
        config = cls(**values)
        if config.max_running > 8 or config.image_concurrency > 16 or config.max_retries > 5:
            raise UserError("Limits: max_running <= 8, image_concurrency <= 16, max_retries <= 5.")
        if config.proxy_url and urlsplit(config.proxy_url).scheme not in {"http", "https"}:
            raise UserError("Config proxy_url must use http:// or https://.")
        return config

    def authorize(self, user_id: str, group_id: str) -> None:
        if user_id in self.blocked_user_ids:
            raise UserError("Access denied: your user ID is blocked.")
        if group_id and group_id in self.blocked_group_ids:
            raise UserError("Access denied: this group is blocked.")

    def worker_config(self) -> dict:
        """Do not pass chat identities into the download process."""
        result = asdict(self)
        result["blocked_user_ids"] = []
        result["blocked_group_ids"] = []
        return result
