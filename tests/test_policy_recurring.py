"""Verification of the recurring-obligations policy (ordnung.recurrence, points 1-7) after the redesign.

Each test is a realistic history through the Store/API that the written policy decides, found to
break a policy point (or to be a user-facing bug) by verifying the redesign; each pins the fix.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from fixtures_llm import APPOINTMENT_LETTER, INVOICE_LETTER, TAX_LETTER, TAX_PAYMENT_QUOTE
from ordnung import clock
from ordnung.db.store import Store
from ordnung.ingest.verify import UNVERIFIED_NOTE
from ordnung.llm.runtime import LLMService
from ordnung.models import DateSpec, Recurrence
from ordnung.recurrence import rolled
from ordnung.rules import RuleContext
from ordnung.tick import DailyTick
from test_api_support import Api, ApiRouter, api_for

MONTHLY = {"interval": 1, "unit": "months"}
BUFFER = 3


@pytest.fixture(autouse=True)
def unpinned_after_test() -> Iterator[None]:
    yield
    clock.set_today(None)


async def _patch(api: Api, item_id: str, **patch: Any) -> dict[str, Any]:
    response = await api.client.patch(f"/api/items/{item_id}", json=patch)
    assert response.status_code == 200, response.text
    return dict(response.json())


async def _payments(api: Api, doc_id: str) -> list[dict[str, Any]]:
    response = await api.client.get("/api/items", params={"doc_id": doc_id, "kind": "payment"})
    assert response.status_code == 200, response.text
    return list(response.json())


@dataclass
class _TickContext:
    store: Store
    llm: LLMService | None = None
    bus: None = None


async def _tick(api: Api, day: str) -> None:
    """The day's tick, as the app runs it when the date changes (without the model)."""
    clock.set_today(day)
    assert (await DailyTick(_TickContext(api.ctx.store)).check()).day_changed


async def _item(api: Api, item_id: str) -> dict[str, Any]:
    response = await api.client.get(f"/api/items/{item_id}")
    assert response.status_code == 200, response.text
    return dict(response.json())


# --------------------------------------------------------------------------------------------------
# user-facing: "Undo" after "Mark as paid"
# --------------------------------------------------------------------------------------------------


async def test_undo_after_mark_as_paid_brings_the_occurrence_back(data_dir: Path) -> None:
    """Today's "Pay" panel and the letter's to-do list mark a to-do paid with ``{"status": "done"}`` and
    offer "Undo", which sends ``{"status": "open"}`` (web/src/features/today/TopThree.tsx,
    web/src/features/document/actions.ts). A recurring rent paid by mistake and undone must show the
    October rent again, not November's."""
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
        rent = created.json()
        paid = await _patch(api, rent["id"], status="done")
        assert (paid["status"], paid["due_date"]) == ("open", "2026-11-01")

        undone = await _patch(api, rent["id"], status="open")  # the toast's "Undo"
        assert (undone["status"], undone["due_date"]) == ("open", "2026-10-01")


