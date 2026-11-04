"""A synthetic final-split plug-in for the generator's tests and the zero-token rehearsal; never benchmark data.

``evals/generate.py`` loads ``gen/final.py`` when that module exists. This file has its shape: ``FINAL_DAY``,
``VALID_UNTIL``, ``FAMILIES`` (per final split, its builders), ``CONVENTIONS_FINAL`` and ``KIND_ALSO_ACCEPTED_FINAL``.
It builds one one-page letter of the ``newkinds`` split and its phone photo: two entries. The letter is filed under the
family ``adversarial``, the one family whose case names no template variant, since ``newkinds`` has none.

Every date follows ``FINAL_DAY``, so a rehearsal can set that one line to the day it runs. The imports are relative,
as the real plug-in's are: the file runs as a module of ``evals/gen``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

from . import law
from .common import Case, fixed_item, truth, with_conventions
from .pdf import Letter, Org, P, Person, Sign
from .text import de

FINAL_DAY = date(2026, 12, 8)
VALID_UNTIL = FINAL_DAY + timedelta(days=7)
SPLIT = "newkinds"
CASE_ID = f"{SPLIT}-adversarial-1"

CONVENTIONS_FINAL: list[dict[str, Any]] = [
    {
        "id": "f01",
        "disputed": False,
        "text": "Synthetic test split: the letter is read on the final day, and its one date lies after the window.",
    },
]
KIND_ALSO_ACCEPTED_FINAL: dict[str, list[str]] = {CASE_ID: ["invoice"]}


def _working_day_from(day: date) -> date:
    while not all(law.is_working_day(day, land) for land in law.LAENDER):
        day += timedelta(days=1)
    return day


def payment_request(
    *, due: date | None = None, today: date | None = None, tags: Sequence[str] = ("c06", "f01")
) -> list[Case]:
    """One payment request with a fixed date: ``due`` defaults to the first working day a week after the window."""
    letter_date = FINAL_DAY - timedelta(days=3)
    due = due or _working_day_from(VALID_UNTIL + timedelta(days=8))
    org = Org(
        name="Beispiel Testversand GmbH",
        kind="company",
        street="Musterweg 1",
        postcode="12345",
        city="Musterstadt",
        style="minimal",
    )
    person = Person(name="Erika Beispiel", street="Probestraße 2", postcode="12345", city="Musterstadt")
    item = with_conventions(
        fixed_item(
            due=due,
            region=None,
            kind="payment",
            nature="payment",
            title="Offenen Betrag bezahlen",
            money=48.0,
            rule="Payment date stated in the letter.",
        ),
        tags,
    )
    letter = Letter(
        org=org,
        recipient=person,
        info=[("Kundennummer", "T-0001"), ("Datum", de(letter_date))],
        subject="Zahlungserinnerung (Testschreiben)",
        blocks=[
            P("Dies ist ein fiktives Testschreiben ohne echten Absender."),
            P(f"Bitte zahlen Sie den offenen Betrag von 48,00 EUR bis zum {de(due)}."),
            Sign("Mit freundlichen Grüßen", ("Beispiel Testversand",)),
        ],
        created=datetime(letter_date.year, letter_date.month, letter_date.day, 8, 0, tzinfo=UTC),
    )
    case = Case(
        id=CASE_ID,
        split=SPLIT,
        family="adversarial",
        variant="",
        letter=letter,
        truth=truth(
            kind="dunning",
            sender=org.name,
            document_date=letter_date,
            references=[("Kundennummer", "T-0001")],
            amounts=[48.0],
            items=[item],
        ),
        today=today or FINAL_DAY,
        authority_region=None,
        key_phrases=[de(due)],
        photo=True,
    )
    return [case]


FAMILIES = {SPLIT: (("adversarial", payment_request),)}
