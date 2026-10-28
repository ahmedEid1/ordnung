"""Text Ordnung read in a picture itself (ADR 0024): ``derived/<doc_id>/picture-text.json``, kept by the store only
for letters Claude isn't reading (kept private, held, waiting for Claude, failed), ORed into the person's letter
search as ``found_in="picture_text"`` and forgotten once Claude reads the page — the scanner text's rules (ADR 0020).
The worker that reads the pictures is tested in ``test_worker_pictures.py``; Ask's blindness in
``test_picture_text_ask.py``."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from fixtures_llm import TAX_LETTER
from helpers_docs import photo, scanned_pdf
from ordnung import clock
from ordnung.config import OCR_SWITCH
from ordnung.db import store as store_module
from ordnung.db.store import Store
from ordnung.ingest import worker
from ordnung.models import PROOF_SOURCE, Document
from test_api_support import TODAY, ApiRouter, api_for

PICTURE_WORDS = "Hausverwaltung Beispiel GmbH · Ihr Kellerabteil 7 · Gebäude Süd, Musterstraße 12"


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


@pytest.fixture
def ocr_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """Text in pictures on (``tests/conftest.py`` turns it off for every test)."""
    monkeypatch.delenv(OCR_SWITCH)


def add_letter(
    store: Store,
    name: str,
    *,
    mime: str = "image/jpeg",
    pages: int = 1,
    texts: dict[int, str] | None = None,
    **fields: Any,
) -> Document:
    """A letter with a real original under ``files/`` and ``pages`` pages (without text unless ``texts``)."""
    content = f"{name} {mime} {pages}".encode()
    digest = hashlib.sha256(content).hexdigest()
    relative = Path("files") / digest[:2] / f"{digest}.bin"
    target = store.data_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    document = store.add_document(sha256=digest, filename=name, mime=mime, file_path=relative, pages=pages)
    store.set_pages(
        document.id,
        [
            {
                "page": n,
                "width": 1240,
                "height": 1754,
                "image_path": f"derived/{document.id}/page-{n}.jpg",
                "text": (texts or {}).get(n, ""),
                "text_source": "text" if (texts or {}).get(n) else "none",
            }
            for n in range(1, pages + 1)
        ],
    )
    return store.update_document(document.id, **fields) if fields else document


def private_photo(store: Store, name: str = "foto.jpg", **fields: Any) -> Document:
    return add_letter(store, name, ai_private=True, status="processed", **fields)


def private_scan(store: Store, name: str = "scan.pdf", *, pages: int = 1, **fields: Any) -> Document:
    """A private PDF whose pages have no text of their own, after its text stage (no scanner text found)."""
    document = add_letter(
        store, name, mime="application/pdf", pages=pages, ai_private=True, status="processed", **fields
    )
    store.write_scan_text(document.id, {})
    return document


def picture_file(store: Store, doc_id: str) -> Path:
    return store.paths.derived / doc_id / "picture-text.json"


def kept_pages(store: Store, doc_id: str) -> dict[str, str]:
    pages: dict[str, str] = json.loads(picture_file(store, doc_id).read_text("utf-8"))["pages"]
    return pages


def set_created(store: Store, doc_id: str, moment: str) -> None:
    with store.tx() as conn:
        conn.execute("UPDATE documents SET created_at = ? WHERE id = ?", (moment, doc_id))


# --------------------------------------------------------------------------------------------------
# which pages are read, and what is kept
# --------------------------------------------------------------------------------------------------


def test_picture_text_lives_in_its_own_file_with_the_scanner_texts_format(store: Store) -> None:
    """``picture-text.json`` beside the page images, in the scanner text's format; a page Tesseract found no words
    on is kept as ``""`` (looked at, nothing there); no scanner text is made up for it."""
    letter = private_scan(store, pages=2)
    assert store.write_picture_text(letter.id, 2, f"  {PICTURE_WORDS}\n\f") is True
    assert store.write_picture_text(letter.id, 1, " \n\f") is True
    assert json.loads(picture_file(store, letter.id).read_text("utf-8")) == {
        "version": 1,
        "pages": {"1": "", "2": PICTURE_WORDS},
    }
    assert json.loads((store.paths.derived / letter.id / "scan-text.json").read_text("utf-8"))["pages"] == {}
    assert store.picture_text_pages(letter.id) == [2]
    assert store.scan_text_pages(letter.id) == []


def _waiting(reason: str) -> Callable[[Store, Document], None]:
    def wait(store: Store, document: Document) -> None:
        job = store.enqueue_job("ingest", document.id)
        store.update_job(job.id, waiting_reason=reason, not_before="2099-01-01T00:00:00Z")

    return wait


def _queued(store: Store, document: Document) -> None:
    store.enqueue_job("ingest", document.id)


def _put_back_after_a_stop(store: Store, document: Document) -> None:
    job = store.enqueue_job("ingest", document.id)
    store.update_job(
        job.id, waiting_reason="Ordnung was stopped before this letter was finished; it will continue."
    )


def _scanner_text(store: Store, document: Document) -> None:
    store.write_scan_text(document.id, {1: "Ablesung Ihres Wasserzählers"})


def _no_text_stage(store: Store, document: Document) -> None:
    (store.paths.derived / document.id / "scan-text.json").unlink()


DUE_CASES: dict[str, tuple[dict[str, Any], Callable[[Store, Document], None] | None, bool]] = {
    # name: (the letter's fields, what else is true of it, due)
    "private photo": ({"ai_private": True, "status": "processed"}, None, True),
    "held photo": ({"ai_private": True, "status": "held"}, None, True),
    "failed photo": ({"status": "failed", "error": "Couldn't read this letter."}, None, True),
    "waiting for Claude": (
        {"status": "queued"},
        _waiting(f"{worker.WAITING_FOR_CLAUDE}: Claude Code isn't installed on this computer yet."),
        True,
    ),
    "usage-limit wait": (
        {"status": "queued"},
        _waiting(
            f"{worker.WAITING_FOR_CLAUDE}: the usage limit was reached. Ordnung continues at about 15:00."
        ),
        True,
    ),
    "private scan": ({"mime": "application/pdf", "ai_private": True, "status": "processed"}, None, True),
    "queued to be read": ({"status": "queued"}, _queued, False),
    "put back after a stop": ({"status": "queued"}, _put_back_after_a_stop, False),
    "read": ({"status": "processed"}, None, False),
    "read, kept private since": (
        {"ai_private": True, "status": "processed", "ai_processed_at": "2026-09-20T10:00:00Z"},
        None,
        False,
    ),
    "read, failed on Read again": (
        {
            "status": "failed",
            "error": "Couldn't read this letter.",
            "ai_processed_at": "2026-09-20T10:00:00Z",
        },
        None,
        False,
    ),
    "needs a look": ({"status": "needs_review"}, None, False),
    "in the trash": (
        {"ai_private": True, "status": "processed", "deleted_at": "2026-09-20T10:00:00Z"},
        None,
        False,
    ),
    "proof file": ({"ai_private": True, "status": "processed", "source": PROOF_SOURCE}, None, False),
    "text file": ({"mime": "text/plain", "ai_private": True, "status": "processed"}, None, False),
    "e-mail": ({"mime": "message/rfc822", "ai_private": True, "status": "processed"}, None, False),
    "PDF page with own text": (
        {"mime": "application/pdf", "texts": {1: "Eigener Text"}, "ai_private": True, "status": "processed"},
        None,
        False,
    ),
    "PDF page with scanner text": (
        {"mime": "application/pdf", "ai_private": True, "status": "processed"},
        _scanner_text,
        False,
    ),
    "PDF whose text stage hasn't run": (
        {"mime": "application/pdf", "ai_private": True, "status": "queued"},
        _no_text_stage,
        False,
    ),
}


@pytest.mark.parametrize("case", DUE_CASES, ids=list(DUE_CASES))
def test_only_letters_claude_isnt_reading_are_due(store: Store, case: str) -> None:
    """Pages without text of their own of photos and PDFs Claude isn't reading — kept private, held, waiting for
    Claude (not ready, or a usage limit) or failed — and nothing else: not a letter queued to be read or read,
    one in the trash, a proof file, a text file, a page with its own or a scanner's text, or a PDF whose own text
    hasn't been looked for yet, nor one Claude has read (kept private or failed since). What is due is also what may
    be kept."""
    fields, more, due = DUE_CASES[case]
    fields = dict(fields)
    mime, texts = fields.pop("mime", "image/jpeg"), fields.pop("texts", None)
    source = fields.pop("source", None)
    letter = add_letter(store, f"{case}.bin", mime=mime, texts=texts, **fields)
    if source is not None:
        with store.tx() as conn:
            conn.execute("UPDATE documents SET source = ? WHERE id = ?", (source, letter.id))
    if mime == "application/pdf":
        store.write_scan_text(letter.id, {})  # its text stage ran (one case undoes that)
    if more is not None:
        more(store, letter)
    assert store.picture_text_due() == ([(letter.id, 1)] if due else [])
    assert store.write_picture_text(letter.id, 1, PICTURE_WORDS) is due
    assert picture_file(store, letter.id).is_file() is due
    assert store.picture_text_due() == []  # looked at: never read twice


def test_the_waiting_reason_is_the_workers() -> None:
    """One definition of how a letter waiting for Claude says so: the store's, which the worker (and the CLI
    through it) uses."""
    assert worker.WAITING_FOR_CLAUDE is store_module.WAITING_FOR_CLAUDE == "Waiting for Claude"


def test_newest_letters_come_first_and_a_looked_at_page_is_never_read_again(store: Store) -> None:
    """The person most likely searches for what they just added: the newest letter first, its pages in order. A
    page looked at — words found or none — is never due again."""
    old = private_photo(store, "alt.jpg")
    set_created(store, old.id, "2026-09-01T08:00:00Z")
    scan = private_scan(store, "neu.pdf", pages=3)
    set_created(store, scan.id, "2026-09-24T08:00:00Z")
    middle = add_letter(store, "mitte.jpg", status="failed")
    set_created(store, middle.id, "2026-09-10T08:00:00Z")
    assert store.picture_text_due() == [(scan.id, 1), (scan.id, 2), (scan.id, 3), (middle.id, 1), (old.id, 1)]
    assert store.write_picture_text(scan.id, 2, "") and store.write_picture_text(middle.id, 1, PICTURE_WORDS)
    assert store.picture_text_due() == [(scan.id, 1), (scan.id, 3), (old.id, 1)]


def test_picture_text_is_kept_only_while_claude_isnt_reading_and_the_page_has_no_text(store: Store) -> None:
    """What Tesseract read is checked again when it is kept, in one transaction: a letter the person let Claude
    read meanwhile, a page that got its own text, one with a scanner's text, a page or letter that isn't there —
    nothing is kept, and an earlier page stays as it was."""
    released = private_photo(store, "freigegeben.jpg")
    store.update_document(released.id, ai_private=False, status="queued")
    assert store.write_picture_text(released.id, 1, PICTURE_WORDS) is False
    assert not picture_file(store, released.id).exists()

    scan = private_scan(store, pages=3)
    assert store.write_picture_text(scan.id, 1, "Seite eins") is True
    store.set_page_text(scan.id, 2, "Transkript der zweiten Seite", "transcript")
    assert store.write_picture_text(scan.id, 2, PICTURE_WORDS) is False
    store.write_scan_text(scan.id, {3: "Ablesung Ihres Wasserzählers"})
    assert store.write_picture_text(scan.id, 3, PICTURE_WORDS) is False
    assert store.write_picture_text(scan.id, 9, PICTURE_WORDS) is False
    assert kept_pages(store, scan.id) == {"1": "Seite eins"}
    assert store.write_picture_text("doc_missing", 1, PICTURE_WORDS) is False


def test_a_letter_deleted_for_good_meanwhile_never_gets_the_file_back(store: Store) -> None:
    letter = private_photo(store)
    store.delete_document(letter.id)
    assert store.write_picture_text(letter.id, 1, PICTURE_WORDS) is False
    assert not (store.paths.derived / letter.id).exists()


def test_a_file_that_cant_be_written_is_logged_without_its_words(
    store: Store, caplog: pytest.LogCaptureFixture
) -> None:
    letter = private_photo(store)
    (store.paths.derived / letter.id).mkdir(parents=True)
    picture_file(store, letter.id).mkdir()  # a folder where the file should be
    with pytest.raises(OSError):  # not a refusal: the worker counts the page as failed
        store.write_picture_text(letter.id, 1, PICTURE_WORDS)
    assert "Kellerabteil" not in caplog.text and letter.id in caplog.text


# --------------------------------------------------------------------------------------------------
# finding letters by it
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query",
    [
        "Kellerabteil",
        "kellerabteil 7",
        "Gebaude Sud",
        "Gebäude",
        "abteil",
        "Musterstrasse",
        "Hausverwaltung GmbH",
    ],
)
def test_picture_text_matches_like_the_scanner_text(store: Store, query: str) -> None:
    """The very rules the indexes and the scanner text follow: whole words, and every term of three or more
    letters as a substring in either spelling of its umlauts."""
    letter = private_photo(store)
    store.write_picture_text(letter.id, 1, PICTURE_WORDS)
    assert store.picture_text_matches(query) == {letter.id}
    assert store.scan_text_matches(query) == set()


@pytest.mark.parametrize("query", ["Dachboden", "Kellerabteil 789", "", "*", "ab"])
def test_picture_text_matches_only_what_it_says(store: Store, query: str) -> None:
    letter = private_photo(store)
    store.write_picture_text(letter.id, 1, PICTURE_WORDS)
    assert store.picture_text_matches(query) == set()


def test_picture_text_counts_only_on_pages_without_text_and_not_in_the_trash(store: Store) -> None:
    """Search never sees it in Ask's search, the indexes or the letter's text; a page that has text of its own by
    now, or a letter in the trash, isn't matched by it. A letter let through to Claude keeps its match until Claude
    has read the page, as a scanner's text does."""
    letter = private_photo(store)
    store.write_picture_text(letter.id, 1, PICTURE_WORDS)
    assert store.search("Kellerabteil") == [] and store.list_documents(q="Kellerabteil") == []
    assert store.get_document_text(letter.id) == ""
    store.update_document(letter.id, ai_private=False, status="queued")
    assert store.picture_text_matches("Kellerabteil") == {letter.id}
    store.trash_document(letter.id)
    assert store.picture_text_matches("Kellerabteil") == set()
    store.restore_document(letter.id)
    store.set_page_text(letter.id, 1, "Was Claude las", "transcript")
    assert store.picture_text_matches("Kellerabteil") == set() and store.picture_text_pages(letter.id) == []


