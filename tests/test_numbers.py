"""My numbers (``ordnung.numbers``): check digits, the written classification policy, the page built from a
ledger, the demo's own numbers, and ``GET /api/numbers``."""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from ordnung import clock
from ordnung.config import Paths
from ordnung.db.store import Store
from ordnung.models import DocumentExtraction, Identifier
from ordnung.numbers import (
    RESIDENCE_EXPIRED_NOTE,
    RESIDENCE_EXTENSION_NOTE,
    Context,
    check_number,
    classify,
    copy_value,
    display_value,
    health_insurance_problem,
    is_number,
    label_key,
    social_insurance_problem,
    tax_id_problem,
)
from ordnung.views import my_numbers
from test_api_support import api_for

TODAY = date(2026, 9, 28)
DEMO_DB = Path(__file__).resolve().parents[1] / "src" / "ordnung" / "demo" / "demo_db"


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


# --------------------------------------------------------------------------------------------------
# check digits
# --------------------------------------------------------------------------------------------------


def _tax_id(first_ten: str) -> str:
    """``first_ten`` with its ISO/IEC 7064 MOD 11,10 check digit (computed independently of the module)."""
    product = 10
    for digit in first_ten:
        total = (int(digit) + product) % 10
        product = ((total or 10) * 2) % 11
    return first_ten + str((11 - product) % 10)


@pytest.mark.parametrize("valid", ["86095742719", "47036892816", "57 216 480 354", "86 095 742 719"])
def test_valid_steuer_ids_pass(valid: str) -> None:
    assert tax_id_problem(valid) is None
    assert check_number("tax_id", valid).status == "ok"


@pytest.mark.parametrize(
    ("value", "problem"),
    [
        ("8609574271", "A Steuer-ID has 11 digits; this has 10"),
        ("860957427190", "A Steuer-ID has 11 digits; this has 12"),
        ("06095742719", "A Steuer-ID never starts with 0"),
        # the demo payslip's number: all ten first digits differ
        (
            "57 216 480 393",
            "In a Steuer-ID's first ten digits exactly one digit appears twice or three times",
        ),
        ("11223456781", "In a Steuer-ID's first ten digits exactly one digit appears twice or three times"),
        (
            _tax_id("1112345678"),
            "A digit that appears three times in a Steuer-ID never stands three in a row",
        ),
        ("86095742718", "The last digit is not the Steuer-ID's check digit"),
        ("8609574271X", "A Steuer-ID has 11 digits; this has 10"),
    ],
)
def test_steuer_id_rules(value: str, problem: str) -> None:
    assert tax_id_problem(value) == problem
    check = check_number("tax_id", value)
    assert check.status == "fails"
    assert check.note is not None and "compare it with the letter" in check.note and "§ 139b AO" in check.note


def test_a_digit_three_times_is_allowed_when_not_three_in_a_row() -> None:
    assert tax_id_problem(_tax_id("1121345678")) is None  # 1 three times, two of them side by side
    assert tax_id_problem(_tax_id("1213145678")) is None


_TEN = st.permutations("0123456789").map("".join)


@st.composite
def _valid_tax_ids(draw: st.DrawFn) -> str:
    digits = draw(_TEN.filter(lambda d: d[0] != "0"))
    # replace one digit by another one of the first ten: one digit twice, one missing
    drop = draw(st.integers(1, 9))
    copy = draw(st.integers(0, 9).filter(lambda i: i != drop))
    first_ten = digits[:drop] + digits[copy] + digits[drop + 1 :]
    return _tax_id(first_ten)


@given(_valid_tax_ids(), st.integers(0, 10), st.integers(1, 9))
def test_every_single_misread_digit_of_a_steuer_id_fails(valid: str, position: int, shift: int) -> None:
    assert tax_id_problem(valid) is None
    misread = valid[:position] + str((int(valid[position]) + shift) % 10) + valid[position + 1 :]
    assert tax_id_problem(misread) is not None


@pytest.mark.parametrize("valid", ["15 070649 C 103", "65 140300 R 005", "65140300R005"])
def test_valid_social_insurance_numbers_pass(valid: str) -> None:
    assert social_insurance_problem(valid) is None
    assert check_number("social_insurance", valid).status == "ok"


@pytest.mark.parametrize(
    ("value", "problem"),
    [
        ("65 140300 R 004", "The last digit is not the check digit"),  # the demo payslip's
        ("15 070649 C 10", "A Rentenversicherungsnummer has 12 characters: 8 digits, a letter and 3 digits"),
        ("15 070649 1 103", "A Rentenversicherungsnummer has 12 characters: 8 digits, a letter and 3 digits"),
    ],
)
def test_social_insurance_rules(value: str, problem: str) -> None:
    assert social_insurance_problem(value) == problem
    assert check_number("social_insurance", value).status == "fails"


def _rvnr(body: str, letter: str) -> str:
    digits = body[:8] + f"{ord(letter) - 64:02d}" + body[8:]
    weights = (2, 1, 2, 5, 7, 1, 2, 1, 2, 1, 2, 1)
    total = sum(sum(map(int, str(int(d) * w))) for d, w in zip(digits, weights, strict=True))
    return f"{body[:8]}{letter}{body[8:]}{total % 10}"


