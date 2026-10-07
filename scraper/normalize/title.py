import re

_MONTHS = re.compile(r"\b\d{1,2}\s*(?:-|–|to)?\s*(?:\d{1,2}\s*)?[- ]?months?\b", re.I)
_YEAR = re.compile(r"\b20\d\d\b")
_SEASON = re.compile(r"\b(?:summer|fall|autumn|winter|spring)\b", re.I)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize_title(title: str) -> str:
    """Lowercase title without term/year/duration words or punctuation (for fingerprints)."""
    t = title.lower()
    t = _MONTHS.sub(" ", t)
    t = _YEAR.sub(" ", t)
    t = _SEASON.sub(" ", t)
    t = _NON_ALNUM.sub(" ", t)
    return " ".join(t.split())
