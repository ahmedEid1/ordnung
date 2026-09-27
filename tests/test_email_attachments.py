"""E-mail attachments (``ingest.attachments``): the policy on crafted messages, and end to end through
the pipeline with the FakeBackend — an e-mailed bill becomes two letters in one thread, pictures inside
the e-mail are skipped, limits refuse with a reason, at most ten are read, and the e-mail's privacy
choice (private, or waiting for the person) carries over."""

from __future__ import annotations

import asyncio
import base64
import io
import os
from collections.abc import Iterator
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from fixtures_llm import (
    ALL_LETTERS,
    DUNNING_LETTER,
    INVOICE_LETTER,
    INVOICE_PAY_QUOTE,
    TODAY,
    Letter,
    Router,
    fake_backend,
)
from helpers_docs import Line, make_pdf, photo
from ordnung import clock
from ordnung.api.routes.documents import document_detail
from ordnung.api.routes.parties import get_party
from ordnung.app_context import AppContext, build_context
from ordnung.ingest import attachments as attachments_module
from ordnung.ingest import held
from ordnung.ingest.attachments import (
    INLINE_IMAGE_MAX_BYTES,
    MAX_ATTACHMENTS,
    MAX_LISTED,
    MAX_NAME_CHARS,
    PHOTO_MIN_SIDE_PX,
    email_attachments,
    email_source,
)
from ordnung.ingest.intake import TOO_DEEP, IntakeError, normalise_upload
from ordnung.ingest.link import ATTACHMENT_ITEM_NOTE, attachment_repeats
from ordnung.ingest.pipeline import add_file, ingest_document, release_held
from ordnung.llm.fake import FakeBackend
from ordnung.models import Document, Identifier, Item
from ordnung.secretary.triggers import Ledger
from ordnung.views import dashboard

EMAIL_MARKER = "Rechnungs-E-Mail September"
EMAIL_LETTER = Letter(
    marker=EMAIL_MARKER,
    pages=((),),
    payload={
        "kind": "invoice",
        "area": "money",
        "title": "Phone bill e-mail",
        "sender": {"name": "Muster Telecom GmbH", "kind": "telecom"},
        "document_date": "2026-09-01",
        "references": [{"label": "Kundennummer", "value": "K-778899"}],
        "summary": "Muster Telecom sends the September bill as a PDF.",
        "explanation": "The bill itself is attached.",
        "items": [],
        "case_title": "Phone bill by e-mail",
    },
)
PNG_LOGO_CID = "logo.2026@muster-telecom.example"


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


@pytest.fixture
def ctx(data_dir: Path) -> Iterator[AppContext]:
    # the e-mail first: its subject also contains the invoice's marker ("Ihre Rechnung…")
    context = build_context(data_dir, backend_obj=fake_backend(Router(letters=(EMAIL_LETTER, *ALL_LETTERS))))
    yield context
    context.close()


def email_letter(marker: str, **payload: Any) -> Letter:
    """An e-mail the FakeBackend answers for (found by ``marker`` in its subject)."""
    return Letter(marker=marker, pages=((),), payload={**EMAIL_LETTER.extraction(), **payload})


def backend(ctx: AppContext) -> FakeBackend:
    assert isinstance(ctx.llm.backend, FakeBackend)
    return ctx.llm.backend


# --------------------------------------------------------------------------------------------------
# Building e-mails
# --------------------------------------------------------------------------------------------------


def email(
    *,
    html: str | None = None,
    logo: bytes | None = None,
    subject: str = f"Ihre {EMAIL_MARKER}",
    body: str = "Guten Tag,\n\nim Anhang finden Sie Ihre Rechnung als PDF.\n\nIhr Muster Telecom Team\n",
) -> EmailMessage:
    """A SPECIMEN e-mail from Muster Telecom (plain body, optionally HTML with a ``cid:`` logo)."""
    message = EmailMessage()
    message["From"] = "Muster Telecom <rechnung@muster-telecom.example>"
    message["To"] = "Sam Rivera <sam@example.org>"
    message["Subject"] = subject
    message["Date"] = "Tue, 01 Sep 2026 09:00:00 +0200"
    message.set_content(body)
    if html is not None:
        message.add_alternative(html, subtype="html")
        if logo is not None:
            html_part = message.get_payload()[1]
            assert isinstance(html_part, EmailMessage)
            html_part.add_related(logo, "image", "png", cid=f"<{PNG_LOGO_CID}>")
    return message


