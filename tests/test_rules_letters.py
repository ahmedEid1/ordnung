"""High-stakes letters: classification, date routing, the letter rules, the advice card and how to send.

Each policy in :mod:`ordnung.rules.routing`, :mod:`ordnung.rules.letters`, :mod:`ordnung.rules.tenancy`,
:mod:`ordnung.rules.consumer`, :mod:`ordnung.rules.employment` and :mod:`ordnung.rules.advice` is
pinned here, including the refusal paths (no start date, a debt collector threatening a Mahnbescheid,
an authority's Widerruf, a statement whose lateness can't be known). The worked legal examples with
sources are in ``test_rules_letter_golden.py``.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from typing import Any

import pytest

from ordnung.models import (
    ComputationReceipt,
    DateSpec,
    DocumentExtraction,
    ExtractedChange,
    ExtractedContract,
    ExtractedFact,
    ExtractedItem,
    ExtractedParty,
    Item,
    LetterAdvice,
    Recurrence,
    Remedy,
)
from ordnung.rules import catalog, routing, send_guidance
from ordnung.rules.advice import (
    HARDSHIP_EXCLUDED,
    BillingPeriod,
    billing_period,
    billing_period_text,
    letter_advice,
    settles,
    statement_arrival,
    statement_date,
    statement_late,
)
from ordnung.rules.consumer import latest_barred_year, limitation_end, long_withdrawal_end, withdrawal_end
from ordnung.rules.deadlines import (
    ASSUMED_DELIVERY_WARNING,
    ASSUMED_RECEIPT_WARNING,
    NEEDS_DELIVERY_WARNING,
    RuleContext,
    compute_due,
)
from ordnung.rules.employment import registration_deadline
from ordnung.rules.explain import fmt_date
from ordnung.rules.letters import LATE_NOTICE_OBJECTION, NEXT_END_WARNING
from ordnung.rules.tenancy import (
    consent_period,
    month_end,
    next_permissible_end,
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


@pytest.mark.parametrize(
    ("title", "period"),
    [
        ("European order for payment (Europäischer Zahlungsbefehl)", "binnen 30 Tagen (Art. 16 EuMahnVO)"),
        ("Europäischer Zahlungsbefehl", "innerhalb von 30 Tagen"),
        ("Order for payment", "30 Tage, Verordnung (EG) Nr. 1896/2006"),
    ],
)
def test_a_european_order_for_payment_is_no_mahnbescheid(title: str, period: str) -> None:
    """Review round 4 of phase 2: a European order for payment was filed as a Mahnbescheid — two weeks, a
    Widerspruch, an enforcement order after it. It gives 30 days for an Einspruch at the issuing court (Art. 16
    Abs. 2 VO (EG) 1896/2006), has no Vollstreckungsbescheid, and a late Einspruch needs a review (Art. 20): it
    keeps the model's kind, dated as a court's letter."""
    court = ExtractedParty(name="Amtsgericht Wedding", kind="authority")
    remedy = Remedy(type="einspruch", quote="Einspruch", period_text=period)
    assert routing.classify_letter(reading(title=title, sender=court, remedy=remedy)) is None


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


@pytest.mark.parametrize(
    "name",
    [
        "Amtsgericht Kassel",
        "Landgericht Kassel",
        "Arbeitsgericht Kassel",
        "ArbG Kassel",
        "Sozialgericht Kassel",
        "SG Kassel",
        "Bundessozialgericht, Kassel",
        "Hessischer Verwaltungsgerichtshof Kassel",
        "Amtsgericht Kassel – Mahnabteilung, Kasseler Straße 1",
    ],
)
def test_a_court_in_kassel_is_a_court(name: str) -> None:
    """Review round 2 of phase 2: the court-cashier exclusion matched the place name "Kassel", so every
    court there was an ordinary authority (a labour court's one-week Notfrist came out one week late)."""
    assert routing.is_court(name, "authority")
    assert routing.may_be_court(name)
    extraction = reading(
        title="Vollstreckungsbescheid",
        sender=ExtractedParty(name=name, kind="authority"),
        remedy=EINSPRUCH,
    )
    assert routing.classify_letter(extraction) == "enforcement_order"


@pytest.mark.parametrize(
    "name", ["Landesjustizkasse Bamberg", "Kasse des Amtsgerichts Kassel", "Justizkassen Hessen"]
)
def test_a_court_cashier_in_any_place_is_no_court(name: str) -> None:
    assert not routing.is_court(name, "authority")
    assert not routing.may_be_court(name)


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


#: A court's later letters about an order: after an objection, to the claimant, and from enforcement.
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
    """They state no remedy of the person's and give no objection date: nothing asks the person to answer
    the order as the respondent (policy 1 (b)), whatever their wording says about it."""
    extraction = reading(title=title, sender=COURT, items=[item(quote)], key_facts=[_fact(quote)])
    assert routing.classify_letter(extraction) is None


def _fact(quote: str) -> ExtractedFact:
    return ExtractedFact(label="Note", value="x", quote=quote)


def test_a_later_letter_read_with_an_objection_date_and_the_order_in_its_title_is_filed_as_the_order() -> (
    None
):
    """The documented limitation of the short policy (no list of exceptions): a later letter whose reading
    gives the person an objection date anyway, and whose title names the order, is filed as that order —
    the safe side for a Notfrist; the person can change the kind on the letter's page."""
    misread = reading(
        title="Objection filed against the Mahnbescheid",
        sender=COURT,
        items=[objection_date("Widerspruch binnen zwei Wochen")],
    )
    assert routing.classify_letter(misread) == "court_payment_order"
    # without the order in its title, the order some sentence names doesn't make it one
    untitled = reading(
        title="Abgabenachricht",
        sender=COURT,
        items=[item(FOLLOW_UPS[0][1]), objection_date("binnen zwei Wochen")],
    )
    assert routing.classify_letter(untitled) is None


EINSPRUCH_QUOTE = (
    "Gegen diesen Vollstreckungsbescheid können Sie binnen zwei Wochen ab Zustellung Einspruch einlegen."
)


@pytest.mark.parametrize(
    ("title", "quote"),
    [
        ("Enforcement order (Vollstreckungsbescheid)", None),
        ("Enforcement order: you have not objected to the payment order", None),
        ("Enforcement order after the payment order was served on you", None),
        ("Vollstreckungsbescheid – the claim was transferred to Inkasso Nord", None),
        ("Enforcement order (Vollstreckungsbescheid)", "Die Kostenrechnung ist beigefügt."),
        ("Enforcement order (Vollstreckungsbescheid)", "Ihr Antrag auf Ratenzahlung wurde weitergeleitet."),
    ],
)
def test_a_genuine_enforcement_order_is_never_vetoed_by_what_else_it_says(
    title: str, quote: str | None
) -> None:
    """Review round 4: words a court's later letter may use (objected, served, transferred, costs, "Ihr
    Antrag") no longer hide a genuine Vollstreckungsbescheid and its Notfrist."""
    extraction = reading(
        title=title,
        summary="The court issued an enforcement order for 612 EUR claimed by Inkasso Nord.",
        sender=ExtractedParty(name="Amtsgericht Hagen", kind="authority"),
        items=[objection_date(EINSPRUCH_QUOTE)],
        key_facts=[_fact(quote)] if quote else [],
        remedy=Remedy(type="einspruch", addressee="Amtsgericht Hagen", quote=EINSPRUCH_QUOTE),
    )
    assert routing.classify_letter(extraction) == "enforcement_order"


@pytest.mark.parametrize(
    "name",
    [
        "Amtsgericht Hagen",
        "Geschäftsstelle des Amtsgerichts Hagen",
        "AG Hagen",
        "Geschäftsstelle des AG Hagen",
        "Zentrales Mahngericht Berlin-Brandenburg",
        "Landgericht Köln",
        "Kammergericht",
        "Sozialgericht Berlin",
        "Verwaltungsgerichtshof Baden-Württemberg",
        "Bundesgerichtshof",
    ],
)
def test_courts_are_recognised_by_their_kind_in_any_case_or_abbreviated(name: str) -> None:
    assert routing.is_court(name, "authority") and not routing.is_labour_court(name, "authority")
    # a name of unknown kind (a recipient typed in) is a court by its full name only
    assert routing.is_court(name) is (" AG " not in f" {name} ")


@pytest.mark.parametrize(
    "name",
    [
        # a word ending in "gericht" is a dish, not a court
        "Lieblingsgericht GmbH",
        "Leibgericht Catering",
        "Fertiggericht Express",
        # a company's "AG", and abbreviations that are also clubs or collecting societies
        "Allianz AG",
        "Allianz AG Hamburg",
        "Allianz Versicherungs-AG, Berlin",
        "VG Wort",
        "SG Dynamo Dresden",
        "BAG Wohnungslosenhilfe e.V.",
    ],
)
def test_business_names_are_not_courts(name: str) -> None:
    assert not routing.is_court(name)
    for kind in ("company", "gym", "retailer"):  # an abbreviation counts only from an authority (or other)
        assert not routing.is_court(name, kind)


@pytest.mark.parametrize(
    ("name", "labour"),
    [
        ("SG Berlin", False),
        ("VG Minden", False),
        ("Geschäftsstelle des VG Berlin", False),
        ("BGH", False),
        ("BSG, 1. Senat", False),
        ("BVerwG Leipzig", False),
        ("BAG", True),
        ("Bundesverfassungsgericht", False),
        ("Verfassungsgerichtshof des Landes Berlin", False),
        ("Staatsgerichtshof des Landes Hessen", False),
    ],
)
def test_social_administrative_federal_and_constitutional_courts_are_courts(name: str, labour: bool) -> None:
    """Review round 1: "SG Berlin" and "VG Minden" read as authorities got the VwVfG delivery fiction and a
    later date than the court's own (a Gerichtsbescheid served on 15 Sep: 15 Oct, not 19 Oct)."""
    assert routing.is_court(name, "authority") and routing.is_court(name, "other")
    assert routing.is_labour_court(name, "authority") is labour
    spec = DateSpec(
        type="relative",
        anchor="deemed_delivery",
        amount=1,
        unit="months",
        delivery_rule="de_admin_post",
        nature="objection",
        text="Berufung innerhalb eines Monats nach Zustellung",
    )
    ctx = RuleContext(
        today=date(2026, 9, 20),
        document_date=date(2026, 9, 14),
        delivery_scope="vwvfg",
        sender_kind="authority",
        court=routing.is_court(name, "authority"),
    )
    receipt = compute_due(spec, ctx)
    assert receipt.due_date == "2026-10-14" and receipt.confidence != "high"
    assert "posting_day" not in receipt.rule_ids and "zpo_180" in receipt.rule_ids


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


@pytest.mark.parametrize(
    "quote",
    [
        "Der Antragsgegner hat gegen den Mahnbescheid keinen Widerspruch erhoben.",
        "Der Antragsgegner hat nicht rechtzeitig Widerspruch erhoben.",
        "Da der Antragsgegner keinen Widerspruch erhoben hat, ergeht dieser Vollstreckungsbescheid.",
    ],
)
def test_an_enforcement_order_that_says_why_it_was_issued_is_one(quote: str) -> None:
    """Why a Vollstreckungsbescheid is issued — no objection was raised — is not a notice that the other
    side objected (a letter to the claimant)."""
    extraction = reading(
        title="Enforcement order (Vollstreckungsbescheid)",
        sender=COURT,
        remedy=EINSPRUCH,
        key_facts=[ExtractedFact(label="Grund", value="kein Widerspruch", quote=quote)],
    )
    assert routing.classify_letter(extraction) == "enforcement_order"


LABOUR_COURT = ExtractedParty(name="Arbeitsgericht Berlin", kind="authority")


def test_a_labour_court_is_a_court_whose_orders_give_one_week() -> None:
    assert routing.is_labour_court("Arbeitsgericht Berlin") and routing.is_court("Arbeitsgericht Berlin")
    assert routing.is_labour_court("Landesarbeitsgericht Hamm")
    for name in ("Geschäftsstelle des Arbeitsgerichts Berlin", "ArbG Berlin", "LAG Hamm"):
        assert routing.is_court(name, "authority") and routing.is_labour_court(name, "authority")
    assert not routing.is_labour_court("Amtsgericht Hagen – Zentrales Mahngericht")
    assert not routing.is_labour_court("Gerichtsvollzieher beim Arbeitsgericht Berlin")
    order = reading(title="Mahnbescheid", sender=LABOUR_COURT, remedy=WIDERSPRUCH)
    assert routing.classify_letter(order) == "court_payment_order"


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
    ("quote", "title"),
    [
        (
            "Bitte stimmen Sie der Erhöhung der Nettokaltmiete auf 780 € ab dem 01.12.2026 zu. Die "
            "Betriebskostenvorauszahlung wird nicht erhöht.",
            "Mieterhöhungsverlangen",
        ),
        (
            "Bitte stimmen Sie der Erhöhung der Nettokaltmiete auf 780 € ab dem 01.12.2026 zu.",
            "Rent increase request and adjustment of operating-cost prepayments",
        ),
        (
            "Hiermit verlangen wir Ihre Zustimmung zur Erhöhung der Nettokaltmiete auf 780 €; die Vorauszahlungen "
            "werden angepasst.",
            "Mieterhöhung",
        ),
        ("Wir bitten Sie, Ihre Zustimmung zu erteilen; die Vorauszahlung wird erhöht.", "Mieterhöhung"),
        ("Ihre Zustimmung zur Mieterhöhung; die Vorauszahlung wird auf 250 € erhöht.", "Mieterhöhung"),
        # the increase's own quote asks for consent, whatever statute it names: a § 559 increase never asks
        ("Die Miete steigt nach § 559 BGB; bitte stimmen Sie der Vergleichsmiete zu.", "Rent increase"),
    ],
)
def test_the_usual_ways_of_asking_for_consent_make_a_rent_increase_request(quote: str, title: str) -> None:
    """Review round 4 of phase 2: "Bitte stimmen Sie … zu" and "verlangen wir Ihre Zustimmung" were not read as
    asking for consent, and "die Vorauszahlung wird nicht erhöht" read as a prepayment increase — the letter
    was not filed as a § 558 request, and its new rent looked like a plain payment."""
    facts = [ExtractedFact(label="Mietspiegel", value="Mietspiegel 2025", quote="Mietspiegel 2025")]
    assert routing.classify_letter(_increase(quote, title=title, key_facts=facts)) == "rent_increase"


def test_a_prepayment_that_is_not_raised_is_no_cost_increase() -> None:
    facts = [ExtractedFact(label="Mietspiegel", value="Mietspiegel 2025", quote="Mietspiegel 2025")]
    # the rent itself rises to the Mietspiegel; nothing in the quote asks for consent, and the prepayment stays
    stays = _increase("Die Nettokaltmiete steigt; die Vorauszahlung wird nicht erhöht.", key_facts=facts)
    assert routing.classify_letter(stays) == "rent_increase"
    raised = _increase("Die Nettokaltmiete steigt; die Vorauszahlung wird ab Januar erhöht.", key_facts=facts)
    assert routing.classify_letter(raised) is None  # a § 560 adjustment: no consent asked for


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


#: A § 558 request as it is written: the new total with the prepayment, what happens without consent.
REQUEST = (
    "Ich bitte Sie, der Erhöhung der Nettokaltmiete von 800,00 EUR auf 880,00 EUR zum 01.01.2027 zuzustimmen "
    "(ortsübliche Vergleichsmiete, Mietspiegel 2025)."
)


@pytest.mark.parametrize(
    "extra",
    [
        {
            "key_facts": [
                ExtractedFact(
                    label="Operating-cost advance payment",
                    value="180,00 EUR",
                    quote="Betriebskostenvorauszahlung 180,00 EUR",
                )
            ]
        },
        {
            "summary": "The prepayment for operating costs stays at 180 EUR. If you do not agree by 31 Dec, the "
            "landlord can sue for consent."
        },
        {
            "key_facts": [
                ExtractedFact(
                    label="Klage",
                    value="Klage auf Zustimmung",
                    quote="Sollten Sie bis zum 31.12.2026 keine Zustimmung erteilen, müsste ich auf Zustimmung klagen.",
                )
            ]
        },
        {
            "key_facts": [
                ExtractedFact(
                    label="Klage",
                    value="Klage",
                    quote="Sollten Sie Ihre Zustimmung nicht erteilen, werde ich Klage erheben.",
                )
            ]
        },
        {
            "key_facts": [
                ExtractedFact(label="Ausstattung", value="Bad modernisiert", quote="Bad 2012 modernisiert")
            ]
        },
        {"title": "Rent increase request (rent index)"},
    ],
)
def test_a_real_consent_request_is_recognised_whatever_else_it_says(extra: dict[str, Any]) -> None:
    extraction = _increase(REQUEST, **extra)
    assert routing.classify_letter(extraction) == "rent_increase"


@pytest.mark.parametrize(
    ("quote", "extra"),
    [
        # the increase's own quote or the title names another kind of increase
        ("Die Staffelmiete erhöht sich; wir bitten um Zustimmung zur Kenntnisnahme.", {}),
        (REQUEST, {"title": "Rent increase after modernisation (§ 559 BGB)"}),
        (REQUEST, {"title": "Index rent adjustment"}),
        (
            "Die Betriebskostenvorauszahlung wird ab 01.01.2027 auf 250,00 EUR erhöht; Zustimmung nicht nötig.",
            {},
        ),
        # a quote says consent isn't needed
        (
            "Die Miete steigt zum 01.01.2027 (Mietspiegel).",
            {"key_facts": [ExtractedFact(label="x", value="y", quote="Ihrer Zustimmung bedarf es nicht.")]},
        ),
    ],
)
def test_other_increases_are_still_not_consent_requests(quote: str, extra: dict[str, Any]) -> None:
    assert routing.classify_letter(_increase(quote, **extra)) is None


@pytest.mark.parametrize(
    ("quote", "title"),
    [
        (
            "Nach der Modernisierung des Bades bitten wir Sie, der Erhöhung der Miete auf die ortsübliche "
            "Vergleichsmiete von 800,00 € zuzustimmen.",
            "Rent increase request",
        ),
        (
            "Wir bitten um Ihre Zustimmung zur Mieterhöhung auf 800,00 € gemäß § 558 BGB.",
            "Rent increase to local comparative rent after modernisation of the bathroom",
        ),
    ],
)
def test_a_consent_request_that_mentions_a_modernisation_is_one(quote: str, title: str) -> None:
    """Review round 2 of phase 2: a § 558 request that names a modernised bathroom (a Mietspiegel feature)
    wasn't filed as a rent increase — no consent to-do, and "Pay" offered on the new rent, which can count as
    consent (§ 558b Abs. 1 BGB)."""
    assert routing.classify_letter(_increase(quote, title=title)) == "rent_increase"


@pytest.mark.parametrize(
    ("quote", "title"),
    [
        (  # the standard sentence of § 558 Abs. 1 S. 3 BGB
            "Gemäß § 558 BGB bitten wir um Zustimmung zur Erhöhung der Nettokaltmiete auf 780,00 € (Erhöhungen "
            "nach §§ 559 bis 560 BGB bleiben unberücksichtigt).",
            "Rent increase request",
        ),
        (
            "Wir bitten um Zustimmung zur Mieterhöhung auf 780 € (§ 558 BGB). Die neue Gesamtmiete inkl. "
            "Vorauszahlungen steigt auf 950 €.",
            "Rent increase request",
        ),
        (
            "Wir bitten um Ihre Zustimmung zur Erhöhung auf die ortsübliche Vergleichsmiete, die Vorauszahlungen "
            "werden angepasst.",
            "Rent increase",
        ),
        (REQUEST, "Rent increase and adjustment of operating cost prepayments"),
        (
            "Gemäß § 558 BGB bitten wir um Ihre Zustimmung; zugleich passen wir die Vorauszahlungen nach § 560 BGB "
            "an.",
            "Rent increase",
        ),
    ],
)
def test_a_consent_request_that_mentions_prepayments_or_559_560_is_one(quote: str, title: str) -> None:
    """Review round 3 of phase 2: a § 558 request whose own quote or title also named the prepayments or
    §§ 559–560 wasn't filed as a rent increase — no consent to-do (§ 558b Abs. 2 BGB), no note that paying the
    new rent can count as consent, and its start not held to the third month (§ 558b Abs. 1 BGB)."""
    assert routing.classify_letter(_increase(quote, title=title)) == "rent_increase"


