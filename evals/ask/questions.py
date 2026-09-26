"""The Ask benchmark's questions, with gold answers computed from the sample life's truth.

The sample life is the same one the demo uses (``src/ordnung/demo/samples/manifest.json``): 25
letters of Sam Rivera, each with a hand-written *truth* — the to-dos with their expected due dates
and amounts, the contracts with their expected cancellation dates — whose arithmetic is spelled out
in ``scripts/samplelife`` and checked there without ``ordnung.rules``. Gold answers are read from
that truth only: never from the rules engine, the ledger or the app's outputs.

Five categories, as the person would ask:

* ``deadline`` — one dated to-do: an objection deadline, a declaration, an appointment, an expiry;
* ``payment`` — one payment's amount and due date;
* ``contract`` — when a cancellation must arrive and when the contract then ends, or what it costs;
* ``cross_letter`` — several letters at once ("Which payments are due in the next four weeks?");
* ``unanswerable`` — something the sample life has no record of; the right answer says so.

Templates turn each truth record into a question (``source="template"``); hand-written paraphrases
ask about the same facts in other words, some in German (``source="paraphrase"``, same ``cluster``,
so the bootstrap resamples a fact with its paraphrases). Optional truth items (ones a perfect reading
may or may not file) and dates before today are left out, so every gold value is something the
person should be told.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Literal

from evals.ask.ledger import TODAY

MANIFEST = Path(__file__).resolve().parents[2] / "src" / "ordnung" / "demo" / "samples" / "manifest.json"

Category = Literal["deadline", "payment", "contract", "cross_letter", "unanswerable"]
Source = Literal["template", "paraphrase", "hand"]
CATEGORIES: tuple[Category, ...] = ("deadline", "payment", "contract", "cross_letter", "unanswerable")


@dataclass(frozen=True)
class Gold:
    """What a correct answer must state: every date and amount, and the letters they come from."""

    dates: tuple[date, ...] = ()
    amounts: tuple[float, ...] = ()
    letters: tuple[str, ...] = ()
    related: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "dates": [day.isoformat() for day in self.dates],
            "amounts": list(self.amounts),
            "letters": list(self.letters),
            "related": list(self.related),
        }


@dataclass(frozen=True)
class Question:
    """One benchmark question (``gold`` is ``None`` for an unanswerable one)."""

    id: str
    category: Category
    text: str
    gold: Gold | None
    source: Source
    cluster: str = ""

    def __post_init__(self) -> None:
        if not self.cluster:
            object.__setattr__(self, "cluster", self.id)


@dataclass(frozen=True)
class TruthDoc:
    """A letter of the sample life and its truth (as in the manifest)."""

    order: int
    slug: str
    truth: dict[str, Any]
    related: tuple[str, ...] = field(default=())


def load_truth(path: Path = MANIFEST) -> dict[str, TruthDoc]:
    """The sample life's letters by slug, with their truth and related letters' slugs."""
    documents = json.loads(path.read_text(encoding="utf-8"))["documents"]
    slugs = {doc["order"]: doc["slug"] for doc in documents}
    return {
        doc["slug"]: TruthDoc(
            order=doc["order"],
            slug=doc["slug"],
            truth=doc["truth"],
            related=tuple(slugs[link["order"]] for link in doc["truth"].get("related", [])),
        )
        for doc in documents
    }


def _day(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _items(doc: TruthDoc) -> list[dict[str, Any]]:
    """The letter's required to-dos with a date that is not in the past."""
    return [
        item
        for item in doc.truth["items"]
        if not item["optional"] and (day := _day(item["expected_due"])) is not None and day >= TODAY
    ]


def _related(doc: TruthDoc, truth: dict[str, TruthDoc]) -> tuple[str, ...]:
    """Letters related either way (a reminder and its invoice support each other's citations)."""
    back = tuple(slug for slug, other in truth.items() if doc.slug in other.related)
    return tuple(dict.fromkeys((*doc.related, *back)))


# --------------------------------------------------------------------------------------------------
# templates
# --------------------------------------------------------------------------------------------------

