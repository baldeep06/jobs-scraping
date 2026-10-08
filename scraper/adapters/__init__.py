from scraper.adapters import (
    amazon,
    apple,
    ashby,
    google,
    greenhouse,
    lever,
    microsoft,
    smartrecruiters,
    workable,
    workday,
)
from scraper.adapters.base import Adapter

ADAPTERS: dict[str, Adapter] = {
    "google": google.fetch,
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
