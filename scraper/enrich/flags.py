import re

from scraper.models import ParsedLocation, Pay
from scraper.text import sentence_at

_TITLE_GRAD = re.compile(r"\b(?:ph\.?\s?d|master['’]?s|msc)\b|\bm\.s\.", re.I)
_TITLE_EARLY = re.compile(
    r"(?-i:\bSTEP\b)|\b(?:first|second)[- ]year\b|\bfreshman\b|\bsophomore\b", re.I
)
_GRAD_YEAR = re.compile(r"\bgraduat\w*[^.\n]{0,40}?\b(20\d\d)\b", re.I)
_YEAR = re.compile(r"\b20\d\d\b")

TEXT_FLAGS: list[tuple[str, re.Pattern[str]]] = [
    (
        "grad_students_only",
        re.compile(
            r"(?:must|required\s+to)\s+be\s+(?:currently\s+)?(?:pursuing|enrolled\s+in)\s+an?\s+"
            r"(?:ph\.?\s?d|master['’]?s|graduate)",
            re.I,
        ),
    ),
    (
        "early_years_only",
        re.compile(
            r"\b(?:first|second|1st|2nd)[- ]year\s+(?:and\s+(?:first|second|1st|2nd)[- ]year\s+)?"
            r"(?:undergraduate\s+)?students?\b|\bfreshm[ae]n\b|\bsophomores?\b",
            re.I,
        ),
    ),
    (
        "eligibility_restricted",
        re.compile(
            r"\b(?:open\s+only\s+to|exclusively\s+for|must\s+(?:self-)?identify\s+as|"
            r"(?:program|internship)\s+(?:is\s+)?(?:designed|intended)\s+(?:specifically\s+)?for)\b",
            re.I,
        ),
    ),
    (
        "relocation",
        re.compile(
            r"\brelocation\s+(?:assistance|support|stipend|package|bonus|benefits?)"
            r"|\bhousing\s+(?:stipend|provided|assistance|support)",
            re.I,
        ),
    ),
]


def detect_flags(
    title: str, text: str, pay: Pay | None, location: ParsedLocation
) -> dict[str, str]:
    """Flag name -> evidence ("" when the flag needs no evidence)."""
    flags: dict[str, str] = {}
    if pay is not None:
        flags["pay_listed"] = pay.raw
    if location.work_mode in ("remote", "hybrid"):
        flags[location.work_mode] = ""
    if _TITLE_GRAD.search(title):
        flags["grad_students_only"] = title
    if _TITLE_EARLY.search(title):
        flags["early_years_only"] = title
    for name, pattern in TEXT_FLAGS:
        if name not in flags and (m := pattern.search(text)):
            flags[name] = sentence_at(text, m.start())
    if m := _GRAD_YEAR.search(text):
        sentence = sentence_at(text, m.start())
        for year in sorted(set(_YEAR.findall(sentence))):
            flags[f"grad_year:{year}"] = sentence
    return flags