# --------------------------------------------------------------------------------------------------
# point 6: reading the letter again never moves it backwards while the schedule is the same
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("reread", "quote"),
    [
        # the same fixed date read with an anchor that means nothing for a fixed date (as the demo's
        # Deutschlandticket reading has it), same quote
        ({"anchor": "explicit_date", "anchor_date": "2026-10-15"}, None),
        # the same fixed date with shift_rule "none" instead of "auto" (the same date for a payment)
        ({"shift_rule": "none"}, None),
        # the anchor again, and the model quotes the sentence a little shorter (carry_over's case)
        (
            {"anchor": "explicit_date", "anchor_date": "2026-10-15"},
            "Bitte zahlen Sie den Betrag von 1.234,56 EUR",
        ),
    ],
)
async def test_a_paid_ahead_payment_stays_ahead_when_the_date_is_read_with_other_details(
    data_dir: Path, reread: dict[str, Any], quote: str | None
) -> None:
    """A monthly payment on the 15th, first occurrence 15 Oct 2026 (unchanged in every reading). On
    20 Nov the person pays December early, so it shows 15 Jan. "Read again" returns the same rule and
    first occurrence, with a detail of the DateSpec that does not change the date: the payment must
    stay on 15 Jan (point 6), not come back as the paid December."""
    clock.set_today("2026-11-20")
    router = ApiRouter()
    payment = next(item for item in router.payloads[TAX_LETTER.marker]["items"] if item["kind"] == "payment")
    payment["recurrence"] = MONTHLY
    async with api_for(data_dir, router=router) as api:
        doc_id = (await api.upload(("steuer.pdf", TAX_LETTER.pdf())))["documents"][0]["id"]
        await api.read_all()
        [item] = await _payments(api, doc_id)
        assert item["due_date"] == "2026-12-15"
        paid = await _patch(api, item["id"], status="done")
        assert (paid["status"], paid["due_date"]) == ("open", "2027-01-15")

        payment["date"] |= reread
        if quote is not None:
            payment["quote"] = quote
        assert (await api.client.post(f"/api/documents/{doc_id}/reprocess")).status_code == 202
        await api.read_all()
        [after] = await _payments(api, doc_id)
        assert after["date_spec"]["date"] == "2026-10-15"  # the same first occurrence
        assert after["recurrence"] == MONTHLY  # the same rule
        assert (after["status"], after["due_date"]) == ("open", "2027-01-15")


# --------------------------------------------------------------------------------------------------
# point 4: marking a recurring item done does not close it
# --------------------------------------------------------------------------------------------------


async def test_ticking_off_an_undated_recurring_rent_does_not_end_the_series(data_dir: Path) -> None:
    """The most common rent clause, "spätestens bis zum dritten Werktag eines jeden Monats", has no
    date the engine can compute: the model files it as a monthly payment with a DateSpec of type
    "none" (as in the demo's lease). Ticking October's rent off must not close the monthly rent."""
    clock.set_today("2026-10-02")
    async with api_for(data_dir) as api:
        rent = api.ctx.store.add_item(
            kind="payment",
            title="Monthly rent payment (Gesamtmiete)",
            date_spec=DateSpec(
                type="none", nature="payment", text="spätestens bis zum dritten Werktag eines jeden Monats"
            ),
            recurrence=Recurrence(interval=1, unit="months"),
            amount=870.0,
            direction="out",
            due_date_source="none",
            filed_on="2026-09-20",
        )
        after = await _patch(api, rent.id, status="done")
        assert after["status"] == "open"


# --------------------------------------------------------------------------------------------------
# point 5: every occurrence's receipt comes from the rules engine
# --------------------------------------------------------------------------------------------------


def test_one_occurrence_on_a_regional_holiday_does_not_lower_every_later_one(store: Store) -> None:
    """A monthly payment on the 6th, "or the next business day" (shift_rule next_business_day); the
    person's Land is unknown. 6 Jan 2027 is a holiday in some Länder only, so the engine gives that
    occurrence medium confidence with a warning saying why. February's occurrence has no such issue:
    its receipt must be the engine's (high, no warning), not stuck at medium without a reason."""
    spec = DateSpec(type="fixed", date="2026-10-06", nature="payment", shift_rule="next_business_day")
    item = store.add_item(
        kind="payment",
        title="Monthly instalment",
        due_date="2026-12-07",
        date_spec=spec,
        recurrence=Recurrence(interval=1, unit="months"),
        amount=120.0,
        direction="out",
        due_date_source="fixed",
    )
    january = rolled(item, RuleContext(today=date(2026, 12, 8)), postal_buffer_days=BUFFER)
    assert january is not None and january.due_date == "2027-01-06"
    assert january.computation is not None and january.computation.confidence == "medium"
    february = rolled(january, RuleContext(today=date(2027, 1, 7)), postal_buffer_days=BUFFER)
    assert february is not None and february.due_date == "2027-02-08"
    assert february.computation is not None and not february.computation.warnings
    assert february.computation.confidence == "high"


