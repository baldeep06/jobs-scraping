import re
import unicodedata

from scraper.models import Location, ParsedLocation
from scraper.normalize.geo import (
    CA_PROVINCES,
    FOREIGN_CITIES,
    FOREIGN_RE,
    KNOWN_CITIES,
    US_STATES,
)

_SPLIT = re.compile(r"\s*(?:;|\||\n|\s/\s|\sor\s|\s&\s)\s*", re.I)
_CITY_CODE = re.compile(r"^\s*(?P<city>[^,()]+?)\s*,\s*(?P<code>[A-Z]{2})\b")
_MODE_PREFIX = re.compile(r"^(?:remote|hybrid|on-?site)\s*[-–:]\s*", re.I)
_REMOTE = re.compile(r"\bremote\b|\bwork from home\b|\bwfh\b", re.I)
_HYBRID = re.compile(r"\bhybrid\b", re.I)
_MODE_WORDS = re.compile(r"\b(?:remote|hybrid|on-?site|work from home|wfh|anywhere)\b", re.I)
_CANADA = re.compile(r"\bcanada\b", re.I)
_USA = re.compile(r"\bunited states\b|\busa\b|(?<!\w)u\.s\.(?:a\.)?|(?-i:\bUS\b)", re.I)

_CA_NAMES = {name.lower(): code for code, name in CA_PROVINCES.items()} | {"québec": "QC"}
_US_NAMES = {name.lower(): code for code, name in US_STATES.items()}
_REGION_NAME = re.compile(
    r"\b("
    + "|".join(sorted(map(re.escape, _CA_NAMES | _US_NAMES), key=len, reverse=True))
    + r")\b",
    re.I,
)
_KNOWN_CITY = re.compile(
    r"\b(" + "|".join(sorted(map(re.escape, KNOWN_CITIES), key=len, reverse=True)) + r")\b", re.I
)


def _clean_city(city: str, explicit: bool = False) -> str | None:
    """`explicit`: the text sat right before a state/province code, so "New York" is a city."""
    city = _MODE_PREFIX.sub("", city).strip(" -–")
    if not city or _REMOTE.search(city) or _CANADA.search(city) or _USA.search(city):
        return None
    if not explicit and _REGION_NAME.fullmatch(city):
        return None
    return city


def _city_before(seg: str) -> str | None:
    return _clean_city(re.split(r"[,(]", seg, maxsplit=1)[0])


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _parse_segment(seg: str, country_hint: str | None = None) -> tuple[list[Location], bool]:
    """Returns (locations, is_foreign). No locations and not foreign means unclear."""
    if m := _CITY_CODE.match(seg):
        city, code = m.group("city"), m.group("code")
        key = _MODE_PREFIX.sub("", city).strip().lower()
        foreign_hint = country_hint not in (None, "CA", "US")
        if FOREIGN_CITIES.get(key) == code or (foreign_hint and code == country_hint):
            return [], True
        known = KNOWN_CITIES.get(key)
        if code == "CA" and ((known and known[1] == "CA") or country_hint == "CA"):
            region = known[0] if known else None
            return [Location(city=_clean_city(city, True), region=region, country="CA")], False
        if code in CA_PROVINCES:
            return [Location(city=_clean_city(city, True), region=code, country="CA")], False
        if code in US_STATES:
            return [Location(city=_clean_city(city, True), region=code, country="US")], False
        if code not in ("US", "CA"):
            return [], True  # an ISO country code that isn't a state or province

    parts = [p.strip() for p in seg.split(",") if p.strip()]
    if len(parts) > 1 and all(p.lower() in KNOWN_CITIES for p in parts):
        return [
            Location(city=p, region=KNOWN_CITIES[p.lower()][0], country=KNOWN_CITIES[p.lower()][1])
            for p in parts
        ], False

    if m := _REGION_NAME.search(seg):
        key = m.group(1).lower()
        if key in _CA_NAMES:
            return [Location(city=_city_before(seg), region=_CA_NAMES[key], country="CA")], False
        return [Location(city=_city_before(seg), region=_US_NAMES[key], country="US")], False

    if m := _KNOWN_CITY.search(seg):
        region, country = KNOWN_CITIES[m.group(1).lower()]
        return [Location(city=_clean_city(m.group(1)), region=region, country=country)], False

    in_ca, in_us = bool(_CANADA.search(seg)), bool(_USA.search(seg))
    if in_ca or in_us:
        return [Location(country=c) for c, hit in (("CA", in_ca), ("US", in_us)) if hit], False
    return [], bool(FOREIGN_RE.search(seg))


def _work_mode(raw: str, hint: str | None, has_city: bool) -> str:
    if hint:
        return hint
    if _HYBRID.search(raw):
        return "hybrid"
    if _REMOTE.search(raw):
        return "remote"
    return "onsite" if has_city else "unknown"


def parse_location(
    raw: str,
    country_hint: str | None = None,
    work_mode_hint: str | None = None,
    default_country: str | None = None,
) -> ParsedLocation:
    hint = (country_hint or "").upper() or None
    segments = [s for s in _SPLIT.split(_strip_accents(raw or "")) if s.strip()]
    found: dict[str, Location] = {}
    foreign: list[bool] = []
    named_unresolved = False  # a place name we couldn't place in CA/US or abroad
    for seg in segments:
        locs, is_foreign = _parse_segment(seg, hint)
        foreign.append(is_foreign)
        if not locs and not is_foreign and _MODE_WORDS.sub("", seg).strip(" ,-–()/"):
            named_unresolved = True
        for loc in locs:
            found.setdefault(loc.key(), loc)
    locations = list(found.values())
    mode = _work_mode(raw or "", work_mode_hint, any(loc.city for loc in locations))

    if not locations:
        if hint in ("CA", "US"):
            locations = [Location(country=hint)]
        elif hint or (foreign and all(foreign)):
            return ParsedLocation(country="UNKNOWN", work_mode=mode, foreign_only=True)
        elif default_country in ("CA", "US") and not named_unresolved:
            locations = [Location(country=default_country)]
        else:
            return ParsedLocation(country="UNKNOWN", work_mode=mode, location_unclear=True)

    countries = {loc.country for loc in locations}
    country = "BOTH" if countries == {"CA", "US"} else next(iter(countries))
    return ParsedLocation(locations=locations, country=country, work_mode=mode)