@pytest.mark.parametrize(
    ("quote", "title"),
    [
        ("Die Betriebskostenvorauszahlung wird ab 01.01.2027 auf 250,00 EUR erhöht.", "Rent increase"),
        ("Die Miete steigt nach § 560 BGB (Mietspiegel beachtet).", "Rent increase"),
        ("Die Miete steigt ab 01.01.2027 (Mietspiegel 2025).", "Adjustment of your prepayments"),
    ],
)
def test_prepayments_or_559_560_without_a_consent_request_are_none(quote: str, title: str) -> None:
    assert routing.classify_letter(_increase(quote, title=title)) is None


@pytest.mark.parametrize(
    ("quote", "title"),
    [
        ("Mieterhöhung nach Modernisierung: Die Miete steigt ab 01.01.2027 um 80,00 EUR.", "Rent increase"),
        ("Modernisierungsmieterhöhung zum 01.01.2027", "Rent increase"),
        ("Die Miete steigt ab 01.01.2027 um 80,00 EUR.", "Rent increase after modernisation"),
        (REQUEST, "Rent increase after modernisation (§ 559 BGB)"),
    ],
)
def test_a_modernisation_increase_without_its_own_consent_request_is_none(quote: str, title: str) -> None:
    """A modernisation increase needs no consent (§ 559 BGB) — even when another quote mentions the rent
    index; only the increase's own request for consent makes a modernisation a § 558 feature."""
    elsewhere = [ExtractedFact(label="Mietspiegel", value="Mietspiegel 2025", quote="laut Mietspiegel 2025")]
    assert routing.classify_letter(_increase(quote, title=title, key_facts=elsewhere)) is None


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


# ------------------------------------------------ the kind the model names (extraction prompt version 9)


def naming(extraction: DocumentExtraction, kind: str | None) -> DocumentExtraction:
    """``extraction`` as a reading of extraction prompt version 9 whose model names ``kind``."""
    return DocumentExtraction.model_validate({**extraction.model_dump(), "high_stakes_kind": kind})


#: A court named only in English, which code doesn't recognise by name (an accepted miss of ADR 0010).
ENGLISH_COURT = ExtractedParty(name="Local Court of Hagen, Central Dunning Court", kind="authority")
EMPLOYER = ExtractedParty(name="Café Kranz", kind="employer")


@pytest.mark.parametrize(
    ("extraction", "kind"),
    [
        (
            reading(title="Court payment order", sender=ENGLISH_COURT, remedy=WIDERSPRUCH),
            "court_payment_order",
        ),
        # a court order whose reading has no remedy and no objection date
        (reading(title="Vollstreckungsbescheid", sender=COURT), "enforcement_order"),
        # a reading without a sender, and a court's full name read as a company
        (reading(title="Mahnbescheid", remedy=WIDERSPRUCH), "court_payment_order"),
        (
            reading(title="Mahnbescheid", sender=ExtractedParty(name="Amtsgericht Hagen", kind="company")),
            "court_payment_order",
        ),
        # terminations the reading doesn't record, or whose contract says nothing
        (reading(kind="employment", title="Termination of your employment", sender=EMPLOYER), "dismissal"),
        (
            reading(
                kind="rent_lease", title="Notice", contract=ExtractedContract(name="Lease", category="rent")
            ),
            "landlord_notice",
        ),
        (_termination(kind="contract", contract=ExtractedContract(name="Vertrag")), "landlord_notice"),
        # a consent request the reading doesn't quote in German
        (_increase("Please agree to the new rent of 880 EUR from 1 January."), "rent_increase"),
    ],
)
def test_the_kind_the_model_names_is_filed_when_code_reads_none(
    extraction: DocumentExtraction, kind: str
) -> None:
    """ADR 0010 point 5: the model names the letter's kind itself, and code files it when its own policy
    reads none and nothing in the reading rules it out — the misses ADR 0010 had accepted (a court named only
    in English, an order read without its remedy, a termination the reading doesn't record). A reading that
    names no kind (every reading before prompt version 9) keeps code's result."""
    assert routing.classify_letter(extraction) is None
    assert routing.classify_letter(naming(extraction, None)) is None
    assert routing.classify_letter(naming(extraction, kind)) == kind
    assert routing.letter_kind(naming(extraction, kind)) == kind


def test_the_kind_code_reads_stands_when_the_model_names_the_same() -> None:
    order = reading(title="Mahnbescheid", sender=COURT, remedy=WIDERSPRUCH)
    assert routing.classify_letter(naming(order, "court_payment_order")) == "court_payment_order"
    notice = _termination(kind="rent_lease")
    assert routing.classify_letter(naming(notice, "landlord_notice")) == "landlord_notice"


@pytest.mark.parametrize(
    ("extraction", "named", "kind"),
    [
        (
            reading(title="Vollstreckungsbescheid", sender=COURT, remedy=EINSPRUCH),
            "court_payment_order",
            "enforcement_order",
        ),
        # an employer ending the lease of a company flat
        (
            _termination(
                contract=ExtractedContract(name="Werkmietwohnung", category="rent"), sender=EMPLOYER
            ),
            "dismissal",
            "landlord_notice",
        ),
        (_increase("Wir bitten um Ihre Zustimmung zur Mieterhöhung."), "landlord_notice", "rent_increase"),
        (_termination(kind="rent_lease"), "operating_costs", "landlord_notice"),
    ],
)
def test_when_code_and_the_model_name_different_kinds_codes_is_filed(
    extraction: DocumentExtraction, named: str, kind: str
) -> None:
    """Code's kind is the structured decision the review rounds checked: it wins a disagreement."""
    assert routing.classify_letter(extraction) == kind
    assert routing.classify_letter(naming(extraction, named)) == kind


@pytest.mark.parametrize("named", ["court_payment_order", "enforcement_order"])
@pytest.mark.parametrize(
    "sender",
    [
        ExtractedParty(name="Inkasso Nord GmbH", kind="company"),  # a debt collector threatening an order
        ExtractedParty(name="LG Electronics Deutschland GmbH", kind="retailer"),
        ExtractedParty(name="OLG Immobilien", kind="landlord"),
        ExtractedParty(name="Gerichtsvollzieher bei dem Amtsgericht Frankfurt am Main", kind="authority"),
        ExtractedParty(name="Gerichtskasse Hamm", kind="authority"),
    ],
)
def test_the_models_court_order_is_vetoed_when_the_sender_is_clearly_no_court(
    sender: ExtractedParty, named: str
) -> None:
    letter = reading(
        kind="dunning",
        title="Letzte Mahnung",
        sender=sender,
        items=[item("Andernfalls beantragen wir beim Amtsgericht einen Mahnbescheid.")],
        remedy=WIDERSPRUCH,
    )
    assert routing.classify_letter(naming(letter, named)) is None
    assert routing.letter_kind(naming(letter, named)) == "dunning"


@pytest.mark.parametrize("named", ["court_payment_order", "enforcement_order"])
@pytest.mark.parametrize(
    "court", [ExtractedParty(name="Amtsgericht Wedding", kind="authority"), ENGLISH_COURT]
)
def test_the_models_court_order_is_vetoed_for_a_european_order_for_payment(
    court: ExtractedParty, named: str
) -> None:
    remedy = Remedy(type="einspruch", quote="Einspruch", period_text="binnen 30 Tagen (Art. 16 EuMahnVO)")
    order = reading(title="European order for payment", sender=court, remedy=remedy)
    assert routing.classify_letter(naming(order, named)) is None


@pytest.mark.parametrize(
    ("extraction", "named"),
    [
        (
            _termination(
                kind="employment", contract=ExtractedContract(name="Jobticket", category="transport")
            ),
            "dismissal",
        ),
        (
            reading(kind="employment", contract=ExtractedContract(name="Fitnessstudio", category="gym")),
            "dismissal",
        ),
        (
            reading(kind="rent_lease", contract=ExtractedContract(name="Fitnessstudio", category="gym")),
            "landlord_notice",
        ),
        (
            reading(sender=EMPLOYER, contract=ExtractedContract(name="Werkmietwohnung", category="rent")),
            "dismissal",
        ),
        (
            reading(
                kind="employment", contract=ExtractedContract(name="Arbeitsvertrag", category="employment")
            ),
            "landlord_notice",
        ),
    ],
)
def test_the_models_termination_is_vetoed_by_a_contract_of_another_category(
    extraction: DocumentExtraction, named: str
) -> None:
    """The contract the reading names decides first, as for code's own kind: a job ticket or a gym ends
    neither a job nor a tenancy, a tenancy no job and a job no tenancy."""
    assert routing.classify_letter(naming(extraction, named)) is None


@pytest.mark.parametrize(
    ("quote", "title"),
    [
        ("Die Staffelmiete erhöht sich zum 01.01.2027 auf 820,00 EUR.", "Rent increase"),
        ("Die Miete erhöht sich zum 01.01.2027 auf 820,00 EUR.", "Index rent adjustment"),
        ("Anpassung der Betriebskostenvorauszahlung ab 01.01.2027 auf 250,00 EUR.", "Rent increase"),
        ("Die Miete steigt ab 01.01.2027 um 80,00 EUR.", "Rent increase after modernisation"),
        ("Die Miete steigt zum 01.01.2027; Ihrer Zustimmung bedarf es nicht.", "Rent increase"),
    ],
)
def test_the_models_rent_increase_is_vetoed_when_it_needs_no_consent(quote: str, title: str) -> None:
    increase = naming(_increase(quote, title=title), "rent_increase")
    assert routing.classify_letter(increase) is None
    assert routing.letter_kind(increase) == "rent_lease"


@pytest.mark.parametrize(
    "fact",
    [
        "Die Miete ist als Indexmiete (§ 557b BGB) vereinbart; maßgeblich ist der Verbraucherpreisindex.",
        "Mieterhöhung nach Modernisierung gemäß § 559 BGB: 8 % der aufgewendeten Kosten.",
    ],
)
def test_the_models_rent_increase_is_vetoed_by_another_kind_anywhere_in_its_quotes(fact: str) -> None:
    """Index rent or a modernisation increase named only in a key fact, while nothing quoted asks for consent:
    filed as a § 558 request it would be dated a month late (§ 557b Abs. 3 S. 3 BGB) and called optional
    (§ 559b Abs. 2 BGB), so the model's kind gives way. Asking for consent anywhere keeps it."""
    quote = "Die monatliche Nettokaltmiete erhöht sich daher ab dem 01.11.2026 auf 668,00 EUR."
    increase = _increase(
        quote,
        title="Rent adjustment for your flat",
        key_facts=[ExtractedFact(label="Grundlage", value="Indexmiete", quote=fact)],
    )
    assert routing.classify_letter(naming(increase, "rent_increase")) is None
    asks = ExtractedFact(label="Bitte", value="Zustimmung", quote="Wir bitten Sie um Ihre Zustimmung.")
    asking = increase.model_copy(update={"key_facts": [*increase.key_facts, asks]})
    assert routing.classify_letter(naming(asking, "rent_increase")) == "rent_increase"


def test_the_models_operating_cost_statement_is_recognised_on_read_and_never_filed() -> None:
    landlord = ExtractedParty(name="Wohnbau Muster GmbH", kind="landlord")
    # a reading whose words code doesn't recognise as a statement
    statement = reading(kind="rent_lease", title="Annual utility cost settlement 2025", sender=landlord)
    assert not routing.names_statement(statement)
    named = naming(statement, "operating_costs")
    assert routing.names_statement(named)
    assert routing.classify_letter(named) is None  # its dates don't depend on its kind
    assert routing.letter_kind(named) == "rent_lease"
    # the vetoes of code's own recognition: a reminder, a utility or a public body
    assert not routing.names_statement(named.model_copy(update={"kind": "dunning"}))
    for kind in ("utility", "authority"):
        sender = ExtractedParty(name="Stadtwerke Musterstadt", kind=kind)
        assert not routing.names_statement(named.model_copy(update={"sender": sender}))


def _notice(quote: str, *, end: str | None = None, **kw: Any) -> DocumentExtraction:
    """A landlord's notice dated 20 Sep 2026 whose termination reads ``quote``."""
    change = ExtractedChange(type="termination_by_provider", effective_date=end, quote=quote)
    kw.setdefault("title", "Kündigung des Mietverhältnisses")
    kw.setdefault("document_date", "2026-09-20")
    return reading(kind="rent_lease", change=change, **kw)


@pytest.mark.parametrize(
    ("quote", "end"),
    [
        ("Hiermit kündigen wir das Mietverhältnis fristlos wegen Zahlungsverzugs.", None),
        ("kündigen wir außerordentlich gemäß § 543 Abs. 2 S. 1 Nr. 3 BGB", "2026-09-30"),
        ("Wir kündigen ohne Einhaltung einer Kündigungsfrist (§ 569 Abs. 3 BGB).", "2026-10-31"),
    ],
)
def test_a_notice_without_notice_period_is_recognised_from_its_own_wording(
    quote: str, end: str | None
) -> None:
    assert routing.extraordinary_notice(_notice(quote, end=end))


ORDINARY_EIGENBEDARF = (
    "Hiermit kündige ich das Mietverhältnis ordentlich und fristgerecht zum 31.03.2027 wegen Eigenbedarfs "
    "(§ 573 Abs. 2 Nr. 2 BGB)."
)


@pytest.mark.parametrize(
    "extraction",
    [
        # the model's summary says what the notice is not
        _notice(
            ORDINARY_EIGENBEDARF,
            end="2027-03-31",
            summary="Your landlord gives ordinary notice for personal use, not a notice without notice period.",
        ),
        # an ordinary notice for arrears that only reserves a notice without notice period
        _notice(
            "Hiermit kündige ich das Mietverhältnis ordentlich und fristgerecht zum 31.03.2027 (§ 573 Abs. 2 "
            "Nr. 1 BGB).",
            end="2027-03-31",
            key_facts=[
                ExtractedFact(
                    label="Vorbehalt",
                    value="fristlose Kündigung vorbehalten",
                    quote="Eine fristlose Kündigung wegen des Zahlungsverzugs behalten wir uns ausdrücklich vor.",
                )
            ],
        ),
        # … or says so in the termination's own sentence
        _notice(
            "Wir kündigen ordentlich zum 31.03.2027; eine fristlose Kündigung bleibt vorbehalten.",
            end="2027-03-31",
        ),
        _notice("Wir behalten uns vor, das Mietverhältnis fristlos zu kündigen.", end=None),
        _notice(
            "Dies ist keine fristlose Kündigung; das Mietverhältnis endet am 31.03.2027.", end="2027-03-31"
        ),
        _notice(ORDINARY_EIGENBEDARF, end="2027-03-31", title="Ordinary notice, not without notice"),
        # a special termination with the statutory period: §§ 574–574c apply (§ 575a Abs. 2 BGB)
        _notice(
            "kündigen wir das Mietverhältnis außerordentlich mit der gesetzlichen Frist gemäß § 57a ZVG zum "
            "31.03.2027",
            end="2027-03-31",
        ),
        _notice("Sonderkündigung gemäß § 111 InsO außerordentlich zum 31.12.2026", end="2026-12-31"),
        # "fristlos" with the tenancy ending months later: unsure, so the objection to-do is kept
        _notice("Wir kündigen fristlos; räumen Sie die Wohnung bis zum 31.03.2027.", end="2027-03-31"),
        _notice("Wir kündigen fristlos.", end="2027-03-31", document_date=None),
    ],
)
def test_a_notice_is_only_without_notice_period_when_its_own_wording_says_so(
    extraction: DocumentExtraction,
) -> None:
    assert not routing.extraordinary_notice(extraction)
    assert (
        routing.derived_deadlines(
            "landlord_notice", end=routing.announced_end(extraction), letter_date=D("2026-09-20")
        )
        or routing.announced_end(extraction) is None
    )


@pytest.mark.parametrize(
    ("quote", "title"),
    [
        # § 573d BGB is headed "Außerordentliche Kündigung mit gesetzlicher Frist": heirs and a buyer at a
        # forced sale write it so, often without an end ("zum nächstmöglichen Zeitpunkt")
        (
            "Wir kündigen das Mietverhältnis außerordentlich mit gesetzlicher Kündigungsfrist zum nächstmöglichen "
            "Zeitpunkt.",
            "Kündigung des Mietverhältnisses",
        ),
        ("Als Erben kündigen wir das Mietverhältnis außerordentlich mit gesetzlicher Frist.", "Kündigung"),
        ("Wir kündigen außerordentlich unter Wahrung der gesetzlichen Frist.", "Kündigung"),
        # … and the model's English title of one
        (
            "Als Erbin kündige ich das Mietverhältnis außerordentlich zum nächstmöglichen Termin.",
            "Extraordinary termination of your tenancy with statutory notice (heirs)",
        ),
        (
            "Als Erbin kündige ich das Mietverhältnis außerordentlich zum nächstmöglichen Termin.",
            "Extraordinary notice of termination (heir, statutory period)",
        ),
    ],
)
def test_a_special_termination_with_the_statutory_period_keeps_the_hardship_objection(
    quote: str, title: str
) -> None:
    """Final review 2: "außerordentlich mit gesetzlicher Frist" (§ 573d BGB) is no notice without notice
    period, even with no end stated — the hardship objection applies to it (§ 574 Abs. 1 BGB), so the card
    and the composer (both :func:`~ordnung.rules.routing.extraordinary_notice`) offer it."""
    assert not routing.extraordinary_notice(_notice(quote, end=None, title=title))
    # the same letter said fristlos is one
    assert routing.extraordinary_notice(_notice("Wir kündigen das Mietverhältnis fristlos.", end=None))


@pytest.mark.parametrize(
    ("quote", "title"),
    [
        # the usual arrears notice: the statutory period belongs to the notice given in the alternative
        (
            "Hiermit kündigen wir das Mietverhältnis fristlos wegen Zahlungsverzugs, hilfsweise ordentlich unter "
            "Einhaltung der gesetzlichen Kündigungsfrist zum 31.12.2026.",
            "Kündigung des Mietverhältnisses",
        ),
        (
            "Hiermit kündigen wir das Mietverhältnis fristlos. Hilfsweise kündigen wir ordentlich mit der "
            "gesetzlichen Frist.",
            "Kündigung des Mietverhältnisses",
        ),
        (
            "Wir kündigen fristlos, vorsorglich auch ordentlich unter Wahrung der gesetzlichen Frist.",
            "Kündigung",
        ),
        ("Wir kündigen fristlos.", "Termination without notice, alternatively with statutory notice"),
        # a statutory period the wording denies
        (
            "Hiermit kündigen wir fristlos wegen Zahlungsverzugs.",
            "Termination of tenancy without statutory notice",
        ),
        ("fristlos wegen Zahlungsverzugs", "Termination without statutory notice period"),
        ("Wir kündigen fristlos und nicht mit der gesetzlichen Frist.", "Kündigung"),
    ],
)
def test_a_statutory_period_of_the_alternative_notice_or_denied_keeps_it_without_notice_period(
    quote: str, title: str
) -> None:
    """Final review 3: "mit der gesetzlichen Frist" and "statutory notice" make a special termination only
    when they are said of the notice itself — not of the notice given in the alternative (after *hilfsweise*,
    *vorsorglich … ordentlich*, "alternatively"), and not denied ("without statutory notice"). Such a notice
    stays one without notice period: urgent, with the fact, and never filed as handled."""
    extraction = _notice(quote, end=None, title=title)
    assert routing.extraordinary_notice(extraction)
    card = letter_advice(
        "landlord_notice",
        today=TODAY,
        extraordinary=True,
        alternative=routing.alternative_notice(extraction),
        handled=True,
    )
    assert card is not None and card.urgent and not card.handled
    assert card.facts[0].title == "This reads as a notice without notice period (fristlos)"


def test_the_standard_arrears_notice_with_an_end_date_reads_as_without_notice_period() -> None:
    """Final review 3: the exact wording from the review, with the alternative notice's end date: before, the
    statutory period in the *hilfsweise* clause made it an ordinary notice that could be filed as handled."""
    quote = (
        "Hiermit kündigen wir das Mietverhältnis fristlos wegen Zahlungsverzugs, hilfsweise ordentlich unter "
        "Einhaltung der gesetzlichen Kündigungsfrist zum 31.12.2026."
    )
    both = _notice(quote, end="2026-12-31")
    assert routing.extraordinary_notice(both) and routing.alternative_notice(both)
    fristgerecht = _notice(
        quote.replace("ordentlich unter Einhaltung der gesetzlichen Kündigungsfrist", "fristgerecht")
    )
    assert routing.extraordinary_notice(fristgerecht)
    # a statutory period said of the notice itself, before any alternative, still counts
    special = _notice(
        "Wir kündigen außerordentlich mit gesetzlicher Frist (§ 573d BGB), hilfsweise ordentlich zum 31.12.2026.",
        end="2026-12-31",
    )
    assert not routing.extraordinary_notice(special)