def attach(message: EmailMessage, data: bytes, mime: str, filename: str | None, **extra: Any) -> None:
    maintype, subtype = mime.split("/")
    message.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename, **extra)


def png(size: tuple[int, int] = (40, 20), mode: str = "RGB") -> bytes:
    buffer = io.BytesIO()
    Image.new(mode, size, "white" if mode == "RGB" else 1).save(buffer, "PNG")
    return buffer.getvalue()


def noisy_jpeg(size: tuple[int, int]) -> bytes:
    """A photo-like JPEG well over the inline-picture size (noise does not compress)."""
    buffer = io.BytesIO()
    Image.frombytes("RGB", size, os.urandom(size[0] * size[1] * 3)).save(buffer, "JPEG", quality=90)
    assert len(buffer.getvalue()) > INLINE_IMAGE_MAX_BYTES
    return buffer.getvalue()


def nested_email(depth: int) -> bytes:
    """An e-mail whose body sits ``depth`` multipart levels deep (about 60 bytes a level)."""
    opening = b"".join(
        b'Content-Type: multipart/mixed; boundary="b%d"\r\n\r\n--b%d\r\n' % (n, n) for n in range(depth)
    )
    closing = b"".join(b"--b%d--\r\n" % n for n in reversed(range(depth)))
    head = b"From: a@example.org\r\nSubject: tief\r\nMIME-Version: 1.0\r\n"
    return head + opening + b"Content-Type: text/plain\r\n\r\nhallo\r\n" + closing


def pdf_with(text: str, pages: int = 1) -> bytes:
    return make_pdf([[Line(72, 90, f"{text} · Seite {number + 1}")] for number in range(pages)])


def emailed_bill() -> bytes:
    message = email()
    attach(message, INVOICE_LETTER.pdf(), "application/pdf", "Rechnung_0925.pdf")
    return message.as_bytes()


def attachments_of(ctx: AppContext, parent: Document) -> list[Document]:
    return ctx.store.list_documents(source=email_source(parent.id))


# --------------------------------------------------------------------------------------------------
# The policy (pure)
# --------------------------------------------------------------------------------------------------


def test_the_body_is_no_attachment_and_every_other_part_is_one_in_order() -> None:
    message = email(html="<p>Guten Tag</p>")
    attach(message, pdf_with("Rechnung"), "application/pdf", "rechnung.pdf")
    attach(message, b"PK\x03\x04 zipped", "application/zip", "belege.zip")
    attach(message, b"just notes", "text/plain", "notes.txt")
    parts = email_attachments(message.as_bytes())
    assert [(a.filename, a.decision) for a in parts.attachments] == [
        ("rechnung.pdf", "read"),
        ("belege.zip", "not_read"),
        ("notes.txt", "not_read"),  # text with a file name is an attachment, but not read from e-mails
    ]
    assert parts.more == 0
    assert parts.attachments[0].data.startswith(b"%PDF-") and parts.attachments[1].data == b""


def test_the_bytes_decide_what_is_read_never_the_declared_type_or_name() -> None:
    message = email()
    attach(message, pdf_with("Rechnung"), "application/octet-stream", "scan")
    attach(message, b"PK\x03\x04 not a pdf", "application/pdf", "rechnung.pdf")
    attach(message, photo("JPEG"), "application/octet-stream", "IMG_0001.JPG")
    decisions = [(a.filename, a.decision) for a in email_attachments(message.as_bytes()).attachments]
    assert decisions == [("scan", "read"), ("rechnung.pdf", "not_read"), ("IMG_0001.JPG", "read")]


def test_pictures_inside_the_email_are_skipped() -> None:
    logo = png((400, 400))  # a large logo is still part of the design when the HTML shows it
    message = email(html=f'<p>Hallo</p><img src="CID:{PNG_LOGO_CID.upper()}">', logo=logo)
    attach(message, png(), "image/png", "pixel.png", disposition="inline")  # small, not an attachment
    attach(message, png(), "image/png", "foto.png")  # small, but attached on purpose: read
    decisions = [(a.filename, a.decision) for a in email_attachments(message.as_bytes()).attachments]
    assert decisions == [("attachment-1.png", "inline"), ("pixel.png", "inline"), ("foto.png", "read")]


