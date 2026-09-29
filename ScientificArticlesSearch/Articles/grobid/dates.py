"""Best-effort publication date parsing for the values GROBID emits."""
import datetime as dt
import re
from typing import Optional

from dateutil import parser as dateutil_parser

_FRENCH_MONTHS = {
    "janvier": "January",
    "février": "February",
    "fevrier": "February",
    "mars": "March",
    "avril": "April",
    "mai": "May",
    "juin": "June",
    "juillet": "July",
    "août": "August",
    "aout": "August",
    "septembre": "September",
    "octobre": "October",
    "novembre": "November",
    "décembre": "December",
    "decembre": "December",
}
_FRENCH_MONTHS_RE = re.compile(r"\b(" + "|".join(_FRENCH_MONTHS) + r")\b", re.IGNORECASE)

# GROBID normalises dates into the TEI `when` attribute as YYYY, YYYY-MM or YYYY-MM-DD.
_ISO_PARTIAL_RE = re.compile(r"^(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?$")
_NUMERIC_DATE_RE = re.compile(r"\b(\d{1,2})\s*[/.-]\s*(\d{1,2})\s*[/.-]\s*(\d{4})\b")
_YEAR_RE = re.compile(r"\b(1[89]\d{2}|2\d{3})\b")


def parse_iso_partial(value: Optional[str]) -> Optional[dt.date]:
    """Parse `YYYY`, `YYYY-MM` or `YYYY-MM-DD`; missing parts default to 1."""
    if not value:
        return None
    match = _ISO_PARTIAL_RE.match(value.strip())
    if not match:
        return None
    year, month, day = (int(part) if part else 1 for part in match.groups())
    try:
        return dt.date(year, month, day)
    except ValueError:
        return None


def extract_date_from_text(text: Optional[str]) -> Optional[dt.date]:
    """Extract a date from free text such as "2 Aug 2023", "12/03/2021" or "juin 2020".

    Returns a `datetime.date` (never a datetime, which DRF's DateField rejects), or None.
    """
    if not text or not text.strip():
        return None

    iso = parse_iso_partial(text)
    if iso:
        return iso

    numeric = _NUMERIC_DATE_RE.search(text)
    if numeric:
        day, month, year = (int(part) for part in numeric.groups())
        try:
            return dt.date(year, month, day)
        except ValueError:
            pass  # e.g. US-style 03/25/2021: fall through to dateutil

    normalised = _FRENCH_MONTHS_RE.sub(lambda m: _FRENCH_MONTHS[m.group(1).lower()], text)
    if _YEAR_RE.search(normalised):
        try:
            default = dt.datetime(1900, 1, 1)
            return dateutil_parser.parse(normalised, fuzzy=True, dayfirst=True, default=default).date()
        except (ValueError, OverflowError):
            pass

    year = _YEAR_RE.search(text)
    return dt.date(int(year.group(1)), 1, 1) if year else None