def test_the_letter_date_given_wins_over_the_readings() -> None:
    far = _notice("Wir kündigen fristlos.", end="2026-12-31")
    assert not routing.extraordinary_notice(far)  # ends more than two months after 20 Sep
    assert routing.extraordinary_notice(far, D("2026-11-15"))  # the person corrected the letter's date


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
        # review round 1: the new rent is never owed before the third month after the request arrived
        (spec(nature="payment"), "rent_increase", False, "bgb_558b"),
        (spec(nature="payment", legal_basis="§ 558b BGB"), None, False, None),
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
        # only a declaration is a withdrawal: a cancellation or a payment that mentions it is not
        (
            DateSpec(
                type="fixed",
                date="2026-10-31",
                nature="notice",
                text="Kündigung muss bis 31.10.2026 eingehen (unabhängig von Ihrem Widerrufsrecht)",
            ),
            None,
            False,
            None,
        ),
        (
            spec(
                nature="payment",
                anchor="document_date",
                amount=30,
                unit="days",
                text="zahlbar 30 Tage nach Ablauf der Widerrufsfrist",
            ),
            None,
            False,
            None,
        ),
        (spec(nature="other", text="Vertragsbeginn nach Ablauf der Widerrufsfrist"), None, False, None),
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
    # a labour court's orders give one week (§ 46a Abs. 3, § 59 ArbGG)
    [labour_order] = routing.derived_deadlines("court_payment_order", end=None, labour_court=True)
    [labour_enforcement] = routing.derived_deadlines("enforcement_order", end=None, labour_court=True)
    assert (labour_order.rule_id, labour_enforcement.rule_id) == ("arbgg_46a", "arbgg_59")
    assert (labour_order.spec.amount, labour_order.spec.unit) == (1, "weeks")
    assert "one week" in labour_order.consequence and "one week" in labour_enforcement.consequence
    assert [d.rule_id for d in routing.derived_deadlines("dismissal", end=None)] == ["kschg_4", "sgb3_38"]
    assert [d.rule_id for d in routing.derived_deadlines("rent_increase", end=None)] == ["bgb_558b"]
    # no hardship objection to a notice without notice period (§ 574 Abs. 1 S. 2 BGB)
    assert routing.derived_deadlines("landlord_notice", end=D("2027-10-31"), extraordinary=True) == []
    assert routing.derived_deadlines("landlord_notice", end=None, extraordinary=True) == []
    # review round 1: a notice too short for its period, or with no end read (given in the alternative, "zum
    # nächstmöglichen Termin" — review round 2 of phase 2), counts back from the next permissible end
    # (§ 573c Abs. 1 BGB)
    [short] = routing.derived_deadlines("landlord_notice", end=D("2026-10-31"), letter_date=D("2026-09-20"))
    [no_end] = routing.derived_deadlines("landlord_notice", end=None)
    [alternative] = routing.derived_deadlines("landlord_notice", end=None, alternative=True, dated=True)
    # … unless the letter gives its own objection date, which counts from the end the landlord knows
    assert routing.derived_deadlines("landlord_notice", end=None, dated=True) == []
    for next_end in (short, no_end, alternative):
        assert next_end.rule_id == "bgb_574b" and next_end.spec.anchor == "receipt"
        assert "nächstmöglichen" in next_end.spec.text and "§ 573c" in (next_end.spec.legal_basis or "")
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


@pytest.mark.parametrize(
    ("date_spec", "dated"),
    [
        (DateSpec(type="fixed", date="2026-11-30", nature="objection"), True),
        (
            DateSpec(
                type="relative",
                anchor="explicit_date",
                anchor_date="2027-01-31",
                amount=-2,
                unit="months",
                nature="objection",
            ),
            True,
        ),
        # the statutory hint of a notice with no end: a period from an end it doesn't give (review round 3)
        (
            DateSpec(
                type="relative",
                anchor="explicit_date",
                amount=-2,
                unit="months",
                nature="objection",
                text="spätestens zwei Monate vor der Beendigung des Mietverhältnisses",
            ),
            False,
        ),
        (DateSpec(type="fixed", date=None, nature="objection"), False),
        (DateSpec(type="none", nature="objection"), False),
        (DateSpec(type="fixed", date="2026-11-30", nature="payment"), False),
    ],
)
def test_only_an_objection_date_that_can_be_computed_is_the_letters_own(
    date_spec: DateSpec, dated: bool
) -> None:
    assert routing.objection_dated(date_spec) is dated


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
    # review round 1: a served letter's one date is "delivered", never "arrived" or "received"
    assert ASSUMED_DELIVERY_WARNING in receipt.warnings and ASSUMED_RECEIPT_WARNING not in receipt.warnings
    delivered = compute_due(
        spec(),
        ctx(
            region="NW",
            document_date="2026-09-21",
            received_date="2026-09-23",
            received_confirmed=True,
            letter_kind="court_payment_order",
        ),
    )
    assert "after the day it was delivered (Wed 23 Sep 2026)" in delivered.summary
    assert "received" not in delivered.summary
    undated = compute_due(spec(), ctx(letter_kind="court_payment_order"))
    assert NEEDS_DELIVERY_WARNING in undated.warnings
    assert sum("yellow envelope" in w for w in receipt.warnings) == 1  # asked once, not twice


def test_a_court_order_read_as_deemed_delivery_still_runs_from_formal_service() -> None:
    receipt = compute_due(
        spec(anchor="deemed_delivery", delivery_rule="de_admin_post"),
        ctx(
            region="NW", document_date="2026-09-21", delivery_scope="vwvfg", letter_kind="court_payment_order"
        ),
    )
    assert receipt.due_date == "2026-10-05"  # no 4-day fiction for court orders
    assert any("yellow envelope" in w and "§ 180 ZPO" in w for w in receipt.warnings)


@pytest.mark.parametrize(
    ("anchor", "delivery_rule"),
    [("document_date", "none"), ("deemed_delivery", "de_admin_post"), (None, "none"), ("today", "none")],
)
def test_the_envelope_date_the_person_entered_counts_whatever_anchor_the_order_was_read_with(
    anchor: str | None, delivery_rule: str
) -> None:
    """A court order runs from delivery (§ 180 ZPO): once the person enters the envelope date it is the
    start, even when the model read the period as counted from the letter's date."""
    date_spec = spec(anchor=anchor, delivery_rule=delivery_rule, text="binnen zwei Wochen")
    receipt = compute_due(
        date_spec,
        ctx(
            region="NW",
            document_date="2026-09-21",
            received_date="2026-09-25",
            received_confirmed=True,
            delivery_scope="vwvfg",
            letter_kind="court_payment_order",
        ),
    )
    assert receipt.due_date == "2026-10-09"  # two weeks from Fri 25 Sep, not from Mon 21 Sep
    assert not any("enter the" in w and "envelope date" in w for w in receipt.warnings)
    assert receipt.confidence == "medium" and "zpo_180" in receipt.rule_ids
    # the law's to-do isn't filed next to it: this date was counted under the court rule
    assert routing.computed_under(date_spec, receipt.rule_ids, "zpo_692")


@pytest.mark.parametrize(
    ("anchor", "letter_kind", "court"),
    [
        ("receipt", "court_payment_order", True),
        ("explicit_date", "court_payment_order", True),
        ("explicit_date", "enforcement_order", True),
        ("receipt", None, True),  # a court's letter the policy doesn't file as an order
        ("receipt", None, False),  # any letter read with its delivery day
    ],
)
def test_an_earlier_envelope_date_the_person_entered_beats_a_start_the_reading_names(
    anchor: str, letter_kind: str | None, court: bool
) -> None:
    """The reading may name a start of its own (a hand-written envelope date misread from a photo as
    Thu 24 Sep); the person enters Tue 22 Sep. The earlier day counts, and a warning names both — two
    days past a Notfrist can't be undone."""
    date_spec = spec(anchor=anchor, anchor_date="2026-09-24", text="binnen zwei Wochen seit der Zustellung")
    base = ctx(region="NW", document_date="2026-09-18", letter_kind=letter_kind, court=court)
    assert compute_due(date_spec, base).due_date == "2026-10-08"
    receipt = compute_due(date_spec, replace(base, received_date=D("2026-09-22"), received_confirmed=True))
    assert receipt.due_date == "2026-10-06"
    assert "22 Sep" in receipt.summary
    assert any("Tue 22 Sep 2026" in w and "Thu 24 Sep 2026" in w for w in receipt.warnings)
    assert receipt.confidence != "high"


@pytest.mark.parametrize("anchor", ["receipt", "explicit_date"])
def test_a_later_envelope_date_keeps_the_earlier_start_the_reading_names_and_says_so(anchor: str) -> None:
    """The person's later day doesn't move a stated start later (the earliest plausible date); the
    warning names both so the person can check the envelope."""
    date_spec = spec(anchor=anchor, anchor_date="2026-09-22", text="binnen zwei Wochen seit der Zustellung")
    receipt = compute_due(
        date_spec,
        ctx(
            region="NW",
            document_date="2026-09-18",
            received_date="2026-09-24",
            received_confirmed=True,
            letter_kind="court_payment_order",
            court=True,
        ),
    )
    assert receipt.due_date == "2026-10-06"
    assert any("Tue 22 Sep 2026" in w and "Thu 24 Sep 2026" in w and "earlier" in w for w in receipt.warnings)
    assert receipt.confidence == "low"  # a court date (soft) whose start is disputed (soft)
    # the same day entered and read: nothing to warn about
    same = compute_due(
        date_spec,
        ctx(
            region="NW",
            document_date="2026-09-18",
            received_date="2026-09-22",
            received_confirmed=True,
            letter_kind="court_payment_order",
            court=True,
        ),
    )
    assert same.due_date == "2026-10-06" and not any("you entered" in w.lower() for w in same.warnings)


def test_an_unreadable_explicit_start_of_a_court_order_uses_the_envelope_date_entered() -> None:
    date_spec = spec(anchor="explicit_date", anchor_date="24.09.", text="binnen zwei Wochen")
    court = ctx(region="NW", document_date="2026-09-18", letter_kind="court_payment_order", court=True)
    assert compute_due(date_spec, court).due_date is None  # nothing to count from
    entered = compute_due(date_spec, replace(court, received_date=D("2026-09-22"), received_confirmed=True))
    assert entered.due_date == "2026-10-06"


def test_the_letter_rules_count_from_an_earlier_arrival_day_the_person_entered() -> None:
    """The consent period of a rent increase (§ 558b BGB) runs from the arrival: a day the reading states
    and a different one the person entered give the earlier."""
    date_spec = spec(
        nature="declaration",
        anchor="receipt",
        anchor_date="2026-10-01",
        text="Zustimmung",
        amount=None,
        unit=None,
    )
    base = ctx(region="BE", document_date="2026-09-25", letter_kind="rent_increase")
    assert compute_due(date_spec, base).due_date == "2026-12-31"  # October + 2 months
    entered = compute_due(date_spec, replace(base, received_date=D("2026-09-29"), received_confirmed=True))
    assert entered.due_date == "2026-11-30"  # September + 2 months
    assert any("Tue 29 Sep 2026" in w and "Thu 1 Oct 2026" in w for w in entered.warnings)


def test_a_court_letter_the_policy_doesnt_file_as_an_order_still_runs_from_delivery() -> None:
    """A court's letter that isn't filed as a court order (a Versäumnisurteil, an order the policy
    missed) never gets the 4-day fiction of an authority letter and is never ``high``."""
    date_spec = spec(anchor="deemed_delivery", delivery_rule="de_admin_post", text="binnen zwei Wochen")
    as_authority = compute_due(
        date_spec, ctx(region="NW", document_date="2026-09-23", delivery_scope="vwvfg")
    )
    assert as_authority.due_date == "2026-10-12" and as_authority.confidence == "high"  # the fiction
    court = ctx(region="NW", document_date="2026-09-23", delivery_scope="vwvfg", court=True)
    receipt = compute_due(date_spec, court)
    assert receipt.due_date == "2026-10-07"  # from the letter's date: the earliest plausible start
    assert receipt.confidence != "high" and "vwvfg_41_2" not in receipt.rule_ids
    assert any("court's letter" in w and "yellow envelope" in w for w in receipt.warnings)
    fixed = compute_due(DateSpec(type="fixed", date="2026-10-20", nature="objection"), court)
    assert fixed.due_date == "2026-10-20" and fixed.confidence != "high"
    entered = compute_due(date_spec, replace(court, received_date=D("2026-09-25"), received_confirmed=True))
    assert entered.due_date == "2026-10-09"
    # a court's "Widerruf" (a settlement's, say) is never a consumer's withdrawal
    revocation = spec(nature="declaration", anchor="document_date", text="Widerrufsfrist für den Vergleich")
    assert "bgb_355" not in compute_due(revocation, court).rule_ids


def test_a_labour_courts_order_gives_one_week() -> None:
    """§ 46a Abs. 3 ArbGG: the period in a labour court's Mahnbescheid is one week; § 59 ArbGG: the
    objection to its enforcement order too."""
    labour = ctx(
        region="BE",
        document_date="2026-09-21",
        received_date="2026-09-22",
        received_confirmed=True,
        letter_kind="court_payment_order",
        court=True,
        labour_court=True,
    )
    [derived] = routing.derived_deadlines("court_payment_order", end=None, labour_court=True)
    receipt = compute_due(derived.spec, labour)
    assert receipt.due_date == "2026-09-29" and receipt.confidence == "medium"
    assert {"arbgg_46a", "zpo_180", "zpo_222"} <= set(receipt.rule_ids) and "zpo_692" not in receipt.rule_ids
    # the letter's own one-week period, citing the ZPO: no false "the law gives two weeks"
    own = spec(amount=1, unit="weeks", legal_basis="§ 692 Abs. 1 Nr. 3 ZPO", text="binnen einer Woche")
    stated = compute_due(own, labour)
    assert stated.due_date == "2026-09-29" and not any("two weeks" in w for w in stated.warnings)
    assert routing.computed_under(own, stated.rule_ids, "arbgg_46a")
    # a two-week period read from it is cut to the law's week
    two = compute_due(spec(text="binnen zwei Wochen"), labour)
    assert two.due_date == "2026-09-29"
    assert any("one week" in w and "§ 46a" in w for w in two.warnings)
    enforcement = replace(labour, letter_kind="enforcement_order")
    notfrist = compute_due(spec(text="Einspruch binnen einer Woche", amount=1), enforcement)
    assert notfrist.due_date == "2026-09-29" and "arbgg_59" in notfrist.rule_ids


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


def test_a_court_orders_payment_date_doesnt_stand_in_for_pay_or_object() -> None:
    """The official wording ("… die behauptete Schuld … zu begleichen oder dem Gericht mitzuteilen, ob Sie
    … widersprechen") read as a payment item is counted under the court rule, but the law's to-do asks
    to pay *or object*: it is still filed, so the letter never reads as "Pay 480 EUR" alone."""
    payment = spec(nature="payment", text="innerhalb von zwei Wochen seit der Zustellung dieses Bescheids")
    order = ctx(region="NW", document_date="2026-09-21", letter_kind="court_payment_order", court=True)
    receipt = compute_due(payment, order)
    assert "zpo_692" in receipt.rule_ids and receipt.due_date == "2026-10-05"
    assert not routing.computed_under(payment, receipt.rule_ids, "zpo_692")
    objection = spec(text="binnen zwei Wochen Widerspruch")
    assert routing.computed_under(objection, compute_due(objection, order).rule_ids, "zpo_692")


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
    assert registration_deadline(D("2026-07-02"), D("2026-09-30")) == (D("2026-07-05"), "after_learning")
    assert registration_deadline(D("2026-07-01"), None) == (D("2026-07-04"), "after_learning")


def test_registration_on_the_boundary_day_uses_the_earlier_reading() -> None:
    """Review round 1: three months before 31 Dec is 30 Sep — or 1 Oct, as some guides read it. On that
    reading, a person who learns the end on 1 Oct still had three months, so sentence 1 gives 1 Oct itself,
    earlier than three days later (4 Oct)."""
    assert registration_deadline(D("2026-10-01"), D("2026-12-31")) == (D("2026-10-01"), "boundary")
    assert registration_deadline(D("2026-07-01"), D("2026-09-30")) == (D("2026-07-01"), "boundary")
    assert registration_deadline(D("2026-10-02"), D("2026-12-31")) == (D("2026-10-05"), "after_learning")
    receipt = compute_due(
        spec(amount=3, unit="days", nature="declaration", legal_basis="§ 38 SGB III"),
        ctx(
            document_date="2026-09-29",
            received_date="2026-10-01",
            received_confirmed=True,
            end_date="2026-12-31",
        ),
    )
    assert receipt.due_date == "2026-10-01"
    assert any("as some read it, Thu 1 Oct 2026" in step.label for step in receipt.steps)


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


def test_a_dismissal_without_notice_period_counts_the_registration_from_its_arrival() -> None:
    """Review round 4 of phase 2: "außerordentlich fristlos, hilfsweise fristgerecht zum 31.12.2026" counted
    § 38 SGB III from the end given in the alternative (Wed 30 Sep, high) — but a notice without notice period
    ends the job when it arrives, so the three days of § 38 Abs. 1 S. 2 SGB III count from then (Mon 28 Sep),
    whether or not the dismissal is challenged (S. 3). The alternative end is only noted."""
    dismissal = ctx(
        document_date="2026-09-24",
        received_date="2026-09-25",
        received_confirmed=True,
        end_date="2026-12-31",
        letter_kind="dismissal",
    )
    register = spec(amount=3, unit="days", nature="declaration", legal_basis="§ 38 Abs. 1 SGB III")
    assert compute_due(register, dismissal).due_date == "2026-09-30"  # an ordinary notice to 31 Dec
    fristlos = compute_due(register, replace(dismissal, ends_on_arrival=True))
    assert fristlos.due_date == "2026-09-28"
    assert "without notice period arrived (Fri 25 Sep 2026)" in fristlos.summary
    assert any("fristlos) ends the job when it arrives" in step.label for step in fristlos.steps)
    assert any("names Thu 31 Dec 2026" in w and "§ 38 Abs. 1 S. 3 SGB III" in w for w in fristlos.warnings)
    # the letter's own "three months before the end" counts from the arrival too
    wording = spec(
        anchor="explicit_date",
        anchor_date="2026-12-31",
        amount=-3,
        unit="months",
        nature="declaration",
        text="sich spätestens drei Monate vor Beendigung arbeitsuchend zu melden",
    )
    assert compute_due(wording, replace(dismissal, ends_on_arrival=True)).due_date == "2026-09-28"
    # no end given: nothing to note
    bare = compute_due(register, replace(dismissal, ends_on_arrival=True, end_date=None))
    assert bare.due_date == "2026-09-28" and not any("names" in w for w in bare.warnings)
    assert not any("don't know when the job ends" in w for w in bare.warnings)


def test_registering_on_a_weekend_is_said_to_work_online_only() -> None:
    """Review round 4 of phase 2: the Agentur's phone line is open on working days only."""
    weekend = compute_due(
        spec(amount=3, unit="days", nature="declaration", legal_basis="§ 38 SGB III"),
        ctx(document_date="2026-09-30", received_date="2026-10-01", received_confirmed=True),
    )
    [note] = [w for w in weekend.warnings if "§ 26 Abs. 3 SGB X" in w]
    assert "registering online works on any day" in note and "phone" not in note


