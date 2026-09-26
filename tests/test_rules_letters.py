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
from ordnung.rules.advice import BillingPeriod, billing_period, billing_period_text, letter_advice
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
#: What makes the person the respondent: the order's remedy, or an objection date.
WIDERSPRUCH = Remedy(type="widerspruch", quote="Gegen den Anspruch können Sie Widerspruch erheben.")
EINSPRUCH = Remedy(type="einspruch", quote="Gegen diesen Bescheid kann Einspruch eingelegt werden.")


def objection_date(quote: str, **date_fields: Any) -> ExtractedItem:
    """A dated objection to-do (two weeks from delivery) quoting ``quote``."""
    fields: dict[str, Any] = {"type": "relative", "anchor": "receipt", "amount": 2, "unit": "weeks"}
    fields |= {"nature": "objection", **date_fields}
    return ExtractedItem(kind="deadline", title="Object", date=DateSpec(**fields), quote=quote)


def test_a_court_payment_order_is_recognised_from_a_court_sender() -> None:
    extraction = reading(title="Mahnbescheid", sender=COURT, remedy=WIDERSPRUCH)
    assert routing.classify_letter(extraction) == "court_payment_order"
    assert routing.letter_kind(extraction) == "court_payment_order"


def test_an_enforcement_order_wins_over_the_payment_order_it_mentions() -> None:
    extraction = reading(
        title="Vollstreckungsbescheid",
        summary="Enforcement order after the Mahnbescheid of 1 August.",
        sender=COURT,
        remedy=EINSPRUCH,
    )
    assert routing.classify_letter(extraction) == "enforcement_order"


def test_a_debt_collector_threatening_a_mahnbescheid_stays_a_reminder() -> None:
    extraction = reading(
        kind="dunning",
        title="Letzte Mahnung",
        sender=ExtractedParty(name="Inkasso Nord GmbH", kind="company"),
        items=[item("Andernfalls beantragen wir beim Amtsgericht einen Mahnbescheid.")],
        remedy=WIDERSPRUCH,
    )
    assert routing.classify_letter(extraction) is None
    assert routing.letter_kind(extraction) == "dunning"


BAILIFF_QUOTE = (
    "Aus dem Vollstreckungsbescheid des Amtsgerichts Hünfeld vom 01.03.2026 fordere ich Sie auf zu zahlen."
)


@pytest.mark.parametrize(
    "name",
    [
        "Gerichtsvollzieher Klein",
        "Gerichtskasse Hamm",
        # the letterhead formula of a bailiff (§ 154 GVG): named after the court they are attached to
        "Gerichtsvollzieher bei dem Amtsgericht Frankfurt am Main",
        "Obergerichtsvollzieherin Schmidt, Amtsgericht Köln",
        "Amtsgericht Hamm – Gerichtskasse",
    ],
)
def test_bailiffs_and_court_cashiers_are_not_courts(name: str) -> None:
    assert not routing.is_court(name)
    extraction = reading(
        title="Vollstreckungsbescheid",
        sender=ExtractedParty(name=name, kind="authority"),
        key_facts=[ExtractedFact(label="Titel", value="Vollstreckungsbescheid", quote=BAILIFF_QUOTE)],
        remedy=EINSPRUCH,  # even a (misread) remedy doesn't make a bailiff a court
        items=[objection_date(BAILIFF_QUOTE)],
    )
    assert routing.classify_letter(extraction) is None


def test_a_court_letter_about_something_else_keeps_its_kind() -> None:
    assert routing.classify_letter(reading(title="Ladung zum Termin", sender=COURT)) is None
    # a Widerspruch that isn't about an order (e.g. against an Arrest, § 924 ZPO) names no order
    assert routing.classify_letter(reading(title="Beschluss", sender=COURT, remedy=WIDERSPRUCH)) is None


def test_the_models_advice_prose_does_not_classify() -> None:
    extraction = reading(
        title="Schreiben",
        explanation="If you don't pay, a Mahnbescheid may follow.",
        sender=COURT,
        remedy=WIDERSPRUCH,
    )
    assert routing.classify_letter(extraction) is None


#: The warning every Mahnbescheid carries (§ 692 Abs. 1 Nr. 4 ZPO), as the official form words it.
MB_WARNING = (
    "Nach Ablauf dieser Frist kann der Antragsteller ohne Widerspruch einen Vollstreckungsbescheid "
    "erwirken und aus diesem die Zwangsvollstreckung betreiben."
)
MB_OBJECTION = "Sie können binnen zwei Wochen seit der Zustellung dieses Bescheids Widerspruch erheben."


