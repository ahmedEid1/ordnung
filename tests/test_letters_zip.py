"""Export letters as a ZIP (``ordnung.letters_zip``): which letters it holds (the cases shared with the web
app's dialog), safe names inside the archive, the originals byte for byte, ``index.csv`` for a
spreadsheet (and no formula a letter could plant in it), streaming one chunk at a time, ZIP64, and letters
whose file is missing."""

from __future__ import annotations

import csv
import gc
import hashlib
import io
import json
import os
import stat
import warnings
import zipfile
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any

import pytest

from ordnung import letters_zip
from ordnung.config import Paths
from ordnung.db.store import Store
from ordnung.letters_zip import (
    CHUNK,
    INDEX_COLUMNS,
    INDEX_NAME,
    MISSING_NOTE,
    Choice,
    LettersZip,
    csv_cell,
    plan,
    safe_component,
    select_documents,
    zip_name,
)
from ordnung.models import Document

CASES_FILE = (
    Path(__file__).resolve().parents[1] / "web" / "src" / "features" / "export" / "selection-cases.json"
)
SHARED = json.loads(CASES_FILE.read_text(encoding="utf-8"))
STAMP = "2026-01-01T09:00:00Z"
PDF = b"%PDF-1.7\n" + bytes(range(256)) * 4 + b"\n%%EOF\n"


def _shared_doc(fields: dict[str, Any]) -> Document:
    base = {
        "sha256": fields["id"],
        "filename": f"{fields['id']}.pdf",
        "mime": "application/pdf",
        "status": "processed",
        "created_at": STAMP,
        "updated_at": STAMP,
    }
    return Document.model_validate({**base, **fields})


def _choice(raw: dict[str, Any]) -> Choice:
    until = raw.get("until")
    return Choice(
        year=raw.get("year"),
        until=date.fromisoformat(until) if until else None,
        tax=bool(raw.get("tax", False)),
        party_id=raw.get("party_id"),
    )


def letter(
    store: Store,
    paths: Paths,
    label: str,
    data: bytes = PDF,
    *,
    mime: str = "application/pdf",
    extension: str = "pdf",
    **fields: Any,
) -> str:
    """A letter whose original is stored like an upload's (``files/<sha[:2]>/<sha>.<ext>``)."""
    sha = hashlib.sha256(label.encode()).hexdigest()
    path = paths.files / sha[:2] / f"{sha}.{extension}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    doc = store.add_document(
        sha256=sha, filename=f"{label}.{extension}", mime=mime, file_path=path.relative_to(paths.data_dir)
    )
    fields.setdefault("status", "processed")
    fields.setdefault("title", label)
    store.update_document(doc.id, **fields)
    return doc.id


def archive_bytes(store: Store, choice: Choice | None = None, **kwargs: Any) -> bytes:
    return b"".join(LettersZip(plan(store, choice or Choice()), **kwargs))


def opened(blob: bytes) -> zipfile.ZipFile:
    archive = zipfile.ZipFile(io.BytesIO(blob))
    assert archive.testzip() is None
    return archive


def index_rows(archive: zipfile.ZipFile) -> list[dict[str, str]]:
    text = archive.read(INDEX_NAME).decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text, newline=""), delimiter=";"))


def files_of(archive: zipfile.ZipFile) -> list[str]:
    return [name for name in archive.namelist() if name != INDEX_NAME]


# --------------------------------------------------------------------------------------------------
# which letters: the cases the web app's dialog counts with too
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("case", SHARED["cases"], ids=[case["name"] for case in SHARED["cases"]])
def test_the_letters_chosen_are_the_ones_the_dialog_counts(case: dict[str, Any]) -> None:
    docs = [_shared_doc(fields) for fields in SHARED["docs"]]
    chosen = select_documents(docs, _choice(case["choice"]))
    assert [doc.id for doc in chosen] == case["expected_ids"]


@pytest.mark.parametrize("case", SHARED["cases"], ids=[case["name"] for case in SHARED["cases"]])
def test_the_zip_is_named_as_the_dialog_names_it(case: dict[str, Any]) -> None:
    today = date.fromisoformat(SHARED["today"])
    assert zip_name(_choice(case["choice"]), today) == case["expected_name"]


