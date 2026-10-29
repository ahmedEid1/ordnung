"""Outlook ``.msg`` files (``ingest.outlook``): synthetic files of every shape (``helpers_msg``, no binary
blobs) become the same ``.eml`` every time, with the headers, text and attachments the policy keeps; what
is not an e-mail, or is signed or encrypted, is refused with its reason; hostile files are refused quickly
and with little memory, and flipped bytes never crash the converter."""

from __future__ import annotations

import builtins
import email
import email.policy
import hashlib
import importlib.metadata
import os
import struct
import subprocess
import sys
import threading
import time
import tomllib
import tracemalloc
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

from helpers_msg import (
    MAGIC,
    Attachment,
    Message,
    Recipient,
    bill,
    bill_pdf,
    build,
    build_msg,
    directory,
    entries_named,
    message_nodes,
    patched,
    patched_all,
    simple_pdf,
    storage,
    stream,
)
from helpers_timing import assert_linear
from ordnung.ingest import intake, outlook
from ordnung.ingest.attachments import email_attachments
from ordnung.ingest.intake import IntakeError, normalise_upload
from ordnung.ingest.layout_guard import text_layout_refused
from ordnung.ingest.outlook import (
    DAMAGED,
    ENCRYPTED,
    NOT_AN_EMAIL,
    NOT_OUTLOOK,
    OFFICE_FILE,
    OLE_MAGIC,
    TOO_LARGE,
    as_email,
    is_ole,
    msg_to_eml,
)
from ordnung.ingest.text import email_heading, text_document

ROOT = Path(__file__).resolve().parents[1]
PDF = bill_pdf()


def parsed(m: Message | bytes) -> EmailMessage:
    data = m if isinstance(m, bytes) else build_msg(m)
    message = email.message_from_bytes(msg_to_eml(data), policy=email.policy.default)
    assert isinstance(message, EmailMessage)
    return message


def lf(text: str) -> str:
    """Text with LF line ends (the .eml has CRLF, as RFC 5322 says)."""
    return text.replace("\r\n", "\n")


def refusal(data: bytes) -> str:
    with pytest.raises(IntakeError) as caught:
        msg_to_eml(data)
    return str(caught.value)


def attachments_of(message: EmailMessage) -> list[tuple[str | None, str, str | None, bytes]]:
    """(file name, content type, disposition, bytes) of each attachment, in order."""
    return [
        (
            part.get_filename(),
            part.get_content_type(),
            part.get_content_disposition(),
            part.get_payload(decode=True),
        )
        for part in message.iter_attachments()
    ]


# --------------------------------------------------------------------------------------------------
# The test files themselves
# --------------------------------------------------------------------------------------------------


def test_cfb_writer_output_opens_strictly() -> None:
    """The writer's files are valid compound files: olefile opens them refusing every defect."""
    import olefile

    raw = build_msg(
        bill(attachments=[Attachment("a.pdf", PDF, "application/pdf"), Attachment("fwd", method=5)])
    )
    assert raw.startswith(MAGIC) and b"%PDF-" in raw[:1024]  # the attached PDF sits in the first kilobyte
    ole = olefile.OleFileIO(io_of(raw), raise_defects=olefile.DEFECT_INCORRECT)
    try:
        names = {"/".join(path) for path in ole.listdir()}
        assert "__substg1.0_0037001F" in names
        assert "__attach_version1.0_#00000000/__substg1.0_37010102" in names
        assert ole.openstream("__attach_version1.0_#00000000/__substg1.0_37010102").read() == PDF
    finally:
        ole.close()
    assert len(entries_named(raw, "__substg1.0_0037001F")) == 2  # the subject, and the attached e-mail's


def io_of(data: bytes) -> Any:
    import io

    return io.BytesIO(data)


# --------------------------------------------------------------------------------------------------
# What an e-mail keeps
# --------------------------------------------------------------------------------------------------


def test_plain_email_round_trip() -> None:
    message = parsed(
        bill(
            subject="Ihre Rechnung September 2026 – Grüße",
            recipients=[
                Recipient("Sam Rivera", "sam@example.org"),
                Recipient("Alex Rivera", "alex@example.org", 2),
            ],
        )
    )
    assert message["Subject"] == "Ihre Rechnung September 2026 – Grüße"
    assert message["From"] == "Stadtwerke Musterstadt <rechnung@stadtwerke-musterstadt.example>"
    assert message["To"] == "Sam Rivera <sam@example.org>"
    assert message["Cc"] == "Alex Rivera <alex@example.org>"
    assert message["Date"] == "Sun, 27 Sep 2026 16:02:00 +0000"  # PR_CLIENT_SUBMIT_TIME, in UTC
    assert message["Message-ID"] == "<rechnung-2026-09@stadtwerke-musterstadt.example>"
    assert message["MIME-Version"] == "1.0"
    body = message.get_body(preferencelist=("plain",))
    assert body is not None and lf(body.get_content()) == "Guten Tag,\nanbei Ihre Rechnung für September.\n"
    assert attachments_of(message) == [("Rechnung_2026-09.pdf", "application/pdf", "attachment", PDF)]


