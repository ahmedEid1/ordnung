"""The Land the postcode on a sender's letters suggests, while the person hasn't set it: where it comes from, the
dates it may change, and the ``sender_land`` Idea that asks about it — a question, never an answer (ADR 0019)."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from helpers_secretary import TODAY
from helpers_sender_land import (
    BACKWARDS,
    DELIVERY,
    DRESDEN,
    ERFURT,
    HOLIDAY,
    MUNICH,
    NUREMBERG,
    QUIET,
    letter_from,
    to_do,
    without_land,
)
from ordnung.assistant.mcp_server import PARTY_FIELDS
from ordnung.db.store import Store
from ordnung.models import ContractComputation, Party, RegionSuggestion, Suggestion
from ordnung.rules import normalize_region
from ordnung.rules.calendar_de import REGION_NAMES
from ordnung.rules.deadlines import REGION_EARLIER, REGION_UNKNOWN, compute_due
from ordnung.rules.delivery import LAND_DAYS_UNCONFIRMED
from ordnung.secretary import sender_land
from ordnung.secretary.sender_land import (
    LETTERS_LOOKED_AT,
    RULE_ID,
    idea_id,
    land_name,
    region_suggestion,
    sender_land_ideas,
)
from ordnung.secretary.triggers import TRIGGERS, Ledger, fingerprint, run_and_reconcile, run_triggers

#: Sam's town in the persona: 12345 is a Berlin postcode
HOME = "Beispielweg 5\n12345 Musterstadt"


def _sender(store: Store, name: str = "Stadtwerke Beispiel", **fields: Any) -> Party:
    fields.setdefault("kind", "authority")
    return store.add_party(name=name, **fields)


def _suggest(store: Store, party: Party, today: date = TODAY, **kw: Any) -> RegionSuggestion | None:
    found = store.get_party(party.id)
    assert found is not None
    return region_suggestion(Ledger(store, today), found, **kw)


def _ideas(store: Store, today: date = TODAY) -> list[Suggestion]:
    return run_triggers(store, today)[RULE_ID]


def _onboarded(store: Store, region: str = "NW", **fields: Any) -> None:
    store.save_profile({"name": "Sam Rivera", "address": HOME, "region": region, "onboarded": True, **fields})


# --------------------------------------------------------------------------------------------------
# where the suggestion comes from: the sender's letters, never the stored address
# --------------------------------------------------------------------------------------------------


def test_the_newest_live_incoming_letter_suggests_the_land(store: Store) -> None:
    party = _sender(store)
    letter_from(store, party, MUNICH, day="2026-08-01")
    newest = letter_from(store, party, NUREMBERG, day="2026-09-20")

    found = _suggest(store, party)

    assert found == RegionSuggestion(region="BY", postcode="90403", doc_id=newest)
    assert (store.get_party(party.id) or party).region is None  # a question: nothing is set


@pytest.mark.parametrize("how", ["scam_signs", "trashed", "outgoing"])
def test_a_letter_with_scam_signs_in_the_trash_or_sent_out_is_never_a_source(store: Store, how: str) -> None:
    party = _sender(store)
    older = letter_from(store, party, MUNICH, day="2026-08-01")
    if how == "scam_signs":
        newest = letter_from(store, party, DRESDEN, warnings=["Possible scam: payment to an account abroad."])
    else:
        newest = letter_from(store, party, DRESDEN, direction="outgoing" if how == "outgoing" else "incoming")
    if how == "trashed":
        store.trash_document(newest)

    found = _suggest(store, party)

    assert found is not None and (found.region, found.doc_id) == ("BY", older)


def test_a_postcode_only_in_hidden_text_never_suggests(store: Store) -> None:
    party = _sender(store)
    letter_from(store, party, DRESDEN, shown="Stadtwerke Beispiel\nSehr geehrte Frau Rivera,", hidden=DRESDEN)
    assert _suggest(store, party) is None


def test_letters_that_name_different_lands_suggest_nothing(store: Store) -> None:
    party = _sender(store)
    letter_from(store, party, MUNICH, day="2026-08-01")
    letter_from(store, party, DRESDEN, day="2026-09-20")
    assert _suggest(store, party) is None


def test_only_the_newest_letters_are_looked_at(store: Store) -> None:
    """A sender who moved shows it in recent letters: older ones don't keep the question from being asked."""
    party = _sender(store)
    letter_from(store, party, DRESDEN, day="2025-01-02")
    for month in range(1, LETTERS_LOOKED_AT + 1):
        letter_from(store, party, MUNICH, day=f"2026-{month:02d}-01")
    found = _suggest(store, party)
    assert found is not None and found.region == "BY"


