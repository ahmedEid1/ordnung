"""Audit: regression tests for user-visible bugs found by reading and probing the core flows.

Every test here reproduced a bug (it failed before the fix) and describes the correct behaviour.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from fixtures_llm import DUNNING_LETTER, INVOICE_LETTER, SCAM_IBAN, TAX_LETTER, Letter
from ordnung import clock
from ordnung.ingest.plan import item_context
from ordnung.recurrence import roll_forward
from test_api_support import Api, ApiRouter, api_for

MONTHLY = {"interval": 1, "unit": "months"}


@pytest.fixture(autouse=True)
def unpinned_after_test() -> Iterator[None]:
    yield
    clock.set_today(None)


async def _open_items(api: Api, **params: str) -> list[dict[str, Any]]:
    response = await api.client.get("/api/items", params={"status": "open", **params})
    assert response.status_code == 200, response.text
    return list(response.json())


# --------------------------------------------------------------------------------------------------
# Recurring obligations
# --------------------------------------------------------------------------------------------------


async def test_marking_a_recurring_payment_done_keeps_the_series_going(data_dir: Path) -> None:
    """Paying this month's rent ("Pay" → "Mark as paid" on Today) must not cancel next month's rent.

    ``recurrence.roll_forward`` only moves items that are ``open``/``snoozed``; a ``done`` recurring
    item never came back, so the monthly obligation silently disappeared after the first payment. Now
    "done" moves it on to the next month and it stays open.
    """
    clock.set_today("2026-09-25")
    async with api_for(data_dir) as api:
        created = await api.client.post(
            "/api/items",
            json={
                "kind": "payment",
                "title": "Rent",
                "due_date": "2026-10-01",
                "amount": 650.0,
                "recurrence": MONTHLY,
            },
        )
        assert created.status_code == 201, created.text
        item_id = created.json()["id"]
        paid = await api.client.patch(f"/api/items/{item_id}", json={"status": "done"})
        assert paid.status_code == 200

        rent = [item for item in await _open_items(api) if item["title"] == "Rent"]
        assert [item["due_date"] for item in rent] == ["2026-11-01"]

        roll_forward(api.ctx.store, date(2026, 11, 2), item_context)  # what the daily tick does on 2 Nov

        rent = [item for item in await _open_items(api) if item["title"] == "Rent"]
        assert [item["due_date"] for item in rent] == ["2026-12-01"]


async def test_manual_monthly_item_keeps_its_day_of_month_after_february(data_dir: Path) -> None:
    """A to-do added by hand "every month on the 31st" must come back on 31 March, not 28 March.

    Manual items had no ``date_spec``, so the schedule fell back to the *current* due date: after it
    was clipped to 28 Feb, every later occurrence was computed from the 28th.
    """
    clock.set_today("2026-01-20")
    async with api_for(data_dir) as api:
        created = await api.client.post(
            "/api/items",
            json={
                "kind": "payment",
                "title": "Savings plan",
                "due_date": "2026-01-31",
                "amount": 50.0,
                "recurrence": MONTHLY,
            },
        )
        item_id = created.json()["id"]
        roll_forward(api.ctx.store, date(2026, 2, 5), item_context)
        assert api.ctx.store.get_item(item_id).due_date == "2026-02-28"
        roll_forward(api.ctx.store, date(2026, 3, 5), item_context)
        assert api.ctx.store.get_item(item_id).due_date == "2026-03-31"


async def test_confirming_the_arrival_date_keeps_a_rolled_recurring_date(data_dir: Path) -> None:
    """Answering "When did this letter arrive?" must not turn next month's instalment into an
    overdue payment: ``recompute_document_items`` recomputes the stored DateSpec (the *first*
    occurrence) and overwrites the rolled-forward date; nothing rolls it again until tomorrow."""
    clock.set_today("2026-09-25")
    router = ApiRouter()
    router.payloads[INVOICE_LETTER.marker]["items"][0]["recurrence"] = MONTHLY
    async with api_for(data_dir, router=router) as api:
        body = await api.upload(("rechnung.pdf", INVOICE_LETTER.pdf()))
        await api.read_all()
        doc_id = body["documents"][0]["id"]
        [before] = await _open_items(api, doc_id=doc_id)
        assert before["due_date"] == "2026-10-15"  # 15 Sep has passed: rolled to the next instalment

        patched = await api.client.patch(f"/api/documents/{doc_id}", json={"received_date": "2026-09-03"})
        assert patched.status_code == 200

        [after] = await _open_items(api, doc_id=doc_id)
        assert after["due_date"] == "2026-10-15"
        dashboard = (await api.client.get("/api/dashboard")).json()
        assert all(item["id"] != after["id"] for item in dashboard["attention"])  # not "overdue"


async def test_confirming_the_arrival_date_keeps_the_dates_confidence(data_dir: Path) -> None:
    """The pipeline accepts an amount that is written elsewhere in the letter
    (``plan._stated_in_document``) — the payment is "processed", high confidence. Confirming the
    arrival date re-grades it in ``dates._verified`` *without* that check, so "Why this date?" drops
    to medium confidence and says "The amount doesn't appear in the sentence … please check it" —
    for a fixed date the arrival date doesn't even change."""
    clock.set_today("2026-09-05")
    router = ApiRouter()
    router.payloads[INVOICE_LETTER.marker]["items"][0]["quote"] = "bis zum 15.09.2026"
    async with api_for(data_dir, router=router) as api:
        body = await api.upload(("rechnung.pdf", INVOICE_LETTER.pdf()))
        await api.read_all()
        doc_id = body["documents"][0]["id"]
        [before] = await _open_items(api, doc_id=doc_id)
        assert before["computation"]["confidence"] == "high"

        await api.client.patch(f"/api/documents/{doc_id}", json={"received_date": "2026-09-03"})

        [after] = await _open_items(api, doc_id=doc_id)
        assert after["due_date"] == before["due_date"]
        assert after["computation"]["confidence"] == "high"
        assert after["computation"]["warnings"] == before["computation"]["warnings"]


