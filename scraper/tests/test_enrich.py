from scraper.enrich import enrich
from scraper.models import PayRange, RawJob


def raw(**kw):
    base = dict(
        source="greenhouse",
        source_job_id="1",
        title="Software Engineer Intern",
        url="https://x/1",
        location_raw="Toronto, ON",
    )
    return RawJob(**(base | kw))


def test_canadian_intern_with_pay_and_term():
    job = enrich(
        raw(
            title="Software Engineer Intern (Summer 2027)",
            description_text="Join our team.\nThe hourly rate is CA$30 - CA$38 per hour.",
        ),
        company_id=7,
    )
    assert job is not None
    assert (job.category, job.location.country, job.term) == ("SWE", "CA", "Summer 2027")
    assert (job.pay.min, job.pay.max, job.pay.currency) == (30, 38, "CAD")
    assert job.visa_status == "open"
    assert "pay_listed" in job.flags
    assert job.normalized_title == "software engineer intern"
    assert job.company_id == 7 and len(job.fingerprint) == 40


def test_us_intern_without_sponsorship_is_blocked_with_evidence():
    job = enrich(
        raw(
            title="Data Science Intern",
            location_raw="New York, NY",
            description_text="We will not sponsor visas for this role.",
        ),
        company_id=1,
    )
    assert job.visa_status == "blocked"
    assert job.visa_signals == ["no_sponsorship"]
    assert job.evidence["no_sponsorship"] == "We will not sponsor visas for this role."


def test_title_counts_for_visa_signals():
    job = enrich(raw(title="Software Intern (US Citizens Only)", location_raw="Austin, TX"), 1)
    assert job.visa_status == "blocked"


def test_non_intern_and_non_tech_dropped():
    assert enrich(raw(title="Senior Account Executive"), 1) is None
    assert enrich(raw(title="Marketing Intern"), 1) is None


def test_foreign_only_dropped():
    assert enrich(raw(location_raw="London", country_hint="OTHER"), 1) is None
    assert enrich(raw(location_raw="Bangalore, India"), 1) is None


def test_structured_pay_and_hints_flow_through():
    job = enrich(
        raw(
            location_raw="Remote",
            country_hint="US",
            work_mode_hint="remote",
            pay_structured=PayRange(min=50, max=60, currency="USD", period="hour"),
        ),
        1,
    )
    assert job.location.country == "US" and "remote" in job.flags
    assert job.pay.hourly_max == 60


def test_default_country_used_for_bare_remote():
    job = enrich(raw(location_raw="Remote"), 1, default_country="CA")
    assert job.location.country == "CA" and not job.location.location_unclear
