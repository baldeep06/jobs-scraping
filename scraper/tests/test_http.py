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


async def test_response_headers_works_for_an_empty_body():
    def handler(request):
        return httpx.Response(200, content=b"", headers={"x-token": "t0"})

    async with fetcher_for(handler) as f:
        headers = await f.response_headers("GET", "https://x.test/j")
    assert headers["x-token"] == "t0"


async def test_text_raises_on_client_errors():
    async with fetcher_for(lambda r: httpx.Response(404)) as f:
        with pytest.raises(FetchError) as exc:
            await f.text("GET", "https://x.test/missing")
    assert exc.value.status == 404


async def test_requests_to_one_vendor_are_capped_across_its_subdomains(monkeypatch):
    import asyncio

    from scraper import http

    monkeypatch.setattr(http, "VENDOR_LIMIT", 2)
    active = peak = 0

    async def handler(request):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return httpx.Response(200, json={})

    async with fetcher_for(handler) as f:
        await asyncio.gather(
            *(f.json("GET", f"https://t{i}.wd5.myworkdayjobs.com/x") for i in range(8))
        )
    assert peak == 2


def test_vendor_is_the_registrable_domain():
    from scraper.http import vendor

    assert vendor("nvidia.wd5.myworkdayjobs.com") == "myworkdayjobs.com"
    assert vendor("boards-api.greenhouse.io") == "greenhouse.io"
    assert vendor("localhost") == "localhost"


async def test_retry_after_is_honoured(monkeypatch):
    from scraper import http

    waits = []

    async def fake_sleep(seconds):
        waits.append(seconds)

    monkeypatch.setattr(http.asyncio, "sleep", fake_sleep)
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "7"})
        return httpx.Response(200, json={"ok": True})

    async with fetcher_for(handler) as f:
        assert await f.json("GET", "https://api.example.com/x") == {"ok": True}
    assert 7 in waits


async def test_a_long_retry_after_gives_up_at_once_instead_of_stalling_the_pass():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "3600"})

    async with fetcher_for(handler) as f:
        with pytest.raises(FetchError) as e:
            await f.json("GET", "https://api.example.com/x")
    assert e.value.status == 429 and len(calls) == 1