def test_scanner_text_and_picture_text_are_matched_apart(store: Store) -> None:
    """Each holds every searched word or doesn't count: a scan's scanner text on one page and the words read in
    the picture of another aren't put together."""
    scan = private_scan(store, pages=2)
    store.write_scan_text(scan.id, {1: "Ablesung Ihres Wasserzählers"})
    store.write_picture_text(scan.id, 2, PICTURE_WORDS)
    assert store.scan_text_matches("Wasserzählers") == {scan.id}
    assert store.picture_text_matches("Kellerabteil") == {scan.id}
    assert store.scan_text_matches("Wasserzählers Kellerabteil") == set()
    assert store.picture_text_matches("Wasserzählers Kellerabteil") == set()
    assert (store.scan_text_pages(scan.id), store.picture_text_pages(scan.id)) == ([1], [2])


# --------------------------------------------------------------------------------------------------
# forgetting it
# --------------------------------------------------------------------------------------------------


def test_reading_a_page_forgets_its_picture_text(store: Store) -> None:
    """Once Claude transcribed a page the words Ordnung read there go (``forget_scan_text_once_read`` keeps its
    name, the text stage calls it): pages still without text keep theirs, ``""`` included; the file goes with the
    last of them."""
    scan = private_scan(store, pages=3)
    for number, text in ((1, "Seite eins Kellerabteil"), (2, ""), (3, "Seite drei")):
        store.write_picture_text(scan.id, number, text)
    assert store.picture_text_matches("Kellerabteil") == {scan.id}  # cached now
    store.set_page_text(scan.id, 1, "Transkript der ersten Seite", "transcript")
    store.forget_scan_text_once_read(scan.id)
    assert kept_pages(store, scan.id) == {"2": "", "3": "Seite drei"}
    assert store.picture_text_matches("Kellerabteil") == set()
    for number in (2, 3):
        store.set_page_text(scan.id, number, "Transkript", "transcript")
    store.forget_scan_text_once_read(scan.id)
    assert not picture_file(store, scan.id).exists()
    assert scan.id not in store._picture_text_cache
    store.forget_scan_text_once_read(scan.id)  # nothing left to forget
    store.forget_scan_text_once_read("doc_missing")