def test_same_msg_same_bytes() -> None:
    """No generated Date, Message-ID or random boundary: the same .msg always gives the same .eml, in
    another process too (whatever its hash seed), so adding it twice finds the letter already there."""
    raw = build_msg(
        bill(html=b"<p>Guten Tag</p>", attachments=[Attachment("a.pdf", PDF), Attachment("b", method=5)])
    )
    first = msg_to_eml(raw)
    assert msg_to_eml(raw) == first
    assert b"=_ordnung_" + hashlib.sha256(raw).hexdigest()[:24].encode() in first
    probe = (
        "import hashlib, sys; from helpers_msg import Attachment, bill, build_msg, bill_pdf; "
        "from ordnung.ingest.outlook import msg_to_eml; "
        "raw = build_msg(bill(html=b'<p>Guten Tag</p>', attachments=[Attachment('a.pdf', bill_pdf()), "
        "Attachment('b', method=5)])); print(hashlib.sha256(msg_to_eml(raw)).hexdigest())"
    )
    for seed in ("1", "2"):
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": os.pathsep.join(sys.path)}
        out = subprocess.run(
            [sys.executable, "-c", probe], capture_output=True, text=True, env=env, check=True
        )
        assert out.stdout.strip() == hashlib.sha256(first).hexdigest()


def test_transport_headers_win_and_content_headers_dropped() -> None:
    """Outlook's copy of the original headers gives the values (decoded, with the sender's offset); none of
    its other lines is copied: no Received, no X-, and no Content-Type that could split the e-mail."""
    headers = (
        "Received: from mx.example by mail.example\r\n"
        "From: =?utf-8?q?M=C3=BCller_Wohnen?= <service@muster-wohnen.example>\r\n"
        "To: sam@example.org\r\n"
        "Reply-To: antworten@muster-wohnen.example\r\n"
        "Subject: Mieterhöhung zum 01.11.2026\r\n"
        "Date: Sun, 27 Sep 2026 18:02:00 +0200\r\n"
        "Message-ID: <orig@muster-wohnen.example>\r\n"
        "References: <a@muster-wohnen.example> <b@muster-wohnen.example>\r\n"
        "In-Reply-To: <b@muster-wohnen.example>\r\n"
        "Content-Type: multipart/mixed; boundary=evil\r\n"
        "X-Evil: 1\r\n\r\n"
    )
    eml = msg_to_eml(build_msg(bill(transport_headers=headers)))
    message = email.message_from_bytes(eml, policy=email.policy.default)
    assert message["From"] == "Müller Wohnen <service@muster-wohnen.example>"
    assert message["To"] == "sam@example.org"
    assert message["Reply-To"] == "antworten@muster-wohnen.example"
    assert message["Subject"] == "Mieterhöhung zum 01.11.2026"  # not the property's
    assert message["Date"] == "Sun, 27 Sep 2026 18:02:00 +0200"
    assert message["Message-ID"] == "<orig@muster-wohnen.example>"
    assert message["References"] == "<a@muster-wohnen.example> <b@muster-wohnen.example>"
    assert message["In-Reply-To"] == "<b@muster-wohnen.example>"
    assert message["Received"] is None and message["X-Evil"] is None
    assert b"evil" not in eml
    assert attachments_of(message)[0][0] == "Rechnung_2026-09.pdf"  # the real structure


def test_transport_headers_without_a_value_fall_back_to_the_properties() -> None:
    message = parsed(bill(transport_headers="Received: from x by y\r\nX-Mailer: something\r\n\r\n"))
    assert message["Subject"] == "Ihre Rechnung September 2026"
    assert message["From"] == "Stadtwerke Musterstadt <rechnung@stadtwerke-musterstadt.example>"


def test_crlf_in_properties_cannot_add_headers() -> None:
    message = parsed(
        bill(
            subject="Hallo\r\nBcc: x@evil.example\r\nX-Injected: 1",
            sender_name="Stadtwerke\nX-Other: 2",
            message_id="<a@b.example>\r\nX-Third: 3",
        )
    )
    assert message["Bcc"] is None and message["X-Injected"] is None
    assert message["X-Other"] is None and message["X-Third"] is None
    assert message["Subject"] == "Hallo Bcc: x@evil.example X-Injected: 1"


def test_exchange_sender_keeps_name_only() -> None:
    """An Exchange-only sender has an X.500 name, not an e-mail address: it is left out, the name stays,
    and a waiting e-mail is still called “Subject · Sender”."""
    exchange = "/O=EXCHANGELABS/OU=EXCHANGE ADMINISTRATIVE GROUP/CN=RECIPIENTS/CN=ABC123"
    eml = msg_to_eml(build_msg(bill(sender_smtp=None, sender_exchange=exchange)))
    message = email.message_from_bytes(eml, policy=email.policy.default)
    (sender,) = message["From"].addresses
    assert sender.display_name == "Stadtwerke Musterstadt" and b"EXCHANGE" not in eml
    assert email_heading(eml) == "Ihre Rechnung September 2026 · Stadtwerke Musterstadt"


