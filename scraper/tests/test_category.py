import pytest

from scraper.enrich.category import categorize, is_intern_title


@pytest.mark.parametrize(
    ("title", "employment", "expected"),
    [
        ("Software Engineer Intern", None, True),
        ("Software Engineering Internship - Summer 2027", None, True),
        ("Co-op Student, Data", None, True),
        ("PEY Co-op", None, True),
        ("Software Engineer Intern, Internal Tools", None, True),
        ("Product Manager Intern", None, True),
        ("Student Researcher", None, True),
        ("Software Engineer, Summer 2027", "Intern", True),
        ("Software Engineer, Summer 2027", "Internship", True),
        ("Senior Software Engineer", None, False),
        ("Sr. Intern Program Manager", None, False),
        ("Staff Engineer", None, False),
        ("Internal Audit Analyst", None, False),
        ("International Sales Lead", None, False),
        ("Student Success Manager", None, False),
        ("Software Engineer", "Full-time", False),
    ],
)
def test_is_intern_title(title, employment, expected):
    assert is_intern_title(title, employment) is expected


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Software Engineer Intern", "SWE"),
        ("Backend Developer Co-op", "SWE"),
        ("UI Engineer Intern", "SWE"),
        ("Quantum Computing Intern", "SWE"),
        ("Machine Learning Intern", "Data/ML"),
        ("Data Analyst Intern", "Data/ML"),
        ("Firmware Engineering Co-op", "Hardware/Embedded"),
        ("Mechanical Engineering Intern", "Hardware/Embedded"),
        ("Security Engineer Intern", "IT/Security"),
        ("IT Support Co-op", "IT/Security"),
        ("Product Manager Intern", "PM"),
        ("AI Product Manager Intern", "PM"),
        ("Product Design Intern", "Design"),
        ("UX Research Intern", "Design"),
        ("Quantitative Research Intern", "Quant"),
        ("Trading Intern", "Quant"),
        ("Technical Writer Intern", "Other-tech"),
        ("Marketing Intern", None),
        ("Civil Engineering Intern", None),
        ("Chemical Engineer Co-op", None),
    ],
)
def test_categorize(title, expected):
    assert categorize(title) == expected