def test_a_letter_waiting_in_the_trash_or_a_proof_file_never_goes_in(store: Store, paths: Paths) -> None:
    kept = letter(store, paths, "kept", doc_date="2025-03-01")
    letter(store, paths, "waiting", doc_date="2025-03-02", status="held", ai_private=True)
    trashed = letter(store, paths, "trashed", doc_date="2025-03-03")
    store.update_document(trashed, deleted_at=STAMP)
    letter(store, paths, "proof", doc_date="2025-03-04", source="proof", direction="outgoing")
    private = letter(store, paths, "private", doc_date="2025-03-05", ai_private=True)
    assert {entry.doc.id for entry in plan(store, Choice())} == {kept, private}


# --------------------------------------------------------------------------------------------------
# names inside the archive
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("../../etc/passwd", "-..-etc-passwd"),
        ("..\\..\\x", "-..-x"),
        ("C:\\Windows", "C--Windows"),
        ("/abs", "-abs"),
        (".", "Fallback"),
        ("..", "Fallback"),
        ("", "Fallback"),
        ("   ", "Fallback"),
        ('Re: x?*|<>"', "Re- x------"),
        ("evil\u202egnp.exe", "evilgnp.exe"),
        ("bell\x07 and\x1b[31m csi\x9b", "bell and[31m csi"),
        ("Mu\u0308ller", "Müller"),
        ("trailing dots and spaces. . .", "trailing dots and spaces"),
        (".hidden", "hidden"),
        ("tab\tand\nnew line", "tab and new line"),
        ("CON", "_CON"),
        ("aux", "_aux"),
        ("NUL.txt", "_NUL.txt"),
        ("com1", "_com1"),
        ("LPT9.tar.gz", "_LPT9.tar.gz"),
        ("Console", "Console"),
        ("COM10", "COM10"),
    ],
)
def test_a_name_from_a_letter_is_made_safe_for_every_file_system(text: str, expected: str) -> None:
    assert safe_component(text, "Fallback", chars=60, max_bytes=80) == expected


def test_a_hostile_name_never_leaves_its_folder() -> None:
    for text in ("../../etc/passwd", "..\\..\\x", "C:\\Windows", "/abs", "a/../../b", "\\\\server\\share"):
        name = safe_component(text, "x", chars=60, max_bytes=80)
        assert "/" not in name and "\\" not in name and ":" not in name
        assert name not in ("", ".", "..")


def test_a_long_name_is_cut_to_its_characters_and_bytes() -> None:
    assert safe_component("a" * 500, "x", chars=90, max_bytes=150) == "a" * 90
    cjk = safe_component("漢" * 200, "x", chars=90, max_bytes=150)
    assert len(cjk.encode("utf-8")) <= 150 and set(cjk) == {"漢"} and len(cjk) == 50
    # a cut that lands on a space or a dot leaves none at the end
    assert safe_component("abc " + "d" * 10, "x", chars=4, max_bytes=80) == "abc"


def test_every_path_is_year_sender_file_and_extracts_inside_its_folder(
    store: Store, paths: Paths, tmp_path: Path
) -> None:
    hostile = store.add_party(name="../Finanzamt/../Musterstadt", kind="tax_office")
    titles = [
        "../../etc/passwd",
        "..\\..\\x",
        "C:\\Windows\\sys",
        "/abs",
        "CON",
        ".",
        "..",
        "\u202eevil",
        "a" * 500,
    ]
    for n, title in enumerate(titles):
        letter(store, paths, f"hostile{n}", title=title, doc_date="2025-03-01", party_id=hostile.id)
    archive = opened(archive_bytes(store))
    names = archive.namelist()
    assert len(names) == len(titles) + 1
    for name in names:
        parts = PurePosixPath(name).parts
        assert name == INDEX_NAME or len(parts) == 3, name
        assert not name.startswith("/") and "\\" not in name and ":" not in name
        assert not any(part in ("", ".", "..") for part in parts)
        assert len(name) < 200
    out = tmp_path / "out"
    archive.extractall(out)
    root = out.resolve()
    assert all(path.resolve().is_relative_to(root) for path in out.rglob("*"))
    assert {path.parent.name for path in out.rglob("*.pdf")} == {"-Finanzamt-..-Musterstadt"}