# --------------------------------------------------------------------------------------------------
# point 5: a kept later occurrence still gets the engine's dates in the current context
# --------------------------------------------------------------------------------------------------


async def test_a_paid_ahead_occurrence_gets_the_new_regions_send_by_date(data_dir: Path) -> None:
    """A monthly phone bill due on the 7th (first occurrence Sat 7 Nov 2026), owed to a private
    company, so the payer's holidays count. The person lives in NRW; on 2 Dec they pay December early,
    so it shows Thu 7 Jan 2027, send by Wed 6 Jan. Then they move to Bavaria and change their region:
    6 Jan is Epiphany there, so the engine's send-by date for 7 Jan is Tue 5 Jan. Ordnung once kept
    telling them to transfer on 6 Jan, a holiday in Bavaria: recomputing the dates skipped the
    occurrence kept (point 6) instead of dating it in the new region (point 5)."""
    clock.set_today("2026-12-02")
    router = ApiRouter()
    payment = router.payloads[INVOICE_LETTER.marker]["items"][0]
    payment |= {
        "recurrence": MONTHLY,
        "date": {"type": "fixed", "date": "2026-11-07", "nature": "payment", "text": "jeweils zum 7."},
    }
    async with api_for(data_dir, router=router) as api:
        onboarded = await api.client.put("/api/profile", json={"region": "NW", "onboarded": True})
        assert onboarded.status_code == 200, onboarded.text
        doc_id = (await api.upload(("rechnung.pdf", INVOICE_LETTER.pdf())))["documents"][0]["id"]
        await api.read_all()
        [item] = await _payments(api, doc_id)
        assert item["due_date"] == "2026-12-07"
        paid = await _patch(api, item["id"], status="done")
        assert (paid["due_date"], paid["send_by"]) == ("2027-01-07", "2027-01-06")
        assert paid["computation"]["holiday_calendar"] == "Nordrhein-Westfalen"

        moved = await api.client.put("/api/profile", json={"region": "BY"})
        assert moved.status_code == 200, moved.text
        [after] = await _payments(api, doc_id)
        assert after["due_date"] == "2027-01-07"  # the paid-ahead occurrence stays (point 6)
        assert after["computation"]["holiday_calendar"] == "Bayern"
        assert after["send_by"] == "2027-01-05"  # compute_due for 7 Jan 2027 with Bavaria's holidays

        back = await api.client.put("/api/profile", json={"region": "NW"})
        assert back.status_code == 200, back.text
        [again] = await _payments(api, doc_id)
        assert (again["due_date"], again["send_by"]) == ("2027-01-07", "2027-01-06")


# --------------------------------------------------------------------------------------------------
# point 5: an occurrence's receipt is graded by the letter's current reading
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("paid_ahead", [False, True])
async def test_reading_the_letter_again_regrades_the_recurring_payments_receipt(
    data_dir: Path, paid_ahead: bool
) -> None:
    """A monthly payment on the 15th (from 15 Oct). The first reading quotes a sentence that is not in
    the letter, so the letter asks "Please check" and the receipt says "We couldn't find this
    sentence". The person clicks "Read again"; the model now quotes the letter's own sentence: the
    letter no longer needs checking, and the payment's receipt must not keep that warning (nor pass
    it on to the occurrences after it)."""
    clock.set_today("2026-11-20")
    router = ApiRouter()
    payment = next(item for item in router.payloads[TAX_LETTER.marker]["items"] if item["kind"] == "payment")
    payment["recurrence"] = MONTHLY
    payment["quote"] = "Bitte überweisen Sie monatlich 1.234,56 EUR an die Finanzkasse."  # not in the letter
    async with api_for(data_dir, router=router) as api:
        doc_id = (await api.upload(("steuer.pdf", TAX_LETTER.pdf())))["documents"][0]["id"]
        await api.read_all()
        [item] = await _payments(api, doc_id)
        assert item["grounding"] == "unverified"
        assert UNVERIFIED_NOTE in item["computation"]["warnings"]
        if paid_ahead:
            item = await _patch(api, item["id"], status="done")
            assert item["due_date"] == "2027-01-15"

        payment["quote"] = TAX_PAYMENT_QUOTE  # the letter's own sentence
        assert (await api.client.post(f"/api/documents/{doc_id}/reprocess")).status_code == 202
        await api.read_all()
        [after] = await _payments(api, doc_id)
        assert (after["id"], after["due_date"]) == (item["id"], item["due_date"])  # never back (point 6)
        assert after["grounding"] == "verified"
        assert UNVERIFIED_NOTE not in after["computation"]["warnings"]

        following = await _patch(api, after["id"], status="done")
        assert UNVERIFIED_NOTE not in following["computation"]["warnings"]


