from scraper.adapters import ashby, greenhouse, lever
from scraper.adapters.base import Adapter

ADAPTERS: dict[str, Adapter] = {
    "greenhouse": greenhouse.fetch,
    "lever": lever.fetch,
    "ashby": ashby.fetch,
}