def test_claude_reading_the_letter_forgets_its_picture_text_also_on_a_page_it_found_illegible(
    store: Store,
) -> None:
    """A page Claude transcribed as empty keeps no text of its own, yet Claude read it: once Claude has read the
    letter, what Ordnung read in its pictures no longer finds it, isn't named on its page, and is tidied away."""
    scan = private_scan(store, pages=2)
    store.write_picture_text(scan.id, 1, "Seite eins")
    store.write_picture_text(scan.id, 2, "Kündigung Mietvertrag")
    store.update_document(scan.id, ai_private=False, status="queued")  # let through to Claude
    # Claude's reading: page 1 transcribed, page 2 illegible (stored as transcribe_pages does), the text stage
    store.set_page_text(scan.id, 1, "Transkript der ersten Seite", "transcript")
    store.set_page_text(scan.id, 2, "", "none")
    store.forget_scan_text_once_read(scan.id)
    store.update_document(scan.id, status="processed", ai_processed_at="2026-09-24T10:00:00Z")
    assert store.picture_text_matches("Kündigung") == set()
    assert store.picture_text_pages(scan.id) == []
    assert store.picture_text_due() == [] and store.write_picture_text(scan.id, 2, "Kündigung") is False
    assert store.picture_text_stale() == [scan.id]
    store.forget_scan_text_once_read(scan.id)
    assert not picture_file(store, scan.id).exists() and store.picture_text_stale() == []