# --------------------------------------------------------------------------------------------------
# points 2 and 7: the schedule of a to-do added by hand stays where it starts
# --------------------------------------------------------------------------------------------------


async def test_sending_the_unchanged_rule_again_keeps_the_schedule(data_dir: Path) -> None:
    """Rent on the 1st, added by hand; November's is moved to the 3rd by hand. A client that saves the
    to-do with its rule unchanged ({"recurrence": every month}, as ``ItemPatch`` allows) must leave
    the schedule on the 1st: once the 3rd has passed, December's rent is on the 1st (point 7)."""
    clock.set_today("2026-10-20")
    async with api_for(data_dir) as api:
        created = await api.client.post(
            "/api/items",
            json={
                "kind": "payment",
                "title": "Rent",
                "due_date": "2026-11-01",
                "amount": 650.0,
                "recurrence": MONTHLY,
            },
        )
        rent = created.json()
        await _patch(api, rent["id"], due_date="2026-11-03")
        saved = await _patch(api, rent["id"], recurrence=MONTHLY)  # the same rule
        assert saved["date_spec"]["date"] == "2026-11-01"
        paid = await _patch(api, rent["id"], status="done")
        assert paid["due_date"] == "2026-12-01"


# --------------------------------------------------------------------------------------------------
# points 2, 3 and 5: a schedule whose first occurrence is not a fixed DateSpec
# --------------------------------------------------------------------------------------------------


async def test_a_month_end_rent_dated_by_hand_keeps_its_day_of_the_month(data_dir: Path) -> None:
    """The lease says the rent is due "jeweils zum Monatsende": no date the engine can compute, so the
    model files a monthly payment with a DateSpec of type "none" (as the demo's rent). The person
    gives October's rent its date by hand ("Change date" → 31 Oct). The schedule is (31 Oct, every
    month): November's rent is due on the 30th, December's on the 31st, and the receipt says the
    rent repeats since 31 Oct. Ordnung counted each month from the date before it, so December's rent
    showed on the 30th, February's on the 28th, then March's on the 28th, "since Sun 28 Feb 2027"
    (the bug the audit fixed for to-dos added by hand, back for a letter's undated to-do)."""
    clock.set_today("2026-10-20")
    async with api_for(data_dir) as api:
        rent = api.ctx.store.add_item(
            kind="payment",
            title="Monthly rent (Gesamtmiete)",
            date_spec=DateSpec(type="none", nature="payment", text="jeweils zum Monatsende"),
            recurrence=Recurrence(interval=1, unit="months"),
            amount=870.0,
            direction="out",
            due_date_source="none",
            filed_on="2026-09-20",
        )
        await _patch(api, rent.id, due_date="2026-10-31")
        await _tick(api, "2026-11-01")
        assert (await _item(api, rent.id))["due_date"] == "2026-11-30"
        await _tick(api, "2026-12-01")
        december = await _item(api, rent.id)
        assert december["due_date"] == "2026-12-31"
        assert december["computation"]["summary"] == (
            "Repeats every month since Sat 31 Oct 2026; next on Thu 31 Dec 2026."
        )