def test_exchange_recipient_keeps_name_only() -> None:
    message = parsed(bill(recipients=[Recipient("Sam Rivera", exchange="/O=EXCHANGELABS/CN=SAM")]))
    (to,) = message["To"].addresses
    assert to.display_name == "Sam Rivera" and "EXCHANGELABS" not in str(message["To"])


def test_names_with_commas_and_quotes_stay_one_address() -> None:
    message = parsed(
        bill(
            sender_name="Müller, Hans",
            recipients=[Recipient('Rivera, "Sam"', "sam@example.org"), Recipient("Alex", "alex@example.org")],
        )
    )
    (sender,) = message["From"].addresses
    assert (sender.display_name, sender.addr_spec) == (
        "Müller, Hans",
        "rechnung@stadtwerke-musterstadt.example",
    )
    assert [(a.display_name, a.addr_spec) for a in message["To"].addresses] == [
        ('Rivera, "Sam"', "sam@example.org"),
        ("Alex", "alex@example.org"),
    ]


def test_string8_uses_message_code_page() -> None:
    """8-bit strings are decoded in the message's code page (PR_MESSAGE_CODEPAGE), not guessed."""
    western = parsed(bill(subject="Mahnung für Müller", body="Grüße\n", string8=True, codepage=1252))
    assert western["Subject"] == "Mahnung für Müller"
    body = western.get_body(preferencelist=("plain",))
    assert body is not None and lf(body.get_content()) == "Grüße\n"
    cyrillic = parsed(bill(subject="Счёт за сентябрь", sender_name="Горэнерго", string8=True, codepage=1251))
    assert cyrillic["Subject"] == "Счёт за сентябрь"
    assert cyrillic["From"].addresses[0].display_name == "Горэнерго"


def test_html_only_body() -> None:
    eml = msg_to_eml(build_msg(bill(body=None, html=b"<p>Guten Tag <b>Sam</b>, anbei die Rechnung.</p>")))
    body = email.message_from_bytes(eml, policy=email.policy.default).get_body()
    assert body is not None and body.get_content_type() == "text/html"
    assert "Guten Tag <b>Sam</b>" in body.get_content()
    assert "Guten Tag Sam, anbei die Rechnung." in text_document(eml, "message/rfc822").text


def test_plain_and_html_alternative() -> None:
    message = parsed(Message(body="Guten Tag\n", html=b"<p>Guten Tag</p>"))
    assert message.get_content_type() == "multipart/alternative"
    assert [part.get_content_type() for part in message.iter_parts()] == ["text/plain", "text/html"]
    with_attachment = parsed(bill(html=b"<p>Guten Tag</p>"))
    assert with_attachment.get_content_type() == "multipart/mixed"
    assert [part.get_content_type() for part in with_attachment.walk()] == [
        "multipart/mixed",
        "multipart/alternative",
        "text/plain",
        "text/html",
        "application/pdf",
    ]


def test_html_in_its_internet_code_page_or_utf8() -> None:
    latin = parsed(Message(body=None, html="<p>Grüße</p>".encode("cp1252"), html_cpid=1252))
    utf8 = parsed(Message(body=None, html="<p>Grüße</p>".encode()))
    as_text = parsed(Message(body=None, html_as_text="<p>Grüße</p>"))
    for message in (latin, utf8, as_text):
        body = message.get_body()
        assert body is not None and "Grüße" in body.get_content()


def test_rtf_only_body_has_no_text_but_keeps_attachments() -> None:
    """A text kept only as RTF is not converted: no body part (and no sentence made up), the PDF still comes."""
    eml = msg_to_eml(build_msg(bill(body=None, rtf=b"LZFu" + b"\0" * 40)))
    message = email.message_from_bytes(eml, policy=email.policy.default)
    assert message.get_body(preferencelist=("plain", "html")) is None
    assert attachments_of(message) == [("Rechnung_2026-09.pdf", "application/pdf", "attachment", PDF)]
    assert text_document(eml, "message/rfc822").text.splitlines()[-1] == "Attachments: Rechnung_2026-09.pdf"
    bare = parsed(Message(body=None, rtf=b"LZFu" + b"\0" * 40))  # nothing at all but headers
    assert bare["Subject"] == "Ihre Rechnung September 2026" and not bare.is_multipart()


