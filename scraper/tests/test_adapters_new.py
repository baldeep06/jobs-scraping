import json
from pathlib import Path

import httpx

from scraper.adapters.base import get_details, wanted
from scraper.http import Fetcher

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / name).read_text())


def make_fetcher(handler):
    return Fetcher(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), base_delay=0)


def test_wanted_needs_intern_and_tech():
    assert wanted("Software Engineer Intern")
    assert not wanted("International Sales Manager")
    assert not wanted("Marketing Intern")  # intern but no tech category
    assert not wanted("Senior Software Engineer")
    assert wanted("Software Engineer", "Intern")  # employment type counts


async def test_get_details_skips_failures():
    def handler(request):
        if request.url.path.endswith("/bad"):
            return httpx.Response(404)
        if request.url.path.endswith("/list"):
            return httpx.Response(200, json=[1])
        return httpx.Response(200, json={"ok": request.url.path})

    async with make_fetcher(handler) as f:
        got = await get_details(
            f, {"a": "https://x.test/a", "b": "https://x.test/bad", "c": "https://x.test/list"}
        )
    assert got == {"a": {"ok": "/a"}}
