"""A later rent replaces the rent it changes (ordnung.recurrence, point 9).

The demo's lease rent (€640, the 3rd working day) and its operating-cost statement's "New monthly total rent
€670" (fixed "ab dem 01.11.2026") are both monthly payments under the same rent contract: once October's
rent is paid, November holds one rent — the €670 on Wed 4 Nov, the lease's due day — never both. The other
tests read a SPECIMEN lease, statement and rent increase through the API: a § 558 increase not yet agreed
leaves the old rent running, a new rent's own working day stands, a dismissed new rent leaves the old one
running, reading again doubles nothing, and a rent that had already moved on when the new one came goes back
to its last month.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from fixtures_llm import Letter
from ordnung import clock
from ordnung.assistant.mcp_server import LedgerTools
from ordnung.recurrence import KEEPS_DAY_STEP, LAW_DEFAULT_WARNING
from ordnung.rules.advice import RENT_INCREASE_PAYMENT_WARNING
from ordnung.secretary.brief import build_agenda
from test_api_support import Api, ApiRouter, api_for

DEMO_DB = Path(__file__).resolve().parents[1] / "src" / "ordnung" / "demo" / "demo_db"
DEMO_RENT = "itm_b1b5643x7qy7"  # "Monthly rent", €640, the lease's 3rd working day
DEMO_NEW_RENT = "itm_9dvnqv1acvka"  # "New monthly total rent €670", "ab dem 01.11.2026"
MONTHLY = {"interval": 1, "unit": "months"}


@pytest.fixture(autouse=True)
def unpinned_after_test() -> Iterator[None]:
    yield
    clock.set_today(None)


async def _patch(api: Api, item_id: str, **patch: Any) -> dict[str, Any]:
    response = await api.client.patch(f"/api/items/{item_id}", json=patch)
    assert response.status_code == 200, response.text
    return dict(response.json())


async def _item(api: Api, item_id: str) -> dict[str, Any]:
    response = await api.client.get(f"/api/items/{item_id}")
    assert response.status_code == 200, response.text
    return dict(response.json())


async def _rents(api: Api, **params: str) -> list[dict[str, Any]]:
    """The open monthly payments of the ledger's rent contracts (``params`` narrow the list)."""
    response = await api.client.get("/api/items", params={"kind": "payment", "status": "open", **params})
    assert response.status_code == 200, response.text
    rent = {c["id"] for c in (await api.client.get("/api/contracts")).json() if c["category"] == "rent"}
    return [item for item in response.json() if item["recurrence"] and item["contract_id"] in rent]


def _log(api: Api, item_id: str) -> list[str]:
    return [entry.message for entry in api.ctx.store.list_activity(None) if entry.ref_id == item_id]


def _step_labels(item: dict[str, Any]) -> list[str]:
    return [step["label"] for step in item["computation"]["steps"]]


# --------------------------------------------------------------------------------------------------
# the demo: one rent in November
# --------------------------------------------------------------------------------------------------


