import re

from scraper.models import Pay, PayRange

_HOURS = {"hour": 1.0, "week": 40.0, "month": 173.3, "year": 2080.0}
_PLAUSIBLE = {
    "hour": (10, 500),
    "week": (300, 10_000),
    "month": (1_000, 20_000),
    "year": (10_000, 1_000_000),
}

_NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?"
_CUR = r"CA\$|C\$|US\$|\$"
_PAY_RE = re.compile(
    rf"(?P<cur>{_CUR})\s?(?P<a>{_NUM})\s?(?P<ak>[kK]\b)?(?:\s*(?:USD|CAD))?"
    rf"(?:\s*(?:-|–|—|to)\s*(?:{_CUR})?\s?(?P<b>{_NUM})\s?(?P<bk>[kK]\b)?)?"
)
_NOT_PAY_SUFFIX = re.compile(r"^\s*(?:m|mm|b|bn|million|billion)\b", re.I)
_PERIODS = [
    ("hour", re.compile(r"/\s*h(?:ou)?r\b|per\s+hour|hourly|an\s+hour", re.I)),
    (
        "year",
        re.compile(r"/\s*y(?:ea)?r\b|per\s+(?:year|annum)|annual(?:ly)?|a\s+year|salary", re.I),
    ),
    ("month", re.compile(r"/\s*mo(?:nth)?\b|per\s+month|monthly|a\s+month", re.I)),
    ("week", re.compile(r"/\s*w(?:ee)?k\b|per\s+week|weekly|a\s+week", re.I)),
]
_PAY_WORD = re.compile(r"\b(?:pay|salary|compensation|wages?|rate|range)\b", re.I)


def hourly(value: float, period: str) -> float:
    return round(value / _HOURS[period], 2)


def _default_currency(country: str) -> str:
    return "CAD" if country == "CA" else "USD"


def _num(s: str, k: str | None) -> float:
    v = float(s.replace(",", ""))
    return v * 1000 if k else v


def _find_period(s: str) -> tuple[str, re.Match[str]] | None:
    for period, pattern in _PERIODS:
        if m := pattern.search(s):
            return period, m
    return None


def _from_structured(s: PayRange, country: str) -> Pay | None:
    lo = s.min if s.min is not None else s.max
    hi = s.max if s.max is not None else s.min
    if lo is None or hi is None or s.period is None:
        return None
    cur = (s.currency or _default_currency(country)).upper()
    return Pay(
        min=lo,
        max=hi,
        currency=cur,
        period=s.period,
        hourly_min=hourly(lo, s.period),
        hourly_max=hourly(hi, s.period),
        raw=f"{cur} {lo:g}–{hi:g} per {s.period}",
    )


def parse_pay(text: str, structured: PayRange | None, country: str) -> Pay | None:
    if structured is not None and (pay := _from_structured(structured, country)):
        return pay
    for m in _PAY_RE.finditer(text):
        tail = text[m.end() : m.end() + 40]
        if _NOT_PAY_SUFFIX.match(tail):
            continue
        lo = _num(m.group("a"), m.group("ak"))
        hi = _num(m.group("b"), m.group("bk") or m.group("ak")) if m.group("b") else lo
        if lo > hi:
            lo, hi = hi, lo

        raw_end = m.end()
        found = _find_period(tail)
        if found:
            period, pm = found
            raw_end = m.end() + pm.end()
        else:
            head = text[max(0, m.start() - 60) : m.start()]
            found = _find_period(head)
            if found:
                period = found[0]
            else:
                line_start = text.rfind("\n", 0, m.start()) + 1
                if not _PAY_WORD.search(text[line_start : m.end() + 40]):
                    continue
                if hi < 200:
                    period = "hour"
                elif lo > 10_000:
                    period = "year"
                else:
                    continue
        if period == "year" and hi < 1000:
            period = "hour"

        low_ok, high_ok = _PLAUSIBLE[period]
        if not (low_ok <= lo and hi <= high_ok):
            continue

        cur_sym = m.group("cur")
        window = text[m.start() : m.end() + 12]
        if cur_sym in ("CA$", "C$") or "CAD" in window:
            currency = "CAD"
        elif cur_sym == "US$" or "USD" in window:
            currency = "USD"
        else:
            currency = _default_currency(country)
        return Pay(
            min=lo,
            max=hi,
            currency=currency,
            period=period,
            hourly_min=hourly(lo, period),
            hourly_max=hourly(hi, period),
            raw=text[m.start() : raw_end].strip(),
        )
    return None
