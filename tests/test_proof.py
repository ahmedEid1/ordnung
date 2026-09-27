"""Proof of a sent letter: the written policy (``drafts.proof``), the service that stores proof files
privately (``drafts.sent``) and the Nachweis PDF (``drafts.pdf.render_nachweis``)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium
import pytest

import helpers_proof
from helpers_docs import letter_pdf, photo
from helpers_proof import DRAFT_ANSWER, SENT, TODAY, TRACKING, TRACKING_SHOWN, Gym, incoming
from ordnung import clock
from ordnung.app_context import AppContext, build_context
from ordnung.drafts import proof, sent
from ordnung.drafts.compose import DraftError, compose, mark_sent
from ordnung.drafts.pdf import render as render_letter
from ordnung.drafts.tracking import tracking_info
from ordnung.ingest.intake import IntakeError
from ordnung.ingest.pipeline import add_file
from ordnung.llm.fake import FakeBackend
from ordnung.models import Document, Draft, Profile
from ordnung.secretary.triggers import Ledger
from ordnung.views import dashboard, timeline


@pytest.fixture
def ctx(data_dir: Path) -> Iterator[AppContext]:
    clock.set_today(TODAY)
    context = build_context(data_dir, backend_obj=FakeBackend({"draft": DRAFT_ANSWER}))
    yield context
    context.close()
    clock.set_today(None)


@pytest.fixture
def gym(ctx: AppContext) -> Gym:
    return helpers_proof.gym(ctx)


async def _sent_letter(
    ctx: AppContext, where: Gym, channel: str = "registered_letter", **kwargs: Any
) -> Draft:
    return await helpers_proof.sent_letter(ctx, where, channel, **kwargs)


def _pdf_text(data: bytes) -> str:
    """The PDF's text, no-break spaces read as spaces (tracking numbers are grouped with them)."""
    document = pdfium.PdfDocument(data)
    try:
        text = "\n".join(document[i].get_textpage().get_text_range() for i in range(len(document)))
    finally:
        document.close()
    return text.replace("\u00a0", " ")


def _pages(data: bytes) -> int:
    document = pdfium.PdfDocument(data)
    try:
        return len(document)
    finally:
        document.close()


# --------------------------------------------------------------------------------------------------
# the policy
# --------------------------------------------------------------------------------------------------


def test_every_proof_kind_says_what_it_shows_and_never_claims_to_be_enough() -> None:
    for kind, info in proof.PROOF_KINDS.items():
        assert info.label and info.german and info.shows and info.does_not_show, kind
        words = f"{info.shows} {info.does_not_show}".lower()
        assert not any(claim in words for claim in ("proves", "sufficient", "legally", "guarantee")), kind
    assert "court" in proof.CAVEAT and "not legal advice" in proof.CAVEAT
    assert "Gericht" in proof.CAVEAT_DE and "keine Rechtsberatung" in proof.CAVEAT_DE


def _draft(**fields: Any) -> Draft:
    base: dict[str, Any] = {
        "id": "drf_1",
        "kind": "cancellation",
        "status": "sent",
        "sent_channel": "registered_letter",
        "sent_at": "2026-09-01",
        "created_at": "2026-08-30T10:00:00Z",
        "updated_at": "2026-09-01T10:00:00Z",
    }
    return Draft.model_validate(base | fields)


def _had(*kinds: str, day: str | None = None) -> list[proof.RecordedProof]:
    return [proof.RecordedProof(kind, day, "2026-09-05", None, None) for kind in kinds]


def _missing(draft: Draft, kinds: list[str], *, answered: bool, today: date = TODAY) -> list[str]:
    return proof.missing(draft, _had(*kinds), answered=answered, today=today)


def test_a_registered_letter_wants_its_number_the_receipt_and_the_delivery_record() -> None:
    assert _missing(_draft(), [], answered=False) == [
        proof.MISSING_TRACKING,
        proof.MISSING_POSTING,
        proof.MISSING_DELIVERY,
    ]
    numbered = _draft(tracking_number="RT123456785DE")
    assert _missing(numbered, ["posting_receipt"], answered=False) == [proof.MISSING_DELIVERY]
    assert _missing(numbered, ["posting_receipt", "delivery_record"], answered=False) == []
    assert _missing(numbered, ["posting_receipt", "return_receipt"], answered=False) == []
    assert "BAG 2 AZR 68/24" in proof.MISSING_DELIVERY and "15 months" in proof.MISSING_DELIVERY


