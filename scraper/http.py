import asyncio
import random
from typing import Any
from urllib.parse import urlsplit

import httpx

USER_AGENT = "intern-job-scraper (+https://github.com/baldeep06/jobs-scraping)"
TIMEOUT = httpx.Timeout(15.0)
MAX_RETRIES = 3
PER_HOST_LIMIT = 5
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


class FetchError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class Fetcher:
    """Shared HTTP client: per-host concurrency cap, retries with exponential backoff + jitter."""

    def __init__(self, client: httpx.AsyncClient | None = None, base_delay: float = 1.0):
        self._client = client or httpx.AsyncClient(
            timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=True
        )
        self._base_delay = base_delay
        self._limits: dict[str, asyncio.Semaphore] = {}

    async def __aenter__(self) -> "Fetcher":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._client.aclose()

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        host = urlsplit(url).hostname or ""
        limit = self._limits.setdefault(host, asyncio.Semaphore(PER_HOST_LIMIT))
        last: FetchError | None = None
        for attempt in range(MAX_RETRIES + 1):
            if attempt:
                await asyncio.sleep(self._base_delay * 2 ** (attempt - 1) * (1 + random.random()))
            try:
                async with limit:
                    resp = await self._client.request(method, url, **kwargs)
            except httpx.TransportError as e:
                last = FetchError(f"{type(e).__name__}: {e}")
                continue
            if resp.status_code in RETRY_STATUSES:
                last = FetchError(f"HTTP {resp.status_code}", resp.status_code)
                continue
            if resp.status_code >= 400:
                raise FetchError(f"HTTP {resp.status_code}", resp.status_code)
            return resp
        assert last is not None
        raise last

    async def response_headers(self, method: str, url: str, **kwargs: Any) -> httpx.Headers:
        """Response headers only (some endpoints, like a CSRF token, answer with an empty body)."""
        return (await self._request(method, url, **kwargs)).headers

    async def json(self, method: str, url: str, **kwargs: Any) -> Any:
        resp = await self._request(method, url, **kwargs)
        try:
            return resp.json()
        except ValueError as e:
            raise FetchError(f"invalid JSON: {e}") from e

    async def text(self, method: str, url: str, **kwargs: Any) -> str:
        return (await self._request(method, url, **kwargs)).text
