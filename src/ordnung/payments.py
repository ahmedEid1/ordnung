"""How a payment is made: a transfer the person sends, or money that moves without them (a SEPA direct
debit the sender collects, money coming in). Mirrored by ``web/src/lib/payments.ts``.
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
