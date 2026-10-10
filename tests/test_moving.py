"""The moving checklist (``moved_house``): after the person says they moved, Today lists who needs the new
address — registering at the Bürgeramt within two weeks (§ 17 Abs. 1 BMG), each organisation with the old
address on record, and the broadcasting fee office. A move is said, never guessed; nothing is sent."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, timedelta
from typing import Any

import pytest

from helpers_secretary import TODAY, add_doc, seed_ledger
from ordnung.assistant.ask import known_laws
from ordnung.db.store import Store
from ordnung.models import Suggestion
from ordnung.secretary.moving import (
    BROADCASTING_ENTITY,
    LETTER_LEAD_DAYS,
    LOOKBACK_DAYS,
    MOVE_AHEAD_DAYS,
    MOVE_WINDOW_DAYS,
    REGISTRATION_ENTITY,
    RULE_ID,
    move_problem,
    moving_ideas,
    registration_due,
)
from ordnung.secretary.triggers import (
    IDEA_LAWS,
    REGISTRATION_LAW,
    TRIGGERS,
    Ledger,
    fingerprint,
    run_and_reconcile,
    run_triggers,
)

NEW_ADDRESS = "Neue Allee 7\n54321 Beispielstadt"
OLD_ADDRESS = "Alte Straße 1\n12345 Musterstadt"


@pytest.fixture
def ids(store: Store) -> dict[str, str]:
    return seed_ledger(store)


def move(store: Store, moved_on: str | None, **fields: Any) -> None:
    """The person says they moved in on ``moved_on`` (``None``: no move)."""
    profile = store.get_profile().model_dump()
    store.save_profile(
        profile | {"address": NEW_ADDRESS, "old_address": OLD_ADDRESS, "moved_on": moved_on} | fields
    )


def rows(store: Store, today: date = TODAY) -> list[Suggestion]:
    return run_triggers(store, today)[RULE_ID]


def by_entity(ideas: list[Suggestion]) -> dict[str, Suggestion]:
    return {idea.fingerprint.split(":")[1]: idea for idea in ideas}


def told_rows(ideas: list[Suggestion]) -> list[str]:
    """The organisations listed, in order (their rows' titles)."""
    return [idea.title for idea in ideas if idea.action is not None and idea.action.target_type == "party"]


# --------------------------------------------------------------------------------------------------
# a move is said, never guessed
# --------------------------------------------------------------------------------------------------


def test_no_move_no_rows(store: Store, ids: dict[str, str]) -> None:
    assert rows(store) == []
    # a new address alone is no move
    store.save_profile(
        store.get_profile().model_dump() | {"address": NEW_ADDRESS, "old_address": OLD_ADDRESS}
    )
    assert rows(store) == []


def test_the_rule_is_registered_after_sender_land() -> None:
    rules = list(TRIGGERS)
    assert rules.index(RULE_ID) == rules.index("sender_land") + 1


# --------------------------------------------------------------------------------------------------
# registering at the Bürgeramt
# --------------------------------------------------------------------------------------------------


def test_registration_is_due_two_weeks_after_moving_in(store: Store, ids: dict[str, str]) -> None:
    move(store, "2026-09-24")  # a Thursday
    idea = by_entity(rows(store))[REGISTRATION_ENTITY]

    assert idea.title == "Register your new address by Thu 8 Oct"
    assert idea.due_date == "2026-10-08"
    assert (idea.kind, idea.priority, idea.refs) == ("deadline", "high", [])
    assert idea.action is not None and idea.action.type == "none"
    assert (
        idea.rationale == "You moved in on Thu 24 Sep; registering is due within two weeks (§ 17 Abs. 1 BMG)."
    )
    assert "Bürgeramt" in idea.body and "Wohnungsgeberbestätigung" in idea.body
    assert idea.body.endswith("Appointments are often booked out, so book one soon.")
    assert idea.fingerprint == fingerprint(RULE_ID, REGISTRATION_ENTITY, "2026-09-24")


def test_the_registration_day_is_never_moved_off_a_weekend() -> None:
    """The safe, earlier day: whether the end moves to Monday is not settled for this duty."""
    assert registration_due(date(2026, 9, 26)) == date(2026, 10, 10)  # Saturday → Saturday
    assert registration_due(date(2026, 9, 27)) == date(2026, 10, 11)  # Sunday → Sunday
    assert registration_due(date(2026, 12, 18)) == date(2027, 1, 1)  # a public holiday stays too


def test_a_missed_registration_says_so(store: Store, ids: dict[str, str]) -> None:
    move(store, "2026-09-01")
    idea = by_entity(rows(store))[REGISTRATION_ENTITY]
    assert idea.title == "Register your new address — it was due Tue 15 Sep"
    assert idea.body.endswith("Register as soon as you can.")
    assert "book one soon" not in idea.body
    # the day itself is not missed yet
    on_the_day = by_entity(rows(store, date(2026, 9, 15)))[REGISTRATION_ENTITY]
    assert on_the_day.title == "Register your new address by Tue 15 Sep"


def test_a_move_still_ahead_lists_the_same_rows(store: Store, ids: dict[str, str]) -> None:
    move(store, "2026-11-02")
    found = by_entity(rows(store))
    assert found[REGISTRATION_ENTITY].title == "Register your new address by Mon 16 Nov"
    assert found[REGISTRATION_ENTITY].rationale is not None
    assert found[REGISTRATION_ENTITY].rationale.startswith("You moved in on Mon 2 Nov;")


def test_the_registration_law_is_known_to_ask() -> None:
    assert REGISTRATION_LAW == "§ 17 Abs. 1 BMG"
    assert REGISTRATION_LAW in IDEA_LAWS
    assert REGISTRATION_LAW in known_laws()


# --------------------------------------------------------------------------------------------------
# who needs the new address
# --------------------------------------------------------------------------------------------------


def test_who_is_listed(store: Store, ids: dict[str, str]) -> None:
    old_bank = store.add_party(name="Altbank", kind="bank")
    add_doc(  # a sender who last wrote more than three years ago
        store,
        "old-bank",
        kind="bank_letter",
        title="Account statement",
        doc_date="2023-09-01",
        party_id=old_bank.id,
    )
    move(store, "2026-09-24")
    ideas = rows(store)

    # employer, … utility, telecom, … tax office, immigration office, then everyone else
    assert told_rows(ideas) == [
        "Tell Muster Tech GmbH your new address",
        "Tell Stadtwerke Musterstadt your new address",
        "Tell FunkNetz Mobile your new address",
        "Tell Finanzamt Musterstadt your new address",
        "Tell Ausländerbehörde Musterstadt your new address",
        "Tell FitMuster Studio your new address",
    ]
    # not listed: a shop with no contract, a sender of scam letters only, a broadcaster that never wrote,
    # a university that never wrote, and a bank whose last letter is older than three years
    for party in ("techmarkt", "fake_beitrag", "beitrag", "uni"):
        assert ids[party] not in by_entity(ideas)
    assert old_bank.id not in by_entity(ideas)

    for idea in ideas:
        if idea.action is None or idea.action.target_type != "party":
            continue
        party_id = idea.action.target_id
        assert party_id is not None
        assert (idea.action.type, idea.action.label) == ("open", "Write the letter")
        assert [(ref.type, ref.id) for ref in idea.refs] == [("party", party_id)]
        assert (idea.kind, idea.priority, idea.due_date) == ("hygiene", "low", None)
        assert idea.rationale == "You moved in on Thu 24 Sep."
        assert idea.fingerprint == fingerprint(RULE_ID, party_id, "2026-09-24")


def test_a_running_contract_and_a_recent_letter_each_say_why(store: Store, ids: dict[str, str]) -> None:
    store.add_contract(name="FunkNetz home internet", category="internet", party_id=ids["funknetz"])
    store.add_contract(name="FunkNetz TV", category="streaming", party_id=ids["funknetz"])
    move(store, "2026-09-24")
    found = by_entity(rows(store))

    phone = found[ids["funknetz"]].body
    assert phone.startswith(
        "Your contracts “FunkNetz home internet”, “FunkNetz mobile” and 1 more with them are running."
    )
    assert "move the line to the new address" in phone
    assert found[ids["stadtwerke"]].body.startswith(
        "Your contract “Stadtwerke electricity” with them is running."
    )
    assert "meter readings" in found[ids["stadtwerke"]].body
    assert found[ids["employer"]].body.startswith(
        "Your contract “Working student contract” with them is running."
    )
    assert "payslips" in found[ids["employer"]].body
    assert found[ids["finanzamt"]].body.startswith("They last wrote to you on Tue 15 Sep.")
    assert "tax return" in found[ids["finanzamt"]].body
    assert found[ids["abh"]].body.startswith("They last wrote to you on Fri 10 Jan 2025.")
    assert "residence permit" in found[ids["abh"]].body


def test_two_contracts_are_both_named(store: Store, ids: dict[str, str]) -> None:
    store.add_contract(name="Stadtwerke gas", category="gas", party_id=ids["stadtwerke"])
    move(store, "2026-09-24")
    body = by_entity(rows(store))[ids["stadtwerke"]].body
    assert body.startswith(
        "Your contracts “Stadtwerke electricity” and “Stadtwerke gas” with them are running."
    )


def test_an_ended_contract_or_one_from_a_scam_letter_is_no_reason(store: Store, ids: dict[str, str]) -> None:
    store.update_contract(ids["gym_contract"], status="ended")
    store.add_contract(
        name="Broadcasting fee", category="other", party_id=ids["fake_beitrag"], source_doc_id=ids["doc_scam"]
    )
    move(store, "2026-09-24")
    found = by_entity(rows(store))
    assert ids["gym"] not in found
    assert ids["fake_beitrag"] not in found


def test_a_letter_kept_private_never_lists_its_sender(store: Store, ids: dict[str, str]) -> None:
    """A row's title reaches the weekly Ideas and the daily note: a "Keep private — no AI" letter's sender
    never gets one from that letter (nor from a contract read from it)."""
    insurer = store.add_party(name="Diskret Versicherung", kind="insurer")
    letter = add_doc(
        store,
        "insurer",
        kind="insurance",
        title="Policy",
        doc_date="2026-06-01",
        party_id=insurer.id,
        ai_private=True,
    )
    store.add_contract(name="Liability", category="insurance", party_id=insurer.id, source_doc_id=letter)
    move(store, "2026-09-24")
    assert insurer.id not in by_entity(rows(store))


def test_tips_follow_the_kind_of_organisation(store: Store, ids: dict[str, str]) -> None:
    def sender(name: str, kind: str) -> str:
        party = store.add_party(name=name, kind=kind)
        add_doc(store, name, kind="other", title=f"From {name}", doc_date="2026-08-01", party_id=party.id)
        return party.id

    bank = sender("Sparkasse Musterstadt", "bank")
    insurer = sender("Muster Versicherung", "insurer")
    landlord = sender("Hausverwaltung Muster", "landlord")
    moved = sender("Hochschule Beispiel", "university")
    move(store, "2026-09-24")
    found = by_entity(rows(store))
    assert "online banking" in found[bank].body
    assert "their app or online account" in found[insurer].body
    assert "deposit" in found[landlord].body
    assert "enrolment" in found[moved].body
    assert found[bank].body.startswith("They last wrote to you on Sat 1 Aug.")


def test_a_letter_within_three_years_counts_and_one_before_doesnt(store: Store, ids: dict[str, str]) -> None:
    bank = store.add_party(name="Grenzbank", kind="bank")
    add_doc(store, "edge", kind="bank_letter", title="Statement", doc_date="2023-09-28", party_id=bank.id)
    move(store, "2026-09-24")
    assert (TODAY - date(2023, 9, 28)).days <= LOOKBACK_DAYS
    assert bank.id in by_entity(rows(store))
    assert bank.id not in by_entity(rows(store, TODAY + timedelta(days=1)))


# --------------------------------------------------------------------------------------------------
# the broadcasting fee office
# --------------------------------------------------------------------------------------------------


def test_the_broadcasting_row_stands_in_for_a_missing_broadcaster(store: Store, ids: dict[str, str]) -> None:
    move(store, "2026-09-24")
    fixed = by_entity(rows(store))[BROADCASTING_ENTITY]
    assert fixed.title == "Tell the broadcasting fee office your new address"
    assert "rundfunkbeitrag.de" in fixed.body and "Rundfunkbeitrag" in fixed.body
    assert (fixed.kind, fixed.priority, fixed.refs, fixed.due_date) == ("hygiene", "low", [], None)
    assert fixed.action is not None and fixed.action.type == "none"

    add_doc(
        store,
        "beitrag",
        kind="broadcasting_fee",
        title="Broadcasting fee notice",
        doc_date="2026-07-01",
        party_id=ids["beitrag"],
    )
    found = by_entity(rows(store))
    assert BROADCASTING_ENTITY not in found
    assert found[ids["beitrag"]].title == "Tell Beitragsservice Musterstadt your new address"
    assert "rundfunkbeitrag.de" in found[ids["beitrag"]].body


def test_a_sender_whose_letter_is_the_broadcasting_fee_counts_as_the_broadcaster(
    store: Store, ids: dict[str, str]
) -> None:
    office = store.add_party(name="ARD ZDF Deutschlandradio Beitragsservice", kind="authority")
    add_doc(store, "fee", kind="broadcasting_fee", title="Fee", doc_date="2026-05-01", party_id=office.id)
    store.add_contract(name="Rundfunkbeitrag", category="other", party_id=office.id)
    move(store, "2026-09-24")
    found = by_entity(rows(store))
    assert office.id in found
    assert BROADCASTING_ENTITY not in found


# --------------------------------------------------------------------------------------------------
# how rows end
# --------------------------------------------------------------------------------------------------


def test_a_sent_new_address_letter_takes_the_row_away(store: Store, ids: dict[str, str]) -> None:
    move(store, "2026-09-24")
    run_and_reconcile(store, TODAY)
    row = by_entity(rows(store))[ids["funknetz"]]

    unsent = store.add_draft(kind="address_change", party_id=ids["funknetz"], status="final")
    assert ids["funknetz"] in by_entity(rows(store))
    too_early = store.add_draft(
        kind="address_change",
        party_id=ids["funknetz"],
        status="sent",
        sent_at=f"{date(2026, 9, 24) - timedelta(days=LETTER_LEAD_DAYS + 1)}T10:00:00Z",
    )
    other_kind = store.add_draft(
        kind="general_reply", party_id=ids["funknetz"], status="sent", sent_at="2026-09-25T10:00:00Z"
    )
    assert ids["funknetz"] in by_entity(rows(store))

    store.update_draft(unsent.id, status="sent", sent_at="2026-09-14T10:00:00Z")  # 10 days before the move
    assert ids["funknetz"] not in by_entity(rows(store))
    run_and_reconcile(store, TODAY)
    stored = store.get_suggestion(row.id)
    assert stored is not None and stored.status == "expired"
    assert {too_early.id, other_kind.id} <= {draft.id for draft in store.list_drafts(status="sent")}


def test_ticks_last_and_a_new_move_starts_fresh(store: Store, ids: dict[str, str]) -> None:
    move(store, "2026-09-24")
    run_and_reconcile(store, TODAY)
    tax_office = by_entity(rows(store))[ids["finanzamt"]]
    store.update_suggestion(tax_office.id, status="done")
    run_and_reconcile(store, TODAY)
    kept = store.get_suggestion(tax_office.id)
    assert kept is not None and kept.status == "done"

    old_rows = [idea.id for idea in rows(store) if idea.id != tax_office.id]
    move(store, "2026-09-21")
    run_and_reconcile(store, TODAY)
    fresh = by_entity(rows(store))
    assert all(idea.id not in old_rows and idea.id != tax_office.id for idea in fresh.values())
    assert all((store.get_suggestion(idea.id) or idea).status == "new" for idea in fresh.values())
    assert {(store.get_suggestion(i) or tax_office).status for i in old_rows} == {"expired"}
    done = store.get_suggestion(tax_office.id)
    assert done is not None and done.status == "done"  # the old move's answers stay as they were


def test_stopping_the_checklist_expires_its_open_rows(store: Store, ids: dict[str, str]) -> None:
    move(store, "2026-09-24")
    run_and_reconcile(store, TODAY)
    listed = [idea.id for idea in rows(store)]
    move(store, None, old_address="")
    run_and_reconcile(store, TODAY)
    assert rows(store) == []
    assert [(stored.status if (stored := store.get_suggestion(i)) else None) for i in listed] == [
        "expired"
    ] * len(listed)


def test_the_checklist_ends_180_days_after_the_move(store: Store, ids: dict[str, str]) -> None:
    moved = TODAY - timedelta(days=MOVE_WINDOW_DAYS)
    move(store, moved.isoformat())
    assert rows(store)
    assert rows(store, TODAY + timedelta(days=1)) == []


# --------------------------------------------------------------------------------------------------
# privacy and cost
# --------------------------------------------------------------------------------------------------


def test_no_row_carries_an_address(store: Store, ids: dict[str, str]) -> None:
    move(store, "2026-09-24")
    ideas = rows(store)
    assert len(ideas) >= 7
    for idea in ideas:
        words = " ".join(
            [idea.title, idea.body, idea.rationale or "", idea.action.label if idea.action else ""]
        )
        for line in (*NEW_ADDRESS.splitlines(), *OLD_ADDRESS.splitlines()):
            assert line not in words, idea.title
        for part in ("Neue Allee", "Alte Straße", "54321", "12345"):
            assert part not in words, idea.title


@contextmanager
def counting_reads(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, int]]:
    """How often each of the store's list and get reads ran inside the block."""
    counts: dict[str, int] = {}
    reads = [name for name in dir(Store) if name.startswith(("list_", "get_"))]
    with monkeypatch.context() as patch:
        for name in reads:
            original = getattr(Store, name)

            def tracked(
                self: Store, *args: Any, __name: str = name, __original: Any = original, **kw: Any
            ) -> Any:
                counts[__name] = counts.get(__name, 0) + 1
                return __original(self, *args, **kw)

            patch.setattr(Store, name, tracked)
        yield counts


