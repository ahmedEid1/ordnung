"""The GiroCode: the EPC QR code a banking app scans to pre-fill a SEPA credit transfer.

Pure code, no I/O. It builds the text a QR code carries, following the European Payments Council's
*Quick Response Code: Guidelines to Enable the Data Capture for the Initiation of a SEPA Credit
Transfer* (EPC069-12, version 3.1 of 19 March 2024). Whether a payment *gets* a code is decided
elsewhere (:mod:`ordnung.secretary.girocode_gate`); this module only knows the standard.

Policy (the standard's section 2, and nothing more lenient):

* **Twelve elements, one per line**, separated by a line feed: ``BCD``, the version (``002``; ``001``
  only with a BIC), the character set, ``SCT``, the BIC, the payee's name, the IBAN, ``EUR`` and the
  amount, the purpose code, the structured *or* the unstructured remittance information, and a note
  to the payer. Empty elements keep their line; the last populated element is followed by nothing,
  so trailing empty elements are dropped.
* **Character set 1 (UTF-8)** by default — what the web app's QR encoder writes. The standard's
  other sets (ISO 8859-1 … -15) can be declared for text that fits them.
* **Payee name** 1–70 characters, **IBAN** well-formed by :func:`ordnung.money.iban.inspect_iban`
  (country, length, ISO 13616 checksum), **BIC** 8 or 11 characters. Version 002 may leave the BIC
  empty only for an account in the EEA: "the BIC will continue to be mandatory for SEPA payment
  transactions involving SCT scheme participants from non-EEA countries".
* **Amount** in euro from 0.01 to 999 999 999.99 with at most two decimals, written the way the
  standard's own examples write it: ``EUR12.3``, never ``EUR12.30`` or ``EUR 12,30``. It may be left
  out (the payer then types it).
* **Reference.** A reference shaped like an ISO 11649 RF creditor reference (``RF``, two check
  digits, 1–21 letters or digits; spaces allowed) goes into the structured element, without spaces,
  and only when its mod-97 check digits are right — a wrong one is refused, never passed on as text
  (it was misprinted or misread, and the money would be misallocated). Any other reference is the
  unstructured remittance information, at most 140 characters. The two are never both filled
  ("only one of the elements may be populated").
* **Free text** (name, reference, note) loses its line breaks, tabs and other control or format
  characters, and runs of spaces become one — a line break inside a value would shift every later
  element. Nothing is shortened: text that is too long is refused, because a cut-off name or
  reference is a different one.
* **At most 331 bytes** in the declared character set (QR version 13 at error-correction level M,
  the standard's limit).

Every refusal is a :class:`GiroCodeError` whose message says what is wrong in plain words.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal

from ordnung.money.iban import IBAN_COUNTRIES, inspect_iban

SERVICE_TAG = "BCD"
IDENTIFICATION = "SCT"
SEPARATOR = "\n"
MAX_PAYLOAD_BYTES = 331
MAX_NAME = 70
MAX_REMITTANCE = 140
MAX_STRUCTURED = 35
MAX_INFO = 70
MIN_AMOUNT = Decimal("0.01")
MAX_AMOUNT = Decimal("999999999.99")
#: The standard's character sets by the digit the payload declares.
CHARSETS: dict[str, str] = {
    "1": "utf-8",
    "2": "iso8859-1",
    "3": "iso8859-2",
    "4": "iso8859-4",
    "5": "iso8859-5",
    "6": "iso8859-7",
    "7": "iso8859-10",
    "8": "iso8859-15",
}
#: The European Economic Area: the EU's 27 member states, Iceland, Liechtenstein and Norway. Only
#: an account here may be paid by a version 002 code without its bank's BIC.
EEA_COUNTRIES = frozenset(
    {
        "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR", "GR", "HR", "HU", "IE",
        "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO", "SE", "SI", "SK",
        "IS", "LI", "NO",
    }
)  # fmt: skip

_BIC = re.compile(r"[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}(?:[A-Z0-9]{3})?")
_PURPOSE = re.compile(r"[A-Z0-9]{1,4}")
#: ``RF``, two check digits, then 1–21 letters or digits (spaces as printed are ignored).
_RF_SHAPE = re.compile(r"RF[0-9]{2}[A-Z0-9]{1,21}")
#: Characters that break a line or are invisible: control (Cc), format (Cf), line and paragraph
#: separators (Zl, Zp). Replaced by a space before spaces are collapsed.
_BREAKING = frozenset({"Cc", "Cf", "Zl", "Zp"})
_SPACES = re.compile(r"\s+")


class GiroCodeError(ValueError):
    """Why these transfer details can't become a GiroCode (plain words, for the person)."""