def test_a_large_inline_photo_without_a_cid_link_is_read() -> None:
    buffer = io.BytesIO()
    Image.effect_noise((400, 400), 90).convert("RGB").save(buffer, "PNG")  # noise: no compression
    assert len(buffer.getvalue()) > INLINE_IMAGE_MAX_BYTES
    message = email()
    attach(message, buffer.getvalue(), "image/png", "brief.png", disposition="inline")
    (only,) = email_attachments(message.as_bytes()).attachments
    assert only.decision == "read"


def test_pdfs_are_never_skipped_as_pictures() -> None:
    message = email()
    attach(message, pdf_with("klein"), "application/pdf", "klein.pdf", disposition="inline")
    (only,) = email_attachments(message.as_bytes()).attachments
    assert only.decision == "read"


def test_a_forwarded_email_is_listed_never_opened() -> None:
    inner = email()
    attach(inner, pdf_with("innen"), "application/pdf", "inner.pdf")
    outer = email()
    outer.add_attachment(inner, filename="weitergeleitet.eml")
    decisions = [(a.filename, a.decision) for a in email_attachments(outer.as_bytes()).attachments]
    assert decisions == [("weitergeleitet.eml", "not_read")]


def test_at_most_ten_are_read_and_the_listing_is_bounded() -> None:
    message = email()
    for number in range(MAX_ATTACHMENTS + 2):
        attach(message, pdf_with(f"Beleg {number}"), "application/pdf", f"beleg-{number}.pdf")
    decisions = [a.decision for a in email_attachments(message.as_bytes()).attachments]
    assert decisions == ["read"] * MAX_ATTACHMENTS + ["over_limit"] * 2

    many = email()
    for number in range(MAX_LISTED + 7):
        attach(many, b"x", "application/octet-stream", f"f{number}.bin")
    parts = email_attachments(many.as_bytes())
    assert len(parts.attachments) == MAX_LISTED and parts.more == 7


def test_names_are_safe_bounded_and_made_up_when_missing() -> None:
    message = email()
    attach(message, pdf_with("a"), "application/pdf", "../../etc/pass‮wd.pdf")
    attach(message, pdf_with("b"), "application/pdf", "R" * 400 + ".pdf")
    attach(message, pdf_with("c"), "application/pdf", None)
    attach(message, b"\x00\x01", "application/x-thing", None)
    names = [a.filename for a in email_attachments(message.as_bytes()).attachments]
    assert names[0] == "passwd.pdf"
    assert len(names[1]) == MAX_NAME_CHARS and names[1].endswith("….pdf")
    assert names[2:] == ["attachment-3.pdf", "attachment-4.x-thing"]


def test_deeply_nested_parts_are_walked_in_order_without_recursion() -> None:
    message = email()
    attach(message, pdf_with("tief"), "application/pdf", "tief.pdf")
    raw = message.as_bytes()
    boundary_open = b"".join(
        b'Content-Type: multipart/mixed; boundary="b%d"\n\n--b%d\n' % (level, level) for level in range(60)
    )
    boundary_close = b"".join(b"\n--b%d--\n" % level for level in reversed(range(60)))
    nested = (
        b"From: a@example.org\nSubject: nested\nMIME-Version: 1.0\n"
        + boundary_open
        + b'Content-Type: application/pdf; name="n.pdf"\nContent-Disposition: attachment; filename="n.pdf"\n'
        + b"Content-Transfer-Encoding: base64\n\n"
        + base64.encodebytes(pdf_with("n"))
        + boundary_close
    )
    assert [a.filename for a in email_attachments(raw).attachments] == ["tief.pdf"]
    assert [(a.filename, a.decision) for a in email_attachments(nested).attachments] == [("n.pdf", "read")]


