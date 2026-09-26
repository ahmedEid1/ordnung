"""Template letters (withdrawal, more time, instalments, defect, data access, receipts, deposit, new
address) and the objections the law gives court orders and a landlord's notice.

The legally operative sentences are fixed (German letter, English reference); the checks, sending
advice, notes and follow-up are pinned per kind, and so are the refusals (missing or invalid facts).
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from fixtures_llm import iban
from ordnung import clock
from ordnung.app_context import AppContext, build_context
from ordnung.drafts import templates
from ordnung.drafts.checks import unknown_citations
from ordnung.drafts.compose import DraftError, compose, mark_sent
from ordnung.drafts.template_letters import (
    IBAN_PLACEHOLDER,
    TEMPLATES,
    TemplateError,
    TemplateInput,
    format_money,
    missing_facts,
    template_letter,
)
from ordnung.llm.base import LLMError, LLMRequest, LLMResponse
from ordnung.llm.fake import FakeBackend
from ordnung.models import DateSpec, Draft, Identifier, LetterDetails, Profile, Remedy
from test_api_support import api_for

TODAY = date(2026, 9, 28)
MY_IBAN = iban("DE", "500105175407324931")


class NoModel(FakeBackend):
    """Claude is signed out: every letter is the fixed text with the code-built translation."""

    async def complete(self, req: LLMRequest) -> LLMResponse:
        self.calls.append(req)
        raise LLMError("Claude is not signed in")


@pytest.fixture
def ctx(data_dir: Path) -> Iterator[AppContext]:
    clock.set_today(TODAY)
    context = build_context(data_dir, backend_obj=NoModel({}))
    yield context
    context.close()
    clock.set_today(None)


def _doc(ctx: AppContext, label: str, text: str = "", **fields: Any) -> str:
    doc = ctx.store.add_document(
        sha256=hashlib.sha256(label.encode()).hexdigest(),
        filename=f"{label}.pdf",
        mime="application/pdf",
        file_path=f"files/{label}.pdf",
    )
    ctx.store.update_document(doc.id, status="processed", **fields)
    if text:
        page = {
            "page": 1,
            "width": 1000,
            "height": 1414,
            "image_path": "x.jpg",
            "text": text,
            "text_source": "text",
        }
        ctx.store.set_pages(doc.id, [page])
    return doc.id


@pytest.fixture
def ids(ctx: AppContext) -> dict[str, str]:
    store = ctx.store
    store.save_profile(
        Profile(
            name="Sam Rivera",
            address="Beispielweg 5\n12345 Musterstadt",
            email="sam@example.org",
            language="en",
        )
    )
    shop = store.add_party(
        name="Technik Versand GmbH", kind="retailer", address="Lagerstraße 9, 20095 Hamburg"
    ).id
    landlord = store.add_party(
        name="Wohnbau Muster GmbH", kind="landlord", address="Hofweg 3, 12345 Musterstadt"
    ).id
    fa = store.add_party(
        name="Finanzamt Musterstadt", kind="tax_office", address="Steuerplatz 2, 12345 Musterstadt"
    ).id
    schufa = store.add_party(
        name="SCHUFA Holding AG", kind="company", address="Postfach 10 34 41, 50474 Köln"
    ).id
    court = store.add_party(
        name="Amtsgericht Hagen", kind="authority", address="Heinitzstraße 42, 58097 Hagen"
    ).id
    statement = _doc(
        ctx,
        "statement",
        text="Betriebskostenabrechnung. Abrechnungszeitraum: 01.01.2025 - 31.12.2025. Nachzahlung 120,00 EUR.",
        kind="utility_bill",
        title="Operating-cost statement 2025",
        doc_date="2026-09-10",
        party_id=landlord,
    )
    tax = _doc(
        ctx,
        "tax",
        kind="tax_assessment",
        title="Income tax 2025",
        doc_date="2026-09-15",
        party_id=fa,
        references=[Identifier(label="Steuernummer", value="123/456/78901")],
    )
    store.add_item(
        kind="payment", title="Pay", due_date="2026-10-15", amount=1234.56, doc_id=tax, party_id=fa
    )
    store.add_item(
        kind="deadline",
        title="Reply",
        due_date="2026-10-12",
        doc_id=tax,
        party_id=fa,
        date_spec=DateSpec(type="relative", nature="declaration"),
    )
    order = _doc(
        ctx,
        "order",
        kind="court_payment_order",
        title="Mahnbescheid",
        doc_date="2026-09-21",
        party_id=court,
        references=[Identifier(label="Geschäftsnummer", value="26-1234567-0-8")],
        remedy=Remedy(type="none"),
    )
    enforcement = _doc(
        ctx,
        "vb",
        kind="enforcement_order",
        title="Vollstreckungsbescheid",
        doc_date="2026-09-21",
        party_id=court,
    )
    notice = _doc(
        ctx, "notice", kind="landlord_notice", title="Kündigung", doc_date="2026-09-20", party_id=landlord
    )
    return {
        "shop": shop,
        "landlord": landlord,
        "fa": fa,
        "schufa": schufa,
        "statement": statement,
        "tax": tax,
        "order": order,
        "enforcement": enforcement,
        "notice": notice,
    }


def _check(draft: Draft, check_id: str) -> bool:
    return next(check.ok for check in draft.checks if check.id == check_id)


# ------------------------------------------------------------------------------------ templates


def _inp(**details: Any) -> TemplateInput:
    extra = {k: details.pop(k) for k in list(details) if k in TemplateInput.__dataclass_fields__}
    return TemplateInput(details=LetterDetails(**details), **extra)


def test_every_draft_template_kind_is_registered() -> None:
    from ordnung.models import TemplateDraftKind

    assert set(TemplateDraftKind.__args__) == set(TEMPLATES)  # type: ignore[attr-defined]


def test_withdrawal_letter() -> None:
    de = template_letter(
        "withdrawal",
        "de",
        _inp(
            subject_matter="Kaffeemaschine",
            ordered_on="2026-09-10",
            received_on="2026-09-14",
            reference="Bestellnummer 991",
        ),
    )
    assert de.paragraphs[0] == (
        "hiermit widerrufe ich den von mir abgeschlossenen Vertrag über „Kaffeemaschine“ (bestellt am "
        "10.09.2026, erhalten am 14.09.2026)."
    )
    assert de.subject == "Widerruf des Vertrags über „Kaffeemaschine“ – Bestellnummer 991"
    en = template_letter("withdrawal", "en", _inp(topic="Zeitschriften-Abo"))
    assert en.paragraphs[0] == "I hereby withdraw from the contract I concluded for “Zeitschriften-Abo”."
    assert "refund all payments" in en.paragraphs[1]


def test_extension_letter() -> None:
    de = template_letter(
        "extension_request",
        "de",
        _inp(until="2026-10-31", deadline=date(2026, 10, 12), doc_date=date(2026, 9, 15)),
    )
    assert de.paragraphs[0] == (
        "zu Ihrem Schreiben vom 15.09.2026 bitte ich Sie, die mir bis zum 12.10.2026 gesetzte Frist bis zum "
        "31.10.2026 zu verlängern."
    )
    en = template_letter("extension_request", "en", _inp(until="2026-10-31"))
    assert en.paragraphs[0] == "I kindly ask you to extend the deadline you set me until 31 October 2026."
    assert en.subject == "Request for an extension of the deadline"
    asked = TemplateInput(details=LetterDetails(until="2026-10-01", deadline="2026-10-12"))
    with pytest.raises(TemplateError, match="later than the current deadline"):
        template_letter("extension_request", "de", asked)


def test_payment_plan_letters() -> None:
    general = template_letter(
        "payment_plan",
        "de",
        _inp(instalment=50, first_instalment="2026-11-01", amount=480, doc_date=date(2026, 9, 1)),
    )
    assert general.paragraphs[0] == (
        "zu Ihrer Forderung aus Ihrem Schreiben vom 01.09.2026 in Höhe von 480,00 € biete ich Ihnen an, den "
        "Betrag in monatlichen Raten von 50,00 € zu zahlen, beginnend am 01.11.2026."
    )
    tax = template_letter(
        "payment_plan",
        "de",
        _inp(instalment=200, first_instalment="2026-11-01", amount=1234.56, tax_office=True),
    )
    assert (
        tax.paragraphs[0]
        == "hiermit beantrage ich die Stundung der festgesetzten Steuer in Höhe von 1.234,56 € nach § 222 AO."
    )
    assert (
        tax.paragraphs[2] == "Die sofortige Zahlung des vollen Betrags wäre für mich eine erhebliche Härte."
    )
    en_tax = template_letter(
        "payment_plan",
        "en",
        _inp(instalment=200, first_instalment="2026-11-01", tax_office=True, doc_date=date(2026, 9, 15)),
    )
    assert (
        "deferral (Stundung) of the tax assessed by the notice of 15 September 2026 under § 222 AO"
        in en_tax.paragraphs[0]
    )
    en = template_letter("payment_plan", "en", _inp(instalment=50, first_instalment="2026-11-01"))
    assert (
        en.paragraphs[0]
        == "Regarding your claim, I offer to pay the amount in monthly instalments of €50.00, starting on 1 November 2026."
    )
    with pytest.raises(TemplateError, match="more than the amount"):
        template_letter("payment_plan", "de", _inp(instalment=600, first_instalment="2026-11-01", amount=480))


def test_defect_letter() -> None:
    de = template_letter(
        "defect_notice",
        "de",
        _inp(
            defect="Die Heizung im Bad funktioniert nicht",
            noticed_on="2026-09-20",
            fix_by="2026-10-10",
            address="Beispielweg 5\n12345 Musterstadt",
        ),
    )
    assert de.paragraphs == (
        "hiermit zeige ich Ihnen einen Mangel in meiner Wohnung Beispielweg 5, 12345 Musterstadt an: Die "
        "Heizung im Bad funktioniert nicht.",
        "Der Mangel besteht seit dem 20.09.2026.",
        "Bitte beseitigen Sie den Mangel bis zum 10.10.2026.",
        "Bis zur Beseitigung behalte ich mir vor, die Miete zu mindern.",
    )
    en = template_letter("defect_notice", "en", _inp(defect="The heating is broken."))
    assert en.paragraphs[1] == "Please repair it without delay."
    assert en.subject == "Notice of a defect"


def test_data_access_letter() -> None:
    schufa = template_letter("data_access", "de", _inp(schufa=True))
    assert schufa.subject == "Auskunftsersuchen nach Art. 15 DSGVO"
    assert any("Scorewerte" in p for p in schufa.paragraphs)
    assert schufa.paragraphs[-1].endswith("(Art. 12 Abs. 3 DSGVO).")
    en = template_letter("data_access", "en", _inp())
    assert not any("score" in p for p in en.paragraphs)
    assert "free copy of the data (Art. 15(3) GDPR)" in en.paragraphs[1]


def test_receipts_letter() -> None:
    de = template_letter(
        "receipts_inspection", "de", _inp(period="01.01.2025 – 31.12.2025", doc_date=date(2026, 9, 10))
    )
    assert de.paragraphs[0] == (
        "zu Ihrer Betriebskostenabrechnung vom 10.09.2026 für den Abrechnungszeitraum 01.01.2025 – 31.12.2025 "
        "bitte ich um Einsicht in die Abrechnungsbelege (§ 556 Abs. 4 BGB)."
    )
    en = template_letter("receipts_inspection", "en", _inp())
    assert en.paragraphs[0].startswith("Regarding your operating-cost statement, I ask")


def test_deposit_letter() -> None:
    details = LetterDetails(moved_out_on="2026-08-31", amount=1500, old_address="Altweg 1, 12345 Musterstadt")
    de = template_letter("deposit_return", "de", TemplateInput(details=details, iban=MY_IBAN))
    assert de.paragraphs[0] == (
        "das Mietverhältnis über die Wohnung Altweg 1, 12345 Musterstadt ist beendet; die Wohnung habe ich am "
        "31.08.2026 an Sie zurückgegeben."
    )
    assert f"IBAN {MY_IBAN}" in de.paragraphs[1] and "1.500,00 €" in de.paragraphs[1]
    en = template_letter("deposit_return", "en", _inp(moved_out_on="2026-08-31"))
    assert IBAN_PLACEHOLDER in en.paragraphs[1] and en.subject == "Return of the rent deposit"


def test_address_letter() -> None:
    de = template_letter(
        "address_change",
        "de",
        _inp(
            address="Neuweg 2\n12345 Musterstadt",
            old_address="Altweg 1, 12345 Musterstadt",
            moved_on="2026-10-01",
        ),
    )
    assert de.paragraphs == (
        "bitte beachten Sie, dass sich meine Anschrift zum 01.10.2026 geändert hat.",
        "Meine neue Anschrift lautet: Neuweg 2, 12345 Musterstadt.",
        "Meine bisherige Anschrift war: Altweg 1, 12345 Musterstadt.",
        "Bitte senden Sie Ihre Post künftig an meine neue Anschrift.",
    )
    en = template_letter("address_change", "en", _inp(new_address="Neuweg 2, 12345 Musterstadt"))
    assert en.paragraphs[0] == "Please note that my address has changed."


def test_missing_and_invalid_facts() -> None:
    assert missing_facts("withdrawal", _inp()) == ["what you ordered or agreed to"]
    assert missing_facts("withdrawal", _inp(topic="Abo")) == []
    assert missing_facts("payment_plan", _inp()) == [
        "the monthly instalment you offer",
        "the day of the first instalment",
    ]
    assert missing_facts("address_change", _inp(new_address="  ")) == ["your new address"]
    assert missing_facts("data_access", _inp()) == []
    with pytest.raises(TemplateError, match="add what is broken or wrong"):
        template_letter("defect_notice", "de", _inp())
    with pytest.raises(TemplateError, match="is not a date"):
        template_letter("withdrawal", "de", _inp(subject_matter="Abo", ordered_on="gestern"))


def test_format_money() -> None:
    assert format_money(1234.5, "de") == "1.234,50 €"
    assert format_money(1234.5, "en") == "€1,234.50"


def test_template_letters_only_cite_laws_ordnung_knows() -> None:
    letters = [
        template_letter(
            "payment_plan", "de", _inp(instalment=1, first_instalment="2026-11-01", tax_office=True)
        ),
        template_letter("receipts_inspection", "de", _inp()),
        templates.tenancy_objection("de", doc_date=date(2026, 9, 20), reference=None, flat="Beispielweg 5"),
    ]
    for parts in letters:
        assert unknown_citations(" ".join([parts.subject, *parts.paragraphs])) == []


# ------------------------------------------------------------------------------------ objections by law


def test_statutory_objection_templates() -> None:
    court = templates.objection(
        "de",
        remedy="widerspruch",
        document_kind="court_payment_order",
        doc_date=date(2026, 9, 21),
        reference="Geschäftsnummer 26-1234567-0-8",
    )
    assert court.paragraphs == (
        "hiermit lege ich gegen den Mahnbescheid vom 21.09.2026, Geschäftsnummer 26-1234567-0-8, Widerspruch ein.",
        "Ich widerspreche dem geltend gemachten Anspruch insgesamt.",
    )
    enforcement = templates.objection(
        "de",
        remedy="einspruch",
        document_kind="enforcement_order",
        doc_date=None,
        reference=None,
        suspend_enforcement=True,
    )
    assert enforcement.paragraphs[2].startswith("Ich beantrage, die Zwangsvollstreckung")
    en = templates.objection(
        "en",
        remedy="einspruch",
        document_kind="enforcement_order",
        doc_date=None,
        reference=None,
        suspend_enforcement=True,
    )
    assert "einstweilige Einstellung" in en.paragraphs[2]
    tenancy = templates.objection(
        "en",
        remedy="widerspruch",
        document_kind="landlord_notice",
        doc_date=date(2026, 9, 20),
        reference=None,
        flat=None,
    )
    assert tenancy.paragraphs[0] == (
        "I hereby object to your notice of 20 September 2026 terminating the tenancy and request that the tenancy "
        "be continued (§ 574 BGB)."
    )
    assert tenancy.subject == "Objection to your notice of 20 September 2026"


# ------------------------------------------------------------------------------------ compose


async def test_objection_to_a_court_order_uses_the_statutory_remedy(
    ctx: AppContext, ids: dict[str, str]
) -> None:
    draft = await compose(ctx, "objection", doc_id=ids["order"])  # the reading's remedy was "none"
    assert "gegen den Mahnbescheid vom 21.09.2026" in draft.body and "insgesamt" in draft.body
    assert draft.send_guidance is not None and draft.send_guidance.form == "written_form"
    assert any(
        c.channel == "portal" and c.label == "online-mahnantrag.de" for c in draft.send_guidance.channels
    )
    assert any("objects to the whole claim" in note for note in draft.notes_for_user)
    vb = await compose(ctx, "objection", doc_id=ids["enforcement"])
    assert "Einspruch ein." in vb.body


async def test_objection_to_a_landlords_notice(ctx: AppContext, ids: dict[str, str]) -> None:
    draft = await compose(ctx, "objection", doc_id=ids["notice"])
    assert (
        "widerspreche ich Ihrer Kündigung vom 20.09.2026 des Mietverhältnisses über die Wohnung Beispielweg 5, 12345 Musterstadt"
        in draft.body
    )
    assert draft.recipient_block.startswith("Wohnbau Muster GmbH")
    assert draft.send_guidance is not None and draft.send_guidance.form == "text_form"
    assert any("hardship" in note for note in draft.notes_for_user)
    assert _check(draft, "citations_known")


async def test_withdrawal_draft_shows_the_period(ctx: AppContext, ids: dict[str, str]) -> None:
    details = LetterDetails(subject_matter="Kaffeemaschine", received_on="2026-09-24")
    draft = await compose(ctx, "withdrawal", party_id=ids["shop"], details=details)
    assert draft.kind == "withdrawal" and "widerrufe ich" in draft.body
    assert draft.send_guidance is not None and draft.send_guidance.send_by == "2026-10-08"
    assert any("until Thu 8 Oct 2026" in note for note in draft.notes_for_user)
    assert _check(draft, "has_dates")
    assert draft.body_translation.startswith("Subject: Withdrawal")  # the code-built English reference

    late = await compose(
        ctx,
        "withdrawal",
        party_id=ids["shop"],
        details=LetterDetails(subject_matter="Abo", ordered_on="2026-08-01"),
    )
    assert late.send_guidance is not None and late.send_guidance.send_by is None
    assert any("The 14 days ended" in note and "tick that option" in note for note in late.notes_for_user)

    long = await compose(
        ctx,
        "withdrawal",
        party_id=ids["shop"],
        details=LetterDetails(subject_matter="Abo", ordered_on="2026-08-01", instructions_missing=True),
    )
    assert any("12 months and 14 days" in note for note in long.notes_for_user)

    undated = await compose(
        ctx, "withdrawal", party_id=ids["shop"], details=LetterDetails(subject_matter="Abo")
    )
    assert not _check(undated, "has_dates")
    assert any("Add when you ordered" in note for note in undated.notes_for_user)


async def test_extension_request_defaults_to_the_letters_deadline(
    ctx: AppContext, ids: dict[str, str]
) -> None:
    draft = await compose(
        ctx, "extension_request", doc_id=ids["tax"], details=LetterDetails(until="2026-11-15")
    )
    assert "bis zum 12.10.2026 gesetzte Frist bis zum 15.11.2026" in draft.body
    assert draft.send_guidance is not None and draft.send_guidance.must_arrive_by == "2026-10-12"
    assert any("can't be extended by asking" in tip for tip in draft.send_guidance.tips)
    assert _check(draft, "has_reference")


async def test_payment_plan_with_the_tax_office(ctx: AppContext, ids: dict[str, str]) -> None:
    details = LetterDetails(instalment=200, first_instalment="2026-11-01")
    draft = await compose(ctx, "payment_plan", doc_id=ids["tax"], details=details)
    assert (
        "Stundung der mit Bescheid vom 15.09.2026 festgesetzten Steuer in Höhe von 1.234,56 €" in draft.body
    )
    assert draft.send_guidance is not None and draft.send_guidance.must_arrive_by == "2026-10-15"
    assert any("interest" in note for note in draft.notes_for_user)
    assert _check(draft, "citations_known")


async def test_data_access_to_schufa_and_its_follow_up(ctx: AppContext, ids: dict[str, str]) -> None:
    draft = await compose(ctx, "data_access", party_id=ids["schufa"])
    assert "Scorewerte" in draft.body and _check(draft, "has_dates")
    assert any("meineschufa.de" in note for note in draft.notes_for_user)
    _, followup = mark_sent(ctx, draft.id, "letter", TODAY)
    assert followup.due_date == "2026-11-02"  # 35 days: one month after it arrives


async def test_receipts_request_takes_the_period_from_the_statement(
    ctx: AppContext, ids: dict[str, str]
) -> None:
    draft = await compose(ctx, "receipts_inspection", doc_id=ids["statement"])
    assert "Abrechnungszeitraum 01.01.2025 – 31.12.2025" in draft.body
    assert draft.recipient_block.startswith("Wohnbau Muster GmbH")


async def test_deposit_letter_uses_the_profile_iban(ctx: AppContext, ids: dict[str, str]) -> None:
    details = LetterDetails(moved_out_on="2026-08-31")
    without = await compose(ctx, "deposit_return", party_id=ids["landlord"], details=details)
    assert IBAN_PLACEHOLDER in without.body and not _check(without, "no_placeholders")
    assert any("Settings → Profile" in note for note in without.notes_for_user)
    ctx.store.save_profile(ctx.store.get_profile().model_copy(update={"iban": MY_IBAN}))
    with_iban = await compose(ctx, "deposit_return", party_id=ids["landlord"], details=details)
    assert MY_IBAN in with_iban.body
    assert _check(with_iban, "no_placeholders") and _check(with_iban, "no_new_identifiers")


async def test_defect_and_address_letters(ctx: AppContext, ids: dict[str, str]) -> None:
    defect = await compose(
        ctx, "defect_notice", party_id=ids["landlord"], details=LetterDetails(defect="Schimmel im Bad")
    )
    assert "Mangel in meiner Wohnung Beispielweg 5, 12345 Musterstadt an: Schimmel im Bad." in defect.body
    assert not _check(defect, "has_dates")  # neither since when nor by when
    moved = await compose(
        ctx, "address_change", party_id=ids["shop"], details=LetterDetails(moved_on="2026-10-01")
    )
    assert "Meine neue Anschrift lautet: Beispielweg 5, 12345 Musterstadt." in moved.body
    assert any("Bürgeramt" in note for note in moved.notes_for_user)


async def test_template_letters_refuse_what_they_cant_write(ctx: AppContext, ids: dict[str, str]) -> None:
    with pytest.raises(DraftError, match="Choose who the letter is for"):
        await compose(ctx, "data_access")
    with pytest.raises(DraftError, match="add the monthly instalment"):
        await compose(ctx, "payment_plan", party_id=ids["shop"])
    with pytest.raises(DraftError, match="is not a date"):
        await compose(
            ctx,
            "withdrawal",
            party_id=ids["shop"],
            details=LetterDetails(subject_matter="x", received_on="soon"),
        )


# ------------------------------------------------------------------------------------ API


async def test_api_drafts_a_template_letter_and_explains_what_is_missing(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        api.ctx.store.save_profile(Profile(name="Sam Rivera", address="Beispielweg 5, 12345 Musterstadt"))
        party = api.ctx.store.add_party(
            name="Technik Versand GmbH", kind="retailer", address="Lagerstraße 9, 20095 Hamburg"
        ).id
        body = {
            "kind": "withdrawal",
            "party_id": party,
            "details": {"subject_matter": "Kaffeemaschine", "received_on": "2026-09-24"},
        }
        response = await api.client.post("/api/drafts", json=body)
        assert response.status_code == 201, response.text
        assert response.json()["kind"] == "withdrawal"
        missing = await api.client.post("/api/drafts", json={"kind": "defect_notice", "party_id": party})
        assert missing.status_code == 422 and "what is broken" in missing.json()["detail"]
        bad = await api.client.post(
            "/api/drafts", json={"kind": "payment_plan", "party_id": party, "details": {"instalment": -5}}
        )
        assert bad.status_code == 422


async def test_profile_iban_is_validated_and_normalised(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        spaced = " ".join(MY_IBAN[i : i + 4] for i in range(0, len(MY_IBAN), 4)).lower()
        response = await api.client.put("/api/profile", json={"iban": spaced})
        assert response.status_code == 200 and response.json()["iban"] == MY_IBAN
        wrong = MY_IBAN[:-1] + ("1" if MY_IBAN[-1] != "1" else "2")
        rejected = await api.client.put("/api/profile", json={"iban": wrong})
        assert rejected.status_code == 422 and "isn't valid" in rejected.text
        cleared = await api.client.put("/api/profile", json={"iban": ""})
        assert cleared.json()["iban"] == ""


async def test_the_model_never_sees_the_persons_address_or_iban(data_dir: Path) -> None:
    """docs/privacy.md: your address is never sent — template letters that contain it (and the IBAN)
    reach the model with placeholders; the letter itself keeps them."""
    seen: list[str] = []

    def answer(req: LLMRequest) -> dict[str, Any]:
        seen.append(req.prompt)
        return {
            "subject": "",
            "body": "Vielen Dank.",
            "body_translation": "",
            "enclosures": [],
            "notes_for_user": [],
        }

    clock.set_today(TODAY)
    context = build_context(data_dir, backend_obj=FakeBackend({"draft": answer}))
    try:
        context.store.save_profile(
            Profile(
                name="Sam Rivera", address="Beispielweg 5\n12345 Musterstadt", language="en", iban=MY_IBAN
            )
        )
        landlord = context.store.add_party(
            name="Wohnbau", kind="landlord", address="Hofweg 3, 12345 Musterstadt"
        ).id
        deposit = await compose(
            context,
            "deposit_return",
            party_id=landlord,
            details=LetterDetails(moved_out_on="2026-08-31", old_address="Altweg 1, 12345 Musterstadt"),
        )
        moved = await compose(context, "address_change", party_id=landlord, details=LetterDetails())
        assert MY_IBAN in deposit.body and "Altweg 1" in deposit.body and "Beispielweg 5" in moved.body
        assert len(seen) == 2
        for prompt in seen:
            for private in (MY_IBAN, "Beispielweg 5", "Altweg 1", "12345 Musterstadt"):
                assert private not in prompt
            assert "[your address]" in prompt
        assert "[your IBAN]" in seen[0]
    finally:
        context.close()
        clock.set_today(None)


async def test_a_template_letter_to_someone_not_in_ordnung_yet(ctx: AppContext, ids: dict[str, str]) -> None:
    recipient = "SCHUFA Holding AG\nPrivatkunden ServiceCenter\nPostfach 10 34 41\n50474 Köln"
    draft = await compose(ctx, "data_access", details=LetterDetails(recipient=recipient))
    assert draft.recipient_block == recipient and draft.party_id is None
    assert "Scorewerte" in draft.body  # recognised as SCHUFA from the typed name
    assert _check(draft, "recipient_complete")
    with pytest.raises(DraftError, match="or type their name and address"):
        await compose(ctx, "data_access", details=LetterDetails())
    # a known party wins over a typed recipient
    known = await compose(
        ctx, "data_access", party_id=ids["shop"], details=LetterDetails(recipient=recipient)
    )
    assert known.recipient_block.startswith("Technik Versand GmbH")
