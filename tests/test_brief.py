"""Daily brief: deterministic agenda, code-generated text, model note with free-text check and fallback."""

from __future__ import annotations

from datetime import date

import pytest

from helpers_secretary import TODAY, seed_ledger
from ordnung.db.store import Store
from ordnung.llm.base import LLMError, LLMRequest, LLMResponse
from ordnung.llm.fake import FakeBackend
from ordnung.llm.runtime import LLMService
from ordnung.models import Profile
from ordnung.secretary.brief import (
    Agenda,
    agenda_text,
    brief_cache_key,
    brief_text,
    build_agenda,
    generate_brief,
    get_brief,
    grounded_note,
)
from ordnung.secretary.triggers import run_and_reconcile

GOOD_NOTE = (
    "Good morning, Sam! Your library books were due on 20 Sep, and the TechMarkt reminder of €94.99 is "
    "due on Wed 30 Sep. Decide on FunkNetz mobile by 8 Oct."
)


@pytest.fixture
def ids(store: Store) -> dict[str, str]:
    return seed_ledger(store)


class FailingBackend:
    name = "fake"

    def __init__(self) -> None:
        self.calls: list[LLMRequest] = []

    async def complete(self, req: LLMRequest) -> LLMResponse:
        self.calls.append(req)
        raise LLMError("Claude is not signed in")

    async def stream(self, req: LLMRequest):  # pragma: no cover - not used
        raise LLMError("unused")
        yield


def test_build_agenda_is_deterministic(store: Store, ids: dict[str, str]) -> None:
    agenda = build_agenda(store, TODAY)
    assert [e.id for e in agenda.overdue] == [ids["library_task"]]
    assert agenda.today == []
    # the scam letter's "payment" and the incoming refund are no agenda entries
    assert [e.id for e in agenda.next_7_days] == [
        ids["parking_payment"],
        ids["dunning_payment"],
        ids["semester_fee"],
    ]
    assert [e.id for e in agenda.payments_this_month] == [ids["parking_payment"], ids["dunning_payment"]]
    assert agenda.payments_total == 119.99
    assert [e.id for e in agenda.decisions] == [ids["phone"]]
    assert agenda.decisions[0].date == "2026-10-08"
    assert build_agenda(store, TODAY) == agenda


def test_agenda_lists_new_ideas_and_a_missed_send_by_as_today(store: Store, ids: dict[str, str]) -> None:
    run_and_reconcile(store, TODAY)
    agenda = build_agenda(store, date(2026, 10, 16))  # objection send-by (15 Oct) passed, due 21 Oct
    assert ids["tax_objection"] in [e.id for e in agenda.today]
    assert len(build_agenda(store, TODAY).new_ideas) == 3


def test_agenda_text_is_plain_and_complete(store: Store, ids: dict[str, str]) -> None:
    text = agenda_text(build_agenda(store, TODAY))
    assert text.startswith("Overdue: Return library books (Sun 20 Sep).")
    assert (
        "Next 7 days: Pay parking fine (Tue 29 Sep, €25); Pay TechMarkt reminder (Wed 30 Sep, €94.99); "
        in text
    )
    assert "Payments this month: €119.99 in 2 payments." in text
    assert "Decide on your FunkNetz mobile: send a cancellation by Thu 8 Oct if you want to leave." in text


def test_agenda_text_all_clear() -> None:
    assert agenda_text(Agenda(date="2026-09-28")) == "All clear — nothing is due in the next 7 days."


def test_grounded_note_rejects_invented_facts(store: Store, ids: dict[str, str]) -> None:
    agenda = build_agenda(store, TODAY)
    assert grounded_note(GOOD_NOTE, agenda)
    assert not grounded_note("Pay €95 by Wed 30 Sep.", agenda)
    assert not grounded_note("Your appointment is on 12 Nov.", agenda)
    assert not grounded_note("Remember § 193 BGB.", agenda)
    assert not grounded_note("", agenda)


async def test_brief_text_uses_a_grounded_model_note_and_caches_it(store: Store, ids: dict[str, str]) -> None:
    backend = FakeBackend({"brief": {"text": GOOD_NOTE}})
    llm = LLMService(backend, sink=store)
    agenda = build_agenda(store, TODAY)
    profile = store.get_profile()
    brief = await brief_text(llm, agenda, profile, settings=store.get_settings())
    assert (brief.source, brief.text, brief.date) == ("llm", GOOD_NOTE, "2026-09-28")
    again = await brief_text(llm, agenda, profile, settings=store.get_settings())
    assert again.text == GOOD_NOTE and len(backend.calls) == 1  # cached per day + agenda hash
    request = backend.calls[0]
    assert request.purpose == "brief" and request.model == "haiku"
    assert request.cache_key == brief_cache_key(agenda, profile)
    assert request.cache_key.startswith("brief:2026-09-28:")
    assert "<untrusted_document>" in request.prompt and "Sam" in request.prompt
    assert "English" in request.system


async def test_brief_text_falls_back_when_the_note_invents_a_date(store: Store, ids: dict[str, str]) -> None:
    backend = FakeBackend({"brief": {"text": "Your tax objection is due on 12 Nov. Relax!"}})
    agenda = build_agenda(store, TODAY)
    brief = await brief_text(LLMService(backend), agenda, store.get_profile())
    assert brief.source == "template"
    assert brief.text == agenda_text(agenda)


async def test_brief_text_falls_back_when_the_model_fails(store: Store, ids: dict[str, str]) -> None:
    backend = FailingBackend()
    agenda = build_agenda(store, TODAY)
    brief = await brief_text(LLMService(backend), agenda, store.get_profile())
    assert brief.source == "template" and len(backend.calls) == 1


async def test_brief_text_needs_no_model_for_an_empty_agenda() -> None:
    backend = FakeBackend({})
    brief = await brief_text(LLMService(backend), Agenda(date="2026-09-28"), Profile())
    assert brief.source == "template" and backend.calls == []


async def test_private_letters_never_reach_the_model(store: Store, ids: dict[str, str]) -> None:
    store.update_item(ids["private_item"], due_date="2026-10-01")
    agenda = build_agenda(store, TODAY)
    assert any(entry.private for entry in agenda.next_7_days)
    backend = FakeBackend({"brief": {"text": GOOD_NOTE}})
    await brief_text(LLMService(backend), agenda, store.get_profile())
    assert "Therapy invoice" not in backend.calls[0].prompt
    assert ids["doc_private"] not in backend.calls[0].doc_ids


def test_cache_key_depends_on_language(store: Store, ids: dict[str, str]) -> None:
    agenda = build_agenda(store, TODAY)
    english = brief_cache_key(agenda, Profile(name="Sam", language="en"))
    german = brief_cache_key(agenda, Profile(name="Sam", language="de"))
    assert english != german and english == brief_cache_key(agenda, Profile(name="Sam", language="en"))


async def test_generate_brief_stores_the_brief_of_the_day(store: Store, ids: dict[str, str]) -> None:
    assert get_brief(store, TODAY) is None
    stored = await generate_brief(store, None, TODAY)
    assert stored.source == "template"
    assert get_brief(store, TODAY) == stored
    llm = LLMService(FakeBackend({"brief": {"text": GOOD_NOTE}}), sink=store)
    updated = await generate_brief(store, llm, TODAY)
    assert updated.source == "llm"
    loaded = get_brief(store, TODAY)
    assert loaded is not None and loaded.text == GOOD_NOTE