@pytest.mark.parametrize(
    "extraction",
    [
        # the title names the order; the quote holds the statutory warning
        reading(title="Mahnbescheid", sender=COURT, items=[item(MB_WARNING)], remedy=WIDERSPRUCH),
        reading(
            title="Court payment order (Mahnbescheid)",
            summary="The claimant can apply for a Vollstreckungsbescheid after two weeks.",
            sender=COURT,
            items=[objection_date(MB_OBJECTION)],
        ),
        # an English title alone, with the order named in the letter's own words
        reading(
            title="Court payment order from the Amtsgericht",
            sender=COURT,
            items=[objection_date(MB_WARNING)],
        ),
        # no title signal: the remedy decides
        reading(title="Letter from the court", sender=COURT, items=[item(MB_WARNING)], remedy=WIDERSPRUCH),
        # … or the objection date's own wording
        reading(
            title="Letter from the court",
            summary="Mahnbescheid über 1.250,00 EUR.",
            items=[item(MB_WARNING), objection_date(MB_OBJECTION)],
            sender=COURT,
        ),
        reading(
            title="Letter from the court",
            summary="Mahnbescheid über 1.250,00 EUR.",
            items=[objection_date("binnen zwei Wochen", legal_basis="§ 692 Abs. 1 Nr. 3 ZPO")],
            sender=COURT,
        ),
    ],
)
def test_a_mahnbescheid_that_warns_of_the_enforcement_order_is_a_payment_order(
    extraction: DocumentExtraction,
) -> None:
    assert routing.classify_letter(extraction) == "court_payment_order"


@pytest.mark.parametrize(
    "extraction",
    [
        reading(
            title="Vollstreckungsbescheid",
            summary="Auf Grund des Mahnbescheids vom 01.08.2026.",
            sender=COURT,
            items=[objection_date("Einspruch binnen zwei Wochen")],
        ),
        reading(
            title="Enforcement order after the payment order",
            summary="Mahnbescheid vom 01.08.2026",
            sender=COURT,
            remedy=EINSPRUCH,
        ),
        reading(
            title="Letter from the court",
            summary="Mahnbescheid vom 01.08.2026",
            sender=COURT,
            remedy=EINSPRUCH,
        ),
        reading(
            title="Letter from the court",
            sender=COURT,
            items=[
                item("Dieser Vollstreckungsbescheid ergeht auf Grund des Mahnbescheids vom 01.08.2026."),
                objection_date("Gegen diesen Vollstreckungsbescheid kann Einspruch eingelegt werden."),
            ],
        ),
    ],
)
def test_an_enforcement_order_is_recognised_by_what_it_is(extraction: DocumentExtraction) -> None:
    assert routing.classify_letter(extraction) == "enforcement_order"


@pytest.mark.parametrize(
    "extraction",
    [
        # nothing asks the person to answer as the respondent: a notice to the claimant, a bailiff's
        # quote of the order he enforces, the court's invoice
        reading(title="Mahnbescheid", sender=COURT),
        reading(
            title="Nachricht über die Zustellung des Mahnbescheids",
            summary="The Mahnbescheid was served on the respondent on 10.09.2026.",
            sender=COURT,
            items=[item("Der Mahnbescheid wurde dem Antragsgegner am 10.09.2026 zugestellt.")],
        ),
        reading(
            title="Payment demand",
            summary="Pay 612 EUR from the Vollstreckungsbescheid of 01.03.2026.",
            sender=COURT,
            items=[
                ExtractedItem(
                    kind="payment",
                    title="Pay",
                    date=DateSpec(
                        type="relative", anchor="receipt", amount=2, unit="weeks", nature="payment"
                    ),
                    quote=BAILIFF_QUOTE,
                )
            ],
        ),
        # the remedy isn't named by the letter: neither the remedy block nor the objection date says
        reading(
            title="Letter from the court",
            summary="Mahnbescheid vom 01.08.2026",
            sender=COURT,
            items=[objection_date("binnen zwei Wochen")],
        ),
        # a Vollstreckungsbescheid named outside the Mahnbescheid's warning no longer decides
        reading(
            title="Letter from the court",
            summary="Zahlung aus dem Vollstreckungsbescheid vom 01.03.2025.",
            sender=COURT,
            items=[objection_date("binnen zwei Wochen")],
        ),
    ],
)
def test_a_court_letter_that_doesnt_make_the_person_answer_an_order_is_neither(
    extraction: DocumentExtraction,
) -> None:
    assert routing.classify_letter(extraction) is None