@pytest.mark.parametrize(
    "quote",
    [
        "Hiermit kündigen wir das Arbeitsverhältnis außerordentlich fristlos, hilfsweise fristgerecht zum "
        "31.12.2026.",
        "Wir kündigen das Arbeitsverhältnis außerordentlich, hilfsweise ordentlich zum 31.12.2026.",
        "Wir kündigen das Arbeitsverhältnis gemäß § 626 BGB, hilfsweise zum 31.12.2026.",
    ],
)
def test_a_dismissal_without_notice_period_is_recognised_like_a_landlords(quote: str) -> None:
    change = ExtractedChange(type="termination_by_provider", effective_date="2026-12-31", quote=quote)
    dismissal = reading(kind="employment", change=change, document_date="2026-09-24")
    assert routing.notice_without_period(dismissal) is not None
    ordinary = change.model_copy(
        update={"quote": "Wir kündigen das Arbeitsverhältnis fristgerecht zum 31.12.2026."}
    )
    assert routing.notice_without_period(reading(kind="employment", change=ordinary)) is None


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


@pytest.mark.parametrize(
    ("grounding", "confidence", "flagged"),
    [("quote", "high", False), ("letter", "medium", False), ("none", "low", True)],
)
def test_dates_counted_from_the_end_date_are_only_as_sure_as_its_reading(
    grounding: str, confidence: str, flagged: bool
) -> None:
    """The end a termination announces is the model's reading: only one written in the termination's own
    sentence may give ``high`` (SPEC § 21, anchor stated in the document). The objection to a landlord's
    notice (§ 574b) and the registration three months before the end (§ 38 SGB III) count from it."""
    notice = routing.derived_deadlines("landlord_notice", end=D("2027-03-31"), letter_date=D("2026-09-20"))[0]
    objection = compute_due(
        notice.spec,
        ctx(
            region="NW",
            document_date="2026-09-20",
            letter_kind="landlord_notice",
            end_date="2027-03-31",
            end_date_grounding=grounding,
        ),
    )
    registration = compute_due(
        routing.derived_deadlines("dismissal", end=D("2027-03-31"))[1].spec,
        ctx(
            document_date="2026-09-24",
            received_date="2026-09-25",
            received_confirmed=True,
            letter_kind="dismissal",
            end_date="2027-03-31",
            end_date_grounding=grounding,
        ),
    )
    assert objection.due_date == "2027-01-31" and registration.due_date == "2026-12-31"
    for receipt in (objection, registration):
        assert receipt.confidence == confidence
        assert ("termination_end" in receipt.rule_ids) is flagged
        assert any("Wed 31 Mar 2027" in w for w in receipt.warnings) is (grounding != "quote")


def test_the_three_days_after_learning_dont_depend_on_the_end_date() -> None:
    """A job ending within three months: three days after learning it, whatever end was read — a
    misread end can only make the date earlier, so nothing is lowered."""
    receipt = compute_due(
        routing.derived_deadlines("dismissal", end=D("2026-11-30"))[1].spec,
        ctx(
            document_date="2026-09-24",
            received_date="2026-09-25",
            received_confirmed=True,
            letter_kind="dismissal",
            end_date="2026-11-30",
            end_date_grounding="none",
        ),
    )
    assert receipt.due_date == "2026-09-28" and receipt.confidence == "high"


def test_an_end_a_date_names_itself_is_graded_by_its_own_quote() -> None:
    """A date whose own wording names the end (an explicit anchor other than the reading's end) is
    graded by its quote, not by the reading's end."""
    receipt = compute_due(
        spec(
            anchor="explicit_date",
            anchor_date="2027-04-30",
            amount=-2,
            unit="months",
            legal_basis="§ 574b BGB",
        ),
        ctx(region="NW", document_date="2026-09-20", end_date="2027-03-31", end_date_grounding="none"),
    )
    assert receipt.due_date == "2027-02-28" and "termination_end" not in receipt.rule_ids


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


def test_a_withdrawal_cites_the_bgbs_counting_rule_only() -> None:
    """Review round 4 of phase 2: a consumer's § 355 BGB period cited the AO, VwVfG and SGB X for its start."""
    receipt = compute_due(
        spec(amount=14, unit="days", nature="declaration", text="Widerrufsfrist"),
        ctx(document_date="2026-09-20", received_date="2026-09-22", received_confirmed=True),
    )
    [start] = [step for step in receipt.steps if step.rule_id == "bgb_187_1"]
    assert start.citation == "§ 187 Abs. 1 BGB"


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


def test_a_withdrawal_period_in_working_days_is_counted_and_shown() -> None:
    """14 Werktage (Mon–Sat) from Tue 1 Sep 2026 end on Thu 17 Sep: longer than the 14 days of § 355 BGB
    (Tue 15 Sep), so the letter's grant is shown and kept once the 14 days have passed."""
    early = _stated(14, "2026-09-10", unit="werktage")
    assert early.due_date == "2026-09-15" and early.confidence == "medium"
    assert any("14 working days" in w and "Thu 17 Sep 2026" in w for w in early.warnings)
    later = _stated(14, "2026-09-16", unit="werktage")
    assert later.due_date == "2026-09-17"
    business = _stated(10, "2026-09-10", unit="business_days")  # Mon–Fri: Tue 15 Sep, the same day
    assert business.due_date == "2026-09-15" and business.confidence == "high"
    assert not any("shorter period" in w or "longer than" in w for w in business.warnings)


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


@pytest.mark.parametrize("kind", ["court_payment_order", "enforcement_order"])
def test_a_labour_courts_order_has_its_own_card(kind: str) -> None:
    card = letter_advice(kind, today=TODAY, labour_court=True)
    assert card is not None and card.urgent
    assert "one week" in card.title and "two weeks" not in card.summary
    assert "labour court" in card.help[0].name.lower() or "labour court" in card.help[0].what
    assert all("online-mahnantrag" not in (link.url or "") for link in card.help)
    assert ("arbgg_46a" if kind == "court_payment_order" else "arbgg_59") in card.rule_ids
    for rule_id in card.rule_ids:
        catalog.get_rule(rule_id)
    entered = letter_advice(kind, today=TODAY, labour_court=True, arrival_confirmed=True)
    assert entered is not None and entered.steps[0].startswith("The period counts from the delivery date")


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


@pytest.mark.parametrize(
    ("extraordinary", "todo", "urgent"),
    [(False, True, False), (True, True, True), (False, False, True), (True, False, True)],
)
def test_a_landlords_card_comes_first_when_no_to_do_carries_the_notice(
    extraordinary: bool, todo: bool, urgent: bool
) -> None:
    """Review round 4, final review 1: a notice without notice period, or one no to-do carries the objection
    of, has only its card to say "act", so it is urgent and rendered first — decided by the to-dos, not by
    whether the reading had an end date."""
    card = letter_advice(
        "landlord_notice", today=TODAY, extraordinary=extraordinary, objection_todo=todo, end_unknown=True
    )
    assert card is not None and card.urgent is urgent
    asks_for_end = card.steps[0].startswith("We couldn't read when your tenancy ends")
    assert asks_for_end is (not todo and not extraordinary)


def test_a_late_statement_card_comes_first_and_says_check_before_paying() -> None:
    text = "Abrechnungszeitraum: 01.01.2024 - 31.12.2024"
    late = letter_advice("operating_costs", today=TODAY, arrived=D("2026-09-10"), text=text)
    assert late is not None and late.urgent and late.steps[0].startswith("Don't pay a back-payment")
    on_time = letter_advice("operating_costs", today=TODAY, arrived=D("2025-09-10"), text=text)
    assert on_time is not None and not on_time.urgent and not on_time.steps[0].startswith("Don't pay")
    assert statement_late(text, D("2026-09-10"), False, None)
    assert not statement_late(text, None, False, None)  # no arrival: nothing to check
    assert not statement_late("Rechnung", D("2026-09-10"), False, None)  # no billing period
    assert not statement_late(text, D("2025-12-01"), True, "NW")


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
    assert not any(step.startswith("No hardship objection when") for step in card.steps)  # not twice


def test_the_hardship_objection_is_excluded_against_the_notice_in_the_alternative_too() -> None:
    """Final review 3: § 574 Abs. 1 S. 2 BGB excludes the hardship objection whenever the landlord had grounds
    for a notice without notice period — also against the ordinary notice given in the alternative, and a
    payment within the grace period doesn't revive it (BGH, 01.07.2020, VIII ZR 323/18). The card never says
    the objection applies to the alternative notice; it keeps the objection letter (the safe side) and says
    to object anyway only if those grounds didn't exist. The ordinary card's step and the objection letter's
    note say the same."""
    from ordnung.drafts.compose import NO_HARDSHIP_OBJECTION

    card = letter_advice("landlord_notice", today=TODAY, extraordinary=True, alternative=True)
    ordinary = letter_advice("landlord_notice", today=TODAY)
    assert card is not None and ordinary is not None
    [fact] = card.facts
    assert card.draft == "objection"
    assert "only to the notice the landlord gives" not in fact.text
    assert HARDSHIP_EXCLUDED in fact.text and "VIII ZR 323/18" in (fact.citation or "")
    assert HARDSHIP_EXCLUDED.startswith(
        "The hardship objection is excluded whenever the landlord had grounds for a notice without notice "
        "period — also against the notice given in the alternative, and paying the arrears doesn't change that "
        "(§ 574 Abs. 1 S. 2 BGB; BGH, 01.07.2020, VIII ZR 323/18)."
    )
    assert "Object in time anyway if you think those grounds didn't exist" in HARDSHIP_EXCLUDED
    [step] = [step for step in ordinary.steps if step.startswith("No hardship objection when")]
    assert "even against a notice with a notice period, and even once the arrears are paid" in step
    assert "VIII ZR 323/18" in step and "can't be met with this objection" not in step
    assert "excluded whenever the landlord had grounds for such a notice" in NO_HARDSHIP_OBJECTION


def test_paying_the_arrears_is_never_said_to_undo_more_than_the_law_does() -> None:
    """Final review 2: paying rent arrears in time undoes only the notice without notice period, and not
    when that already happened within two years (§ 569 Abs. 3 Nr. 2 S. 2 BGB) — never a notice with a
    notice period given as well (BGH VIII ZR 231/17): the card's fact, the ordinary card's step and the
    composer's refusal all say so."""
    from ordnung.drafts.compose import NO_HARDSHIP_OBJECTION

    alternative = letter_advice("landlord_notice", today=TODAY, extraordinary=True, alternative=True)
    fristlos = letter_advice("landlord_notice", today=TODAY, extraordinary=True)
    ordinary = letter_advice("landlord_notice", today=TODAY)
    assert alternative is not None and fristlos is not None and ordinary is not None
    [step] = [step for step in ordinary.steps if step.startswith("No hardship objection when")]
    for text in (alternative.facts[0].text, fristlos.facts[0].text, step, NO_HARDSHIP_OBJECTION):
        assert "can undo the notice without notice period" in text
        assert "not if that already happened within the last two years" in text
        assert "but under current law not a notice with a notice period given as well" in text
        assert "still undo it" not in text


def test_paying_the_arrears_names_what_must_be_paid_and_the_public_body_undertaking() -> None:
    """Final review 3: § 569 Abs. 3 Nr. 2 S. 1 BGB counts all rent due and the compensation for use (§ 546a
    Abs. 1 BGB) by then — and a public body (Jobcenter, Sozialamt) undertaking to pay it, the usual route
    for a tenant who can't pay. The "never a notice with a notice period" part holds under current law only:
    the pending Mietrecht II bill would change it, and the rules' re-check list says where to update."""
    from ordnung.drafts.compose import NO_HARDSHIP_OBJECTION
    from ordnung.rules.advice import ARREARS_CURE

    for text in (ARREARS_CURE, NO_HARDSHIP_OBJECTION):
        assert "all rent due by then" in text and "(§ 546a BGB)" in text
        assert "Jobcenter or Sozialamt promising to pay it" in text
        assert "under current law not a notice with a notice period given as well" in text
    [pending] = catalog.PENDING_CHANGES
    assert "Mietrecht II" in pending.change and "§ 573 Abs. 4 BGB" in pending.change
    assert all(catalog.get_rule(rule_id) for rule_id in pending.rule_ids)
    assert "ARREARS_CURE" in pending.update and pending.source.startswith("https://")


def test_a_notice_too_short_for_its_period_counts_from_its_arrival() -> None:
    """Review round 4 of phase 2: an ordinary notice dated 25 Aug 2026 "zum 31.10.2026" that arrived on Fri
    28 Aug (after the third working day of August) can end the tenancy on 30 Nov at the earliest (§ 573c Abs. 1
    BGB). Only the stated end's objection (Mon 31 Aug, passed three days after it arrived) was filed, and the
    card said it had passed; the objection from the end such a notice usually has instead is open until 30 Sep."""
    end, written, arrived = D("2026-10-31"), D("2026-08-25"), D("2026-08-28")
    assert routing.short_notice(end, letter_date=written, arrived=arrived) == "short"
    assert (
        routing.short_notice(end, letter_date=written) == "short"
    )  # arrived late in the month: from its date too
    assert routing.short_notice(D("2026-11-30"), letter_date=written, arrived=arrived) is None
    assert routing.short_notice(D("2026-10-31"), letter_date=D("2026-08-03"), arrived=D("2026-08-04")) is None
    assert routing.short_notice(D("2026-10-15"), letter_date=D("2026-09-20")) == "passed"
    assert routing.short_notice(None, letter_date=written) is None
    assert routing.short_notice(end, letter_date=None) is None
    [objection] = routing.derived_deadlines("landlord_notice", end=end, letter_date=written, arrived=arrived)
    assert objection.spec.legal_basis == "§ 574b Abs. 2, § 573c Abs. 1 BGB"
    receipt = compute_due(
        objection.spec,
        ctx(
            document_date="2026-08-25",
            received_date="2026-08-28",
            received_confirmed=True,
            today="2026-09-02",
            letter_kind="landlord_notice",
        ),
    )
    assert receipt.due_date == "2026-09-30"
    card = letter_advice("landlord_notice", today=D("2026-09-02"), short_period=True)
    assert card is not None and card.urgent
    assert card.steps[0].startswith("Your tenancy would end earlier than a landlord's notice")
    assert "may still be open" in card.steps[0] and "(§ 573c Abs. 1 BGB)" in card.steps[0]
    alternative = letter_advice(
        "landlord_notice", today=D("2026-09-02"), extraordinary=True, alternative=True, short_period=True
    )
    assert (
        alternative is not None
        and "counts back two months from that earliest end" in alternative.facts[0].text
    )


def test_a_short_notice_names_the_usual_period_not_a_minimum() -> None:
    """Final review 2: § 573c BGB sets about three months (and less for a furnished room, Abs. 3), no fixed
    minimum."""
    card = letter_advice("landlord_notice", today=TODAY, objection_todo=False, objection_passed=True)
    assert card is not None
    assert "usually about three months, § 573c Abs. 1 BGB" in card.steps[0]
    assert "at least three months" not in card.steps[0]


def test_a_notice_hilfsweise_with_notice_period_keeps_its_objection_to_do() -> None:
    fristlos = _notice("Wir kündigen fristlos wegen Zahlungsverzugs.")
    both = _notice(
        "kündigen wir das Mietverhältnis fristlos, hilfsweise fristgerecht zum 31.12.2026",
        end="2026-12-31",
        summary="The landlord terminates without notice, alternatively with notice to 31 Dec 2026.",
    )
    careful = _notice("Wir kündigen fristlos, vorsorglich auch ordentlich zum 31.12.2026.", end="2026-12-31")
    assert routing.extraordinary_notice(fristlos) and not routing.alternative_notice(fristlos)
    assert routing.extraordinary_notice(both) and routing.alternative_notice(both)
    assert routing.alternative_notice(careful)
    titled = _notice("Wir kündigen fristlos.", title="Fristlose, hilfsweise fristgerechte Kündigung")
    assert routing.alternative_notice(titled)
    # "vorsorglich" alone (e.g. against a tacit extension, § 545 BGB) is no alternative notice
    tacit = _termination(
        kind="rent_lease", summary="Einer stillschweigenden Verlängerung widersprechen wir vorsorglich."
    )
    assert not routing.alternative_notice(tacit)


@pytest.mark.parametrize(
    "quote",
    [
        "Wir kündigen das Mietverhältnis fristlos, zugleich vorsorglich zum 31.01.2027.",
        "Wir kündigen fristlos wegen Zahlungsverzugs, andernfalls zum 31.01.2027.",
        "Wir kündigen fristlos wegen Zahlungsverzugs, anderenfalls zum 31. Januar 2027.",
        "Wir kündigen fristlos. Ersatzweise kündigen wir zum 31.01.2027.",
        "Wir kündigen fristlos. Ersatzweise kündigen wir zum nächstmöglichen Termin.",
        "Wir kündigen fristlos, spätestens zum nächstmöglichen Zeitpunkt.",
        "Wir kündigen fristlos. Sollte die fristlose Kündigung unwirksam sein, kündigen wir zum nächstzulässigen "
        "Termin.",
        "Wir kündigen fristlos, für den Fall der Unwirksamkeit zum nächstmöglichen Termin.",
        "Wir kündigen fristlos, für den Fall, dass die fristlose Kündigung unwirksam ist, zum 31.1.27.",
        "We terminate without notice, at the latest at the next possible date.",
        # review round 4 of phase 2: "zum/mit Ablauf des …", abbreviated or ISO dates, a month's end, the next
        # permissible date in two words and the end of the notice period
        "Wir kündigen das Mietverhältnis fristlos, spätestens zum Ablauf des 31.12.2026.",
        "Wir kündigen das Mietverhältnis fristlos, spätestens mit Ablauf des 31. Dezember 2026.",
        "Wir kündigen das Mietverhältnis fristlos, jedenfalls aber zum nächsten zulässigen Termin.",
        "Wir kündigen das Mietverhältnis fristlos, spätestens zum nächsten möglichen Termin.",
        "Wir kündigen das Mietverhältnis fristlos und vorsorglich zum Ende der gesetzlichen Kündigungsfrist.",
        "Wir kündigen fristlos, vorsorglich zum Ablauf des 31.01.2027.",
        "Wir kündigen fristlos, zugleich vorsorglich mit Ablauf des 31.01.2027.",
        "Wir kündigen fristlos, vorsorglich zum 31. Jan. 2027.",
        "Wir kündigen fristlos, vorsorglich auch zum Ende Januar 2027.",
        "Wir kündigen fristlos, vorsorglich per Ende Januar 2027.",
        "Wir kündigen fristlos, vorsorglich zum Monatsende Januar 2027.",
        "Wir kündigen fristlos, vorsorglich zum 2027-01-31.",
        "Wir kündigen fristlos. Ersatzweise kündigen wir zum Ablauf des 31.01.2027.",
        # the words alone, with no end (review round 4: each branch needs its own case)
        "Wir kündigen fristlos. Ersatzweise kündigen wir fristgerecht.",
        "Wir kündigen fristlos, andernfalls ordentlich.",
        "Wir kündigen fristlos. Sollte die fristlose Kündigung unwirksam sein, kündigen wir ordentlich.",
        "Wir kündigen fristlos, vorsorglich zum 30.09.2026.",
    ],
)
@pytest.mark.parametrize("end", [None, "2026-09-30"])
def test_a_notice_without_notice_period_that_names_a_later_end_gives_one_in_the_alternative(
    quote: str, end: str | None
) -> None:
    """Review round 3 of phase 2: an ordinary notice given in the alternative without "hilfsweise" or
    "ordentlich" was read as none — no objection to-do, the letter refused and the card saying the objection
    doesn't apply. It is excluded only if the grounds for the notice without notice period existed (§ 574
    Abs. 1 S. 2 BGB; BGH VIII ZR 323/18): when unsure, it is an ordinary notice."""
    notice = _notice(quote, end=end)
    assert routing.notice_without_period(notice) == "certain"
    assert routing.alternative_notice(notice) and not routing.objection_excluded(notice)
    [objection] = routing.derived_deadlines("landlord_notice", end=D(end) if end else None, alternative=True)
    assert objection.rule_id == "bgb_574b"


@pytest.mark.parametrize(
    ("quote", "letter_date"),
    [
        ("Wir kündigen fristlos wegen Zahlungsverzugs.", "2026-09-20"),
        # an end less than two months away is the notice's own (or the day to move out)
        ("Wir kündigen fristlos zum 30.09.2026.", "2026-09-20"),
        ("Wir kündigen fristlos. Räumen Sie die Wohnung bis zum 31.10.2026.", "2026-09-20"),
        ("Wir kündigen fristlos zum 31.02.2027.", "2026-09-20"),  # no calendar date
        # a later end or the next permissible date said of no notice without notice period
        ("Wir kündigen zum 31.01.2027 wegen Eigenbedarfs.", "2026-09-20"),
    ],
)
def test_an_end_of_the_notice_itself_gives_no_notice_in_the_alternative(quote: str, letter_date: str) -> None:
    notice = _notice(quote, document_date=letter_date)
    assert not routing.alternative_notice(notice)