# --------------------------------------------------------------------------------------------------
# Payment reminders (Mahnung)
# --------------------------------------------------------------------------------------------------


async def test_deleting_a_payment_reminder_brings_back_the_invoice_payment(data_dir: Path) -> None:
    """``link_dunning`` marks the invoice's payment as superseded (``description = DUNNING_ITEM_NOTE``)
    and every view hides superseded payments. When the reminder letter is deleted (or turns out to be
    someone else's / a scam) the note stays, so the still-open invoice payment vanishes from Today and
    from the Ideas — an obligation dropped without the person ever closing it (SPEC §21)."""
    clock.set_today("2026-09-10")
    async with api_for(data_dir) as api:
        await api.upload(("rechnung.pdf", INVOICE_LETTER.pdf()))
        await api.read_all()
        reminder = await api.upload(("mahnung.pdf", DUNNING_LETTER.pdf()))
        await api.read_all()

        deleted = await api.client.delete(f"/api/documents/{reminder['documents'][0]['id']}")
        assert deleted.status_code == 200

        dashboard = (await api.client.get("/api/dashboard")).json()
        shown = [item["title"] for item in dashboard["attention"] + dashboard["upcoming"]]
        assert "Pay the phone bill" in shown  # due 15 Sep, still open


_REMINDER_OTHER_IBAN = Letter(
    marker="Zahlungserinnerung (anderes Konto)",  # own PDF cache entry; routed by "Zahlungserinnerung"
    pages=(
        (
            "Muster Telecom · Funkweg 5 · 12345 Musterstadt",
            "SPECIMEN",
            "Musterstadt, 20.09.2026",
            "Zahlungserinnerung zu Rechnung Nr. R-2026-0815",
            "Kundennummer: K-778899",
            "Bitte zahlen Sie jetzt 54,99 EUR bis zum 30.09.2026.",
            f"IBAN: {SCAM_IBAN}",
        ),
    ),
    payload={},
)


async def test_a_suspicious_reminder_does_not_hide_the_invoice_payment(data_dir: Path) -> None:
    """A "reminder" asking for payment to a different IBAN is flagged as a possible scam, so its own
    payment is (rightly) not offered — but ``link_dunning`` has already marked the genuine invoice's
    payment as superseded, so Today shows *no* payment at all, only the scam warning."""
    clock.set_today("2026-09-10")
    router = ApiRouter()
    router.payloads[DUNNING_LETTER.marker]["payment"]["iban"] = SCAM_IBAN
    async with api_for(data_dir, router=router) as api:
        await api.upload(("rechnung.pdf", INVOICE_LETTER.pdf()))
        await api.read_all()
        await api.upload(("mahnung.pdf", _REMINDER_OTHER_IBAN.pdf()))
        await api.read_all()

        dashboard = (await api.client.get("/api/dashboard")).json()
        assert "scam_warning" in [idea["rule_id"] for idea in dashboard["suggestions"]]
        shown = [item["title"] for item in dashboard["attention"] + dashboard["upcoming"]]
        assert "Pay the phone bill" in shown