#: A court's later letters about an order, each with a (misread) objection date, so only their wording
#: decides: after an objection, to the claimant, and from enforcement.
FOLLOW_UPS = [
    (
        "Abgabenachricht",
        "Nach Widerspruch gegen den Mahnbescheid wird das Verfahren an das Landgericht Köln abgegeben.",
    ),
    ("Case transferred to the Landgericht", "Mahnbescheid vom 01.08.2026"),
    ("Letter from the court", "Ihr Widerspruch gegen den Mahnbescheid vom 01.08.2026 ist eingegangen."),
    (
        "Mitteilung über Widerspruch",
        "Der Antragsgegner hat gegen den Mahnbescheid vom 01.09.2026 Widerspruch erhoben.",
    ),
    ("Objection filed against the Mahnbescheid", "Mahnbescheid vom 01.09.2026"),
    ("The respondent has objected to the payment order", "Mahnbescheid vom 01.09.2026"),
    ("Mahnbescheid", "Nachricht an den Antragsteller: der Mahnbescheid wurde am 10.09.2026 zugestellt."),
    ("Mahnbescheid", "Zustellungsnachricht zum Mahnbescheid vom 01.09.2026"),
    (
        "Monierung Ihres Antrags auf Erlass eines Mahnbescheids",
        "Bitte beheben Sie die Mängel binnen eines Monats.",
    ),
    ("Kostenrechnung", "Gerichtskosten für das Mahnverfahren (Mahnbescheid) 36,00 EUR"),
    (
        "Mitteilung im Mahnverfahren",
        "Der Antrag auf Erlass des Mahnbescheids wurde vom Antragsteller zurückgenommen.",
    ),
    (
        "Pfändungs- und Überweisungsbeschluss",
        "Wegen der Forderung aus dem Vollstreckungsbescheid des AG Hagen vom 12.03.2025 wird gepfändet.",
    ),
    ("Garnishment order", "Forderung aus dem Vollstreckungsbescheid vom 12.03.2025"),
    (
        "Beschluss",
        "Die Zwangsvollstreckung aus dem Vollstreckungsbescheid vom 01.09.2026 wird einstweilen eingestellt.",
    ),
    ("Enforcement suspended", "Vollstreckungsbescheid vom 01.09.2026"),
    ("Payment order application withdrawn", "Mahnbescheid vom 01.09.2026"),
    ("Court fee invoice", "Mahnbescheid vom 01.09.2026"),
    ("Notice of service of the payment order", "Mahnbescheid vom 01.09.2026"),
]


@pytest.mark.parametrize(("title", "quote"), FOLLOW_UPS)
def test_a_courts_later_letter_about_the_order_is_neither(title: str, quote: str) -> None:
    extraction = reading(
        title=title, sender=COURT, items=[item(quote), objection_date("Widerspruch binnen zwei Wochen")]
    )
    assert routing.classify_letter(extraction) is None


def test_a_payment_order_that_explains_the_hand_over_is_still_one() -> None:
    extraction = reading(
        title="Mahnbescheid",
        sender=COURT,
        items=[
            item(MB_WARNING),
            item("Im Falle des Widerspruchs wird das Verfahren an das Amtsgericht Köln abgegeben."),
        ],
        remedy=WIDERSPRUCH,
    )
    assert routing.classify_letter(extraction) == "court_payment_order"


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
    ("quote", "summary"),
    [
        (
            "Die Miete erhöht sich zum 01.01.2027 auf 820,00 EUR.",
            "The rent rises in line with the consumer price index, as set out in your rental agreement.",
        ),
        ("Die Miete erhöht sich zum 01.01.2027 auf 820,00 EUR.", "As agreed in the lease's graduated rent."),
        (
            "Die monatliche Vorauszahlung wird ab Januar auf 250,00 EUR angepasst.",
            "The operating-cost prepayment rises after the statement. You don't need to agree.",
        ),
        (
            "Wir passen die Vorauszahlung nach § 560 Abs. 4 BGB an; Ihrer Zustimmung bedarf es nicht.",
            "Your prepayments are adjusted.",
        ),
    ],
)
def test_english_prose_never_makes_an_increase_a_consent_request(quote: str, summary: str) -> None:
    assert routing.classify_letter(_increase(quote, summary=summary)) is None


def test_consent_must_be_asked_for_in_the_letters_own_wording() -> None:
    increase = _increase(
        "Die Nettokaltmiete steigt ab 01.01.2027.", summary="Please agree to the rent increase."
    )
    assert routing.classify_letter(increase) is None
    request = _increase(
        "Wir bitten um Ihre Zustimmung zur Erhöhung der Nettokaltmiete; die Betriebskostenvorauszahlung bleibt "
        "unverändert.",
        summary="The landlord asks you to agree to a higher rent based on the local rent index (Mietspiegel).",
    )
    assert routing.classify_letter(request) == "rent_increase"


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


@pytest.mark.parametrize(
    ("sender", "kind", "title", "quote", "named"),
    [
        # a Jobcenter asking for the statement doesn't send one
        (
            "authority",
            "other",
            "Request for documents",
            "bittet Sie, Ihre Nebenkostenabrechnung 2025 einzureichen",
            False,
        ),
        # a letter that only mentions one, with no tenancy and no billing period
        ("company", "other", "Offer", "Sparen Sie bei der Nebenkostenabrechnung", False),
        # a metering company's heating statement names its billing period
        (
            "company",
            "other",
            "Ihre Abrechnung",
            "Heizkostenabrechnung für den Abrechnungszeitraum 2025",
            True,
        ),
        # a landlord's statement
        ("landlord", "other", "Letter", "anbei die Nebenkostenabrechnung", True),
    ],
)
def test_a_statement_needs_a_tenancy_or_a_billing_period(
    sender: str, kind: str, title: str, quote: str, named: bool
) -> None:
    extraction = reading(
        kind=kind, title=title, sender=ExtractedParty(name="Absender", kind=sender), items=[item(quote)]
    )
    assert routing.names_statement(extraction) is named


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


