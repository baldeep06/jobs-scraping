from scraper.adapters import (
    amazon,
    apple,
    ashby,
    greenhouse,
    lever,
    microsoft,
    smartrecruiters,
    workable,
    workday,
)
from scraper.adapters.base import Adapter

ADAPTERS: dict[str, Adapter] = {
    "greenhouse": greenhouse.fetch,
    "lever": lever.fetch,
    "microsoft": microsoft.fetch,
    "amazon": amazon.fetch,
    "apple": apple.fetch,
    "ashby": ashby.fetch,
    "smartrecruiters": smartrecruiters.fetch,
    "workable": workable.fetch,
    "workday": workday.fetch,
}