def test_picture_text_out_of_date_is_tidied(store: Store) -> None:
    """A file still holding the words of a page that has text of its own by now — Claude read it on a computer
    without text in pictures, then hand-off sync — is listed until it is tidied. A letter in the trash waits."""
    read = private_photo(store, "gelesen.jpg")
    store.write_picture_text(read.id, 1, PICTURE_WORDS)
    store.set_page_text(read.id, 1, "Transkript", "transcript")
    duplex = private_scan(store, "duplex.pdf", pages=2)
    store.write_picture_text(duplex.id, 1, "Vorderseite")
    store.write_picture_text(duplex.id, 2, "")
    store.set_page_text(duplex.id, 1, "Transkript", "transcript")
    waiting = private_photo(store, "wartet.jpg")
    store.write_picture_text(waiting.id, 1, PICTURE_WORDS)
    trashed = private_photo(store, "papierkorb.jpg")
    store.write_picture_text(trashed.id, 1, PICTURE_WORDS)
    store.set_page_text(trashed.id, 1, "Transkript", "transcript")
    store.trash_document(trashed.id)
    assert sorted(store.picture_text_stale()) == sorted([read.id, duplex.id])
    for doc_id in store.picture_text_stale():
        store.forget_scan_text_once_read(doc_id)
    assert store.picture_text_stale() == []
    assert not picture_file(store, read.id).exists() and kept_pages(store, duplex.id) == {"2": ""}
    assert kept_pages(store, waiting.id) == {"1": PICTURE_WORDS}
    store.restore_document(trashed.id)
    assert store.picture_text_stale() == [trashed.id]