def test_the_delivery_record_is_suggested_only_while_deutsche_post_issues_it() -> None:
    """Deutsche Post issues a copy for 15 months after posting (sent 1 Sep 2026: until 1 Dec 2027)."""
    numbered = _draft(tracking_number="RT123456785DE")
    assert _missing(numbered, ["posting_receipt"], answered=False, today=date(2027, 12, 1)) == [
        proof.MISSING_DELIVERY
    ]
    late = _missing(numbered, ["posting_receipt"], answered=False, today=date(2027, 12, 2))
    assert late == [proof.MISSING_DELIVERY_LATE]
    assert "Ask Deutsche Post" not in late[0] and "time has passed" in late[0]
    assert proof.delivery_record_obtainable(_draft(sent_at=None), date(2030, 1, 1))


def test_a_confirmed_answer_shows_the_letter_arrived() -> None:
    assert _missing(_draft(tracking_number="RT123456785DE"), ["posting_receipt"], answered=True) == []
    assert _missing(_draft(sent_channel="letter"), [], answered=True) == []
    assert _missing(_draft(sent_channel="fax"), [], answered=True) == []


@pytest.mark.parametrize("kind", sorted(proof.SENDING_DAY_KINDS))
def test_a_sending_proof_on_another_day_than_the_sending_is_pointed_out(kind: str) -> None:
    draft = _draft()  # sent 2026-09-01
    assert proof.conflicts(draft, _had(kind, day="2026-09-01")) == []
    assert proof.conflicts(draft, _had(kind)) == []  # no day: nothing to compare
    (said,) = proof.conflicts(draft, _had(kind, day="2026-09-03"))
    assert "Thu 3 Sep 2026" in said and "Tue 1 Sep 2026" in said and "correct one of them" in said
    assert proof.conflicts(draft, _had("delivery_record", day="2026-09-03")) == []
    assert proof.conflicts(_draft(status="draft", sent_at=None), _had(kind, day="2026-09-03")) == []


@pytest.mark.parametrize(
    ("channel", "have", "expected"),
    [
        ("fax", [], [proof.MISSING_FAX]),
        ("fax", ["fax_report"], []),
        ("email", [], [proof.MISSING_EMAIL]),
        ("email", ["sent_email"], []),
        ("online_button", [], [proof.MISSING_BUTTON]),
        ("online_button", ["cancel_confirmation"], []),
        ("letter", [], [proof.MISSING_LETTER]),
        ("letter", ["other"], []),
        ("in_person", [], [proof.MISSING_IN_PERSON]),
        ("portal", [], [proof.MISSING_PORTAL]),
    ],
)
def test_what_is_missing_follows_the_channel(channel: str, have: list[str], expected: list[str]) -> None:
    assert _missing(_draft(sent_channel=channel), have, answered=False) == expected


def test_a_letter_not_yet_sent_misses_nothing() -> None:
    assert _missing(_draft(status="draft", sent_at=None, sent_channel=None), [], answered=False) == []


def test_the_timeline_lists_what_was_recorded_in_order() -> None:
    tracking = tracking_info("RT123456785DE")
    recorded = [
        proof.RecordedProof("delivery_record", "2026-09-03", "2026-09-05", None, None),
        proof.RecordedProof("posting_receipt", "2026-09-01", "2026-09-01", "Filiale Mitte", None),
    ]
    events = proof.timeline(_draft(), tracking, recorded, None)
    assert [(e.date, e.kind) for e in events] == [
        ("2026-08-30", "created"),
        ("2026-09-01", "sent"),
        ("2026-09-01", "tracking"),
        ("2026-09-01", "proof"),
        ("2026-09-03", "delivered"),
    ]
    assert (
        events[2].english == f"Tracking number {TRACKING_SHOWN}" and events[2].detail == "check digit correct"
    )
    assert events[3].detail == "Filiale Mitte"
    assert events[4].german == "Zugestellt laut Auslieferungsbeleg"


def test_a_proof_without_a_day_is_never_put_on_a_day() -> None:
    """Sent 10 Sep, a posting receipt without a day added on 27 Sep: never "27 Sep · posting receipt"."""
    recorded = [
        proof.RecordedProof("posting_receipt", None, "2026-09-27", None, None),
        proof.RecordedProof("delivery_record", None, "2026-09-26", None, None),
    ]
    events = proof.timeline(_draft(sent_at="2026-09-10"), None, recorded, None)
    assert [(e.date, e.kind, e.added_on) for e in events] == [
        ("2026-08-30", "created", None),
        ("2026-09-10", "sent", None),
        (None, "proof", "2026-09-26"),  # undated ones last, apart, with the day they were added
        (None, "proof", "2026-09-27"),
    ]
    assert events[2].english == "Delivery record"  # not "Delivered —": no day of delivery was given
    assert all(event.date != "2026-09-27" for event in events)