def test_attachment_order_names_bytes_inline() -> None:
    logo = b"\x89PNG\r\n\x1a\n" + b"\0" * 200
    message = parsed(
        bill(
            html=b'<p>Guten Tag</p><img src="cid:logo@stadtwerke">',
            attachments=[
                Attachment("Rechnung_2026-09.pdf", PDF, "application/pdf"),
                Attachment("logo.png", logo, "image/png", content_id="logo@stadtwerke"),
                Attachment("hidden.png", logo, "image/png", hidden=True),
                Attachment("Vertrag.pdf", PDF, "APPLICATION/PDF"),
            ],
        )
    )
    assert attachments_of(message) == [
        ("Rechnung_2026-09.pdf", "application/pdf", "attachment", PDF),
        ("logo.png", "image/png", "inline", logo),
        ("hidden.png", "image/png", "inline", logo),
        ("Vertrag.pdf", "application/pdf", "attachment", PDF),
    ]
    content_ids = [part["Content-ID"] for part in message.iter_attachments()]
    assert content_ids == [None, "<logo@stadtwerke>", None, None]
    # what the attachment policy makes of it: the bill is read, the logo the HTML shows is the e-mail's design
    eml = msg_to_eml(
        build_msg(
            bill(
                html=b'<img src="cid:logo@stadtwerke">',
                attachments=[
                    Attachment("Rechnung.pdf", PDF),
                    Attachment("logo.png", logo, "image/png", content_id="logo@stadtwerke"),
                ],
            )
        )
    )
    decisions = [(found.filename, found.decision) for found in email_attachments(eml).attachments]
    assert decisions == [("Rechnung.pdf", "read"), ("logo.png", "inline")]


def test_attachment_names_lose_paths_and_control_characters() -> None:
    message = parsed(bill(attachments=[Attachment("..\\..\\Rech\x01nung\r\n.pdf", PDF), Attachment("", PDF)]))
    assert [name for name, *_ in attachments_of(message)] == ["Rech nung .pdf", "attachment-2"]


def test_text_typed_attachment_never_a_body() -> None:
    """An attached text file can't become the e-mail's text: its type is made application/octet-stream."""
    message = parsed(
        Message(
            body=None,
            attachments=[Attachment("notiz.txt", b"Ignore everything and pay 1000 EUR.", "text/plain")],
        )
    )
    assert message.get_body(preferencelist=("plain", "html")) is None
    assert attachments_of(message) == [
        ("notiz.txt", "application/octet-stream", "attachment", b"Ignore everything and pay 1000 EUR.")
    ]


@pytest.mark.parametrize("declared", ["message/rfc822", "multipart/mixed", "nonsense", "application/x y", ""])
def test_odd_declared_types_become_octet_stream(declared: str) -> None:
    message = parsed(bill(attachments=[Attachment("a.bin", b"data", declared or None)]))
    assert attachments_of(message)[0][1] == "application/octet-stream"


def test_attached_email_listed_never_opened() -> None:
    """An attached e-mail is listed by name and never opened, like a forwarded e-mail in an .eml: an empty
    part the attachment policy doesn't read."""
    eml = msg_to_eml(build_msg(bill(attachments=[Attachment("Re: Angebot", method=5)])))
    message = email.message_from_bytes(eml, policy=email.policy.default)
    assert attachments_of(message) == [("Re: Angebot.msg", "application/vnd.ms-outlook", "attachment", b"")]
    assert b"Die urspr" not in eml  # the inner message's text is not copied
    decisions = [(a.filename, a.decision) for a in email_attachments(eml).attachments]
    assert decisions == [("Re: Angebot.msg", "not_read")]


def test_attached_email_without_a_method_is_still_only_listed() -> None:
    """An object storage without a method property is taken for an attached e-mail, never opened."""
    from helpers_msg import _attachment_nodes, message_nodes

    nodes = message_nodes(bill(attachments=[]))
    inner = [
        node for node in _attachment_nodes(Attachment("Weitergeleitet.msg", method=5)) if node.is_storage
    ]
    nodes.append(
        storage("__attach_version1.0_#00000000", stream("__properties_version1.0", b"\0" * 8), *inner)
    )
    message = parsed(build(nodes))
    assert attachments_of(message) == [("attachment-1.msg", "application/vnd.ms-outlook", "attachment", b"")]


def test_ole_and_link_attachments_named_only() -> None:
    message = parsed(
        bill(
            attachments=[
                Attachment("Diagramm", b"ole object bytes", method=6),
                Attachment("\\\\server\\share\\Rechnung.pdf", PDF, method=2),
                Attachment("Rechnung.pdf", PDF, "application/pdf"),
            ]
        )
    )
    assert attachments_of(message) == [
        ("Diagramm", "application/octet-stream", "attachment", b""),
        ("Rechnung.pdf", "application/octet-stream", "attachment", b""),
        ("Rechnung.pdf", "application/pdf", "attachment", PDF),
    ]


def test_more_than_50_attachments_named_only_after_50() -> None:
    small = simple_pdf(["Beleg"])
    message = parsed(
        Message(attachments=[Attachment(f"beleg-{n}.pdf", small, "application/pdf") for n in range(60)])
    )
    found = attachments_of(message)
    assert [name for name, *_ in found] == [f"beleg-{n}.pdf" for n in range(60)]
    assert all(data == small for *_, data in found[:50]) and not any(data for *_, data in found[50:])