def test_a_file_is_named_by_its_date_and_title_in_folders_by_year_and_sender(
    store: Store, paths: Paths
) -> None:
    office = store.add_party(name="Finanzamt Musterstadt", kind="tax_office")
    letter(store, paths, "assessment", title="Steuerbescheid 2025", doc_date="2026-03-14", party_id=office.id)
    letter(store, paths, "no title", title=None, doc_date="2026-04-01", party_id=office.id)
    letter(store, paths, "arrived", title="Mahnung", received_date="2025-12-30")
    letter(store, paths, "undated", title="Notiz")
    assert sorted(files_of(opened(archive_bytes(store)))) == [
        "2025/Sender unknown/2025-12-30 Mahnung.pdf",
        "2026/Finanzamt Musterstadt/2026-03-14 Steuerbescheid 2025.pdf",
        "2026/Finanzamt Musterstadt/2026-04-01 no title.pdf",
        "Undated/Sender unknown/Notiz.pdf",
    ]


def test_a_sender_named_like_a_windows_device_gets_a_safe_folder(store: Store, paths: Paths) -> None:
    device = store.add_party(name="CON", kind="other")
    letter(store, paths, "device", title="Brief", doc_date="2025-01-02", party_id=device.id)
    assert files_of(opened(archive_bytes(store))) == ["2025/_CON/2025-01-02 Brief.pdf"]


def test_names_that_differ_only_in_case_are_numbered(store: Store, paths: Paths) -> None:
    for n, title in enumerate(
        ["Lohnsteuerbescheinigung", "LOHNSTEUERbescheinigung", "lohnsteuerbescheinigung"]
    ):
        letter(store, paths, f"case{n}", title=title, doc_date="2026-02-20")
    names = files_of(opened(archive_bytes(store)))
    assert sorted(name.casefold() for name in names) == [
        "2026/sender unknown/2026-02-20 lohnsteuerbescheinigung (2).pdf",
        "2026/sender unknown/2026-02-20 lohnsteuerbescheinigung (3).pdf",
        "2026/sender unknown/2026-02-20 lohnsteuerbescheinigung.pdf",
    ]


def test_senders_whose_names_differ_only_in_case_share_one_folder(store: Store, paths: Paths) -> None:
    first = store.add_party(name="Stadtwerke", kind="utility")
    second = store.add_party(name="STADTWERKE", kind="utility")
    letter(store, paths, "one", title="Abschlag", doc_date="2025-02-01", party_id=first.id)
    letter(store, paths, "two", title="Abschlag", doc_date="2025-02-01", party_id=second.id)
    folders = {PurePosixPath(name).parts[1] for name in files_of(opened(archive_bytes(store)))}
    assert len(folders) == 1


def test_the_archive_is_ordered_by_year_sender_and_date(store: Store, paths: Paths) -> None:
    bank = store.add_party(name="bank", kind="bank")
    insurer = store.add_party(name="Allianz", kind="insurer")
    letter(store, paths, "late", title="b", doc_date="2025-09-01", party_id=bank.id)
    letter(store, paths, "early", title="a", doc_date="2025-02-01", party_id=bank.id)
    letter(store, paths, "insurer", title="c", doc_date="2025-12-01", party_id=insurer.id)
    letter(store, paths, "older", title="d", doc_date="2024-12-31", party_id=bank.id)
    letter(store, paths, "undated", title="e", party_id=bank.id)
    assert files_of(opened(archive_bytes(store))) == [
        "2024/bank/2024-12-31 d.pdf",
        "2025/Allianz/2025-12-01 c.pdf",
        "2025/bank/2025-02-01 a.pdf",
        "2025/bank/2025-09-01 b.pdf",
        "Undated/bank/e.pdf",
    ]


