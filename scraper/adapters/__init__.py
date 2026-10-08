from scraper.adapters import (
    amazon,
    apple,
    ashby,
    eightfold,
    google,
    greenhouse,
    lever,
    meta,
    microsoft,
    oraclehcm,
    smartrecruiters,
    workable,
    workday,
)
from scraper.adapters.base import Adapter

ADAPTERS: dict[str, Adapter] = {
    "google": google.fetch,
    "greenhouse": greenhouse.fetch,
    "lever": lever.fetch,
    "meta": meta.fetch,
    "microsoft": microsoft.fetch,
    "amazon": amazon.fetch,
    "apple": apple.fetch,
    "ashby": ashby.fetch,
    "eightfold": eightfold.fetch,
    "eightfold_v2": eightfold.fetch_v2,
    "oraclehcm": oraclehcm.fetch,
    "smartrecruiters": smartrecruiters.fetch,
    "workable": workable.fetch,
    "workday": workday.fetch,
}