def test_only_a_confirmed_answer_is_stated_and_a_possible_one_stays_a_hint() -> None:
    invoice = Document.model_validate(
        {
            "id": "doc_i",
            "sha256": "x",
            "filename": "i.pdf",
            "mime": "application/pdf",
            "title": "Beitragsrechnung",
            "doc_date": "2026-09-15",
            "created_at": "2026-09-15T08:00:00Z",
            "updated_at": "2026-09-15T08:00:00Z",
        }
    )
    draft = _draft(sent_at="2026-09-10")
    possible = proof.timeline(draft, None, [], None, invoice)
    assert possible[-1].kind == "possible_answer" and not possible[-1].in_nachweis
    assert "Antwort erhalten" not in possible[-1].german and "is it the answer?" in possible[-1].english
    confirmed = proof.timeline(draft, None, [], proof.RecordedAnswer(None, invoice, "letter"), invoice)
    assert [e.kind for e in confirmed][-1] == "answered" and confirmed[-1].in_nachweis
    assert confirmed[-1].german == "Antwort erhalten: „Beitragsrechnung“"
    assert all(e.kind != "possible_answer" for e in confirmed)
    noted = proof.timeline(draft, None, [], proof.RecordedAnswer("2026-09-20", None, "noted"), invoice)
    assert (noted[-1].date, noted[-1].kind, noted[-1].english) == (
        "2026-09-20",
        "answered",
        "Answered — as you noted",
    )
    confirmation = proof.timeline(draft, None, [], proof.RecordedAnswer(None, invoice, "confirmation"))
    assert confirmation[-1].german.startswith("Kündigung bestätigt")


def test_a_letter_recorded_after_it_was_sent_starts_with_its_sending() -> None:
    events = proof.timeline(_draft(created_at="2026-09-20T08:00:00Z"), None, [], None)
    assert [e.kind for e in events] == ["sent"]


def test_labels_and_waiting_words() -> None:
    assert proof.channel_label("registered_letter") == "registered letter (Einschreiben)"
    assert proof.channel_label("registered_letter", german=True) == "Einschreiben"
    assert proof.channel_label("carrier_pigeon") == "carrier pigeon"
    assert proof.channel_label(None) == "sent"
    assert proof.waits_for("address_change") is None
    assert proof.waits_for("some_new_kind") == proof.WAITING_FOR["general_reply"]
    assert proof.kind_info("nonsense") == proof.PROOF_KINDS["other"]
    assert proof.day_words("2026-09-01") == "Tue 1 Sep 2026" and proof.day_words("soon") == "soon"


# --------------------------------------------------------------------------------------------------
# storing proof
# --------------------------------------------------------------------------------------------------


async def test_marking_sent_keeps_a_checked_tracking_number(ctx: AppContext, gym: Gym) -> None:
    letter = await _sent_letter(ctx, gym, tracking_number="rt 123 456 785 de")
    assert letter.tracking_number == "RT123456785DE"
    _, item = mark_sent(ctx, letter.id, "registered_letter", SENT)
    assert item.id == proof.followup_item_id(letter.id)
    assert ctx.store.get_draft(letter.id).tracking_number == "RT123456785DE"  # type: ignore[union-attr]


async def test_marking_sent_refuses_a_mistyped_number_before_saving_anything(
    ctx: AppContext, gym: Gym
) -> None:
    draft = await compose(ctx, "cancellation", contract_id=gym.contract)
    with pytest.raises(DraftError, match="check digit"):
        mark_sent(ctx, draft.id, "registered_letter", SENT, tracking_number="RT123456784DE")
    assert ctx.store.get_draft(draft.id).status == "draft"  # type: ignore[union-attr]
    assert ctx.store.get_item(proof.followup_item_id(draft.id)) is None


async def test_the_tracking_number_can_be_set_and_removed(ctx: AppContext, gym: Gym) -> None:
    letter = await _sent_letter(ctx, gym)
    assert sent.set_tracking(ctx.store, letter.id, "0034 0434 1234").tracking_number == "003404341234"
    with pytest.raises(DraftError, match="two letters, nine digits"):
        sent.set_tracking(ctx.store, letter.id, "RT12345678DE")
    assert sent.set_tracking(ctx.store, letter.id, "  ").tracking_number is None
    unsent = await compose(ctx, "cancellation", contract_id=gym.contract)
    with pytest.raises(DraftError, match="Mark the letter as sent first"):
        sent.set_tracking(ctx.store, unsent.id, TRACKING)