# --------------------------------------------------------------------------------------------------
# the files themselves
# --------------------------------------------------------------------------------------------------


def test_the_originals_come_out_byte_for_byte_with_their_real_extension(store: Store, paths: Paths) -> None:
    jpeg = b"\xff\xd8\xff\xe0" + os.urandom(2000) + b"\xff\xd9"
    text = "Sehr geehrte Frau Rivera,\r\nmit freundlichen Grüßen\r\n".encode() * 50
    mail = b"From: a@example.org\r\nSubject: Rechnung\r\n\r\nHallo\r\n" * 40
    letter(store, paths, "pdf", PDF, title="Bescheid", doc_date="2025-01-01")
    # an upload named letter.html is still a photo: its extension follows the real type
    letter(
        store,
        paths,
        "photo",
        jpeg,
        mime="image/jpeg",
        extension="jpg",
        title="Foto.html",
        doc_date="2025-01-02",
    )
    letter(
        store, paths, "text", text, mime="text/plain", extension="txt", title="Notiz", doc_date="2025-01-03"
    )
    letter(
        store,
        paths,
        "mail",
        mail,
        mime="message/rfc822",
        extension="eml",
        title="E-Mail",
        doc_date="2025-01-04",
    )
    archive = opened(archive_bytes(store))
    folder = "2025/Sender unknown"
    assert archive.read(f"{folder}/2025-01-01 Bescheid.pdf") == PDF
    assert archive.read(f"{folder}/2025-01-02 Foto.html.jpg") == jpeg
    assert archive.read(f"{folder}/2025-01-03 Notiz.txt") == text
    assert archive.read(f"{folder}/2025-01-04 E-Mail.eml") == mail
    # text is compressed; PDFs and photos are already
    kinds = {info.filename.rsplit(".", 1)[1]: info.compress_type for info in archive.infolist()}
    assert kinds == {
        "pdf": zipfile.ZIP_STORED,
        "jpg": zipfile.ZIP_STORED,
        "txt": zipfile.ZIP_DEFLATED,
        "eml": zipfile.ZIP_DEFLATED,
        "csv": zipfile.ZIP_DEFLATED,
    }


def test_each_file_carries_its_letter_day_and_owner_only_permissions(store: Store, paths: Paths) -> None:
    letter(store, paths, "dated", title="a", doc_date="2025-03-14")
    letter(store, paths, "ancient", title="b", doc_date="1975-06-01")
    archive = opened(archive_bytes(store))
    infos = {info.filename: info for info in archive.infolist()}
    assert infos["2025/Sender unknown/2025-03-14 a.pdf"].date_time == (2025, 3, 14, 12, 0, 0)
    assert infos["1975/Sender unknown/1975-06-01 b.pdf"].date_time == (1980, 1, 1, 12, 0, 0)
    for info in infos.values():
        assert stat.S_IMODE(info.external_attr >> 16) == 0o600
        assert info.flag_bits & 0x08  # sizes after the data: it is written as it is sent


def test_a_name_with_umlauts_is_marked_as_utf8(store: Store, paths: Paths) -> None:
    office = store.add_party(name="Bürgeramt Köln", kind="authority")
    letter(store, paths, "umlaut", title="Anmeldebestätigung", doc_date="2025-05-05", party_id=office.id)
    info = next(info for info in opened(archive_bytes(store)).infolist() if info.filename != INDEX_NAME)
    assert info.filename == "2025/Bürgeramt Köln/2025-05-05 Anmeldebestätigung.pdf"
    assert info.flag_bits & 0x800


# --------------------------------------------------------------------------------------------------
# index.csv
# --------------------------------------------------------------------------------------------------