@dataclass(frozen=True)
class Transfer:
    """What a GiroCode tells the payer's banking app. Only ``name`` and ``iban`` are required."""

    name: str
    iban: str
    amount: Decimal | float | str | None = None
    reference: str | None = None
    bic: str = ""
    purpose: str = ""
    info: str = ""
    version: Literal["001", "002"] = "002"
    charset: str = "1"


# --------------------------------------------------------------------------------------------------
# Pieces
# --------------------------------------------------------------------------------------------------


def clean_text(text: str) -> str:
    """``text`` on one line: line breaks, tabs and invisible characters become spaces, runs of
    whitespace one space, and the ends are trimmed (see the module policy)."""
    visible = "".join(" " if unicodedata.category(char) in _BREAKING else char for char in text)
    return _SPACES.sub(" ", visible).strip()


def compact(text: str) -> str:
    """``text`` without spaces, upper-case: how an IBAN, BIC or RF reference is written in a code."""
    return re.sub(r"\s+", "", text).upper()


def _mod97(text: str) -> int:
    """ISO 7064 MOD 97-10 of ``text`` (letters count as 10–35) after moving its first four
    characters to the end — the check shared by IBANs (ISO 13616) and RF references (ISO 11649)."""
    rearranged = text[4:] + text[:4]
    return int("".join(str(int(char, 36)) for char in rearranged)) % 97


def looks_like_creditor_reference(reference: str) -> bool:
    """Whether ``reference`` is shaped like an ISO 11649 RF creditor reference (checksum aside)."""
    return _RF_SHAPE.fullmatch(compact(reference)) is not None


def creditor_reference_valid(reference: str) -> bool:
    """An ISO 11649 RF creditor reference with the right check digits (``RF18 5390 0754 7034``)."""
    value = compact(reference)
    return _RF_SHAPE.fullmatch(value) is not None and _mod97(value) == 1


def creditor_reference(body: str) -> str:
    """The RF creditor reference for ``body`` (1–21 letters or digits): ``RF``, check digits, body."""
    value = compact(body)
    if not re.fullmatch(r"[A-Z0-9]{1,21}", value):
        raise ValueError("an RF reference holds 1 to 21 letters or digits")
    return f"RF{98 - _mod97(f'RF00{value}'):02d}{value}"


def amount_text(amount: Decimal | float | str) -> str:
    """``EUR`` and the amount as the standard's examples write it: ``12.30`` → ``EUR12.3``."""
    value = _amount(amount)
    digits = format(value, "f")
    if "." in digits:
        digits = digits.rstrip("0").rstrip(".")
    return f"EUR{digits}"


def _amount(amount: Decimal | float | str) -> Decimal:
    try:
        # a float is taken as written (184.3), never as its binary expansion
        value = Decimal(repr(amount)) if isinstance(amount, float) else Decimal(amount)
    except (InvalidOperation, ValueError) as exc:
        raise GiroCodeError(f"“{amount}” is not an amount.") from exc
    if not value.is_finite():
        raise GiroCodeError(f"“{amount}” is not an amount.")
    if value < MIN_AMOUNT or value > MAX_AMOUNT:
        raise GiroCodeError("A GiroCode carries amounts from €0.01 to €999,999,999.99.")
    if value != value.quantize(Decimal("0.01")):
        raise GiroCodeError(f"{value} has more than two decimals, so it can't be an amount in euro.")
    return value