def test_a_photo_pasted_into_the_text_is_read_and_a_banner_is_not() -> None:
    """Apple Mail shows attached photos through ``cid:`` links: a big photo of a page is read, a
    wide banner the HTML shows is part of the design, a small logo too."""
    html = '<p>Hallo</p><img src="cid:foto@x"><img src="cid:banner@x"><img src="cid:logo@x">'
    message = email(html=html)
    html_part = message.get_payload()[1]
    assert isinstance(html_part, EmailMessage)
    html_part.add_related(noisy_jpeg((900, 1200)), "image", "jpeg", cid="<foto@x>", filename="IMG_0412.jpeg")
    html_part.add_related(noisy_jpeg((1200, PHOTO_MIN_SIDE_PX - 400)), "image", "jpeg", cid="<banner@x>")
    html_part.add_related(png(), "image", "png", cid="<logo@x>")
    decided = [(a.filename, a.decision) for a in email_attachments(message.as_bytes()).attachments]
    assert decided == [
        ("IMG_0412.jpeg", "read"),
        ("attachment-2.jpg", "inline"),
        ("attachment-3.png", "inline"),
    ]


def test_an_email_nested_too_deeply_is_refused_with_a_reason() -> None:
    """The standard library's parser recurses once per level: such an e-mail is refused, never a crash."""
    deep = nested_email(1000)
    assert len(deep) < 100_000
    with pytest.raises(IntakeError, match="nested too deeply"):
        email_attachments(deep)
    with pytest.raises(IntakeError) as refused:
        normalise_upload(deep, "tief.eml")
    assert str(refused.value) == TOO_DEEP
    data, mime, _ = normalise_upload(nested_email(60), "flach.eml")  # an ordinary depth still reads
    assert mime == "message/rfc822" and email_attachments(data).attachments == ()


def item(doc: Document, **fields: Any) -> Item:
    stamp = "2026-09-01T09:00:00"
    values = {"id": f"itm_{doc.id}", "kind": "payment", "title": "Pay", "doc_id": doc.id}
    values |= {"created_at": stamp, "updated_at": stamp}
    return Item.model_validate({**values, **fields})


def document(doc_id: str, *, source: str = "upload", references: tuple[str, ...] = ()) -> Document:
    return Document.model_validate(
        {
            "id": doc_id,
            "sha256": doc_id,
            "filename": f"{doc_id}.pdf",
            "mime": "application/pdf",
            "source": source,
            "references": [Identifier(label="Rechnungsnummer", value=ref) for ref in references],
            "created_at": "2026-09-01T09:00:00",
            "updated_at": "2026-09-01T09:00:00",
        }
    )


def test_an_attached_bill_takes_over_the_payment_its_email_repeats() -> None:
    mail = document("doc_mail", references=("R-1",))
    bill = document("doc_bill", source=email_source("doc_mail"), references=("R-1",))
    same = dict(amount=49.99, currency="EUR", direction="out", due_date="2026-09-15")
    asked = item(mail, **same)
    assert attachment_repeats(mail, asked, bill, [item(bill, amount=50.0)])  # the same invoice number
    unnumbered = mail.model_copy(update={"references": []})
    assert attachment_repeats(unnumbered, asked, bill, [item(bill, **same)])  # the same amount and day
    assert not attachment_repeats(unnumbered, asked, bill, [item(bill, **{**same, "amount": 59.99})])
    assert not attachment_repeats(unnumbered, asked, bill, [item(bill, **{**same, "due_date": "2026-10-15"})])
    assert not attachment_repeats(unnumbered, asked, bill, [item(bill, **{**same, "direction": "in"})])
    assert not attachment_repeats(mail, asked, bill, [])  # the bill asks for nothing
    assert not attachment_repeats(mail, asked, bill, [item(bill, kind="deadline")])
    stranger = document("doc_other", references=("R-1",))  # not attached to this e-mail
    assert not attachment_repeats(mail, asked, stranger, [item(stranger, **same)])
    assert not attachment_repeats(mail, item(mail, kind="deadline"), bill, [item(bill, **same)])


# --------------------------------------------------------------------------------------------------
# Through the pipeline
# --------------------------------------------------------------------------------------------------