async def test_a_reminder_read_before_its_invoice_still_supersedes_it(data_dir: Path) -> None:
    """``link_dunning`` only looks for the invoice when the *reminder* is linked. Drop both letters
    at once with the reminder first (or scan the reminder first) and the invoice's payment is never
    flagged: Today shows "Pay the phone bill" (€49.99) *and* "Pay the reminder" (€54.99) — the
    double payment the "pay once, not twice" logic exists to prevent."""
    clock.set_today("2026-09-10")
    async with api_for(data_dir) as api:
        await api.upload(("mahnung.pdf", DUNNING_LETTER.pdf()))
        await api.read_all()
        await api.upload(("rechnung.pdf", INVOICE_LETTER.pdf()))
        await api.read_all()

        dashboard = (await api.client.get("/api/dashboard")).json()
        shown = [item["title"] for item in dashboard["attention"] + dashboard["upcoming"]]
        assert shown == ["Pay the reminder"]  # what reading the invoice first gives


# --------------------------------------------------------------------------------------------------
# Reading a letter again
# --------------------------------------------------------------------------------------------------


async def test_read_again_keeps_the_letter_date_the_person_corrected(data_dir: Path) -> None:
    """The model misread the letter date (18 instead of 15 Sep); the person corrects it and the
    objection deadline is recomputed to 21 Oct. "Read again" (for any reason) runs ``write_plan``,
    which overwrites ``doc_date`` (and title, kind …) with the model's reading and recomputes the
    deadline from it: 22 Oct — a day after the real deadline."""
    clock.set_today("2026-09-25")
    router = ApiRouter()
    router.payloads[TAX_LETTER.marker]["document_date"] = "2026-09-18"
    async with api_for(data_dir, router=router) as api:
        body = await api.upload(("steuer.pdf", TAX_LETTER.pdf()))
        await api.read_all()
        doc_id = body["documents"][0]["id"]
        corrected = await api.client.patch(f"/api/documents/{doc_id}", json={"doc_date": "2026-09-15"})
        assert corrected.status_code == 200
        [deadline] = await _open_items(api, doc_id=doc_id, kind="deadline")
        assert deadline["due_date"] == "2026-10-21"

        assert (await api.client.post(f"/api/documents/{doc_id}/reprocess")).status_code == 202
        await api.read_all()

        document = (await api.client.get(f"/api/documents/{doc_id}")).json()["document"]
        assert document["doc_date"] == "2026-09-15"
        [deadline] = await _open_items(api, doc_id=doc_id, kind="deadline")
        assert deadline["due_date"] == "2026-10-21"


async def test_read_again_keeps_a_payment_marked_as_paid(data_dir: Path) -> None:
    """Status clicks (done, dismissed) don't count as ``user_modified``. When the re-read quotes the
    sentence slightly differently, the slot key changes, ``delete_stale_extracted_items`` deletes the
    paid item and a fresh *open* payment appears on Today again."""
    clock.set_today("2026-09-25")
    router = ApiRouter()
    async with api_for(data_dir, router=router) as api:
        body = await api.upload(("steuer.pdf", TAX_LETTER.pdf()))
        await api.read_all()
        doc_id = body["documents"][0]["id"]
        [payment] = await _open_items(api, doc_id=doc_id, kind="payment")
        assert (
            await api.client.patch(f"/api/items/{payment['id']}", json={"status": "done"})
        ).status_code == 200

        router.payloads[TAX_LETTER.marker]["items"][1]["quote"] = (
            "die festgesetzte Einkommensteuer beträgt 1.234,56 EUR. "
            "Bitte zahlen Sie den Betrag von 1.234,56 EUR bis zum 15.10.2026."
        )
        await api.client.post(f"/api/documents/{doc_id}/reprocess")
        await api.read_all()

        assert await _open_items(api, doc_id=doc_id, kind="payment") == []