def test_extraordinary_notice() -> None:
    assert routing.extraordinary_notice(_termination(kind="rent_lease", summary="Fristlose Kündigung"))
    assert routing.extraordinary_notice(
        _termination(kind="rent_lease", items=[item("gemäß § 543 Abs. 2 BGB")])
    )
    assert not routing.extraordinary_notice(_termination(kind="rent_lease", summary="Ordentliche Kündigung"))


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
        (spec(nature="declaration", legal_basis="§ 38 Abs. 1 SGB III"), None, False, "sgb3_38"),
        (spec(nature="declaration", text="Bitte melden Sie sich arbeitsuchend."), None, True, "sgb3_38"),
        (spec(nature="declaration", text="sich arbeitsuchend zu melden"), "dismissal", False, "sgb3_38"),
        # a date that isn't a registration is never re-dated as one
        (
            DateSpec(
                type="fixed",
                date="2026-10-15",
                nature="appointment",
                text="Einladung zum Gespräch über Ihre Arbeitsuchendmeldung am 15.10.2026",
            ),
            None,
            True,
            None,
        ),
        (spec(legal_basis="§ 38 Abs. 1 SGB III"), None, False, None),  # an objection
        (
            DateSpec(
                type="fixed",
                date="2026-10-15",
                nature="declaration",
                text="Reichen Sie die Unterlagen zu Ihrer Arbeitsuchendmeldung bis 15.10.2026 ein",
            ),
            None,
            True,
            None,
        ),
        (  # an authority's own fixed date for registering stays as the authority set it
            DateSpec(type="fixed", date="2026-10-15", nature="declaration", legal_basis="§ 38 SGB III"),
            None,
            True,
            None,
        ),
        (spec(legal_basis="§ 558b BGB", nature="declaration"), None, False, "bgb_558b"),
        (spec(nature="declaration"), "rent_increase", False, "bgb_558b"),
        (spec(nature="payment"), "rent_increase", False, None),
        (  # the date the higher rent is owed from is a payment, not the consent period
            DateSpec(
                type="fixed",
                date="2026-04-01",
                nature="payment",
                text="Die erhöhte Miete ist ab dem 01.04.2026 zu zahlen (§ 558b Abs. 1 BGB)",
            ),
            None,
            False,
            None,
        ),
        (spec(legal_basis="§ 574b Abs. 2 BGB"), None, False, "bgb_574b"),
        (spec(legal_basis="§ 574b Abs. 2 BGB", nature="notice"), None, False, None),
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
        (spec(nature="appointment", text="Widerrufsbelehrung"), None, False, None),
        (  # insurance has its own withdrawal periods (14 or 30 days, § 8, § 152 VVG)
            spec(
                nature="declaration",
                amount=30,
                unit="days",
                text="Widerrufsfrist 30 Tage",
                legal_basis="§ 152 VVG",
            ),
            None,
            False,
            None,
        ),
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
    # no hardship objection to a notice without notice period (§ 574 Abs. 1 S. 2 BGB)
    assert routing.derived_deadlines("landlord_notice", end=D("2027-10-31"), extraordinary=True) == []
    assert (
        routing.derived_deadlines("landlord_notice", end=D("2026-10-31"), letter_date=D("2026-09-20")) == []
    )
    [kept] = routing.derived_deadlines("landlord_notice", end=D("2026-12-31"), letter_date=D("2026-09-20"))
    assert "first court hearing" in kept.consequence
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


@pytest.mark.parametrize("letter", ["court_payment_order", "enforcement_order"])
@pytest.mark.parametrize("legal_basis", [None, "§ 692 Abs. 1 Nr. 3 ZPO"])
def test_a_fixed_date_on_a_court_order_is_never_high(letter: str, legal_basis: str | None) -> None:
    date_spec = DateSpec(type="fixed", date="2026-10-08", nature="objection", legal_basis=legal_basis)
    receipt = compute_due(date_spec, ctx(region="NW", document_date="2026-09-21", letter_kind=letter))
    assert receipt.due_date == "2026-10-08"
    assert receipt.confidence == "medium"
    court_rule = "zpo_692" if legal_basis or letter == "court_payment_order" else "zpo_339"
    assert court_rule in receipt.rule_ids  # cited; but a fixed date wasn't computed under it:
    assert not routing.computed_under(date_spec, receipt.rule_ids, court_rule)  # the law's to-do is filed too
    assert any("court deadline" in w for w in receipt.warnings)