async def test_the_demos_new_rent_replaces_the_lease_rent_from_november(tmp_path: Path) -> None:
    """Mark October's rent paid: the lease rent's series ends with it (closed, logged), and November holds
    one rent — €670 on Wed 4 Nov, the lease's 3rd working day, not Sun 1 Nov as the statement words it — in
    the list, on Today, in the Money totals, the agenda and Ask's money summary. Paid, it moves on to Thu 3
    Dec; "Undo" brings November back; set open again, the old rent is back at October."""
    clock.set_today("2026-09-28")
    data = tmp_path / "data"
    shutil.copytree(DEMO_DB, data)
    async with api_for(data, demo=True) as api:
        paid = await _patch(api, DEMO_RENT, status="done")
        # its last occurrence stays, and the series is closed there
        assert (paid["status"], paid["due_date"], paid["amount"]) == ("done", "2026-10-05", 640.0)
        assert (
            "Paid “Monthly rent” (Mon 5 Oct 2026) — replaced by “New monthly total rent €670” from Nov 2026"
            in _log(api, DEMO_RENT)
        )

        new = await _item(api, DEMO_NEW_RENT)
        assert (new["status"], new["due_date"], new["due_date_source"]) == ("open", "2026-11-04", "computed")
        receipt = new["computation"]
        assert receipt["summary"] == "Repeats every month on the 3rd working day; next on Wed 4 Nov 2026."
        assert f"The lease's due day{KEEPS_DAY_STEP}Sun 1 Nov 2026 as the start" in _step_labels(new)
        assert "bgb_556b" in receipt["rule_ids"]
        # the lease names its working day (the demo's reading gives 3), so no warning that it is the law's,
        # and the Sunday is no longer the due day
        assert not any("not a working day" in warning for warning in receipt["warnings"])
        assert LAW_DEFAULT_WARNING not in receipt["warnings"]
        # its send-by follows how the statement says it is paid: the demo's reading ("Adjust your standing
        # order … unless you use direct debit") names a direct debit, which the sender collects
        # (ordnung.payments) — a transfer's send-by is tested below with a statement that asks for one
        assert new["send_by"] is None

        november = await _rents(api, **{"from": "2026-11-01", "to": "2026-11-30"})
        assert [(r["id"], r["amount"], r["due_date"]) for r in november] == [
            (DEMO_NEW_RENT, 670.0, "2026-11-04")
        ]

        # the views that list payments agree, on a day in November
        clock.set_today("2026-11-02")
        today = (await api.client.get("/api/dashboard")).json()
        listed = {item["id"] for item in [*today["attention"], *today["upcoming"]]}
        upcoming = {item["id"] for item in today["money"]["upcoming_payments"]}
        assert DEMO_NEW_RENT in listed and DEMO_NEW_RENT in upcoming
        assert DEMO_RENT not in listed | upcoming
        agenda = build_agenda(api.ctx.store, date(2026, 11, 2))
        rents = [entry for entry in agenda.payments_this_month if entry.id in (DEMO_RENT, DEMO_NEW_RENT)]
        assert [(entry.id, entry.amount) for entry in rents] == [(DEMO_NEW_RENT, 670.0)]
        ask = LedgerTools(api.ctx.store, today=date(2026, 11, 2)).money_summary().record
        asked = {row["id"] for row in ask["upcoming_payments"]}
        assert DEMO_NEW_RENT in asked and DEMO_RENT not in asked

        clock.set_today("2026-09-28")
        december = await _patch(api, DEMO_NEW_RENT, status="done")
        assert (december["status"], december["due_date"]) == ("open", "2026-12-03")
        undone = await _patch(api, DEMO_NEW_RENT, status="open")  # the toast's "Undo"
        assert (undone["status"], undone["due_date"]) == ("open", "2026-11-04")

        reopened = await _patch(api, DEMO_RENT, status="open")  # the closed rent set open again
        assert (reopened["status"], reopened["due_date"]) == ("open", "2026-10-05")
        assert "Reopened “Monthly rent” (Mon 5 Oct 2026)" in _log(api, DEMO_RENT)
        closed = await _patch(api, DEMO_RENT, status="done")
        assert (closed["status"], closed["due_date"]) == ("done", "2026-10-05")


# --------------------------------------------------------------------------------------------------
# a SPECIMEN lease, statement and rent increase through the API
# --------------------------------------------------------------------------------------------------

LANDLORD = {"name": "Wohnbau Musterstadt eG", "kind": "landlord"}
RENT_QUOTE = "Die Miete von 640,00 EUR ist spätestens am dritten Werktag eines jeden Monats zu zahlen."
NEW_RENT_QUOTE = "Ihre Gesamtmiete beträgt ab dem 01.11.2026 somit 670,00 EUR (bisher 640,00 EUR)."
OWN_DAY_QUOTE = (
    "Die neue Gesamtmiete von 670,00 EUR ist ab dem 01.11.2026 spätestens am fünften Werktag eines jeden "
    "Monats zu zahlen."
)
ASK_QUOTE = "Wir bitten Sie um Zustimmung zur Erhöhung der Miete auf die ortsübliche Vergleichsmiete."
INCREASE_QUOTE = "Die neue Miete von 700,00 EUR ist ab dem 01.12.2026 zu zahlen."