# --------------------------------------------------------------------------------------------------
# Deleting letters
# --------------------------------------------------------------------------------------------------


async def test_a_letter_deleted_before_it_was_read_is_never_sent_to_claude(data_dir: Path) -> None:
    """Deleting a letter that is still waiting to be read (queued, or held back by a usage-limit
    pause) only trashes it; its job stays queued and the worker later sends the letter to the model
    anyway and files its to-dos. "Delete means delete" (docs/privacy.md)."""
    clock.set_today("2026-09-25")
    async with api_for(data_dir) as api:
        body = await api.upload(("steuer.pdf", TAX_LETTER.pdf()))
        doc_id = body["documents"][0]["id"]
        assert (await api.client.delete(f"/api/documents/{doc_id}")).status_code == 200

        await api.read_all()

        assert [call.purpose for call in api.backend.calls if doc_id in call.doc_ids] == []


# --------------------------------------------------------------------------------------------------
# "Please check"
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("fix", ["change_date", "not_a_real_todo", "delete"])
async def test_resolving_the_flagged_date_clears_please_check(data_dir: Path, fix: str) -> None:
    """The "Please check" card offers "Change date" and "Not a real to-do" next to "Yes, that's
    right", but only ``POST /items/{id}/confirm`` calls ``refresh_review_status``. After the other
    fixes the letter stays "Please check" in the inbox and the "Please check" Idea never goes away,
    although nothing is left to check."""
    clock.set_today("2026-09-05")
    router = ApiRouter()
    router.payloads[INVOICE_LETTER.marker]["items"][0]["quote"] = "Zahlbar bis zum 15.09.2026 ohne Abzug."
    async with api_for(data_dir, router=router) as api:
        body = await api.upload(("rechnung.pdf", INVOICE_LETTER.pdf()))
        await api.read_all()
        doc_id = body["documents"][0]["id"]
        detail = (await api.client.get(f"/api/documents/{doc_id}")).json()
        assert detail["document"]["status"] == "needs_review"
        item_id = detail["items"][0]["id"]

        if fix == "change_date":
            response = await api.client.patch(f"/api/items/{item_id}", json={"due_date": "2026-09-15"})
        elif fix == "not_a_real_todo":
            response = await api.client.patch(f"/api/items/{item_id}", json={"status": "dismissed"})
        else:
            response = await api.client.delete(f"/api/items/{item_id}")
        assert response.status_code in (200, 204)

        document = (await api.client.get(f"/api/documents/{doc_id}")).json()["document"]
        assert document["status"] == "processed"
        ideas = (await api.client.get("/api/suggestions", params={"status": "new"})).json()
        assert not [idea for idea in ideas if idea["rule_id"] == "please_check"]


# --------------------------------------------------------------------------------------------------
# Changing the holiday region
# --------------------------------------------------------------------------------------------------

_NET_14_QUOTE = "Bitte überweisen Sie 49,99 EUR innerhalb von 14 Tagen nach Rechnungsdatum."
_DECEMBER_INVOICE = Letter(
    marker="Ihre Rechnung Nr. R-2026-0999",  # own PDF cache entry; routed by "Ihre Rechnung"
    pages=(
        (
            "Muster Telecom GmbH · Funkweg 5 · 12345 Musterstadt",
            "SPECIMEN",
            "Musterstadt, 23.12.2026",
            "Ihre Rechnung Nr. R-2026-0999",
            "Kundennummer: K-778899",
            _NET_14_QUOTE,
        ),
    ),
    payload={},
)