@pytest.mark.parametrize(
    "date_spec",
    [
        # a labour-court hearing in the court-action case
        DateSpec(
            type="fixed",
            date="2026-11-12",
            nature="appointment",
            text="Gütetermin in Sachen Kündigungsschutzklage am 12.11.2026",
        ),
        # a severance payment offered if no court action is brought (§ 1a KSchG)
        DateSpec(
            type="fixed",
            date="2026-12-31",
            nature="payment",
            text="zum 31.12.2026 eine Abfindung, wenn Sie keine Kündigungsschutzklage erheben",
        ),
        DateSpec(
            type="relative",
            anchor="receipt",
            amount=2,
            unit="weeks",
            nature="payment",
            legal_basis="§ 1a KSchG, § 4 KSchG",
            text="Abfindung zwei Wochen nach Ablauf der Klagefrist",
        ),
        # paying isn't what the enforcement order's two weeks are for
        DateSpec(type="fixed", date="2026-10-08", nature="payment", legal_basis="§ 700 ZPO"),
    ],
)
def test_a_date_that_only_mentions_a_court_rule_doesnt_follow_it(date_spec: DateSpec) -> None:
    receipt = compute_due(
        date_spec,
        ctx(region="NW", document_date="2026-09-24", received_date="2026-09-25", received_confirmed=True),
    )
    assert not {"kschg_4", "zpo_339", "zpo_692"} & set(receipt.rule_ids)
    assert not any("court" in w for w in receipt.warnings)


def test_computed_under() -> None:
    relative = spec(amount=3, legal_basis="§ 4 KSchG")
    assert routing.computed_under(relative, ["kschg_4", "bgb_193"], "kschg_4")
    assert not routing.computed_under(relative, ["bgb_193"], "kschg_4")
    fixed = DateSpec(type="fixed", date="2026-10-15", nature="declaration", text="arbeitsuchend melden")
    assert routing.computed_under(fixed, ["sgb3_38"], "sgb3_38")  # routed: the law's date was computed
    assert not routing.computed_under(
        fixed.model_copy(update={"nature": "objection"}), ["kschg_4"], "kschg_4"
    )


def test_any_date_on_a_court_order_is_never_high() -> None:
    payment = DateSpec(type="fixed", date="2026-10-08", nature="payment")
    receipt = compute_due(payment, ctx(region="NW", letter_kind="enforcement_order"))
    assert receipt.confidence == "medium" and any("court order" in w for w in receipt.warnings)
    fixed_kschg = DateSpec(type="fixed", date="2026-10-16", nature="objection", legal_basis="§ 4 KSchG")
    assert compute_due(fixed_kschg, ctx(region="NW")).confidence == "medium"


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
        spec(amount=3, unit="days", nature="declaration", text="arbeitsuchend melden"),
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


def test_registration_without_any_start_date_gives_no_date() -> None:
    receipt = compute_due(
        spec(amount=3, unit="days", nature="declaration", legal_basis="§ 38 SGB III"), ctx()
    )
    assert receipt.due_date is None and "start date is missing" in receipt.summary


