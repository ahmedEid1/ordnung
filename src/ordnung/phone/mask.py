"""What a paired phone sees of the person's own numbers: their last 4 characters (policy:
:mod:`ordnung.phone`).

Whoever holds an unlocked paired phone shouldn't read the person's tax ID, social security number or
IBAN off it. So on a phone *My numbers* (``GET /api/numbers``) shows the person's own numbers — those
about them, on their identity documents, the ones organisations' letters show for them and a case's
references — as ``•••• 1234`` (``masked: true``; the full number is on the computer), and the profile
its IBAN the same way. An organisation's own numbers (its register entry, its bank account) stay
whole: the phone pays with them. Ask's tools mask the same numbers for a phone's question
(``ordnung.assistant.mcp_server``). Each masked number gets a key of its own, so a key can't be traced
back to the number.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from ordnung.models import CallSheet, IdentityDocument, MyNumber, MyNumbers, OpenCase, Profile

MASK = "••••"
_KEY_SALT = secrets.token_bytes(16)  # per process: a masked key never says which number it was


def mask_value(value: str) -> str:
    """``•••• 1234`` (the last 4 characters, spaces left out); a value of 4 characters or fewer stays."""
    compact = "".join(value.split())
    return compact if len(compact) <= 4 else f"{MASK} {compact[-4:]}"


def _masked_key(key: str) -> str:
    return "num_" + hmac.new(_KEY_SALT, key.encode(), hashlib.sha256).hexdigest()[:12]


def mask_number(number: MyNumber) -> MyNumber:
    """One number as a phone shows it."""
    shown = mask_value(number.value)
    return number.model_copy(
        update={"key": _masked_key(number.key), "value": shown, "display": shown, "copy_value": shown}
    )


def _case(case: OpenCase) -> OpenCase:
    return case.model_copy(update={"references": [mask_number(n) for n in case.references]})


def _document(document: IdentityDocument) -> IdentityDocument:
    return document.model_copy(update={"number": mask_number(document.number) if document.number else None})


def _sheet(sheet: CallSheet) -> CallSheet:
    return sheet.model_copy(
        update={
            "numbers": [mask_number(n) for n in sheet.numbers],
            "open_cases": [_case(c) for c in sheet.open_cases],
        }
    )


def mask_numbers(page: MyNumbers) -> MyNumbers:
    """*My numbers* on a phone (``masked: true``)."""
    return page.model_copy(
        update={
            "about_you": [mask_number(n) for n in page.about_you],
            "documents": [_document(d) for d in page.documents],
            "organisations": [_sheet(s) for s in page.organisations],
            "open_cases": [_case(c) for c in page.open_cases],
            "masked": True,
        }
    )


def mask_profile(profile: Profile) -> Profile:
    """The profile on a phone: its IBAN masked (the address stays — letters written there need it)."""
    return profile.model_copy(update={"iban": mask_value(profile.iban)}) if profile.iban else profile