def test_deleting_for_good_deletes_the_picture_text_and_its_folded_copy(store: Store) -> None:
    letter = private_photo(store)
    store.write_picture_text(letter.id, 1, PICTURE_WORDS)
    assert store.picture_text_matches("Kellerabteil") == {letter.id}  # cached now
    assert letter.id in store._picture_text_cache
    store.delete_document(letter.id)
    assert not (store.paths.derived / letter.id).exists()
    assert letter.id not in store._picture_text_cache
    assert store.picture_text_matches("Kellerabteil") == set()


def test_delete_everything_leaves_no_folded_copy_in_memory(store: Store) -> None:
    letter = private_photo(store)
    store.write_picture_text(letter.id, 1, PICTURE_WORDS)
    assert store.picture_text_matches("Kellerabteil") and store._picture_text_cache
    store.wipe()
    assert store._picture_text_cache == {} and store._scan_text_cache == {}
    assert store.picture_text_matches("Kellerabteil") == set()


def test_forgetting_all_picture_text_leaves_the_scanner_text(store: Store) -> None:
    """``ORDNUNG_OCR=off``: every ``picture-text.json`` goes (the worker does this when it starts); the scanner's
    text and the page images stay."""
    photo_letter = private_photo(store)
    store.write_picture_text(photo_letter.id, 1, PICTURE_WORDS)
    scan = private_scan(store, pages=2)
    store.write_scan_text(scan.id, {1: "Ablesung Ihres Wasserzählers"})
    store.write_picture_text(scan.id, 2, "Rückseite")
    assert store.picture_text_matches("Kellerabteil") == {photo_letter.id}  # cached now
    assert store.forget_all_picture_text() == 2
    assert list(store.paths.derived.rglob("picture-text.json")) == []
    assert store._picture_text_cache == {}
    assert store.picture_text_matches("Kellerabteil") == set()
    assert store.scan_text_matches("Wasserzählers") == {scan.id}
    assert store.forget_all_picture_text() == 0


