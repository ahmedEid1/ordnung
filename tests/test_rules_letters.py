"""High-stakes letters: classification, date routing, the letter rules, the advice card and how to send.

Each policy in :mod:`ordnung.rules.routing`, :mod:`ordnung.rules.letters`, :mod:`ordnung.rules.tenancy`,
:mod:`ordnung.rules.consumer`, :mod:`ordnung.rules.employment` and :mod:`ordnung.rules.advice` is
pinned here, including the refusal paths (no start date, a debt collector threatening a Mahnbescheid,
an authority's Widerruf, a statement whose lateness can't be known). The worked legal examples with
sources are in ``test_rules_letter_golden.py``.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from ordnung.models import (
    DateSpec,
    DocumentExtraction,
    ExtractedChange,
    ExtractedContract,
    ExtractedFact,
    ExtractedItem,
    ExtractedParty,
    Remedy,
)
from ordnung.rules import catalog, routing, send_guidance
from ordnung.rules.advice import billing_period_end, billing_period_text, letter_advice
from ordnung.rules.consumer import latest_barred_year, limitation_end, long_withdrawal_end, withdrawal_end
from ordnung.rules.deadlines import ASSUMED_RECEIPT_WARNING, RuleContext, compute_due
from ordnung.rules.employment import registration_deadline
from ordnung.rules.tenancy import (
    consent_period,
    month_end,
    notice_objection_deadline,
    rent_increase_percent,
    statement_check,
)

D = date.fromisoformat
TODAY = D("2026-09-26")


def ctx(**kw: Any) -> RuleContext:
    kw.setdefault("today", TODAY)
    for key in ("today", "document_date", "received_date", "end_date"):
        if isinstance(kw.get(key), str):
            kw[key] = D(kw[key])
    return RuleContext(**kw)


def spec(**kw: Any) -> DateSpec:
    base: dict[str, Any] = {
        "type": "relative",
        "anchor": "receipt",
        "amount": 2,
        "unit": "weeks",
        "nature": "objection",
    }
    base.update(kw)
    return DateSpec(**base)


def reading(**kw: Any) -> DocumentExtraction:
    base: dict[str, Any] = {"kind": "other", "title": "Letter", "summary": "A letter.", "explanation": ""}
    base.update(kw)
    return DocumentExtraction(**base)


def item(quote: str, **date_fields: Any) -> ExtractedItem:
    date_fields.setdefault("type", "none")
    return ExtractedItem(kind="deadline", title="To do", date=DateSpec(**date_fields), quote=quote)


# ------------------------------------------------------------------------------------ classification


COURT = ExtractedParty(name="Amtsgericht Hagen – Zentrales Mahngericht", kind="authority")


def test_a_court_payment_order_is_recognised_from_a_court_sender() -> None:
    extraction = reading(title="Mahnbescheid", sender=COURT)
    assert routing.classify_letter(extraction) == "court_payment_order"
    assert routing.letter_kind(extraction) == "court_payment_order"


def test_an_enforcement_order_wins_over_the_payment_order_it_mentions() -> None:
    extraction = reading(
        title="Vollstreckungsbescheid",
        summary="Enforcement order after the Mahnbescheid of 1 August.",
        sender=COURT,
    )
    assert routing.classify_letter(extraction) == "enforcement_order"


def test_a_debt_collector_threatening_a_mahnbescheid_stays_a_reminder() -> None:
    extraction = reading(
        kind="dunning",
        title="Letzte Mahnung",
        sender=ExtractedParty(name="Inkasso Nord GmbH", kind="company"),
        items=[item("Andernfalls beantragen wir beim Amtsgericht einen Mahnbescheid.")],
    )
    assert routing.classify_letter(extraction) is None
    assert routing.letter_kind(extraction) == "dunning"


@pytest.mark.parametrize("name", ["Gerichtsvollzieher Klein", "Gerichtskasse Hamm"])
def test_bailiffs_and_court_cashiers_are_not_courts(name: str) -> None:
    extraction = reading(title="Vollstreckungsbescheid", sender=ExtractedParty(name=name, kind="authority"))
    assert routing.classify_letter(extraction) is None


def test_a_court_letter_about_something_else_keeps_its_kind() -> None:
    assert routing.classify_letter(reading(title="Ladung zum Termin", sender=COURT)) is None


def test_the_models_advice_prose_does_not_classify() -> None:
    extraction = reading(
        title="Schreiben", explanation="If you don't pay, a Mahnbescheid may follow.", sender=COURT
    )
    assert routing.classify_letter(extraction) is None


def _termination(**kw: Any) -> DocumentExtraction:
    change = ExtractedChange(
        type="termination_by_provider", effective_date="2026-12-31", quote="kündigen wir"
    )
    return reading(change=change, **kw)


def test_a_termination_by_the_employer_is_a_dismissal() -> None:
    assert routing.classify_letter(_termination(kind="employment")) == "dismissal"
    employer = ExtractedParty(name="Café Kranz", kind="employer")
    assert routing.classify_letter(_termination(sender=employer)) == "dismissal"
    job = ExtractedContract(name="Werkstudent", category="employment")
    assert routing.classify_letter(_termination(contract=job)) == "dismissal"


def test_a_termination_by_the_landlord_is_a_landlord_notice() -> None:
    assert routing.classify_letter(_termination(kind="rent_lease")) == "landlord_notice"
    landlord = ExtractedParty(name="Wohnbau GmbH", kind="landlord")
    assert routing.classify_letter(_termination(sender=landlord)) == "landlord_notice"


def test_other_terminations_keep_their_kind() -> None:
    assert routing.classify_letter(_termination(kind="contract")) is None


def test_a_confirmation_of_your_own_notice_is_not_a_dismissal() -> None:
    change = ExtractedChange(type="cancellation_confirmation", quote="bestätigen wir Ihre Kündigung")
    assert routing.classify_letter(reading(kind="employment", change=change)) is None


def _increase(text: str, **kw: Any) -> DocumentExtraction:
    change = ExtractedChange(type="price_increase", old_amount=800.0, new_amount=880.0, quote=text)
    return reading(kind="rent_lease", change=change, **kw)


def test_a_rent_increase_that_asks_for_consent_is_recognised() -> None:
    assert (
        routing.classify_letter(_increase("Wir bitten um Ihre Zustimmung zur Mieterhöhung."))
        == "rent_increase"
    )
    assert (
        routing.classify_letter(_increase("gemäß § 558 BGB auf die ortsübliche Vergleichsmiete"))
        == "rent_increase"
    )


@pytest.mark.parametrize(
    "text",
    [
        "Die Staffelmiete erhöht sich gemäß Vertrag; Ihre Zustimmung ist nicht nötig.",
        "Anpassung der Indexmiete an den Verbraucherpreisindex (Zustimmung nicht erforderlich)",
        "Mieterhöhung nach Modernisierung gemäß § 559 BGB, Zustimmung entbehrlich",
    ],
)
def test_increases_that_need_no_consent_are_not_consent_requests(text: str) -> None:
    assert routing.classify_letter(_increase(text)) is None


def test_a_price_increase_without_a_consent_request_keeps_its_kind() -> None:
    assert routing.classify_letter(_increase("Die Miete steigt ab 1. Januar.")) is None


def test_an_operating_cost_statement_is_recognised_on_read_only() -> None:
    statement = reading(kind="utility_bill", title="Betriebs- und Heizkostenabrechnung 2025")
    assert routing.classify_letter(statement) is None  # its dates don't depend on its kind
    assert routing.names_statement(statement)
    utility = ExtractedParty(name="Stadtwerke", kind="utility")
    assert not routing.names_statement(statement.model_copy(update={"sender": utility}))
    assert not routing.names_statement(reading(title="Stromrechnung"))


def test_the_reading_text_covers_quotes_facts_remedy_and_change() -> None:
    extraction = reading(
        sender=COURT,
        key_facts=[ExtractedFact(label="Art", value="Mahnbescheid", quote="Mahnbescheid")],
        remedy=Remedy(
            type="widerspruch", quote="Widerspruch", period_text="zwei Wochen", addressee="Amtsgericht"
        ),
    )
    assert routing.classify_letter(extraction) == "court_payment_order"


def test_announced_end() -> None:
    assert routing.announced_end(_termination()) == D("2026-12-31")
    assert routing.announced_end(reading()) is None
    unknown = ExtractedChange(type="termination_by_provider", quote="x")
    assert routing.announced_end(reading(change=unknown)) is None
    garbled = ExtractedChange(type="termination_by_provider", effective_date="31.12.2026", quote="x")
    assert routing.announced_end(reading(change=garbled)) is None
    raise_ = ExtractedChange(type="price_increase", effective_date="2026-12-31", quote="x")
    assert routing.announced_end(reading(change=raise_)) is None


# ------------------------------------------------------------------------------------ date routing


def test_court_orders_give_their_relative_dates_the_court_rule() -> None:
    assert routing.kind_statute("court_payment_order", spec(nature="payment")) == "zpo_692"
    assert routing.kind_statute("enforcement_order", spec()) == "zpo_339"
    assert routing.kind_statute("enforcement_order", spec(nature="payment")) is None
    assert routing.kind_statute("court_payment_order", spec(nature="appointment")) is None
    assert routing.kind_statute("court_payment_order", DateSpec(type="fixed", date="2026-10-01")) is None
    assert routing.kind_statute("dunning", spec()) is None


@pytest.mark.parametrize(
    ("date_spec", "letter", "authority", "rule"),
    [
        (spec(legal_basis="§ 38 Abs. 1 SGB III"), None, False, "sgb3_38"),
        (spec(text="Bitte melden Sie sich arbeitsuchend."), None, True, "sgb3_38"),
        (spec(legal_basis="§ 558b BGB", nature="declaration"), None, False, "bgb_558b"),
        (spec(nature="declaration"), "rent_increase", False, "bgb_558b"),
        (spec(nature="payment"), "rent_increase", False, None),
        (spec(legal_basis="§ 574b Abs. 2 BGB"), None, False, "bgb_574b"),
        (spec(), "landlord_notice", False, "bgb_574b"),
        (spec(nature="declaration"), "landlord_notice", False, None),
        (spec(nature="declaration", legal_basis="§ 355 BGB"), None, False, "bgb_355"),
        (spec(nature="declaration", text="Die Widerrufsfrist beträgt 14 Tage."), None, False, "bgb_355"),
        (
            spec(nature="declaration", text="Widerrufsbelehrung"),
            None,
            True,
            None,
        ),  # an authority's revocation
        (spec(nature="objection", text="Widerrufsrecht"), None, False, None),
        (spec(legal_basis="§ 355 AO"), None, False, None),  # the tax objection, not a withdrawal
        (DateSpec(type="none", legal_basis="§ 38 SGB III"), None, False, None),
        (spec(), None, False, None),
    ],
)
def test_special_rules(date_spec: DateSpec, letter: str | None, authority: bool, rule: str | None) -> None:
    assert routing.special_rule(date_spec, letter, authority=authority) == rule


def test_derived_deadlines_per_kind() -> None:
    assert [d.rule_id for d in routing.derived_deadlines("court_payment_order", end=None)] == ["zpo_692"]
    assert [d.rule_id for d in routing.derived_deadlines("enforcement_order", end=None)] == ["zpo_339"]
    assert [d.rule_id for d in routing.derived_deadlines("dismissal", end=None)] == ["kschg_4", "sgb3_38"]
    assert [d.rule_id for d in routing.derived_deadlines("rent_increase", end=None)] == ["bgb_558b"]
    assert routing.derived_deadlines("landlord_notice", end=None) == []  # counts back from the end
    [notice] = routing.derived_deadlines("landlord_notice", end=D("2027-10-31"))
    assert notice.spec.anchor == "explicit_date" and notice.spec.anchor_date == "2027-10-31"
    assert routing.derived_deadlines("operating_costs", end=None) == []
    assert routing.derived_deadlines("invoice", end=None) == []
    for kind in ("court_payment_order", "enforcement_order", "dismissal", "rent_increase"):
        for derived in routing.derived_deadlines(kind, end=D("2026-12-31")):
            catalog.get_rule(derived.rule_id)
            assert derived.title and derived.action and derived.consequence


# ------------------------------------------------------------------------------------ court deadlines


def test_a_court_payment_order_counts_from_the_envelope_date() -> None:
    receipt = compute_due(
        spec(),
        ctx(
            region="NW",
            document_date="2026-09-21",
            received_date="2026-09-24",
            received_confirmed=True,
            letter_kind="court_payment_order",
        ),
    )
    assert receipt.due_date == "2026-10-08"
    assert receipt.confidence == "medium"  # a court deadline is never high
    assert {"zpo_692", "zpo_180", "zpo_222"} <= set(receipt.rule_ids)
    assert any("§ 694 ZPO" in w for w in receipt.warnings)


def test_without_the_envelope_date_the_letters_date_is_used_and_confidence_is_low() -> None:
    receipt = compute_due(
        spec(), ctx(region="NW", document_date="2026-09-21", letter_kind="court_payment_order")
    )
    assert receipt.due_date == "2026-10-05"
    assert receipt.confidence == "low"
    assert ASSUMED_RECEIPT_WARNING in receipt.warnings
    assert not any("yellow envelope" in w for w in receipt.warnings)  # asked once, not twice


def test_a_court_order_read_as_deemed_delivery_still_runs_from_formal_service() -> None:
    receipt = compute_due(
        spec(anchor="deemed_delivery", delivery_rule="de_admin_post"),
        ctx(
            region="NW", document_date="2026-09-21", delivery_scope="vwvfg", letter_kind="court_payment_order"
        ),
    )
    assert receipt.due_date == "2026-10-05"  # no 4-day fiction for court orders
    assert any("yellow envelope" in w and "§ 180 ZPO" in w for w in receipt.warnings)


def test_a_stated_delivery_day_needs_no_envelope_warning() -> None:
    receipt = compute_due(
        spec(anchor="explicit_date", anchor_date="2026-09-24", legal_basis="§ 339 ZPO"),
        ctx(region="BE", document_date="2026-09-21"),
    )
    assert receipt.due_date == "2026-10-08"
    assert not any("yellow envelope" in w for w in receipt.warnings)
    assert any("Notfrist" in w for w in receipt.warnings)


def test_a_court_period_the_letter_misstates_uses_the_earlier_statutory_one() -> None:
    receipt = compute_due(
        spec(amount=1, unit="months"),
        ctx(
            region="NW",
            document_date="2026-09-21",
            received_date="2026-09-24",
            received_confirmed=True,
            letter_kind="enforcement_order",
        ),
    )
    assert receipt.due_date == "2026-10-08"
    assert receipt.confidence == "low"  # court note + misread period


def test_the_dismissal_court_action_moves_off_a_holiday_and_is_never_high() -> None:
    receipt = compute_due(
        spec(amount=3, legal_basis="§ 4 KSchG"),
        ctx(region="BE", document_date="2026-12-10", received_date="2026-12-11", received_confirmed=True),
    )
    assert receipt.due_date == "2027-01-04"
    assert receipt.confidence == "medium"
    assert "kschg_4" in receipt.rule_ids and "bgb_193" in receipt.rule_ids


# ------------------------------------------------------------------------------------ registration


def test_registration_three_months_before_the_end() -> None:
    assert registration_deadline(D("2026-05-02"), D("2026-09-30")) == (D("2026-06-30"), "before_end")
    assert registration_deadline(D("2026-06-30"), D("2026-09-30")) == (D("2026-06-30"), "before_end")
    assert registration_deadline(D("2026-07-01"), D("2026-09-30")) == (D("2026-07-04"), "after_learning")
    assert registration_deadline(D("2026-07-01"), None) == (D("2026-07-04"), "after_learning")


def test_registration_receipts() -> None:
    long_ahead = compute_due(
        spec(amount=3, unit="days", nature="declaration", legal_basis="§ 38 SGB III"),
        ctx(
            document_date="2026-06-12",
            received_date="2026-06-15",
            received_confirmed=True,
            end_date="2026-12-31",
        ),
    )
    assert long_ahead.due_date == "2026-09-30" and long_ahead.send_by is None
    assert long_ahead.confidence == "high"
    assert "three months before" in long_ahead.summary

    no_end = compute_due(
        spec(amount=3, unit="days", nature="declaration", text="arbeitsuchend"),
        ctx(document_date="2026-09-24", received_date="2026-09-25", received_confirmed=True),
    )
    assert no_end.due_date == "2026-09-28" and no_end.confidence == "medium"
    assert any("don't know when the job ends" in w for w in no_end.warnings)

    weekend = compute_due(
        spec(amount=3, unit="days", nature="declaration", legal_basis="§ 38 SGB III"),
        ctx(
            document_date="2026-09-30",
            received_date="2026-10-01",
            received_confirmed=True,
            end_date="2026-11-30",
        ),
    )
    assert weekend.due_date == "2026-10-04"
    assert any("§ 26 Abs. 3 SGB X" in w for w in weekend.warnings)


def test_registration_from_the_letters_three_months_wording() -> None:
    receipt = compute_due(
        spec(
            anchor="explicit_date",
            anchor_date="2026-09-30",
            amount=-3,
            unit="months",
            nature="declaration",
            text="arbeitsuchend",
        ),
        ctx(document_date="2026-05-01", received_date="2026-05-02", received_confirmed=True),
    )
    assert receipt.due_date == "2026-06-30"


def test_registration_uses_an_earlier_date_the_letter_names() -> None:
    receipt = compute_due(
        DateSpec(type="fixed", date="2026-09-27", nature="declaration", legal_basis="§ 38 SGB III"),
        ctx(
            document_date="2026-09-24",
            received_date="2026-09-25",
            received_confirmed=True,
            end_date="2026-12-31",
        ),
    )
    assert receipt.due_date == "2026-09-27"
    assert any("earlier than the law's date" in w for w in receipt.warnings)


def test_registration_without_any_start_gives_no_date() -> None:
    receipt = compute_due(spec(amount=3, unit="days", nature="declaration", text="arbeitsuchend"), ctx())
    assert receipt.due_date is None and receipt.confidence == "low"


# ------------------------------------------------------------------------------------ tenancy


def test_consent_period_and_month_end() -> None:
    assert consent_period(D("2026-01-15")) == (D("2026-03-31"), D("2026-04-01"))
    assert consent_period(D("2026-12-31")) == (D("2027-02-28"), D("2027-03-01"))
    assert month_end(D("2028-02-10")) == D("2028-02-29")


def test_consent_receipts() -> None:
    receipt = compute_due(
        spec(amount=2, unit="months", nature="declaration"),
        ctx(
            region="HH",
            document_date="2026-01-12",
            received_date="2026-01-15",
            received_confirmed=True,
            letter_kind="rent_increase",
            today="2026-01-16",
        ),
    )
    assert receipt.due_date == "2026-03-31" and receipt.send_by == "2026-03-25"
    assert "higher rent is owed from Wed 1 Apr 2026" in receipt.summary

    earlier = compute_due(
        DateSpec(type="fixed", date="2026-02-28", nature="declaration", legal_basis="§ 558b BGB"),
        ctx(
            document_date="2026-01-12",
            received_date="2026-01-15",
            received_confirmed=True,
            today="2026-01-16",
        ),
    )
    assert earlier.due_date == "2026-03-31"  # a landlord can't shorten it
    assert any("can't shorten" in w for w in earlier.warnings)
    assert earlier.confidence == "high"  # nationwide 31 Mar is no regional holiday


def test_consent_without_region_flags_regional_holidays() -> None:
    receipt = compute_due(
        spec(amount=2, unit="months", nature="declaration", legal_basis="§ 558b BGB"),
        ctx(
            document_date="2025-08-27",
            received_date="2025-08-29",
            received_confirmed=True,
            today="2025-09-01",
        ),
    )
    assert receipt.due_date == "2025-10-31"  # nationwide: Fri 31 Oct stays
    assert receipt.confidence == "medium"


def test_consent_without_a_date_gives_no_date() -> None:
    receipt = compute_due(
        spec(amount=2, unit="months", nature="declaration", legal_basis="§ 558b BGB"), ctx()
    )
    assert receipt.due_date is None


def test_notice_objection_deadline() -> None:
    assert notice_objection_deadline(D("2027-10-31")) == D("2027-08-31")
    assert notice_objection_deadline(D("2027-04-30")) == D("2027-02-28")


def test_notice_objection_receipts() -> None:
    from_context = compute_due(
        spec(),
        ctx(region="NW", document_date="2026-09-20", letter_kind="landlord_notice", end_date="2027-04-30"),
    )
    assert from_context.due_date == "2027-02-28" and from_context.safe_date == "2027-02-26"
    assert "bgb_574b" in from_context.rule_ids and "backward_no_shift" in from_context.rule_ids

    earlier = compute_due(
        DateSpec(type="fixed", date="2027-08-15", nature="objection", legal_basis="§ 574b BGB"),
        ctx(region="NW", document_date="2026-09-20", end_date="2027-10-31"),
    )
    assert earlier.due_date == "2027-08-15"
    assert any("we show the earlier" in w for w in earlier.warnings)

    as_written = compute_due(
        DateSpec(type="fixed", date="2027-08-31", nature="objection", legal_basis="§ 574b BGB"),
        ctx(region="NW", document_date="2026-09-20"),
    )
    assert as_written.due_date == "2027-08-31" and as_written.confidence == "medium"

    unknown = compute_due(spec(legal_basis="§ 574b BGB"), ctx(document_date="2026-09-20"))
    assert unknown.due_date is None and "tenancy ends" in unknown.summary


def test_rent_increase_percent() -> None:
    assert rent_increase_percent(800, 880) == 10.0
    assert rent_increase_percent(0, 880) is None
    assert rent_increase_percent(800, 0) is None


def test_statement_check_policies() -> None:
    late = statement_check(D("2024-12-31"), D("2026-01-02"), confirmed=True, region="NW")
    assert late.late is True and late.deadline == D("2025-12-31")
    on_time = statement_check(D("2024-12-31"), D("2025-12-30"), confirmed=True, region="NW")
    assert on_time.late is False
    unknown = statement_check(D("2024-12-31"), D("2025-12-30"), confirmed=False)
    assert unknown.late is None
    certain = statement_check(D("2024-12-31"), D("2026-01-05"), confirmed=False)
    assert certain.late is True  # dated after the deadline, so it arrived after it too
    # 28 Feb period end: the later reading, the end of February
    assert statement_check(D("2023-02-28"), D("2024-01-10"), confirmed=True).deadline == D("2024-02-29")
    # Reformation Day: with a known Land without the holiday, the deadline stays on Friday
    assert statement_check(D("2024-10-31"), D("2025-11-03"), confirmed=True, region="NW").late is True
    assert statement_check(D("2024-10-31"), D("2025-11-03"), confirmed=True, region="NI").late is False


# ------------------------------------------------------------------------------------ consumer


def test_withdrawal_period_helpers() -> None:
    assert withdrawal_end(D("2026-09-12")) == D("2026-09-26")
    assert long_withdrawal_end(D("2025-03-01")) == (D("2026-03-15"), False)
    assert long_withdrawal_end(D("2024-02-16")) == (D("2025-03-01"), True)
    assert limitation_end(D("2022-06-15")) == D("2025-12-31")
    assert latest_barred_year(D("2026-09-26")) == 2022


def test_withdrawal_receipts() -> None:
    doorstep = compute_due(
        spec(anchor="document_date", amount=14, unit="days", nature="declaration", legal_basis="§ 355 BGB"),
        ctx(document_date="2026-09-12", today="2026-09-12"),
    )
    assert doorstep.due_date == "2026-09-28" and doorstep.send_by == "2026-09-28"
    assert any("For goods" in w for w in doorstep.warnings)

    goods = compute_due(
        spec(amount=14, unit="days", nature="declaration", text="Widerrufsfrist"),
        ctx(
            document_date="2026-12-10",
            received_date="2026-12-16",
            received_confirmed=True,
            today="2026-12-17",
            recipient_region="BY",
        ),
    )
    assert goods.due_date == "2026-12-30"
    assert not any("For goods" in w for w in goods.warnings)

    passed = compute_due(
        spec(
            anchor="explicit_date",
            anchor_date="2026-08-01",
            amount=14,
            unit="days",
            nature="declaration",
            legal_basis="§ 355 BGB",
        ),
        ctx(),
    )
    assert passed.send_by is None and any("12 months and 14 days" in w for w in passed.warnings)

    fixed = compute_due(
        DateSpec(type="fixed", date="2026-10-10", nature="declaration", legal_basis="§ 356 BGB"), ctx()
    )
    assert fixed.due_date == "2026-10-12"  # Saturday → Monday

    missing = compute_due(DateSpec(type="fixed", nature="declaration", legal_basis="§ 355 BGB"), ctx())
    assert missing.due_date is None


# ------------------------------------------------------------------------------------ advice card


def test_advice_cards_for_court_orders_and_dismissals_are_urgent_with_public_help() -> None:
    for kind in ("court_payment_order", "enforcement_order", "dismissal"):
        card = letter_advice(kind, today=TODAY)
        assert card is not None and card.urgent
        assert card.help and all(link.url and link.url.startswith("https://") for link in card.help)
        for rule_id in card.rule_ids:
            catalog.get_rule(rule_id)
    court = letter_advice("court_payment_order", today=TODAY)
    assert court is not None
    assert "Rechtsantragstelle" in court.help[0].name
    [time_bar] = court.facts
    assert "2022 or earlier may be time-barred" in time_bar.text  # "may", never "is"
    assert " is time-barred" not in time_bar.text
    dismissal = letter_advice("dismissal", today=TODAY)
    assert dismissal is not None and any("union" in link.name.lower() for link in dismissal.help)


def test_tenancy_cards_are_information() -> None:
    notice = letter_advice("landlord_notice", today=TODAY)
    assert notice is not None and not notice.urgent and notice.help[0].name.startswith("Mieterverein")
    assert letter_advice("invoice", today=TODAY) is None
    assert letter_advice(None, today=TODAY) is None


@pytest.mark.parametrize(
    ("old", "new", "tone", "words"),
    [
        (800.0, 1000.0, "warn", "more than the 20 % cap"),
        (800.0, 940.0, "warn", "15 % cap that many cities have"),
        (800.0, 880.0, "good", "within both caps"),
        (None, None, "info", "couldn't read the old and new rent"),
    ],
)
def test_rent_cap_fact(old: float | None, new: float | None, tone: str, words: str) -> None:
    card = letter_advice("rent_increase", today=TODAY, old_amount=old, new_amount=new)
    assert card is not None
    [fact] = card.facts
    assert fact.tone == tone and words in fact.text
    assert fact.citation == catalog.citation("bgb_558_3")


STATEMENT = "Betriebskostenabrechnung\nAbrechnungszeitraum: 01.01.2024 - 31.12.2024\nNachzahlung 120,00 EUR"


@pytest.mark.parametrize(
    ("arrived", "confirmed", "title", "tone"),
    [
        (D("2026-01-02"), True, "This statement came too late", "warn"),
        (D("2025-12-20"), False, "Probably on time", "info"),
        (D("2025-12-20"), True, "On time", "good"),
    ],
)
def test_statement_fact(arrived: date, confirmed: bool, title: str, tone: str) -> None:
    card = letter_advice(
        "operating_costs",
        today=TODAY,
        arrived=arrived,
        arrival_confirmed=confirmed,
        region="NW",
        text=STATEMENT,
    )
    assert card is not None
    [fact] = card.facts
    assert fact.title == title and fact.tone == tone
    if fact.tone == "warn":
        assert "probably owe no back-payment" in fact.text and "unless" in fact.text


def test_statement_fact_without_a_period_claims_nothing() -> None:
    card = letter_advice("operating_costs", today=TODAY, arrived=D("2026-01-02"), text="Abrechnung")
    assert card is not None and card.facts[0].title == "Was it on time?"


def test_billing_period() -> None:
    assert billing_period_end(STATEMENT) == D("2024-12-31")
    assert billing_period_end("Abrechnungsperiode 1.7.2024 bis 30.6.2025") == D("2025-06-30")
    assert billing_period_end("Abrechnungsjahr: 2024") == D("2024-12-31")
    assert billing_period_end("Abrechnungszeitraum 01.01.2024 – 31.02.2024") is None
    assert billing_period_end("nichts") is None
    assert billing_period_text(STATEMENT) == "01.01.2024 – 31.12.2024"
    assert billing_period_text("Abrechnungsjahr 2024") is None


# ------------------------------------------------------------------------------------ how to send


def test_court_objections_never_by_email() -> None:
    order = send_guidance("objection", letter_kind="court_payment_order", today=TODAY)
    channels = {c.channel: c for c in order.channels}
    assert order.form == "written_form"
    assert not channels["email"].allowed and channels["portal"].label == "online-mahnantrag.de"
    assert channels["registered_letter"].recommended
    enforcement = send_guidance("objection", letter_kind="enforcement_order", today=TODAY)
    assert "portal" not in {c.channel for c in enforcement.channels}
    assert any("doesn't stop enforcement" in tip for tip in enforcement.tips)


def test_tenancy_objection_is_text_form_since_2025() -> None:
    guidance = send_guidance("objection", letter_kind="landlord_notice", today=TODAY)
    assert guidance.form == "text_form"
    assert {c.channel: c.allowed for c in guidance.channels}["email"] is True


def test_withdrawal_only_has_to_be_sent_in_time() -> None:
    guidance = send_guidance("withdrawal", due=D("2026-10-05"), today=TODAY)
    assert guidance.send_by == "2026-10-05" and guidance.must_arrive_by is None
    assert guidance.channels[0].channel == "online_button" and guidance.channels[0].recommended
    late = send_guidance("withdrawal", due=D("2026-09-01"), today=TODAY)
    assert late.send_by is None and "ended on" in late.tips[0]


@pytest.mark.parametrize(
    "kind",
    [
        "extension_request",
        "payment_plan",
        "defect_notice",
        "data_access",
        "receipts_inspection",
        "deposit_return",
        "address_change",
    ],
)
def test_every_template_letter_has_sending_advice(kind: str) -> None:
    guidance = send_guidance(kind, today=TODAY, due=D("2026-10-30"))  # type: ignore[arg-type]
    assert guidance.channels and guidance.form == "any"
    assert guidance.send_by is not None


def test_template_specific_tips() -> None:
    assert any(
        "only counts once they confirm" in t for t in send_guidance("extension_request", today=TODAY).tips
    )
    assert any("one month" in t for t in send_guidance("data_access", today=TODAY).tips)
    tax = send_guidance("payment_plan", party_kind="tax_office", today=TODAY)
    assert tax.channels[0].label.startswith("ELSTER")
    assert "full amount stays due" in (send_guidance("payment_plan", today=TODAY).form_note or "")
    assert "§ 536c BGB" in (send_guidance("defect_notice", today=TODAY).form_note or "")