@pytest.mark.parametrize(
    ("quote", "end"),
    [
        (
            "Hiermit kündigen wir das Mietverhältnis unter Einhaltung der vertraglichen Kündigungsfrist. Eine "
            "fristlose Kündigung nach § 543 BGB behalten wir uns ausdrücklich vor.",
            None,
        ),
        (
            "Hiermit kündigen wir das Mietverhältnis wegen Eigenbedarfs. Eine fristlose Kündigung gemäß § 543 Abs. 2 "
            "Nr. 3 BGB bleibt ausdrücklich vorbehalten.",
            None,
        ),
        (
            "Hiermit kündigen wir das Mietverhältnis zum 31.10.2026. Ein Recht zur fristlosen Kündigung nach § 543 "
            "BGB behalten wir uns vor.",
            "2026-10-31",
        ),
        (
            "Hiermit kündigen wir das Mietverhältnis. Eine Kündigung nach § 543 BGB behalten wir uns vor.",
            None,
        ),
        (
            "Wir behalten uns eine Kündigung nach § 569 Abs. 3 BGB vor; heute kündigen wir zum 31.10.2026.",
            None,
        ),
        (
            "Hiermit kündigen wir das Mietverhältnis zum 31.10.2026. Von einer fristlosen Kündigung sehen wir ab.",
            None,
        ),
        (
            "Hiermit kündigen wir das Mietverhältnis zum 31.10.2026. Auf eine fristlose Kündigung verzichten wir.",
            None,
        ),
        ("Wir kündigen das Mietverhältnis. Von einer fristlosen Kündigung sehen wir vorerst ab.", None),
        ("Wir verzichten auf eine fristlose Kündigung und kündigen zum 31.10.2026.", "2026-10-31"),
        ("Wir wären zur fristlosen Kündigung berechtigt; wir kündigen zum 31.10.2026.", "2026-10-31"),
        ("Das Recht, fristlos zu kündigen, bleibt vorbehalten. Wir kündigen zum 31.10.2026.", "2026-10-31"),
    ],
)
def test_a_notice_that_reserves_or_refuses_one_without_notice_period_is_an_ordinary_one(
    quote: str, end: str | None
) -> None:
    """Review round 4 of phase 2: a § 543/§ 569 BGB citation inside a reservation, and a refusal ("sehen wir
    ab", "verzichten wir"), made an ordinary notice "certainly fristlos" — no objection to-do, the letter
    refused. The reservation now governs a citation too (ADR 0010 §4)."""
    notice = _notice(quote, end=end)
    assert routing.notice_without_period(notice) is None
    assert not routing.objection_excluded(notice)


@pytest.mark.parametrize(
    "quote",
    [
        "Hiermit kündigen wir das Mietverhältnis gemäß § 543 Abs. 2 Nr. 3 BGB.",
        "Wir kündigen das Mietverhältnis nach § 569 Abs. 3 BGB wegen Zahlungsverzugs.",
    ],
)
def test_a_statute_alone_makes_a_notice_only_probably_one_without_notice_period(quote: str) -> None:
    """Review round 4 of phase 2: a citation is named in reservations, threats and refusals as often as in the
    notice itself, so alone it keeps the objection to-do and letter (the card says it may be one)."""
    notice = _notice(quote)
    assert routing.notice_without_period(notice) == "probable"
    assert not routing.objection_excluded(notice) and not routing.alternative_notice(notice)
    later = _notice(f"{quote} Hilfsweise zum 31.01.2027.")
    assert routing.alternative_notice(later)
    assert routing.alternative_notice(_notice("Wir kündigen gemäß § 543 BGB, spätestens zum 31.01.2027."))


def test_without_the_letters_date_any_later_end_gives_notice_in_the_alternative() -> None:
    """The safe side: without the letter's date, an end it names can't be told from the notice's own."""
    notice = _notice("Wir kündigen fristlos zum 30.09.2026.", document_date=None)
    assert routing.alternative_notice(notice)


def test_only_the_notices_own_words_give_notice_in_the_alternative() -> None:
    """Review round 4: the model's summary ("Alternatively you may pay all arrears") is not the landlord
    giving notice with a notice period in the alternative, so no hardship objection is offered."""
    fristlos = _notice(
        "Hiermit kündigen wir das Mietverhältnis fristlos.",
        summary="Your landlord terminates without notice for rent arrears. Alternatively you may pay all arrears.",
    )
    assert routing.extraordinary_notice(fristlos) and not routing.alternative_notice(fristlos)


@pytest.mark.parametrize(
    "quote",
    [
        "Hiermit kündigen wir das Mietverhältnis fristlos und behalten uns die Geltendmachung weiterer "
        "Ansprüche vor.",
        "Hiermit erklären wir die fristlose Kündigung des Mietverhältnisses und behalten wir uns weitere "
        "Ansprüche vor.",
        "Wir kündigen fristlos gemäß § 543 BGB; die Rechte aus § 546a BGB bleiben vorbehalten.",
        "Wir kündigen fristlos, behalten uns aber Schadensersatz vor.",
    ],
)
def test_reserving_something_else_doesnt_hide_a_notice_without_notice_period(quote: str) -> None:
    """Review round 4: only a reservation of the notice itself makes it "only reserved"."""
    assert routing.extraordinary_notice(_notice(quote))


@pytest.mark.parametrize(
    "quote",
    [
        "Eine fristlose Kündigung behalten wir uns vor.",
        "Eine fristlose Kündigung wegen des Zahlungsverzugs behalten wir uns ausdrücklich vor.",
        "Wir behalten uns eine fristlose Kündigung vor.",
        "Sollten Sie nicht zahlen, behalten wir uns die fristlose Kündigung vor.",
        "Vorbehaltlich einer außerordentlichen Kündigung endet das Mietverhältnis ordentlich.",
    ],
)
def test_a_reserved_notice_without_notice_period_is_not_one(quote: str) -> None:
    assert not routing.extraordinary_notice(_notice(quote))


@pytest.mark.parametrize(
    ("quote", "end", "written"),
    [
        # "außerordentlich" as an intensifier of something else, and the notice itself called ordinary
        (
            "Aufgrund Ihres außerordentlich störenden Verhaltens kündigen wir das Mietverhältnis ordentlich zum "
            "30.11.2026.",
            "2026-11-30",
            "2026-10-05",
        ),
        (
            "Aufgrund der außerordentlich hohen Sanierungskosten kündigen wir das Mietverhältnis zum 31.10.2026.",
            "2026-10-31",
            "2026-09-20",
        ),
        (
            "Aufgrund Ihres außerordentlich störenden Verhaltens kündigen wir das Mietverhältnis.",
            None,
            "2026-09-20",
        ),
        # a negation after the wording, at the end of its clause
        (
            "Wir kündigen das Mietverhältnis zum 31.10.2026; eine fristlose Kündigung ist damit nicht verbunden.",
            "2026-10-31",
            "2026-09-20",
        ),
        (
            "Eine außerordentliche Kündigung sprechen wir nicht aus. Wir kündigen zum 31.10.2026.",
            "2026-10-31",
            "2026-09-20",
        ),
    ],
)
def test_an_intensifier_or_a_denied_notice_without_period_keeps_the_objection(
    quote: str, end: str | None, written: str
) -> None:
    """Review round 2 of phase 2: "außerordentlich" anywhere made an ordinary notice one without notice period
    — no objection to-do, and the objection letter refused (§ 574 BGB applies to it). The objection counts
    back from the next permissible end: the end is too short (or not given) for a landlord's period (§ 573c
    Abs. 1 BGB: 31 Dec 2026 → objection by Sat 31 Oct 2026)."""
    extraction = _notice(quote, end=end, title="Ordinary notice of termination", document_date=written)
    assert routing.notice_without_period(extraction) is None
    assert not routing.extraordinary_notice(extraction) and not routing.objection_excluded(extraction)
    [objection] = routing.derived_deadlines(
        "landlord_notice", end=routing.announced_end(extraction), letter_date=D(written)
    )
    assert objection.rule_id == "bgb_574b" and "nächstmöglichen" in objection.spec.text
    receipt = compute_due(
        objection.spec, ctx(document_date=written, letter_kind="landlord_notice", today=D("2026-10-06"))
    )
    assert receipt.due_date == "2026-10-31"


@pytest.mark.parametrize(
    "quote",
    [
        "Hiermit kündigen wir das Mietverhältnis außerordentlich.",
        "Wir kündigen das Mietverhältnis außerordentlich zum 31.10.2026.",
        "Außerordentliche Kündigung des Mietverhältnisses",
    ],
)
def test_a_notice_only_called_extraordinary_is_probably_one_and_keeps_the_objection(quote: str) -> None:
    """Review round 2 of phase 2: "außerordentlich" alone may be a special termination with the statutory
    period (§ 573d BGB), so the objection to-do and letter are kept, and the card says it may be fristlos."""
    end = "2026-10-31" if "31.10" in quote else None
    extraction = _notice(quote, end=end)
    assert routing.notice_without_period(extraction) == "probable"
    assert routing.extraordinary_notice(extraction) and not routing.objection_excluded(extraction)
    [objection] = routing.derived_deadlines(
        "landlord_notice",
        end=routing.announced_end(extraction),
        letter_date=D("2026-09-20"),
        extraordinary=routing.objection_excluded(extraction),
    )
    assert "nächstmöglichen" in objection.spec.text
    card = letter_advice("landlord_notice", today=TODAY, extraordinary=True, probable=True)
    assert card is not None and card.urgent and card.draft == "objection"
    assert card.facts[0].title == "This may be a notice without notice period"
    assert "§ 573d BGB" in card.facts[0].text
    # the same notice said fristlos is certainly one: no to-do, no letter
    fristlos = _notice("Hiermit kündigen wir das Mietverhältnis außerordentlich und fristlos.")
    assert routing.notice_without_period(fristlos) == "certain" and routing.objection_excluded(fristlos)


@pytest.mark.parametrize(
    "quote",
    [
        "Hiermit kündigen wir das Mietverhältnis wegen Eigenbedarfs fristgerecht zum nächstmöglichen Termin.",
        "Wir kündigen das Mietverhältnis ordentlich zum nächstmöglichen Zeitpunkt.",
    ],
)
def test_a_notice_to_the_next_possible_date_gets_an_objection_to_do(quote: str) -> None:
    """Review round 2 of phase 2: a notice that writes no end got no objection deadline, and its card asked
    for an end the notice doesn't write. The objection counts back from the earliest end (§ 573c Abs. 1 BGB)."""
    extraction = _notice(quote, end=None)
    assert not routing.extraordinary_notice(extraction)
    [objection] = routing.derived_deadlines("landlord_notice", end=None, letter_date=D("2026-09-20"))
    assert "nächstmöglichen" in objection.spec.text
    receipt = compute_due(objection.spec, ctx(document_date="2026-09-20", letter_kind="landlord_notice"))
    # arrived 20 Sep (after the third working day): the earliest end is 31 Dec 2026, objection by 31 Oct
    assert receipt.due_date == "2026-10-31" and NEXT_END_WARNING in receipt.warnings


@pytest.mark.parametrize(
    "quote",
    [
        "Wir kündigen das Mietverhältnis fristlos gemäß § 543 BGB. Sollte die fristlose Kündigung unwirksam sein, "
        "gilt sie als ordentliche Kündigung mit gesetzlicher Frist.",
        "Wir kündigen fristlos und zugleich ordentlich zum nächstmöglichen Termin.",
        "Wir kündigen fristlos; im Fall der Unwirksamkeit ist sie in eine ordentliche Kündigung umgedeutet.",
    ],
)
def test_a_notice_in_the_alternative_without_hilfsweise_is_one(quote: str) -> None:
    """Review round 2 of phase 2: an ordinary notice given in the alternative without the word "hilfsweise"
    read as an ordinary notice with no end, and got no objection deadline."""
    extraction = _notice(quote, end=None)
    assert routing.notice_without_period(extraction) == "certain"
    assert routing.alternative_notice(extraction) and not routing.objection_excluded(extraction)
    [objection] = routing.derived_deadlines("landlord_notice", end=None, letter_date=D("2026-09-20"))
    assert "nächstmöglichen" in objection.spec.text


def test_the_objection_is_only_for_a_home() -> None:
    """§§ 574–574b BGB are rules for Wohnraum: a garage, parking space or business premises let on its own
    (§ 578 BGB) has no hardship objection — said on the to-do, the card and in the catalog."""
    [objection] = routing.derived_deadlines("landlord_notice", end=D("2027-03-31"))
    assert (
        "garage, parking space or business premises" in objection.action and "§ 578 BGB" in objection.action
    )
    card = letter_advice("landlord_notice", today=TODAY)
    assert card is not None and any("garage" in step and "§ 578 BGB" in step for step in card.steps)
    assert "garage" in catalog.get_rule("bgb_574b").summary


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
        (800.0, 1000.0, "warn", "more than the 20 % cap (at most €960.00)"),
        (800.0, 940.0, "warn", "more than the 15 % cap that many cities have (at most €920.00"),
        (800.0, 880.0, "good", "within both caps"),
        # the caps are limits in euros: compared exactly, never from a rounded percentage
        (800.0, 920.0, "good", "within both caps"),
        (800.0, 920.30, "warn", "within the 20 % cap, but more than the 15 % cap"),
        (1000.0, 1150.40, "warn", "more than the 15 % cap"),
        (500.0, 600.20, "warn", "more than the 20 % cap (at most €600.00)"),
        (1000.0, 1200.45, "warn", "more than the 20 % cap"),
        (800.0, 960.0, "warn", "within the 20 % cap"),
        (None, None, "info", "couldn't read the old and new rent"),
    ],
)
def test_rent_cap_fact(old: float | None, new: float | None, tone: str, words: str) -> None:
    card = letter_advice("rent_increase", today=TODAY, old_amount=old, new_amount=new)
    assert card is not None
    [fact] = card.facts
    assert fact.tone == tone and words in fact.text
    assert fact.citation == catalog.citation("bgb_558_3")


def test_a_rise_just_over_a_cap_shows_two_decimals() -> None:
    card = letter_advice("rent_increase", today=TODAY, old_amount=800.0, new_amount=920.30)
    assert card is not None and card.facts[0].title == "Rent rises by 15.04 %"
    within = letter_advice("rent_increase", today=TODAY, old_amount=1000.0, new_amount=1149.60)
    assert within is not None and within.facts[0].title == "Rent rises by 14.96 %"
    assert within.facts[0].tone == "good"
    plain = letter_advice("rent_increase", today=TODAY, old_amount=800.0, new_amount=880.0)
    assert plain is not None and plain.facts[0].title == "Rent rises by 10.0 %"


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
    assert billing_period(STATEMENT) == BillingPeriod(D("2024-12-31"), True, "01.01.2024 – 31.12.2024", True)
    assert billing_period("Abrechnungsperiode 1.7.2024 bis 30.6.2025") == BillingPeriod(
        D("2025-06-30"), True, "01.07.2024 – 30.06.2025", True
    )
    assert billing_period("Abrechnungsjahr: 2024") == BillingPeriod(D("2024-12-31"), False, "2024")
    assert billing_period("Abrechnungszeitraum 01.01.2024 – 31.02.2024") is None
    assert billing_period("Abrechnungsjahr 2024/12") is None  # not a split year
    assert billing_period("Abrechnungszeitraum 01.01. – 31.12.") is None  # no year to end in
    assert billing_period("Zeitraum 31.12.2024 – 01.01.2024") is None  # ends before it starts
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
            BillingPeriod(D("2024-06-30"), True, "01.07.2023 – 30.06.2024", True),
        ),
        (
            "Heizkostenabrechnung Abrechnungsjahr 2024 (01.07.2024 - 30.06.2025)",
            BillingPeriod(D("2025-06-30"), True, "01.07.2024 – 30.06.2025", True),
        ),
        # "vom … bis zum …" without a label: its end, but not called the billing period
        (
            "Wir rechnen die Kosten vom 01.07.2023 bis zum 30.06.2024 ab.",
            BillingPeriod(D("2024-06-30"), True, "01.07.2023 – 30.06.2024", False),
        ),
        # the previous year's period is not this statement's: the later billing year wins
        (
            "Abrechnungszeitraum 2024, Vorjahr: Abrechnungszeitraum 01.01.2023 - 31.12.2023",
            BillingPeriod(D("2024-12-31"), False, "2024"),
        ),
        # a split year alone ends at the latest on 31 December of its second year
        ("Abrechnungsjahr 2023/24", BillingPeriod(D("2024-12-31"), False, "2023/24")),
        # two-digit years; a range that ends after the statement arrived is a new prepayment period (a
        # bare "Zeitraum" is no label: review round 2 of phase 2)
        (
            "Zeitraum 01.01.24-31.12.24; neue Vorauszahlung 01.01.2026 - 31.12.2026",
            BillingPeriod(D("2024-12-31"), True, "01.01.2024 – 31.12.2024", False),
        ),
        # the period in words, as an ISO range, in months, below its label
        (
            "Abrechnung für den Zeitraum vom 1. Januar 2024 bis 31. Dez. 2024",
            BillingPeriod(D("2024-12-31"), True, "01.01.2024 – 31.12.2024", True),
        ),
        (
            "Betriebskostenabrechnung (Zeitraum 2024-07-01 bis 2025-06-30)",
            BillingPeriod(D("2025-06-30"), True, "01.07.2024 – 30.06.2025", True),
        ),
        (
            "Zeitraum: Juli bis Juni 2025",
            BillingPeriod(D("2025-06-30"), True, "01.07.2024 – 30.06.2025", False),
        ),
        (
            "Heizkostenabrechnung\nZeitraum: Juli bis Juni 2025",
            BillingPeriod(D("2025-06-30"), True, "01.07.2024 – 30.06.2025", True),
        ),
        (
            "Abrechnungszeitraum 01/2024 – 12/2024",
            BillingPeriod(D("2024-12-31"), True, "01.01.2024 – 31.12.2024", True),
        ),
        (
            "Abrechnungszeitraum:\n01.01.2024 - 31.12.2024",
            BillingPeriod(D("2024-12-31"), True, "01.01.2024 – 31.12.2024", True),
        ),
        # a billing year named with the statement, not only with the word Abrechnungsjahr
        ("Betriebskostenabrechnung für das Jahr 2024", BillingPeriod(D("2024-12-31"), False, "2024")),
        ("Heizkostenabrechnung 2023/2024", BillingPeriod(D("2024-12-31"), False, "2023/2024")),
        ("Operating-cost statement 2024", BillingPeriod(D("2024-12-31"), False, "2024")),
    ],
)
def test_billing_period_takes_the_latest_end_of_every_period_named(text: str, period: BillingPeriod) -> None:
    assert billing_period(text, before=D("2025-12-01")) == period


@pytest.mark.parametrize(
    "text",
    [
        # the tenant moved out mid-year: their time in the flat is not the landlord's billing period
        "Betriebskostenabrechnung 2024\nAbrechnungsjahr 2024\nIhr Nutzungszeitraum: 01.01.2024 - 30.06.2024\n"
        "Nachzahlung 95,00 EUR",
        "Betriebskostenabrechnung 2024\nMietdauer 01.01.2024 bis 30.06.2024 (Auszug)\nNachzahlung 95,00 EUR",
        # a cost item's service period ends earlier in the named year, and is no split year's own months
        "Operating-cost statement 2024\nWartung Heizung 01.03.2023 - 28.02.2024\nNachzahlung 95,00 EUR",
    ],
)
def test_a_shorter_range_never_makes_a_named_billing_year_end_earlier(text: str) -> None:
    """Review round 1: § 556 Abs. 3 S. 2 BGB counts from the end of the landlord's billing period (31 Dec
    2024: due by 31 Dec 2025), not from a move-out — the card called a statement that arrived on 15 Nov 2025
    "probably too late" and its back-payment "may not be owed"."""
    assert billing_period(text, before=D("2025-11-15")) == BillingPeriod(D("2024-12-31"), False, "2024")
    assert not statement_late(text, D("2025-11-15"), True, None)
    card = letter_advice(
        "operating_costs", today=D("2025-11-20"), arrived=D("2025-11-15"), arrival_confirmed=True, text=text
    )
    assert card is not None and not card.urgent
    assert "too late" not in card.facts[0].title.casefold()