async def test_a_proof_file_is_private_outgoing_and_never_sent_to_the_model(
    ctx: AppContext, gym: Gym
) -> None:
    letter = await _sent_letter(ctx, gym)
    added = await sent.add_proof(
        ctx,
        letter.id,
        photo("JPEG", size=(300, 400)),
        "beleg.jpg",
        kind="posting_receipt",
        on_date="2026-09-01",
        today=TODAY,
    )
    await ctx.worker.run_until_idle()
    document = ctx.store.get_document(added.doc_id or "")
    assert document is not None
    assert (document.ai_private, document.direction, document.source) == (
        True,
        "outgoing",
        proof.PROOF_SOURCE,
    )
    assert document.status == "processed" and document.ai_processed_at is None
    backend = ctx.llm.backend
    assert isinstance(backend, FakeBackend)
    assert [call.purpose for call in backend.calls] == ["draft"]  # composing the letter, nothing after
    logged = [entry for entry in ctx.store.list_activity(20) if entry.kind == "draft.proof"]
    assert len(logged) == 1 and "kept private, not sent to AI" in logged[0].message
    overview = sent.overview(ctx.store, letter.id, TODAY)
    assert [entry.label for entry in overview.proofs] == ["Posting receipt"]
    assert overview.proofs[0].document is not None and overview.proofs[0].document.id == document.id


async def test_proof_files_are_no_letters_of_the_ledger(ctx: AppContext, gym: Gym) -> None:
    letter = await _sent_letter(ctx, gym)
    added = await sent.add_proof(
        ctx, letter.id, letter_pdf(), "beleg.pdf", kind="delivery_record", today=TODAY
    )
    ledger = Ledger(ctx.store, TODAY)
    assert added.doc_id not in ledger.documents
    assert all(doc.id != added.doc_id for doc in dashboard(ctx.store, TODAY).recent_documents)
    everything = timeline(ctx.store, date(2026, 1, 1), date(2026, 12, 31), today=TODAY)
    assert all(entry.id != added.doc_id for entry in everything)


async def test_proof_refusals(ctx: AppContext, gym: Gym, monkeypatch: pytest.MonkeyPatch) -> None:
    letter = await _sent_letter(ctx, gym)
    unsent = await compose(ctx, "cancellation", contract_id=gym.contract)
    jpeg = photo("JPEG")
    with pytest.raises(DraftError, match="Mark the letter as sent first"):
        await sent.add_proof(ctx, unsent.id, jpeg, "a.jpg", kind="other", today=TODAY)
    with pytest.raises(DraftError, match="Choose what the proof is"):
        await sent.add_proof(ctx, letter.id, jpeg, "a.jpg", kind="selfie", today=TODAY)
    with pytest.raises(DraftError, match="future"):
        await sent.add_proof(ctx, letter.id, jpeg, "a.jpg", kind="other", on_date="2026-10-01", today=TODAY)
    with pytest.raises(DraftError, match="not a date"):
        await sent.add_proof(ctx, letter.id, jpeg, "a.jpg", kind="other", on_date="Tuesday", today=TODAY)
    with pytest.raises(DraftError, match="under 500"):
        await sent.add_proof(ctx, letter.id, jpeg, "a.jpg", kind="other", note="x" * 501, today=TODAY)
    with pytest.raises(IntakeError):
        await sent.add_proof(ctx, letter.id, b"PK\x03\x04" + bytes(200), "a.bin", kind="other", today=TODAY)
    monkeypatch.setattr(sent, "MAX_PROOFS", 1)
    await sent.add_proof(ctx, letter.id, jpeg, "a.jpg", kind="other", today=TODAY)
    with pytest.raises(DraftError, match="up to"):
        await sent.add_proof(ctx, letter.id, photo("PNG"), "b.png", kind="other", today=TODAY)
    assert len(ctx.store.list_proofs(letter.id)) == 1
    assert ctx.store.list_documents(direction="outgoing")[0].source == proof.PROOF_SOURCE