async def test_an_instalment_plan_returns_to_its_schedule_after_a_date_set_by_hand(data_dir: Path) -> None:
    """An instalment plan: "Die erste Rate ist einen Monat nach dem Datum dieses Schreibens fällig, die
    weiteren Raten jeweils monatlich" (letter of 15 Sep: first instalment Thu 15 Oct, then the 15th of
    every month). The person moves October's instalment to the 20th by hand. Once the 20th has passed
    the letter's schedule applies again (point 7): November's instalment is due on the 15th, and the
    receipt says the plan repeats since 15 Oct. Ordnung restarted the schedule at the date set by hand
    (20 Nov, 20 Dec, …, "since Tue 20 Oct 2026")."""
    clock.set_today("2026-09-25")
    router = ApiRouter()
    payment = next(item for item in router.payloads[TAX_LETTER.marker]["items"] if item["kind"] == "payment")
    payment["recurrence"] = MONTHLY
    payment["date"] = {
        "type": "relative",
        "amount": 1,
        "unit": "months",
        "anchor": "document_date",
        "nature": "payment",
        "text": "einen Monat nach dem Datum dieses Schreibens, die weiteren Raten jeweils monatlich",
    }
    async with api_for(data_dir, router=router) as api:
        doc_id = (await api.upload(("raten.pdf", TAX_LETTER.pdf())))["documents"][0]["id"]
        await api.read_all()
        [instalment] = await _payments(api, doc_id)
        assert instalment["due_date"] == "2026-10-15"
        await _patch(api, instalment["id"], due_date="2026-10-20")

        await _tick(api, "2026-10-21")
        after = await _item(api, instalment["id"])
        assert after["due_date"] == "2026-11-15"
        assert after["computation"]["summary"].startswith("Repeats every month since Thu 15 Oct 2026;")


# --------------------------------------------------------------------------------------------------
# point 6: the same schedule, written as another rule
# --------------------------------------------------------------------------------------------------


async def test_a_yearly_payment_read_again_as_every_12_months_stays_paid_ahead(data_dir: Path) -> None:
    """A yearly payment on 15 Oct (first 15 Oct 2026, "jährlich"). The person pays it on 25 Sep, so it
    shows 15 Oct 2027. "Read again": the model now writes the rule as every 12 months instead of every
    year, the same dates for every occurrence. The schedule (its first occurrence and its dates) is
    unchanged, so the payment must stay on 15 Oct 2027 (point 6); Ordnung asked for it again on
    15 Oct 2026."""
    clock.set_today("2026-09-25")
    router = ApiRouter()
    payment = next(item for item in router.payloads[TAX_LETTER.marker]["items"] if item["kind"] == "payment")
    payment["recurrence"] = {"interval": 1, "unit": "years"}
    async with api_for(data_dir, router=router) as api:
        doc_id = (await api.upload(("jahresbeitrag.pdf", TAX_LETTER.pdf())))["documents"][0]["id"]
        await api.read_all()
        [item] = await _payments(api, doc_id)
        paid = await _patch(api, item["id"], status="done")
        assert (paid["status"], paid["due_date"]) == ("open", "2027-10-15")

        payment["recurrence"] = {"interval": 12, "unit": "months"}
        assert (await api.client.post(f"/api/documents/{doc_id}/reprocess")).status_code == 202
        await api.read_all()
        [after] = await _payments(api, doc_id)
        assert after["date_spec"]["date"] == "2026-10-15"  # the same first occurrence
        assert (after["status"], after["due_date"]) == ("open", "2027-10-15")


# --------------------------------------------------------------------------------------------------
# user-facing: a date moved earlier by hand stands for the occurrence it replaced
# --------------------------------------------------------------------------------------------------