def test_a_sender_whose_land_is_set_is_not_asked(store: Store) -> None:
    party = _sender(store, region="SN")
    letter_from(store, party, MUNICH)
    assert _suggest(store, party) is None


def test_the_sender_s_stored_address_is_never_a_source(store: Store) -> None:
    """``Party.address`` is the first letter's address, never refreshed, and nothing checks it against a page."""
    party = _sender(store, address=MUNICH)
    letter_from(store, party, None, shown=f"Stadtwerke Beispiel\n{MUNICH}")
    assert _suggest(store, party) is None


def test_no_question_when_the_postcode_contradicts_the_person_s_own_land(store: Store) -> None:
    """Sam set North Rhine-Westphalia for their own town, yet the table puts its postcode in Berlin: the table
    and the person disagree, so a sender in that town is not asked. Before onboarding the Land shown is a
    default, no one's choice (``Profile.known_region``), and vetoes nothing."""
    party = _sender(store, name="Stadt Musterstadt")
    letter_from(store, party, "Rathausplatz 1, 12345 Musterstadt")
    _onboarded(store, region="NW")
    assert _suggest(store, party) is None

    _onboarded(store, region="NW", onboarded=False)
    found = _suggest(store, party)
    assert found is not None and (found.region, found.postcode) == ("BE", "12345")


def test_a_sender_abroad_is_not_asked(store: Store) -> None:
    party = _sender(store, name="Agence Exemple")
    letter_from(store, party, "75116 Paris", email="contact@exemple.fr")
    assert _suggest(store, party) is None


# --------------------------------------------------------------------------------------------------
# which dates may change once it is confirmed
# --------------------------------------------------------------------------------------------------


def test_the_sender_s_open_dates_a_land_may_move_are_counted(store: Store) -> None:
    party = _sender(store)
    letter = letter_from(store, party, MUNICH)
    to_do(store, party, letter, HOLIDAY)
    to_do(store, party, letter, DELIVERY)  # Bavaria uses the 4-day rule: confirming it may move this one
    to_do(store, party, letter, QUIET)
    to_do(store, party, letter, HOLIDAY, status="done")
    to_do(store, party, letter, HOLIDAY, filed_on="2027-01-20")  # history when it was read: set aside
    to_do(store, party, letter, HOLIDAY, origin="manual")  # typed in by hand: a Land never recomputes it
    to_do(store, party, letter, HOLIDAY, due_date_source="manual")

    found = _suggest(store, party)

    assert found is not None and (found.waiting, found.may_be_late) == (2, False)


def test_a_date_counted_backwards_may_be_late(store: Store) -> None:
    receipt = compute_due(BACKWARDS, without_land(BACKWARDS))
    assert any(REGION_EARLIER in warning for warning in receipt.warnings)
    party = _sender(store)
    letter = letter_from(store, party, MUNICH)
    to_do(store, party, letter, HOLIDAY)
    to_do(store, party, letter, BACKWARDS)

    found = _suggest(store, party)

    assert found is not None and (found.waiting, found.may_be_late) == (2, True)


def test_the_3_or_4_day_rule_waits_only_for_a_land_that_uses_the_4th_day(store: Store) -> None:
    """Thuringia's authorities count 3 days, as Ordnung does without the Land: confirming it changes nothing."""
    receipt = compute_due(DELIVERY, without_land(DELIVERY))
    assert receipt.warnings == [LAND_DAYS_UNCONFIRMED]
    erfurt, munich = _sender(store, name="Stadt Erfurt"), _sender(store, name="Stadt München")
    to_do(store, erfurt, letter_from(store, erfurt, ERFURT), DELIVERY)
    to_do(store, munich, letter_from(store, munich, MUNICH), DELIVERY)

    in_thuringia, in_bavaria = _suggest(store, erfurt), _suggest(store, munich)

    assert in_thuringia is not None and (in_thuringia.region, in_thuringia.waiting) == ("TH", 0)
    assert in_bavaria is not None and (in_bavaria.region, in_bavaria.waiting) == ("BY", 1)


def test_a_letter_counts_only_its_own_dates(store: Store) -> None:
    party = _sender(store)
    first = letter_from(store, party, MUNICH, day="2026-08-01")
    second = letter_from(store, party, MUNICH, day="2026-09-20")
    to_do(store, party, first, HOLIDAY)
    to_do(store, party, second, HOLIDAY)
    to_do(store, party, second, BACKWARDS)

    by_letter = _suggest(store, party, doc_id=first)
    by_sender = _suggest(store, party)

    assert by_letter is not None and (by_letter.waiting, by_letter.may_be_late) == (1, False)
    assert by_letter.doc_id == second  # the newest letter that shows the postcode, whichever letter asks
    assert by_sender is not None and (by_sender.waiting, by_sender.may_be_late) == (3, True)


