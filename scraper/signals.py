import hashlib
import re

_STOP = frozenset(
    "intern interns internship internships co op coop student the a an and for of to in at".split()
)
_SEASONS = re.compile(r"\b(?:summer|fall|autumn|winter|spring)\b")
_NON_ALPHA = re.compile(r"[^a-z]+")
MIN_DESCRIPTION_CHARS = 300


def title_key(normalized_title: str) -> str | None:
    """Order-insensitive title identity: "backend swe intern" == "swe intern, backend".

    Intern/co-op words are dropped (the same role is often relabelled), and fewer than two
    meaningful tokens is too generic to match on.
    """
    tokens = sorted({t for t in normalized_title.split() if t not in _STOP})
    return " ".join(tokens) if len(tokens) >= 2 else None


def desc_hash(text: str) -> str | None:
    """Hash of a posting body with numbers, seasons and punctuation removed, so a reposted
    description matches even when its term, dates or pay were edited. None if too short."""
    body = _NON_ALPHA.sub(" ", _SEASONS.sub(" ", text.lower()))
    body = " ".join(body.split())
    if len(body) < MIN_DESCRIPTION_CHARS:
        return None
    return hashlib.sha1(body.encode()).hexdigest()