def _lease(quote: str = RENT_QUOTE, when: dict[str, Any] | None = None) -> Letter:
    """The lease of a flat from 1 Oct 2026: its monthly rent read as the demo's is, without a day (the law's
    3rd working day dates it) unless ``when`` gives one, and the tenancy as a rent contract."""
    return Letter(
        marker="Wohnraummietvertrag Beispielweg 7",
        pages=(("Wohnbau Musterstadt eG", "SPECIMEN", "Wohnraummietvertrag Beispielweg 7", quote),),
        payload={
            "kind": "rent_lease",
            "area": "home",
            "title": "Rental agreement",
            "sender": LANDLORD,
            "document_date": "2026-09-01",
            "summary": "A lease for a flat from 1 Oct 2026.",
            "explanation": "The rent is paid every month.",
            "items": [
                {
                    "kind": "payment",
                    "title": "Monthly rent",
                    "action": "Transfer the rent every month",
                    "date": when
                    or {"type": "none", "nature": "payment", "text": "spätestens am dritten Werktag"},
                    "amount": 640.0,
                    "currency": "EUR",
                    "direction": "out",
                    "recurrence": MONTHLY,
                    "quote": quote,
                }
            ],
            "contract": {
                "name": "Flat lease",
                "category": "rent",
                "start_date": "2026-10-01",
                "quotes": [quote],
            },
            "case_title": "Flat",
        },
    )


def _statement(quote: str = NEW_RENT_QUOTE, working_day: int | None = None) -> Letter:
    """The landlord's operating-cost statement: new advance payments, so a new total rent from November."""
    return Letter(
        marker="Betriebskostenabrechnung 2025 Beispielweg 7",
        pages=(("Wohnbau Musterstadt eG", "SPECIMEN", "Betriebskostenabrechnung 2025 Beispielweg 7", quote),),
        payload={
            "kind": "utility_bill",  # as the demo's statement is filed
            "area": "home",
            "title": "Operating cost statement 2025",
            "sender": LANDLORD,
            "document_date": "2026-09-08",
            "summary": "The advance payments rise, so the total rent is €670 from November.",
            "explanation": "Pay the new total rent from November.",
            "items": [
                {
                    "kind": "payment",
                    "title": "New monthly total rent €670",
                    "action": "Transfer the new total rent from November",
                    "date": {
                        "type": "fixed",
                        "date": "2026-11-01",
                        "nature": "payment",
                        "text": "ab dem 01.11.2026",
                    },
                    "amount": 670.0,
                    "currency": "EUR",
                    "direction": "out",
                    "recurrence": {**MONTHLY, "working_day": working_day},
                    "quote": quote,
                }
            ],
            "change": {
                "type": "price_increase",
                "effective_date": "2026-11-01",
                "old_amount": 640.0,
                "new_amount": 670.0,
                "quote": quote,
            },
            "case_title": "Flat",
        },
    )


def _increase() -> Letter:
    """A rent increase to the local comparative rent (§ 558 BGB), dated 24 Sep: €700 from 1 Dec, only owed
    once the tenant agrees (§ 558b Abs. 1 BGB)."""
    return Letter(
        marker="Mieterhöhungsverlangen Beispielweg 7",
        pages=(
            (
                "Wohnbau Musterstadt eG",
                "SPECIMEN",
                "Mieterhöhungsverlangen Beispielweg 7",
                ASK_QUOTE,
                INCREASE_QUOTE,
            ),
        ),
        payload={
            "kind": "rent_lease",  # the model's kind; code files it as a rent increase (ADR 0010)
            "high_stakes_kind": "rent_increase",
            "area": "home",
            "title": "Rent increase request",
            "sender": LANDLORD,
            "document_date": "2026-09-24",
            "summary": "The landlord asks you to agree to €700 rent from December.",
            "explanation": "The higher rent is only owed once you agree.",
            "items": [
                {
                    "kind": "payment",
                    "title": "New monthly rent €700",
                    "action": "Transfer the new rent from December if you agree",
                    "date": {
                        "type": "fixed",
                        "date": "2026-12-01",
                        "nature": "payment",
                        "text": "ab dem 01.12.2026",
                    },
                    "amount": 700.0,
                    "currency": "EUR",
                    "direction": "out",
                    "recurrence": MONTHLY,
                    "quote": INCREASE_QUOTE,
                }
            ],
            "change": {
                "type": "price_increase",
                "effective_date": "2026-12-01",
                "old_amount": 640.0,
                "new_amount": 700.0,
                "quote": ASK_QUOTE,
            },
            "case_title": "Flat",
        },
    )