def test_registration_from_the_letters_three_months_wording() -> None:
    receipt = compute_due(
        spec(
            anchor="explicit_date",
            anchor_date="2026-09-30",
            amount=-3,
            unit="months",
            nature="declaration",
            text="sich spätestens drei Monate vor Beendigung arbeitsuchend zu melden",
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

    later = compute_due(
        DateSpec(type="fixed", date="2026-04-30", nature="declaration", legal_basis="§ 558b BGB"),
        ctx(
            document_date="2026-01-12",
            received_date="2026-01-15",
            received_confirmed=True,
            today="2026-01-16",
        ),
    )
    assert later.due_date == "2026-03-31"
    assert not any("can't shorten" in w for w in later.warnings)  # the landlord gave more time
    assert any("the law's date is shown, the earlier one" in w for w in later.warnings)


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
    assert not any("574b Abs. 2 S. 2" in w for w in from_context.warnings)  # still ahead


def test_a_passed_notice_objection_says_when_the_tenant_may_still_object() -> None:
    receipt = compute_due(
        spec(),
        ctx(region="NW", document_date="2026-08-20", letter_kind="landlord_notice", end_date="2026-10-31"),
    )
    assert receipt.due_date == "2026-08-31"  # before today, 26 Sep 2026
    assert any("first hearing of an eviction suit (§ 574b Abs. 2 S. 2 BGB)" in w for w in receipt.warnings)


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


def _stated(amount: int, today: str, unit: str = "days") -> Any:
    return compute_due(
        spec(
            anchor="explicit_date",
            anchor_date="2026-09-01",
            amount=amount,
            unit=unit,
            nature="declaration",
            text=f"Widerrufsfrist {amount} Tage ab Erhalt der Ware",
        ),
        ctx(today=today, recipient_region="NW"),
    )


def test_a_longer_withdrawal_period_the_letter_grants_is_shown_and_never_lost() -> None:
    early = _stated(30, "2026-09-10")
    assert early.due_date == "2026-09-15" and early.confidence == "medium"  # the law's earlier date first
    assert any("gives you 30 days (until Thu 1 Oct 2026)" in w for w in early.warnings)
    # the 14 days are § 355 BGB's, not "the law's": life insurance has 30 days by law (§ 152 VVG)
    assert any("14 days of § 355 BGB" in w and "§ 152 VVG" in w for w in early.warnings)
    assert not any("the law sets" in w for w in early.warnings)
    after_14 = _stated(30, "2026-09-26")  # the reported case: never "passed" while the 30 days run
    assert after_14.due_date == "2026-10-01" and after_14.send_by == "2026-10-01"
    assert any("you can still withdraw until Thu 1 Oct 2026" in w for w in after_14.warnings)
    assert not any("already passed" in w for w in after_14.warnings)
    both_passed = _stated(30, "2026-10-05")
    assert both_passed.due_date == "2026-10-01" and both_passed.send_by is None
    assert any("(Thu 1 Oct 2026) has already passed" in w for w in both_passed.warnings)


def test_a_shorter_withdrawal_period_doesnt_count_against_the_consumer() -> None:
    shorter = _stated(7, "2026-09-10")
    assert shorter.due_date == "2026-09-15"
    assert any("a shorter period doesn't count against you" in w for w in shorter.warnings)
    assert _stated(2, "2026-09-01", unit="weeks").confidence == "high"  # two weeks are the 14 days
    assert _stated(0, "2026-09-01").due_date == "2026-09-15"  # nonsense periods are ignored


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
    assert any("§ 574b Abs. 2 S. 2 BGB" in step for step in notice.steps)  # a late objection may still count
    assert any("fristlos" in step and "§ 569 Abs. 3 Nr. 2 BGB" in step for step in notice.steps)
    assert notice.draft == "objection" and notice.facts == []
    statement = letter_advice("operating_costs", today=TODAY)
    assert statement is not None and statement.draft == "receipts_inspection"
    assert letter_advice("invoice", today=TODAY) is None
    assert letter_advice(None, today=TODAY) is None


def test_short_lets_and_furnished_rooms_have_neither_objection_nor_consent_procedure() -> None:
    """§ 549 Abs. 2, 3 BGB: said on both tenancy cards, the objection to-do and in the catalog."""
    notice = letter_advice("landlord_notice", today=TODAY)
    increase = letter_advice("rent_increase", today=TODAY)
    assert notice is not None and increase is not None
    assert any("furnished room" in step and "§ 549 Abs. 2 BGB" in step for step in notice.steps)
    assert any("student hall (§ 549 Abs. 3 BGB)" in step for step in increase.steps)
    assert "bgb_549" in notice.rule_ids and "bgb_549" in increase.rule_ids
    [objection] = routing.derived_deadlines("landlord_notice", end=D("2027-10-31"))
    assert "§ 549 Abs. 2 BGB" in objection.action
    assert objection.action.startswith("Your tenancy ends on Sun 31 Oct 2027.")
    assert "§ 549 Abs. 2 BGB" in catalog.get_rule("bgb_574b").summary


@pytest.mark.parametrize("alternative", [False, True])
def test_a_notice_without_notice_period_says_so_and_offers_no_useless_objection(alternative: bool) -> None:
    card = letter_advice("landlord_notice", today=TODAY, extraordinary=True, alternative=alternative)
    assert card is not None
    [fact] = card.facts
    assert fact.title.startswith("This reads as a notice without notice period") and fact.tone == "warn"
    assert "§ 574 Abs. 1 S. 2 BGB" in (fact.citation or "")
    # a hardship objection only against the notice given with a notice period in the alternative
    assert card.draft == ("objection" if alternative else None)
    assert ("hilfsweise" in fact.text) is alternative
    assert not any(step.startswith("A notice without notice period") for step in card.steps)  # not twice


def test_a_notice_hilfsweise_with_notice_period_keeps_its_objection_to_do() -> None:
    fristlos = _termination(kind="rent_lease", summary="Fristlose Kündigung wegen Zahlungsverzugs")
    both = _termination(
        kind="rent_lease",
        summary="The landlord terminates without notice, alternatively with notice to 31 Dec 2026.",
        items=[item("kündigen wir das Mietverhältnis fristlos, hilfsweise fristgerecht zum 31.12.2026")],
    )
    careful = _termination(
        kind="rent_lease", summary="Fristlose Kündigung, vorsorglich auch ordentlich zum 31.12.2026"
    )
    assert routing.extraordinary_notice(fristlos) and not routing.alternative_notice(fristlos)
    assert routing.extraordinary_notice(both) and routing.alternative_notice(both)
    assert routing.alternative_notice(careful)
    # "vorsorglich" alone (e.g. against a tacit extension, § 545 BGB) is no alternative notice
    tacit = _termination(
        kind="rent_lease", summary="Einer stillschweigenden Verlängerung widersprechen wir vorsorglich."
    )
    assert not routing.alternative_notice(tacit)


@pytest.mark.parametrize("kind", ["court_payment_order", "enforcement_order", "dismissal"])
def test_a_card_doesnt_ask_for_an_arrival_day_the_person_entered(kind: str) -> None:
    asking = letter_advice(kind, today=TODAY)
    entered = letter_advice(kind, today=TODAY, arrived=D("2026-09-24"), arrival_confirmed=True)
    assert asking is not None and entered is not None
    assert asking.steps[0].startswith(("Find the delivery date", "Enter the day"))
    assert "you entered" in entered.steps[0] and not entered.steps[0].startswith(("Find", "Enter"))


def test_the_dismissal_card_and_registration_to_do_mention_apprentices() -> None:
    card = letter_advice("dismissal", today=TODAY)
    assert card is not None
    assert any("§ 38 Abs. 1 S. 4 SGB III" in s and "§ 111 Abs. 2 ArbGG" in s for s in card.steps)
    register = next(d for d in routing.derived_deadlines("dismissal", end=None) if d.rule_id == "sgb3_38")
    assert "apprenticeship" in register.action and "§ 38 Abs. 1 S. 4 SGB III" in register.action


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
    assert billing_period(STATEMENT) == BillingPeriod(D("2024-12-31"), True, "01.01.2024 – 31.12.2024")
    assert billing_period("Abrechnungsperiode 1.7.2024 bis 30.6.2025") == BillingPeriod(
        D("2025-06-30"), True, "01.07.2024 – 30.06.2025"
    )
    assert billing_period("Abrechnungsjahr: 2024") == BillingPeriod(D("2024-12-31"), False, "2024")
    assert billing_period("Abrechnungszeitraum 01.01.2024 – 31.02.2024") is None
    assert billing_period("Abrechnungsjahr 2024/12") is None  # not a split year
    assert billing_period("nichts") is None
    assert billing_period_text(STATEMENT) == "01.01.2024 – 31.12.2024"
    assert billing_period_text("Abrechnungsjahr 2024") == "2024"
    assert billing_period_text("nichts") is None


@pytest.mark.parametrize(
    ("text", "period"),
    [
        # a heating year: the range decides, the split year gives way to it
        (
            "Abrechnungsjahr 2023/2024 (01.07.2023 bis 30.06.2024)",
            BillingPeriod(D("2024-06-30"), True, "01.07.2023 – 30.06.2024"),
        ),
        (
            "Heizkostenabrechnung Abrechnungsjahr 2024 (01.07.2024 - 30.06.2025)",
            BillingPeriod(D("2025-06-30"), True, "01.07.2024 – 30.06.2025"),
        ),
        # "vom … bis zum …" without the word Abrechnungszeitraum
        (
            "Wir rechnen die Kosten vom 01.07.2023 bis zum 30.06.2024 ab.",
            BillingPeriod(D("2024-06-30"), True, "01.07.2023 – 30.06.2024"),
        ),
        # the previous year's period is not this statement's: the later billing year wins
        (
            "Abrechnungszeitraum 2024, Vorjahr: Abrechnungszeitraum 01.01.2023 - 31.12.2023",
            BillingPeriod(D("2024-12-31"), False, "2024"),
        ),
        # a split year alone ends at the latest on 31 December of its second year
        ("Abrechnungsjahr 2023/24", BillingPeriod(D("2024-12-31"), False, "2023/24")),
        # two-digit years; a range that ends after the statement arrived is a new prepayment period
        (
            "Zeitraum 01.01.24-31.12.24; neue Vorauszahlung 01.01.2026 - 31.12.2026",
            BillingPeriod(D("2024-12-31"), True, "01.01.2024 – 31.12.2024"),
        ),
    ],
)
def test_billing_period_takes_the_latest_end_of_every_period_named(text: str, period: BillingPeriod) -> None:
    assert billing_period(text, before=D("2025-12-01")) == period


@pytest.mark.parametrize(
    ("text", "arrived", "region", "title"),
    [
        # the reported case: a heating year statement that was on time is not called late
        ("Abrechnungsjahr 2023/2024 (01.07.2023 bis 30.06.2024)", D("2025-03-10"), None, "On time"),
        (
            "Heizkostenabrechnung Abrechnungsjahr 2024 (01.07.2024 - 30.06.2025)",
            D("2026-02-10"),
            None,
            "On time",
        ),
        (
            "Abrechnungszeitraum 2024, Vorjahr: Abrechnungszeitraum 01.01.2023 - 31.12.2023",
            D("2025-02-10"),
            None,
            "Probably on time",
        ),
        # from a billing year alone a statement is never certainly late
        ("Abrechnungsjahr 2024", D("2026-01-02"), "NW", "Probably too late — check the billing period"),
        ("Abrechnungsjahr 2023/2024", D("2025-02-10"), "NW", "Probably on time"),
        # on time only because the deadline moved off a holiday (Reformation Day, Friday 31 Oct 2025)
        ("Abrechnungszeitraum 01.11.2023 - 31.10.2024", D("2025-11-03"), None, "Probably on time"),
        ("Abrechnungszeitraum 01.11.2023 - 31.10.2024", D("2025-11-03"), "NI", "Probably on time"),
        ("Abrechnungszeitraum 01.11.2023 - 31.10.2024", D("2025-10-30"), None, "On time"),
    ],
)
def test_the_statement_check_never_wrongly_says_you_dont_owe_it(
    text: str, arrived: date, region: str | None, title: str
) -> None:
    card = letter_advice(
        "operating_costs",
        today=D("2026-02-20"),
        arrived=arrived,
        arrival_confirmed=True,
        region=region,
        text=text,
    )
    assert card is not None
    [fact] = card.facts
    assert fact.title == title
    if title == "Probably on time" and "weekend or holiday" in fact.text:
        assert "disputed" in fact.text and ("any Land" in fact.text) == (region is None)
    if title.startswith("Probably too late"):
        assert "may owe no back-payment" in fact.text and fact.tone == "warn"


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


@pytest.mark.parametrize(
    "kind", ["general_reply", "extension_request", "address_change", "payment_plan", "objection"]
)
def test_nothing_goes_to_a_court_by_email(kind: str) -> None:
    guidance = send_guidance(kind, party_kind="authority", today=TODAY, court=True)  # type: ignore[arg-type]
    channels = {c.channel: c for c in guidance.channels}
    assert not channels["email"].allowed and not channels["email"].recommended
    assert channels["letter"].recommended
    # a court order's objection keeps its own channels (the form, online-mahnantrag.de)
    order = send_guidance("objection", letter_kind="court_payment_order", today=TODAY, court=True)
    assert "portal" in {c.channel for c in order.channels}


def test_another_courts_desk_is_offered_only_with_the_129a_catch() -> None:
    for letter in ("court_payment_order", "enforcement_order"):
        guidance = send_guidance("objection", letter_kind=letter, today=TODAY, due=D("2026-10-08"))
        desk = {c.channel: c for c in guidance.channels}["in_person"]
        assert "only counts once their record reaches the issuing court" in desk.note
        assert desk.citation == catalog.citation("zpo_129a") and not desk.recommended
    enforcement = send_guidance("objection", letter_kind="enforcement_order", today=TODAY)
    assert "§ 129a Abs. 3 S. 2 ZPO" in (enforcement.form_note or "")
    card = letter_advice("enforcement_order", today=TODAY)
    assert card is not None and any("record reaches the issuing court" in step for step in card.steps)
    assert "§ 129a Abs. 3 S. 2 ZPO" in card.help[0].what and "any Amtsgericht" not in card.help[0].name
    assert "zpo_129a" in card.rule_ids


def test_tenancy_objection_is_text_form_since_2025() -> None:
    guidance = send_guidance("objection", letter_kind="landlord_notice", today=TODAY)
    assert guidance.form == "text_form"
    assert {c.channel: c.allowed for c in guidance.channels}["email"] is True


def test_withdrawal_only_has_to_be_sent_in_time() -> None:
    guidance = send_guidance("withdrawal", due=D("2026-10-05"), today=TODAY)
    assert guidance.send_by == "2026-10-05" and guidance.must_arrive_by is None
    assert guidance.channels[0].channel == "email" and guidance.channels[0].recommended
    # the withdrawal button only exists for contracts made online (§ 356a BGB), not at the door
    button = {c.channel: c for c in guidance.channels}["online_button"]
    assert not button.recommended and "Not for contracts made at the door or by phone" in button.note
    late = send_guidance("withdrawal", due=D("2026-09-01"), today=TODAY)
    assert late.send_by is None and "ended on Tue 1 Sep 2026" in late.tips[0]
    assert "14 days" not in late.tips[0]  # the date may be the 12-month end, not the 14 days


def test_replies_to_a_rent_increase_and_a_statement_have_their_own_advice() -> None:
    consent = send_guidance("general_reply", letter_kind="rent_increase", today=TODAY)
    assert "no special form" in (consent.form_note or "") and "part of it" in (consent.form_note or "")
    assert any("can also count as agreeing" in tip for tip in consent.tips)
    assert consent.channels[0].citation == catalog.citation("bgb_558b")
    for guidance in (
        send_guidance("general_reply", letter_kind="operating_costs", today=TODAY),
        send_guidance("receipts_inspection", today=TODAY),
    ):
        assert any("within twelve months of receiving it" in tip for tip in guidance.tips)
    assert (
        send_guidance("general_reply", today=TODAY).form_note
        == send_guidance("general_reply", letter_kind="invoice", today=TODAY).form_note
    )


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
