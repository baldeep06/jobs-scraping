from scraper.dedupe import fingerprint
from scraper.enrich.category import categorize, is_intern_title
from scraper.enrich.flags import detect_flags
from scraper.enrich.visa import detect_visa_signals, visa_status
from scraper.models import EnrichedJob, RawJob
from scraper.normalize.location import parse_location
from scraper.normalize.pay import parse_pay
from scraper.normalize.term import parse_term
from scraper.normalize.title import normalize_title
from scraper.signals import desc_hash, title_key


def enrich(raw: RawJob, company_id: int, default_country: str | None = None) -> EnrichedJob | None:
    """Turn a RawJob into an EnrichedJob, or None if it isn't a CA/US tech internship."""
    if not is_intern_title(raw.title, raw.employment_type_hint):
        return None
    category = categorize(raw.title)
    if category is None:
        return None
    location = parse_location(
        raw.location_raw, raw.country_hint, raw.work_mode_hint, default_country
    )
    if location.foreign_only:
        return None

    text = raw.description_text
    pay = parse_pay(text, raw.pay_structured, location.country)
    term, duration = parse_term(raw.title, text)
    signals = detect_visa_signals(f"{raw.title}\n{text}")
    flags = detect_flags(raw.title, text, pay, location)
    normalized = normalize_title(raw.title)
    return EnrichedJob(
        raw=raw,
        company_id=company_id,
        normalized_title=normalized,
        category=category,
        term=term,
        duration_months=duration,
        location=location,
        pay=pay,
        visa_signals=sorted(signals),
        visa_status=visa_status(signals, location.country),
        flags=sorted(flags),
        evidence={k: v for k, v in (signals | flags).items() if v},
        fingerprint=fingerprint(company_id, normalized, location.locations),
        title_key=title_key(normalized),
        desc_hash=desc_hash(text),
    )