# --------------------------------------------------------------------------------------------------
# the letter routes
# --------------------------------------------------------------------------------------------------


async def _search(api: Any, query: str) -> dict[str, str | None]:
    found = (await api.client.get("/api/documents", params={"q": query})).json()
    return {row["id"]: row["found_in"] for row in found}


async def test_search_finds_a_private_photo_by_its_picture_text_and_says_so(
    data_dir: Path, ocr_on: None
) -> None:
    """A private photo found only by the words Ordnung read in it is marked ``picture_text`` (not checked);
    the words themselves are never in an answer."""
    async with api_for(data_dir) as api:
        upload = await api.upload(("foto.jpg", photo("JPEG")), private=True)
        doc_id = str(upload["documents"][0]["id"])
        await api.read_all()
        assert await _search(api, "Kellerabteil") == {}
        assert api.ctx.store.picture_text_due() == [(doc_id, 1)]
        assert api.ctx.store.write_picture_text(doc_id, 1, PICTURE_WORDS)
        assert await _search(api, "Kellerabteil") == {doc_id: "picture_text"}
        assert await _search(api, "Gebaude Sud") == {doc_id: "picture_text"}
        assert await _search(api, "foto") == {doc_id: "letter"}
        listed = (await api.client.get("/api/documents")).json()
        assert [(row["id"], row["found_in"]) for row in listed] == [(doc_id, None)]
        public = (
            await api.client.get("/api/documents", params={"q": "Kellerabteil", "private": "false"})
        ).json()
        assert public == []
        detail = (await api.client.get(f"/api/documents/{doc_id}")).json()
        assert detail["picture_text_pages"] == [1] and detail["scan_text_pages"] == []
        answers = json.dumps([listed, detail, await _search(api, "Kellerabteil")])
        assert "Kellerabteil" not in answers and "Hausverwaltung" not in answers


async def test_a_letters_own_words_and_its_scanner_text_come_before_its_picture_text(
    data_dir: Path, ocr_on: None
) -> None:
    """A letter its own words find says nothing; one its scanner's text finds keeps the scanner line, even when
    the picture text matches too; only a letter found by the picture text alone says so."""
    async with api_for(data_dir) as api:
        named = await api.upload(("kellerabteil.jpg", photo("JPEG", size=(201, 100))), private=True)
        named_id = str(named["documents"][0]["id"])
        scan = await api.upload(("scan.pdf", scanned_pdf(ocr=True, blank_back=True)), private=True)
        scan_id = str(scan["documents"][0]["id"])
        other = await api.upload(("foto.jpg", photo("JPEG", size=(202, 100))), private=True)
        other_id = str(other["documents"][0]["id"])
        await api.read_all()
        store = api.ctx.store
        assert sorted(store.picture_text_due()) == sorted([(named_id, 1), (scan_id, 2), (other_id, 1)])
        assert store.write_picture_text(named_id, 1, "Ihr Kellerabteil 7")
        assert store.write_picture_text(scan_id, 2, "Rückseite Dachboden")
        assert store.write_picture_text(other_id, 1, PICTURE_WORDS)
        assert await _search(api, "Kellerabteil") == {named_id: "letter", other_id: "picture_text"}
        assert await _search(api, "Einkommensteuer") == {scan_id: "scanner_text"}
        assert await _search(api, "Dachboden") == {scan_id: "picture_text"}
        assert await _search(api, "Einkommensteuer Dachboden") == {}  # each must hold every word
        detail = (await api.client.get(f"/api/documents/{scan_id}")).json()
        assert (detail["scan_text_pages"], detail["picture_text_pages"]) == ([1], [2])