def _router(*letters: Letter) -> ApiRouter:
    router = ApiRouter()
    router.letters = (*router.letters, *letters)
    router.payloads |= {letter.marker: letter.extraction() for letter in letters}
    return router


async def _read(api: Api, letter: Letter) -> tuple[str, dict[str, Any]]:
    """Upload ``letter``, read it and return its id and its monthly payment."""
    doc_id = (await api.upload((f"{letter.marker}.pdf", letter.pdf())))["documents"][0]["id"]
    await api.read_all()
    items = (await api.client.get("/api/items", params={"doc_id": doc_id, "kind": "payment"})).json()
    [monthly] = [item for item in items if item["recurrence"]]
    return doc_id, monthly


async def _read_again(api: Api, doc_id: str) -> None:
    assert (await api.client.post(f"/api/documents/{doc_id}/reprocess")).status_code == 202
    await api.read_all()


async def test_the_new_rent_keeps_the_leases_day_and_its_send_by(data_dir: Path) -> None:
    """The statement's new rent, "ab dem 01.11.2026", paid by transfer: due by the lease's day — the law's
    3rd working day, which the lease leaves it (so it carries the same warning to check the lease) — Wed 4
    Nov with its send-by Tue 3 Nov, then Thu 3 Dec; the lease rent's October is its last."""
    lease, statement = _lease(), _statement()
    clock.set_today("2026-09-28")
    async with api_for(data_dir, router=_router(lease, statement)) as api:
        _, rent = await _read(api, lease)
        _, new = await _read(api, statement)
        assert rent["contract_id"] is not None and new["contract_id"] == rent["contract_id"]
        assert (rent["due_date"], new["due_date"], new["send_by"]) == (
            "2026-10-05",
            "2026-11-04",
            "2026-11-03",
        )
        assert new["recurrence"] == {**MONTHLY, "working_day": None}  # the reading stays as it was read
        assert f"The lease's due day{KEEPS_DAY_STEP}Sun 1 Nov 2026 as the start" in _step_labels(new)
        assert LAW_DEFAULT_WARNING in new["computation"]["warnings"]

        closed = await _patch(api, rent["id"], status="done")
        assert (closed["status"], closed["due_date"]) == ("done", "2026-10-05")
        december = await _patch(api, new["id"], status="done")
        assert (december["due_date"], december["send_by"]) == ("2026-12-03", "2026-12-02")


async def test_a_rent_increase_not_yet_agreed_leaves_the_old_rent_running(data_dir: Path) -> None:
    """A § 558 increase's new rent (€700 from Thu 3 Dec, the lease's day) is only owed once agreed: the old
    rent runs on into December next to it, and the new one keeps its note. Once the person pays the new
    rent — paying counts as agreeing — the old rent, which had moved on to December, goes back to November,
    its last month, and closes there, since November was marked paid."""
    lease, increase = _lease(), _increase()
    clock.set_today("2026-09-29")
    async with api_for(data_dir, router=_router(lease, increase)) as api:
        _, rent = await _read(api, lease)
        _, new = await _read(api, increase)
        assert new["due_date"] == "2026-12-03"
        assert RENT_INCREASE_PAYMENT_WARNING in new["computation"]["warnings"]

        november = await _patch(api, rent["id"], status="done")
        assert (november["status"], november["due_date"]) == ("open", "2026-11-04")
        december = await _patch(api, rent["id"], status="done")
        assert (december["status"], december["due_date"]) == ("open", "2026-12-03")  # runs on
        still = await _item(api, new["id"])
        assert still["due_date"] == "2026-12-03"
        assert RENT_INCREASE_PAYMENT_WARNING in still["computation"]["warnings"]

        agreed = await _patch(api, new["id"], status="done")
        assert (agreed["status"], agreed["due_date"]) == ("open", "2027-01-06")
        old = await _item(api, rent["id"])
        assert (old["status"], old["due_date"]) == ("done", "2026-11-04")
        assert (
            "“Monthly rent” ends with the payment marked paid (Wed 4 Nov 2026) — replaced by “New monthly rent "
            "€700” from Dec 2026" in _log(api, rent["id"])
        )