async def test_an_emailed_bill_becomes_two_letters_in_one_thread(ctx: AppContext) -> None:
    parent = await add_file(ctx, emailed_bill(), "rechnung.eml")
    (child,) = attachments_of(ctx, parent)
    assert child.filename == "Rechnung_0925.pdf" and child.mime == "application/pdf"
    assert child.status == "queued" and not child.ai_private

    assert await ctx.worker.run_until_idle() == 2
    parent, child = ctx.store.get_document(parent.id), ctx.store.get_document(child.id)
    assert parent is not None and child is not None
    assert (parent.status, child.status) == ("processed", "processed")
    assert parent.case_id is not None and child.case_id == parent.case_id
    assert len(ctx.store.list_cases()) == 1
    assert [item.kind for item in ctx.store.list_items(doc_id=child.id)] == ["payment"]

    detail = document_detail(ctx.store, parent.id, clock.today())
    (listed,) = detail.attachments
    assert (listed.filename, listed.outcome, listed.doc_id) == ("Rechnung_0925.pdf", "added", child.id)
    assert listed.detail == "Added as its own letter"
    assert detail.email is None
    child_detail = document_detail(ctx.store, child.id, clock.today())
    assert child_detail.email is not None and child_detail.email.id == parent.id
    assert child_detail.attachments == []
    assert "Rechnung_0925.pdf" in (ctx.store.get_document_text(parent.id))  # the e-mail still names it


@pytest.mark.parametrize("first", ["email", "attachment"])
async def test_the_thread_is_shared_whichever_is_read_first(ctx: AppContext, first: str) -> None:
    parent = await add_file(ctx, emailed_bill(), "rechnung.eml")
    (child,) = attachments_of(ctx, parent)
    order = [parent.id, child.id] if first == "email" else [child.id, parent.id]
    for doc_id in order:
        await ingest_document(ctx, doc_id)
    parent, child = ctx.store.get_document(parent.id), ctx.store.get_document(child.id)
    assert parent is not None and child is not None
    assert parent.case_id is not None and parent.case_id == child.case_id
    assert len(ctx.store.list_cases()) == 1


async def test_pictures_inside_and_other_types_become_no_letters(ctx: AppContext) -> None:
    message = email(html=f'<p>Hallo</p><img src="cid:{PNG_LOGO_CID}">', logo=png())
    attach(message, INVOICE_LETTER.pdf(), "application/pdf", "Rechnung_0925.pdf")
    attach(message, b"PK\x03\x04 zipped", "application/zip", "belege.zip")
    parent = await add_file(ctx, message.as_bytes(), "mail.eml")
    assert [doc.filename for doc in attachments_of(ctx, parent)] == ["Rechnung_0925.pdf"]
    listing = document_detail(ctx.store, parent.id, clock.today()).attachments
    assert [(a.filename, a.outcome) for a in listing] == [
        ("attachment-1.png", "inline"),
        ("Rechnung_0925.pdf", "added"),
        ("belege.zip", "not_read"),
    ]
    activity = ctx.store.list_activity(5, kinds=["email.attachments"])[0]
    assert activity.message == "Attachments of “mail.eml”: 1 added as its own letter, 2 not read"


async def test_an_attached_photo_is_read_like_an_upload(ctx: AppContext) -> None:
    message = email()
    attach(message, photo("PNG", size=(300, 200)), "image/png", "foto.png")
    parent = await add_file(ctx, message.as_bytes(), "mail.eml")
    (child,) = attachments_of(ctx, parent)
    assert child.mime == "image/jpeg" and child.filename == "foto.jpg"  # converted like any photo


@pytest.mark.filterwarnings("ignore::PIL.Image.DecompressionBombWarning")
async def test_attachments_over_a_limit_are_refused_with_the_reason(ctx: AppContext) -> None:
    message = email()
    attach(message, png((10_000, 9_000), mode="1"), "image/png", "riesig.png")  # 90 megapixels
    attach(message, pdf_with("Seiten", pages=61), "application/pdf", "lang.pdf")
    attach(message, b"%PDF-1.4 broken", "application/pdf", "kaputt.pdf")
    parent = await add_file(ctx, message.as_bytes(), "mail.eml")
    assert attachments_of(ctx, parent) == []
    listing = document_detail(ctx.store, parent.id, clock.today()).attachments
    assert [(a.filename, a.outcome, a.doc_id) for a in listing] == [
        ("riesig.png", "refused", None),
        ("lang.pdf", "refused", None),
        ("kaputt.pdf", "refused", None),
    ]
    assert listing[0].detail == "This image is too large to process safely."
    assert listing[1].detail == "This document has 61 pages; the limit is 60 pages per document."
    assert "could not be opened" in listing[2].detail