def test_a_split_billing_year_gives_way_to_its_own_months_only() -> None:
    """A split year ("2023/2024") gives way to a range that starts in its first year and ends in its last (its
    own months: a heating year), never to another range that ends in it (a cost item's service period)."""
    own = "Heizkostenabrechnung 2023/2024\nHeizung 01.07.2023 - 30.06.2024\nNachzahlung 95,00 EUR"
    assert billing_period(own, before=D("2025-11-15")) == BillingPeriod(
        D("2024-06-30"), True, "01.07.2023 – 30.06.2024", False
    )
    other = "Heizkostenabrechnung 2023/2024\nWartung 01.03.2022 - 28.02.2024\nNachzahlung 95,00 EUR"
    assert billing_period(other, before=D("2025-11-15")) == BillingPeriod(D("2024-12-31"), False, "2023/2024")


def test_a_tenants_own_period_alone_is_no_billing_period() -> None:
    assert billing_period("Ihr Nutzungszeitraum: 01.01.2024 - 30.06.2024", before=D("2025-11-15")) is None
    assert billing_period("Mietdauer 01.01.2024 bis 30.06.2024 (Auszug)", before=D("2025-11-15")) is None
    # … and a range the letter calls its billing period next to a move-out is kept, but never for certain
    # (review round 2 of phase 2): a departing tenant's deadline runs from the landlord's annual period
    assert billing_period(
        "Abrechnungszeitraum 01.01.2024 - 31.12.2024 (Auszug 30.06.2024)", before=D("2025-11-15")
    ) == BillingPeriod(D("2024-12-31"), True, "01.01.2024 – 31.12.2024", False)


#: Review round 2 of phase 2: a cost item's own "Zeitraum", or the tenant's period labelled as the billing
#: period, made an on-time statement "certainly too late" (§ 556 Abs. 3 S. 2 BGB counts from the end of the
#: landlord's billing period — here 31 Dec 2025, so the statement is due by 31 Dec 2026).
COST_ITEM_AND_MOVE_OUT_PERIODS = [
    "Betriebskostenabrechnung 2025\nGebäudeversicherung\nZeitraum: 01.04.2024 – 31.03.2025\nNachzahlung: 180,00 €",
    "Betriebskostenabrechnung 2025 – Gebäudeversicherung (Zeitraum 01.04.2024 - 31.03.2025), Nachzahlung: 180,00 €",
    "Abrechnungsjahr 2025\nWartung Rauchwarnmelder, Zeitraum 01.07.2024 – 30.06.2025\nNachzahlung 20,00 €",
    "Betriebskostenabrechnung 2025\nAbrechnungszeitraum: 01.01.2025 – 30.04.2025 (Auszug)\nNachzahlung 20,00 €",
    "Betriebskostenabrechnung 2025\nAbrechnungszeitraum: 01.01.2025 – 30.04.2025\nMietende: 30.04.2025\nNachzahlung 20,00 €",
    # a bare "Zeitraum" after the statement's name, ending before the year it names, is no reason either
    "Betriebskostenabrechnung 2025\nZeitraum: 01.04.2024 – 31.03.2025\nNachzahlung: 180,00 €",
]


@pytest.mark.parametrize("text", COST_ITEM_AND_MOVE_OUT_PERIODS)
def test_a_cost_items_or_the_tenants_period_never_makes_a_statement_late(text: str) -> None:
    arrived = D("2026-07-15")
    assert billing_period(text, before=arrived) == BillingPeriod(D("2025-12-31"), False, "2025")
    assert not statement_late(text, arrived, True, "NW")
    card = letter_advice(
        "operating_costs",
        today=D("2026-07-20"),
        arrived=arrived,
        arrival_confirmed=True,
        region="NW",
        text=text,
    )
    assert card is not None and not card.urgent
    assert card.facts[0].title == "Probably on time"


#: The demo's statement (and most real ones) writes the tenant's own time beside the billing period.
BESIDE = "Betriebskostenabrechnung 2025\nAbrechnungszeitraum 01.01.–31.12.2025 · Ihr Nutzungszeitraum 01.10.–31.12.2025 (92 Tage)\nNachzahlung 184,30 €"
BESIDE_FIRST = "Betriebskostenabrechnung 2025\nIhr Nutzungszeitraum: 01.10.–31.12.2025 · Abrechnungszeitraum 01.01.–31.12.2025\nNachzahlung 184,30 €"


@pytest.mark.parametrize("text", [BESIDE, BESIDE_FIRST], ids=["tenant-after", "tenant-before"])
def test_the_tenants_period_written_beside_the_billing_period_leaves_it_the_billing_period(text: str) -> None:
    """Review round 2 of phase 2 (found by the UI audit of the fix for the move-out period): a tenant marker
    that labels a range of its own says the other range is *not* the tenant's — the demo's statement lost its
    billing period ("doesn't call it the billing period") and was only "probably" on time."""
    period = BillingPeriod(D("2025-12-31"), True, "01.01.2025 – 31.12.2025", True)
    assert billing_period(text, before=D("2026-09-10")) == period
    card = letter_advice(
        "operating_costs", today=D("2026-09-27"), arrived=D("2026-09-10"), arrival_confirmed=True, text=text
    )
    assert card is not None and card.facts[0].title == "On time"
    # … and a statement that arrives after 31 Dec 2026 is certainly late
    assert statement_late(text, D("2027-01-15"), True, None) is True


def test_a_marker_before_its_own_range_still_marks_it_after_a_gap() -> None:
    """The marker's dates may follow a colon and "vom": the tenant's range is never the billing period."""
    text = "Abrechnungsjahr 2025\nMietdauer: vom 01.01.2025 bis 30.04.2025\nNachzahlung 20,00 €"
    assert billing_period(text, before=D("2026-07-15")) == BillingPeriod(D("2025-12-31"), False, "2025")


def test_a_labelled_move_out_period_alone_is_at_most_probably_late() -> None:
    text = "Abrechnungszeitraum: 01.01.2025 – 30.04.2025 (Auszug)\nNachzahlung 20,00 €"
    card = letter_advice(
        "operating_costs", today=D("2026-06-20"), arrived=D("2026-06-15"), arrival_confirmed=True, text=text
    )
    assert card is not None
    assert card.facts[0].title == "Probably too late — check the billing period"


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


#: Statements whose own period Ordnung reads in words, as ISO dates or only as a year, next to the
#: previous year's comparison (§ 6a HeizkostenV) or an older prepayment agreement — none was late.
ON_TIME_NEXT_TO_AN_OLDER_RANGE = [
    (
        "Betriebs- und Heizkostenabrechnung für den Zeitraum vom 1. Januar 2025 bis 31. Dezember 2025\n"
        "Nachzahlung: 312,40 EUR\n"
        "Verbrauchsvergleich (§ 6a HeizkostenV): Vorjahreszeitraum 01.01.2024 - 31.12.2024: 9.100 kWh",
        "On time",
    ),
    (
        "Betriebskostenabrechnung 2025 (Zeitraum 2025-01-01 bis 2025-12-31)\n"
        "Vorauszahlungen lt. Vereinbarung vom 01.03.2023 bis 31.12.2024 je 150 EUR, danach 170 EUR",
        "On time",
    ),
    (
        "Betriebskostenabrechnung für das Jahr 2025\nVorjahr (01.01.2024 – 31.12.2024): 2.150,00 EUR\n"
        "Nachzahlung: 310,00 EUR",
        "Probably on time",
    ),
    (
        "Heizkostenabrechnung\nZeitraum: Januar bis Dezember 2025\nVorjahr (01.01.2024 – 31.12.2024)",
        "On time",
    ),
    # only the previous year's range is found: this statement's own period was missed
    ("Heizkostenabrechnung\nVorjahreszeitraum 01.01.2024 - 31.12.2024: 9.100 kWh", "Was it on time?"),
    ("Vorjahres-Abrechnungszeitraum: 01.01.2024 – 31.12.2024", "Was it on time?"),
]


@pytest.mark.parametrize(("text", "title"), ON_TIME_NEXT_TO_AN_OLDER_RANGE)
def test_the_previous_years_comparison_never_makes_a_statement_late(text: str, title: str) -> None:
    card = letter_advice(
        "operating_costs",
        today=D("2026-09-26"),
        arrived=D("2026-09-10"),
        arrival_confirmed=True,
        region="BE",
        text=text,
    )
    assert card is not None
    [fact] = card.facts
    assert fact.title == title and "too late" not in fact.title and fact.tone != "warn"


def test_a_range_the_letter_doesnt_call_its_billing_period_is_at_most_probably_late() -> None:
    card = letter_advice(
        "operating_costs",
        today=D("2026-09-26"),
        arrived=D("2026-09-10"),
        arrival_confirmed=True,
        region="BE",
        text="Kosten vom 01.01.2024 bis 31.12.2024\nNachzahlung 120,00 EUR",
    )
    assert card is not None
    [fact] = card.facts
    assert fact.title == "Probably too late — check the billing period" and fact.tone == "warn"
    assert "doesn't call it the billing period" in fact.text and "may owe no back-payment" in fact.text
    on_time = letter_advice(
        "operating_costs",
        today=D("2026-09-26"),
        arrived=D("2025-09-10"),
        text="Kosten vom 01.01.2024 bis 31.12.2024",
    )
    assert on_time is not None and on_time.facts[0].title == "Probably on time"
    assert "Its date is before that" in on_time.facts[0].text


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


@pytest.mark.parametrize("letter", ["court_payment_order", "enforcement_order"])
def test_a_labour_courts_order_is_answered_there_within_one_week(letter: str) -> None:
    guidance = send_guidance("objection", letter_kind=letter, today=TODAY, court=True, labour_court=True)
    channels = {c.channel: c for c in guidance.channels}
    assert "portal" not in channels and not channels["email"].allowed
    assert "one week" in guidance.form_note and "ArbGG" in guidance.form_note
    assert channels["registered_letter"].recommended and "labour court" in channels["in_person"].label


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


@pytest.mark.parametrize("letter", ["enforcement_order", "court_payment_order", "landlord_notice"])
@pytest.mark.parametrize("due", ["2026-09-28", "2026-09-29"])
def test_on_the_last_days_the_letter_page_never_says_to_post_it(letter: str, due: str) -> None:
    """Review round 4 of phase 2: on an Einspruch's last day the page said "Post a letter by Mon 28 Sep" and
    recommended Einwurf-Einschreiben — a letter posted then arrives after the Notfrist (§§ 700 Abs. 1, 339
    ZPO). When the usual time to post has passed, it says a letter may arrive too late and ranks the ways that
    reach the recipient the same day first."""
    today = D("2026-09-28")
    guidance = send_guidance("objection", letter_kind=letter, today=today, due=D(due))
    assert guidance.post_too_late and guidance.send_by == "2026-09-28" and guidance.must_arrive_by == due
    assert "Post a letter by" not in guidance.tips[0]
    assert "a letter posted today may arrive too late" in guidance.tips[0]
    first = guidance.channels[0]
    assert first.allowed and first.recommended and first.channel in ("fax", "email")
    assert first.label in guidance.tips[0]
    assert not any(c.recommended for c in guidance.channels[1:])
    letters = [c for c in guidance.channels if c.channel in ("letter", "registered_letter")]
    assert letters and guidance.channels.index(letters[0]) > guidance.channels.index(first)
    # in good time: post it, the signed letter first
    early = send_guidance("objection", letter_kind=letter, today=today, due=D("2026-10-12"))
    assert not early.post_too_late and early.tips[0].endswith("Post a letter by Tue 6 Oct 2026.")


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


# ------------------------------------------------------------------------------------ final review 1


REMINDER_QUOTE = (
    "aus unserer Betriebskostenabrechnung 2023 vom 15.11.2024 ist noch eine Nachzahlung von 312,40 EUR offen."
)


def test_a_reminder_about_an_old_statement_is_not_the_statement() -> None:
    """Final review 1: a landlord's payment reminder names the statement it is about; it is not the
    statement, so no late-statement card (nor "may not be owed") is worked out from its date."""
    landlord = ExtractedParty(name="Hausverwaltung Muster GmbH", kind="landlord")
    reminder = reading(
        kind="dunning",
        title="Reminder: back-payment from the operating-cost statement 2023",
        sender=landlord,
        items=[item(REMINDER_QUOTE)],
        document_date="2026-09-20",
    )
    assert not routing.names_statement(reminder)
    assert routing.names_statement(reminder.model_copy(update={"kind": "rent_lease"}))
    # an English title of a heating statement names it too
    assert routing.names_statement(reading(title="Heating cost statement 2025", sender=landlord))
    assert routing.names_statement(reading(title="Operating and heating costs statement 2025"))


@pytest.mark.parametrize(
    ("text", "dated"),
    [
        (REMINDER_QUOTE, D("2024-11-15")),
        ("Ihr Widerspruch gegen unsere Abrechnung vom 15. November 2024 ist unbegründet.", D("2024-11-15")),
        ("Betriebskostenabrechnung vom 2024-11-15", D("2024-11-15")),
        # two statements named: the earlier date is the earliest the older one can have arrived
        ("Abrechnung vom 01.12.2025 ersetzt die Abrechnung vom 15.11.2024.", D("2024-11-15")),
        # a billing period that starts with "vom" is no date of the statement
        ("Betriebskostenabrechnung vom 01.01.2024 bis 31.12.2024", None),
        ("Abrechnung für den Zeitraum vom 1. Januar 2024 – 31. Dezember 2024", None),
        ("Abrechnungszeitraum vom 01.01.2024 bis 31.12.2024", None),
        # a date without a year, or no full date, or an impossible one, dates nothing
        ("Abrechnung vom 15.11.", None),
        ("Abrechnung vom November 2024", None),
        ("Abrechnung vom 31.02.2024", None),
        ("Abrechnung vom Hausmeister", None),
    ],
)
def test_the_date_a_letter_gives_the_statement(text: str, dated: date | None) -> None:
    assert statement_date(text) == dated


def test_a_later_letter_counts_from_the_statements_own_date() -> None:
    """Final review 1: never the reminder's (or reply's) date as the statement's arrival when its text
    dates the statement earlier — then that date counts, never confirmed."""
    letter = D("2026-09-20")
    assert statement_arrival(REMINDER_QUOTE, letter, True, letter) == (D("2024-11-15"), False, None)
    # the statement itself: its own date isn't earlier than the letter's, so the arrival entered counts
    own = "Betriebskostenabrechnung 2025 vom 08.09.2026\nAbrechnungszeitraum 01.01.2025 - 31.12.2025"
    assert statement_arrival(own, D("2026-09-11"), True, D("2026-09-08")) == (D("2026-09-11"), True, None)
    assert statement_arrival(REMINDER_QUOTE, letter, False, None) == (letter, False, None)  # no letter date
    card = letter_advice(
        "operating_costs",
        today=TODAY,
        arrived=letter,
        arrival_confirmed=True,
        letter_date=letter,
        text=f"Zahlungserinnerung\n{REMINDER_QUOTE}",
    )
    assert card is not None and not card.urgent
    assert card.facts[0].title == "Probably on time"  # the 2023 statement of 15 Nov 2024: on time
    assert not any(step.startswith("Don't pay") for step in card.steps)


#: A late 2024 statement (due by 31 Dec 2025, arrived 17 Jan 2026) that encloses the metering company's
#: heating statement, dated earlier.
ENCLOSING_STATEMENT = (
    "Betriebskostenabrechnung 2024\nAbrechnungszeitraum: 01.01.2024 - 31.12.2024\n"
    "Anlage: Heizkostenabrechnung der Techem vom 20.03.2025\nNachzahlung: 412,00 EUR"
)
#: … and one that names the previous year's statement.
NAMING_LAST_YEARS = (
    "Betriebskostenabrechnung 2024\nAbrechnungszeitraum: 01.01.2024 - 31.12.2024\n"
    "Das Guthaben aus der Abrechnung 2023 vom 10.11.2024 wurde bereits erstattet."
)


def _statement_card(text: str, arrived: date | None, letter: date, today: date) -> LetterAdvice:
    card = letter_advice(
        "operating_costs",
        today=today,
        arrived=arrived or letter,
        arrival_confirmed=arrived is not None,
        letter_date=letter,
        text=text,
    )
    assert card is not None
    return card


def test_another_years_statement_never_replaces_the_arrival() -> None:
    """Final review 2: an earlier "Abrechnung 2023 vom" in the 2024 statement is the previous year's
    statement, not this one's date, so the arrival the person entered counts — and the late statement
    stays late, on the card and on its back-payment."""
    letter, arrived = D("2026-01-15"), D("2026-01-17")
    assert statement_arrival(NAMING_LAST_YEARS, arrived, True, letter) == (arrived, True, None)
    assert statement_arrival(NAMING_LAST_YEARS, None, False, letter) == (None, False, None)
    card = _statement_card(NAMING_LAST_YEARS, arrived, letter, D("2026-01-20"))
    assert card.urgent and card.facts[0].title == "This statement came too late"
    # the back-payment's warning is worked out the same way (:func:`ordnung.ingest.plan.late_statement_warning`)
    arrival = statement_arrival(NAMING_LAST_YEARS, arrived, True, letter)
    assert statement_late(NAMING_LAST_YEARS, arrival.arrived, arrival.confirmed, None, named=arrival.named)


#: Final review 3: later letters that repeat the statement's billing period and date it without its year —
#: a reply to objections (one with the period in brackets, one in its subject) and a corrected statement.
#: Each is about the 2023 statement of 15 Nov 2024, which was on time (due by 31 Dec 2024).
REPLY_WITH_PERIOD = (
    "zu Ihren Einwendungen gegen unsere Nebenkostenabrechnung vom 15.11.2024 (Abrechnungszeitraum 01.01.2023 "
    "bis 31.12.2023) nehmen wir wie folgt Stellung. Die Nachzahlung von 312,40 EUR bleibt bestehen."
)
REPLY_WITH_PERIOD_IN_SUBJECT = (
    "Betreff: Betriebskostenabrechnung, Abrechnungszeitraum 01.01.2023 – 31.12.2023\nSehr geehrte Frau Weber, "
    "zu Ihren Einwendungen gegen unsere Abrechnung vom 15.11.2024 nehmen wir wie folgt Stellung … Bitte "
    "überweisen Sie die Nachzahlung von 312,40 EUR bis 28.02.2025."
)
CORRECTED_STATEMENT = (
    "Korrigierte Betriebskostenabrechnung\nAbrechnungszeitraum 01.01.2023 – 31.12.2023\n"
    "Diese Abrechnung ersetzt unsere Abrechnung vom 15.11.2024. Nachzahlung: 312,40 EUR"
)


@pytest.mark.parametrize(
    ("text", "letter"),
    [
        (REPLY_WITH_PERIOD, D("2026-09-20")),
        (REPLY_WITH_PERIOD_IN_SUBJECT, D("2025-02-10")),
        (CORRECTED_STATEMENT, D("2025-02-10")),
    ],
    ids=["reply", "reply-subject", "corrected"],
)
@pytest.mark.parametrize("entered", [True, False], ids=["arrival-entered", "letter-date-only"])
def test_a_later_letter_that_repeats_the_period_is_never_certainly_late(
    text: str, letter: date, entered: bool
) -> None:
    """Final review 3: a later letter often prints the statement's billing period too, so a date it gives
    "unsere Abrechnung" without the year may be the statement it is about — never proof that the letter is
    the statement. The card says both readings, isn't urgent and never says "came too late", and the
    back-payment carries no warning."""
    arrived = letter + timedelta(days=2) if entered else None
    arrival = statement_arrival(text, arrived or letter, entered, letter)
    assert arrival == (arrived or letter, entered, D("2024-11-15"))
    assert not statement_late(text, arrival.arrived, arrival.confirmed, None, named=arrival.named)
    card = _statement_card(text, arrived, letter, letter + timedelta(days=5))
    fact = card.facts[0]
    assert not card.urgent and not any(step.startswith("Don't pay") for step in card.steps)
    assert fact.title == "Too late only if this letter is the statement itself" and fact.tone == "info"
    assert "names a statement dated Fri 15 Nov 2024" in fact.text
    assert "probably on time and the back-payment (Nachzahlung) is owed" in fact.text
    assert ("This letter arrived later" if entered else "This letter is dated later") in fact.text


