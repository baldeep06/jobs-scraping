import re

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire",
    "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee",
    "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
}  # fmt: skip

CA_PROVINCES = {
    "AB": "Alberta", "BC": "British Columbia", "MB": "Manitoba", "NB": "New Brunswick",
    "NL": "Newfoundland and Labrador", "NS": "Nova Scotia", "NT": "Northwest Territories",
    "NU": "Nunavut", "ON": "Ontario", "PE": "Prince Edward Island", "QC": "Quebec",
    "SK": "Saskatchewan", "YT": "Yukon",
}  # fmt: skip

# Lowercase city -> (region code, country). Only unambiguous, commonly-posted tech cities.
KNOWN_CITIES = {
    "toronto": ("ON", "CA"), "waterloo": ("ON", "CA"), "kitchener": ("ON", "CA"),
    "ottawa": ("ON", "CA"), "mississauga": ("ON", "CA"), "markham": ("ON", "CA"),
    "montreal": ("QC", "CA"), "montréal": ("QC", "CA"), "quebec city": ("QC", "CA"),
    "vancouver": ("BC", "CA"), "burnaby": ("BC", "CA"), "calgary": ("AB", "CA"),
    "edmonton": ("AB", "CA"), "winnipeg": ("MB", "CA"), "halifax": ("NS", "CA"),
    "new york": ("NY", "US"), "new york city": ("NY", "US"), "nyc": ("NY", "US"),
    "brooklyn": ("NY", "US"), "jersey city": ("NJ", "US"), "san francisco": ("CA", "US"),
    "sf": ("CA", "US"), "bay area": ("CA", "US"), "san francisco bay area": ("CA", "US"),
    "mountain view": ("CA", "US"), "palo alto": ("CA", "US"), "menlo park": ("CA", "US"),
    "sunnyvale": ("CA", "US"), "san jose": ("CA", "US"), "cupertino": ("CA", "US"),
    "san mateo": ("CA", "US"), "santa clara": ("CA", "US"), "los angeles": ("CA", "US"),
    "san diego": ("CA", "US"), "seattle": ("WA", "US"), "redmond": ("WA", "US"),
    "bellevue": ("WA", "US"), "boston": ("MA", "US"), "austin": ("TX", "US"),
    "dallas": ("TX", "US"), "houston": ("TX", "US"), "chicago": ("IL", "US"),
    "denver": ("CO", "US"), "atlanta": ("GA", "US"), "pittsburgh": ("PA", "US"),
    "philadelphia": ("PA", "US"), "miami": ("FL", "US"), "salt lake city": ("UT", "US"),
    "portland": ("OR", "US"), "raleigh": ("NC", "US"), "washington dc": ("DC", "US"),
}  # fmt: skip

FOREIGN_RE = re.compile(
    r"\b(?:uk|united kingdom|england|scotland|london|dublin|ireland|germany|berlin|munich|"
    r"france|paris|netherlands|amsterdam|spain|madrid|barcelona|portugal|lisbon|italy|milan|"
    r"poland|warsaw|switzerland|zurich|sweden|stockholm|denmark|copenhagen|norway|finland|"
    r"india|bangalore|bengaluru|hyderabad|pune|mumbai|delhi|gurgaon|gurugram|singapore|japan|"
    r"tokyo|china|beijing|shanghai|shenzhen|hong kong|taiwan|taipei|korea|seoul|australia|"
    r"sydney|melbourne|new zealand|israel|tel aviv|brazil|são paulo|sao paulo|mexico|"
    r"argentina|buenos aires|colombia|bogota|philippines|manila|vietnam|indonesia|uae|dubai|"
    r"emea|apac|latam|europe)\b",
    re.I,
)