async def test_a_proof_can_be_corrected(ctx: AppContext, gym: Gym) -> None:
    letter = await _sent_letter(ctx, gym)
    added = await sent.add_proof(
        ctx, letter.id, photo("JPEG"), "a.jpg", kind="other", on_date="2026-09-02", today=TODAY
    )
    changed = sent.update_proof(
        ctx.store, letter.id, added.id, today=TODAY, kind="return_receipt", note=" signed "
    )
    assert (changed.kind, changed.on_date, changed.note) == ("return_receipt", "2026-09-02", "signed")
    cleared = sent.update_proof(ctx.store, letter.id, added.id, today=TODAY, clear_date=True, note="")
    assert (cleared.on_date, cleared.note) == (None, None)
    assert sent.update_proof(ctx.store, letter.id, added.id, today=TODAY) == cleared
    with pytest.raises(DraftError, match="future"):
        sent.update_proof(ctx.store, letter.id, added.id, today=TODAY, on_date="2027-01-01")
    other = await compose(ctx, "cancellation", contract_id=gym.contract)
    with pytest.raises(LookupError):
        sent.update_proof(ctx.store, other.id, added.id, today=TODAY, kind="other")


async def test_removing_a_proof_deletes_its_file_for_good(ctx: AppContext, gym: Gym) -> None:
    letter = await _sent_letter(ctx, gym)
    added = await sent.add_proof(ctx, letter.id, photo("JPEG"), "a.jpg", kind="posting_receipt", today=TODAY)
    original = ctx.store.get_document_file(added.doc_id or "")
    assert original is not None and original.is_file()
    sent.remove_proof(ctx.store, letter.id, added.id)
    assert ctx.store.get_document(added.doc_id or "") is None
    assert not original.exists()
    assert ctx.store.list_proofs(letter.id) == []


async def test_a_letter_already_in_ordnung_is_linked_and_kept(ctx: AppContext, gym: Gym) -> None:
    letter = await _sent_letter(ctx, gym)
    data = letter_pdf()
    known = await add_file(ctx, data, "sent-copy.pdf", private=True)
    added = await sent.add_proof(ctx, letter.id, data, "sent-copy.pdf", kind="other", today=TODAY)
    assert added.doc_id == known.id
    sent.remove_proof(ctx.store, letter.id, added.id)
    assert ctx.store.get_document(known.id) is not None


async def test_deleting_a_letter_deletes_its_proofs_and_their_files(ctx: AppContext, gym: Gym) -> None:
    letter = await _sent_letter(ctx, gym)
    one = await sent.add_proof(ctx, letter.id, photo("JPEG"), "a.jpg", kind="posting_receipt", today=TODAY)
    two = await sent.add_proof(ctx, letter.id, letter_pdf(), "b.pdf", kind="delivery_record", today=TODAY)
    sent.delete_letter(ctx.store, letter.id)
    assert ctx.store.get_draft(letter.id) is None
    assert ctx.store.list_proofs() == []
    assert (
        ctx.store.get_document(one.doc_id or "") is None and ctx.store.get_document(two.doc_id or "") is None
    )


async def test_a_proof_whose_file_is_in_the_trash_is_left_out_until_restored(
    ctx: AppContext, gym: Gym
) -> None:
    letter = await _sent_letter(ctx, gym)
    added = await sent.add_proof(ctx, letter.id, photo("JPEG"), "a.jpg", kind="posting_receipt", today=TODAY)
    ctx.store.trash_document(added.doc_id or "")
    assert sent.overview(ctx.store, letter.id, TODAY).proofs == []
    ctx.store.restore_document(added.doc_id or "")
    assert len(sent.overview(ctx.store, letter.id, TODAY).proofs) == 1


async def test_deleting_the_file_deletes_the_proof(ctx: AppContext, gym: Gym) -> None:
    letter = await _sent_letter(ctx, gym)
    added = await sent.add_proof(ctx, letter.id, photo("JPEG"), "a.jpg", kind="posting_receipt", today=TODAY)
    ctx.store.delete_document(added.doc_id or "")
    assert ctx.store.get_proof(added.id) is None


# --------------------------------------------------------------------------------------------------
# the overview and the Nachweis
# --------------------------------------------------------------------------------------------------


async def test_the_overview_brings_everything_together(ctx: AppContext, gym: Gym) -> None:
    letter = await _sent_letter(ctx, gym, tracking_number=TRACKING)
    await sent.add_proof(
        ctx, letter.id, photo("JPEG"), "a.jpg", kind="posting_receipt", on_date="2026-09-01", today=TODAY
    )
    overview = sent.overview(ctx.store, letter.id, TODAY)
    assert overview.sent and overview.channel == "registered_letter"
    assert overview.tracking is not None and overview.tracking.display == TRACKING_SHOWN
    assert overview.missing == [proof.MISSING_DELIVERY]
    assert overview.caveat == proof.CAVEAT
    assert overview.waiting is not None and overview.waiting.title == "A written confirmation of the end date"
    assert [event.kind for event in overview.timeline][-1] == "proof"