async def test_a_new_rent_that_names_its_own_working_day_keeps_it(data_dir: Path) -> None:
    """ "spätestens am fünften Werktag" in the statement's own sentence: the new rent is due by its 5th
    working day, Fri 6 Nov — not the lease's 3rd — and still replaces the old rent from November."""
    lease, statement = _lease(), _statement(OWN_DAY_QUOTE, working_day=5)
    clock.set_today("2026-09-28")
    async with api_for(data_dir, router=_router(lease, statement)) as api:
        _, rent = await _read(api, lease)
        _, new = await _read(api, statement)
        assert new["due_date"] == "2026-11-06"
        assert not any(KEEPS_DAY_STEP in label for label in _step_labels(new))
        closed = await _patch(api, rent["id"], status="done")
        assert (closed["status"], closed["due_date"]) == ("done", "2026-10-05")


async def test_a_dismissed_new_rent_leaves_the_old_rent_running(data_dir: Path) -> None:
    """The person says the statement's new rent is not a real to-do: it replaces nothing, so the lease rent
    moves on to November as ever."""
    lease, statement = _lease(), _statement()
    clock.set_today("2026-09-28")
    async with api_for(data_dir, router=_router(lease, statement)) as api:
        _, rent = await _read(api, lease)
        _, new = await _read(api, statement)
        await _patch(api, new["id"], status="dismissed")
        paid = await _patch(api, rent["id"], status="done")
        assert (paid["status"], paid["due_date"]) == ("open", "2026-11-04")


async def test_reading_the_letters_again_doubles_nothing(data_dir: Path) -> None:
    """After October is paid, both letters read again: the old rent stays closed at October, the new one at
    Wed 4 Nov — one rent in November, no new to-dos."""
    lease, statement = _lease(), _statement()
    clock.set_today("2026-09-28")
    async with api_for(data_dir, router=_router(lease, statement)) as api:
        lease_id, rent = await _read(api, lease)
        statement_id, new = await _read(api, statement)
        await _patch(api, rent["id"], status="done")
        before = len(api.ctx.store.list_items())
        await _read_again(api, statement_id)
        await _read_again(api, lease_id)
        assert len(api.ctx.store.list_items()) == before
        old = await _item(api, rent["id"])
        assert (old["status"], old["due_date"]) == ("done", "2026-10-05")
        november = await _rents(api, **{"from": "2026-11-01", "to": "2026-11-30"})
        assert [(r["id"], r["due_date"]) for r in november] == [(new["id"], "2026-11-04")]


async def test_a_statement_read_after_octobers_rent_was_paid_closes_the_old_rent(data_dir: Path) -> None:
    """The usual order: October is paid, so the lease rent already shows Wed 4 Nov when the statement comes.
    It goes back to October, its last month, closed there because October was marked paid — November holds
    only the new rent."""
    lease, statement = _lease(), _statement()
    clock.set_today("2026-09-28")
    async with api_for(data_dir, router=_router(lease, statement)) as api:
        _, rent = await _read(api, lease)
        moved = await _patch(api, rent["id"], status="done")
        assert (moved["status"], moved["due_date"]) == ("open", "2026-11-04")
        _, new = await _read(api, statement)
        old = await _item(api, rent["id"])
        assert (old["status"], old["due_date"]) == ("done", "2026-10-05")
        assert (
            "“Monthly rent” ends with the payment marked paid (Mon 5 Oct 2026) — replaced by “New monthly total "
            "rent €670” from Nov 2026" in _log(api, rent["id"])
        )
        november = await _rents(api, **{"from": "2026-11-01", "to": "2026-11-30"})
        assert [(r["id"], r["due_date"]) for r in november] == [(new["id"], "2026-11-04")]


