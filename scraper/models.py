from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Country = Literal["CA", "US", "BOTH", "UNKNOWN"]
WorkMode = Literal["onsite", "hybrid", "remote", "unknown"]
PayPeriod = Literal["hour", "year", "month", "week"]
VisaStatus = Literal["open", "blocked", "unknown"]


class Company(BaseModel):
    id: int
    name: str
    ats: str
    slug: str
    job_ids_hash: str | None = None
    workday_host: str | None = None
    workday_site: str | None = None
    # Only for sites that need one request per posting (Meta): ids of open internships we
    # already hold, and ids of pages we opened and rejected. Filled by the CLI before polling.
    known_ids: set[str] = set()
    checked_ids: set[str] = set()


class PayRange(BaseModel):
    """Structured pay as provided by an ATS (any field may be missing)."""

    min: float | None = None
    max: float | None = None
    currency: str | None = None
    period: PayPeriod | None = None


class Pay(BaseModel):
    """Normalized pay attached to an enriched job."""

    min: float
    max: float
    currency: str
    period: PayPeriod
    hourly_min: float
    hourly_max: float
    raw: str


class RawJob(BaseModel):
    source: str
    source_job_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    url: str = Field(min_length=1)
    location_raw: str = ""
    description_text: str = ""
    source_posted_at: datetime | None = None
    pay_structured: PayRange | None = None
    work_mode_hint: WorkMode | None = None
    # "CA", "US", any other ISO code, or "OTHER" (= somewhere outside CA/US)
    country_hint: str | None = None
    employment_type_hint: str | None = None

    @field_validator("title")
    @classmethod
    def _collapse_title(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("empty title")
        return v

    @field_validator("source_posted_at")
    @classmethod
    def _utc(cls, v: datetime | None) -> datetime | None:
        if v is not None and v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v


class Location(BaseModel):
    city: str | None = None
    region: str | None = None  # 2-letter state/province code
    country: Literal["CA", "US"]

    def key(self) -> str:
        return f"{(self.city or '').lower()}|{self.region or ''}|{self.country}"


class ParsedLocation(BaseModel):
    locations: list[Location] = []
    country: Country
    work_mode: WorkMode = "unknown"
    location_unclear: bool = False
    foreign_only: bool = False


class EnrichedJob(BaseModel):
    raw: RawJob
    company_id: int
    normalized_title: str
    category: str
    term: str | None
    duration_months: int | None
    location: ParsedLocation
    pay: Pay | None
    visa_signals: list[str]
    visa_status: VisaStatus
    flags: list[str]
    evidence: dict[str, str]
    fingerprint: str
    title_key: str | None = None
    desc_hash: str | None = None


@dataclass
class FetchResult:
    jobs: list[RawJob]
    invalid: int = 0
    # A search-based ATS answered successfully with zero hits (so the last job may be gone).
    confirmed_empty: bool = False
    # Listed, but its detail fetch failed: not missing, just not readable this time.
    pending_ids: set[str] = field(default_factory=set)
    rejected_ids: set[str] = field(default_factory=set)  # opened and not wanted: remember
    forgotten_ids: set[str] = field(default_factory=set)  # remembered ids that left the listing


@dataclass
class CompanyOutcome:
    """Result of polling one company, ready for db.ingest()."""

    company: Company
    ok: bool
    jobs: list[EnrichedJob] = field(default_factory=list)
    seen_ids: set[str] = field(default_factory=set)
    ids_hash: str | None = None
    unchanged: bool = False
    invalid: int = 0
    confirmed_empty: bool = False
    # Listed but not read this time: seen (so not missing) and neither re-enriched nor closed.
    pending_ids: set[str] = field(default_factory=set)
    rejected_ids: set[str] = field(default_factory=set)
    forgotten_ids: set[str] = field(default_factory=set)
    error: str | None = None
    status: int | None = None