@pytest.mark.parametrize(
    "text",
    [
        ENCLOSING_STATEMENT,
        # final review 3: a statement that gives only its billing year, with the same enclosure
        "Betriebskostenabrechnung 2024\nAnlage: Heizkostenabrechnung der Techem vom 20.03.2025\nNachzahlung: 412,00 EUR",
    ],
    ids=["period", "billing-year"],
)
def test_a_statement_dating_an_enclosure_says_both_readings(text: str) -> None:
    """Final review 3: a date without its year may be an enclosure's (the metering company's heating
    statement) in the statement itself, or the statement a later letter is about: Ordnung can't tell which.
    Counting from the day this letter arrived, it is late; from the enclosure's date it would be on time —
    so the card names both and neither calls it certainly late nor probably on time."""
    letter, arrived = D("2026-01-15"), D("2026-01-17")
    assert statement_arrival(text, arrived, True, letter) == (arrived, True, D("2025-03-20"))
    card = _statement_card(text, arrived, letter, D("2026-01-20"))
    fact = card.facts[0]
    assert not card.urgent and fact.title == "Too late only if this letter is the statement itself"
    assert "Only if this letter is the statement itself" in fact.text and "20 Mar 2025" in fact.text
    if "Abrechnungszeitraum" not in text:
        assert fact.text.startswith("The letter names the billing year (2024) but not its dates.")


def test_a_named_statement_date_that_is_late_too_keeps_the_statement_late() -> None:
    """Final review 3: when the date the letter also gives a statement is past the deadline as well, both
    readings say late — the card says so with certainty and the back-payment is warned about."""
    text = "Abrechnungszeitraum: 01.01.2023 - 31.12.2023\nzu Ihren Einwendungen gegen unsere Abrechnung vom 15.01.2025"
    letter, arrived = D("2025-03-10"), D("2025-03-12")
    arrival = statement_arrival(text, arrived, True, letter)
    assert arrival == (arrived, True, D("2025-01-15"))
    assert statement_late(text, arrival.arrived, arrival.confirmed, None, named=arrival.named)
    card = _statement_card(text, arrived, letter, D("2025-03-20"))
    assert card.urgent and card.facts[0].title == "This statement came too late"


def test_a_later_letter_that_arrived_in_time_is_on_time_either_way() -> None:
    """Final review 3: a statement date the letter gives without its year changes nothing when the letter's
    own arrival was in time: whichever reading holds, the statement arrived by then."""
    arrived = D("2024-11-20")
    arrival = statement_arrival(REPLY_WITH_PERIOD, arrived, True, D("2024-11-18"))
    assert arrival == (arrived, True, D("2024-11-15"))
    card = _statement_card(REPLY_WITH_PERIOD, arrived, D("2024-11-18"), D("2024-11-25"))
    assert card.facts[0].title == "On time"


@pytest.mark.parametrize(
    ("text", "counts"),
    [
        # a reply that names the statement with its billing year counts from the statement's date, even when
        # it repeats the statement's period
        (
            "Ihr Widerspruch gegen unsere Betriebskostenabrechnung 2023 vom 15.11.2024 ist unbegründet.\n"
            "Abrechnungszeitraum: 01.01.2023 - 31.12.2023",
            "counts",
        ),
        # without a year, it may be this statement's — or an enclosure's: named, the arrival stays
        ("Operating-cost statement 2023\nIhr Widerspruch gegen unsere Abrechnung vom 15.11.2024 …", "named"),
        (REPLY_WITH_PERIOD, "named"),
        (REPLY_WITH_PERIOD_IN_SUBJECT, "named"),
        (CORRECTED_STATEMENT, "named"),
        # another year's statement, even without a period of its own
        ("Betriebskostenabrechnung 2024\nDie Abrechnung 2023 vom 15.01.2025 wurde korrigiert.", "ignored"),
        # … or named with its year before this statement's own period ended (the period the card checks)
        (
            "Abrechnungszeitraum: 01.01.2025 - 31.12.2025\nDas Guthaben aus der Abrechnung 2024 vom 10.11.2025 "
            "wurde erstattet.",
            "ignored",
        ),
        # dated before the billing period ended: the previous statement
        (
            "Betriebskostenabrechnung 2024\nDas Guthaben aus der letzten Abrechnung vom 10.11.2024 …",
            "ignored",
        ),
        # no billing period at all: nothing to check it against
        ("Ihr Widerspruch gegen unsere Abrechnung vom 15.11.2024 ist unbegründet.", "ignored"),
    ],
)
def test_which_statement_date_a_later_letter_counts_from(text: str, counts: str) -> None:
    letter, arrived = D("2026-09-20"), D("2026-09-22")
    dated = statement_date(text)
    assert dated is not None
    expected = {
        "counts": (dated, False, None),
        "named": (arrived, True, dated),
        "ignored": (arrived, True, None),
    }[counts]
    assert statement_arrival(text, arrived, True, letter) == expected


def test_two_dates_on_one_day_are_sorted_by_date_alone() -> None:
    text = "Operating-cost statement 2023\nAbrechnung 2023 vom 15.11.2024 und Abrechnung vom 15.11.2024"
    assert statement_arrival(text, D("2026-09-22"), True, D("2026-09-20")) == (D("2024-11-15"), False, None)
    # the earliest of several dates without a year is the one named
    text = "Abrechnungszeitraum 01.01.2023 - 31.12.2023\nAbrechnung vom 20.11.2024 ersetzt die Abrechnung vom 15.11.2024"
    assert statement_arrival(text, D("2026-09-22"), True, D("2026-09-20")).named == D("2024-11-15")


def test_a_rent_increase_card_says_which_month_ends_the_decision() -> None:
    card = letter_advice("rent_increase", today=TODAY)
    assert card is not None
    assert "second calendar month after the month you received" in card.summary
    assert "until 31 March" in card.summary


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("LG Electronics Deutschland GmbH", "retailer"),
        ("LG Electronics Deutschland GmbH", None),
        ("LG Display", "company"),
        ("AG Wohnbau GmbH", "landlord"),
        ("AG Wohnbau GmbH", None),
        ("FG Finanz-Service AG", None),
        ("OLG Immobilien", "landlord"),
        ("Kundenservice der LG Electronics Deutschland", "retailer"),
        ("LG Electronics Deutschland Service Center Nord", None),  # more than a place
    ],
)
def test_a_company_whose_name_starts_like_a_court_abbreviation_is_no_court(
    name: str, kind: str | None
) -> None:
    """Final review 1: an abbreviation counts only before a place (a word or two, no legal form) and from a
    sender read as an authority (or of unknown kind)."""
    assert not routing.is_court(name, kind) and not routing.is_labour_court(name, kind)


@pytest.mark.parametrize(
    "name",
    [
        "AG Hagen",
        "AG Frankfurt am Main",
        "LG Berlin II",
        "AG Halle (Saale)",
        "AG Neustadt a. d. Weinstraße",
        "OLG München, 3. Zivilsenat",
        "Geschäftsstelle des AG Hamburg-St. Georg",
    ],
)
def test_a_courts_abbreviation_before_its_place_is_a_court(name: str) -> None:
    assert routing.is_court(name, "authority") and routing.is_court(name, "other")
    # final review 2: a name of unknown kind (a recipient typed in) needs the court's full name
    assert not routing.is_court(name)


@pytest.mark.parametrize("name", ["LG Electronics", "OLG Immobilien", "AG Hausverwaltung Müller", "AG Hagen"])
def test_a_typed_recipient_is_a_court_only_by_its_full_name(name: str) -> None:
    """Final review 2: a recipient typed into a template letter has no kind; an abbreviation without a legal
    form ("LG Electronics") doesn't make it a court, a court's full name does."""
    assert not routing.is_court(name, None) and not routing.is_labour_court(name, None)
    assert routing.is_court("Amtsgericht Hagen", None) and routing.is_labour_court(
        "Arbeitsgericht Berlin", None
    )
    assert not routing.is_court(name, "retailer") and not routing.is_court(name, "company")
    assert routing.is_court("Amtsgericht Hagen", "other")  # a court's full name counts from any sender kind
    # final review 3: … but it may be one, which its sending advice says (:func:`test_a_typed_name_that_may_be_a_court`)
    assert routing.may_be_court(name)


@pytest.mark.parametrize(
    ("name", "maybe"),
    [
        ("AG Hagen", True),
        ("LG Köln", True),
        ("AG Hagen – Abteilung 12", True),
        ("Amtsgericht Hagen", True),
        ("LG Electronics", True),  # can't be told apart from a court
        ("LG Electronics Deutschland GmbH", False),
        ("Gerichtsvollzieher beim AG Hagen", False),
        ("Stadtwerke Hagen", False),
    ],
)
def test_a_typed_name_that_may_be_a_court(name: str, maybe: bool) -> None:
    """Final review 3: a request for more time sent to "AG Hagen" by plain e-mail isn't validly filed, so a
    typed name that abbreviates a court before a place gets the court's channels — a signed letter first —
    with e-mail last and allowed only for the case it isn't a court. Only for letters sent to a court (an
    objection, a reply, a request for more time): a withdrawal to "LG Electronics" keeps its own channels."""
    assert routing.may_be_court(name) is maybe
    unsure = maybe and not routing.is_court(name, None)
    guidance = send_guidance(
        "extension_request", court=routing.is_court(name, None), court_unsure=unsure, today=TODAY
    )
    [email] = [channel for channel in guidance.channels if channel.channel == "email"]
    assert guidance.channels[0].channel == ("letter" if maybe else "email")
    assert email.allowed is (not maybe or unsure) and email.recommended is not maybe
    if unsure:
        assert email.note is not None and email.note.startswith("Not valid if this is a court")
    withdrawal = send_guidance("withdrawal", court=False, court_unsure=unsure, today=TODAY)
    assert withdrawal.channels[0].channel == "email" and withdrawal.channels[0].allowed


def test_an_lg_order_confirmation_keeps_the_consumer_withdrawal_rules() -> None:
    """Final review 1: the retailer "LG Electronics" isn't a court, so a withdrawal period on its order
    confirmation follows § 355 BGB (not the court rules of § 222 ZPO)."""
    withdrawal = spec(
        amount=14, unit="days", nature="declaration", text="Widerrufsfrist 14 Tage ab Erhalt der Ware"
    )
    context = ctx(document_date="2026-09-20", received_date="2026-09-22", received_confirmed=True)
    court = routing.is_court("LG Electronics Deutschland GmbH", "retailer")
    receipt = compute_due(withdrawal, replace(context, court=court))
    assert "bgb_355" in receipt.rule_ids and "zpo_222" not in receipt.rule_ids
    guidance = send_guidance("withdrawal", today=TODAY, court=court)
    [email] = [channel for channel in guidance.channels if channel.channel == "email"]
    assert email.allowed and "Not valid at a court" not in (email.note or "")
    at_court = send_guidance("withdrawal", today=TODAY, court=True)
    assert not next(channel for channel in at_court.channels if channel.channel == "email").allowed


@pytest.mark.parametrize(
    ("extra", "kind"),
    [
        # an employer ending the lease of a company flat: a landlord's notice (§ 576a BGB), not a dismissal
        (
            {"kind": "rent_lease", "sender": ExtractedParty(name="Werk GmbH", kind="employer")},
            "landlord_notice",
        ),
        (
            {
                "sender": ExtractedParty(name="Werk GmbH", kind="employer"),
                "contract": ExtractedContract(name="Werkmietwohnung", category="rent"),
            },
            "landlord_notice",
        ),
        # an employer ending a job ticket: neither
        (
            {
                "kind": "employment",
                "sender": ExtractedParty(name="Werk GmbH", kind="employer"),
                "contract": ExtractedContract(name="Jobticket", category="transport"),
            },
            None,
        ),
        # a job whose contract the reading files as "other": the letter's kind decides
        (
            {"kind": "employment", "contract": ExtractedContract(name="Vertrag", category="other")},
            "dismissal",
        ),
        # the letter's own kind before the sender's
        ({"kind": "employment", "sender": ExtractedParty(name="Wohnbau", kind="landlord")}, "dismissal"),
        ({"kind": "other", "sender": ExtractedParty(name="Wohnbau", kind="landlord")}, "landlord_notice"),
        ({"kind": "other", "sender": ExtractedParty(name="Fitness", kind="gym")}, None),
        ({"kind": "other"}, None),
    ],
)
def test_what_a_termination_ends_is_decided_by_its_contract_then_its_kind_then_its_sender(
    extra: dict[str, Any], kind: str | None
) -> None:
    assert routing.classify_letter(_termination(**extra)) == kind


def test_not_only_fristlos_is_no_negation() -> None:
    """Final review 1: "nicht nur fristlos, sondern hilfsweise auch ordentlich" gives notice without notice
    period (and one with it in the alternative)."""
    both = _notice("Wir kündigen nicht nur fristlos, sondern hilfsweise auch ordentlich.")
    assert routing.extraordinary_notice(both) and routing.alternative_notice(both)
    assert not routing.extraordinary_notice(_notice("Wir kündigen nicht fristlos, sondern ordentlich."))


def test_a_reserved_alternative_notice_still_offers_the_objection() -> None:
    """ADR 0010: any "hilfsweise" in the notice's own words counts, even one that only reserves the
    ordinary notice — offering an objection that may not be needed is the safe side of missing one."""
    reserved = _notice(
        "Wir kündigen hiermit fristlos. Hilfsweise behalten wir uns eine ordentliche Kündigung vor."
    )
    assert routing.extraordinary_notice(reserved) and routing.alternative_notice(reserved)


@pytest.mark.parametrize(
    ("written", "legal_basis", "context", "due"),
    [
        # § 574b: the tenancy ends 31 Mar 2027; the law's date is 31 Jan 2027, the letter says 15 Feb 2027
        (
            "2027-02-15",
            "§ 574b BGB",
            {"letter_kind": "landlord_notice", "end_date": "2027-03-31", "end_date_grounding": "quote"},
            "2027-01-31",
        ),
        # § 38 SGB III: the job ends 31 Dec 2026; the law's date is 30 Sep 2026, the letter says 15 Oct 2026
        (
            "2026-10-15",
            "§ 38 SGB III",
            {"end_date": "2026-12-31", "end_date_grounding": "quote", "received_date": "2026-09-01"},
            "2026-09-30",
        ),
    ],
    ids=["objection", "registration"],
)
def test_a_later_date_the_letter_names_keeps_the_laws_and_says_so(
    written: str, legal_basis: str, context: dict[str, Any], due: str
) -> None:
    """Final review 1: the letter's later date is not dropped silently: the receipt names it, keeps the law's
    earlier date and is no longer high (the end it counts from may be misread)."""
    nature = "objection" if "574b" in legal_basis else "declaration"
    receipt = compute_due(
        DateSpec(type="fixed", date=written, nature=nature, legal_basis=legal_basis),
        ctx(document_date="2026-09-01", received_confirmed=True, region="NW", **context),
    )
    assert receipt.due_date == due and receipt.confidence == "medium"
    assert any(f"later than the law's date ({fmt_date(D(due))})" in w for w in receipt.warnings)


@pytest.mark.parametrize(
    ("todo", "passed", "end_unknown", "first", "urgent"),
    [
        # the objection date had passed when the notice was written: no to-do — say why, and act now
        (False, True, False, "Your tenancy would end less than two months after this letter", True),
        (False, False, True, "We couldn't read when your tenancy ends", True),
        # no to-do for another reason (the person deleted it): still urgent, with the rule
        (False, False, False, "There is no to-do for the objection", True),
        # the letter's own objection date is the to-do, although the end wasn't read: no such step
        (True, False, True, "Don't agree to move out", False),
    ],
)
def test_a_landlords_card_says_why_no_to_do_carries_the_objection(
    todo: bool, passed: bool, end_unknown: bool, first: str, urgent: bool
) -> None:
    card = letter_advice(
        "landlord_notice",
        today=TODAY,
        objection_todo=todo,
        objection_passed=passed,
        end_unknown=end_unknown,
    )
    assert card is not None and card.urgent is urgent
    assert card.steps[0].startswith(first)
    if passed:
        assert "§ 574b Abs. 2 S. 2 BGB" in card.steps[0] and "§ 573c" in card.steps[0]


@pytest.mark.parametrize(
    ("kind", "facts"),
    [
        ("court_payment_order", {}),
        ("court_payment_order", {"labour_court": True}),
        ("enforcement_order", {"labour_court": True}),
        ("enforcement_order", {}),
        ("dismissal", {}),
        ("dismissal", {"arrival_confirmed": True}),
        (
            "operating_costs",
            {"arrived": D("2026-09-10"), "text": "Abrechnungszeitraum: 01.01.2024 - 31.12.2024"},
        ),
    ],
)
def test_a_card_is_no_longer_urgent_once_the_person_closed_every_to_do(
    kind: str, facts: dict[str, Any]
) -> None:
    """Final review 1: after the person objected (or went to court) and marked the to-dos done, the card
    stays as information and the verdict settles. Final review 2: it says so (``handled``) and no longer
    asks for the delivery day."""
    card = letter_advice(kind, today=TODAY, **facts)
    handled = letter_advice(kind, today=TODAY, handled=True, **facts)
    assert card is not None and handled is not None
    assert card.urgent and not handled.urgent and handled.handled and not card.handled
    asks = kind != "operating_costs"  # the court orders and the dismissal ask for the delivery day first
    assert handled.steps == (card.steps[1:] if asks else card.steps)
    assert (
        handled.model_copy(
            update={"urgent": True, "handled": False, "steps": card.steps, "title": card.title}
        )
        == card
    )
    # review round 2 of phase 2: the title names the letter, never the deadline it no longer urges
    assert handled.title == f"{card.title.split(' — ')[0]} — you've dealt with it"


@pytest.mark.parametrize(
    "facts",
    [
        {"extraordinary": True},
        {"extraordinary": True, "alternative": True},
        {"objection_todo": False, "end_unknown": True},
        {"objection_todo": False, "objection_passed": True},
        {"objection_todo": False},
    ],
)
def test_a_landlords_notice_no_to_do_carries_is_never_handled(facts: dict[str, Any]) -> None:
    """Final review 2: paying the arrears a notice without notice period demands, or closing a handover
    appointment, doesn't deal with a notice no objection to-do carries: its card stays urgent."""
    card = letter_advice("landlord_notice", today=TODAY, handled=True, **facts)
    assert card is not None and card.urgent and not card.handled
    ordinary = letter_advice("landlord_notice", today=TODAY, handled=True)
    assert ordinary is not None and ordinary.handled and not ordinary.urgent
    # final review 3: … until the person says they dealt with it (had advice, moved out, settled): the card
    # offers that itself, as no to-do can close it
    assert card.closable and not ordinary.closable
    dealt = letter_advice("landlord_notice", today=TODAY, dealt_with=True, **facts)
    assert dealt is not None and dealt.handled and not dealt.urgent and dealt.closable
    assert dealt.model_copy(update={"urgent": True, "handled": False, "title": card.title}) == card
    # review round 2 of phase 2: a handled card no longer urges what it did
    assert dealt.title == "Notice from your landlord — you've dealt with it"
    assert ordinary.title == "Notice from your landlord — you've dealt with it"
    # the tag means nothing on a card its to-dos settle
    other = letter_advice("landlord_notice", today=TODAY, dealt_with=True)
    assert other is not None and not other.handled


def _todo(status: str, *rule_ids: str, origin: str = "extracted") -> Item:
    receipt = ComputationReceipt(due_date=None, rule_ids=list(rule_ids)) if rule_ids else None
    return Item(
        id=f"{status}-{origin}-{'-'.join(rule_ids)}",
        kind="deadline",
        title="To do",
        status=status,  # type: ignore[arg-type]
        origin=origin,  # type: ignore[arg-type]
        computation=receipt,
        created_at="2026-09-20T10:00:00",
        updated_at="2026-09-20T10:00:00",
    )


def test_only_the_to_dos_that_carry_the_letters_deadline_settle_it() -> None:
    """Final review 2: a letter is handled once every to-do the law added or that cites a rule of its card
    is closed — never by closing another to-do of the letter (the arrears, a handover appointment)."""
    card = letter_advice("court_payment_order", today=TODAY)
    assert card is not None
    assert not settles(card, [])
    assert not settles(card, [_todo("done")])  # a to-do without a receipt: another one
    assert not settles(card, [_todo("done", "bgb_286")])  # a receipt citing another rule
    assert settles(card, [_todo("done", "zpo_692", origin="rule"), _todo("open", "bgb_286")])
    assert settles(card, [_todo("dismissed", origin="rule")])
    assert not settles(card, [_todo("done", "zpo_692", origin="rule"), _todo("snoozed", "zpo_180")])
    assert not settles(card, [_todo("missed", "zpo_692")])


