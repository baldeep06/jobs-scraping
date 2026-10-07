from scraper.text import html_to_text, sentence_at


def test_html_to_text_handles_escaped_html():
    raw = "&lt;p&gt;Join our team.&lt;/p&gt;&lt;p&gt;Pay is &lt;b&gt;$30&lt;/b&gt; per hour &amp;amp; more.&lt;/p&gt;"
    assert html_to_text(raw) == "Join our team.\nPay is $30 per hour & more."


def test_html_to_text_list_items_and_br():
    assert (
        html_to_text("<ul><li>One</li><li>Two</li></ul>Three<br/>Four") == "One\nTwo\nThree\nFour"
    )


def test_html_to_text_empty():
    assert html_to_text("") == ""


def test_sentence_at_picks_containing_sentence():
    text = "Great team. We will not sponsor visas. Apply now."
    assert sentence_at(text, text.index("sponsor")) == "We will not sponsor visas."


def test_sentence_at_does_not_split_on_us_abbreviation():
    text = "Applicants must be U.S. Citizens to apply. Thanks."
    assert sentence_at(text, text.index("must")) == "Applicants must be U.S. Citizens to apply."


def test_sentence_at_splits_on_newlines_and_truncates():
    text = "Line one\n" + "x" * 400
    assert sentence_at(text, 2) == "Line one"
    out = sentence_at(text, 20)
    assert len(out) == 300 and out.endswith("…")