def test_the_rule_reads_parties_contracts_and_drafts_once(
    store: Store, ids: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Batch A made the Ideas refresh grow with the ledger, not its square: the rule reads the parties, the
    contracts and the sent letters once per run, never once per organisation."""
    for n in range(40):
        party = store.add_party(name=f"Versicherung {n:02d}", kind="insurer")
        store.add_contract(name=f"Policy {n:02d}", category="insurance", party_id=party.id)
        add_doc(
            store,
            f"policy-{n}",
            kind="insurance",
            title=f"Policy {n}",
            doc_date="2026-05-01",
            party_id=party.id,
        )
        store.add_draft(
            kind="address_change", party_id=party.id, status="sent", sent_at="2026-09-20T10:00:00Z"
        )
    move(store, "2026-09-24")

    ledger = Ledger(store, TODAY)  # the rows every rule shares, loaded once
    with counting_reads(monkeypatch) as counts:
        ideas = moving_ideas(ledger)
    assert told_rows(ideas) and not any(title.startswith("Tell Versicherung") for title in told_rows(ideas))
    assert counts.get("list_drafts", 0) == 1
    assert not {name for name in counts if name != "list_drafts"}, counts

    # a whole run reads the store as often with the move as without it: the rule shares what the others read
    with counting_reads(monkeypatch) as counts:
        run_triggers(store, TODAY)
    move(store, None)
    run_triggers(store, TODAY)  # the rows of the changed profile, loaded once more outside the count
    with counting_reads(monkeypatch) as without:
        run_triggers(store, TODAY)
    move(store, "2026-09-24")
    run_triggers(store, TODAY)
    with counting_reads(monkeypatch) as again:
        assert told_rows(run_triggers(store, TODAY)[RULE_ID])
    assert again == without, (again, without)
    assert counts.get("list_parties", 0) <= 1 and counts.get("list_contracts", 0) <= 1, counts


# --------------------------------------------------------------------------------------------------
# the day a move may be told
# --------------------------------------------------------------------------------------------------


def test_a_move_may_be_told_from_six_months_back_to_three_ahead() -> None:
    today = date(2026, 9, 25)
    assert move_problem(today - timedelta(days=MOVE_WINDOW_DAYS), today) is None
    assert move_problem(today + timedelta(days=MOVE_AHEAD_DAYS), today) is None
    assert move_problem(today, today) is None
    for day in (today - timedelta(days=MOVE_WINDOW_DAYS + 1), today + timedelta(days=MOVE_AHEAD_DAYS + 1)):
        assert move_problem(day, today) == (
            "Ordnung's moving checklist is for a move in the last six months or the next three — check the day."
        )
