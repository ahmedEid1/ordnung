"""E-mail attachments (``ingest.attachments``): the policy on crafted messages, and end to end through
the pipeline with the FakeBackend — an e-mailed bill becomes two letters in one thread, pictures inside
the e-mail are skipped, limits refuse with a reason, at most ten are read, and the e-mail's privacy
choice (private, or waiting for the person) carries over."""

from __future__ import annotations

import base64
import io
from collections.abc import Iterator
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from fixtures_llm import ALL_LETTERS, INVOICE_LETTER, TODAY, Letter, Router, fake_backend
from helpers_docs import Line, make_pdf, photo
from ordnung import clock
from ordnung.api.routes.documents import document_detail
from ordnung.app_context import AppContext, build_context
from ordnung.ingest import held
from ordnung.ingest.attachments import (
    INLINE_IMAGE_MAX_BYTES,
    MAX_ATTACHMENTS,
    MAX_LISTED,
    MAX_NAME_CHARS,
    email_attachments,
    email_source,
)
from ordnung.ingest.pipeline import add_file, ingest_document, release_held
from ordnung.llm.fake import FakeBackend
from ordnung.models import Document

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


def backend(ctx: AppContext) -> FakeBackend:
    assert isinstance(ctx.llm.backend, FakeBackend)
    return ctx.llm.backend


# --------------------------------------------------------------------------------------------------
# Building e-mails
# --------------------------------------------------------------------------------------------------


def email(*, html: str | None = None, logo: bytes | None = None) -> EmailMessage:
    """A SPECIMEN e-mail from Muster Telecom (plain body, optionally HTML with a ``cid:`` logo)."""
    message = EmailMessage()
    message["From"] = "Muster Telecom <rechnung@muster-telecom.example>"
    message["To"] = "Sam Rivera <sam@example.org>"
    message["Subject"] = f"Ihre {EMAIL_MARKER}"
    message["Date"] = "Tue, 01 Sep 2026 09:00:00 +0200"
    message.set_content(
        "Guten Tag,\n\nim Anhang finden Sie Ihre Rechnung als PDF.\n\nIhr Muster Telecom Team\n"
    )
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