def test_a_rent_increase_is_handled_once_the_consent_decision_is_closed() -> None:
    """Final review 3: a rent increase's new rent cites § 558b BGB for its payment note, and a recurring to-do
    stays open after "done" (it moves to its next occurrence): neither carries the letter's deadline, so
    closing the consent decision handles the letter."""
    card = letter_advice("rent_increase", today=TODAY)
    assert card is not None
    decision = _todo("done", "bgb_558b", origin="rule")
    recurring_rent = _todo("open", "bgb_558b").model_copy(
        update={"id": "rent", "kind": "payment", "recurrence": Recurrence(freq="monthly")}
    )
    one_off_rent = recurring_rent.model_copy(update={"id": "rent-once", "recurrence": None})
    assert settles(card, [decision, recurring_rent, one_off_rent])
    assert not settles(card, [decision.model_copy(update={"status": "open"}), recurring_rent])
    assert not settles(card, [recurring_rent])  # only the new rent: nothing that carries the deadline
    # a recurring to-do never carries a court order's deadline either; a one-off payment under its rule does
    order = letter_advice("court_payment_order", today=TODAY)
    assert order is not None
    pay = _todo("open", "zpo_692").model_copy(update={"id": "pay", "kind": "payment"})
    assert not settles(order, [_todo("done", "zpo_692", origin="rule"), pay])
    monthly = pay.model_copy(update={"recurrence": Recurrence(freq="monthly")})
    assert settles(order, [_todo("done", "zpo_692", origin="rule"), monthly])


def test_an_on_time_statement_has_no_to_do_that_carries_a_deadline() -> None:
    """Final review 3: an operating-cost statement that came in time has no to-do carrying a legal deadline
    (its back-payment cites § 556 Abs. 3 BGB only when it is late), so it is never handled — its card is
    information, and the page keeps asking when it arrived (the objection period counts from then). A late
    one is handled once its back-payment is closed."""
    card = letter_advice("operating_costs", today=TODAY)
    assert card is not None
    back_payment = _todo("done").model_copy(update={"kind": "payment"})
    assert not settles(card, [back_payment])
    late = back_payment.model_copy(
        update={"computation": ComputationReceipt(due_date=None, rule_ids=["bgb_286", "bgb_556_3"])}
    )
    assert settles(card, [late])


@pytest.mark.parametrize("own_date", ["today", "document_date"])
@pytest.mark.parametrize("court", [True, False], ids=["court", "other-sender"])
def test_a_period_from_the_letters_own_date_without_its_date_counts_from_the_arrival_entered(
    own_date: str, court: bool
) -> None:
    """Final review 3: a letter that counts from its own date ("ab heute") but whose date wasn't read can be
    dated at the latest the day it arrived — the envelope date the person entered — never the (later) day it
    is processed. A court's letter then runs from the envelope date as before (§ 180 ZPO, 18 Sep, not 12 Oct);
    both say the real deadline may be earlier. Another sender's "ab dem Datum dieses Schreibens" without the
    date still computes nothing."""
    date_spec = spec(anchor=own_date, nature="declaration", text="binnen zwei Wochen ab heute")
    undated = ctx(
        today=D("2026-09-27"),
        document_date=None,
        received_date=D("2026-09-04"),
        received_confirmed=True,
        court=court,
    )
    receipt = compute_due(date_spec, undated)
    if not court and own_date == "document_date":
        assert receipt.due_date is None
        return
    assert receipt.due_date == "2026-09-18" and receipt.confidence == "low"
    assert any("which is missing; we counted from Fri 4 Sep 2026" in warning for warning in receipt.warnings)
    assert ("zpo_180" in receipt.rule_ids) is court
    # nothing entered: from today, as before (the real deadline may be earlier)
    unknown = replace(undated, received_date=None, received_confirmed=False)
    if own_date == "today":
        assert compute_due(date_spec, unknown).due_date == "2026-10-12"
        # an arrival entered as today changes nothing
        same_day = replace(undated, received_date=D("2026-09-27"))
        assert compute_due(date_spec, same_day).due_date == "2026-10-12"


def test_every_court_letters_period_runs_from_delivery() -> None:
    """Final review 1: a court's letter filed as another kind cites § 180 ZPO too, so the page asks for the
    envelope date ("when was it delivered?") instead of prefilling today."""
    court = ctx(document_date="2026-09-21", court=True)
    relative = compute_due(spec(text="Stellungnahme binnen zwei Wochen nach Zustellung"), court)
    assert relative.due_date == "2026-10-05" and relative.confidence == "low"
    assert "zpo_180" in relative.rule_ids and "zpo_222" in relative.rule_ids
    # a date counted from a day the letter names, and a fixed date, don't depend on delivery
    explicit = compute_due(spec(anchor="explicit_date", anchor_date="2026-10-20", amount=-1), court)
    fixed = compute_due(DateSpec(type="fixed", date="2026-10-20", nature="objection"), court)
    assert "zpo_180" not in explicit.rule_ids and "zpo_180" not in fixed.rule_ids
    assert "zpo_180" not in compute_due(spec(), ctx(document_date="2026-09-21")).rule_ids


@pytest.mark.parametrize("own_date", ["document_date", "today"])
def test_a_court_period_counted_from_the_letters_own_date_ignores_the_envelope_date(own_date: str) -> None:
    """Final review 2: a court may count its own period from its letter's date (§ 221 ZPO: "ab dem Datum
    dieses Schreibens"); the envelope date the person enters never moves it later, and the page doesn't ask
    for it (no § 180 ZPO)."""
    date_spec = spec(
        anchor=own_date, nature="declaration", text="binnen zwei Wochen ab dem Datum dieses Schreibens"
    )
    court = ctx(document_date="2026-09-01", court=True)
    entered = replace(court, received_date=D("2026-09-04"), received_confirmed=True)
    for context in (court, entered):
        receipt = compute_due(date_spec, context)
        assert receipt.due_date == "2026-09-15" and receipt.confidence != "high"
        assert "zpo_180" not in receipt.rule_ids
    # a court order's statutory period still runs from delivery, whatever anchor it was read with
    order = spec(anchor=own_date, text="binnen zwei Wochen")
    as_order = replace(entered, letter_kind="court_payment_order")
    served = compute_due(order, as_order)
    assert served.due_date == "2026-09-18" and "zpo_180" in served.rule_ids
    # … and so does a court's own period that names no start (§ 221 ZPO: delivery)
    no_start = compute_due(spec(anchor=None, nature="declaration", text="binnen zwei Wochen"), entered)
    assert no_start.due_date == "2026-09-18" and "zpo_180" in no_start.rule_ids


@pytest.mark.parametrize("kind", ["authority", "university", "other", None, "employer"])
def test_the_kschg_period_counts_from_arrival_whoever_the_employer_is(kind: str | None) -> None:
    """Review round 1: a dismissal takes effect on receipt (§ 130 BGB, § 4 S. 1 KSchG) — a city's or a
    university's too; the VwVfG's delivery fiction made it 15 Oct (16 Oct in NW) instead of 12 Oct."""
    from ordnung.rules import is_private_sender, scope_for_party_kind

    spec = DateSpec(
        type="relative",
        anchor="deemed_delivery",
        delivery_rule="de_admin_post",
        amount=3,
        unit="weeks",
        nature="objection",
        legal_basis="§ 4 KSchG",
        text="innerhalb von drei Wochen nach Zugang der Kündigung",
    )
    scope = scope_for_party_kind(kind, name="Stadt Musterstadt - Personalamt")
    for region in (None, "NW"):
        ctx = RuleContext(
            today=date(2026, 9, 27),
            document_date=date(2026, 9, 21),
            region=region,
            delivery_scope=scope,
            sender_kind=kind,
            private_sender=is_private_sender(kind, scope=scope),
            letter_kind="dismissal",
        )
        receipt = compute_due(spec, ctx)
        assert receipt.due_date == "2026-10-12" and "posting_day" not in receipt.rule_ids
        assert "private_sender_arrival" in receipt.rule_ids
    court_letter = compute_due(spec, replace(ctx, court=True))  # a court's letter keeps formal service
    assert "private_sender_arrival" not in court_letter.rule_ids


def test_the_kschg_period_counts_a_regional_holiday_only_where_the_action_may_be_filed() -> None:
    """Review round 1: the action may be filed at the labour court of the place of work (§ 48 Abs. 1a
    ArbGG), maybe in another Land than the employer's seat: 1 Nov (All Saints' Day in Bavaria) moves the
    end only when the person lives in the employer's Land too; otherwise it stays, with a warning."""
    spec = DateSpec(
        type="relative",
        anchor="receipt",
        amount=3,
        unit="weeks",
        nature="objection",
        legal_basis="§ 4 KSchG",
        text="innerhalb von drei Wochen nach Zugang der Kündigung",
    )
    ctx = RuleContext(
        today=date(2027, 10, 12),
        document_date=date(2027, 10, 8),
        received_date=date(2027, 10, 11),
        received_confirmed=True,
        region="BY",
        sender_kind="employer",
        private_sender=True,
        letter_kind="dismissal",
    )
    unknown = compute_due(spec, replace(ctx, recipient_region=None))
    assert unknown.due_date == "2027-11-01" and unknown.confidence != "high"
    assert any("1 Nov 2027 is a public holiday in some Länder" in w for w in unknown.warnings)
    assert unknown.holiday_calendar == "Germany (nationwide holidays only)"
    # review round 4 of phase 2: two Länder given count the holidays both have — not "region unknown"
    elsewhere = compute_due(spec, replace(ctx, recipient_region="BE"))
    assert elsewhere.due_date == "2027-11-01" and elsewhere.confidence != "high"
    assert not any("Holiday region unknown" in w for w in elsewhere.warnings)
    assert any(
        w.startswith(
            "Mon 1 Nov 2027 is a public holiday in Bayern but not in Berlin. Only a holiday both Länder"
        )
        for w in elsewhere.warnings
    )
    assert elsewhere.holiday_calendar == "Berlin and Bayern (only holidays both have)"
    same_land = compute_due(spec, replace(ctx, recipient_region="BY"))
    assert same_land.due_date == "2027-11-02"
    # All Saints' Day in both Länder: the action can't be filed that day at either court
    both = compute_due(spec, replace(ctx, region="NW", recipient_region="RP"))
    assert both.due_date == "2027-11-02"
    assert both.holiday_calendar == "Nordrhein-Westfalen and Rheinland-Pfalz (only holidays both have)"
    assert not any("public holiday in" in w for w in both.warnings)


def test_a_statement_dated_at_the_end_of_the_calendar_claims_nothing() -> None:
    """Review round 1: a statement dated 31 Dec 9999 (a mistyped year) made PATCH answer 500: its twelve
    months run past the calendar. Nothing is claimed about it instead."""
    text = "Betriebskostenabrechnung\nAbrechnungszeitraum: 01.01.2024 - 31.12.2024\nNachzahlung 120,00 EUR"
    end = D("9999-12-31")
    assert not statement_late(text, end, True, None)
    assert not statement_late(text, end, False, None, named=end)
    card = letter_advice("operating_costs", today=TODAY, arrived=end, letter_date=end, text=text)
    assert card is not None and not card.urgent
    assert "couldn't find the billing period" in card.facts[0].text
    named = "Abrechnungszeitraum: 01.01.2023 - 31.12.2023\nIhre Abrechnung vom 31.12.9999"
    assert statement_late(named, D("2025-06-01"), True, None, named=end)  # that date never makes it on time


@pytest.mark.parametrize(
    ("letter_date", "arrived", "written", "due"),
    [
        # the review's case: "ab dem 01.11.2026" in a request of 24 Sep 2026 — the law says 1 Dec
        ("2026-09-24", None, "2026-11-01", "2026-12-01"),
        # it arrived after the month turned: 1 Jan, whatever the letter says
        ("2026-09-29", "2026-10-02", "2026-12-01", "2027-01-01"),
        # a later start the letter names is kept
        ("2026-09-24", "2026-09-25", "2027-02-01", "2027-02-01"),
        # a period, not a date: the law's date
        ("2026-09-24", "2026-09-25", None, "2026-12-01"),
    ],
)
def test_a_rent_increases_new_rent_is_never_due_before_the_law_allows(
    letter_date: str, arrived: str | None, written: str | None, due: str
) -> None:
    """Review round 1: the payment to-do kept the letter's earlier date with confidence high (§ 558b Abs. 1
    BGB: owed from the start of the third calendar month after the request arrived)."""
    date_spec = (
        DateSpec(type="fixed", date=written, nature="payment", text=f"ab dem {written}")
        if written
        else DateSpec(type="relative", anchor="receipt", amount=3, unit="months", nature="payment")
    )
    context = ctx(document_date=letter_date, letter_kind="rent_increase")
    if arrived:
        context = replace(context, received_date=D(arrived), received_confirmed=True)
    receipt = compute_due(date_spec, context)
    assert receipt.due_date == due and "bgb_558b" in receipt.rule_ids
    assert receipt.send_by is not None and receipt.send_by < due  # a bank transfer, a working day ahead
    if written and written < due:
        assert any(f"by law the date is {fmt_date(D(due))}" in warning for warning in receipt.warnings)
    if arrived is None:
        assert receipt.confidence == "low"  # the real arrival day may move it later: asked for


def test_a_rent_increases_new_rent_without_a_date_to_count_from() -> None:
    receipt = compute_due(
        DateSpec(type="fixed", date="2026-12-01", nature="payment"), ctx(letter_kind="rent_increase")
    )
    assert receipt.due_date is None


@pytest.mark.parametrize(
    ("received", "region", "end"),
    [
        ("2026-09-24", None, "2026-12-31"),  # after the third working day: a month more
        ("2026-10-02", None, "2026-12-31"),  # 1 Oct, 2 Oct, (3 Oct: a holiday), 5 Oct
        ("2026-10-05", None, "2026-12-31"),
        ("2026-10-06", None, "2027-01-31"),
        ("2026-08-04", None, "2026-10-31"),  # 1 Aug is a Saturday and counts: 1, 3, 4 Aug
        ("2026-08-05", None, "2026-11-30"),
        # a Saturday third working day runs on to Monday (§ 193 BGB, as some courts hold): the earlier end
        ("2027-04-05", None, "2027-06-30"),  # 1 Apr Thu, 2 Apr Fri, 3 Apr Sat → Mon 5 Apr
        ("2027-04-06", None, "2027-07-31"),
        ("2027-05-03", None, "2027-07-31"),  # 1 May holiday, 3 May Mon, 4 Tue, 5 Wed
        ("2025-11-03", None, "2026-01-31"),  # 1 Nov (Sat, a holiday in some Länder), 3 Nov, 4 Nov
        ("2025-11-04", None, "2026-01-31"),
        ("2025-11-05", "BE", "2026-02-28"),  # 1 Nov Sat counts in Berlin: 1, 3, 4 Nov
        ("2025-11-05", None, "2026-01-31"),  # any Land's holiday on 1 Nov doesn't count: 3, 4, 5 Nov
        ("2026-02-28", "BY", "2026-05-31"),
    ],
)
def test_next_permissible_end_of_a_landlords_notice(received: str, region: str | None, end: str) -> None:
    """§ 573c Abs. 1 BGB: received by the third working day (Saturday counts, BGH VIII ZR 206/04) of a
    month, a landlord's notice ends the tenancy at the end of the month after next — the earliest end, for
    an objection that counts back from it."""
    assert next_permissible_end(D(received), region) == D(end)


def test_a_short_notices_objection_counts_back_from_the_next_permissible_end() -> None:
    notice = spec(
        amount=-2,
        unit="months",
        nature="objection",
        legal_basis="§ 574b Abs. 2, § 573c Abs. 1 BGB",
        text="spätestens zwei Monate vor dem nächstmöglichen Kündigungstermin",
    )
    context = ctx(document_date="2026-09-24", end_date="2026-10-31", letter_kind="landlord_notice")
    receipt = compute_due(notice, context)
    assert receipt.due_date == "2026-10-31" and receipt.confidence == "low"
    assert "bgb_573c_landlord" in receipt.rule_ids and NEXT_END_WARNING in receipt.warnings
    assert receipt.summary.startswith("If the notice ends your tenancy at the earliest date the law allows")
    confirmed = compute_due(notice, replace(context, received_date=D("2026-10-06"), received_confirmed=True))
    assert confirmed.due_date == "2026-11-30" and confirmed.confidence == "medium"
    passed = compute_due(notice, replace(context, today=D("2026-12-15")))
    assert LATE_NOTICE_OBJECTION in passed.warnings
    undated = compute_due(notice, ctx(end_date="2026-10-31", letter_kind="landlord_notice"))
    assert undated.due_date is None
    # an objection date the letter gives from its own end is not one of these
    own = spec(type="fixed", date="2026-08-31", nature="objection", text="bis zum 31.08.2026")
    assert "bgb_573c_landlord" not in compute_due(own, context).rule_ids


@pytest.mark.parametrize("name", ["Sozialgericht Berlin", "SG Kassel", "Landessozialgericht NRW", "BSG"])
def test_a_social_courts_period_cites_the_sgg(name: str) -> None:
    """Review round 2 of phase 2: a social court counts under § 64 Abs. 1–3 SGG, not § 222 ZPO (the dates
    are the same; "Why this date?" cited the wrong act)."""
    assert routing.is_social_court(name, "authority")
    counted = spec(amount=1, unit="months", text="Berufung binnen eines Monats nach Zustellung (§ 151 SGG)")
    receipt = compute_due(
        counted,
        ctx(document_date="2026-09-18", court=True, social_court=routing.is_social_court(name, "authority")),
    )
    citations = {step.rule_id: step.citation for step in receipt.steps}
    assert citations["bgb_187_1"] == "§ 64 Abs. 1 SGG" and citations["bgb_188"] == "§ 64 Abs. 2 SGG"
    assert "sgg_64" in receipt.rule_ids and "zpo_222" not in receipt.rule_ids
    # Sun 18 Oct 2026 moves to Monday under § 64 Abs. 3 SGG
    assert receipt.due_date == "2026-10-19"
    assert catalog.citation("sgg_64") == "§ 64 Abs. 1–3 SGG"
    for other in ("Amtsgericht Berlin", "Arbeitsgericht Kassel", "SG Musterverein e. V."):
        assert not routing.is_social_court(other, "authority")


def test_a_court_deadlines_receipt_cites_the_court_counting_rules() -> None:
    """Review round 1: "Why this date?" on a Mahnbescheid and a Kündigungsschutzklage cited the counting
    rules of the AO, the VwVfG, the StPO and the SGG next to §§ 187, 188 BGB."""
    counted = spec(text="binnen zwei Wochen")
    court = compute_due(
        counted, ctx(document_date="2026-09-21", letter_kind="court_payment_order", court=True)
    )
    citations = {step.rule_id: step.citation for step in court.steps}
    assert citations["bgb_187_1"] == "§ 222 Abs. 1 ZPO; § 187 Abs. 1 BGB"
    assert citations["bgb_188"] == "§ 222 Abs. 1 ZPO; § 188 Abs. 1, 2 BGB"
    labour = compute_due(
        counted,
        ctx(document_date="2026-09-21", letter_kind="court_payment_order", court=True, labour_court=True),
    )
    assert {step.rule_id: step.citation for step in labour.steps}["bgb_187_1"].startswith("§ 46 Abs. 2 ArbGG")
    action = compute_due(
        spec(amount=3, legal_basis="§ 4 KSchG", text="Kündigungsschutzklage"),
        ctx(document_date="2026-09-21", sender_kind="employer", private_sender=True, letter_kind="dismissal"),
    )
    assert {step.rule_id: step.citation for step in action.steps}["bgb_187_1"] == "§ 187 Abs. 1 BGB"
    # an authority's period keeps the catalog's citation, which names its own law too
    tax = compute_due(
        spec(anchor="deemed_delivery", amount=1, unit="months"),
        ctx(document_date="2026-09-21", delivery_scope="ao"),
    )
    assert {step.rule_id: step.citation for step in tax.steps}["bgb_187_1"] == catalog.citation("bgb_187_1")
