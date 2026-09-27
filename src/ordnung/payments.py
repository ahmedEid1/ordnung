"""How a payment is made: a transfer the person sends, money paid in person (card or cash on site), or
money that moves without them (a SEPA direct debit the sender collects, money coming in). Mirrored by
``web/src/lib/payments.ts`` and ``paysOnSite`` in ``web/src/features/document/item-meta.ts``.
"""

from __future__ import annotations

import re

from ordnung.models import Item

_DEBIT_WORDS = re.compile(
    r"direct debit|lastschrift|abbuchung|abgebucht|sufficient funds|kontodeckung|collected automatically",
    re.I,
)
_TRANSFER_WORDS = re.compile(r"\btransfer|überweis", re.I)


def is_direct_debit(item: Item) -> bool:
    """The sender collects this payment itself (SEPA direct debit): nothing to transfer."""
    text = " ".join(part for part in (item.title, item.action, item.description) if part)
    return bool(_DEBIT_WORDS.search(text)) and not _TRANSFER_WORDS.search(item.action or "")


def is_collected_or_incoming(item: Item) -> bool:
    """A payment the person doesn't make: a direct debit the sender collects, or money coming in."""
    return item.kind == "payment" and (item.direction == "in" or is_direct_debit(item))


#: Paid in person — at the appointment, the service desk or a machine, by card or in cash (as
#: ``ON_SITE`` in ``web/src/features/document/item-meta.ts``).
_ON_SITE_WORDS = re.compile(
    r"\bon[ -]site\b|\bat the appointment\b|\bat the (?:service )?(?:desk|counter)\b|\bpayment machine\b"
    r"|\bgirocard\b|\bEC[ -]card\b|\bcash\b|\bvor Ort\b|\bin bar\b|\bbar (?:be)?zahlen\b|\bEC-Karte\b"
    r"|\bam (?:Kassen|Zahl)automaten\b|\ban der Kasse\b",
    re.I,
)


def pays_on_site(item: Item) -> bool:
    """A payment made in person (card or cash at the appointment, the desk, a machine), not by bank
    transfer: its "send by" — a transfer's day (§ 675s BGB) — means nothing, the due day is the day."""
    if item.kind != "payment" or item.direction == "in" or is_direct_debit(item):
        return False
    how = " ".join(part for part in (item.action, item.description) if part)
    return bool(_ON_SITE_WORDS.search(how)) and not _TRANSFER_WORDS.search(item.action or "")