#: How the person names each letter's subject (the templates' only hand-written part).
SUBJECT: dict[str, str] = {
    "steuerbescheid_2025": "the tax assessment",
    "krankenkasse_beitragsbescheid": "the health insurance contribution notice from Muster BKK",
    "nebenkostenabrechnung_2025": "the 2025 service-charge statement",
    "stipendium_zusage": "submit the first scholarship progress report",
    "bank_preisaenderung": "decide on the bank's new account fee",
    "stadtwerke_preisanpassung": "my electricity contract because of the price increase",
    "arbeitsvertrag_werkstudent": "my working-student contract",
    "auslaenderbehoerde_termin": "my residence permit",
    "reisepass": "my passport",
    "zahnarzt_terminkarte": "my dentist appointment",
    "stadtbibliothek_mahnung": "return the overdue library books",
    "mietvertrag": "my rent",
    "haftpflicht_versicherungsschein": "my liability insurance",
    "rueckmeldung_sose_2027": "the semester fee for the summer semester 2027",
    "mahnung_techmarkt": "the TechMarkt payment reminder",
    "rundfunkbeitrag_zahlungsaufforderung": "the broadcasting fee (Rundfunkbeitrag)",
    "verwarnungsgeld_parken": "the parking fine",
    "mobilfunkvertrag": "my phone contract",
    "deutschlandticket_abo": "my Deutschlandticket subscription",
    "fitnessstudio_mitgliedsvertrag": "my gym membership",
    "stadtwerke_vertrag": "my electricity contract",
}
APPOINTMENT: dict[str, str] = {
    "auslaenderbehoerde_termin": "my appointment at the Ausländerbehörde",
    "zahnarzt_terminkarte": "my dentist appointment",
}
RENT_LEASE = "the rental agreement for my flat"


def _dated_question(doc: TruthDoc, item: dict[str, Any]) -> str | None:
    """The template for one dated to-do (``None``: its kind is asked elsewhere)."""
    kind, nature, slug = item["kind"], item["nature"], doc.slug
    if kind == "deadline" and nature == "objection":
        return f"When do I have to object to {SUBJECT[slug]}?"
    if kind in ("deadline", "task") and nature == "declaration":
        return f"By when do I have to {SUBJECT[slug]}?"
    if kind == "deadline" and nature == "notice":
        return f"Until when can I cancel {SUBJECT[slug]}?"
    if kind == "expiry":
        verb = "end" if "contract" in SUBJECT[slug] else "expire"
        return f"When does {SUBJECT[slug]} {verb}?"
    if kind == "appointment":
        return f"When is {APPOINTMENT[slug]}?"
    return None


def deadline_questions(truth: dict[str, TruthDoc]) -> list[Question]:
    """One question per required dated to-do that is not a payment."""
    questions = []
    for doc in truth.values():
        for index, item in enumerate(_items(doc)):
            text = _dated_question(doc, item) if item["kind"] != "payment" else None
            if text is None:
                continue
            gold = Gold(
                dates=(date.fromisoformat(item["expected_due"]),),
                letters=(doc.slug,),
                related=_related(doc, truth),
            )
            questions.append(Question(f"deadline-{doc.slug}-{index}", "deadline", text, gold, "template"))
    return questions


def payment_questions(truth: dict[str, TruthDoc]) -> list[Question]:
    """One question per required outgoing payment with an amount and a due date."""
    questions = []
    for doc in truth.values():
        for index, item in enumerate(_items(doc)):
            if item["kind"] != "payment" or item["direction"] != "out" or item["amount"] is None:
                continue
            subject = SUBJECT[doc.slug]
            if item["recurrence"]:
                text = f"How much is {subject} and when is the next payment due?"
            else:
                text = f"How much do I have to pay for {subject}, and by when?"
            gold = Gold(
                dates=(date.fromisoformat(item["expected_due"]),),
                amounts=(float(item["amount"]),),
                letters=(doc.slug,),
                related=_related(doc, truth),
            )
            questions.append(Question(f"payment-{doc.slug}-{index}", "payment", text, gold, "template"))
    return questions


#: Contracts asked about their cost (the rest of the costs is asked as payments).
COST_CONTRACTS = (
    "mobilfunkvertrag",
    "fitnessstudio_mitgliedsvertrag",
    "stadtwerke_vertrag",
    "deutschlandticket_abo",
)


