import re

_SEASON = re.compile(
    r"\b(summer|fall|autumn|winter|spring)\s*(?:term\s*)?[,'’]?\s*(20\d\d)\b", re.I
)
_MONTHS = r"\b(\d{1,2})(?:\s*(?:-|–|to|/)\s*(\d{1,2}))?[- ]months?\b"
_MONTHS_TITLE = re.compile(_MONTHS, re.I)
# In descriptions, only count durations attached to the role ("6 months of experience" doesn't).
_MONTHS_DESC = re.compile(
    _MONTHS + r"\s+(?:co-?op|intern(?:ship)?|work term|placement|term|contract)", re.I
)
_PEY = re.compile(r"(?-i:\bPEY\b)|professional experience year", re.I)


def parse_term(title: str, text: str) -> tuple[str | None, int | None]:
    term: str | None = None
    if season := (_SEASON.search(title) or _SEASON.search(text)):
        name = season.group(1).lower()
        term = f"{'Fall' if name == 'autumn' else name.title()} {season.group(2)}"

    duration: int | None = None
    label: str | None = None
    months = _MONTHS_TITLE.search(title) or _MONTHS_DESC.search(text)
    if months and 2 <= int(months.group(1)) <= 18:
        lo, hi = int(months.group(1)), months.group(2)
        duration = lo
        label = f"{lo}–{hi}-month" if hi else f"{lo}-month"
    elif _PEY.search(title) or _PEY.search(text):
        duration, label = 12, "PEY"

    if label:
        term = f"{term} · {label}" if term else label
    return term, duration