async def test_at_most_ten_attachments_become_letters(ctx: AppContext) -> None:
    message = email()
    for number in range(MAX_ATTACHMENTS + 2):
        attach(message, pdf_with(f"Beleg {number}"), "application/pdf", f"beleg-{number:02d}.pdf")
    parent = await add_file(ctx, message.as_bytes(), "belege.eml")
    assert len(attachments_of(ctx, parent)) == MAX_ATTACHMENTS
    listing = document_detail(ctx.store, parent.id, clock.today()).attachments
    assert [a.outcome for a in listing] == ["added"] * MAX_ATTACHMENTS + ["over_limit"] * 2
    assert listing[-1].detail == f"Only the first {MAX_ATTACHMENTS} attachments of an e-mail are read"


async def test_attachments_of_a_private_email_stay_private(ctx: AppContext) -> None:
    parent = await add_file(ctx, emailed_bill(), "rechnung.eml", private=True)
    (child,) = attachments_of(ctx, parent)
    assert child.ai_private
    await ctx.worker.run_until_idle()
    assert backend(ctx).calls == []  # no model ever saw the e-mail or its bill
    assert {doc.status for doc in ctx.store.list_documents()} == {"processed"}


async def test_attachments_of_a_waiting_email_wait_and_are_answered_with_it(ctx: AppContext) -> None:
    parent = await add_file(ctx, emailed_bill(), "rechnung.eml", hold=True, source="folder")
    (child,) = attachments_of(ctx, parent)
    assert (child.status, child.ai_private, parent.status) == ("held", True, "held")
    await ctx.worker.run_until_idle()
    assert backend(ctx).calls == []
    assert [doc.id for doc in held.waiting(ctx.store)] == [parent.id, child.id]

    answer = release_held(ctx, [parent.id])  # "Read" for the e-mail reads what it brought as well
    assert [doc.id for doc in answer.documents] == [parent.id, child.id] and len(answer.jobs) == 2
    await ctx.worker.run_until_idle()
    parent, child = ctx.store.get_document(parent.id), ctx.store.get_document(child.id)
    assert parent is not None and child is not None
    assert (parent.status, child.status) == ("processed", "processed")
    assert not parent.ai_private and not child.ai_private and parent.case_id == child.case_id


async def test_keeping_a_waiting_email_private_keeps_its_attachments_private(ctx: AppContext) -> None:
    parent = await add_file(ctx, emailed_bill(), "rechnung.eml", hold=True, source="folder")
    (child,) = attachments_of(ctx, parent)
    await ctx.worker.run_until_idle()
    answer = held.keep_private(ctx.store, [parent.id])
    assert [doc.id for doc in answer.documents] == [parent.id, child.id]
    assert all(doc.status == "processed" and doc.ai_private for doc in ctx.store.list_documents())
    assert held.waiting(ctx.store) == [] and backend(ctx).calls == []


async def test_a_known_attachment_is_linked_not_added_again(ctx: AppContext) -> None:
    upload = await add_file(ctx, INVOICE_LETTER.pdf(), "rechnung.pdf")
    parent = await add_file(ctx, emailed_bill(), "rechnung.eml")
    assert attachments_of(ctx, parent) == []
    (listed,) = document_detail(ctx.store, parent.id, clock.today()).attachments
    assert (listed.outcome, listed.doc_id, listed.detail) == ("known", upload.id, "Already in Ordnung")


async def test_a_deleted_attachment_is_no_longer_linked(ctx: AppContext) -> None:
    parent = await add_file(ctx, emailed_bill(), "rechnung.eml")
    (child,) = attachments_of(ctx, parent)
    ctx.store.trash_document(child.id)
    (listed,) = document_detail(ctx.store, parent.id, clock.today()).attachments
    assert (listed.outcome, listed.doc_id) == ("added", None)
    ctx.store.trash_document(parent.id)
    assert document_detail(ctx.store, child.id, clock.today()).email is None