async def test_an_appointment_moved_earlier_by_hand_does_not_come_back_on_its_old_day(data_dir: Path) -> None:
    """A weekly appointment, Mondays 10:30 from 12 Oct. The practice moves next Monday's (19 Oct) to
    Friday 16 Oct, and the person changes its date. After Friday the next appointment is Monday
    26 Oct; Ordnung showed Monday 19 Oct, the appointment that had been moved to the 16th."""
    clock.set_today("2026-10-13")
    router = ApiRouter()
    router.payloads[APPOINTMENT_LETTER.marker]["items"][0]["recurrence"] = {"interval": 1, "unit": "weeks"}
    async with api_for(data_dir, router=router) as api:
        doc_id = (await api.upload(("termine.pdf", APPOINTMENT_LETTER.pdf())))["documents"][0]["id"]
        await api.read_all()
        [series] = (await api.client.get("/api/items", params={"doc_id": doc_id})).json()
        assert series["due_date"] == "2026-10-19"
        await _patch(api, series["id"], due_date="2026-10-16")

        await _tick(api, "2026-10-17")
        assert (await _item(api, series["id"]))["due_date"] == "2026-10-26"


async def test_a_payment_moved_earlier_and_marked_paid_is_not_asked_for_again(data_dir: Path) -> None:
    """A monthly payment on the 15th. The person pays November's early, on 10 Nov: they change its
    date to the 10th and mark it paid. The next payment is December's; Ordnung asked for November's
    again ("Paid … (Tue 10 Nov 2026) — next on Sun 15 Nov 2026"), inviting a second transfer."""
    clock.set_today("2026-11-10")
    router = ApiRouter()
    payment = next(item for item in router.payloads[TAX_LETTER.marker]["items"] if item["kind"] == "payment")
    payment["recurrence"] = MONTHLY
    async with api_for(data_dir, router=router) as api:
        doc_id = (await api.upload(("steuer.pdf", TAX_LETTER.pdf())))["documents"][0]["id"]
        await api.read_all()
        [item] = await _payments(api, doc_id)
        assert item["due_date"] == "2026-11-15"
        await _patch(api, item["id"], due_date="2026-11-10")
        paid = await _patch(api, item["id"], status="done")
        assert (paid["status"], paid["due_date"]) == ("open", "2026-12-15")


# --------------------------------------------------------------------------------------------------
# point 6: reading the letter again to correct a misread amount
# --------------------------------------------------------------------------------------------------


async def test_reading_the_letter_again_to_fix_the_amount_keeps_the_payment_paid_ahead(
    data_dir: Path,
) -> None:
    """A monthly payment on the 15th (from 15 Oct). The first reading got the amount wrong (1,243.56
    instead of 1,234.56) and quoted a sentence that isn't in the letter, so the letter asks "Please
    check". On 20 Nov the person pays December early anyway: it shows 15 Jan. Then they click "Read
    again" to fix the amount; the model now reads 1,234.56 and quotes the letter's own sentence. The
    schedule is the same, so the payment keeps 15 Jan (point 6); Ordnung deleted it and filed a new
    one on 15 Dec, asking for the paid December again."""
    clock.set_today("2026-11-20")
    router = ApiRouter()
    payment = next(item for item in router.payloads[TAX_LETTER.marker]["items"] if item["kind"] == "payment")
    payment |= {
        "recurrence": MONTHLY,
        "amount": 1243.56,
        "quote": "Bitte zahlen Sie monatlich 1.243,56 EUR bis zum 15.10.2026.",
    }
    async with api_for(data_dir, router=router) as api:
        doc_id = (await api.upload(("steuer.pdf", TAX_LETTER.pdf())))["documents"][0]["id"]
        await api.read_all()
        [item] = await _payments(api, doc_id)
        assert item["grounding"] == "unverified"
        paid = await _patch(api, item["id"], status="done")
        assert (paid["status"], paid["due_date"]) == ("open", "2027-01-15")

        payment |= {"amount": 1234.56, "quote": TAX_PAYMENT_QUOTE}
        assert (await api.client.post(f"/api/documents/{doc_id}/reprocess")).status_code == 202
        await api.read_all()
        [after] = await _payments(api, doc_id)
        assert after["amount"] == 1234.56
        assert (after["status"], after["due_date"]) == ("open", "2027-01-15")
