"""A big inbox stays fast: 400 letters from 97 senders, read through the real routes.

The gate is the number of ``Store.list_documents`` calls a request makes, which doesn't depend on the
machine: one page of the app loads the letters once, never once per letter (the N+1 query of the
scam check made every page take seconds at 500 letters). The time budget on top is soft — generous
enough for a loaded CI runner, tight enough to catch a page that is back to seconds. The letter list
has a size budget too: it leaves out each letter's reading, which the letter's own page loads.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import sys
import threading
import time
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from fixtures_llm import TAX_LETTER, record_events
from helpers_secretary import add_doc, seed_ledger
from ordnung import clock
from ordnung.api.routes.documents import LEFT_OUT_OF_LIST
from ordnung.config import Paths
from ordnung.db.store import TAX_CHOICES_META_KEY, Store
from ordnung.ingest import pipeline
from ordnung.ingest.pipeline import add_file
from ordnung.models import DocumentExtraction, Evidence, Identifier, PaymentDetails
from ordnung.secretary import household, triggers
from ordnung.secretary.week import pending_items
from ordnung.views import weekly_session
from test_api_support import Api, api_for, client_for

TODAY = date(2026, 9, 28)
LETTERS = 400
SENDERS = 97
#: Seconds one request may take with :data:`LETTERS` letters (a few times what it takes on a laptop).
BUDGET_S = 1.5
#: Seconds for every request of a page together.
PAGE_BUDGET_S = 3.0
#: Letters of the small and the large library of the growth check: four times the letters (and senders).
GROWTH_LETTERS = (100, 400)
#: How much more work the large library may take: about four times as much, never sixteen.
GROWTH_LIMIT = 5.5
#: What the letter list may weigh, as a share of the same letters whole (``GET /api/documents.json``):
#: it leaves out each letter's explanation, key facts, references, bank details and file hash. About
#: half here, where a letter has no key facts (a quarter on the demo, where key facts are half the bytes).
LIST_SHARE = 0.6
#: Bytes of JSON a list row may take on average: about a kilobyte, a title and a summary with the rest.
ROW_BYTES = 1_200
#: What the letter list may weigh on the wire, as a share of its JSON: answers are gzip-compressed.
WIRE_SHARE = 0.10

_PARTY_KINDS = ("utility", "telecom", "insurer", "health_insurer", "retailer", "landlord", "bank", "gym")
_SENDER_WORDS = ("Stadtwerke", "Netz", "Versicherung", "Kasse", "Handel", "Wohnen", "Bank", "Fitness")
_KINDS = ("invoice", "invoice", "utility_bill", "dunning", "insurance", "contract_change", "bank_letter")
#: Who the letters are addressed to: mostly the person, now and then someone of the household or a family.
_RECIPIENTS = (
    "Sam Rivera",
    "Sam Rivera",
    "Alex Rivera",
    "Sam Rivera",
    "Mia Rivera",
    "Familie Rivera",
    "Kim Rivera",
)
#: The household of the big inbox: three people, a few letters filed for them (``/api/household``).
_HOUSEHOLD = ("Alex Rivera", "Mia Rivera", "Jo Rivera")
_TEXT = (
    "Sehr geehrte Damen und Herren, wir bedanken uns für Ihr Vertrauen. Bitte überweisen Sie den Betrag "
    "bis zum genannten Datum auf das angegebene Konto. Bei Fragen erreichen Sie uns werktags. "
)


def iban(number: int) -> str:
    """A German IBAN with valid check digits (bank code and account derived from ``number``)."""
    bban = f"{10_000_000 + number:08d}{number * 7919 % 10**10:010d}"
    check = 98 - int(bban + "131400") % 97
    return f"DE{check:02d}{bban}"


def _day(offset: int) -> str:
    return (TODAY - timedelta(days=offset)).isoformat()


def fill_inbox(store: Store, letters: int = LETTERS, senders: int = SENDERS) -> list[str]:
    """``letters`` processed letters from ``senders`` senders, two to-dos each, a contract for every
    fourth sender; mostly paid bills over two years, a payment reminder now and then (taking over its
    invoice) and a letter asking for an account the sender never used. Returns the letter ids."""
    doc_ids: list[str] = []
    with store.tx():
        store.save_profile({"name": "Sam Rivera", "language": "en", "region": "NW", "onboarded": True})
        parties = []
        for n in range(senders):
            name = f"{_SENDER_WORDS[n % len(_SENDER_WORDS)]} Muster {n:02d} GmbH"
            party = store.add_party(
                name=name, kind=_PARTY_KINDS[n % len(_PARTY_KINDS)], ibans=[iban(n)] if n % 3 else []
            )
            case = store.add_case(title=f"Account {n:02d}", party_id=party.id)
            parties.append((party, case))
            if n % 4 == 0:
                store.add_contract(
                    name=f"{name} contract",
                    party_id=party.id,
                    category="mobile" if n % 8 == 0 else "energy",
                    start_date=_day(400 + n),
                    initial_term_months=24,
                    renewal_term_months=1,
                    notice_value=1,
                    notice_unit="months",
                    cost_amount=20.0 + n,
                    cost_interval="monthly",
                )
        for i in range(letters):
            party, case = parties[i % senders]
            kind = _KINDS[i % len(_KINDS)]
            age = (letters - i) * 730 // letters
            invoice_no = f"RE-{i - len(_KINDS) * senders if kind == 'dunning' else i:05d}"
            paying = kind in ("invoice", "utility_bill", "dunning")
            account = iban(1000 + i) if i % 41 == 7 else iban(i % senders)
            payment = PaymentDetails(iban=account, payee=party.name, reference=invoice_no) if paying else None
            title = f"{party.name}: {kind.replace('_', ' ')} {i}"
            references = [Identifier(label="Rechnungsnummer", value=invoice_no)] if paying else []
            doc = store.add_document(
                sha256=hashlib.sha256(f"letter {i}".encode()).hexdigest(),
                filename=f"letter-{i:03d}.pdf",
                mime="application/pdf",
                file_path=f"files/letter-{i:03d}.pdf",
                received_date=_day(age - 2),
            )
            extraction = DocumentExtraction(
                kind=kind,
                title=title,
                summary=f"{title}. " + _TEXT,
                explanation=_TEXT * 4,
                references=references,
                payment=payment,
                recipient_name=_RECIPIENTS[i % len(_RECIPIENTS)],
            )
            store.update_document(
                doc.id,
                status="processed",
                kind=kind,
                area="money" if paying else "home",
                title=title,
                summary=extraction.summary,
                explanation=extraction.explanation,
                doc_date=_day(age),
                party_id=party.id,
                case_id=case.id if paying else None,
                references=references,
                payment=payment,
                extraction=extraction,
                text=_TEXT * 8,
            )
            evidence = [Evidence(doc_id=doc.id, page=1, quote=f"Betrag {20 + i % 50},00 EUR")]
            store.add_item(
                kind="payment" if paying else "task",
                title=f"Pay {party.name}" if paying else f"Check {title}",
                amount=20.0 + i % 50 if paying else None,
                currency="EUR" if paying else None,
                direction="out" if paying else None,
                due_date=_day(age - 14),
                status="done" if age > 180 else "open",
                party_id=party.id,
                doc_id=doc.id,
                evidence=evidence,
                grounding="verified",
                due_date_source="fixed",
            )
            store.add_item(
                kind="deadline",
                title=f"Object to {title}",
                due_date=_day(age - 30),
                status="dismissed" if age > 365 else "open",
                party_id=party.id,
                doc_id=doc.id,
                evidence=evidence,
                grounding="verified",
                due_date_source="computed",
            )
            doc_ids.append(doc.id)
    return doc_ids


# --------------------------------------------------------------------------------------------------
# Counting the store's work
# --------------------------------------------------------------------------------------------------


@contextmanager
def counting(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, int]]:
    """How often each tracked store read ran inside the block."""
    counts = {"list_documents": 0}
    original = Store.list_documents

    def tracked(self: Store, *args: Any, **kwargs: Any) -> Any:
        counts["list_documents"] += 1
        return original(self, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Store, "list_documents", tracked)
        yield counts


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


@pytest.fixture(scope="module")
def inbox(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One data folder with the big inbox, shared by the tests of this module (they only read it, or
    put it back as it was)."""
    data_dir = tmp_path_factory.mktemp("inbox") / "data"
    with Store.open(Paths(data_dir)) as store:
        letters = fill_inbox(store)
        triggers.run_and_reconcile(store, TODAY)
        people = household.change(store, base=household.version([]), members=[_Person(n) for n in _HOUSEHOLD])
        alex, mia, _jo = (person["id"] for person in people["members"])
        household.file(store, {letters[2]: alex, letters[4]: mia, letters[9]: household.MINE})
    return data_dir