async def test_an_unsent_letter_has_an_empty_overview_and_no_nachweis(ctx: AppContext, gym: Gym) -> None:
    draft = await compose(ctx, "cancellation", contract_id=gym.contract)
    overview = sent.overview(ctx.store, draft.id, TODAY)
    assert not overview.sent and overview.proofs == [] and overview.missing == [] and overview.waiting is None
    with pytest.raises(DraftError, match="Mark the letter as sent first"):
        sent.nachweis_pdf(ctx.store, draft.id, TODAY)
    with pytest.raises(LookupError):
        sent.overview(ctx.store, "drf_missing", TODAY)


async def test_the_nachweis_holds_the_timeline_the_letter_and_the_proof_files(
    ctx: AppContext, gym: Gym
) -> None:
    letter = await _sent_letter(ctx, gym, tracking_number=TRACKING)
    await sent.add_proof(
        ctx,
        letter.id,
        photo("JPEG", size=(300, 400)),
        "beleg.jpg",
        kind="posting_receipt",
        on_date="2026-09-01",
        today=TODAY,
    )
    await sent.add_proof(
        ctx,
        letter.id,
        letter_pdf(),
        "zustellung.pdf",
        kind="delivery_record",
        on_date="2026-09-03",
        today=TODAY,
    )
    incoming(
        ctx,
        "confirmation",
        kind="cancellation_confirmation",
        title="Kündigungsbestätigung",
        doc_date="2026-09-10",
        party_id=gym.party,
        case_id=gym.case,
        direction="incoming",
    )
    data = sent.nachweis_pdf(ctx.store, letter.id, TODAY)
    text = _pdf_text(data)
    for expected in (
        "Versandnachweis",
        "Versandt per Einschreiben",
        f"Sendungsnummer {TRACKING}",
        "Prüfziffer korrekt",
        "Einlieferungsbeleg",
        "Zugestellt laut Auslieferungsbeleg",
        "Kündigung bestätigt: „Kündigungsbestätigung“",  # a confirmation of the cancelled contract
        "01.09.2026",
        "03.09.2026",
        "10.09.2026",
        "entscheidet im Streitfall das Gericht",
        "Kündigung des Vertrags",  # the letter itself
        "Anlage 2: Einlieferungsbeleg vom 01.09.2026",  # the photo's caption
    ):
        assert expected in text, expected
    letter_pages = _pages(render_letter(ctx.store.get_draft(letter.id), ctx.store.get_profile()))  # type: ignore[arg-type]
    assert _pages(data) == 1 + letter_pages + 1 + 3  # summary, letter, photo, the 3-page PDF
    assert "Ordnung" not in text.split("Kündigung des Vertrags")[0]  # no branding on the summary


def test_the_note_at_the_end_of_the_summary_is_never_split_over_two_pages() -> None:
    """However long the timeline, the caveat and the made-on line stay on one page together."""
    from ordnung.drafts import pdf as pdf_module

    draft = _draft(subject="Kündigung", recipient_block="FitWell Studios GmbH")
    facts = pdf_module.NachweisFacts(
        recipient="FitWell Studios GmbH",
        sender="Sam Rivera",
        sent="01.09.2026 · Einschreiben",
        tracking=None,
        created="28.09.2026",
        caveat_de=proof.CAVEAT_DE,
        caveat_en=proof.CAVEAT,
    )
    for count in range(8, 22):
        lines = [pdf_module.NachweisLine("01.09.2026", f"Zeile {i}", f"Line {i}") for i in range(count)]
        data = pdf_module._summary(draft, Profile(name="Sam Rivera"), facts, lines, [], 1, [])
        document = pdfium.PdfDocument(data)
        try:
            pages = [document[i].get_textpage().get_text_range() for i in range(len(document))]
        finally:
            document.close()
        holding = [i for i, text in enumerate(pages) if "Hinweis" in text]
        made = [i for i, text in enumerate(pages) if "Erstellt am" in text]
        assert holding == made, count
        footer = pages[-1]
        assert f"Seite {len(pages)} von {len(pages)}" in footer and "Summary, page" in footer
