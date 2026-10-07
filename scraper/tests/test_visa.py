import pytest

from scraper.enrich.visa import detect_visa_signals, visa_status


@pytest.mark.parametrize(
    ("text", "signal"),
    [
        ("We are unable to sponsor visas for this role.", "no_sponsorship"),
        ("We do not sponsor work visas.", "no_sponsorship"),
        ("We don't offer visa sponsorship for interns.", "no_sponsorship"),
        (
            "Must be authorized to work in the US without current or future sponsorship.",
            "no_sponsorship",
        ),
        ("Sponsorship is not available for this position.", "no_sponsorship"),
        ("Applicants must be a U.S. citizen.", "us_citizen_only"),
        ("U.S. citizenship is required.", "us_citizen_only"),
        ("Open to US citizens or green card holders only.", "us_citizen_only"),
        ("This role is subject to ITAR.", "us_citizen_only"),
        ("This position requires an active Secret clearance.", "clearance"),
        ("Candidates must obtain a security clearance.", "clearance"),
        ("Must be enrolled at a U.S. university.", "us_school_required"),
        ("F-1 students with CPT authorization are welcome.", "us_school_required"),
        ("Visa sponsorship is available for this role.", "sponsors"),
        ("We will sponsor J-1 visas for interns.", "sponsors"),
        ("International students are welcome to apply.", "sponsors"),
        ("Must be enrolled in a co-op program at a Canadian university.", "canadian_coop_required"),
    ],
)
def test_detects_signal(text, signal):
    assert signal in detect_visa_signals(text)


def test_evidence_is_the_matching_sentence():
    signals = detect_visa_signals("Great team. We will not sponsor visas. Apply now.")
    assert signals == {"no_sponsorship": "We will not sponsor visas."}


def test_no_false_positives_on_neutral_text():
    text = "We offer great opportunities. Secrets management experience is a plus. Apply now."
    assert detect_visa_signals(text) == {}


def test_not_available_is_not_sponsors():
    assert "sponsors" not in detect_visa_signals("Visa sponsorship is not available.")


@pytest.mark.parametrize(
    ("signals", "country", "status"),
    [
        ({"no_sponsorship"}, "US", "blocked"),
        ({"sponsors"}, "US", "open"),
        ({"sponsors", "no_sponsorship"}, "US", "blocked"),
        (set(), "US", "unknown"),
        ({"clearance"}, "UNKNOWN", "blocked"),
        ({"no_sponsorship"}, "CA", "open"),
        ({"canadian_coop_required"}, "CA", "open"),
        ({"us_citizen_only"}, "BOTH", "open"),
    ],
)
def test_visa_status_for_owner(signals, country, status):
    assert visa_status(signals, country) == status
