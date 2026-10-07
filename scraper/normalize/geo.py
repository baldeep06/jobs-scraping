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

# Foreign city -> ISO country code. "City, XX" is foreign when XX is that code, so
# "Berlin, DE" is Germany but "Dublin, OH" / "Paris, TX" stay in the US.
FOREIGN_CITIES = {
    "london": "GB", "manchester": "GB", "edinburgh": "GB", "belfast": "GB", "dublin": "IE",
    "berlin": "DE", "munich": "DE", "hamburg": "DE", "frankfurt": "DE", "cologne": "DE",
    "stuttgart": "DE", "paris": "FR", "lyon": "FR", "amsterdam": "NL", "rotterdam": "NL",
    "eindhoven": "NL", "utrecht": "NL", "madrid": "ES", "barcelona": "ES", "lisbon": "PT",
    "milan": "IT", "warsaw": "PL", "krakow": "PL", "wroclaw": "PL", "zurich": "CH",
    "stockholm": "SE", "copenhagen": "DK", "oslo": "NO", "helsinki": "FI", "bucharest": "RO",
    "cluj": "RO", "prague": "CZ", "brno": "CZ", "budapest": "HU", "vienna": "AT",
    "brussels": "BE", "athens": "GR", "istanbul": "TR", "kyiv": "UA", "belgrade": "RS",
    "sofia": "BG", "zagreb": "HR", "tallinn": "EE", "riga": "LV", "vilnius": "LT",
    "bratislava": "SK", "bangalore": "IN", "bengaluru": "IN", "hyderabad": "IN", "pune": "IN",
    "mumbai": "IN", "delhi": "IN", "new delhi": "IN", "gurgaon": "IN", "gurugram": "IN",
    "chennai": "IN", "noida": "IN", "kolkata": "IN", "ahmedabad": "IN", "kochi": "IN",
    "singapore": "SG", "tokyo": "JP", "osaka": "JP", "beijing": "CN", "shanghai": "CN",
    "shenzhen": "CN", "hong kong": "HK", "taipei": "TW", "seoul": "KR", "sydney": "AU",
    "melbourne": "AU", "tel aviv": "IL", "haifa": "IL", "herzliya": "IL", "sao paulo": "BR",
    "buenos aires": "AR", "bogota": "CO", "medellin": "CO", "manila": "PH",
    "kuala lumpur": "MY", "bangkok": "TH", "jakarta": "ID", "hanoi": "VN",
    "ho chi minh": "VN", "cairo": "EG", "nairobi": "KE", "lagos": "NG",
    "johannesburg": "ZA", "cape town": "ZA", "riyadh": "SA", "doha": "QA", "dubai": "AE",
    "abu dhabi": "AE", "karachi": "PK", "lahore": "PK", "dhaka": "BD", "colombo": "LK",
    "lima": "PE", "santiago": "CL", "montevideo": "UY", "mexico city": "MX",
    "guadalajara": "MX", "monterrey": "MX",
}  # fmt: skip

FOREIGN_PLACES = [
    "uk", "united kingdom", "england", "scotland", "wales", "ireland", "germany", "france",
    "netherlands", "spain", "portugal", "italy", "poland", "switzerland", "sweden", "denmark",
    "norway", "finland", "romania", "czech republic", "czechia", "hungary", "austria",
    "belgium", "greece", "turkey", "ukraine", "serbia", "bulgaria", "croatia", "estonia",
    "latvia", "lithuania", "slovakia", "luxembourg", "iceland", "india", "japan", "china",
    "taiwan", "korea", "south korea", "australia", "new zealand", "israel", "brazil",
    "mexico", "argentina", "colombia", "philippines", "vietnam", "indonesia", "malaysia",
    "thailand", "egypt", "kenya", "nigeria", "south africa", "saudi arabia", "qatar", "uae",
    "united arab emirates", "pakistan", "bangladesh", "sri lanka", "peru", "chile",
    "uruguay", "costa rica", "emea", "apac", "latam", "europe",
]  # fmt: skip

FOREIGN_RE = re.compile(
    r"\b(?:"
    + "|".join(sorted(map(re.escape, [*FOREIGN_CITIES, *FOREIGN_PLACES]), key=len, reverse=True))
    + r")\b",
    re.I,
)