async def test_search_and_the_letters_page_ignore_picture_text_while_turned_off(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``ORDNUNG_OCR=off`` counts at once, on every request: no match and no pages, though the file is still
    there (the worker removes it when it next starts)."""
    monkeypatch.delenv(OCR_SWITCH)
    async with api_for(data_dir) as api:
        upload = await api.upload(("foto.jpg", photo("JPEG")), private=True)
        doc_id = str(upload["documents"][0]["id"])
        await api.read_all()
        api.ctx.store.write_picture_text(doc_id, 1, PICTURE_WORDS)
        assert await _search(api, "Kellerabteil") == {doc_id: "picture_text"}
        for off in ("off", " OFF ", "0", "false", "No"):
            monkeypatch.setenv(OCR_SWITCH, off)
            assert await _search(api, "Kellerabteil") == {}
            detail = (await api.client.get(f"/api/documents/{doc_id}")).json()
            assert detail["picture_text_pages"] == []
        assert picture_file(api.ctx.store, doc_id).is_file()
        monkeypatch.setenv(OCR_SWITCH, "on")
        assert await _search(api, "Kellerabteil") == {doc_id: "picture_text"}


async def test_the_letters_page_names_the_pages_with_picture_text(data_dir: Path, ocr_on: None) -> None:
    """Only the page numbers, and only of pages where words were found: a page Tesseract found nothing on isn't
    named."""
    async with api_for(data_dir) as api:
        scan = await api.upload(("scan.pdf", scanned_pdf(blank_back=True)), private=True)
        scan_id = str(scan["documents"][0]["id"])
        await api.read_all()
        store = api.ctx.store
        assert store.picture_text_due() == [(scan_id, 1), (scan_id, 2)]
        page = (await api.client.get(f"/api/documents/{scan_id}")).json()
        assert page["picture_text_pages"] == []
        store.write_picture_text(scan_id, 1, "")
        store.write_picture_text(scan_id, 2, "Kellerabteil")
        page = (await api.client.get(f"/api/documents/{scan_id}")).json()
        assert page["picture_text_pages"] == [2] and "Kellerabteil" not in json.dumps(page)


async def test_claude_reading_the_page_forgets_its_picture_text(data_dir: Path, ocr_on: None) -> None:
    """A photo Claude couldn't read is due; once *Try again* has Claude transcribe it, the text stage forgets
    what Ordnung read there (``forget_scan_text_once_read``): the file, the match and the page note go."""
    router = ApiRouter()
    async with api_for(data_dir, router=router) as api:
        upload = await api.upload(("foto.jpg", photo("JPEG")))
        doc_id = str(upload["documents"][0]["id"])
        await api.read_all()  # Claude found no words: it failed
        store = api.ctx.store
        failed = store.get_document(doc_id)
        assert failed is not None and failed.status == "failed" and not failed.ai_private
        assert store.picture_text_due() == [(doc_id, 1)]
        assert store.write_picture_text(doc_id, 1, PICTURE_WORDS)
        assert await _search(api, "Kellerabteil") == {doc_id: "picture_text"}

        router.transcript = TAX_LETTER.transcript()
        retried = await api.client.post(f"/api/documents/{doc_id}/reprocess")
        assert retried.status_code == 202, retried.text
        await api.read_all()
        read = store.get_document(doc_id)
        assert read is not None and read.status in ("processed", "needs_review")
        assert not picture_file(store, doc_id).exists()
        assert await _search(api, "Kellerabteil") == {}
        assert (await api.client.get(f"/api/documents/{doc_id}")).json()["picture_text_pages"] == []
        assert store.picture_text_due() == []


async def test_a_phone_s_search_says_where_it_found_a_letter_by_its_picture_text(
    data_dir: Path, ocr_on: None
) -> None:
    from phone_support import pair, phone_app, phone_client

    async with phone_app(data_dir) as (api, _, _):
        upload = await api.upload(("foto.jpg", photo("JPEG")), private=True)
        doc_id = str(upload["documents"][0]["id"])
        await api.read_all()
        api.ctx.store.write_picture_text(doc_id, 1, PICTURE_WORDS)
        async with phone_client(api) as phone:
            await pair(api, phone)
            found = await phone.get("/api/documents", params={"q": "Kellerabteil"})
            assert found.status_code == 200, found.text
            assert [(row["id"], row["found_in"]) for row in found.json()] == [(doc_id, "picture_text")]
            page = await phone.get(f"/api/documents/{doc_id}")
            assert page.status_code == 200 and page.json()["picture_text_pages"] == [1]
