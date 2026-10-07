from scraper.signals import desc_hash, title_key

LONG = "We build payment systems and you will write Python services. " * 8


def test_title_key_ignores_order_and_intern_words():
    a = title_key("software engineer intern backend")
    assert a == title_key("backend software engineer intern")
    assert a == title_key("backend software engineer co op")
    assert a == title_key("backend software engineer internship")


def test_title_key_keeps_distinguishing_words():
    assert title_key("data analyst intern") != title_key("data scientist intern")
    assert title_key("software engineer intern frontend") != title_key(
        "software engineer intern backend"
    )


def test_title_key_needs_two_meaningful_tokens():
    assert title_key("intern") is None
    assert title_key("engineer intern") is None
    assert title_key("software engineer intern") is not None


def test_desc_hash_ignores_terms_numbers_and_punctuation():
    a = desc_hash(LONG + " Summer 2026, pay $40/hour. Apply by 2026-01-15!")
    b = desc_hash(LONG + " Fall 2027, pay $45/hour. Apply by 2027-02-01.")
    assert a is not None and a == b


def test_desc_hash_differs_for_different_roles():
    assert desc_hash(LONG) != desc_hash(LONG.replace("Python", "Rust"))


def test_desc_hash_none_when_description_is_too_short():
    assert desc_hash("Short blurb.") is None
    assert desc_hash("") is None