def test_the_index_opens_in_a_german_spreadsheet(store: Store, paths: Paths) -> None:
    office = store.add_party(name="Finanzamt Musterstadt", kind="tax_office")
    letter(
        store,
        paths,
        "assessment",
        title="Steuerbescheid 2025",
        kind="tax_assessment",
        doc_date="2026-03-14",
        received_date="2026-03-17",
        party_id=office.id,
        tax_relevant=True,
        tax_note="Refund; check the laptop",
        pages=3,
    )
    letter(
        store,
        paths,
        "sent",
        title="Widerspruch; Teil 1",
        direction="outgoing",
        doc_date="2026-04-01",
        ai_private=True,
    )
    raw = opened(archive_bytes(store)).read(INDEX_NAME)
    assert raw.startswith(b"\xef\xbb\xbf")
    lines = raw.decode("utf-8-sig").split("\r\n")
    assert lines[0] == ";".join(INDEX_COLUMNS)
    assert INDEX_COLUMNS == (
        "file",
        "letter_date",
        "arrived",
        "sender",
        "title",
        "kind",
        "for_taxes",
        "tax_note",
        "direction",
        "private",
        "pages",
        "original_name",
        "ordnung_id",
        "note",
    )
    rows = index_rows(opened(archive_bytes(store)))
    assessment, sent = rows
    assert assessment == {
        "file": "2026/Finanzamt Musterstadt/2026-03-14 Steuerbescheid 2025.pdf",
        "letter_date": "2026-03-14",
        "arrived": "2026-03-17",
        "sender": "Finanzamt Musterstadt",
        "title": "Steuerbescheid 2025",
        "kind": "tax assessment",
        "for_taxes": "yes",
        "tax_note": "Refund; check the laptop",
        "direction": "received",
        "private": "no",
        "pages": "3",
        "original_name": "assessment.pdf",
        "ordnung_id": assessment["ordnung_id"],
        "note": "",
    }
    assert (sent["direction"], sent["private"], sent["sender"], sent["title"]) == (
        "sent",
        "yes",
        "",
        "Widerspruch; Teil 1",
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ('=HYPERLINK("http://x.example","click")', '\'=HYPERLINK("http://x.example","click")'),
        ("+49 30 1234", "'+49 30 1234"),
        ("-2+3", "'-2+3"),
        ("@SUM(A1:A2)", "'@SUM(A1:A2)"),
        ("\t=1", "'\t=1"),
        ("\r=1", "'\r=1"),
        ("Rechnung = 12 €", "Rechnung = 12 €"),
        ("", ""),
        (None, ""),
        (3, "3"),
    ],
)
def test_a_cell_never_starts_a_spreadsheet_formula(value: object, expected: str) -> None:
    assert csv_cell(value) == expected


def test_a_title_a_letter_planted_stays_text_in_the_index(store: Store, paths: Paths) -> None:
    letter(store, paths, "planted", title='=HYPERLINK("http://x.example","Open")', doc_date="2025-01-01")
    party = store.add_party(name="@evil", kind="other")
    letter(store, paths, "sender", title="ok", doc_date="2025-01-02", party_id=party.id)
    rows = {row["title"]: row for row in index_rows(opened(archive_bytes(store)))}
    assert set(rows) == {'\'=HYPERLINK("http://x.example","Open")', "ok"}
    assert rows["ok"]["sender"] == "'@evil"


# --------------------------------------------------------------------------------------------------
# missing files
# --------------------------------------------------------------------------------------------------


def test_a_missing_file_or_one_outside_the_data_folder_is_listed_not_followed(
    store: Store, paths: Paths, tmp_path: Path
) -> None:
    kept = letter(store, paths, "kept", title="kept", doc_date="2025-01-01")
    gone = letter(store, paths, "gone", title="gone", doc_date="2025-01-02")
    linked = letter(store, paths, "linked", title="linked", doc_date="2025-01-03")
    path = store.get_document_file(gone)
    assert path is not None
    path.unlink()
    outside = tmp_path / "secret.pdf"
    outside.write_bytes(b"not Ordnung's")
    link = store.get_document_file(linked)
    assert link is not None
    link.unlink()
    link.symlink_to(outside)
    archive = opened(archive_bytes(store))
    assert files_of(archive) == ["2025/Sender unknown/2025-01-01 kept.pdf"]
    rows = {row["ordnung_id"]: row for row in index_rows(archive)}
    assert rows[kept]["file"] and not rows[kept]["note"]
    for doc_id in (gone, linked):
        assert (rows[doc_id]["file"], rows[doc_id]["note"]) == ("", MISSING_NOTE)
    assert MISSING_NOTE == "The file is missing from Ordnung's data folder."


