"""A big inbox stays fast: 400 letters from 97 senders, read through the real routes.

The gate is the number of ``Store.list_documents`` calls a request makes, which doesn't depend on the
machine: one page of the app loads the letters once, never once per letter (the N+1 query of the
scam check made every page take seconds at 500 letters). The time budget on top is soft — generous
enough for a loaded CI runner, tight enough to catch a page that is back to seconds.
"""

from __future__ import annotations

import asyncio
import hashlib
import threading
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from fixtures_llm import TAX_LETTER, record_events
from helpers_secretary import add_doc, seed_ledger
from ordnung import clock
from ordnung.config import Paths
from ordnung.db.store import Store
from ordnung.ingest import pipeline
from ordnung.ingest.pipeline import add_file
from ordnung.models import DocumentExtraction, Evidence, Identifier, PaymentDetails
from ordnung.secretary import triggers
from test_api_support import Api, api_for, client_for

TODAY = date(2026, 9, 28)
LETTERS = 400
SENDERS = 97
#: Seconds one request may take with :data:`LETTERS` letters (a few times what it takes on a laptop).
BUDGET_S = 1.5
#: Seconds for every request of a page together.
PAGE_BUDGET_S = 3.0

_PARTY_KINDS = ("utility", "telecom", "insurer", "health_insurer", "retailer", "landlord", "bank", "gym")
_SENDER_WORDS = ("Stadtwerke", "Netz", "Versicherung", "Kasse", "Handel", "Wohnen", "Bank", "Fitness")
_KINDS = ("invoice", "invoice", "utility_bill", "dunning", "insurance", "contract_change", "bank_letter")
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
        fill_inbox(store)
        triggers.run_and_reconcile(store, TODAY)
    return data_dir


@pytest.fixture
async def api(inbox: Path) -> AsyncIterator[Api]:
    async with api_for(inbox) as client:
        yield client


#: The requests of the pages that read the whole ledger: Today, Timeline, Week, Numbers, the shell's
#: background-problem check, the calendar file and the waiting list.
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

    monkeypatch.setattr(pipeline, "triggers_hook", lambda: slow_triggers)
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
    runs: list[date] = []

    def slow_triggers(store: Store, today: date) -> None:
        gate.wait(10)
        runs.append(today)

    monkeypatch.setattr(pipeline, "triggers_hook", lambda: slow_triggers)
    for _ in range(3):  # the first starts a run; the others ask for one more after it
        api.ctx.worker.refresh_ideas()
        await asyncio.sleep(0.05)
    gate.set()
    await api.ctx.worker.ideas_settled()
    assert runs == [TODAY, TODAY]


# --------------------------------------------------------------------------------------------------
# Soft time budget
# --------------------------------------------------------------------------------------------------


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
