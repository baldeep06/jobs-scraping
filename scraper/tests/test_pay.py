import pytest

from scraper.models import PayRange
from scraper.normalize.pay import parse_pay


def p(text, country="US", structured=None):
    return parse_pay(text, structured, country)


def test_hourly_range_usd():
    pay = p("The hourly rate for this role is $28 - $35 per hour.")
    assert (pay.min, pay.max, pay.currency, pay.period) == (28, 35, "USD", "hour")
    assert (pay.hourly_min, pay.hourly_max) == (28, 35)
    assert pay.raw == "$28 - $35 per hour"


def test_annual_cad_with_hourly_equivalent():
    pay = p("Compensation: CA$70,000–CA$85,000 annually.", country="CA")
    assert (pay.min, pay.max, pay.currency, pay.period) == (70000, 85000, "CAD", "year")
    assert (pay.hourly_min, pay.hourly_max) == (33.65, 40.87)


def test_k_suffix_with_period_from_preceding_text():
    pay = p("Salary range: $80k-$100k")
    assert (pay.min, pay.max, pay.period) == (80000, 100000, "year")


def test_single_value_per_hr():
    pay = p("Pay: $45/hr")
    assert (pay.min, pay.max, pay.period) == (45, 45, "hour")


def test_canada_job_defaults_to_cad():
    assert p("Pay: $30 – $40 hourly", country="CA").currency == "CAD"


def test_monthly():
    pay = p("The base salary range is $8,000 - $9,000 per month.")
    assert (pay.period, pay.hourly_min, pay.hourly_max) == ("month", 46.16, 51.93)


def test_no_period_small_values_with_pay_word_are_hourly():
    assert p("Pay range: $25 - $30").period == "hour"


def test_decimal_values():
    assert p("$28.50 per hour").min == 28.5


@pytest.mark.parametrize(
    "text",
    [
        "We raised a $50M Series B last year.",
        "You'll receive a $5,000 relocation stipend.",
        "Enjoy a $100 monthly learning budget",
        "No pay listed here.",
    ],
)
def test_non_pay_dollar_amounts_ignored(text):
    assert p(text) is None


def test_structured_pay_preferred():
    s = PayRange(min=32, max=40, currency="CAD", period="hour")
    pay = p("Pay is $99 per hour", country="CA", structured=s)
    assert (pay.min, pay.max, pay.currency, pay.raw) == (32, 40, "CAD", "CAD 32–40 per hour")


def test_structured_missing_currency_uses_country_default():
    s = PayRange(min=80000, max=None, currency=None, period="year")
    pay = p("", country="CA", structured=s)
    assert (pay.min, pay.max, pay.currency) == (80000, 80000, "CAD")
