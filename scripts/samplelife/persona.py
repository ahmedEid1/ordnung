"""The demo persona (SPEC §1.3): Sam Rivera, international master's student in Musterstadt (NRW)."""

from __future__ import annotations

from samplelife.ids import format_iban
from samplelife.orgs import MUSTERBANK

NAME = "Sam Rivera"
FIRST_NAME = "Sam"
LAST_NAME = "Rivera"
STREET = "Beispielweg 5"
CITY = "12345 Musterstadt"
#: As the Profile asks for it: street and house number, then postcode and town, one per line.
ADDRESS = f"{STREET}\n{CITY}"
# Until 30.09.2025 Sam lived in a student residence; letters from that time go there.
OLD_STREET = "Campusallee 12, App. 314"
OLD_CITY = "12347 Musterstadt"
EMAIL = "sam.rivera@example.org"
PHONE = "0123 98765432"
BIRTH_DATE = "2000-03-14"
BIRTH_PLACE = "Examplia City"
NATIONALITY_DE = "examplianisch"
MATRIKEL = "4711123"
STEUER_ID = "57 216 480 393"
KVNR = "R482019375"
RV_NUMMER = "65 140300 R 004"
PERSONALNUMMER = "10482"
SIMULATED_TODAY = "2026-09-28"

IBAN = MUSTERBANK.iban("0071234500")
IBAN_PRETTY = format_iban(IBAN)
IBAN_MASKED = f"{IBAN[:4]} XXXX XXXX XXXX XX{IBAN[-4:-2]} {IBAN[-2:]}"


def recipient(*, old: bool = False, english: bool = False) -> list[str]:
    """Address-window lines for Sam (``old`` = the student-residence address)."""
    street, city = (OLD_STREET, OLD_CITY) if old else (STREET, CITY)
    if english:
        return [f"Mr {NAME}", street, city]
    return ["Herrn", NAME, street, city]


PROFILE = {
    "name": NAME,
    "address": ADDRESS,
    "email": EMAIL,
    "phone": PHONE,
    "language": "en",
    "country": "DE",
    "region": "NW",
    "timezone": "Europe/Berlin",
    "is_student_visa": True,
}
