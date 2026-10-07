from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from scraper.models import Location, RawJob


def make(**kw):
    base = dict(source="greenhouse", source_job_id="1", title="Intern", url="https://x/1")
    return RawJob(**(base | kw))


def test_title_whitespace_collapsed():
    assert make(title="  Software   Engineer\nIntern ").title == "Software Engineer Intern"


def test_blank_title_rejected():
    with pytest.raises(ValidationError):
        make(title="   ")


def test_empty_source_job_id_rejected():
    with pytest.raises(ValidationError):
        make(source_job_id="")


def test_naive_datetime_becomes_utc():
    job = make(source_posted_at=datetime(2026, 10, 1, 12, 0))
    assert job.source_posted_at == datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def test_iso_string_parsed():
    job = make(source_posted_at="2026-09-28T09:00:00-04:00")
    assert job.source_posted_at == datetime(2026, 9, 28, 13, 0, tzinfo=UTC)


def test_location_key():
    assert Location(city="Toronto", region="ON", country="CA").key() == "toronto|ON|CA"
    assert Location(country="US").key() == "||US"