async def test_a_rent_rolled_on_unpaid_goes_back_to_its_last_month(data_dir: Path) -> None:
    """October's rent was never marked paid and the days moved it on to November (point 3) before the
    statement came: it goes back to October, its last month, still open — nobody said it was paid — and no
    day moves it past it again."""
    lease, statement = _lease(), _statement()
    clock.set_today("2026-09-28")
    async with api_for(data_dir, router=_router(lease, statement)) as api:
        _, rent = await _read(api, lease)
        clock.set_today("2026-10-20")
        rolled = await _patch(api, rent["id"], title="Monthly rent")  # any edit brings it to today
        assert rolled["due_date"] == "2026-11-04"
        await _read(api, statement)
        old = await _item(api, rent["id"])
        assert (old["status"], old["due_date"]) == ("open", "2026-10-05")
        assert any("is back at its last occurrence (Mon 5 Oct 2026)" in m for m in _log(api, rent["id"]))
        clock.set_today("2026-11-10")
        still = await _patch(api, rent["id"], title="Monthly rent")
        assert (still["status"], still["due_date"]) == ("open", "2026-10-05")


async def test_a_statement_read_before_the_lease_joins_it_once_read_again(data_dir: Path) -> None:
    """The statement first: there is no rent contract to link it to yet, so its new rent is due Sun 1 Nov as
    written, and once the lease is read the two rents run side by side — the accepted limit of a rent
    without a contract link. Read again, the statement links to the lease's contract: its new rent keeps the
    lease's day, Wed 4 Nov, and ends the lease rent after October."""
    lease, statement = _lease(), _statement()
    clock.set_today("2026-09-28")
    async with api_for(data_dir, router=_router(lease, statement)) as api:
        statement_id, new = await _read(api, statement)
        assert (new["contract_id"], new["due_date"]) == (None, "2026-11-01")
        _, rent = await _read(api, lease)
        assert (rent["due_date"], (await _item(api, new["id"]))["due_date"]) == ("2026-10-05", "2026-11-01")

        await _read_again(api, statement_id)
        again = await _item(api, new["id"])
        assert again["contract_id"] == rent["contract_id"]
        assert (again["due_date"], again["send_by"]) == ("2026-11-04", "2026-11-03")
        closed = await _patch(api, rent["id"], status="done")
        assert (closed["status"], closed["due_date"]) == ("done", "2026-10-05")


async def test_a_rent_on_the_same_day_of_every_month_passes_that_day_on(data_dir: Path) -> None:
    """A lease rent due on the 15th of each month (its first on Thu 15 Oct): the statement's new rent "ab dem
    01.11.2026" is due on the 15th too — Sun 15 Nov, then Tue 15 Dec."""
    lease = _lease(
        "Die Miete von 640,00 EUR ist ab dem 15.10.2026 jeweils zum 15. eines Monats zu zahlen.",
        {"type": "fixed", "date": "2026-10-15", "nature": "payment", "text": "ab dem 15.10.2026"},
    )
    statement = _statement()
    clock.set_today("2026-09-28")
    async with api_for(data_dir, router=_router(lease, statement)) as api:
        _, rent = await _read(api, lease)
        _, new = await _read(api, statement)
        assert rent["due_date"] == "2026-10-15"
        assert new["due_date"] == "2026-11-15"
        assert f"The lease's due day{KEEPS_DAY_STEP}Sun 1 Nov 2026 as the start" in _step_labels(new)
        december = await _patch(api, new["id"], status="done")
        assert december["due_date"] == "2026-12-15"