async def test_adding_a_trashed_email_again_restores_its_attachments(ctx: AppContext) -> None:
    data = emailed_bill()  # (each new message gets a random MIME boundary)
    parent = await add_file(ctx, data, "rechnung.eml")
    (child,) = attachments_of(ctx, parent)
    ctx.store.trash_document(parent.id)
    ctx.store.trash_document(child.id)
    again = await add_file(ctx, data, "rechnung.eml")
    assert again.id == parent.id and again.deleted_at is None
    restored = ctx.store.get_document(child.id)
    assert restored is not None and restored.deleted_at is None
    assert len(ctx.store.list_activity(20, kinds=["email.attachments"])) == 1  # listed once, when new


async def test_an_email_without_attachments_logs_nothing_about_them(ctx: AppContext) -> None:
    parent = await add_file(ctx, email().as_bytes(), "mail.eml")
    assert attachments_of(ctx, parent) == []
    assert ctx.store.list_activity(10, kinds=["email.attachments"]) == []
    assert document_detail(ctx.store, parent.id, clock.today()).attachments == []


@pytest.mark.parametrize(
    "references",
    [[], [{"label": "Kundennummer", "value": "K-778899"}]],
    ids=["no-reference", "customer-number"],
)
async def test_a_payment_reminder_attached_to_an_email_joins_its_invoices_thread(
    data_dir: Path, references: list[dict[str, str]]
) -> None:
    """The e-mail is read first (its text is short) and opens a thread; the reminder it brought still
    threads by its own invoice number — pay once, not twice — and the e-mail follows it there."""
    marker = "Zahlungserinnerung per E-Mail Oktober"
    mail_letter = email_letter(marker, kind="other", title="Reminder e-mail", references=references, items=[])
    context = build_context(data_dir, backend_obj=fake_backend(Router(letters=(mail_letter, *ALL_LETTERS))))
    try:
        invoice = await add_file(context, INVOICE_LETTER.pdf(), "rechnung.pdf")
        await context.worker.run_until_idle()
        message = email(subject=marker, body="Guten Tag,\nanbei Ihre Zahlungserinnerung.\n")
        attach(message, DUNNING_LETTER.pdf(), "application/pdf", "Mahnung.pdf")
        parent = await add_file(context, message.as_bytes(), "mahnung.eml")
        (reminder,) = attachments_of(context, parent)
        for doc_id in (parent.id, reminder.id):  # the e-mail first
            await ingest_document(context, doc_id)
        invoice, parent, reminder = (context.store.get_document(d.id) for d in (invoice, parent, reminder))
        assert invoice is not None and parent is not None and reminder is not None
        assert reminder.case_id == invoice.case_id and parent.case_id == invoice.case_id
        assert any("Pay the amount asked here once" in warning for warning in reminder.warnings)
        ledger = Ledger(context.store, clock.today())
        (invoice_payment,) = context.store.list_items(doc_id=invoice.id, kind="payment")
        assert ledger.is_superseded_by_reminder(invoice_payment)
        to_pay = [i.doc_id for i in ledger.actionable_items() if i.kind == "payment"]
        assert to_pay == [reminder.id]
        assert {i.case_id for i in context.store.list_items(doc_id=parent.id)} <= {invoice.case_id}
    finally:
        context.close()


