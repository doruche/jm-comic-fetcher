import pytest

from jm_comic_fetcher.commands import HELP, parse_command, split_text
from jm_comic_fetcher.config import Config
from jm_comic_fetcher.models import Chapter, Comic, UserError


@pytest.mark.parametrize(
    "args,selected",
    [
        ("fetch 123", [1, 2, 3, 4]),
        ("fetch 123 0", [1, 2, 3, 4]),
        ("fetch 123 3", [3]),
        ("fetch 123 --from 2 --to 4", [2, 3, 4]),
        ("fetch 123 --to 3 --from 2", [2, 3]),
    ],
)
def test_selection(args, selected):
    comic = Comic("123", "test", "", tuple(Chapter(i, str(i), str(i)) for i in range(1, 5)))
    assert [c.index for c in parse_command(args).select(comic, 10)] == selected


@pytest.mark.parametrize(
    "args",
    [
        "fetch",
        "fetch ../a",
        "fetch 123 -1",
        "fetch 123 1 --from 2 --to 3",
        "fetch 123 --from 2",
        "fetch 123 --from 3 --to 2",
        "fetch 123 --from 0 --to 2",
        "fetch 123 --from 2 --from 3",
        "inspect 123",
        "inspect 123 bad",
        "fetch 123 'a",
    ],
)
def test_invalid_command(args):
    with pytest.raises(UserError):
        parse_command(args)


def test_english_help_and_lossless_chunking():
    assert HELP.isascii()
    assert parse_command("help") is None
    text = "long title " * 900
    chunks = split_text(text)
    assert "".join(chunks) == text
    assert max(map(len, chunks)) <= 1500


def test_config_and_permissions():
    config = Config.from_mapping({"allowed_user_ids": ["123"], "allowed_group_ids": ["456"]})
    config.authorize("123", "")
    config.authorize("123", "456")
    for user, group in [("999", "456"), ("123", "999")]:
        with pytest.raises(UserError):
            config.authorize(user, group)
    for values in [
        {"max_running": 0},
        {"max_pages": True},
        {"max_retries": 6},
        {"allowed_user_ids": [123]},
        {"proxy_url": "socks5://host"},
    ]:
        with pytest.raises(UserError):
            Config.from_mapping(values)


def test_schema_defaults_match_runtime():
    import json
    from dataclasses import asdict
    from pathlib import Path

    schema = json.loads((Path(__file__).resolve().parents[1] / "_conf_schema.json").read_text())
    assert set(schema) == set(asdict(Config()))
    assert Config.from_mapping({k: v["default"] for k, v in schema.items()}) == Config()
