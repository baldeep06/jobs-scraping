import re
from collections.abc import Iterable
from dataclasses import dataclass

from scraper.text import sentence_at

_US = r"(?:U\.?S\.?|United\s+States)"

VISA_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "no_sponsorship",
        re.compile(
            r"\b(?:will|do|does|can|are|is)\s*(?:not|n['’]t)\s+(?:be\s+)?(?:able\s+to\s+)?"
            r"(?:offer\s+|provide\s+)?(?:visa\s+|immigration\s+)?sponsor"
            r"|\b(?:won['’]t|can['’]t)\s+(?:be\s+able\s+to\s+)?(?:offer\s+|provide\s+)?"
            r"(?:visa\s+|immigration\s+)?sponsor"
            r"|\bunable\s+to\s+(?:offer\s+|provide\s+|support\s+)?(?:visa\s+|immigration\s+)?sponsor"
            r"|\bnot\s+(?:able|eligible)\s+to\s+(?:provide|offer|receive)\s+"
            r"(?:visa\s+|immigration\s+)?sponsorship"
            r"|\bwithout\s+(?:the\s+need\s+for\s+)?(?:current\s+or\s+future\s+|now\s+or\s+in\s+"
            r"the\s+future\s+)?(?:visa\s+|employment\s+|immigration\s+|work\s+)?sponsorship"
            r"|\bno\s+(?:visa\s+|immigration\s+)?sponsorship"
            r"|\bsponsorship\s+(?:is\s+|will\s+)?not\s+(?:be\s+)?(?:available|provided|offered)"
            r"|\bsponsorship[^.]{0,60}\bnot\s+eligible|\bnot\s+eligible[^.]{0,60}\bsponsorship",
            re.I,
        ),
    ),
    (
        "us_citizen_only",
        re.compile(
            rf"\bmust\s+be\s+(?:a\s+)?{_US}\s+citizens?"
            rf"|\b{_US}\s+citizenship\s+(?:is\s+)?required|\brequires?\s+{_US}\s+citizenship"
            rf"|\b{_US}\s+citizens?\s+(?:or\s+green\s+card\s+holders\s+)?only"
            rf"|\b{_US}\s+persons?\b|\bgreen\s+card\b"
            rf"|\b{_US}\s+(?:lawful\s+)?permanent\s+residen"
            r"|(?-i:\bITAR\b)|\bexport\s+control",
            re.I,
        ),
    ),
    (
        "clearance",
        re.compile(
            r"\bsecurity\s+clearance|\btop\s+secret\b|(?-i:\bTS/SCI\b)"
            r"|\bsecret\s+(?:level\s+)?clearance|\breliability\s+status\b",
            re.I,
        ),
    ),
    (
        "us_school_required",
        re.compile(
            rf"\benrolled\s+(?:at|in)\s+(?:an?\s+)?(?:accredited\s+)?{_US}(?:[-\s]based)?\s+"
            r"(?:college|university|institution|school)"
            r"|(?-i:\b(?:CPT|OPT)\b)",
            re.I,
        ),
    ),
    (
        "sponsors",
        re.compile(
            r"\b(?:visa\s+|immigration\s+)?sponsorship\s+(?:is\s+)?(?:available|offered|provided)\b"
            r"|\bwe\s+(?:will|can|do)\s+sponsor"
            r"|(?-i:\bJ-?1\b)"
            r"|\binternational\s+(?:students|candidates|applicants)\s+(?:are\s+)?"
            r"(?:welcome|encouraged)"
            r"|\bopen\s+to\s+(?:candidates|applicants)\s+(?:who\s+)?(?:require|requiring|need|"
            r"needing)\s+(?:visa\s+)?sponsorship",
            re.I,
        ),
    ),
    (
        "canadian_coop_required",
        re.compile(
            r"\bco-?op\s+(?:program|students?|term)[^.]{0,60}\bcanad"
            r"|\benrolled[^.]{0,60}\bcanadian\s+(?:post-?secondary\s+)?"
            r"(?:university|institution|college|school)"
            r"|\bcanad\w*[^.]{0,40}\bco-?op\s+program",
            re.I,
        ),
    ),
]

BLOCKING_SIGNALS = frozenset(
    {"no_sponsorship", "us_citizen_only", "clearance", "us_school_required"}
)


@dataclass(frozen=True)
class Profile:
    authorized_countries: frozenset[str]


OWNER_PROFILE = Profile(authorized_countries=frozenset({"CA"}))


def detect_visa_signals(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for signal, pattern in VISA_PATTERNS:
        if m := pattern.search(text):
            found[signal] = sentence_at(text, m.start())
    return found


def visa_status(signals: Iterable[str], country: str, profile: Profile = OWNER_PROFILE) -> str:
    """Status for `profile`. UNKNOWN country is judged like a country the profile needs a visa for."""
    if country in profile.authorized_countries:
        return "open"
    if country == "BOTH" and profile.authorized_countries & {"CA", "US"}:
        return "open"
    s = set(signals)
    if s & BLOCKING_SIGNALS:
        return "blocked"
    if "sponsors" in s:
        return "open"
    return "unknown"
