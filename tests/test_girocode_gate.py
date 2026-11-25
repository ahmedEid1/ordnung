"""The GiroCode gate (ordnung.secretary.girocode_gate): every reason a payment gets no code, in the
policy's order, the grounding of each value, and — on a real store — known senders, an attacker's
IBAN with valid check digits, photo letters, the person's comparison with the paper letter, and the
first payment to a payee and IBAN, which always waits for that comparison."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from fixtures_llm import iban as make_iban
from helpers_secretary import add_doc, add_item
from helpers_store import seed_database
from helpers_tables import check_rows
from ordnung.api.routes.items import ItemPatch, _confirm, _update
from ordnung.config import Paths
from ordnung.db.store import Store
from ordnung.models import (
    Evidence,
    GiroCodeBlocked,
    GiroCodeReady,
    Identifier,
    Item,
    Page,
    PaymentDetails,
    TransferValues,
)
from ordnung.secretary import household
from ordnung.secretary.girocode_gate import (
    CHECKED,
    CheckRefused,
    ScamSign,
    TransferFacts,
    amount_grounding,
    compared_accounts,
    decide,
    document_girocodes,
    item_girocode,
    known_iban,
    record_check,
    same_values,
    value_grounding,
)
from ordnung.secretary.triggers import Ledger

TODAY = date(2026, 9, 28)
KNOWN_IBAN = make_iban("DE", "100100100123456789")
ATTACKER_IBAN = make_iban("DE", "700700700555444333")  # valid check digits, another account
PAYLOAD = "BCD\n002\n1\nSCT\n\nMuster Telecom GmbH\n{iban}\nEUR49.99\n\n\nR-2026-0815"


def ready_facts(**changes: Any) -> TransferFacts:
    """A payment every point of the policy lets through (all values from the letter's text layer)."""
    facts = TransferFacts(
        item_id="itm_1",
        party="Muster Telecom GmbH",
        amount=49.99,
        amount_grounding="verified",
        payee="Muster Telecom GmbH",
        iban=KNOWN_IBAN,
        iban_grounding="verified",
        reference="R-2026-0815",
        reference_grounding="verified",
        known_account=True,
    )
    return replace(facts, **changes)


def blocked(facts: TransferFacts) -> GiroCodeBlocked:
    code = decide(facts)
    assert isinstance(code, GiroCodeBlocked), code
    return code


# --------------------------------------------------------------------------------------------------
# The policy, point by point (pure)
# --------------------------------------------------------------------------------------------------


def test_a_grounded_transfer_gets_its_payload() -> None:
    code = decide(ready_facts())
    assert code == GiroCodeReady(item_id="itm_1", payload=PAYLOAD.format(iban=KNOWN_IBAN), checked=False)


def test_a_payment_without_a_reference_gets_a_code_without_one() -> None:
    """Nothing to ground, nothing to invent: both remittance elements stay empty (and are trimmed, as
    the standard allows). The Pay panel reads that off the payload and says to add the letter's
    reference, if it names one, in the banking app (``GIROCODE_NO_REFERENCE``)."""
    code = decide(ready_facts(reference=None, reference_grounding="unverified"))
    assert isinstance(code, GiroCodeReady)
    assert code.payload == f"BCD\n002\n1\nSCT\n\nMuster Telecom GmbH\n{KNOWN_IBAN}\nEUR49.99"


REASONS_FOR_NO_CODE = [
    ({"incoming": True}, "incoming", "No code: this is money coming to you."),
    (
        {"direct_debit": True},
        "direct_debit",
        "No code: Muster Telecom GmbH collects this by direct debit — there is nothing to transfer.",
    ),
    (
        {"direct_debit": True, "party": None},
        "direct_debit",
        "No code: the sender collects this by direct debit — there is nothing to transfer.",
    ),
    (
        {"debit_in_letter": True},
        "direct_debit",
        "No code: the letter says this is collected by direct debit (Lastschrift)",
    ),
    ({"trashed": True}, "settled", "No code: this letter is in the trash."),
    ({"status": "done"}, "settled", "No code: you marked this as paid."),
    ({"status": "dismissed"}, "settled", "No code: you set this to-do aside."),
    (
        {"replaced_by": "Zahlungserinnerung"},
        "replaced",
        "No code: the payment reminder “Zahlungserinnerung” took over this payment — pay once",
    ),
    (
        {"attached_bill": "Rechnung September"},
        "replaced",
        "No code: the bill attached to this e-mail, “Rechnung September”, asks for this payment — pay once",
    ),
    ({"other_transfers": 1}, "several", "No code: this letter asks for more than one payment"),
    ({"currency": "CHF"}, "currency", "No code: GiroCodes are for euro transfers, and this is in CHF."),
    ({"amount": None}, "no_amount", "No code: the letter doesn't say how much to pay."),
    ({"iban": None}, "no_iban", "No code: the letter gives no IBAN to transfer to."),
    ({"payee": " \n"}, "no_payee", "No code: the letter doesn't name the account holder to pay."),
    ({"payee": None}, "no_payee", "No code: the letter doesn't name the account holder to pay."),
]


def test_each_reason_for_no_code() -> None:
    def check(changes: dict[str, Any], reason: str, message: str) -> None:
        code = blocked(ready_facts(**changes))
        assert code.reason == reason
        assert code.message.startswith(message)
        assert code.to_check == [] and code.values is None

    check_rows(REASONS_FOR_NO_CODE, check)


STATUSES_STILL_TO_PAY = ["open", "snoozed", "missed"]


def test_open_snoozed_and_missed_payments_are_still_to_pay() -> None:
    def check(status: str) -> None:
        assert isinstance(decide(ready_facts(status=status)), GiroCodeReady)

    check_rows(STATUSES_STILL_TO_PAY, check)


def test_an_iban_failing_its_check_digits_says_why_and_what_to_do() -> None:
    code = blocked(ready_facts(iban=KNOWN_IBAN[:-1] + ("0" if KNOWN_IBAN[-1] != "0" else "1")))
    assert code.reason == "invalid_iban"
    assert "is not a valid IBAN. The check digits do not match" in code.message
    assert code.message.endswith("compare it with the letter and ask the sender before paying.")


def test_the_standards_limits_are_reasons_too() -> None:
    swiss = blocked(ready_facts(iban=make_iban("CH", "00762011623852957")))
    assert swiss.reason == "invalid"
    assert swiss.message == (
        "No code: an account in Switzerland is outside the European Economic Area (the EU, Iceland, "
        "Liechtenstein and Norway), so the GiroCode would need its bank's BIC. Copy the details by hand."
    )
    rf = blocked(ready_facts(reference="RF19 5390 0754 7034"))
    assert rf.reason == "invalid" and "check digits don't match" in rf.message
    assert blocked(ready_facts(payee="x" * 71)).reason == "invalid"
    assert isinstance(decide(ready_facts(reference="RF18 5390 0754 7034")), GiroCodeReady)


BUILDER_REFUSALS = [
    ({"amount": 0.001}, "No code: a GiroCode carries amounts from €0.01 to €999,999,999.99."),
    ({"reference": "x" * 141}, "No code: the reference is longer than the 140 characters"),
    ({"payee": "x" * 71}, "No code: the payee's name is longer than the 70 characters"),
    ({"reference": "RF19 5390 0754 7034"}, "No code: the reference RF19 5390 0754 7034 looks like"),
]


def test_the_builders_refusals_read_on_after_no_code_and_say_what_to_do() -> None:
    def check(changes: dict[str, Any], message: str) -> None:
        code = blocked(ready_facts(**changes))
        assert code.reason == "invalid"
        assert code.message.startswith(message)
        assert code.message.endswith(" Copy the details by hand.")

    check_rows(BUILDER_REFUSALS, check)


SCAM_SIGNS_AND_THEIR_WORDS = [
    (
        ScamSign("iban_changed", party="Beitragsservice Musterstadt"),
        "No code: this IBAN is not the one Beitragsservice Musterstadt used before. Check with them "
        "using contact details you already have, not the ones in this letter.",
    ),
    (
        ScamSign(
            "similar_party_iban",
            party="Rundfunk Zahlungszentrale",
            look_alike="Beitragsservice Musterstadt",
        ),
        "No code: “Beitragsservice Musterstadt”, whose name is like this sender's, used another IBAN "
        "before. Check who sent this letter first, using contact details you already have.",
    ),
    (
        ScamSign("payee_changed", party="Muster Telecom GmbH", payee="M. Mustermann"),
        "No code: the money would go to “M. Mustermann”, but payments to Muster Telecom GmbH went to "
        "someone else before.",
    ),
    (ScamSign("other"), "No code: this letter shows signs of a scam."),
]


def test_a_scam_sign_blocks_with_its_own_words() -> None:
    def check(sign: ScamSign, message: str) -> None:
        code = blocked(ready_facts(scam=sign))
        assert code.reason == "scam" and code.message.startswith(message)

    check_rows(SCAM_SIGNS_AND_THEIR_WORDS, check)


def test_scam_signs_come_before_every_other_reason_but_not_to_pay() -> None:
    """A scam letter says so even when it also asks for several payments or was read from a photo."""
    sign = ScamSign("iban_changed", party="Beitragsservice Musterstadt")
    for changes in (
        {"other_transfers": 2},
        {"replaced_by": "Mahnung"},
        {"amount_grounding": "model_read", "iban_grounding": "model_read"},
        {"iban": "DE00"},
        {"amount": None},
    ):
        assert blocked(ready_facts(scam=sign, **changes)).reason == "scam"
    # nothing to pay any more: no scam advice needed
    assert blocked(ready_facts(scam=sign, status="done")).reason == "settled"


def test_values_read_from_a_photo_need_the_paper_letter_first() -> None:
    facts = ready_facts(
        amount_grounding="model_read", iban_grounding="model_read", reference_grounding="model_read"
    )
    code = blocked(facts)
    assert code.reason == "check_letter"
    assert code.message == (
        "No code yet: the amount, the IBAN and the reference were read by AI from a photo. Compare them "
        "with the paper letter, then confirm."
    )
    assert code.to_check == ["amount", "iban", "reference"]
    assert code.values == TransferValues(
        payee="Muster Telecom GmbH", iban=KNOWN_IBAN, reference="R-2026-0815", amount=49.99
    )


def test_the_check_message_names_only_what_to_compare_and_why() -> None:
    # a PDF's value not found in its text: its pages are the letter — there is no paper to compare with
    one = blocked(ready_facts(reference_grounding="unverified"))
    assert one.to_check == ["reference"]
    assert one.message == (
        "No code yet: the reference wasn't found in the letter's text. Compare it with the letter, then confirm."
    )
    assert "paper" not in blocked(ready_facts(amount_grounding="unverified")).message
    mixed = blocked(ready_facts(iban_grounding="model_read", amount_grounding="unverified"))
    assert mixed.to_check == ["amount", "iban"]
    assert mixed.message == (
        "No code yet: the IBAN was read by AI from a photo and the amount wasn't found in the letter's "
        "text. Compare them with the paper letter, then confirm."
    )
    # no reference: nothing to compare there
    assert blocked(ready_facts(reference=None, amount_grounding="model_read")).to_check == ["amount"]


def test_the_persons_check_unlocks_the_code_only_for_the_values_they_saw() -> None:
    photo = ready_facts(
        amount_grounding="model_read", iban_grounding="model_read", reference_grounding="model_read"
    )
    seen = photo.values
    ready = decide(replace(photo, checked=seen))
    assert isinstance(ready, GiroCodeReady) and ready.checked
    # spacing and case of what was seen don't matter …
    spaced = TransferValues(
        payee=" Muster  Telecom GmbH",
        iban=" ".join(KNOWN_IBAN[i : i + 4] for i in range(0, 22, 4)).lower(),
        reference="R-2026-0815 ",
        amount=49.990000001,
    )
    assert isinstance(decide(replace(photo, checked=spaced)), GiroCodeReady)
    # … any other value does: the letter was read again, or the amount was changed
    for changed in (
        {"iban": ATTACKER_IBAN},
        {"amount": 59.99},
        {"reference": "R-2026-0816"},
        {"payee": "Muster Telecom"},
    ):
        assert blocked(replace(photo, checked=seen, **changed)).reason == "check_letter"


def test_same_values_compares_the_payment_not_its_spelling() -> None:
    a = TransferValues(payee="A B", iban=KNOWN_IBAN, reference="X 1", amount=1.0)
    assert same_values(
        a, TransferValues(payee="A\nB", iban=KNOWN_IBAN.lower(), reference=" X  1", amount=1.001)
    )
    assert not same_values(a, a.model_copy(update={"amount": 1.01}))
    assert not same_values(a, a.model_copy(update={"amount": None}))


def test_the_first_payment_to_an_account_waits_for_the_comparison_however_well_grounded() -> None:
    """A text layer can say what the page doesn't show, so grounding alone never makes the first code
    to an IBAN: the person compares every value with the letter once, then the code is ready."""
    first = ready_facts(known_account=False)
    code = blocked(first)
    assert code.reason == "check_letter" and code.first_payment
    assert code.message == (
        "No code yet: you haven't compared a payment to this payee and IBAN with a letter from this sender "
        "before. Compare the payee, IBAN, amount and reference with the letter, then confirm."
    )
    # every value is grounded: nothing to name as not found, all four to compare
    assert code.to_check == []
    assert code.values == first.values
    ready = decide(replace(first, checked=first.values))
    assert ready == GiroCodeReady(item_id="itm_1", payload=PAYLOAD.format(iban=KNOWN_IBAN), checked=True)
    # the comparison holds for the values seen, as any other
    assert blocked(replace(first, checked=first.values, amount=59.99)).first_payment
    # a known account goes as before: nothing to compare, nothing said about a comparison
    assert decide(ready_facts()) == GiroCodeReady(
        item_id="itm_1", payload=PAYLOAD.format(iban=KNOWN_IBAN), checked=False
    )


def test_the_first_payment_message_names_what_else_is_missing() -> None:
    photo = blocked(
        ready_facts(
            known_account=False,
            amount_grounding="model_read",
            iban_grounding="model_read",
            reference_grounding="model_read",
        )
    )
    assert photo.first_payment and photo.to_check == ["amount", "iban", "reference"]
    assert photo.message == (
        "No code yet: you haven't compared a payment to this payee and IBAN with a letter from this sender "
        "before, and the amount, the IBAN and the reference were read by AI from a photo. Compare the payee, "
        "IBAN, amount and reference with the paper letter, then confirm."
    )
    no_reference = blocked(ready_facts(known_account=False, reference=None, party=None))
    assert no_reference.message == (
        "No code yet: you haven't compared a payment to this payee and IBAN with a letter before. Compare "
        "the payee, IBAN and amount with the letter, then confirm."
    )
    # a known account's check message stays as it was
    assert not blocked(ready_facts(amount_grounding="unverified")).first_payment


def test_every_earlier_reason_comes_before_the_first_payment() -> None:
    """The comparison is offered only for a code the policy would otherwise give: a scam letter, a
    payment set aside or one that can't be a code says so, and never asks to compare."""
    for changes, reason in (
        ({"scam": ScamSign("iban_changed", party="Beitragsservice Musterstadt")}, "scam"),
        ({"status": "done"}, "settled"),
        ({"other_transfers": 1}, "several"),
        ({"iban": None}, "no_iban"),
        ({"currency": "CHF"}, "currency"),
    ):
        code = blocked(ready_facts(known_account=False, **changes))
        assert code.reason == reason and not code.first_payment and code.values is None


# --------------------------------------------------------------------------------------------------
# Grounding
# --------------------------------------------------------------------------------------------------


def page(text: str, source: str = "text", number: int = 1) -> Page:
    return Page(
        doc_id="doc_x", page=number, width=100, height=100, image_path="p.jpg", text=text, text_source=source
    )


def test_a_value_printed_in_the_text_layer_is_verified_in_a_transcript_model_read() -> None:
    printed = f"IBAN: {' '.join(KNOWN_IBAN[i : i + 4] for i in range(0, 22, 4))}\nBIC: MUSTDEXX"
    assert value_grounding(KNOWN_IBAN, [page(printed)]) == "verified"
    assert value_grounding(KNOWN_IBAN, [page(printed, "transcript")]) == "model_read"
    assert value_grounding(KNOWN_IBAN, [page(printed, "transcript"), page(printed, "text", 2)]) == "verified"
    assert value_grounding(KNOWN_IBAN, [page(printed, "none")]) == "unverified"
    assert value_grounding(ATTACKER_IBAN, [page(printed)]) == "unverified"
    assert value_grounding("", [page(printed)]) == "unverified"


def test_a_reference_must_be_whole_words_of_the_page() -> None:
    text = "Kassenzeichen: 5126 0184-5122 · Datum 2012 · Aktenzeichen OA/VW/2026/55012"
    assert value_grounding("Kassenzeichen 5126 0184 5122", [page(text)]) == "verified"
    assert value_grounding("512601845122", [page(text)]) == "verified"
    assert value_grounding("oa-vw-2026-55012", [page(text)]) == "verified"
    assert value_grounding("12", [page(text)]) == "unverified"  # only inside longer numbers
    assert value_grounding("5126 0184 5123", [page(text)]) == "unverified"  # one digit misread
    assert value_grounding("zeichen 5126", [page(text)]) == "unverified"


REFERENCES_CUT_SHORT = [
    ("2026-0815", "Rechnungsnummer 2026-0815-77 vom 01.09.2026"),  # cut at a dash
    ("0815-77", "Rechnungsnummer 2026-0815-77 vom 01.09.2026"),  # its start missing
    ("Kassenzeichen 5126", "Kassenzeichen: 5126 0184-5122 · Datum 2012"),  # another digit group follows
    ("5126 0184", "Kassenzeichen: 5126 0184-5122 · Datum 2012"),
    ("0184 5122", "Kassenzeichen: 5126 0184 5122"),
    ("OA/VW/2026", "Aktenzeichen OA/VW/2026/55012"),  # cut at a slash
    ("12.345", "Az. 12.345.678"),  # cut at a dot
]


def test_a_reference_cut_short_is_not_found() -> None:
    def check(value: str, text: str) -> None:
        assert value_grounding(value, [page(text)]) == "unverified"
        assert value_grounding(value, [page(text, "transcript")]) == "unverified"

    check_rows(REFERENCES_CUT_SHORT, check)


def test_a_whole_reference_next_to_other_words_is_found() -> None:
    assert (
        value_grounding("2026-0815-77", [page("Rechnungsnummer 2026-0815-77 vom 01.09.2026")]) == "verified"
    )
    # the end of a sentence, a line break or a table's columns end it
    assert value_grounding("5126 0184", [page("Kassenzeichen 5126 0184. Bitte zahlen Sie.")]) == "verified"
    assert value_grounding("5126 0184", [page("Kassenzeichen 5126 0184\n2012 Musterstadt")]) == "verified"
    assert value_grounding("R-2026-0815", [page("R-2026-0815   01.09.2026   49,99 €")]) == "verified"


def test_an_iban_counts_as_printed_before_other_digits() -> None:
    """A footer's columns run into each other; a cut-off IBAN fails its length and check digits anyway."""
    grouped = " ".join(KNOWN_IBAN[i : i + 4] for i in range(0, 22, 4))
    footer = f"IBAN {grouped} 10115 Berlin"
    assert value_grounding(KNOWN_IBAN, [page(footer)], whole=False) == "verified"
    assert value_grounding(KNOWN_IBAN, [page(footer)]) == "unverified"


def todo(amount: float | None, *evidence: tuple[str, str], grounding: str = "verified") -> Item:
    return Item.model_validate(
        {
            "id": "itm_x",
            "kind": "payment",
            "title": "Pay",
            "amount": amount,
            "grounding": grounding,
            "evidence": [
                {"doc_id": "doc_x", "quote": quote, "grounding": level} for quote, level in evidence
            ],
            "created_at": "2026-09-01T00:00:00Z",
            "updated_at": "2026-09-01T00:00:00Z",
        }
    )


def test_the_amount_is_grounded_by_a_verified_sentence_that_states_it() -> None:
    assert (
        amount_grounding(todo(49.99, ("Bitte überweisen Sie 49,99 EUR bis zum 15.09.2026.", "verified")))
        == "verified"
    )
    assert amount_grounding(todo(1234.5, ("Betrag: 1.234,50 €", "verified"))) == "verified"
    # found in the text layer, but the sentence doesn't say how much
    assert amount_grounding(todo(49.99, ("Zahlbar innerhalb von 14 Tagen.", "verified"))) == "unverified"
    assert amount_grounding(todo(49.99, ("Bitte zahlen Sie 49,99 EUR.", "model_read"))) == "model_read"
    assert amount_grounding(todo(49.99, ("Die Verwarnung wird wirksam.", "model_read"))) == "model_read"
    assert amount_grounding(todo(49.99, ("Bitte zahlen Sie 49,99 EUR.", "unverified"))) == "unverified"
    assert amount_grounding(todo(None, ("Bitte zahlen Sie 49,99 EUR.", "verified"))) == "unverified"


def test_a_to_dos_user_grounding_is_about_its_date_not_its_amount() -> None:
    """``grounding="user"`` comes from moving the date or "Correct" on a Please-check card: neither is
    the person reading the amount off the letter."""
    assert amount_grounding(todo(49.99, grounding="user")) == "unverified"
    assert (
        amount_grounding(todo(49.99, ("Zahlbar in 14 Tagen.", "verified"), grounding="user")) == "unverified"
    )
    assert amount_grounding(
        todo(49.99, ("Die Verwarnung wird wirksam.", "model_read"), grounding="user")
    ) == ("model_read")
    assert amount_grounding(todo(49.99, ("Bitte zahlen Sie 49,99 EUR.", "verified"), grounding="user")) == (
        "verified"
    )


# --------------------------------------------------------------------------------------------------
# On a store
# --------------------------------------------------------------------------------------------------


def telecom(store: Store, **extra: Any) -> str:
    return store.add_party(name="Muster Telecom GmbH", kind="telecom", **extra).id


def letter(
    store: Store,
    label: str,
    party_id: str | None,
    *,
    iban: str = KNOWN_IBAN,
    reference: str | None = "R-2026-0815",
    payee: str = "Muster Telecom GmbH",
    source: str = "text",
    amount: float = 49.99,
    quote: str = "Bitte überweisen Sie 49,99 EUR bis zum 15.09.2026.",
    printed_iban: str | None = None,
    **doc: Any,
) -> tuple[str, str]:
    """A letter asking for one transfer, its page printing the IBAN and reference; returns (doc, item)."""
    grounding = "verified" if source == "text" else "model_read"
    doc.setdefault("kind", "invoice")
    doc_id = add_doc(
        store,
        label,
        party_id=party_id,
        text_mode="text" if source == "text" else "vision",
        payment=PaymentDetails(iban=iban, payee=payee, reference=reference, iban_valid=True),
        **doc,
    )
    store.set_pages(
        doc_id,
        [
            {
                "page": 1,
                "width": 100,
                "height": 100,
                "image_path": f"derived/{label}.jpg",
                "text": f"{payee}\nRechnung Nr. {reference}\n{quote}\nIBAN: {printed_iban or iban}",
                "text_source": source,
            }
        ],
    )
    item_id = add_item(
        store,
        kind="payment",
        title=f"Pay {label}",
        amount=amount,
        currency="EUR",
        direction="out",
        doc_id=doc_id,
        party_id=party_id,
        grounding=grounding,
        evidence=[Evidence(doc_id=doc_id, page=1, quote=quote, grounding=grounding)],
    )
    return doc_id, item_id


def code_for(store: Store, item_id: str) -> GiroCodeReady | GiroCodeBlocked:
    item = store.get_item(item_id)
    assert item is not None
    code = item_girocode(store, item, TODAY)
    assert code is not None
    return code


def compared_before(store: Store, iban: str = KNOWN_IBAN) -> None:
    """The person compared a payment to ``iban`` with its letter before (another to-do, another letter), so
    the tests of the other points start from a known account."""
    store.log_activity(
        CHECKED,
        "You compared the transfer details of “Pay earlier” with the letter",
        ref_type="item",
        ref_id="itm_earlier",
        data={
            **TransferValues(
                payee="Muster Telecom GmbH", iban=iban, reference="R-2026-0715", amount=49.99
            ).model_dump(),
            "doc_id": "doc_earlier",
        },
    )


def compare(store: Store, item_id: str) -> GiroCodeReady:
    """The person presses "These match the letter" for the values the payment shows."""
    code = code_for(store, item_id)
    assert isinstance(code, GiroCodeBlocked) and code.reason == "check_letter" and code.values is not None
    item = store.get_item(item_id)
    assert item is not None
    ready = record_check(store, item, code.values, TODAY)
    assert isinstance(ready, GiroCodeReady)
    return ready


def test_a_text_letter_gets_a_code_on_the_store(store: Store) -> None:
    compared_before(store)  # a known account: this test is about another point
    doc_id, item_id = letter(store, "invoice", telecom(store))
    code = code_for(store, item_id)
    assert code == GiroCodeReady(item_id=item_id, payload=PAYLOAD.format(iban=KNOWN_IBAN))
    document = store.get_document(doc_id)
    assert document is not None
    assert document_girocodes(store, document, store.list_items(doc_id=doc_id), TODAY) == [code]


def test_an_attackers_iban_with_valid_check_digits_on_a_known_senders_letter(store: Store) -> None:
    """The sender paid to KNOWN_IBAN before; a letter in its name asks for another valid account."""
    party = store.add_party(name="Beitragsservice Musterstadt", kind="public_broadcaster", ibans=[KNOWN_IBAN])
    letter(store, "genuine", party.id, payee="Beitragsservice Musterstadt", doc_date="2026-07-01")
    _, item_id = letter(
        store,
        "attack",
        party.id,
        iban=ATTACKER_IBAN,
        payee="Beitragsservice Musterstadt",
        doc_date="2026-09-25",
    )
    code = code_for(store, item_id)
    assert isinstance(code, GiroCodeBlocked) and code.reason == "scam"
    assert code.message.startswith(
        "No code: this IBAN is not the one Beitragsservice Musterstadt used before."
    )
    # comparing it with its own paper letter changes nothing: the paper matches, the account is still wrong
    item = store.get_item(item_id)
    assert item is not None
    with pytest.raises(
        CheckRefused, match="this IBAN is not the one Beitragsservice Musterstadt used before"
    ):
        record_check(
            store,
            item,
            TransferValues(
                payee="Beitragsservice Musterstadt", iban=ATTACKER_IBAN, reference="R-2026-0815", amount=49.99
            ),
            TODAY,
        )
    assert store.last_activity("item", item_id, [CHECKED]) is None


def test_a_look_alike_sender_and_hidden_text_are_scam_signs(store: Store) -> None:
    store.add_party(name="Beitragsservice Musterstadt", kind="public_broadcaster", ibans=[KNOWN_IBAN])
    fake = store.add_party(name="Rundfunk Beitragsservice Zahlungszentrale", kind="public_broadcaster")
    _, look_alike = letter(store, "look-alike", fake.id, iban=ATTACKER_IBAN, payee="Zahlungszentrale")
    code = code_for(store, look_alike)
    assert isinstance(code, GiroCodeBlocked) and code.reason == "scam"
    assert "“Beitragsservice Musterstadt”, whose name is like this sender's" in code.message

    _, hidden = letter(store, "hidden", telecom(store), hidden_text=True)
    code = code_for(store, hidden)
    assert isinstance(code, GiroCodeBlocked) and code.reason == "scam"
    assert code.message.startswith("No code: this letter shows signs of a scam.")


def test_a_checked_letter_keeps_its_reminders_but_never_gets_a_code(store: Store) -> None:
    """*I checked — it's genuine* brings a letter's to-dos back (ADR 0012): the gate still reads the letter's scam
    signs, so a check never unlocks a code, and the letter doesn't vouch for its IBAN on another letter."""
    from ordnung.secretary.triggers import run_and_reconcile

    party = store.add_party(name="Muster Telecom GmbH", kind="telecom", ibans=[KNOWN_IBAN]).id
    caution = ["Muster Telecom warns of phishing e-mails that use its name."]
    doc_id, item_id = letter(store, "cautioned", party, warnings=caution, doc_date="2026-09-20")
    run_and_reconcile(store, TODAY)
    (warning,) = [idea for idea in store.list_suggestions() if idea.rule_id == "scam_warning"]
    store.update_suggestion(warning.id, status="dismissed")
    ledger = Ledger(store, TODAY)
    assert ledger.scam_checked == frozenset({doc_id})
    assert item_id in {item.id for item in ledger.actionable_items()}
    code = code_for(store, item_id)
    assert isinstance(code, GiroCodeBlocked) and code.reason == "scam"
    assert not known_iban(ledger, store.get_party(party), KNOWN_IBAN, "doc_other")


def test_a_photo_letter_waits_for_the_paper_then_holds_only_while_the_values_stay(store: Store) -> None:
    doc_id, item_id = letter(store, "photo", telecom(store), source="transcript")
    code = code_for(store, item_id)
    assert isinstance(code, GiroCodeBlocked) and code.reason == "check_letter"
    assert code.to_check == ["amount", "iban", "reference"]
    assert code.values is not None

    item = store.get_item(item_id)
    assert item is not None
    with pytest.raises(CheckRefused, match="changed since you looked"):
        record_check(store, item, code.values.model_copy(update={"amount": 4.99}), TODAY)
    ready = record_check(store, item, code.values, TODAY)
    assert ready == GiroCodeReady(item_id=item_id, payload=PAYLOAD.format(iban=KNOWN_IBAN), checked=True)
    entry = store.last_activity("item", item_id, [CHECKED])
    assert entry is not None and entry.data == {**code.values.model_dump(), "doc_id": doc_id}
    assert entry.message == "You compared the transfer details of “Pay photo” with the letter"
    with pytest.raises(CheckRefused, match="nothing to compare"):
        record_check(store, item, code.values, TODAY)

    # reading the letter again gives another reference: the check no longer covers it
    store.update_document(
        doc_id, payment=PaymentDetails(iban=KNOWN_IBAN, payee="Muster Telecom GmbH", reference="R-2026-0816")
    )
    again = code_for(store, item_id)
    assert isinstance(again, GiroCodeBlocked) and again.reason == "check_letter"
    # changing the amount by hand asks again too
    store.update_document(
        doc_id, payment=PaymentDetails(iban=KNOWN_IBAN, payee="Muster Telecom GmbH", reference="R-2026-0815")
    )
    assert isinstance(code_for(store, item_id), GiroCodeReady)
    store.update_item(item_id, amount=59.99)
    assert isinstance(code_for(store, item_id), GiroCodeBlocked)


def test_a_photo_needs_no_iban_check_when_another_letter_of_the_sender_had_it(store: Store) -> None:
    party = telecom(store, ibans=[KNOWN_IBAN])
    letter(store, "earlier", party)
    _, item_id = letter(store, "photo", party, source="transcript")
    code = code_for(store, item_id)
    assert isinstance(code, GiroCodeBlocked) and code.to_check == ["amount", "reference"]


def test_an_iban_only_the_letter_itself_taught_is_not_known(store: Store) -> None:
    """Every clean letter teaches its sender its IBAN — that alone says nothing about another letter."""
    party = telecom(store, ibans=[KNOWN_IBAN])
    _, item_id = letter(store, "photo", party, source="transcript")
    code = code_for(store, item_id)
    assert isinstance(code, GiroCodeBlocked) and "iban" in code.to_check


def test_an_iban_not_printed_on_the_page_needs_the_paper(store: Store) -> None:
    compared_before(store)  # a known account: this test is about another point
    other = make_iban("DE", "100100100123456780")
    _, item_id = letter(store, "misread", telecom(store), printed_iban=other)
    code = code_for(store, item_id)
    assert isinstance(code, GiroCodeBlocked) and code.to_check == ["iban"]
    assert code.message.startswith("No code yet: the IBAN wasn't found in the letter's text.")


def test_the_check_is_deleted_with_the_letter_even_after_its_to_do(store: Store) -> None:
    """docs/privacy.md: deleting the letter deletes the saved comparison (payee, IBAN, reference)."""
    doc_id, item_id = letter(store, "photo", telecom(store), source="transcript")
    code = code_for(store, item_id)
    assert isinstance(code, GiroCodeBlocked) and code.values is not None
    item = store.get_item(item_id)
    assert item is not None
    record_check(store, item, code.values, TODAY)
    store.delete_item(item_id)  # "Delete to-do", or a re-read dropping it
    assert store.last_activity("item", item_id, [CHECKED]) is not None
    store.delete_document(doc_id)
    assert store.last_activity("item", item_id, [CHECKED]) is None


def unstated_amount(store: Store, source: str = "text") -> tuple[str, str]:
    """A letter whose to-do has an amount its sentence doesn't state (so only the person can vouch)."""
    return letter(
        store, "unstated", telecom(store), source=source, amount=499.9, quote="Zahlbar bis zum 15.09.2026."
    )


def test_moving_the_date_never_vouches_for_the_amount(store: Store) -> None:
    compared_before(store)  # a known account: this test is about another point
    _, item_id = unstated_amount(store)
    before = code_for(store, item_id)
    assert isinstance(before, GiroCodeBlocked) and before.to_check == ["amount"]
    moved = _update(store, item_id, ItemPatch(due_date="2026-10-15"), TODAY)
    assert moved.grounding == "user"  # the date is the person's now …
    after = code_for(store, item_id)  # … the amount still isn't
    assert isinstance(after, GiroCodeBlocked) and after.reason == "check_letter"
    assert after.to_check == ["amount"]
    assert after.message.startswith("No code yet: the amount wasn't found in the letter's text.")


def test_correct_on_a_please_check_card_never_vouches_for_the_amount(store: Store) -> None:
    _, item_id = unstated_amount(store)
    _confirm(store, item_id)
    code = code_for(store, item_id)
    assert isinstance(code, GiroCodeBlocked) and code.to_check == ["amount"]


def test_on_a_photo_letter_moving_the_date_keeps_the_amount_to_compare(store: Store) -> None:
    compared_before(store)  # a known account: this test is about another point
    _, item_id = letter(store, "photo", telecom(store), source="transcript")
    _update(store, item_id, ItemPatch(due_date="2026-10-15"), TODAY)
    code = code_for(store, item_id)
    assert isinstance(code, GiroCodeBlocked) and code.to_check == ["amount", "iban", "reference"]
    assert code.message.startswith("No code yet: the amount, the IBAN and the reference were read by AI")


def test_an_amount_the_person_typed_is_compared_with_the_paper_like_any_other(store: Store) -> None:
    compared_before(store)  # a known account: this test is about another point
    _, item_id = letter(store, "invoice", telecom(store))
    assert isinstance(code_for(store, item_id), GiroCodeReady)
    typed = _update(store, item_id, ItemPatch(amount=59.99), TODAY)
    code = code_for(store, item_id)
    assert isinstance(code, GiroCodeBlocked) and code.to_check == ["amount"]
    assert code.values is not None and code.values.amount == 59.99
    ready = record_check(store, typed, code.values, TODAY)
    assert isinstance(ready, GiroCodeReady) and ready.checked and "\nEUR59.99\n" in ready.payload


def test_a_letter_asking_for_two_transfers_gets_no_code_until_one_is_paid(store: Store) -> None:
    compared_before(store)  # a known account: this test is about another point
    party = telecom(store)
    doc_id, first = letter(store, "two", party)
    second = add_item(
        store, kind="payment", title="Deposit", amount=100.0, currency="EUR", direction="out", doc_id=doc_id
    )
    debit = add_item(
        store,
        kind="payment",
        title="Monthly fee",
        action="Collected by direct debit",
        amount=9.99,
        doc_id=doc_id,
    )
    document = store.get_document(doc_id)
    assert document is not None
    codes = {
        code.item_id: code
        for code in document_girocodes(store, document, store.list_items(doc_id=doc_id), TODAY)
    }
    assert [getattr(codes[i], "reason", None) for i in (first, second, debit)] == [
        "several",
        "several",
        "direct_debit",
    ]
    store.update_item(second, status="done")
    assert isinstance(code_for(store, first), GiroCodeReady)


@pytest.mark.parametrize(
    "quote",
    [
        "Der Monatsbeitrag von 29,90 € wird zum 1. eines Monats per SEPA-Lastschrift eingezogen.",
        "Der Monatsbeitrag von 29,90 € wird per Bankeinzug von Ihrem Konto eingezogen.",
        "Den Betrag von 29,90 € ziehen wir am 01.10.2026 von Ihrem Konto ein (Mandatsreferenz M-4711).",
        "Der Betrag von 29,90 € wird wie gewohnt von Ihrem Konto DE12 3456 eingezogen.",
        "Den Betrag von 29,90 € buchen wir am 15.10. ab.",
        "Wir buchen den Beitrag von 29,90 € wie bisher zum 15. eines Monats ab, erstmals am 15.10.2026.",
        "Der Beitrag von 29,90 € wird am 01.10.2026 abgebucht (Gläubiger-ID DE98ZZZ09999999999).",
        "Eine Überweisung ist nicht nötig: den Betrag von 29,90 € ziehen wir ein.",
    ],
)
def test_a_debit_in_the_quoted_sentence_blocks_even_when_the_todo_reads_like_a_transfer(
    store: Store, quote: str
) -> None:
    _, item_id = letter(store, "gym", telecom(store), amount=29.9, quote=quote)
    code = code_for(store, item_id)
    assert isinstance(code, GiroCodeBlocked) and code.reason == "direct_debit", quote


@pytest.mark.parametrize(
    "quote",
    [
        # a returned debit: now the person has to transfer (and fees follow)
        "Ihre Lastschrift wurde von Ihrer Bank zurückgegeben. Bitte überweisen Sie 49,99 EUR bis zum 15.09.2026.",
        "Rücklastschrift: bitte zahlen Sie 49,99 EUR bis zum 15.09.2026.",
        "Der Betrag von 49,99 EUR konnte nicht von Ihrem Konto abgebucht werden.",
        "Da die Lastschrift mangels Deckung nicht ausgeführt wurde, überweisen Sie bitte 49,99 EUR bis zum "
        "15.09.2026.",
        "Die Abbuchung vom 01.09.2026 war leider nicht möglich. Bitte überweisen Sie 49,99 EUR bis zum 15.09.2026.",
        # a mandate offered as the alternative to the transfer asked for
        "Bitte überweisen Sie 49,99 EUR bis zum 15.09.2026 oder erteilen Sie uns ein SEPA-Lastschriftmandat.",
        "Sofern Sie nicht am Lastschriftverfahren teilnehmen, überweisen Sie den Betrag von 49,99 EUR bitte bis "
        "zum 15.09.2026.",
    ],
)
def test_a_returned_debit_or_a_transfer_asked_for_is_no_direct_debit(store: Store, quote: str) -> None:
    compared_before(store)  # a known account: this test is about another point
    _, item_id = letter(store, "reminder", telecom(store), quote=quote)
    assert code_for(store, item_id) == GiroCodeReady(item_id=item_id, payload=PAYLOAD.format(iban=KNOWN_IBAN))


def test_a_to_do_that_says_its_debit_failed_gets_a_code_not_nothing_to_transfer(store: Store) -> None:
    """The to-do's own words say the debit failed and its action asks for no transfer by name: the
    person has to transfer now (a reminder with fees follows otherwise)."""
    compared_before(store)  # a known account: this test is about another point
    quote = "Der Beitrag konnte nicht eingezogen werden. Bitte überweisen Sie 49,99 EUR bis zum 01.10.2026."
    _, item_id = letter(store, "returned", telecom(store), quote=quote)
    store.update_item(
        item_id,
        title="Rundfunkbeitrag nachzahlen – konnte nicht eingezogen werden",
        action="Pay 49.99 € by 01.10.2026",
    )
    assert code_for(store, item_id) == GiroCodeReady(item_id=item_id, payload=PAYLOAD.format(iban=KNOWN_IBAN))


def test_a_new_monthly_amount_on_the_same_letter_doesnt_compete_with_its_back_payment(store: Store) -> None:
    """A utility statement asks for its back-payment and sets new monthly advance payments (§ 560 Abs.
    4 BGB): the back-payment gets its code, the monthly amount — paid by standing order — doesn't."""
    compared_before(store)  # a known account: this test is about another point
    party = telecom(store)
    doc_id, back_payment = letter(store, "statement", party)
    advance = add_item(
        store,
        kind="payment",
        title="Update your standing order to the new monthly amount",
        amount=670.0,
        currency="EUR",
        direction="out",
        doc_id=doc_id,
        recurrence={"freq": "monthly", "interval": 1},
        evidence=[Evidence(doc_id=doc_id, quote="Ihre Gesamtmiete beträgt ab dem 01.11.2026 670,00 €.")],
    )
    assert code_for(store, back_payment) == GiroCodeReady(
        item_id=back_payment, payload=PAYLOAD.format(iban=KNOWN_IBAN)
    )
    # the letter's reference is the back-payment's: none for the monthly amount, paid or not
    for status in ("open", "done"):
        store.update_item(back_payment, status=status)
        code = code_for(store, advance)
        assert isinstance(code, GiroCodeBlocked) and code.reason == "several", status
    # set aside ("not a real to-do"), the back-payment no longer counts
    store.update_item(back_payment, status="dismissed")
    assert isinstance(code_for(store, advance), GiroCodeBlocked)
    assert code_for(store, advance).reason != "several"  # type: ignore[union-attr]


def test_two_monthly_payments_on_one_letter_get_no_code(store: Store) -> None:
    party = telecom(store)
    doc_id, _ = letter(store, "lease", party)
    monthly = {"freq": "monthly", "interval": 1}
    rent, parking = (
        add_item(
            store,
            kind="payment",
            title=title,
            amount=amount,
            direction="out",
            doc_id=doc_id,
            recurrence=monthly,
        )
        for title, amount in (("Rent", 640.0), ("Parking space", 40.0))
    )
    for item_id in (rent, parking):
        code = code_for(store, item_id)
        assert isinstance(code, GiroCodeBlocked) and code.reason == "several"


def test_the_reference_goes_into_the_code_without_its_label(store: Store) -> None:
    """The cashier matches the Kassenzeichen; "Kassenzeichen" itself only takes room in the 140."""
    compared_before(store)  # a known account: this test is about another point
    _, item_id = letter(store, "fine", telecom(store), reference="Kassenzeichen 5126 0184 5122")
    code = code_for(store, item_id)
    assert isinstance(code, GiroCodeReady)
    assert code.payload.splitlines()[-1] == "5126 0184 5122"
    _, photo_id = letter(
        store, "photo-fine", telecom(store), reference="Kassenzeichen: 5126 0184 5122", source="transcript"
    )
    photo = code_for(store, photo_id)
    assert isinstance(photo, GiroCodeBlocked) and photo.values is not None
    assert photo.values.reference == "5126 0184 5122"


def test_a_reference_read_cut_short_needs_the_paper(store: Store) -> None:
    _, item_id = letter(store, "cut", telecom(store), reference="2026-0815")
    store.set_pages(
        store.list_documents()[0].id,
        [
            {
                "page": 1,
                "width": 100,
                "height": 100,
                "image_path": "derived/cut.jpg",
                "text": f"Rechnungsnummer 2026-0815-77\nBitte überweisen Sie 49,99 EUR bis zum 15.09.2026.\n"
                f"IBAN: {KNOWN_IBAN}",
                "text_source": "text",
            }
        ],
    )
    code = code_for(store, item_id)
    assert isinstance(code, GiroCodeBlocked) and code.to_check == ["reference"]


def test_a_scam_letter_teaches_no_known_iban_and_marks_its_iban(store: Store) -> None:
    """A letter with hidden text still teaches its sender its IBAN (ingest checks only the payment):
    a later letter from that sender asking for the same account must not count it as known — and gets
    no code at all, however clean it looks on its own."""
    party = telecom(store, ibans=[ATTACKER_IBAN])
    scam_id, _ = letter(store, "hidden", party, iban=ATTACKER_IBAN, hidden_text=True)
    photo_id, photo_item = letter(store, "follow-up", party, iban=ATTACKER_IBAN, source="transcript")
    stored = store.get_party(party)
    assert stored is not None
    assert not known_iban(Ledger(store, TODAY), stored, ATTACKER_IBAN, photo_id)
    _, text_item = letter(store, "text-follow-up", party, iban=ATTACKER_IBAN)
    for item_id in (photo_item, text_item):
        code = code_for(store, item_id)
        assert isinstance(code, GiroCodeBlocked) and code.reason == "scam"
        assert code.message == (
            "No code: this IBAN is also in “hidden.pdf”, a letter that shows signs of a scam. Check with the "
            "sender using contact details you already have, not the ones in this letter."
        )
    # the scam letter in the trash still counts; deleted for good, it is forgotten
    store.update_document(scam_id, deleted_at="2026-09-27T10:00:00Z")
    assert getattr(code_for(store, text_item), "reason", None) == "scam"
    store.delete_document(scam_id)
    code = code_for(store, text_item)  # judged on its own: a first payment to that payee and IBAN
    assert isinstance(code, GiroCodeBlocked) and code.first_payment


def test_a_letter_in_the_trash_makes_no_iban_known(store: Store) -> None:
    party = telecom(store, ibans=[KNOWN_IBAN])
    earlier, _ = letter(store, "earlier", party)
    photo_id, _ = letter(store, "photo", party, source="transcript")
    stored = store.get_party(party)
    assert stored is not None
    assert known_iban(Ledger(store, TODAY), stored, KNOWN_IBAN, photo_id)
    store.update_document(earlier, deleted_at="2026-09-27T10:00:00Z")
    assert not known_iban(Ledger(store, TODAY), stored, KNOWN_IBAN, photo_id)


def test_an_invoice_a_reminder_took_over(store: Store) -> None:
    compared_before(store)  # a known account: this test is about another point
    party = telecom(store)
    case = store.add_case(title="Phone bill", party_id=party)
    ref = [Identifier(label="Rechnungsnummer", value="R-2026-0815")]
    _, invoice = letter(store, "invoice", party, case_id=case.id, references=ref, doc_date="2026-09-01")
    _, reminder = letter(
        store,
        "reminder",
        party,
        case_id=case.id,
        references=ref,
        doc_date="2026-09-20",
        kind="dunning",
        title="Zahlungserinnerung",
    )
    code = code_for(store, invoice)
    assert isinstance(code, GiroCodeBlocked) and code.reason == "replaced"
    assert "“Zahlungserinnerung” took over this payment" in code.message
    assert isinstance(code_for(store, reminder), GiroCodeReady)


def test_only_payments_of_letters_have_codes(store: Store) -> None:
    doc_id, _ = letter(store, "invoice", telecom(store))
    deadline = add_item(store, kind="deadline", title="Object", doc_id=doc_id)
    manual = add_item(store, kind="payment", title="Pay a friend", amount=10.0, grounding="user")
    for item_id in (deadline, manual):
        item = store.get_item(item_id)
        assert item is not None and item_girocode(store, item, TODAY) is None
        with pytest.raises(CheckRefused, match="isn't a payment from a letter"):
            record_check(store, item, TransferValues(), TODAY)
    document = store.get_document(doc_id)
    assert document is not None
    assert [
        code.item_id for code in document_girocodes(store, document, store.list_items(doc_id=doc_id), TODAY)
    ] == [item.id for item in store.list_items(doc_id=doc_id) if item.kind == "payment"]
    assert document_girocodes(store, document, [], TODAY) == []


def test_a_letter_in_the_trash_and_a_check_of_a_blocked_code(store: Store) -> None:
    doc_id, item_id = letter(store, "trashed", telecom(store))
    store.update_document(doc_id, deleted_at="2026-09-27T10:00:00Z")
    code = code_for(store, item_id)
    assert isinstance(code, GiroCodeBlocked) and code.message == "No code: this letter is in the trash."
    item = store.get_item(item_id)
    assert item is not None
    with pytest.raises(CheckRefused, match="this letter is in the trash"):
        record_check(store, item, TransferValues(), TODAY)


def test_a_returned_debit_fee_warning_never_turns_a_direct_debit_into_a_code(store: Store) -> None:
    """Stock wording on a direct-debit bill warns what a returned debit costs: no debit failed, the
    sender collects the money — a code would pay it twice. Neither the to-do's words nor its sentence
    lose the debit to the warning."""
    quote = (
        "Der Rechnungsbetrag von 49,99 EUR wird am 15.10.2026 per SEPA-Lastschrift von Ihrem Konto abgebucht; "
        "bei einer Rücklastschrift berechnen wir 3,00 EUR."
    )
    _, item_id = letter(store, "debit-bill", telecom(store), quote=quote)
    store.update_item(
        item_id,
        title="Rechnung Oktober 49,99 € per Lastschrift",
        description="Collected by SEPA direct debit on 15 Oct; a returned debit costs €3.",
    )
    code = code_for(store, item_id)
    assert isinstance(code, GiroCodeBlocked) and code.reason == "direct_debit"
    # the sentence alone blocks too, whatever the to-do says
    store.update_item(item_id, title="Pay the October bill", description=None)
    code = code_for(store, item_id)
    assert isinstance(code, GiroCodeBlocked) and code.reason == "direct_debit"


def test_an_emails_payment_its_attached_bill_asks_for_gets_no_code_the_bill_does(store: Store) -> None:
    """The one inbox's most common bill: the e-mail repeats the payment of the bill attached to it, with
    the same bank details. Pay once: the bill gets the code, the e-mail's payment says where it is."""
    compared_before(store)  # a known account: this test is about another point
    party = telecom(store, ibans=[KNOWN_IBAN])
    mail_id, mail_payment = letter(store, "bill-email", party, title="Ihre Rechnung ist da")
    bill_id, bill_payment = letter(store, "bill-pdf", party, title="Rechnung September")
    with store.tx() as conn:
        conn.execute("UPDATE documents SET mime = 'message/rfc822' WHERE id = ?", (mail_id,))
        conn.execute("UPDATE documents SET source = ? WHERE id = ?", (f"email:{mail_id}", bill_id))
    for item_id in (mail_payment, bill_payment):
        store.update_item(item_id, due_date="2026-10-15")
    assert code_for(store, bill_payment) == GiroCodeReady(
        item_id=bill_payment, payload=PAYLOAD.format(iban=KNOWN_IBAN)
    )
    code = code_for(store, mail_payment)
    assert isinstance(code, GiroCodeBlocked) and code.reason == "replaced"
    assert "“Rechnung September”" in code.message


def test_an_emails_payment_stays_without_a_code_when_a_reminder_takes_its_attached_bill_over(
    store: Store,
) -> None:
    """The e-mail names no invoice number, so the postal reminder about its attached bill doesn't take the
    e-mail's payment over itself: the bill still asks for it, and only the reminder gets a code."""
    compared_before(store)  # a known account: this test is about another point
    party = telecom(store, ibans=[KNOWN_IBAN])
    case = store.add_case(title="Phone bill", party_id=party).id
    ref = [Identifier(label="Rechnungsnummer", value="R-2026-0815")]
    mail_id, mail_payment = letter(store, "bill-email", party, title="Ihre Rechnung ist da", case_id=case)
    bill_id, bill_payment = letter(
        store,
        "bill-pdf",
        party,
        title="Rechnung September",
        case_id=case,
        references=ref,
        doc_date="2026-09-01",
    )
    store.update_document(mail_id, mime="message/rfc822")
    store.update_document(bill_id, source=f"email:{mail_id}")
    for item_id in (mail_payment, bill_payment):
        store.update_item(item_id, due_date="2026-09-15")
    _, reminder = letter(
        store,
        "reminder",
        party,
        case_id=case,
        references=ref,
        doc_date="2026-09-20",
        kind="dunning",
        title="Zahlungserinnerung",
        amount=54.99,
        quote="Bitte überweisen Sie 54,99 EUR bis zum 30.09.2026.",
    )
    code = code_for(store, mail_payment)
    assert isinstance(code, GiroCodeBlocked) and code.reason == "replaced"
    assert "the bill attached to this e-mail, “Rechnung September”" in code.message
    code = code_for(store, bill_payment)
    assert isinstance(code, GiroCodeBlocked) and "“Zahlungserinnerung” took over" in code.message
    assert isinstance(code_for(store, reminder), GiroCodeReady)


# --------------------------------------------------------------------------------------------------
# The first payment to an account (point 7), on a store
# --------------------------------------------------------------------------------------------------


def spaced(iban: str) -> str:
    """``iban`` as a letter may print it: in groups of four, lower case."""
    return " ".join(iban[i : i + 4] for i in range(0, len(iban), 4)).lower()


def test_the_first_code_to_an_iban_waits_for_the_comparison_then_the_next_letter_is_ready(
    store: Store,
) -> None:
    party = telecom(store)
    _, first = letter(store, "september", party)
    code = code_for(store, first)
    assert isinstance(code, GiroCodeBlocked) and code.reason == "check_letter" and code.first_payment
    assert code.to_check == []  # every value is in the text layer: the first payment alone asks
    assert compare(store, first) == GiroCodeReady(
        item_id=first, payload=PAYLOAD.format(iban=KNOWN_IBAN), checked=True
    )
    # the next letter to the same account, its IBAN spelled otherwise: ready, nothing to compare
    _, second = letter(store, "october", party, iban=spaced(KNOWN_IBAN), doc_date="2026-10-01")
    assert code_for(store, second) == GiroCodeReady(item_id=second, payload=PAYLOAD.format(iban=KNOWN_IBAN))


def test_the_first_comparison_holds_only_for_the_values_it_saw(store: Store) -> None:
    """The to-do's own comparison vouches for the values it saw (``checked``). Once the letter is read
    again with another reference or amount, it is an earlier payment to that payee and IBAN, as another
    letter's would be: point 6 alone decides, so a value not in the text asks again, and not as a first
    payment."""
    doc_id, item_id = letter(store, "invoice", telecom(store))
    compare(store, item_id)
    # read again with another reference, one the letter's text doesn't print
    store.update_document(
        doc_id, payment=PaymentDetails(iban=KNOWN_IBAN, payee="Muster Telecom GmbH", reference="R-2026-0816")
    )
    again = code_for(store, item_id)
    assert isinstance(again, GiroCodeBlocked) and again.reason == "check_letter"
    assert not again.first_payment and again.to_check == ["reference"]
    # back to the reference printed, at an amount the letter's text says: ready, as on a later letter
    store.update_document(
        doc_id, payment=PaymentDetails(iban=KNOWN_IBAN, payee="Muster Telecom GmbH", reference="R-2026-0815")
    )
    assert code_for(store, item_id) == GiroCodeReady(
        item_id=item_id, payload=PAYLOAD.format(iban=KNOWN_IBAN), checked=True
    )


def test_a_reading_that_makes_a_new_to_do_finds_the_account_compared(store: Store) -> None:
    """Read again, a letter can get a new to-do (another sentence quoted) while the old one goes: what the
    person compared on that page still names the payee and IBAN, so the new to-do is a later payment to
    them — its values grounded by point 6 as on any later letter."""
    party = telecom(store)
    doc_id, old = letter(store, "invoice", party)
    compare(store, old)
    store.delete_item(old)
    new = add_item(
        store,
        kind="payment",
        title="Pay invoice",
        amount=49.99,
        currency="EUR",
        direction="out",
        doc_id=doc_id,
        party_id=party,
        evidence=[
            Evidence(
                doc_id=doc_id,
                page=1,
                quote="Bitte überweisen Sie 49,99 EUR bis zum 15.09.2026.",
                grounding="verified",
            )
        ],
    )
    assert code_for(store, new) == GiroCodeReady(item_id=new, payload=PAYLOAD.format(iban=KNOWN_IBAN))


def test_a_known_sender_asking_for_a_new_iban_is_a_new_account(store: Store) -> None:
    """A familiar name, which the letter itself supplies, never makes a new IBAN a known account. The
    known-sender check keeps its stricter answer (no code at all) where it has one; where it has none, the
    person compares again."""
    party = telecom(store, ibans=[KNOWN_IBAN])
    _, genuine = letter(store, "genuine", party, doc_date="2026-08-01")
    compare(store, genuine)
    _, attack = letter(store, "attack", party, iban=ATTACKER_IBAN, doc_date="2026-09-25")
    code = code_for(store, attack)
    assert isinstance(code, GiroCodeBlocked) and code.reason == "scam"
    assert code.message.startswith("No code: this IBAN is not the one Muster Telecom GmbH used before.")
    # a sender with a look-alike name
    look_alike = store.add_party(name="Muster Telecom Inkasso", kind="other").id
    _, other = letter(store, "look-alike", look_alike, iban=ATTACKER_IBAN, doc_date="2026-09-26")
    code = code_for(store, other)
    assert isinstance(code, GiroCodeBlocked) and code.reason == "scam"
    # the familiar payee's name on a letter Ordnung matched to no sender, asking for another account
    _, unmatched = letter(store, "unmatched", None, iban=make_iban("DE", "500500500111222333"))
    code = code_for(store, unmatched)
    assert isinstance(code, GiroCodeBlocked) and code.reason == "check_letter" and code.first_payment


def test_a_known_iban_under_another_payee_or_sender_asks_again(store: Store) -> None:
    """Security review (pay0-1): an IBAN the person confirmed for one payee says nothing about a letter
    naming another payee, or coming from another sender. A shop's letter whose page really shows the
    account is compared once; a later crafted letter, its text layer reading that account under another
    name, must not borrow it — the scam checks compare only the sender's own history, and point 6 trusts
    the text layer."""
    shop = store.add_party(name="Kramladen Versand", kind="other").id
    _, bought = letter(store, "shop", shop, payee="Kramladen Versand")
    compare(store, bought)
    tax_office = store.add_party(name="Finanzamt Musterstadt", kind="authority").id
    _, tax = letter(store, "tax", tax_office, payee="Finanzamt Musterstadt")
    code = code_for(store, tax)
    assert isinstance(code, GiroCodeBlocked) and code.reason == "check_letter" and code.first_payment
    assert code.message == (
        "No code yet: you haven't compared a payment to this payee and IBAN with a letter from this sender "
        "before. Compare the payee, IBAN, amount and reference with the letter, then confirm."
    )
    # a letter matched to no sender, naming someone else
    _, stranger = letter(store, "stranger", None, payee="Jemand Anders")
    code = code_for(store, stranger)
    assert isinstance(code, GiroCodeBlocked) and code.first_payment
    assert code.message.startswith(
        "No code yet: you haven't compared a payment to this payee and IBAN with a letter before."
    )
    # the shop's name and account, but from another sender
    _, borrowed = letter(store, "borrowed", tax_office, payee="Kramladen Versand")
    code = code_for(store, borrowed)
    assert isinstance(code, GiroCodeBlocked) and code.first_payment
    # the same sender: its name as that sender's letters spell it, give or take a legal form at its end
    for label, payee in (
        ("shop-again", "KRAMLADEN  versand"),
        ("shop-gmbh", "Kramladen Versand GmbH"),
        ("shop-kg", "Kramladen Versand GmbH & Co. KG"),
        ("shop-ug", "Kramladen Versand UG (haftungsbeschränkt)"),
        ("shop-ev", "Kramladen Versand e. V."),
    ):
        _, again = letter(store, label, shop, payee=payee)
        assert isinstance(code_for(store, again), GiroCodeReady), payee
    # ... and nothing looser (security review, pay1-1): a longer name containing it, a part of it, a
    # nearly-alike name, or a legal form alone are other payees, even from the same sender
    for label, payee in (
        ("shop-longer", "Kramladen Versand Inkasso Partner"),
        ("shop-part", "Versand"),
        ("shop-alike", "Kramladen Versandt"),
        ("shop-form-only", "GmbH"),
    ):
        _, other = letter(store, label, shop, payee=payee)
        code = code_for(store, other)
        assert isinstance(code, GiroCodeBlocked) and code.first_payment, payee
    # a letter matched to no sender: the payee's name itself, case and spacing aside, nothing looser
    _, unmatched = letter(store, "shop-unmatched", None, payee="kramladen versand")
    assert isinstance(code_for(store, unmatched), GiroCodeReady)
    _, shorter = letter(store, "shop-short", None, payee="Kramladen")
    code = code_for(store, shorter)
    assert isinstance(code, GiroCodeBlocked) and code.first_payment


def test_only_a_comparison_logged_for_a_to_do_counts(store: Store) -> None:
    """``payment.checked`` is written for a to-do (:func:`record_check`); an entry with that kind about
    anything else is not the person's comparison of a payment and makes no account known."""
    store.log_activity(
        CHECKED,
        "Not a comparison of a payment",
        ref_type="document",
        ref_id="doc_elsewhere",
        data={
            **TransferValues(
                payee="Muster Telecom GmbH", iban=KNOWN_IBAN, reference="R-2026-0715", amount=49.99
            ).model_dump(),
            "doc_id": "doc_elsewhere",
        },
    )
    assert compared_accounts(store) == {}
    _, item_id = letter(store, "invoice", telecom(store))
    code = code_for(store, item_id)
    assert isinstance(code, GiroCodeBlocked) and code.first_payment


def test_a_comparison_made_before_this_rule_counts(store: Store) -> None:
    """A data folder from before point 7 keeps its ``payment.checked`` entries as they were (the same
    shape: the values and the letter's id): the person compared that account then, so its next letter
    gets its code without asking again (security review, pay0-3)."""
    party = telecom(store)
    _, photo_item = letter(store, "photo", party, source="transcript", doc_date="2026-08-01")
    compare(store, photo_item)
    entry = store.last_activity("item", photo_item, [CHECKED])
    assert entry is not None and set(entry.data) == {"payee", "iban", "reference", "amount", "doc_id"}
    _, pdf_item = letter(store, "pdf", party, iban=spaced(KNOWN_IBAN), doc_date="2026-09-01")
    assert code_for(store, pdf_item) == GiroCodeReady(
        item_id=pdf_item, payload=PAYLOAD.format(iban=KNOWN_IBAN)
    )


def test_only_the_persons_comparison_makes_an_account_known(store: Store) -> None:
    """Not the letters (a learned IBAN, another letter asking for it), not "Mark as paid" (it says money
    left, not to which account: the person may have typed the IBAN from the page), and not the model."""
    party = telecom(store, ibans=[KNOWN_IBAN])
    _, paid = letter(store, "paid", party, doc_date="2026-08-01")
    _update(store, paid, ItemPatch(status="done"), TODAY)
    _, earlier = letter(store, "earlier", party, doc_date="2026-08-15")  # another letter asking for it
    _, item_id = letter(store, "now", party, doc_date="2026-09-01")
    code = code_for(store, item_id)
    assert isinstance(code, GiroCodeBlocked) and code.first_payment
    # the person compared the earlier letter: now the account is known
    compare(store, earlier)
    assert isinstance(code_for(store, item_id), GiroCodeReady)


@dataclass(frozen=True)
class Newcomer:
    """A person added to the household, as Settings sends them (no id yet)."""

    name: str
    id: str | None = None
    signs: bool = True


def test_a_comparison_on_a_letter_filed_for_someone_in_the_household_counts(store: Store) -> None:
    """One data folder is one household's, kept by one person: whoever a letter is filed for, it was the
    person who compared the account's IBAN with the page."""
    party = telecom(store)
    child, _ = letter(store, "child", party, doc_date="2026-08-01")
    household.change(store, base=household.version([]), members=[Newcomer("Kim Rivera")], also_file=[child])
    filed = store.get_document(child)
    assert filed is not None and household.letter_for(store, filed).filed_for is not None
    compare(store, store.list_items(doc_id=child)[0].id)
    _, own = letter(store, "own", party, doc_date="2026-09-01")
    assert isinstance(code_for(store, own), GiroCodeReady)


def test_another_data_folders_comparisons_dont_count(store: Store, tmp_path: Path) -> None:
    """Each data folder is its own database: what the person compared in one is not there in another."""
    _, here = letter(store, "invoice", telecom(store))
    compare(store, here)
    other_dir = tmp_path / "other-folder"
    seed_database(other_dir)
    other = Store.open(Paths(other_dir).ensure())
    try:
        _, there = letter(other, "invoice", telecom(other))
        code = code_for(other, there)
        assert isinstance(code, GiroCodeBlocked) and code.first_payment
    finally:
        other.close()


def test_deleting_the_compared_letter_makes_its_account_new_again(store: Store) -> None:
    """docs/privacy.md, "Delete means delete": the comparison goes with its letter, and with it the account's
    history — a list of known accounts kept apart would outlive the letters."""
    party = telecom(store)
    first_doc, first = letter(store, "september", party, doc_date="2026-09-01")
    compare(store, first)
    _, second = letter(store, "october", party, doc_date="2026-10-01")
    assert isinstance(code_for(store, second), GiroCodeReady)
    store.delete_document(first_doc)
    code = code_for(store, second)
    assert isinstance(code, GiroCodeBlocked) and code.first_payment