def contract_questions(truth: dict[str, TruthDoc]) -> list[Question]:
    """When a cancellation must arrive and when the contract then ends; what a contract costs.

    Only contracts whose truth fixes a cancel-by date are asked the first question: for contracts
    that can be cancelled any day, the end date depends on the day the cancellation arrives, which a
    question in words cannot pin down.
    """
    questions = []
    for doc in truth.values():
        contract = doc.truth.get("contract")
        if not contract:
            continue
        cancel_by, exit_day = _day(contract["expected_cancel_by"]), _day(contract["expected_earliest_exit"])
        if cancel_by is not None and exit_day is not None and cancel_by >= TODAY:
            subject = RENT_LEASE if doc.slug == "mietvertrag" else SUBJECT[doc.slug]
            text = f"By when does my cancellation of {subject} have to arrive, and when would it then end?"
            gold = Gold(dates=(cancel_by, exit_day), letters=(doc.slug,), related=_related(doc, truth))
            questions.append(Question(f"contract-{doc.slug}-cancel", "contract", text, gold, "template"))
        if doc.slug in COST_CONTRACTS and contract["cost_amount"] is not None:
            text = f"How much does {SUBJECT[doc.slug]} cost?"
            gold = Gold(
                amounts=(float(contract["cost_amount"]),), letters=(doc.slug,), related=_related(doc, truth)
            )
            questions.append(Question(f"contract-{doc.slug}-cost", "contract", text, gold, "template"))
    return questions


@dataclass(frozen=True)
class Selection:
    """A question over several letters: which truth items answer it, and what of each is stated."""

    id: str
    text: str
    keep: Callable[[dict[str, Any], date], bool]
    state: Literal["date", "amount"]


def _window(days: int) -> Callable[[dict[str, Any], date], bool]:
    return lambda item, day: TODAY <= day <= TODAY + timedelta(days=days)


def _payment_in(days: int) -> Callable[[dict[str, Any], date], bool]:
    inside = _window(days)
    return lambda item, day: item["kind"] == "payment" and item["direction"] == "out" and inside(item, day)


CROSS_LETTER: tuple[Selection, ...] = (
    Selection("pay-4-weeks", "What do I have to pay in the next four weeks?", _payment_in(28), "amount"),
    Selection("pay-this-week", "What do I have to pay this week?", _payment_in(6), "amount"),
    Selection(
        "deadlines-october",
        "Which deadlines do I have in October 2026?",
        lambda item, day: item["kind"] == "deadline" and (day.year, day.month) == (2026, 10),
        "date",
    ),
    Selection(
        "appointments",
        "Which appointments do I have coming up?",
        lambda item, day: item["kind"] == "appointment",
        "date",
    ),
    Selection(
        "expiring-6-months",
        "Which of my documents or permits expire in the next six months?",
        lambda item, day: item["kind"] == "expiry" and day <= TODAY + timedelta(days=182),
        "date",
    ),
)


def cross_letter_questions(truth: dict[str, TruthDoc]) -> list[Question]:
    """Questions whose gold collects the matching required items of every letter."""
    questions = []
    for selection in CROSS_LETTER:
        dates: list[date] = []
        amounts: list[float] = []
        letters: list[str] = []
        for doc in truth.values():
            for item in _items(doc):
                day = date.fromisoformat(item["expected_due"])
                if not selection.keep(item, day):
                    continue
                letters.append(doc.slug)
                if selection.state == "amount":
                    amounts.append(float(item["amount"]))
                else:
                    dates.append(day)
        gold = Gold(
            dates=tuple(sorted(set(dates))), amounts=tuple(amounts), letters=tuple(dict.fromkeys(letters))
        )
        questions.append(Question(f"cross-{selection.id}", "cross_letter", selection.text, gold, "template"))
    return questions


