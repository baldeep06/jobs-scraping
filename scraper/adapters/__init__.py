from scraper.adapters import greenhouse, lever
from scraper.adapters.base import Adapter

ADAPTERS: dict[str, Adapter] = {
    "greenhouse": greenhouse.fetch,
    "lever": lever.fetch,
}