def test_bcc_left_out() -> None:
    raw = build_msg(
        bill(recipients=[Recipient("Sam", "sam@example.org"), Recipient("Geheim", "geheim@example.org", 3)])
    )
    eml = msg_to_eml(raw)
    message = email.message_from_bytes(eml, policy=email.policy.default)
    assert message["Bcc"] is None and b"geheim" not in eml.lower()
    assert message["To"] == "Sam <sam@example.org>"


def test_dates_fall_back_to_delivery_time_and_are_never_made_up() -> None:
    delivered = parsed(bill(sent=None, delivered=datetime(2026, 9, 28, 7, 30, tzinfo=UTC)))
    assert delivered["Date"] == "Mon, 28 Sep 2026 07:30:00 +0000"
    undated = parsed(bill(sent=None, message_id=None))
    assert undated["Date"] is None and undated["Message-ID"] is None


def test_header_values_are_bounded() -> None:
    message = parsed(bill(subject="Rechnung " + "x" * 5000 + "\x07\x1b[31m"))
    assert len(str(message["Subject"])) <= outlook.MAX_HEADER_CHARS and "\x1b" not in str(message["Subject"])


def test_recipients_are_bounded() -> None:
    many = [Recipient(f"Person {n}", f"p{n}@example.org") for n in range(outlook.MAX_RECIPIENTS + 20)]
    message = parsed(Message(recipients=many))
    assert len(message["To"].addresses) == outlook.MAX_RECIPIENTS


# --------------------------------------------------------------------------------------------------
# Refused, with the reason
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message_class", ["IPM.Note.SMIME", "IPM.Note.SMIME.MultipartSigned", "ipm.note.smime"]
)
def test_encrypted_refused(message_class: str) -> None:
    assert refusal(build_msg(bill(message_class=message_class))) == ENCRYPTED


@pytest.mark.parametrize(
    "message_class", ["IPM.Appointment", "IPM.Contact", "IPM.Task", "IPM.Schedule.Meeting.Request"]
)
def test_calendar_entry_refused(message_class: str) -> None:
    """Said what it is (a meeting invitation came to the person as an e-mail) and what to do instead."""
    assert refusal(build_msg(bill(message_class=message_class))) == NOT_AN_EMAIL
    assert NOT_AN_EMAIL == (
        "This Outlook file is a meeting invitation, calendar entry, contact or task, which Ordnung doesn't "
        "open. Save its attachments, or print it as a PDF, and add those."
    )


@pytest.mark.parametrize("message_class", ["IPM.Note", "ipm.note", "IPM.Note.Microsoft.Voicemail"])
def test_every_kind_of_note_is_an_email(message_class: str) -> None:
    assert parsed(bill(message_class=message_class))["Subject"] == "Ihre Rechnung September 2026"


@pytest.mark.parametrize("main", ["WordDocument", "Workbook", "Book", "PowerPoint Document"])
def test_office_file_refused(main: str) -> None:
    assert (
        refusal(build([stream(main, b"x" * 100), stream("\x05SummaryInformation", b"y" * 10)])) == OFFICE_FILE
    )


def test_other_ole_file_refused() -> None:
    assert refusal(build([stream("Contents", b"x" * 100)])) == NOT_OUTLOOK


def test_other_ole_file_named_msg_is_a_damaged_outlook_file() -> None:
    """Named ``.msg``, an OLE file without a message is an Outlook file that can't be opened: “this type is
    not supported” would contradict the list of types that names ``.msg``."""
    other = build([stream("Contents", b"x" * 100)])
    with pytest.raises(IntakeError, match="It may be damaged"):
        as_email(other, "Rechnung.msg")
    with pytest.raises(IntakeError) as caught:
        as_email(other, "Rechnung.dat")
    assert str(caught.value) == NOT_OUTLOOK


def test_without_olefile_outlook_files_say_a_part_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """An install updated without its new dependency: not “damaged, save it again”, but what to do."""
    monkeypatch.setitem(sys.modules, "olefile", None)  # import olefile fails
    assert refusal(build_msg(bill())) == outlook.MISSING_PART
    assert outlook.MISSING_PART == (
        "Ordnung can't open Outlook files on this computer because a part it needs is missing. "
        "Update or reinstall Ordnung, then add the file again."
    )


def test_outlook_item_without_a_class_is_damaged() -> None:
    assert refusal(build_msg(bill(message_class=None))) == DAMAGED


@pytest.mark.parametrize("cut", [100, 600, 3000, -700])
def test_truncated_refused(cut: int) -> None:
    raw = build_msg(bill())
    assert refusal(raw[:cut]) == DAMAGED


def test_short_input_never_opened_as_a_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """olefile takes bytes shorter than 1536 for a file name: the converter always hands it a BytesIO."""
    opened: list[object] = []
    real_open = builtins.open

    def spy(file: Any, *args: Any, **kwargs: Any) -> Any:
        opened.append(file)
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", spy)
    assert refusal(MAGIC + b"\0" * 100) == DAMAGED
    assert refusal(MAGIC + b"\0" * 1000) == DAMAGED
    assert opened == []


