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


async def test_text_returns_the_body_and_retries_like_json():
    calls = []

    def handler(request):
        calls.append(1)
        return (
            httpx.Response(503) if len(calls) == 1 else httpx.Response(200, text="<html>ok</html>")
        )

    async with fetcher_for(handler) as f:
        assert await f.text("GET", "https://x.test/p") == "<html>ok</html>"
    assert len(calls) == 2


async def test_json_with_headers_returns_both():
    def handler(request):
        return httpx.Response(200, json={"a": 1}, headers={"x-token": "t0"})

    async with fetcher_for(handler) as f:
        data, headers = await f.json_with_headers("GET", "https://x.test/j")
    assert data == {"a": 1} and headers["x-token"] == "t0"


async def test_text_raises_on_client_errors():
    async with fetcher_for(lambda r: httpx.Response(404)) as f:
        with pytest.raises(FetchError) as exc:
            await f.text("GET", "https://x.test/missing")
    assert exc.value.status == 404
