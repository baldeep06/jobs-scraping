from scraper.enrich.flags import detect_flags
from scraper.models import ParsedLocation

ONSITE = ParsedLocation(country="CA", work_mode="onsite")


def flags(title="Software Engineer Intern", text="", location=ONSITE):
    return detect_flags(title, text, None, location)


def test_work_mode_flags():
    assert "remote" in flags(location=ParsedLocation(country="US", work_mode="remote"))
    assert "hybrid" in flags(location=ParsedLocation(country="US", work_mode="hybrid"))
    assert "remote" not in flags()


def test_grad_year():
    f = flags(text="Candidates graduating in May 2028 are preferred.")
    assert f["grad_year:2028"] == "Candidates graduating in May 2028 are preferred."


def test_grad_students_only_from_title_and_text():
    assert "grad_students_only" in flags(title="Research Intern (PhD)")
    assert "grad_students_only" in flags(text="You must be currently pursuing a Master's degree.")
    assert "grad_students_only" not in flags(text="Bachelor's or Master's students welcome.")


def test_early_years_only():
    assert "early_years_only" in flags(title="STEP Intern")
    assert "early_years_only" in flags(text="Open to first-year and second-year students.")
    assert "early_years_only" not in flags(title="Step Functions Intern")


def test_eligibility_restricted_and_relocation():
    f = flags(
        text="This program is designed for students from underrepresented groups. "
        "Relocation assistance is provided."
    )
    assert "eligibility_restricted" in f
    assert f["relocation"] == "Relocation assistance is provided."
