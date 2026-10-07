import html
import re

from selectolax.lexbor import LexborHTMLParser

_BLOCK_END = re.compile(r"(?i)<\s*(?:br\s*/?|/p|/li|/div|/h[1-6]|/tr|/ul|/ol)\s*>")
# Split after . ! ? when preceded by a lowercase letter/digit/bracket (so "U.S. Citizens"
# stays together) and followed by an uppercase/digit/quote; or on newlines.
_SENTENCE_BREAK = re.compile(r"(?<=[a-z0-9)\]][.!?])\s+(?=[A-Z0-9(\"'])|\n+")


def html_to_text(raw: str) -> str:
    """HTML (possibly entity-escaped, as Greenhouse returns it) -> plain text, one block per line."""
    if not raw:
        return ""
    marked = _BLOCK_END.sub("\n", html.unescape(raw))
    text = LexborHTMLParser(marked).text(separator="")
    lines = (" ".join(line.split()) for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def _spans(text: str) -> list[tuple[int, int]]:
    spans, pos = [], 0
    for m in _SENTENCE_BREAK.finditer(text):
        spans.append((pos, m.start()))
        pos = m.end()
    spans.append((pos, len(text)))
    return spans


def sentence_at(text: str, index: int, max_len: int = 300) -> str:
    for start, end in _spans(text):
        if start <= index <= end:
            s = text[start:end].strip()
            return s if len(s) <= max_len else s[: max_len - 1].rstrip() + "…"
    return ""