def test_a_loop_of_links_is_listed_as_missing(store: Store, paths: Paths) -> None:
    looped = letter(store, paths, "looped", title="looped", doc_date="2025-01-01")
    path = store.get_document_file(looped)
    assert path is not None
    path.unlink()
    other = path.with_name("other.pdf")
    path.symlink_to(other)
    other.symlink_to(path)
    entry = plan(store, Choice())[0]
    assert (entry.name, entry.path) == (None, None)


def test_a_file_that_cant_be_measured_is_listed_as_missing(
    store: Store, paths: Paths, monkeypatch: pytest.MonkeyPatch
) -> None:
    letter(store, paths, "unmeasured", title="unmeasured", doc_date="2025-01-01")
    entries = plan(store, Choice())
    real_stat = Path.stat

    def failing_stat(self: Path, *args: Any, **kwargs: Any) -> os.stat_result:
        if self.suffix == ".pdf":
            raise OSError("gone")
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", failing_stat)
    with warnings.catch_warnings():
        warnings.simplefilter("error", ResourceWarning)
        archive = opened(b"".join(LettersZip(entries)))
        gc.collect()
    assert files_of(archive) == []
    assert index_rows(archive)[0]["note"] == MISSING_NOTE


def test_a_file_of_another_type_keeps_a_plain_extension_of_its_own(store: Store, paths: Paths) -> None:
    letter(store, paths, "binary", b"\x00\x01", mime="application/octet-stream", extension="bin", title="a")
    letter(store, paths, "odd", b"\x00\x02", mime="application/octet-stream", extension="tar~1", title="b")
    assert sorted(files_of(opened(archive_bytes(store)))) == [
        "Undated/Sender unknown/a.bin",
        "Undated/Sender unknown/b",
    ]


def test_a_file_deleted_after_the_plan_is_listed_as_missing(store: Store, paths: Paths) -> None:
    letter(store, paths, "first", title="first", doc_date="2025-01-01")
    second = letter(store, paths, "second", title="second", doc_date="2025-01-02")
    entries = plan(store, Choice())
    path = store.get_document_file(second)
    assert path is not None
    path.unlink()
    archive = opened(b"".join(LettersZip(entries)))
    assert files_of(archive) == ["2025/Sender unknown/2025-01-01 first.pdf"]
    assert index_rows(archive)[1]["note"] == MISSING_NOTE


def test_an_export_with_no_letters_holds_only_the_index(store: Store) -> None:
    archive = opened(archive_bytes(store))
    assert archive.namelist() == [INDEX_NAME]
    assert index_rows(archive) == []