async def test_an_email_that_repeats_its_attached_bill_is_counted_once(data_dir: Path) -> None:
    """Most bills come as an e-mail that repeats the amount and date above the attached PDF: both are
    read, the bill's to-do counts, and the e-mail's is set aside (deleting the bill brings it back)."""
    marker = "Ihre Mobilfunkrechnung ist da"
    repeated = INVOICE_LETTER.extraction()
    repeated.update(
        title="Phone bill e-mail", summary="The bill is attached.", case_title="Phone bill e-mail"
    )
    context = build_context(
        data_dir, backend_obj=fake_backend(Router(letters=(Letter(marker, ((),), repeated), *ALL_LETTERS)))
    )
    try:
        message = email(
            subject=marker,
            body=f"Guten Tag,\nIhre Rechnung Nr. R-2026-0815, Kundennummer: K-778899.\n{INVOICE_PAY_QUOTE}\n",
        )
        attach(message, INVOICE_LETTER.pdf(), "application/pdf", "Rechnung_0925.pdf")
        parent = await add_file(context, message.as_bytes(), "rechnung.eml")
        await context.worker.run_until_idle()
        (bill,) = attachments_of(context, parent)
        (mail_payment,) = context.store.list_items(doc_id=parent.id, kind="payment")
        (bill_payment,) = context.store.list_items(doc_id=bill.id, kind="payment")
        assert (mail_payment.amount, mail_payment.due_date) == (bill_payment.amount, bill_payment.due_date)

        today = clock.today()
        ledger = Ledger(context.store, today)
        assert ledger.is_covered_by_attachment(mail_payment) and not ledger.is_covered_by_attachment(
            bill_payment
        )
        assert [i.id for i in ledger.actionable_items() if i.kind == "payment"] == [bill_payment.id]
        assert dashboard(context.store, today).money.due_this_month == pytest.approx(49.99)
        (shown,) = [i for i in document_detail(context.store, parent.id, today).items if i.kind == "payment"]
        assert shown.description == ATTACHMENT_ITEM_NOTE
        party = get_party(bill.party_id or "", context.store, today)
        assert [(a.item_id, a.reason, a.replaced_by) for a in party.set_aside] == [
            (mail_payment.id, "attached", bill.id)
        ]

        context.store.trash_document(bill.id)  # the bill goes: the e-mail's to-do counts again
        assert dashboard(context.store, today).money.due_this_month == pytest.approx(49.99)
        assert not Ledger(context.store, today).is_covered_by_attachment(mail_payment)
    finally:
        context.close()


async def test_a_waiting_email_is_named_by_its_subject_and_sender(ctx: AppContext) -> None:
    parent = await add_file(ctx, emailed_bill(), "mail.eml", hold=True, source="folder")
    await ctx.worker.run_until_idle()
    stored = ctx.store.get_document(parent.id)
    assert stored is not None and stored.status == "held" and backend(ctx).calls == []
    assert stored.title == f"Ihre {EMAIL_MARKER} · Muster Telecom"
    (child,) = attachments_of(ctx, parent)
    assert ctx.store.get_document(child.id).title == "Rechnung_0925.pdf"  # type: ignore[union-attr]


async def test_an_email_listing_says_what_each_attachment_is_now(ctx: AppContext) -> None:
    message = email()
    for number in range(MAX_LISTED + 3):
        attach(message, f"Notiz {number}".encode(), "text/plain", f"notiz-{number}.txt")
    attach(message, INVOICE_LETTER.pdf(), "application/pdf", "Rechnung_0925.pdf")
    parent = await add_file(ctx, message.as_bytes(), "mail.eml", hold=True, source="folder")
    detail = document_detail(ctx.store, parent.id, clock.today())
    assert detail.attachments_more == 4 and len(detail.attachments) == MAX_LISTED
    assert {a.status for a in detail.attachments} == {None}  # listed only

    bill_mail = await add_file(ctx, emailed_bill(), "rechnung.eml", hold=True, source="folder")
    (child,) = attachments_of(ctx, bill_mail)
    (listed,) = document_detail(ctx.store, bill_mail.id, clock.today()).attachments
    assert (listed.doc_id, listed.status) == (child.id, "held")
    release_held(ctx, [child.id])  # read on its own page
    (listed,) = document_detail(ctx.store, bill_mail.id, clock.today()).attachments
    assert listed.status == "queued"


async def test_an_email_stopped_before_its_attachments_gets_them_when_added_again(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = emailed_bill()
    real = attachments_module.email_attachments

    def stopped(_data: bytes) -> Any:
        raise asyncio.CancelledError  # Ordnung quits while the e-mail is being added

    monkeypatch.setattr("ordnung.ingest.pipeline.email_attachments", stopped)
    with pytest.raises(asyncio.CancelledError):
        await add_file(ctx, data, "rechnung.eml", hold=True, source="folder")
    (parent,) = ctx.store.list_documents()
    monkeypatch.setattr("ordnung.ingest.pipeline.email_attachments", real)
    again = await add_file(ctx, data, "rechnung.eml", hold=True, source="folder")
    assert again.id == parent.id
    (child,) = attachments_of(ctx, parent)
    assert (child.status, child.ai_private) == ("held", True)  # the e-mail's choice, as it waits
    assert await add_file(ctx, data, "rechnung.eml") and len(attachments_of(ctx, parent)) == 1