@dataclass(frozen=True)
class _Person:
    """A new person of the household (``MemberIn``)."""

    name: str
    id: str | None = None
    signs: bool = True


@pytest.fixture
async def api(inbox: Path) -> AsyncIterator[Api]:
    async with api_for(inbox) as client:
        yield client


#: The requests of the pages that read the whole ledger: Today, Timeline, Week, Numbers, the shell's
#: background-problem check, the calendar file, the waiting list and the household (Inbox, Settings).
LEDGER_PAGES = (
    "/api/dashboard",
    "/api/brief",
    "/api/items",
    "/api/timeline?from=2026-06-01&to=2027-03-31",
    "/api/lanes?from=2026-06-01&to=2027-03-31",
    "/api/week",
    "/api/numbers",
    "/api/waiting",
    "/api/suggestions",
    "/api/calendar.ics",
    "/api/calendar/sync",
    "/api/reminders/desktop?preview=false",
    "/api/household",
)


# --------------------------------------------------------------------------------------------------
# The gate: the letters are loaded once, not once per letter
# --------------------------------------------------------------------------------------------------


async def test_every_ledger_page_loads_the_letters_once(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    """After a change, the first request loads the letters once and every request after it shares them
    until the next change (before: one query per letter with a payment, 200–550 per request)."""
    api.ctx.store.set_meta("perf-test", "a change")
    with counting(monkeypatch) as counts:
        for url in LEDGER_PAGES:
            response = await api.client.get(url)
            assert response.status_code == 200, (url, response.text[:200])
    assert counts["list_documents"] == 1


async def test_a_letter_page_reads_a_handful_of_lists(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    letter = next(doc for doc in api.ctx.store.list_documents(kind="dunning") if doc.title)
    api.ctx.store.set_meta("perf-test", "another change")
    with counting(monkeypatch) as counts:
        response = await api.client.get(f"/api/documents/{letter.id}")
    assert response.status_code == 200
    assert response.json()["set_aside"] or response.json()["items"]
    assert counts["list_documents"] <= 3


async def test_reading_a_letter_loads_the_others_once(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    """The triggers after a letter is read (and the reading itself) don't query per letter."""
    with counting(monkeypatch) as counts:
        document = await add_file(api.ctx, TAX_LETTER.pdf(), "extra.pdf")
        assert await api.read_all() == 1
    try:
        assert counts["list_documents"] <= 3
    finally:
        api.ctx.store.delete_document(document.id)
        triggers.run_and_reconcile(api.ctx.store, TODAY)


async def test_marking_a_to_do_done_doesnt_wait_for_the_ideas(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The to-do is saved and answered at once; the Ideas follow in the background and say so with
    ``suggestions.updated``."""
    gate = threading.Event()
    ran: list[date] = []

    def slow_triggers(store: Store, today: date) -> None:
        gate.wait(10)
        ran.append(today)

    monkeypatch.setattr(pipeline, "run_and_reconcile", slow_triggers)
    events = record_events(api.ctx.bus)
    item = api.ctx.store.list_items(status="open")[0]
    async with client_for(api.app) as raw:  # without the test client's wait for the Ideas
        response = await asyncio.wait_for(raw.patch(f"/api/items/{item.id}", json={"status": "done"}), 5)
    assert response.status_code == 200 and response.json()["status"] == "done"
    assert ran == [] and "suggestions.updated" not in [kind for kind, _ in events]
    gate.set()
    await api.ctx.worker.ideas_settled()
    assert ran == [TODAY] and "suggestions.updated" in [kind for kind, _ in events]
    api.ctx.store.update_item(item.id, status="open")


async def test_changes_while_the_ideas_refresh_get_one_more_run(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = threading.Event()
    started = threading.Event()
    runs: list[date] = []

    def slow_triggers(store: Store, today: date) -> None:
        started.set()
        gate.wait(10)
        runs.append(today)

    monkeypatch.setattr(pipeline, "run_and_reconcile", slow_triggers)
    api.ctx.worker.refresh_ideas()  # starts a run
    assert await asyncio.to_thread(started.wait, 5)
    for _ in range(2):  # the run is under way: these ask for one more after it
        api.ctx.worker.refresh_ideas()
    gate.set()
    await api.ctx.worker.ideas_settled()
    assert runs == [TODAY, TODAY]


# --------------------------------------------------------------------------------------------------
# Soft time budget
# --------------------------------------------------------------------------------------------------


@pytest.mark.slow  # a wall-clock budget: coverage alone makes the pages about twice as slow
async def test_pages_answer_in_time(api: Api) -> None:
    """Each request of the ledger pages, and all of them together, after a change (the cold case)."""
    api.ctx.store.set_meta("perf-test", "a third change")
    slow: dict[str, float] = {}
    total = 0.0
    for url in LEDGER_PAGES:
        start = time.perf_counter()
        response = await api.client.get(url)
        took = time.perf_counter() - start
        total += took
        assert response.status_code == 200
        if took > BUDGET_S:
            slow[url] = round(took, 2)
    assert not slow, f"slower than {BUDGET_S}s with {LETTERS} letters: {slow}"
    assert total < PAGE_BUDGET_S, f"{total:.2f}s for every ledger page with {LETTERS} letters"


# --------------------------------------------------------------------------------------------------
# The letter list stays light
# --------------------------------------------------------------------------------------------------


async def test_the_letter_list_stays_light(api: Api) -> None:
    """With :data:`LETTERS` letters no row of the list carries a letter's reading (the letter's own page
    and the copy of your records have it), and the list weighs well under the same letters whole."""
    listed = await api.client.get("/api/documents")
    whole = await api.client.get("/api/documents.json")
    assert listed.status_code == whole.status_code == 200
    rows, letters = listed.json(), whole.json()
    assert len(rows) == len(letters) == LETTERS
    assert not [row["id"] for row in rows if LEFT_OUT_OF_LIST & set(row)]
    assert all(letter["explanation"] for letter in letters)
    share = len(listed.content) / len(whole.content)
    assert share < LIST_SHARE, f"the list is {share:.0%} of the letters whole with {LETTERS} letters"
    per_row = len(listed.content) / LETTERS
    assert per_row < ROW_BYTES, f"{per_row:.0f} bytes of JSON per list row"


async def test_the_letter_list_is_light_on_the_wire(api: Api) -> None:
    """With :data:`LETTERS` letters the list arrives gzip-compressed, at under a tenth of its JSON."""
    listed = await api.client.get("/api/documents", headers={"Accept-Encoding": "gzip"})
    assert listed.status_code == 200 and len(listed.json()) == LETTERS
    assert listed.headers.get("content-encoding") == "gzip"
    share = listed.num_bytes_downloaded / len(listed.content)
    assert share < WIRE_SHARE, f"{listed.num_bytes_downloaded} bytes on the wire, {share:.0%} of its JSON"


# --------------------------------------------------------------------------------------------------
# The work grows with the library, never with its square
# --------------------------------------------------------------------------------------------------


def lines_run(work: Callable[[], object], package: str = str(Path("ordnung") / "secretary")) -> int:
    """How many lines of ``package`` ``work`` runs: a measure of its work that doesn't depend on the machine."""
    count = 0

    def line(frame: Any, event: str, arg: Any) -> Any:
        nonlocal count
        count += event == "line"
        return line

    def call(frame: Any, event: str, arg: Any) -> Any:
        return line if package in frame.f_code.co_filename else None

    sys.settrace(call)
    try:
        work()
    finally:
        sys.settrace(None)
    return count


@pytest.mark.slow  # counts lines with sys.settrace, the hook coverage uses
def test_the_ideas_refresh_and_the_week_page_grow_with_the_letters_not_their_square(tmp_path: Path) -> None:
    """Four times the letters and senders take about four times the work: no letter's or sender's to-dos are
    found by looking through every to-do. The Week page counted each new letter's open to-dos that way, and
    the Ideas refresh (after every reading) looked through every to-do for each letter before asking whether
    it was a payment reminder, and through every letter for each reminder and each sender."""
    work: dict[int, tuple[int, int]] = {}
    for letters in GROWTH_LETTERS:
        with Store.open(Paths(tmp_path / str(letters))) as store:
            fill_inbox(store, letters, senders=letters // 4)
            # twice: the second run changes nothing, so the counted one reads the rows already loaded
            triggers.run_and_reconcile(store, TODAY)
            triggers.run_and_reconcile(store, TODAY)
            ideas = lines_run(lambda: triggers.run_and_reconcile(store, TODAY))
            weekly_session(store, TODAY)
            week = lines_run(lambda: weekly_session(store, TODAY))
            work[letters] = (ideas, week)
    (small_ideas, small_week), (large_ideas, large_week) = (work[letters] for letters in GROWTH_LETTERS)
    assert large_ideas / small_ideas < GROWTH_LIMIT, work
    assert large_week / small_week < GROWTH_LIMIT, work


def test_the_week_page_counts_each_new_letters_open_to_dos(inbox: Path) -> None:
    """Every letter of the big inbox is new this week (a bulk import): each row the step shows says how many of
    its letter's to-dos are open, or that it has none."""
    with Store.open(Paths(inbox)) as store:
        open_by_letter: dict[str, int] = {}
        for item in pending_items(triggers.Ledger(store, TODAY)):
            open_by_letter[item.doc_id or ""] = open_by_letter.get(item.doc_id or "", 0) + 1
        new = next(step for step in weekly_session(store, TODAY).steps if step.id == "new")
    counted = 0
    for entry in new.entries:
        found = re.fullmatch(r"(\d+) open to-dos?", entry.note or "")
        if found:
            assert int(found[1]) == open_by_letter[entry.doc_id or ""], entry
            counted += 1
        elif entry.note == "Nothing to do — filed.":
            assert entry.doc_id not in open_by_letter, entry
    assert counted and new.more > 0, new


# --------------------------------------------------------------------------------------------------
# The shared rows answer like the store
# --------------------------------------------------------------------------------------------------


def test_scam_signs_from_the_shared_rows_are_the_stores(inbox: Path) -> None:
    """Every letter's scam warning signs, the sender's letters read from the shared rows, are what the
    scam checks find asking the store itself (letters asking for an account their sender never used
    included)."""
    with Store.open(Paths(inbox)) as store:
        ledger = triggers.Ledger(store, TODAY)
        flagged = 0
        for doc in ledger.documents.values():
            party = ledger.parties.get(doc.party_id or "")
            expected = triggers._scam_reasons(store, doc, party) if doc.direction == "incoming" else []
            assert ledger.scam_reasons(doc) == expected, doc.id
            flagged += bool(expected)
        assert flagged >= LETTERS // 41


def test_the_shared_rows_follow_every_change(paths: Paths) -> None:
    """A change by another connection, by this one, or of the schema is seen at once; rows read inside
    a transaction are never shared (they may not be committed)."""
    with Store.open(paths) as store, Store.open(paths) as other:
        seed_ledger(store)
        first = triggers.Ledger(store, TODAY)
        assert triggers.Ledger(store, TODAY).documents == first.documents  # unchanged: shared
        assert triggers.Ledger(store, TODAY)._rows is first._rows

        added = add_doc(other, "from-another-connection", title="Another connection")
        assert added in triggers.Ledger(store, TODAY).documents

        store.update_document(added, title="Renamed here")
        assert triggers.Ledger(store, TODAY).documents[added].title == "Renamed here"
        assert triggers.Ledger(store, TODAY).extraction(added) is None  # read once, and kept
        reading = DocumentExtraction(kind="other", title="Read again", summary="Read.", explanation="Read.")
        store.update_document(added, extraction=reading)
        assert triggers.Ledger(store, TODAY).extraction(added) == reading

        class Rollback(Exception):
            pass

        with pytest.raises(Rollback), store.tx():
            store.update_document(added, title="Never committed")
            assert triggers.Ledger(store, TODAY).documents[added].title == "Never committed"
            raise Rollback
        assert triggers.Ledger(store, TODAY).documents[added].title == "Renamed here"

        store.wipe()
        assert triggers.Ledger(store, TODAY).documents == {}


def test_the_shared_rows_follow_changes_made_in_other_threads(paths: Paths) -> None:
    """Each thread has its own connection: a change committed in one is seen by the others."""
    with Store.open(paths) as store:
        seed_ledger(store)
        before = len(triggers.Ledger(store, TODAY).documents)
        seen: list[int] = []

        def in_a_thread() -> None:
            seen.append(len(triggers.Ledger(store, TODAY).documents))
            add_doc(store, "from-a-thread", title="From a thread")
            seen.append(len(triggers.Ledger(store, TODAY).documents))

        worker = threading.Thread(target=in_a_thread)
        worker.start()
        worker.join()
        assert seen == [before, before + 1]
        assert len(triggers.Ledger(store, TODAY).documents) == before + 1


def test_rows_loaded_behind_an_unfinished_read_are_not_kept_for_the_others(paths: Paths) -> None:
    """A thread whose connection still has a read open (a cursor read part of the way) sees the database as
    it was when that read began. Rows it loaded then must not be kept for the commit made since: every other
    thread would be shown the old rows until the next commit."""
    with Store.open(paths) as store, Store.open(paths) as other:
        seed_ledger(store)
        item = next(item for item in store.list_items() if item.status == "open")
        triggers.Ledger(store, TODAY)
        seen: dict[str, str] = {}

        def pinned() -> None:
            cursor = store._conn().execute("SELECT id FROM documents")
            cursor.fetchone()  # the read stays open: this connection keeps seeing the database as it was
            other.update_item(item.id, status="done")
            seen["pinned"] = next(i.status for i in triggers.Ledger(store, TODAY).items if i.id == item.id)
            cursor.close()

        def after() -> None:
            seen["after"] = next(i.status for i in triggers.Ledger(store, TODAY).items if i.id == item.id)

        for target in (pinned, after):
            worker = threading.Thread(target=target)
            worker.start()
            worker.join()
        assert seen == {"pinned": "done", "after": "done"}


def test_a_ledger_of_an_unchanged_database_reads_only_the_commit_stamp(paths: Paths) -> None:
    """Several Ledgers are built per request: while nothing changed, each looks at the commit stamp once (two
    PRAGMAs) and takes the kept rows, nothing more."""
    with Store.open(paths) as store:
        seed_ledger(store)
        triggers.Ledger(store, TODAY)
        assert store._watch is not None
        ran: list[str] = []
        connections = (store._conn(), store._watch)
        for conn in connections:
            conn.set_trace_callback(ran.append)
        try:
            for _ in range(3):
                triggers.Ledger(store, TODAY)
        finally:
            for conn in connections:
                conn.set_trace_callback(None)
        assert len(ran) <= 3 * 2, ran


def test_only_the_readings_that_state_a_change_are_parsed(
    paths: Paths, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cancellation confirmations and price increases are found by one query: the ledger parses those
    letters' readings, not every letter's (at 3,000 letters, most of a second per reload of the rows)."""
    with Store.open(paths) as store:
        ids = seed_ledger(store)
        for n in range(30):
            reading = DocumentExtraction(kind="invoice", title=f"Rechnung {n}", summary="s", explanation="e")
            add_doc(store, f"plain-{n}", kind="invoice", title=f"Rechnung {n}", extraction=reading)
        parsed: list[str] = []
        original = DocumentExtraction.model_validate_json

        def counted(data: Any, *args: Any, **kwargs: Any) -> DocumentExtraction:
            parsed.append("x")
            return original(data, *args, **kwargs)

        monkeypatch.setattr(DocumentExtraction, "model_validate_json", counted)
        ledger = triggers.Ledger(store, TODAY)
        confirmations, windows = ledger.pending_confirmations(), ledger.price_increase_windows()
        assert [doc.id for doc, _ in confirmations.values()] == [ids["doc_gym_confirm"]]
        assert [window.letter.id for window in windows] == [ids["doc_power"]]
        assert len(parsed) == 2


def test_the_api_threads_share_one_load_per_change(paths: Paths) -> None:
    """The API answers in a pool of threads, each with its own connection: after a change the rows are
    loaded once for all of them, not once per thread (four threads after one change made four loads,
    one after the other, a few seconds each at 3,000 letters)."""
    from concurrent.futures import ThreadPoolExecutor

    from ordnung.secretary import ledger as ledger_module

    with Store.open(paths) as store, Store.open(paths) as other:
        seed_ledger(store)
        triggers.Ledger(store, TODAY)
        cache = ledger_module._CACHES[store]

        def loads_in_new_threads(count: int) -> int:
            before = cache._loads
            with ThreadPoolExecutor(count) as pool:
                list(pool.map(lambda _: triggers.Ledger(store, TODAY), range(count)))
            return cache._loads - before

        assert loads_in_new_threads(4) == 0  # nothing changed: every new thread takes the rows loaded
        added = add_doc(other, "from-another-connection", title="Another connection")
        assert loads_in_new_threads(4) == 1
        store.update_document(added, title="Renamed in this store")
        assert loads_in_new_threads(6) == 1
        with ThreadPoolExecutor(4) as pool:  # a pool's threads write too: one load after each change
            pool.submit(store.update_document, added, title="Renamed in a thread").result()
            assert loads_in_new_threads(4) == 1
            titles = pool.map(lambda _: triggers.Ledger(store, TODAY).documents[added].title, range(4))
            assert set(titles) == {"Renamed in a thread"}


def _repeating_to_dos(store: Store, count: int) -> None:
    """``count`` repeating payments, each to a sender of its own and by a rule of its own kind: every month on
    a day, every few months on a working day, every year, every 2 weeks."""
    from ordnung.models import Recurrence

    rules = [
        Recurrence(interval=1, unit="months", day_of_month=1 + n % 28)
        if n % 4 == 0
        else Recurrence(interval=1 + n % 3, unit="months", working_day=1 + n % 3)
        if n % 4 == 1
        else Recurrence(interval=1, unit="years")
        if n % 4 == 2
        else Recurrence(interval=2, unit="weeks")
        for n in range(count)
    ]
    for n, rule in enumerate(rules):
        party = store.add_party(name=f"Payee {n:03d}", kind="other").id
        store.add_item(
            kind="payment",
            title=f"Fee {n:03d}",
            due_date=(TODAY + timedelta(days=1 + n % 60)).isoformat(),
            recurrence=rule,
            amount=10.0 + n,
            currency="EUR",
            direction="out",
            party_id=party,
            grounding="verified",
        )


@pytest.mark.slow  # times its own growth (helpers_timing): a wall-clock ratio
def test_ask_lists_200_repeating_to_dos_quickly(tmp_path: Path) -> None:
    """Every repeating to-do in Ask's list says how it repeats and where it moves on to once done,
    which the dates engine works out per to-do: four times the to-dos take about four times the time, never
    sixteen (CPU time of this thread, the faster of two runs: ``helpers_timing``), and 200 of them a few
    tenths of a second on a laptop."""
    from helpers_timing import MAX_GROWTH, NOISE_FLOOR_SECONDS, read_seconds
    from ordnung.assistant.mcp_server import LedgerTools

    took: dict[int, float] = {}
    for count in (50, 200):
        with Store.open(Paths(tmp_path / str(count))) as store:
            _repeating_to_dos(store, count)
            tools = LedgerTools(store, today=TODAY)
            rows = tools.list_items(status="all", limit=count).record["items"]
            assert len(rows) == count and all(row.get("following_due_date") for row in rows)
            took[count] = read_seconds("", lambda _: tools.list_items(status="all", limit=count))
    assert took[200] < MAX_GROWTH * max(took[50], NOISE_FLOOR_SECONDS), took


@pytest.mark.slow  # a wall-clock budget
def test_setting_a_tax_choice_among_5000_stays_fast(paths: Paths) -> None:
    """The person's "For taxes" choices are one JSON row, read and written whole on every press: with
    5,000 choices a press still takes under 50 ms."""
    with Store.open(paths) as store:
        with store.tx() as conn:
            conn.executemany(
                "INSERT INTO documents (id, sha256, filename, mime, file_path, created_at, updated_at) VALUES "
                "(?, ?, ?, 'application/pdf', ?, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')",
                [(f"doc_{n:012d}", f"{n:064x}", f"{n}.pdf", f"files/{n}.pdf") for n in range(5000)],
            )
        choices = {f"doc_{n:012d}": n % 2 == 0 for n in range(5000)}
        store.set_meta(TAX_CHOICES_META_KEY, json.dumps(choices, sort_keys=True, separators=(",", ":")))
        took = []
        for n, choice in ((7, True), (8, False), (9, None)):
            start = time.perf_counter()
            assert store.set_tax_choice(f"doc_{n:012d}", choice) is True
            took.append(time.perf_counter() - start)
        assert len(store.tax_choices()) == 4999
        assert sorted(took)[1] < 0.05, took
