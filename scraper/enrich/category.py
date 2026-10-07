import re

_SENIOR = re.compile(r"\b(?:senior|sr|staff|principal|director|head|vp)\b", re.I)
_STRONG = re.compile(
    r"\b(?:interns?|internships?|co-?ops?|apprentices?|apprenticeships?)\b|(?-i:\bPEY\b)", re.I
)
_WEAK = re.compile(r"\b(?:students?|placements?)\b", re.I)
_NOT_STUDENT_ROLE = re.compile(
    r"\b(?:manager|coordinator|advisor|adviser|recruiter|success|services|officer|counsell?or)\b",
    re.I,
)
_INTERN_EMPLOYMENT = re.compile(r"intern|co-?op", re.I)


def is_intern_title(title: str, employment_type: str | None = None) -> bool:
    if _SENIOR.search(title):
        return False
    if _STRONG.search(title):
        return True
    if employment_type and _INTERN_EMPLOYMENT.search(employment_type):
        return True
    return bool(_WEAK.search(title)) and not _NOT_STUDENT_ROLE.search(title)


_NON_TECH_ENGINEERING = re.compile(
    r"\b(?:civil|chemical|structural|environmental|geotechnical|petroleum|mining|nuclear|"
    r"biomedical|process)\s+engineer",
    re.I,
)

# First match wins, so order matters (e.g. "Security Engineer" must hit IT/Security before SWE).
CATEGORY_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("Quant", re.compile(r"\b(?:quant(?:itative)?|trading|trader)\b", re.I)),
    (
        "PM",
        re.compile(
            r"\b(?:product manag\w*|program manag\w*|technical program|apm)\b|(?-i:\bPM\b)", re.I
        ),
    ),
    (
        "Design",
        re.compile(
            r"\b(?:ux|ui/ux|ux/ui|user experience|product design\w*|designer|interaction design|"
            r"visual design)\b",
            re.I,
        ),
    ),
    (
        "Data/ML",
        re.compile(
            r"\b(?:data|machine learning|ml|ai|artificial intelligence|analytics|deep learning|"
            r"nlp|computer vision|research scientist|applied scientist)\b",
            re.I,
        ),
    ),
    (
        "Hardware/Embedded",
        re.compile(
            r"\b(?:hardware|embedded|firmware|fpga|asic|silicon|electrical|electronics?|circuits?|"
            r"rtl|robotics|mechatronics|mechanical|manufacturing)\b",
            re.I,
        ),
    ),
    (
        "IT/Security",
        re.compile(
            r"\b(?:security|cyber\w*|infosec|network\w*|help ?desk|systems? admin\w*)\b"
            r"|(?-i:\bIT\b)",
            re.I,
        ),
    ),
    (
        "SWE",
        re.compile(
            r"\b(?:software|developer|engineer\w*|swe|sde|back-?end|front-?end|full[- ]?stack|"
            r"mobile|ios|android|devops|sre|site reliability|platform|infrastructure|cloud|web|"
            r"programmer|qa|quality assurance|test automation|computer science|computing)\b",
            re.I,
        ),
    ),
    (
        "Other-tech",
        re.compile(r"\b(?:technical|technology|tech|solutions|developer relations)\b", re.I),
    ),
]


def categorize(title: str) -> str | None:
    if _NON_TECH_ENGINEERING.search(title):
        return None
    for category, pattern in CATEGORY_RULES:
        if pattern.search(title):
            return category
    return None
