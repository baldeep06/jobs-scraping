import pytest

from scraper.normalize.term import parse_term


@pytest.mark.parametrize(
    ("title", "text", "expected"),
    [
        ("Software Engineer Intern (Summer 2027)", "", ("Summer 2027", None)),
        ("Software Intern", "This is a Fall 2026 internship.", ("Fall 2026", None)),
        ("Intern - Autumn 2026", "", ("Fall 2026", None)),
        ("Software Engineer Co-op (4 months)", "", ("4-month", 4)),
        ("Co-op, Winter 2027 (8-month)", "", ("Winter 2027 · 8-month", 8)),
        ("Data Intern", "This is a 12-16 month co-op placement.", ("12–16-month", 12)),
        ("PEY Co-op Student", "", ("PEY", 12)),
        ("Software Intern", "Requires 6 months of experience with Python.", (None, None)),
        ("Software Intern", "", (None, None)),
        (
            "Data Analyst, Intern",
            "with the expectation of graduating in December 2027 or spring/summer 2028",
            (None, None),
        ),
        ("Data Intern (Summer 2027)", "Graduating in spring 2028.", ("Summer 2027", None)),
    ],
)
def test_parse_term(title, text, expected):
    assert parse_term(title, text) == expected