@given(
    st.text("0123456789", min_size=10, max_size=10),
    st.sampled_from("ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
    st.sampled_from([0, 1, 2, 3, 5, 6, 7, 9, 10, 11]),  # every digit but the fifth (weight 7) and the letter
    st.integers(1, 9),
)
def test_a_misread_digit_of_a_social_insurance_number_fails(
    body: str, letter: str, position: int, shift: int
) -> None:
    valid = _rvnr(body, letter)
    assert social_insurance_problem(valid) is None
    misread = valid[:position] + str((int(valid[position]) + shift) % 10) + valid[position + 1 :]
    assert social_insurance_problem(misread) is not None


def test_the_published_algorithm_misses_two_swaps_of_the_fifth_digit() -> None:
    """Weight 7 and one cross sum: 0 and 4 (0, 28 → 10) and 3 and 7 (21 → 3, 49 → 13) add the same last
    digit, so these misreads pass — a documented limit of the algorithm, not of the code."""
    valid = _rvnr("0000700000", "A")
    assert social_insurance_problem(valid) is None
    assert social_insurance_problem(valid[:4] + "3" + valid[5:]) is None
    assert social_insurance_problem(valid[:4] + "5" + valid[5:]) is not None


@pytest.mark.parametrize(("value", "ok"), [("A123456780", True), ("R482019379", True), ("R482019375", False)])
def test_health_insurance_numbers(value: str, ok: bool) -> None:
    assert (health_insurance_problem(value) is None) is ok
    assert check_number("health_insurance", value).status == ("ok" if ok else "fails")


def test_a_private_insurers_member_number_has_no_check() -> None:
    assert check_number("health_insurance", "PKV-4471-2290").status == "none"
    assert health_insurance_problem("A12345678") == "A Krankenversichertennummer has a letter and nine digits"


def test_ibans_use_the_existing_check_and_other_numbers_have_none() -> None:
    assert check_number("iban", "DE89 3704 0044 0532 0130 00").status == "ok"
    failing = check_number("iban", "DE89 3704 0044 0532 0130 01")
    assert failing.status == "fails" and failing.note is not None and "check digits" in failing.note
    assert check_number("account", "DE89370400440532013000").status == "ok"  # your account at a bank
    assert check_number("customer", "86095742718").status == "none"
    assert check_number("student", "4711123").status == "none"


# --------------------------------------------------------------------------------------------------
# classification: the written policy, rule by rule
# --------------------------------------------------------------------------------------------------

AUTHORITY = Context(party_kind="authority")
TAX_OFFICE = Context(party_kind="tax_office", doc_kind="tax_assessment")
BANK = Context(party_kind="bank")
BROADCASTER = Context(party_kind="public_broadcaster", doc_kind="broadcasting_fee")


@pytest.mark.parametrize(
    ("label", "value", "ctx", "kind"),
    [
        # 1. not a number
        ("Wohnung", "Nr. 05-2-03, 2. OG links", None, None),
        ("Name", "SAM RIVERA", None, None),
        # 2. by shape, whatever the label
        ("Gläubiger-ID", "DE53ZZZ00000204170", None, "creditor_id"),
        ("Kundennummer", "DE53ZZZ00000204170", None, "creditor_id"),
        ("USt-IdNr.", "DE310457828", None, "vat_id"),
        ("Steuer-Nr.", "DE 310457828", None, "vat_id"),
        ("Bankverbindung", "DE89 3704 0044 0532 0130 00", None, "iban"),
        ("IBAN", "DE89 3704 0044 0532 0130 00", BANK, "account"),
        ("IBAN", "DE89 3704 0044 0532 0130 00", Context(own_iban="DE89370400440532013000"), "account"),
        # a misread IBAN is still an IBAN (and then does not check): its country's length, or its label
        ("IBAN", "DE89 3704 0044 0532 0130 01", None, "iban"),
        ("Bankverbindung", "DE89 3704 0044 0532 0130 01", None, "iban"),
        ("IBAN", "DE89 3704 0044 0532 0130 0", None, "iban"),  # a digit short
        ("Kundennummer", "DE89370400440532013001", None, "customer"),  # the label names what it is
        ("Kundennummer", "DE123456789", None, "customer"),
        # an IBAN labelled as the person's is theirs, hidden on screen
        ("Ihre IBAN", "DE89 3704 0044 0532 0130 00", None, "account"),
        ("Ihre Bankverbindung", "DE89 3704 0044 0532 0130 00", None, "account"),
        ("Kontoinhaber IBAN", "DE89 3704 0044 0532 0130 00", None, "account"),
        ("IBAN des Zahlungspflichtigen", "DE89 3704 0044 0532 0130 00", None, "account"),
        ("Your IBAN", "DE89 3704 0044 0532 0130 00", None, "account"),
        # 3a. the organisation's own
        ("Amtsgericht", "Musterstadt HRB 31045", None, "register"),
        ("Amtsgericht/GnR", "Amtsgericht Musterstadt GnR 88", None, "register"),
        ("Handelsregister", "HRB 4711", None, "register"),
        ("", "HRB 4711", None, "register"),
        ("Vereinsregister", "VR 1234", None, "register"),
        ("Registergericht", "Amtsgericht Musterstadt VR 1234", None, "register"),
        # a register abbreviation in a case or order number is no register
        ("Vertragsnummer", "VR-2024-001", None, "contract"),
        ("Order", "VR-2024-1234", None, "order"),
        ("Bestellnummer", "PR-2024-1234", None, "order"),
        ("Kassenzeichen", "PR 2024 1234", None, "payment_reference"),
        ("Az.", "VR 123/24", None, "case_file"),
        ("Geschäftszeichen", "II/3-4711 PR", None, "case_file"),
        ("Ticket", "PR 12", None, "reference"),
        ("Aktenzeichen", "HRB 12345", None, "case_file"),
        ("WEEE-Reg.-Nr.", "DE 00000000", None, "register"),
        ("Foundation register", "Berlin 3/GT-2011", None, "register"),
        ("BIC", "MUBKDEM1XXX", None, "bic"),
        ("Kontonummer", "1234567890", None, "their_other"),
        ("Kontonummer", "1234567890", BANK, "account"),
        ("Betriebsnummer", "12345678", None, "their_other"),
        (
            "Steuernummer",
            "212/5812/0048",
            Context(party_kind="retailer", doc_kind="invoice"),
            "their_tax_number",
        ),
        ("Versicherungsteuer-Nr.", "812/V/4471", Context(party_kind="insurer"), "their_tax_number"),
        # 3b. about you
        ("Steuernummer", "331/5012/4471", TAX_OFFICE, "tax_number"),
        ("St.-Nr.", "331/5012/4471", Context(party_kind="tax_office"), "tax_number"),
        ("Steuer-ID", "57 216 480 393", None, "tax_id"),
        ("Steuer-IdNr.", "86095742719", None, "tax_id"),
        ("Steuer-ID", "8609574271", None, "tax_id"),  # too short: still a Steuer-ID, and it fails its check
        ("Identifikationsnummer", "86095742719", None, "tax_id"),
        ("Identifikationsnummer", "4711", None, "other"),  # other offices number people too
        ("IdNr", "86095742719", None, "tax_id"),
        ("Steuerliche IdNr.", "86095742719", None, "tax_id"),
        ("St.-IdNr.", "86 095 742 719", None, "tax_id"),
        ("SV-Nummer", "65 140300 R 004", None, "social_insurance"),
        ("Rentenversicherungsnummer", "15 070649 C 103", None, "social_insurance"),
        ("Rentenversicherungs-Nr.", "15 070649 C 103", None, "social_insurance"),
        ("Versicherungsnummer", "15 070649 C 103", None, "social_insurance"),
        ("Versicherungs-Nr.", "15 070649 C 103", Context(party_kind="authority"), "social_insurance"),
        ("Versicherungs-Nr.", "PHV-4471-2290", Context(party_kind="insurer"), "policy"),
        ("Versicherungsnummer", "PHV-4471-2290", Context(party_kind="insurer"), "policy"),
        ("Versicherten-Nr.", "R482019375", Context(party_kind="health_insurer"), "health_insurance"),
        ("Krankenversichertennummer", "A123456780", None, "health_insurance"),
        ("KV-Nummer", "A123456780", None, "health_insurance"),
        ("Versicherungsnummer", "A123456780", Context(party_kind="health_insurer"), "health_insurance"),
        ("Versicherungsnummer", "A123456780", Context(party_kind="insurer"), "policy"),
        # someone else's number is not about you
        ("Identifikationsnummer des Kindes", "86095742719", AUTHORITY, "other"),
        ("Steuer-ID Ehegatte", "86095742719", TAX_OFFICE, "other"),
        ("Reisepass des Kindes", "C01X00T47", AUTHORITY, "other"),
        ("Kfz-Kennzeichen", "B-AB 1234", None, "vehicle"),
        ("Kennzeichen", "M-XY 99", None, "vehicle"),
        ("Matrikelnummer", "4711123", None, "student"),
        ("Matr.-Nr.", "4711123", None, "student"),
        ("Beitragsnummer", "512 345 678", BROADCASTER, "broadcasting_fee"),
        ("Beitragsnr.", "512 345 678", Context(party_kind="public_broadcaster"), "broadcasting_fee"),
        ("Beitragsnummer", "512 345 678", Context(party_kind="health_insurer"), "other"),
        (
            "Passport No.",
            "X1234567",
            Context(party_kind="authority", doc_kind="identity_document"),
            "passport",
        ),
        ("Reisepassnummer", "C01X00T47", None, "passport"),
        ("Personalausweisnummer", "L01X00T47", None, "id_card"),
        ("Ausweisnummer", "L01X00T47", AUTHORITY, "id_card"),
        ("Ausweisnummer", "BIB-0098812", Context(party_kind="other"), "member"),  # a library card
        ("Dokumentennummer", "Y00000001", Context(doc_kind="residence_permit"), "residence_permit"),
        # 3c. one matter
        ("Aktenzeichen", "32.2-AE-24-08815", None, "case_file"),
        ("Az.", "32.4-VW-2026-0184512", None, "case_file"),
        ("Geschäftsnummer", "26-4471902-0-3", None, "case_file"),
        ("Kassenzeichen", "5126 0184 5122", None, "payment_reference"),
        ("Rechnungs-Nr.", "TM-2026-0048213", None, "invoice"),
        ("Bestellnummer", "302-5512094", None, "order"),
        ("Auftragsnummer", "A-2024-5518290", None, "order"),
        ("Sendungsnummer", "RR123456785DE", None, "tracking"),
        ("Unser Zeichen", "BZ-S/2026/0917", None, "reference"),
        ("Vorgang", "BS-2026-99812", None, "reference"),
        ("Mediennummer", "30031 004 812", None, "reference"),
        # 3d. yours with this organisation
        ("Mandatsreferenz", "FN-88213407-01", None, "mandate"),
        ("Kundennummer", "FN-88213407", None, "customer"),
        ("Kunden-Nr.", "K-7719034", None, "customer"),
        ("Mieternummer", "12-0412-07", None, "customer"),
        ("Vertragsnummer", "MV-2025-0412", None, "contract"),
        ("Vertragskonto", "400123987", None, "contract"),
        ("Abonummer", "DT-2025-3304719", None, "contract"),
        ("Vers.-Nr.", "PHV 71-4471220", Context(party_kind="insurer"), "policy"),
        ("Mitgliedsnummer", "FW-10457", None, "member"),
        ("Benutzer-Nr.", "0481 1123 5", None, "member"),
        ("Personalnummer", "10482", None, "employee"),
        ("Zählernummer", "1EMH0012345678", None, "meter"),
        ("Marktlokation", "51238764017", None, "meter"),
        # 4. anything else
        ("Scholarship ID", "GTSF-2026-0317", None, "other"),
        ("Wohnungsnummer", "05-2-03", None, "other"),
    ],
)
def test_classification_policy(label: str, value: str, ctx: Context | None, kind: str | None) -> None:
    assert classify(label, value, ctx) == kind


def test_label_keys_fold_case_umlauts_and_marks() -> None:
    assert label_key("Kunden-Nr.") == "kundennr"
    assert label_key("Zählernummer") == "zaehlernummer"
    assert label_key("  Gläubiger-ID ") == "glaeubigerid"


@pytest.mark.parametrize(
    ("value", "number"),
    [
        ("4711123", True),
        ("K 2231 0917", True),
        ("SAMRIVERA2000", True),
        ("links", False),
        ("2. OG links", False),
    ],
)
def test_what_counts_as_a_number(value: str, number: bool) -> None:
    assert is_number(value) is number


@pytest.mark.parametrize(
    ("kind", "value", "display", "copy"),
    [
        ("tax_id", "57216480354", "57 216 480 354", "57216480354"),
        ("tax_id", "57 216 480 354", "57 216 480 354", "57216480354"),
        ("social_insurance", "65140300R005", "65 140300 R 005", "65140300R005"),
        ("health_insurance", "R 482019379", "R 482019379", "R482019379"),
        ("iban", "de89370400440532013000", "DE89 3704 0044 0532 0130 00", "DE89370400440532013000"),
        ("broadcasting_fee", "512 345 678", "512 345 678", "512345678"),
        ("customer", "K 2231 0917", "K 2231 0917", "K 2231 0917"),
        ("customer", "  FN-88213407 ", "FN-88213407", "FN-88213407"),
    ],
)
def test_display_and_copy(kind: str, value: str, display: str, copy: str) -> None:
    assert display_value(kind, value) == display
    assert copy_value(kind, value) == copy


# --------------------------------------------------------------------------------------------------
# the page, over a small ledger
# --------------------------------------------------------------------------------------------------

STAMP = "2026-01-01T08:00:00Z"


def _party(store: Store, pid: str, name: str, kind: str, **extra: Any) -> str:
    return store.add_party(id=pid, name=name, kind=kind, created_at=STAMP, updated_at=STAMP, **extra).id


def _letter(store: Store, label: str, **fields: Any) -> str:
    sender = fields.pop("sender", None)
    doc = store.add_document(
        sha256=hashlib.sha256(label.encode()).hexdigest(),
        filename=f"{label}.pdf",
        mime="application/pdf",
        file_path=f"files/{label}.pdf",
    )
    fields.setdefault("status", "processed")
    fields.setdefault("title", label)
    if sender is not None:
        fields["extraction"] = DocumentExtraction.model_validate(
            {
                "kind": fields.get("kind", "other"),
                "title": label,
                "summary": label,
                "explanation": label,
                "sender": sender,
            }
        )
    store.update_document(doc.id, **fields)
    return doc.id


def _refs(*pairs: tuple[str, str]) -> list[Identifier]:
    return [Identifier(label=label, value=value) for label, value in pairs]


@pytest.fixture
def ledger(store: Store) -> dict[str, str]:
    ids: dict[str, str] = {}
    store.save_profile({"name": "Sam Rivera", "iban": "DE89 3704 0044 0532 0130 00", "onboarded": True})
    ids["employer"] = _party(store, "pty_employer", "Muster Tech GmbH", "employer")
    ids["gym"] = _party(
        store, "pty_gym", "FitWell", "gym", phone="0123 889900", email="hallo@fitwell.example"
    )
    ids["ministry"] = _party(store, "pty_ministry", "Ministry of Interior", "authority")
    ids["city"] = _party(store, "pty_city", "Ordnungsamt", "authority")
    ids["shop"] = _party(store, "pty_shop", "TechMarkt", "retailer")
    ids["phone"] = _party(store, "pty_phone", "FunkNetz", "telecom")
    ids["abh"] = _party(store, "pty_abh", "Ausländerbehörde", "immigration_office")
    ids["fake"] = _party(store, "pty_fake", "Finanzamt Musterstadt (fake)", "tax_office")
    ids["bank"] = _party(store, "pty_bank", "Musterbank", "bank")

    ids["payslip_old"] = _letter(
        store,
        "payslip-july",
        kind="payslip",
        party_id=ids["employer"],
        doc_date="2026-07-31",
        references=_refs(("Steuer-ID", "57 216 480 354"), ("Personalnr.", "10482")),
    )
    ids["payslip"] = _letter(
        store,
        "payslip-august",
        kind="payslip",
        party_id=ids["employer"],
        doc_date="2026-08-31",
        references=_refs(
            ("Steuerliche Identifikationsnummer", "57216480354"), ("SV-Nummer", "65 140300 R 004")
        ),
        sender={
            "name": "Muster Tech GmbH",
            "kind": "employer",
            "identifiers": [{"label": "USt-IdNr.", "value": "DE424242072"}],
        },
    )
    ids["gym_contract"] = _letter(
        store,
        "gym",
        kind="contract",
        party_id=ids["gym"],
        doc_date="2025-01-02",
        references=_refs(("Mitgliedsnummer", "FW-10457"), ("Gläubiger-ID", "DE25ZZZ00000104570")),
        payment={"iban": "DE05123467000029900150", "payee": "FitWell Studios GmbH", "iban_valid": True},
    )
    ids["passport"] = _letter(
        store,
        "passport",
        kind="identity_document",
        party_id=ids["ministry"],
        references=_refs(("Passport No.", "X1234567")),
    )
    ids["passport_expiry"] = store.add_item(
        kind="expiry",
        title="Passport expires",
        due_date="2027-02-10",
        doc_id=ids["passport"],
        party_id=ids["ministry"],
        area="residence",
    ).id
    ids["permit_letter"] = _letter(
        store,
        "permit",
        kind="residence_permit",
        party_id=ids["abh"],
        doc_date="2026-09-16",
        references=_refs(("Aktenzeichen", "32.2-AE-24-08815")),
    )
    ids["permit_case"] = store.add_case(title="Residence permit extension", party_id=ids["abh"]).id
    store.update_document(ids["permit_letter"], case_id=ids["permit_case"])
    ids["permit_expiry"] = store.add_item(
        kind="expiry",
        title="Residence permit (Aufenthaltserlaubnis) expires",
        due_date="2026-11-30",
        doc_id=ids["permit_letter"],
        case_id=ids["permit_case"],
        area="residence",
    ).id
    ids["appointment"] = store.add_item(
        kind="appointment",
        title="Appointment at the Ausländerbehörde",
        due_date="2026-10-14",
        doc_id=ids["permit_letter"],
        case_id=ids["permit_case"],
        party_id=ids["abh"],
    ).id

    ids["fine"] = _letter(
        store,
        "fine",
        kind="fine",
        party_id=ids["city"],
        doc_date="2026-09-23",
        references=_refs(("Aktenzeichen", "32.4-VW-2026-0184512"), ("Kassenzeichen", "5126 0184 5122")),
    )
    ids["fine_payment"] = store.add_item(
        kind="payment",
        title="Pay the fine",
        due_date="2026-10-02",
        amount=30.0,
        doc_id=ids["fine"],
        party_id=ids["city"],
    ).id
    ids["invoice"] = _letter(
        store,
        "invoice",
        kind="invoice",
        party_id=ids["shop"],
        doc_date="2026-08-20",
        references=_refs(
            ("Rechnungs-Nr.", "TM-2026-0048213"),
            ("Kundennummer", "K-7719034"),
            ("Steuernummer", "212/5812/0048"),
        ),
    )
    store.add_item(
        kind="payment",
        title="Pay the invoice",
        due_date="2026-09-03",
        amount=89.99,
        doc_id=ids["invoice"],
        status="done",
    )
    ids["order"] = _letter(
        store,
        "phone-contract",
        kind="contract",
        party_id=ids["phone"],
        doc_date="2024-11-12",
        references=_refs(("Auftragsnummer", "A-2024-5518290"), ("Kundennummer", "FN-88213407")),
    )
    store.add_item(
        kind="payment",
        title="Monthly fee",
        due_date="2026-10-01",
        amount=34.99,
        doc_id=ids["order"],
        recurrence={"interval": 1, "unit": "months"},
    )
    ids["scam"] = _letter(
        store,
        "scam",
        kind="tax_letter",
        party_id=ids["fake"],
        hidden_text=True,
        references=_refs(("Steuer-ID", "86095742719"), ("Aktenzeichen", "BS-2026-99812")),
    )
    store.add_item(
        kind="payment", title="Pay the fake tax", due_date="2026-10-01", amount=500.0, doc_id=ids["scam"]
    )
    ids["bank_letter"] = _letter(
        store,
        "bank",
        kind="bank_letter",
        party_id=ids["bank"],
        doc_date="2026-09-18",
        references=_refs(
            ("Kundennummer", "7004 1128"),
            ("IBAN", "DE89 3704 0044 0532 0130 00"),
            ("Kontonummer", "0532013000"),
        ),
    )
    ids["private"] = _letter(
        store,
        "private",
        kind="university",
        party_id=ids["employer"],
        ai_private=True,
        doc_date="2026-03-01",
        references=_refs(("Matrikelnummer", "4711123")),
    )
    ids["trashed"] = _letter(
        store,
        "trashed",
        kind="university",
        party_id=ids["employer"],
        doc_date="2026-09-20",
        references=_refs(("Matrikelnummer", "9999999")),
    )
    store.update_document(ids["trashed"], deleted_at="2026-09-01T08:00:00Z")
    return ids


def _numbers(store: Store, **kw: Any) -> Any:
    return my_numbers(store, TODAY, **kw)


def test_about_you_lists_personal_numbers_once_with_their_check(store: Store, ledger: dict[str, str]) -> None:
    page = _numbers(store)
    about = {n.kind: n for n in page.about_you}
    assert set(about) == {"tax_id", "social_insurance", "student"}
    tax = about["tax_id"]
    assert (tax.display, tax.copy_value, tax.check, tax.letters) == ("57 216 480 354", "57216480354", "ok", 2)
    # the latest letter that shows it, and its label
    assert tax.letter is not None and tax.letter.id == ledger["payslip"]
    assert tax.label == "Steuerliche Identifikationsnummer"
    sv = about["social_insurance"]
    assert sv.check == "fails" and sv.check_note and "compare it with the letter" in sv.check_note
    # a letter with scam signs gives nothing, a trashed one nothing; a private one only on screen
    assert all(n.value not in ("86095742719", "9999999") for n in page.about_you)
    assert about["student"].letter is not None and about["student"].letter.id == ledger["private"]
    assert "student" not in {n.kind for n in _numbers(store, shareable_only=True).about_you}


def test_identity_documents_carry_their_number_and_expiry(store: Store, ledger: dict[str, str]) -> None:
    page = _numbers(store)
    docs = {d.kind: d for d in page.documents}
    assert set(docs) == {"passport", "residence_permit"}
    passport = docs["passport"]
    assert passport.number is not None and passport.number.value == "X1234567"
    assert (passport.valid_until, passport.status, passport.item_id) == (
        "2027-02-10",
        "renew_soon",
        ledger["passport_expiry"],
    )
    permit = docs["residence_permit"]
    assert permit.number is None and permit.valid_until == "2026-11-30" and permit.status == "renew_soon"
    assert permit.note == RESIDENCE_EXTENSION_NOTE
    assert "§ 81 Abs. 4 S. 1 AufenthG" in permit.note and "Fiktionsbescheinigung" in permit.note


def test_an_expired_permit_is_never_told_to_apply_before_it_expires(
    store: Store, ledger: dict[str, str]
) -> None:
    """§ 81 Abs. 4 AufenthG: an application in time keeps the permit in force (S. 1); after a late one
    only the office can order that, to avoid undue hardship (S. 3)."""
    store.update_item(ledger["permit_expiry"], due_date="2026-09-20")
    (permit,) = [d for d in _numbers(store).documents if d.kind == "residence_permit"]
    assert permit.status == "expired" and permit.note == RESIDENCE_EXPIRED_NOTE
    assert "before it expires" not in permit.note
    assert "§ 81 Abs. 4 S. 3 AufenthG" in permit.note and "Ausländerbehörde" in permit.note


def test_an_expiry_date_read_by_ai_says_so(store: Store, ledger: dict[str, str]) -> None:
    store.update_item(ledger["passport_expiry"], grounding="model_read")
    (passport,) = [d for d in _numbers(store).documents if d.kind == "passport"]
    assert passport.needs_check is True
    store.update_item(ledger["passport_expiry"], grounding="user")  # "Looks right"
    (passport,) = [d for d in _numbers(store).documents if d.kind == "passport"]
    assert passport.needs_check is False


@pytest.mark.parametrize(
    ("title", "doc_kind", "shown"),
    [
        ("Bibliotheksausweis läuft ab", "other", False),
        ("Studierendenausweis gültig bis", "university", False),
        ("Student ID card expires", "university", False),
        ("Visa card expires", "bank_letter", False),
        ("Reisepass läuft ab", "other", True),
        ("Visa expires", "other", True),
        ("Ausweis expires", "identity_document", True),
    ],
)
def test_only_identity_documents_and_residence_titles_are_documents(
    store: Store, ledger: dict[str, str], title: str, doc_kind: str, shown: bool
) -> None:
    letter = _letter(store, f"card-{title}", kind=doc_kind, doc_date="2026-09-01")
    item = store.add_item(kind="expiry", title=title, due_date="2027-01-31", doc_id=letter).id
    assert (item in {d.item_id for d in _numbers(store).documents}) is shown


@pytest.mark.parametrize(
    ("expiry", "status"),
    [("2026-09-27", "expired"), ("2026-12-27", "renew_soon"), ("2026-12-28", "ok")],
)
def test_a_permit_is_due_for_renewal_90_days_ahead(
    store: Store, ledger: dict[str, str], expiry: str, status: str
) -> None:
    store.update_item(ledger["permit_expiry"], due_date=expiry)
    (permit,) = [d for d in _numbers(store).documents if d.kind == "residence_permit"]
    assert permit.status == status


def test_an_identity_number_without_an_expiry_is_still_listed(store: Store, ledger: dict[str, str]) -> None:
    store.delete_item(ledger["passport_expiry"])
    (passport,) = [d for d in _numbers(store).documents if d.kind == "passport"]
    assert passport.number is not None and passport.valid_until is None and passport.status == "unknown"


def test_call_sheets(store: Store, ledger: dict[str, str]) -> None:
    sheets = {s.name: s for s in _numbers(store).organisations}
    # the ministry that issued the passport is no one to call; the scam sender gets no sheet
    assert "Ministry of Interior" not in sheets and "Finanzamt Musterstadt (fake)" not in sheets
    assert list(sheets) == sorted(sheets, key=str.casefold)
    gym = sheets["FitWell"]
    assert (gym.phone, gym.email) == ("0123 889900", "hallo@fitwell.example")
    assert [(n.kind, n.value) for n in gym.numbers] == [("member", "FW-10457")]
    assert [(n.kind, n.check) for n in gym.their_numbers] == [("creditor_id", "none"), ("iban", "ok")]
    assert gym.their_numbers[1].label == "IBAN for payments to FitWell Studios GmbH"
    employer = sheets["Muster Tech GmbH"]
    assert {n.kind for n in employer.numbers} == {"tax_id", "social_insurance", "employee", "student"}
    assert [n.kind for n in employer.their_numbers] == ["vat_id"]
    assert employer.last_letter is not None and employer.last_letter.id == ledger["payslip"]
    shop = sheets["TechMarkt"]
    assert [n.kind for n in shop.their_numbers] == ["their_tax_number"]  # an invoice prints the seller's
    # the Ausländerbehörde has no number of yours, but an open case
    abh = sheets["Ausländerbehörde"]
    assert abh.numbers == [] and [c.title for c in abh.open_cases] == ["Residence permit extension"]
    # at a bank an account number is yours; your own IBAN is in your profile, not here
    bank = sheets["Musterbank"]
    assert [(n.kind, n.value) for n in bank.numbers] == [("customer", "7004 1128"), ("account", "0532013000")]


def test_open_cases_while_a_one_off_to_do_is_open(store: Store, ledger: dict[str, str]) -> None:
    cases = _numbers(store).open_cases
    by_title = {c.title: c for c in cases}
    # the invoice is paid, the phone order has only a recurring fee: neither is an open case
    assert set(by_title) == {"Residence permit extension", "fine"}
    fine = by_title["fine"]
    assert fine.case_id is None and fine.letter is not None and fine.letter.id == ledger["fine"]
    assert [(r.kind, r.value) for r in fine.references] == [
        ("case_file", "32.4-VW-2026-0184512"),
        ("payment_reference", "5126 0184 5122"),
    ]
    assert fine.next_item is not None and fine.next_item.id == ledger["fine_payment"]
    assert [c.title for c in cases] == ["fine", "Residence permit extension"]  # the next step first
    permit = by_title["Residence permit extension"]
    assert permit.next_item is not None and permit.next_item.kind == "appointment"
    store.update_item(ledger["fine_payment"], status="done")
    assert "fine" not in {c.title for c in _numbers(store).open_cases}


def test_a_to_do_added_to_a_letter_of_the_thread_keeps_the_case_open(
    store: Store, ledger: dict[str, str]
) -> None:
    """POST /api/items takes a letter and an optional thread: a to-do with only the letter still belongs
    to the letter's thread."""
    for item in store.list_items():
        if item.case_id == ledger["permit_case"] and item.kind == "appointment":
            store.update_item(item.id, status="done")
    assert "Residence permit extension" not in {c.title for c in _numbers(store).open_cases}
    added = store.add_item(
        kind="task", title="Bring the biometric photo", due_date="2026-10-10", doc_id=ledger["permit_letter"]
    ).id
    (case,) = [c for c in _numbers(store).open_cases if c.title == "Residence permit extension"]
    assert case.next_item is not None and case.next_item.id == added


def test_a_fee_paid_at_the_appointment_is_no_transfer(store: Store, ledger: dict[str, str]) -> None:
    """The fee is paid on site on the appointment's day: no transfer day, and the appointment first."""
    fee = store.add_item(
        kind="payment",
        title="Fee for the extension",
        due_date="2026-10-14",
        due_time="10:30",
        send_by="2026-10-13",
        amount=100.0,
        doc_id=ledger["permit_letter"],
        case_id=ledger["permit_case"],
    ).id
    (case,) = [c for c in _numbers(store).open_cases if c.title == "Residence permit extension"]
    assert case.next_item is not None and case.next_item.id == ledger["appointment"]
    store.update_item(ledger["appointment"], kind="task")
    (case,) = [c for c in _numbers(store).open_cases if c.title == "Residence permit extension"]
    # without an appointment that day the fee is a transfer: its send-by day counts
    assert case.next_item is not None and (case.next_item.id, case.next_item.send_by) == (fee, "2026-10-13")


def test_an_unconfirmed_next_step_says_so(store: Store, ledger: dict[str, str]) -> None:
    store.update_item(ledger["fine_payment"], grounding="unverified")
    (fine,) = [c for c in _numbers(store).open_cases if c.title == "fine"]
    assert fine.next_item is not None and fine.next_item.needs_check is True
    store.update_item(ledger["fine_payment"], grounding="user")
    (fine,) = [c for c in _numbers(store).open_cases if c.title == "fine"]
    assert fine.next_item is not None and fine.next_item.needs_check is False


def test_a_misread_payment_iban_does_not_check_and_is_never_one_of_yours(store: Store) -> None:
    """The IBAN a letter gives for payment is where to pay the sender, whatever the payee is called — also
    when a digit was misread, which its check then reports."""
    insurer = _party(store, "pty_insurer", "Allianz Versicherungs-AG", "insurer")
    customer = _party(store, "pty_kunden", "Kundenservice Zahlungen GmbH", "company")
    _letter(
        store,
        "insurance-bill",
        kind="insurance",
        party_id=insurer,
        references=_refs(("Versicherungsnummer", "AS-123456")),
        payment={"iban": "DE89370400440532013001", "payee": "Allianz Versicherungs-AG", "iban_valid": False},
    )
    _letter(
        store,
        "service-bill",
        kind="invoice",
        party_id=customer,
        references=_refs(("Kundennummer", "K-1")),
        payment={"iban": "DE89370400440532013000", "payee": "Kundenservice Zahlungen GmbH"},
    )
    sheets = {s.name: s for s in _numbers(store).organisations}
    allianz = sheets["Allianz Versicherungs-AG"]
    assert [(n.kind, n.value) for n in allianz.numbers] == [("policy", "AS-123456")]
    (iban,) = allianz.their_numbers
    assert (iban.kind, iban.check) == ("iban", "fails")
    assert iban.check_note is not None and "Compare it with the letter" in iban.check_note
    service = sheets["Kundenservice Zahlungen GmbH"]
    assert [n.kind for n in service.their_numbers] == ["iban"]  # "Kunden…" in the payee is no label


def test_the_persons_own_payment_iban_stays_in_the_profile(store: Store) -> None:
    store.save_profile({"name": "Sam", "iban": "DE89 3704 0044 0532 0130 00", "onboarded": True})
    refund = _party(store, "pty_refund", "Finanzamt", "tax_office")
    _letter(
        store,
        "refund",
        kind="tax_assessment",
        party_id=refund,
        references=_refs(("Steuernummer", "331/5012/4471")),
        payment={"iban": "DE89370400440532013000", "payee": "Sam Rivera"},
    )
    (sheet,) = _numbers(store).organisations
    assert [n.kind for n in sheet.numbers] == ["tax_number"] and sheet.their_numbers == []


# --------------------------------------------------------------------------------------------------
# the demo's own numbers
# --------------------------------------------------------------------------------------------------


@pytest.fixture
def demo_store(tmp_path: Path) -> Iterator[Store]:
    data = tmp_path / "demo"
    shutil.copytree(DEMO_DB, data)
    opened = Store.open(Paths(data))
    yield opened
    opened.close()


def test_the_demo_numbers(demo_store: Store) -> None:
    page = my_numbers(demo_store, TODAY)
    about = {n.kind: (n.label, n.value, n.check, n.party_name) for n in page.about_you}
    assert about == {
        # A known defect of the sample life, pinned until the demo is re-recorded: scripts/samplelife/
        # persona.py prints numbers whose check digits fail (as a misread would). The fix is the
        # integrator's — give the persona 57 216 480 354, 65 140300 R 005 and R482019379 (the static
        # demo's numbers), re-render the samples and re-record the fixtures, then pin "ok" here.
        "tax_id": ("Steuer-ID", "57 216 480 393", "fails", "Muster Tech GmbH"),
        "social_insurance": ("SV-Nummer", "65 140300 R 004", "fails", "Muster Tech GmbH"),
        "health_insurance": ("Versicherten-Nr.", "R482019375", "fails", "Muster BKK"),
        "student": ("Matrikelnummer", "4711123", "none", "Hochschule Musterstadt"),
        "broadcasting_fee": ("Beitragsnummer", "512 345 678", "none", "Beitragsservice Musterstadt"),
    }
    docs = {d.kind: d for d in page.documents}
    assert docs["passport"].number is not None and docs["passport"].number.value == "X1234567"
    assert (docs["passport"].valid_until, docs["residence_permit"].valid_until) == (
        "2027-02-10",
        "2026-11-30",
    )
    sheets = {s.name: s for s in page.organisations}
    # the passport no longer hangs under the "Ministry of Interior"
    assert "Ministry of Interior" not in sheets
    stadtwerke = sheets["Stadtwerke Musterstadt GmbH"]
    assert {n.label for n in stadtwerke.numbers} == {
        "Kundennummer",
        "Vertragskonto",
        "Zählernummer",
        "Marktlokation",
    }
    assert {n.kind for n in stadtwerke.their_numbers} == {"vat_id", "register", "creditor_id"}
    cases = {c.party_name: sorted(r.value for r in c.references) for c in page.open_cases}
    assert cases["Stadt Musterstadt – Ordnungsamt (Bußgeldstelle)"] == [
        "32.4-VW-2026-0184512",
        "5126 0184 5122",
    ]
    assert cases["Stadt Musterstadt – Ausländerbehörde"] == ["32.2-AE-24-08815"]
    assert "FunkNetz Mobil GmbH" not in cases  # a 2024 order number of a running contract is no open case


# --------------------------------------------------------------------------------------------------
# the endpoint
# --------------------------------------------------------------------------------------------------


async def test_get_numbers(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        store = api.ctx.store
        party = _party(store, "pty_uni", "Hochschule", "university", phone="0123 7788")
        _letter(
            store, "uni", kind="university", party_id=party, references=_refs(("Matrikelnummer", "4711123"))
        )
        response = await api.client.get("/api/numbers")
        assert response.status_code == 200
        body = response.json()
        assert body["today"] == "2026-09-28"
        assert [(n["kind"], n["copy_value"], n["check"]) for n in body["about_you"]] == [
            ("student", "4711123", "none")
        ]
        (sheet,) = body["organisations"]
        assert (sheet["name"], sheet["phone"], sheet["numbers"][0]["name"]) == (
            "Hochschule",
            "0123 7788",
            "Student number (Matrikelnummer)",
        )