async def test_changing_the_region_recomputes_payment_deadlines(data_dir: Path) -> None:
    """A payment "within 14 days of the invoice date" (23 Dec → Wed 6 Jan 2027) is moved to 7 Jan
    for someone in Bavaria (Epiphany). When the person corrects their Land to NRW in Settings,
    ``PUT /profile`` promises "dates are recomputed on read with the new region" — true for
    contracts only: the stored item keeps 7 Jan (and "Bayern" in "Why this date?"), a day late."""
    clock.set_today("2026-12-24")
    router = ApiRouter()
    payload = router.payloads[INVOICE_LETTER.marker]
    payload["document_date"] = "2026-12-23"
    payload["items"][0]["date"] = {
        "type": "relative",
        "amount": 14,
        "unit": "days",
        "anchor": "document_date",
        "nature": "payment",
        "text": "innerhalb von 14 Tagen nach Rechnungsdatum",
    }
    payload["items"][0]["quote"] = _NET_14_QUOTE
    async with api_for(data_dir, router=router) as api:
        assert (
            await api.client.post("/api/onboarding", json={"profile": {"region": "BY"}})
        ).status_code == 200
        body = await api.upload(("rechnung.pdf", _DECEMBER_INVOICE.pdf()))
        await api.read_all()
        doc_id = body["documents"][0]["id"]
        [payment] = await _open_items(api, doc_id=doc_id)
        assert payment["due_date"] == "2027-01-07"

        assert (await api.client.put("/api/profile", json={"region": "NW"})).status_code == 200

        [payment] = await _open_items(api, doc_id=doc_id)
        assert payment["due_date"] == "2027-01-06"


# --------------------------------------------------------------------------------------------------
# Time zones: the person's today vs the computer's today
# --------------------------------------------------------------------------------------------------

# 22:30 UTC on Sat 24 Oct 2026 is 00:30 on Sun 25 Oct in Berlin (the night the clocks go back).
_INSTANT = datetime(2026, 10, 24, 22, 30, tzinfo=UTC)


class _SystemDate(date):
    """``date.today()`` of a computer whose clock runs in UTC (Docker, servers, some WSL setups)."""

    @classmethod
    def today(cls) -> date:  # type: ignore[override]
        return _INSTANT.date()


class _SystemDatetime(datetime):
    @classmethod
    def now(cls, tz: Any = None) -> datetime:  # type: ignore[override]
        return _INSTANT.astimezone(tz) if tz is not None else _INSTANT.replace(tzinfo=None)


@pytest.fixture
def utc_computer_berlin_person(monkeypatch: pytest.MonkeyPatch) -> None:
    """The computer's date is 24 Oct (UTC) while the person (profile time zone Europe/Berlin) is
    already on 25 Oct."""
    clock.set_today(None)
    monkeypatch.delenv("ORDNUNG_TODAY", raising=False)
    monkeypatch.setattr("ordnung.clock.date", _SystemDate)
    monkeypatch.setattr("ordnung.tick.datetime", _SystemDatetime)
    assert not os.environ.get("ORDNUNG_TODAY")


@pytest.mark.usefixtures("utc_computer_berlin_person")
async def test_marking_a_letter_sent_today_works_after_midnight_in_berlin(data_dir: Path) -> None:
    """The "Mark as sent" dialog defaults to the app's today (``/api/health`` → profile time zone),
    but ``compose.mark_sent`` rejects any day after ``clock.today()`` (the computer's local date):
    between midnight and 02:00 in Berlin on a UTC machine the default date fails with
    "The sending date can't be in the future"."""
    async with api_for(data_dir) as api:
        today = (await api.client.get("/api/health")).json()["today"]
        assert today == "2026-10-25"
        now = "2026-10-24T22:30:00Z"
        draft = api.ctx.store.add_draft(
            id="drf_audit0000001",
            kind="general_reply",
            subject="Ihre Rechnung",
            body="Guten Tag,\n\nDanke.",
            created_at=now,
            updated_at=now,
        )
        response = await api.client.post(
            f"/api/drafts/{draft.id}/sent", json={"channel": "letter", "date": today}
        )
        assert response.status_code == 200, response.text


@pytest.mark.usefixtures("utc_computer_berlin_person")
async def test_a_new_letter_is_dated_with_the_persons_today(data_dir: Path) -> None:
    """``compose`` writes ``place_date`` from ``clock.today()``: a letter drafted at 00:30 in Berlin
    on a UTC machine is dated the day before."""
    async with api_for(data_dir) as api:
        store = api.ctx.store
        store.save_profile(
            store.get_profile().model_copy(
                update={"name": "Sam Rivera", "address": "Hauptstraße 1, 12345 Musterstadt"}
            )
        )
        party = store.add_party(
            id="pty_audit0000001", name="Muster Telecom GmbH", address="Funkweg 5, 12345 Musterstadt"
        )
        response = await api.client.post("/api/drafts", json={"kind": "general_reply", "party_id": party.id})
        assert response.status_code == 201, response.text
        assert response.json()["place_date"] == "Musterstadt, 25.10.2026"
