"""Draft checks: each one positive and negative, plus § citation parsing and identifier matching."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from ordnung.drafts.checks import (
    LABELS,
    CheckContext,
    citations,
    citations_known,
    delivery_channel_ok,
    has_dates,
    has_reference,
    identifiers,
    language_matches,
    no_new_identifiers,
    no_placeholders,
    recipient_complete,
    run_checks,
    sender_complete,
    unknown_citations,
)
from ordnung.models import Draft
from ordnung.rules import send_guidance

BODY = (
    "Sehr geehrte Damen und Herren,\n\nhiermit kündige ich den Vertrag „FunkNetz Mobil“, Kundennummer "
    "4711-0815, fristgerecht zum 14.01.2027, hilfsweise zum nächstmöglichen Zeitpunkt.\n\nBitte bestätigen "
    "Sie mir den Eingang dieser Kündigung sowie das Beendigungsdatum schriftlich."
)


def _draft(**fields: Any) -> Draft:
    values: dict[str, Any] = {
        "id": "drf_test",
        "kind": "cancellation",
        "sender_block": "Sam Rivera\nMusterweg 5\n12345 Musterstadt",
        "recipient_block": "FunkNetz Mobile\nFunkallee 1\n10115 Berlin",
        "place_date": "Musterstadt, 28.09.2026",
        "subject": "Kündigung des Vertrags „FunkNetz Mobil“ – Kundennummer 4711-0815",
        "body": BODY,
        "created_at": "2026-09-28T08:00:00Z",
        "updated_at": "2026-09-28T08:00:00Z",
    }
    return Draft.model_validate(values | fields)


CONTEXT = CheckContext(
    references=("4711-0815",),
    known_ids=("4711-0815", "DE89370400440532013000", "sam@example.org"),
    known_texts=("Funkallee 1, 10115 Berlin",),
)


def test_every_check_has_a_plain_label() -> None:
    results = run_checks(_draft(), CONTEXT)
    assert [check.id for check in results] == list(LABELS)
    assert all(check.ok for check in results), [check for check in results if not check.ok]
    assert all(check.label == LABELS[check.id] for check in results)


def test_has_reference() -> None:
    assert has_reference(_draft(), CONTEXT).ok
    missing = has_reference(_draft(subject="Kündigung", body="hiermit kündige ich."), CONTEXT)
    assert not missing.ok and "4711-0815" in (missing.detail or "")
    unknown = has_reference(_draft(subject="Kündigung", body="hiermit kündige ich."), CheckContext())
    assert not unknown.ok and "don't know" in (unknown.detail or "")
    by_date = CheckContext(doc_date=date(2026, 9, 15))
    assert has_reference(_draft(kind="general_reply", subject="Ihr Schreiben vom 15.09.2026"), by_date).ok
    spaced = _draft(body="Kundennummer 4711 0815", subject="Kündigung")
    assert has_reference(spaced, CONTEXT).ok  # spaces, dashes and slashes are ignored


def test_has_dates() -> None:
    assert has_dates(_draft(), CONTEXT).ok
    assert has_dates(_draft(body="kündige ich zum nächstmöglichen Zeitpunkt."), CONTEXT).ok
    assert not has_dates(_draft(body="hiermit kündige ich den Vertrag."), CONTEXT).ok
    objection = _draft(kind="objection", body="lege ich gegen den Bescheid vom 15.09.2026 Einspruch ein.")
    assert has_dates(objection, CheckContext(doc_date=date(2026, 9, 15))).ok
    wrong = has_dates(objection, CheckContext(doc_date=date(2026, 9, 16)))
    assert not wrong.ok and "16.09.2026" in (wrong.detail or "")
    assert not has_dates(_draft(kind="objection", body="lege ich Einspruch ein."), CheckContext()).ok
    assert has_dates(_draft(kind="general_reply", body="Danke."), CheckContext()).ok


def test_recipient_and_sender_complete() -> None:
    assert recipient_complete(_draft(), CONTEXT).ok
    assert recipient_complete(
        _draft(recipient_block="Finanzamt\nPostfach 1234\n12345 Musterstadt"), CONTEXT
    ).ok
    no_street = recipient_complete(
        _draft(recipient_block="Finanzamt Musterstadt\n12345 Musterstadt"), CONTEXT
    )
    assert not no_street.ok and "street" in (no_street.detail or "")
    assert not recipient_complete(_draft(recipient_block="Finanzamt Musterstadt"), CONTEXT).ok
    assert not recipient_complete(_draft(recipient_block=""), CONTEXT).ok
    assert sender_complete(_draft(sender_block="Sam Rivera\nMusterweg 5, 12345 Musterstadt"), CONTEXT).ok
    no_address = sender_complete(_draft(sender_block="Sam Rivera"), CONTEXT)
    assert not no_address.ok and "Settings" in (no_address.detail or "")


@pytest.mark.parametrize("token", ["[Ihr Text]", "{contract_name}", "XXX", "TODO", "Frist ]"])
def test_no_placeholders_flags(token: str) -> None:
    result = no_placeholders(_draft(body=f"{BODY}\n\n{token}"), CONTEXT)
    assert not result.ok
    assert no_placeholders(_draft(), CONTEXT).ok
    assert not no_placeholders(_draft(enclosures=["Kopie [Datum]"]), CONTEXT).ok


def test_language_matches() -> None:
    assert language_matches(_draft(), CONTEXT).ok
    english = _draft(body="Dear Sir or Madam,\n\nI hereby cancel the contract with you. Please confirm this.")
    assert not language_matches(english, CONTEXT).ok
    assert language_matches(english.model_copy(update={"language": "en"}), CONTEXT).ok
    assert language_matches(_draft(language="fr"), CONTEXT).ok  # not checked


def test_citation_parsing() -> None:
    assert list(citations("§ 573c Abs. 1, 4 BGB")) == [("573c", "BGB")]
    assert list(citations("§§ 355, 357 AO")) == [("355", "AO"), ("357", "AO")]
    assert list(citations("§ 175 Abs. 4 S. 5 SGB V")) == [("175", "SGB V")]
    assert list(citations("nach § 5 des Vertrags")) == [("5", None)]
    assert list(citations("kein Paragraph")) == []


def test_citations_known() -> None:
    assert citations_known(_draft(body=BODY + " Siehe § 312k BGB und § 309 Nr. 9 BGB."), CONTEXT).ok
    invented = citations_known(_draft(body=BODY + " Das verstößt gegen § 999 BGB."), CONTEXT)
    assert not invented.ok and "§ 999 BGB" in (invented.detail or "")
    assert unknown_citations("§ 12 KAG NRW gilt.", source_text="Nach § 12 KAG ist …") == []
    assert unknown_citations("§ 12 KAG") == ["§ 12 KAG"]
    assert citations_known(_draft(), CONTEXT).detail == "No laws are cited."


def test_identifier_extraction() -> None:
    found = identifiers("IBAN DE89 3704 0044 0532 0130 00, Mail an x@y.de, Az. 123/456/78901 vom 15.09.2026")
    assert found == {"DE89370400440532013000", "x@y.de", "12345678901"}
    assert identifiers("am 2026-09-15 um 12345 Musterstadt") == set()


def test_no_new_identifiers() -> None:
    known = _draft(body=BODY + " Bitte buchen Sie auf DE89 3704 0044 0532 0130 00 zurück.")
    assert no_new_identifiers(known, CONTEXT).ok
    foreign = _draft(body=BODY + " Bitte überweisen Sie auf LT12 1000 0111 0100 1000.")
    result = no_new_identifiers(foreign, CONTEXT)
    assert not result.ok and "LT121000011101001000" in (result.detail or "")
    assert not no_new_identifiers(_draft(body=BODY + " Antwort an fremd@example.com"), CONTEXT).ok
    assert not no_new_identifiers(_draft(body=BODY + " Vertrag 98765432"), CONTEXT).ok
    in_address = _draft(subject="Kündigung", body="Kundennummer laut Brief: 55512345")
    assert no_new_identifiers(in_address, CheckContext(known_texts=("Ihre Nummer 555-12345",))).ok


def test_delivery_channel_ok() -> None:
    rent = send_guidance("cancellation", contract_category="rent", today=date(2026, 9, 28))
    context = CheckContext(guidance=rent)
    unchosen = delivery_channel_ok(_draft(), context)
    assert unchosen.ok and "Einwurf-Einschreiben" in (unchosen.detail or "")
    by_email = delivery_channel_ok(_draft(), CheckContext(guidance=rent, channel="email"))
    assert not by_email.ok and "signature" in (by_email.detail or "")
    assert delivery_channel_ok(_draft(), CheckContext(guidance=rent, channel="registered_letter")).ok
    sent = _draft(send_guidance=rent, sent_channel="fax")
    assert not delivery_channel_ok(sent, CheckContext()).ok
    mobile = send_guidance("cancellation", contract_category="mobile", today=date(2026, 9, 28))
    assert delivery_channel_ok(_draft(), CheckContext(guidance=mobile, channel="email")).ok
    assert delivery_channel_ok(_draft(), CheckContext()).ok