def test_a_read_error_in_the_middle_of_a_file_cuts_the_archive(
    store: Store, paths: Paths, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = os.urandom(3 * 1024)
    letter(store, paths, "broken", data, title="broken", doc_date="2025-01-01")
    real_open = Path.open

    class Failing(io.BytesIO):
        def read(self, size: int | None = -1) -> bytes:
            if self.tell():
                raise OSError("disk went away")
            return super().read(size)

    def failing_open(self: Path, *args: Any, **kwargs: Any) -> Any:
        if self.suffix == ".pdf":
            return Failing(data)
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", failing_open)
    sent: list[bytes] = []
    with pytest.raises(OSError, match="disk went away"):
        sent.extend(LettersZip(plan(store, Choice()), chunk=1024))
    # what was sent has no central directory: unzip refuses it instead of missing a letter quietly
    with pytest.raises(zipfile.BadZipFile):
        zipfile.ZipFile(io.BytesIO(b"".join(sent)))


# --------------------------------------------------------------------------------------------------
# streaming and ZIP64
# --------------------------------------------------------------------------------------------------


def test_a_large_file_is_sent_a_chunk_at_a_time(store: Store, paths: Paths) -> None:
    data = os.urandom(3 * CHUNK)
    letter(store, paths, "large", data, title="large", doc_date="2025-01-01")
    chunks = list(LettersZip(plan(store, Choice())))
    assert len(chunks) >= 3
    assert all(len(chunk) <= CHUNK + 4096 for chunk in chunks)
    assert opened(b"".join(chunks)).read("2025/Sender unknown/2025-01-01 large.pdf") == data


def test_a_compressed_text_streams_too(store: Store, paths: Paths) -> None:
    text = b"Kontoauszug Seite 1 von 1\r\n" * 4000
    letter(
        store, paths, "statement", text, mime="text/plain", extension="txt", title="t", doc_date="2025-01-01"
    )
    chunks = list(LettersZip(plan(store, Choice()), chunk=4096))
    assert sum(map(len, chunks)) < len(text) // 4  # compressed
    assert opened(b"".join(chunks)).read("2025/Sender unknown/2025-01-01 t.txt") == text


def test_many_small_letters_are_sent_one_by_one(store: Store, paths: Paths) -> None:
    for n in range(300):
        letter(
            store,
            paths,
            f"small{n:03d}",
            b"%PDF-1.4 " + str(n).encode(),
            title=f"n{n:03d}",
            doc_date="2025-01-01",
        )
    chunks = list(LettersZip(plan(store, Choice())))
    assert len(chunks) >= 300
    assert len(files_of(opened(b"".join(chunks)))) == 300


def test_past_the_zip_limits_the_archive_gets_zip64_records(
    store: Store, paths: Paths, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(zipfile, "ZIP64_LIMIT", 1000)
    monkeypatch.setattr(zipfile, "ZIP_FILECOUNT_LIMIT", 5)
    contents = {n: os.urandom(1500) for n in range(8)}
    for n, data in contents.items():
        letter(store, paths, f"big{n}", data, title=f"big{n}", doc_date="2025-01-01")
    blob = archive_bytes(store)
    assert b"PK\x06\x06" in blob  # the ZIP64 end of central directory
    archive = opened(blob)
    assert len(files_of(archive)) == 8
    assert {archive.read(f"2025/Sender unknown/2025-01-01 big{n}.pdf") for n in contents} == set(
        contents.values()
    )


def test_the_same_letters_give_the_same_bytes(store: Store, paths: Paths) -> None:
    office = store.add_party(name="Finanzamt", kind="tax_office")
    letter(store, paths, "a", title="a", doc_date="2025-01-01", party_id=office.id)
    letter(store, paths, "b", b"text" * 100, mime="text/plain", extension="txt", title="b")
    assert archive_bytes(store) == archive_bytes(store)


def test_closing_the_download_early_leaks_no_file(store: Store, paths: Paths) -> None:
    for n in range(3):
        letter(store, paths, f"file{n}", os.urandom(4096), title=f"file{n}", doc_date="2025-01-01")
    with warnings.catch_warnings():
        warnings.simplefilter("error", ResourceWarning)
        stream = iter(LettersZip(plan(store, Choice()), chunk=1024))
        assert next(stream)
        stream.close()
        del stream
        gc.collect()


def test_the_choice_narrows_the_archive(store: Store, paths: Paths) -> None:
    office = store.add_party(name="Finanzamt", kind="tax_office")
    letter(store, paths, "tax25", title="tax25", doc_date="2025-05-01", tax_relevant=True, party_id=office.id)
    letter(store, paths, "early26", title="early26", doc_date="2026-02-01", tax_relevant=True)
    letter(store, paths, "late26", title="late26", doc_date="2026-07-01", tax_relevant=True)
    letter(store, paths, "rent25", title="rent25", doc_date="2025-05-02")
    choice = Choice(year=2025, until=date(2026, 5, 31), tax=True)
    assert files_of(opened(archive_bytes(store, choice))) == [
        "2025/Finanzamt/2025-05-01 tax25.pdf",
        "2026/Sender unknown/2026-02-01 early26.pdf",
    ]
    only_office = Choice(party_id=office.id)
    assert [entry.doc.title for entry in plan(store, only_office)] == ["tax25"]
    assert letters_zip.matches(_shared_doc({"id": "x", "doc_date": "2025-05-01"}), Choice(year=2025))