def test_huge_stream_claim_refused_fast() -> None:
    """A directory entry claiming 3 GB: refused before anything that size is read."""
    raw = build_msg(bill(body="x" * 5000))  # the body in regular sectors
    (body,) = entries_named(raw, "__substg1.0_1000001F")
    crafted = patched(raw, body, size=3 * 1024**3)
    assert_quick_refusal(crafted)


def test_shared_sectors_refused() -> None:
    """Many attachments pointing at the same first sector (read amplification): refused at once."""
    big = PDF + b"%" * 200_000
    raw = build_msg(Message(attachments=[Attachment(f"a{n}.pdf", big, "application/pdf") for n in range(12)]))
    first, *others = entries_named(raw, "__substg1.0_37010102")
    assert_quick_refusal(patched_all(raw, [(entry, {"start": first.start}) for entry in others]))


def test_overlapping_chains_stop_at_the_read_budget() -> None:
    """Attachments starting one sector apart inside the same large stream would read 40 MB out of a file of
    1.3 MB: at most twice the file's size is read in all, then the file is "damaged"."""
    large = PDF + b"%" * 1_000_000
    attachments = [Attachment("gross.pdf", large, "application/pdf")]
    attachments += [Attachment(f"a{n}.pdf", PDF, "application/pdf") for n in range(40)]
    raw = build_msg(Message(attachments=attachments))
    first, *others = entries_named(raw, "__substg1.0_37010102")
    changes = [
        (entry, {"start": first.start + n, "size": first.size - 512 * n}) for n, entry in enumerate(others, 1)
    ]
    crafted = patched_all(raw, changes)
    assert first.size * 40 > 20 * len(crafted)
    assert_quick_refusal(crafted)


def test_deep_sibling_chain_refused() -> None:
    """3,000 entries chained as one long branch: the parser's recursion ends in "damaged", not a crash."""
    raw = build([stream(f"s{n:05d}", b"z") for n in range(3000)])
    entries = [entry for entry in directory(raw) if entry.sid > 0]
    changes = [
        (entry, {"left": 0xFFFFFFFF, "right": entries[n + 1].sid if n + 1 < len(entries) else 0xFFFFFFFF})
        for n, entry in enumerate(entries)
    ]
    (root,) = [entry for entry in directory(raw) if entry.sid == 0]
    assert_quick_refusal(patched_all(raw, [*changes, (root, {"child": entries[0].sid})]))


def test_too_many_entries_refused_before_they_are_built(monkeypatch: pytest.MonkeyPatch) -> None:
    """A directory with more than MAX_ENTRIES entries is refused before olefile builds a single one (a 50 MB
    file could hold 400,000)."""
    import olefile.olefile as olefile_module

    built: list[int] = []
    real_init = olefile_module.OleDirectoryEntry.__init__

    def counting(self: Any, entry: bytes, sid: int, ole_file: Any) -> None:
        built.append(sid)
        real_init(self, entry, sid, ole_file)

    monkeypatch.setattr(olefile_module.OleDirectoryEntry, "__init__", counting)
    assert_quick_refusal(build([stream(f"s{n:05d}", b"") for n in range(outlook.MAX_ENTRIES + 4)]))
    assert built == []
    msg_to_eml(build_msg(bill()))
    assert built  # (the count works)


def test_lookups_stay_linear_with_many_entries() -> None:
    """Finding a stream doesn't scan every entry of its storage: reading a message with 4× the entries
    takes about 4× the time (olefile's own lookup is linear per stream, quadratic per file)."""

    def file_of(size: int) -> bytes:
        recipients = [Recipient(f"Person {n}", f"p{n}@example.org") for n in range(size)]
        # names that sort before "__recip…": olefile's own lookup scans a storage's entries in name order
        filler = [stream(f"0filler-{n:06d}", b"") for n in range(20 * size)]
        return build_msg(Message(recipients=recipients, extra=filler))

    assert_linear(file_of, 100, read=msg_to_eml)


