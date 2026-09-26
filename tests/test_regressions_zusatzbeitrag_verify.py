"""The health-insurance special right (§ 175 Abs. 4 S. 5 SGB V): a structured rule, not sentence parsing.

Reading German sentences is the model's job. The special-right Idea for a health insurer's price
increase is raised only when the extracted change states the rate as numbers — ``unit_price_old`` and
``unit_price_new`` with one percentage each — and the new one is higher. Anything else gets no Idea: a
missed Idea is acceptable, a wrong legal claim is not (a genuine raise letter states the right itself,
which Ordnung files as the letter's own to-do). The other regimes (energy, telecoms, insurance) are
unchanged (``test_triggers.py``).
"""

from __future__ import annotations

from datetime import date

import pytest

from helpers_secretary import add_doc
from ordnung.db.store import Store
from ordnung.models import DocumentExtraction, ExtractedChange
from ordnung.secretary.triggers import contribution_rate, run_triggers, zusatzbeitrag_raised

TODAY = date(2026, 11, 20)


def _change(old: str | None, new: str | None, **fields: object) -> ExtractedChange:
    return ExtractedChange.model_validate(
        {
            "type": "price_increase",
            "effective_date": "2027-01-01",
            "unit_price_old": old,
            "unit_price_new": new,
            **fields,
        }
    )


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("2,5 %", "2,9 %"),
        ("2.5%", "2.9%"),
        ("2,50 Prozent", "2,90 Prozent"),
        ("Zusatzbeitrag 2,69 %", "Zusatzbeitrag 2,99 %"),
        ("1.7 percent", "2.5 percent"),
    ],
)
def test_a_higher_rate_stated_as_numbers_is_a_raise(old: str, new: str) -> None:
    assert zusatzbeitrag_raised(_change(old, new))


@pytest.mark.parametrize(("old", "new"), [("2,5 %", "2,5 %"), ("2,50 %", "2.5%"), ("2,9 %", "2,5 %")])
def test_an_unchanged_or_lower_rate_is_not_a_raise(old: str, new: str) -> None:
    assert not zusatzbeitrag_raised(_change(old, new))


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (None, "2,9 %"),
        ("2,5 %", None),
        (None, None),
        ("", ""),
        ("2,5", "2,9"),  # no percentage: which number is this?
        ("146,29 €", "156,55 €"),  # amounts, not rates
        ("+0,4 Prozentpunkte", "2,9 %"),
    ],
)
def test_missing_rates_are_not_a_raise(old: str | None, new: str | None) -> None:
    assert not zusatzbeitrag_raised(_change(old, new))


def test_several_percentages_are_not_read_as_one_rate() -> None:
    """Which of them is the Zusatzbeitrag is for the model to say, not for code to guess."""
    assert contribution_rate("14,6 % + 2,5 %") is None
    assert not zusatzbeitrag_raised(_change("14,6 % + 2,5 %", "14,6 % + 2,9 %"))
    assert contribution_rate("2,9 %") == 2.9


def test_the_demos_income_based_contribution_notice_opens_no_special_right() -> None:
    """The demo's Beitragsbescheid: the contribution rises because the income basis did; the change
    states amounts only (as the model read it), so no special right is claimed."""
    notice = _change(
        None,
        None,
        effective_date="2026-10-01",
        old_amount=146.29,
        new_amount=156.55,
        cost_interval="monthly",
        quote="Ab dem 01.10.2026 beträgt Ihr monatlicher Beitrag 156,55 € (bisher 146,29 €).",
    )
    assert not zusatzbeitrag_raised(notice)


# --------------------------------------------------------------------------------------------------
# the Idea
# --------------------------------------------------------------------------------------------------


def _insurer_letter(store: Store, change: ExtractedChange) -> str:
    insurer = store.add_party(name="Muster BKK", kind="health_insurer")
    store.add_contract(
        name="Muster BKK health insurance",
        category="insurance",
        party_id=insurer.id,
        start_date="2024-01-01",
        cost_amount=146.29,
        cost_interval="monthly",
    )
    extraction = DocumentExtraction(
        kind="health_insurance", title="New contribution rate", summary="s", explanation="e", change=change
    )
    return add_doc(
        store,
        "bkk",
        kind="health_insurance",
        title="New contribution rate",
        doc_date="2026-11-18",
        party_id=insurer.id,
        extraction=extraction,
    )


def test_a_stated_raise_gets_the_special_right_idea(store: Store) -> None:
    letter = _insurer_letter(store, _change("2,5 %", "2,9 %", old_amount=146.29, new_amount=152.1))
    [idea] = run_triggers(store, TODAY)["price_increase_right"]
    assert idea.title.startswith("Muster BKK raises prices")
    assert idea.action is not None and (idea.action.label, idea.action.target_id) == (
        "Compare insurers",
        letter,
    )
    assert idea.rationale is not None and "§ 175 Abs. 4" in idea.rationale


@pytest.mark.parametrize(
    "change",
    [
        _change(None, None, old_amount=146.29, new_amount=156.55, cost_interval="monthly"),
        _change("2,5 %", "2,5 %", old_amount=146.29, new_amount=156.55, cost_interval="monthly"),
    ],
)
def test_no_special_right_idea_without_a_stated_raise(store: Store, change: ExtractedChange) -> None:
    _insurer_letter(store, change)
    assert run_triggers(store, TODAY)["price_increase_right"] == []
