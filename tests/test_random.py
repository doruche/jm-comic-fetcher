import asyncio
from unittest.mock import AsyncMock

import pytest
from jmcomic import JmMagicConstants, JmSearchPage, MissingAlbumPhotoException

from jm_comic_fetcher.client import Client
from jm_comic_fetcher.config import Config
from jm_comic_fetcher.models import Chapter, Comic, Request, UserError
from jm_comic_fetcher.protocol import WorkerRequest, WorkerResult
from jm_comic_fetcher.worker import run


def listing(ids, total):
    return JmSearchPage([(str(i), {"name": "Fixture"}) for i in ids], total)


def comic(comic_id="123"):
    return Comic(comic_id, "Fixture", "Description", (Chapter(1, "10", "Beginning"),))


@pytest.mark.parametrize("offset", range(7))
async def test_each_item_has_one_offset_including_short_last_page(monkeypatch, offset):
    # A three-item page deliberately differs from the library's hardcoded 80.
    pages = [listing([1, 2, 3], 7), listing([4, 5, 6], 7), listing([7], 7)]
    bounds = []

    def draw(total):
        bounds.append(total)
        return offset

    monkeypatch.setattr("jm_comic_fetcher.client.random.randrange", draw)
    async with Client(Config()) as client:
        client.api.categories_filter = AsyncMock(side_effect=lambda **kw: pages[kw["page"] - 1])
        client.comic = AsyncMock(side_effect=lambda cid: comic(cid))
        result = await client.random_comic()
        assert result.id == str(offset + 1)
        assert bounds == [7]
        calls = client.api.categories_filter.call_args_list
        assert [c.kwargs["page"] for c in calls] == ([1] if offset < 3 else [1, offset // 3 + 1])
        for call in calls:
            assert call.kwargs["time"] == JmMagicConstants.TIME_ALL
            assert call.kwargs["category"] == JmMagicConstants.CATEGORY_ALL
            assert call.kwargs["order_by"] == JmMagicConstants.ORDER_BY_LATEST


@pytest.mark.parametrize(
    "first", [listing([], 0), listing([1], 0), listing([], 5), listing([1, 2], 1)]
)
async def test_unusable_initial_total_fails_without_detail(first):
    async with Client(Config()) as client:
        client.api.categories_filter = AsyncMock(return_value=first)
        client.comic = AsyncMock()
        with pytest.raises(UserError, match="no usable total"):
            await client.random_comic()
        client.comic.assert_not_awaited()
        assert client.api.categories_filter.await_count == 1


@pytest.mark.parametrize("stale", [listing([], 4), listing([3], 4), listing([3, 4], 3)])
async def test_stale_target_refreshes_total_and_redraws(monkeypatch, stale):
    draws = iter([3, 0])
    bounds = []

    def draw(total):
        bounds.append(total)
        return next(draws)

    monkeypatch.setattr("jm_comic_fetcher.client.random.randrange", draw)
    async with Client(Config()) as client:
        client.api.categories_filter = AsyncMock(
            side_effect=[listing([1, 2], 4), stale, listing([5], 1)]
        )
        client.comic = AsyncMock(return_value=comic("5"))
        assert (await client.random_comic()).id == "5"
        assert bounds == [4, 1]
        client.comic.assert_awaited_once_with("5")


@pytest.mark.parametrize(
    "missing", [MissingAlbumPhotoException("secret", {}), Comic("1", "", "", ())]
)
async def test_unavailable_comic_is_redrawn(monkeypatch, missing):
    monkeypatch.setattr("jm_comic_fetcher.client.random.randrange", lambda total: 0)
    async with Client(Config()) as client:
        client.api.categories_filter = AsyncMock(side_effect=[listing([1], 1), listing([2], 1)])
        client.comic = AsyncMock(side_effect=[missing, comic("2")])
        assert (await client.random_comic()).id == "2"
        assert [c.args[0] for c in client.comic.call_args_list] == ["1", "2"]


@pytest.mark.parametrize("failure", ["empty_page", "missing_comic"])
async def test_redraws_are_bounded(monkeypatch, failure):
    monkeypatch.setattr("jm_comic_fetcher.client.random.randrange", lambda total: 1)
    async with Client(Config()) as client:
        client.api.categories_filter = AsyncMock(
            side_effect=lambda **kw: (
                listing([1], 2) if kw["page"] == 1 or failure == "missing_comic" else listing([], 2)
            )
        )
        client.comic = AsyncMock(side_effect=MissingAlbumPhotoException("secret", {}))
        with pytest.raises(UserError, match="after 3 attempts"):
            await client.random_comic()
        assert client.api.categories_filter.await_count == 6
        assert client.comic.await_count == (3 if failure == "missing_comic" else 0)


@pytest.mark.parametrize("where", ["listing", "detail"])
@pytest.mark.parametrize(
    "error", [TimeoutError(), RuntimeError("secret"), asyncio.CancelledError()]
)
async def test_network_unexpected_errors_and_cancellation_are_not_redrawn(
    monkeypatch, where, error
):
    monkeypatch.setattr("jm_comic_fetcher.client.random.randrange", lambda total: 0)
    async with Client(Config()) as client:
        client.api.categories_filter = AsyncMock(return_value=listing([1], 1))
        client.comic = AsyncMock()
        target = client.api.categories_filter if where == "listing" else client.comic
        target.side_effect = error
        with pytest.raises(type(error)):
            await client.random_comic()
        assert client.api.categories_filter.await_count == 1
        assert target.await_count == 1


async def test_invalid_candidate_is_not_queried(monkeypatch):
    monkeypatch.setattr("jm_comic_fetcher.client.random.randrange", lambda total: 0)
    async with Client(Config()) as client:
        client.api.categories_filter = AsyncMock(return_value=listing(["../secret"], 1))
        client.comic = AsyncMock()
        with pytest.raises(UserError, match="invalid comic ID"):
            await client.random_comic()
        client.comic.assert_not_awaited()


async def test_worker_random_returns_brief_without_files(tmp_path, monkeypatch):
    from jmcomic import AsyncJmApiClient

    monkeypatch.setattr("jm_comic_fetcher.client.random.randrange", lambda total: 0)
    monkeypatch.setattr(
        AsyncJmApiClient, "categories_filter", AsyncMock(return_value=listing([123], 1))
    )
    detail = AsyncMock(return_value=comic())
    monkeypatch.setattr(Client, "comic", detail)
    for method in ("stream_image", "chapter_images", "cover", "page"):
        monkeypatch.setattr(
            Client, method, AsyncMock(side_effect=AssertionError("Unexpected download"))
        )
    result = await run(WorkerRequest(Request("random", ""), Config(), tmp_path).to_dict())
    assert WorkerResult.from_dict(result.to_dict()) == result
    assert result.status == "ok" and result.archive is None
    assert result.text == "Fixture\nID: 123\nDescription: Description\nChapters (1):\n1. Beginning"
    detail.assert_awaited_once_with("123")
    assert list(tmp_path.iterdir()) == []