def difat_file(fat_sectors: int, *, difat_sectors: int = 1, loop: bool = True, size: int = 1536) -> bytes:
    """A compound file whose header claims ``fat_sectors`` FAT sectors, listed by a DIFAT chain whose every
    pointer names the one FAT sector (sector 0). The chain is sectors 1 … ``difat_sectors``; with ``loop``
    its last sector points back at itself. Zeros fill the file to ``size`` bytes."""
    fat = [0xFFFFFFFF] * 128
    fat[0] = 0xFFFFFFFD  # a FAT sector
    fat[1 : 1 + difat_sectors] = [0xFFFFFFFC] * difat_sectors  # DIFAT sectors
    sectors = [struct.pack("<128I", *fat)]
    for n in range(1, difat_sectors + 1):
        following = n + 1 if n < difat_sectors else (n if loop else 0xFFFFFFFE)
        sectors.append(struct.pack("<127I", *[0] * 127) + struct.pack("<I", following))
    header = (
        MAGIC
        + b"\0" * 16
        + struct.pack("<HHHHH", 0x3E, 3, 0xFFFE, 9, 6)
        + b"\0" * 6
        + struct.pack("<IIIIIIII", 0, fat_sectors, 0xFFFFFFFE, 0, 4096, 0xFFFFFFFE, 0, 1)
        + struct.pack("<I", (fat_sectors - 109 + 126) // 127)  # the DIFAT sectors that many FAT sectors need
        + struct.pack("<109I", *[0] * 109)
    )
    return (header + b"".join(sectors)).ljust(size, b"\0")


def refused_quickly_in_a_thread(data: bytes) -> None:
    """:func:`assert_quick_refusal` in a thread of its own, given 60 s: a file that sends olefile into an
    endless loop fails the test instead of hanging the run."""
    failed: list[BaseException] = []

    def check() -> None:
        try:
            assert_quick_refusal(data)
        except BaseException as exc:
            failed.append(exc)

    worker = threading.Thread(target=check, daemon=True)
    worker.start()
    worker.join(60)
    assert not worker.is_alive(), "still reading the file after 60 s"
    if failed:
        raise failed[0]


@pytest.mark.parametrize(
    "shape",
    [
        pytest.param({"fat_sectors": 10_000}, id="1.5 KB, a DIFAT sector naming itself, 10,000 FAT sectors"),
        pytest.param({"fat_sectors": 4_000_000_000}, id="1.5 KB claiming 4 billion FAT sectors"),
        pytest.param(
            {"fat_sectors": 109 + 127 * 127, "difat_sectors": 127, "loop": False, "size": 8 * 1024**2},
            id="8 MB, 127 DIFAT sectors naming one FAT sector 16,238 times",
        ),
    ],
)
def test_fat_claims_are_bounded_by_the_file(shape: dict[str, Any]) -> None:
    """The header says how many FAT sectors there are and the DIFAT lists them; olefile believes both, and
    follows a DIFAT sector that points at itself as often as the header says. Every FAT and DIFAT sector is
    a sector of the file, and the FAT is read only until it covers the file: refused at once."""
    refused_quickly_in_a_thread(difat_file(**shape))


def test_attachments_beyond_a_few_hundred_are_not_kept() -> None:
    """10,000 empty attachment storages (1.3 MB) would make 10,000 parts (seconds of work, hundreds of MB):
    only the first :data:`~ordnung.ingest.outlook.MAX_ATTACHMENTS` become parts, quickly and in little
    memory, and the e-mail is still read."""
    nodes = message_nodes(bill(attachments=[Attachment("Rechnung.pdf", PDF, "application/pdf")]))
    nodes += [storage(f"__attach_version1.0_#{n:08X}") for n in range(1, 10_000)]
    raw = build(nodes)
    started = time.thread_time()
    eml = msg_to_eml(raw)
    elapsed = time.thread_time() - started  # (measured apart: tracing every allocation slows it 5 times)
    tracemalloc.start()
    try:
        assert msg_to_eml(raw) == eml
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert elapsed < 2.0 and peak < 50 * 1024**2, (elapsed, peak)
    message = email.message_from_bytes(eml, policy=email.policy.default)
    assert isinstance(message, EmailMessage)
    found = attachments_of(message)
    assert len(found) == outlook.MAX_ATTACHMENTS
    assert found[0] == ("Rechnung.pdf", "application/pdf", "attachment", PDF)
    assert message["Subject"] == "Ihre Rechnung September 2026"


def test_result_over_50_mb_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = build_msg(bill())
    monkeypatch.setattr(outlook, "MAX_BYTES", len(msg_to_eml(raw)) - 1)
    assert refusal(raw) == TOO_LARGE


def test_input_over_50_mb_refused_with_intakes_words(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = build_msg(bill())
    monkeypatch.setattr(intake, "MAX_BYTES", len(raw) - 1)
    assert refusal(raw).startswith("This file is larger than")


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(flips=st.lists(st.tuples(st.integers(0, 2**31), st.integers(1, 255)), min_size=1, max_size=12))
# found in CI: the "T" of the body's "Tag" becomes U+001C, a paragraph separator raqm couldn't lay out (a line break now)
@example(flips=[(44076, 72)])
def test_flipped_bytes_never_crash(flips: list[tuple[int, int]]) -> None:
    """Flipped bytes anywhere: refused with a reason, or an e-mail intake reads — never another error.

    Intake runs inside :func:`~ordnung.ingest.layout_guard.text_layout_refused`, as at every way in."""
    damaged = bytearray(FUZZ_BASE)
    for position, value in flips:
        damaged[8 + position % (len(damaged) - 8)] ^= value  # the magic stays: the converter is used
    try:
        eml, name = as_email(bytes(damaged), "kaputt.msg")
    except IntakeError as exc:
        assert str(exc) in REFUSALS, str(exc)
        return
    assert name == "kaputt.eml"
    try:
        with text_layout_refused():
            _body, mime, _name = normalise_upload(eml, name)
    except IntakeError:
        return
    assert mime == "message/rfc822"


FUZZ_BASE = build_msg(
    bill(
        html=b"<p>Guten Tag</p>",
        transport_headers="From: a@example.org\r\nSubject: Hallo\r\n\r\n",
        recipients=[Recipient("Sam", "sam@example.org"), Recipient("Alex", "alex@example.org", 2)],
        attachments=[
            Attachment("a.pdf", simple_pdf(["Rechnung"]), "application/pdf"),
            Attachment("b", method=5),
        ],
    )
)
REFUSALS = {DAMAGED, NOT_AN_EMAIL, OFFICE_FILE, NOT_OUTLOOK, ENCRYPTED, TOO_LARGE}


def assert_quick_refusal(data: bytes) -> None:
    """``data`` is refused as damaged within 2 s of CPU time and 50 MB of memory (generous: a refusal takes a
    fraction of that, and the coverage tracer slows Python code several times)."""
    tracemalloc.start()
    started = time.thread_time()
    try:
        reason = refusal(data)
        elapsed = time.thread_time() - started
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert reason == DAMAGED
    assert elapsed < 2.0 and peak < 50 * 1024**2, (elapsed, peak)


# --------------------------------------------------------------------------------------------------
# as_email: only OLE files are converted
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "name"),
    [
        (PDF, "Rechnung.pdf"),
        (b"From: a@example.org\r\nSubject: x\r\n\r\nHallo", "mail.eml"),
        (b"Notiz", "notiz.txt"),
        (b"\xd0\xcf\x11", "kurz.pdf"),  # shorter than the magic: intake says what it is
        (b"", "leer.msg"),  # intake says it is empty
        (b"From: a@example.org\r\nSubject: x\r\n\r\nHallo", "mail.msg"),  # an e-mail as text, named .msg
    ],
)
def test_as_email_leaves_other_files_alone(data: bytes, name: str) -> None:
    assert as_email(data, name) == (data, name)
    assert not is_ole(data)