def _name(name: str) -> str:
    value = clean_text(name)
    if not value:
        raise GiroCodeError("A GiroCode needs the name of the account holder to pay.")
    if len(value) > MAX_NAME:
        raise GiroCodeError(f"The payee's name is longer than the {MAX_NAME} characters a transfer carries.")
    return value


def _iban(iban: str) -> str:
    check = inspect_iban(iban)
    if not check.valid:
        raise GiroCodeError(" ".join(["This is not a valid IBAN.", *check.problems]))
    return check.iban


def _bic(bic: str, iban: str, version: str) -> str:
    value = compact(bic)
    if value and not _BIC.fullmatch(value):
        raise GiroCodeError(f"“{bic}” is not a BIC (8 or 11 letters and digits).")
    if not value and version == "001":
        raise GiroCodeError("Version 001 of the GiroCode needs the bank's BIC.")
    if not value and iban[:2] not in EEA_COUNTRIES:
        country = IBAN_COUNTRIES[iban[:2]].name
        raise GiroCodeError(
            f"An account in {country} is outside the EEA, so the GiroCode would need its bank's BIC."
        )
    return value


def _purpose(purpose: str) -> str:
    value = compact(purpose)
    if value and not _PURPOSE.fullmatch(value):
        raise GiroCodeError(f"“{purpose}” is not a purpose code (up to 4 letters or digits).")
    return value


def remittance(reference: str | None) -> tuple[str, str]:
    """The (structured, unstructured) remittance elements for ``reference`` (module policy)."""
    text = clean_text(reference or "")
    if not text:
        return "", ""
    if looks_like_creditor_reference(text):
        if not creditor_reference_valid(text):
            raise GiroCodeError(
                f"The reference {text} looks like an RF creditor reference, but its check digits don't "
                "match — a character is wrong, missing or swapped."
            )
        return compact(text), ""
    if len(text) > MAX_REMITTANCE:
        raise GiroCodeError(
            f"The reference is longer than the {MAX_REMITTANCE} characters a transfer carries."
        )
    return "", text


def _info(info: str) -> str:
    value = clean_text(info)
    if len(value) > MAX_INFO:
        raise GiroCodeError(f"The note to the payer is longer than {MAX_INFO} characters.")
    return value


# --------------------------------------------------------------------------------------------------
# Payload
# --------------------------------------------------------------------------------------------------


def epc_payload(transfer: Transfer) -> str:
    """The text of the GiroCode for ``transfer`` (module policy), or :class:`GiroCodeError`."""
    if transfer.version not in ("001", "002"):
        raise GiroCodeError(f"Unknown GiroCode version “{transfer.version}”.")
    if transfer.charset not in CHARSETS:
        raise GiroCodeError(f"Unknown character set “{transfer.charset}”.")
    iban = _iban(transfer.iban)
    structured, unstructured = remittance(transfer.reference)
    elements = [
        SERVICE_TAG,
        transfer.version,
        transfer.charset,
        IDENTIFICATION,
        _bic(transfer.bic, iban, transfer.version),
        _name(transfer.name),
        iban,
        amount_text(transfer.amount) if transfer.amount is not None else "",
        _purpose(transfer.purpose),
        structured,
        unstructured,
        _info(transfer.info),
    ]
    while not elements[-1]:
        elements.pop()
    payload = SEPARATOR.join(elements)
    size = len(encode_payload(payload, transfer.charset))
    if size > MAX_PAYLOAD_BYTES:
        raise GiroCodeError(
            f"These details need {size} bytes, more than the {MAX_PAYLOAD_BYTES} a GiroCode holds."
        )
    return payload


def encode_payload(payload: str, charset: str = "1") -> bytes:
    """The bytes the QR code stores for ``payload`` in the declared character set."""
    try:
        return payload.encode(CHARSETS[charset])
    except UnicodeEncodeError as exc:
        raise GiroCodeError(
            f"“{exc.object[exc.start : exc.end]}” can't be written in the declared character set."
        ) from exc
