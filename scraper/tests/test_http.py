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
            *(f.json("GET", f"https://t{i}.boards.examplevendor.com/x") for i in range(8))
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


async def test_a_vendor_that_keeps_blocking_us_is_left_alone_for_the_rest_of_the_pass():
    from scraper import http

    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, text="<html>Access denied</html>")

    async with fetcher_for(handler) as f:
        for i in range(http.BREAKER_TRIPS + 5):
            with pytest.raises(FetchError):
                await f.json("POST", f"https://t{i}.wd5.myworkdayjobs.com/x")
        assert f.tripped == {"myworkdayjobs.com"}
    assert len(calls) == http.BREAKER_TRIPS  # nothing sent once it tripped


@pytest.mark.parametrize("status", [403, 429])
async def test_403_and_429_count_as_blocked(status):
    from scraper import http

    async with fetcher_for(lambda r: httpx.Response(status)) as f:
        for i in range(http.BREAKER_TRIPS):
            with pytest.raises(FetchError):
                await f.json("GET", f"https://api{i}.workable.com/x")
        assert f.tripped == {"workable.com"}


async def test_a_404_or_one_bad_page_does_not_trip_the_breaker():
    async with fetcher_for(lambda r: httpx.Response(404)) as f:
        for i in range(10):
            with pytest.raises(FetchError):
                await f.json("GET", f"https://x{i}.example.com/x")
        assert f.tripped == set()


async def test_non_json_errors_say_what_came_back():
    async with fetcher_for(
        lambda r: httpx.Response(200, text="<!DOCTYPE html><title>Hi</title>")
    ) as f:
        with pytest.raises(FetchError, match="<!DOCTYPE html>"):
            await f.json("GET", "https://api.example.com/x")


async def test_workday_gets_a_smaller_vendor_cap():
    from scraper import http

    assert http.vendor_limit("myworkdayjobs.com") == 8
    assert http.vendor_limit("greenhouse.io") == http.VENDOR_LIMIT


async def test_a_few_blocked_boards_among_many_good_ones_do_not_trip_the_vendor():
    from scraper import http

    def handler(request):
        bad = request.url.host.startswith("bad")
        return httpx.Response(403) if bad else httpx.Response(200, json={})

    async with fetcher_for(handler) as f:
        for i in range(40):
            await f.json("GET", f"https://good{i}.greenhouse.io/x")
        for i in range(http.BREAKER_TRIPS + 2):
            with pytest.raises(FetchError):
                await f.json("GET", f"https://bad{i}.greenhouse.io/x")
        assert f.tripped == set()