@pytest.mark.parametrize(
    "data",
    [b"\xd0\xcf\x11", b"\0" * 8192, b"\xd0\xcf\x11\xe0\xa1\xb1"],
    ids=["cut before its first 8 bytes", "zeros after a failed copy", "cut inside the magic"],
)
def test_a_msg_that_is_no_file_intake_reads_is_damaged(data: bytes) -> None:
    """Named ``.msg`` but neither an OLE file nor a type intake reads: an Outlook file that can't be opened,
    with the advice to save it again (not “this file type is not supported”)."""
    with pytest.raises(IntakeError) as caught:
        as_email(data, "kaputt.msg")
    assert str(caught.value) == DAMAGED


@pytest.mark.parametrize(
    ("name", "stored"),
    [
        ("Rechnung Sept.msg", "Rechnung Sept.eml"),
        ("C:\\Users\\sam\\Desktop\\Mail.MSG", "Mail.eml"),
        ("/home/sam/Mail.msg", "Mail.eml"),
        ("Mail", "Mail.eml"),
        (".msg", "e-mail.eml"),
        ("", "e-mail.eml"),
    ],
)
def test_as_email_names_from_windows_paths(name: str, stored: str) -> None:
    raw = build_msg(bill())
    assert is_ole(raw) and OLE_MAGIC == MAGIC
    eml, filename = as_email(raw, name)
    assert filename == stored and eml == msg_to_eml(raw)


# --------------------------------------------------------------------------------------------------
# The dependency and the e2e fixture
# --------------------------------------------------------------------------------------------------


def test_olefile_is_a_permissive_runtime_dependency() -> None:
    """olefile (BSD-2-Clause, with PIL's licence for code from PIL) is a runtime dependency, pinned for CI."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert "olefile>=0.47" in project["dependencies"]
    assert "olefile==0.47\n" in (ROOT / "constraints.txt").read_text(encoding="utf-8")
    metadata = importlib.metadata.metadata("olefile")
    assert metadata["License"] == "BSD"
    assert "Redistribution and use in source and binary forms" in (
        importlib.metadata.distribution("olefile").read_text("LICENSE.txt") or ""
    )


def test_e2e_fixture_is_rebuilt_byte_for_byte() -> None:
    """``web/e2e/fixtures/outlook-bill.msg`` is what ``scripts/make_msg_fixture.py`` makes (fictional)."""
    out = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "make_msg_fixture.py"), "--check"],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)},
    )
    assert out.returncode == 0, out.stdout + out.stderr
    fixture = (ROOT / "web" / "e2e" / "fixtures" / "outlook-bill.msg").read_bytes()
    message = email.message_from_bytes(msg_to_eml(fixture), policy=email.policy.default)
    assert message["Subject"] == "Ihre Stromrechnung September 2026"
    assert [name for name, *_ in attachments_of(message)] == ["Stromrechnung_2026-09.pdf"]
    assert b"%PDF-" in fixture[:1024]
    assert struct.unpack_from("<H", fixture, 26)[0] == 3  # version 3, 512-byte sectors
