import httpx
import pytest

from scraper.http import USER_AGENT, Fetcher, FetchError


def fetcher_for(handler):
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), headers={"User-Agent": USER_AGENT}
    )
    return Fetcher(client=client, base_delay=0)


async def test_retries_then_succeeds():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503) if len(calls) < 3 else httpx.Response(200, json={"ok": True})

    async with fetcher_for(handler) as f:
        assert await f.json("GET", "https://api.example.com/x") == {"ok": True}
    assert len(calls) == 3
    assert calls[0].headers["User-Agent"] == USER_AGENT


async def test_404_is_not_retried():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(404)

    async with fetcher_for(handler) as f:
        with pytest.raises(FetchError) as e:
            await f.json("GET", "https://api.example.com/x")
    assert e.value.status == 404 and len(calls) == 1


async def test_gives_up_after_retries():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(429)

    async with fetcher_for(handler) as f:
        with pytest.raises(FetchError) as e:
            await f.json("GET", "https://api.example.com/x")
    assert e.value.status == 429 and len(calls) == 4


async def test_network_error_wrapped():
    def handler(request):
        raise httpx.ConnectTimeout("timed out")

    async with fetcher_for(handler) as f:
        with pytest.raises(FetchError, match="ConnectTimeout"):
            await f.json("GET", "https://api.example.com/x")


async def test_invalid_json():
    async with fetcher_for(lambda r: httpx.Response(200, text="<html>")) as f:
        with pytest.raises(FetchError, match="invalid JSON"):
            await f.json("GET", "https://api.example.com/x")