UNANSWERABLE: tuple[tuple[str, str], ...] = (
    ("car-insurance", "When is my car insurance due for renewal?"),
    ("gas-bill", "How much is my monthly gas bill?"),
    ("dog-tax", "When do I have to pay the dog tax (Hundesteuer)?"),
    ("kindergeld", "What is the deadline to object to my child benefit (Kindergeld) notice?"),
    ("netflix", "When does my Netflix subscription renew, and how much does it cost?"),
    ("dr-mueller", "When is my appointment with Dr. Müller?"),
    ("bafoeg", "How much do I still have to pay back on my BAföG loan?"),
    ("driving-licence", "When do I have to renew my driving licence?"),
)
"""Things Sam's sample life has no record of (checked against the truth by a test)."""


def unanswerable_questions() -> list[Question]:
    return [Question(f"none-{key}", "unanswerable", text, None, "hand") for key, text in UNANSWERABLE]


#: Hand-written paraphrases: (template question id, text). Their gold is the template's.
PARAPHRASES: tuple[tuple[str, str], ...] = (
    (
        "deadline-steuerbescheid_2025-0",
        "Wann muss ich spätestens Einspruch gegen den Steuerbescheid einlegen?",
    ),
    (
        "deadline-steuerbescheid_2025-0",
        "The Finanzamt sent me my tax assessment — how long do I have to appeal it?",
    ),
    (
        "contract-mobilfunkvertrag-cancel",
        "What's the last day FunkNetz has to receive my cancellation, and when does it end then?",
    ),
    (
        "payment-mahnung_techmarkt-0",
        "I got a reminder from TechMarkt. How much do I owe them and until when?",
    ),
    ("deadline-reisepass-0", "How long is my passport still valid?"),
    (
        "payment-nebenkostenabrechnung_2025-0",
        "Wie viel muss ich für die Nebenkostenabrechnung nachzahlen, und bis wann?",
    ),
    ("deadline-auslaenderbehoerde_termin-0", "When do I need to be at the Ausländerbehörde?"),
    ("deadline-bank_preisaenderung-0", "Until when can I say no to the bank's new account fee?"),
    ("payment-verwarnungsgeld_parken-0", "My parking ticket: what do I owe and by when?"),
    ("deadline-zahnarzt_terminkarte-0", "When's the dentist?"),
    (
        "deadline-krankenkasse_beitragsbescheid-0",
        "Can I still object to the higher health insurance contribution? Until when?",
    ),
)


def paraphrase_questions(templates: Sequence[Question]) -> list[Question]:
    by_id = {question.id: question for question in templates}
    questions = []
    for index, (template_id, text) in enumerate(PARAPHRASES):
        template = by_id[template_id]
        questions.append(
            replace(
                template, id=f"para-{index:02d}", text=text, source="paraphrase", cluster=template.cluster
            )
        )
    return questions


def all_questions(truth: dict[str, TruthDoc] | None = None) -> list[Question]:
    """The whole question set, in a stable order."""
    loaded = truth if truth is not None else load_truth()
    templates = [
        *deadline_questions(loaded),
        *payment_questions(loaded),
        *contract_questions(loaded),
        *cross_letter_questions(loaded),
    ]
    return [*templates, *paraphrase_questions(templates), *unanswerable_questions()]


def truth_values(truth: Iterable[TruthDoc]) -> tuple[set[date], set[int]]:
    """Every date and amount (in cents) the sample life's truth states — its fields and the dates its
    hand-written reasoning names — for telling a true value from a made-up one."""
    from evals.ask.parse import mentions

    dates: set[date] = set()
    cents: set[int] = set()

    def walk(value: Any, key: str | None = None) -> None:
        if isinstance(value, dict):
            for child_key, child in value.items():
                walk(child, child_key)
        elif isinstance(value, list):
            for child in value:
                walk(child, key)
        elif isinstance(value, str):
            for found in mentions(value):
                if found.kind == "date":
                    dates.add(found.date)
                else:
                    cents.add(found.cents)
        elif isinstance(value, int | float) and not isinstance(value, bool) and key in _AMOUNT_FIELDS:
            cents.add(round(float(value) * 100))

    for doc in truth:
        walk(doc.truth)
    dates.add(TODAY)
    return dates, cents


_AMOUNT_FIELDS = frozenset({"value", "amount", "cost_amount", "old_amount", "new_amount"})