def test_no_question_on_a_letter_with_scam_signs_in_the_trash_or_sent_out(store: Store) -> None:
    party = _sender(store)
    letter_from(store, party, MUNICH, day="2026-08-01")
    scam = letter_from(store, party, MUNICH, warnings=["Possible scam: payment to an account abroad."])
    sent = letter_from(store, party, MUNICH, direction="outgoing", day="2026-09-21")
    trashed = letter_from(store, party, MUNICH, day="2026-09-22")
    store.trash_document(trashed)
    for doc_id in (scam, sent, trashed):
        assert _suggest(store, party, doc_id=doc_id) is None, doc_id
    assert _suggest(store, party) is not None


def test_an_open_contract_decision_counts_for_the_sender(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cancellation decision is worked out on read with the sender's Land; one whose dates the engine counted
    without it waits like a to-do. Decided ones (a confirmed or sent cancellation) don't."""
    party = _sender(store, kind="telecom")
    letter_from(store, party, MUNICH)
    contract = store.add_contract(name="Mobile", party_id=party.id, category="mobile", status="active")
    holiday = compute_due(HOLIDAY, without_land(HOLIDAY))
    assert holiday.warnings and holiday.warnings[0].startswith(REGION_UNKNOWN)
    decision = ContractComputation(
        cancel_by="2026-11-20", send_by="2026-11-16", next_renewal="2026-12-01", warnings=holiday.warnings
    )
    monkeypatch.setattr(Ledger, "computation", lambda self, c: decision)

    found = _suggest(store, party)
    assert found is not None and found.waiting == 1

    monkeypatch.setattr(Ledger, "decided_contracts", lambda self: {contract.id})
    found = _suggest(store, party)
    assert found is not None and found.waiting == 0


# --------------------------------------------------------------------------------------------------
# the sender's Idea: Don't know is remembered for that Land
# --------------------------------------------------------------------------------------------------


def test_idea_id_and_declined_follow_the_sender_s_idea(store: Store) -> None:
    party = _sender(store)
    to_do(store, party, letter_from(store, party, MUNICH), HOLIDAY)
    found = _suggest(store, party)
    assert found is not None and (found.idea_id, found.declined) == (None, False)

    run_and_reconcile(store, TODAY)
    found = _suggest(store, party)
    assert found is not None and (found.idea_id, found.declined) == (idea_id(party.id, "BY"), False)

    store.update_suggestion(idea_id(party.id, "BY"), status="dismissed")
    found = _suggest(store, party)
    assert found is not None and (found.idea_id, found.declined) == (idea_id(party.id, "BY"), True)

    store.update_suggestion(idea_id(party.id, "BY"), status="expired")
    found = _suggest(store, party)
    assert found is not None and (found.idea_id, found.declined) == (None, False)


def test_the_rule_is_registered_after_please_check() -> None:
    rules = list(TRIGGERS)
    assert rules.index(RULE_ID) == rules.index("please_check") + 1


def test_the_idea_asks_only_while_a_date_waits_for_the_land(store: Store) -> None:
    party = _sender(store, name="Stadt München")
    letter = letter_from(store, party, MUNICH)
    to_do(store, party, letter, QUIET)
    assert _ideas(store) == []  # asked in their details only

    waiting = to_do(store, party, letter, HOLIDAY)
    [idea] = _ideas(store)

    assert idea.fingerprint == fingerprint(RULE_ID, party.id, "BY") and idea.id == idea_id(party.id, "BY")
    assert (idea.rule_id, idea.kind, idea.source) == (RULE_ID, "deadline", "rule")
    assert idea.title == "Is Stadt München in Bavaria?"
    assert idea.body == (
        "80331 is on their letter. Their state's public holidays may change 1 of your dates with them; until "
        "you answer, Ordnung counts only nationwide holidays, so it may be a day or two early."
    )
    assert idea.action is not None
    assert (idea.action.type, idea.action.target_type, idea.action.target_id, idea.action.label) == (
        "open",
        "party",
        party.id,
        "Answer",
    )
    assert [(ref.type, ref.id) for ref in idea.refs] == [
        ("party", party.id),
        ("document", letter),
        ("item", waiting),
    ]
    item = store.get_item(waiting)
    assert item is not None and idea.due_date == item.due_date == "2026-11-20"
    assert idea.priority == "normal"  # more than 14 days away
    [soon] = _ideas(store, today=date(2026, 11, 9))
    assert soon.priority == "high" and soon.id == idea.id


def test_the_idea_says_when_a_date_may_be_late(store: Store) -> None:
    party = _sender(store, name="Stadt München")
    letter = letter_from(store, party, MUNICH)
    to_do(store, party, letter, HOLIDAY)
    early = to_do(store, party, letter, BACKWARDS)

    [idea] = _ideas(store)

    assert idea.body == (
        "80331 is on their letter. Their state's public holidays may change 2 of your dates with them; until "
        "you answer, act a working day before them."
    )
    item = store.get_item(early)
    assert item is not None and idea.due_date == item.send_by == "2026-11-09"  # the earliest day to act


def test_one_idea_per_sender(store: Store) -> None:
    munich, dresden = _sender(store, name="Stadt München"), _sender(store, name="Stadt Dresden")
    for party, address in ((munich, MUNICH), (munich, NUREMBERG), (dresden, DRESDEN)):
        letter = letter_from(
            store, party, address, day="2026-09-20" if address != NUREMBERG else "2026-09-01"
        )
        to_do(store, party, letter, HOLIDAY)
    found = {(idea.refs[0].id, idea.title) for idea in _ideas(store)}
    assert found == {(munich.id, "Is Stadt München in Bavaria?"), (dresden.id, "Is Stadt Dresden in Saxony?")}


def test_don_t_know_is_remembered_for_that_land_and_another_land_asks_again(store: Store) -> None:
    party = _sender(store)
    to_do(store, party, letter_from(store, party, MUNICH, day="2026-09-01"), HOLIDAY)
    run_and_reconcile(store, TODAY)
    store.update_suggestion(idea_id(party.id, "BY"), status="dismissed")  # "Don't know"

    same_land = letter_from(store, party, NUREMBERG, day="2026-09-25")  # a new letter
    to_do(store, party, same_land, HOLIDAY)
    run_and_reconcile(store, TODAY)
    asked = store.get_suggestion(idea_id(party.id, "BY"))
    assert asked is not None and asked.status == "dismissed"

    for letter in store.list_documents(party_id=party.id):  # the sender moved: their letters now say Saxony
        store.trash_document(letter.id)
    to_do(store, party, letter_from(store, party, DRESDEN, day="2026-09-27"), HOLIDAY)
    run_and_reconcile(store, TODAY)
    again = store.get_suggestion(idea_id(party.id, "SN"))
    asked = store.get_suggestion(idea_id(party.id, "BY"))
    assert again is not None and again.status == "new"
    assert asked is not None and asked.status == "dismissed"


def test_setting_the_land_expires_the_idea(store: Store) -> None:
    party = _sender(store)
    to_do(store, party, letter_from(store, party, MUNICH), HOLIDAY)
    run_and_reconcile(store, TODAY)

    store.update_party(party.id, region="BY")
    run_and_reconcile(store, TODAY)

    idea = store.get_suggestion(idea_id(party.id, "BY"))
    assert idea is not None and idea.status == "expired"
    assert _ideas(store) == []


def test_nothing_the_rule_or_the_suggestion_does_sets_a_land(store: Store) -> None:
    party = _sender(store)
    to_do(store, party, letter_from(store, party, MUNICH), HOLIDAY)
    ledger = Ledger(store, TODAY)
    assert sender_land_ideas(ledger) and region_suggestion(ledger, party) is not None
    run_and_reconcile(store, TODAY)
    assert (store.get_party(party.id) or party).region is None


def test_the_letters_are_read_once_per_ledger(store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    party = _sender(store)
    to_do(store, party, letter_from(store, party, MUNICH), HOLIDAY)
    calls: list[str] = []
    real = sender_land.suggest_land
    monkeypatch.setattr(sender_land, "suggest_land", lambda *a, **kw: calls.append("read") or real(*a, **kw))
    ledger = Ledger(store, TODAY)
    for _ in range(3):
        assert region_suggestion(ledger, party) is not None
    sender_land_ideas(ledger)
    assert calls == ["read"]


# --------------------------------------------------------------------------------------------------
# words, and what Ask sees
# --------------------------------------------------------------------------------------------------


def test_every_land_has_an_english_name_ordnung_reads_back() -> None:
    names = {code: land_name(code) for code in REGION_NAMES}
    assert all(normalize_region(name) == code for code, name in names.items()), names
    assert (names["BY"], names["NW"], names["BE"]) == ("Bavaria", "North Rhine-Westphalia", "Berlin")


def test_ask_never_sees_the_suggestion() -> None:
    """Ask's party fields are part of its ledger fingerprint: a computed question there would stop the recorded
    answers (the demo's, the Ask benchmark's) from replaying."""
    assert "region_suggestion" not in PARTY_FIELDS
    assert "region_suggestion" not in Party.model_fields
