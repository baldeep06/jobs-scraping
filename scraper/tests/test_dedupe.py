from datetime import UTC, datetime, timedelta

from scraper.dedupe import (
    Decision,
    ExistingSource,
    FingerprintMatch,
    OpenJob,
    classify,
    fingerprint,
    ids_hash,
    plan_closures,
)
from scraper.models import Location
from scraper.normalize.title import normalize_title

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
TOR = Location(city="Toronto", region="ON", country="CA")
NYC = Location(city="New York", region="NY", country="US")


def test_normalize_title_strips_terms_years_punctuation():
    a = normalize_title("Software Engineer Intern (Summer 2027)")
    b = normalize_title("Software Engineer Intern - Summer 2028")
    assert a == b == "software engineer intern"
    assert normalize_title("Co-op, 4-Month Software Developer") == "co op software developer"
    assert normalize_title("Data Intern (12-16 months)") == "data intern"


def test_fingerprint_ignores_location_order_and_differs_by_company():
    assert fingerprint(1, "swe intern", [TOR, NYC]) == fingerprint(1, "swe intern", [NYC, TOR])
    assert fingerprint(1, "swe intern", [TOR]) != fingerprint(2, "swe intern", [TOR])


def test_ids_hash_order_independent():
    assert ids_hash(["b", "a"]) == ids_hash({"a", "b"})


def existing(status="open", first_seen_days=30, posted=None):
    return ExistingSource("job-1", status, NOW - timedelta(days=first_seen_days), posted)


def test_new_job_is_fresh_insert():
    assert classify(None, None, None, NOW) == Decision("insert", freshness="fresh")


def test_closed_existing_source_reopens():
    assert classify(existing("closed"), None, None, NOW) == Decision(
        "reopen", job_id="job-1", freshness="reopened"
    )


def test_posted_date_bump_on_old_job_is_refresh():
    old = NOW - timedelta(days=40)
    d = classify(existing(posted=old), NOW - timedelta(days=1), None, NOW)
    assert d == Decision("refresh", job_id="job-1", freshness="refreshed")


def test_posted_date_bump_on_young_job_is_touch():
    old = NOW - timedelta(days=3)
    d = classify(existing(first_seen_days=2, posted=old), NOW, None, NOW)
    assert d == Decision("touch", job_id="job-1")


def test_same_posted_date_is_touch():
    p = NOW - timedelta(days=40)
    assert classify(existing(posted=p), p, None, NOW) == Decision("touch", job_id="job-1")


def test_new_id_matching_open_fingerprint_attaches():
    fp = FingerprintMatch("job-9", "open", NOW, 0)
    assert classify(None, None, fp, NOW) == Decision("attach", job_id="job-9")


def test_new_id_matching_recent_closed_fingerprint_is_repost():
    fp = FingerprintMatch("job-9", "closed", NOW - timedelta(days=30), 1)
    assert classify(None, None, fp, NOW) == Decision(
        "insert", freshness="repost", repost_of="job-9", repost_count=2
    )


def test_new_id_matching_old_fingerprint_is_recurring():
    fp = FingerprintMatch("job-9", "closed", NOW - timedelta(days=200), 0)
    assert classify(None, None, fp, NOW) == Decision("insert", freshness="recurring")


def test_plan_closures():
    jobs = [
        OpenJob("seen", 1, frozenset({"a"})),
        OpenJob("first-miss", 0, frozenset({"b"})),
        OpenJob("second-miss", 1, frozenset({"c"})),
        OpenJob("one-of-two-ids-seen", 0, frozenset({"d", "e"})),
    ]
    plan = plan_closures(jobs, {"a", "e"})
    assert plan.reset == ["seen"]
    assert plan.increment == ["first-miss"]
    assert plan.close == ["second-miss"]
