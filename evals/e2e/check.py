"""The end-to-end checker: verdicts from the manifest's labels and what the person got — nothing of the app.

It imports no ``ordnung`` module (``tests/test_evals_e2e.py`` enforces it): no rules engine, no draft checks, no
Ask check. A labelled obligation is matched to the app's stored to-do by the benchmark's own matching
(:func:`evals.metrics.match_items`: kind, date, amount, title and quote), so a payment of the letter never stands
in for its objection deadline. Written policy for each verdict:

* **Genuine obligation**: a required labelled item with one date, of a letter not labelled a scam.
* **Reminded in time**: an alarm of the to-do's calendar event fires on a day from the reading day (an alarm on an
  earlier day never fires: the file is imported on the reading day) to the labelled date, both included. The lead
  is the labelled date minus the first such day.
* **Reminded only after the day**: not in time, and an alarm from the reading day on fires after the labelled date.
* **Not reminded, why** (the first that applies): the reading failed; no to-do matched; the to-do has no date; the
  app set it aside (with the cause); no calendar event; only alarms after the day; no alarm from the reading day.
* **Morning note**: the agenda on :func:`probe_day` lists the to-do.
* **Idea due**: a deadline whose labelled date is from the reading day to its reminder window ahead (the profile's
  longest reminder for deadlines); then **Idea right**: a ``deadline_soon`` Idea names the to-do and its day to act
  is no later than the labelled date.
* **Objection letter** (:func:`draft_elements`): see :data:`DRAFT_ELEMENTS`. An element the labels cannot judge
  (no reference, no decision date or no objection date labelled) is left out, never failed.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any

from rapidfuzz import fuzz

from evals.e2e.observe import DraftSeen, LetterObservation, StoredItem
from evals.metrics import match_items
from evals.records import Entry, PredictedItem, Truth, TruthItem, parse_iso

#: The elements of a complete objection letter, as the person sends it (the PDF), in the order they are listed.
DRAFT_ELEMENTS: tuple[str, ...] = (
    "remedy_word",  # the labelled remedy's word (Einspruch / Widerspruch) is in the letter, the other one not
    "reference",  # one of the labelled references (a file number, a tax number) is in the letter
    "decision_date",  # the labelled date of the decision objected to is in the letter
    "addressee",  # the labelled sender is the addressee (fuzzy ≥ ADDRESSEE_MIN_SCORE in the recipient block)
    "deadline",  # the day the letter must arrive by is the labelled objection date
    "send_by",  # the day to post it by is no later than the labelled objection date
    "signature",  # the signer's name under the closing formula
    "no_placeholder",  # no [..], {..}, XXX or TODO left in the letter
)
#: Remedies an objection letter is drafted for, and the word the letter must use.
REMEDY_WORDS: dict[str, str] = {"einspruch": "einspruch", "widerspruch": "widerspruch"}
ADDRESSEE_MIN_SCORE = 90.0
#: The closing formula of a German letter; the signer's name follows within SIGNATURE_LINES lines.
CLOSING = re.compile(r"freundlichen\s+gr(?:ü|ue)(?:ß|ss)en", re.I)
SIGNATURE_LINES = 4
PLACEHOLDER = re.compile(r"\[[^\]]{0,40}\]|\{[^}]{0,40}\}|\bXXX+\b|\bTODO\b")
#: A reference shorter than this (normalised) is too short to look for.
MIN_REFERENCE_CHARS = 4
MONTHS_DE = (
    "Januar",
    "Februar",
    "März",
    "April",
    "Mai",
    "Juni",
    "Juli",
    "August",
    "September",
    "Oktober",
    "November",
    "Dezember",
)
#: The kind of a labelled obligation an Idea is expected for, and the profile's reminder kind its window is read from.
IDEA_KINDS: tuple[str, ...] = ("deadline",)
IDEA_RULE = "deadline_soon"
SCAM_IDEA_RULE = "scam_warning"
SCAM_LABEL = "scam"


def genuine(entry: Entry) -> bool:
    """The letter is not labelled a scam: its obligations are real."""
    return SCAM_LABEL not in entry.truth.expected_warnings


def remedy_letter(entry: Entry) -> bool:
    """A genuine letter labelled with an Einspruch or Widerspruch: an objection letter is drafted for it."""
    return genuine(entry) and entry.truth.remedy_type in REMEDY_WORDS


def no_remedy_letter(entry: Entry) -> bool:
    """A genuine letter labelled without any remedy: asking for an objection letter must be refused."""
    return genuine(entry) and entry.truth.remedy_type == "none"


def objection_due(truth: Truth) -> date | None:
    """The labelled date of the letter's objection deadline (``None``: the letter gives none)."""
    return next(
        (item.expected_date for item in truth.items if item.nature == "objection" and item.expected_date),
        None,
    )


def probe_day(entry: Entry, gold: date) -> date:
    """The day the morning note is looked at for an obligation due on ``gold``: the day before, or the reading
    day when that is later."""
    return max(entry.today_date, gold - timedelta(days=1))


def probe_days(entry: Entry) -> list[date]:
    """Every day :func:`probe_day` asks the agenda about, for the letter's dated obligations."""
    return sorted({probe_day(entry, item.expected_date) for item in entry.truth.items if item.expected_date})


# --------------------------------------------------------------------------------------------------
# verdicts
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ObligationVerdict:
    """What reached the person for one genuine labelled obligation."""

    index: int
    kind: str
    nature: str
    gold: str
    #: the matched to-do (``None``: none matched) and its stored date
    item_id: str | None
    stored: str | None
    #: the date the benchmark replay gives (``None``: none); ``parity`` is ``None`` when it wasn't replayed
    bench: str | None
    parity: bool | None
    exact: bool
    reminded: bool
    lead_days: int | None
    late_reminder: bool
    not_reminded: str | None
    morning_note: bool
    idea_due: bool
    idea_right: bool | None

    def to_dict(self) -> dict[str, Any]:
        row = asdict(self)
        row.pop("item_id")  # the app's own id means nothing outside its data folder
        return row


@dataclass(frozen=True)
class DraftVerdict:
    refused: bool
    error: str | None
    elements: dict[str, bool | None]
    complete: bool
    own_checks_failed: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LetterVerdict:
    entry_id: str
    split: str
    family: str
    variant: str
    modality: str
    cluster: str
    scam_gold: bool
    status: str
    hidden_text: bool
    scam_idea: bool
    scam_reasons: list[str]
    calendar_events: int
    obligations: list[ObligationVerdict] = field(default_factory=list)
    draft: DraftVerdict | None = None
    objection_on_none: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "split": self.split,
            "family": self.family,
            "variant": self.variant,
            "modality": self.modality,
            "scam_gold": self.scam_gold,
            "status": self.status,
            "hidden_text": self.hidden_text,
            "scam_idea": self.scam_idea,
            "scam_reasons": list(self.scam_reasons),
            "calendar_events": self.calendar_events,
            "obligations": [obligation.to_dict() for obligation in self.obligations],
            "draft": self.draft.to_dict() if self.draft is not None else None,
            "objection_on_none": self.objection_on_none,
        }


def _predicted(item: StoredItem) -> PredictedItem:
    return PredictedItem(
        kind=item.kind, title=item.title, due_date=item.due_date, amount=item.amount, quote=item.quote
    )


def match_stored(entry: Entry, items: Sequence[StoredItem]) -> dict[int, StoredItem]:
    """Labelled item index → the app's to-do it matches (the benchmark's matching over required and optional
    labelled items, so an optional item takes its own to-do)."""
    truth = entry.truth
    labelled = [*truth.items, *truth.optional_items]
    matches = match_items(labelled, [_predicted(item) for item in items], required_count=len(truth.items))
    return {index: items[pred] for index, pred in matches.items()}


def _alarms_from(obs: LetterObservation, item_id: str, reading_day: date) -> list[date]:
    days = {
        day
        for event in obs.events
        if event.item_id == item_id
        for day in (parse_iso(value) for value in event.alarm_days)
        if day is not None and day >= reading_day
    }
    return sorted(days)


def _has_event(obs: LetterObservation, item_id: str) -> bool:
    return any(event.item_id == item_id for event in obs.events)


def _morning_note(entry: Entry, obs: LetterObservation, item_id: str | None, gold: date) -> bool:
    if item_id is None:
        return False
    day = probe_day(entry, gold).isoformat()
    return any(probe.day == day and item_id in probe.item_ids for probe in obs.agenda)


def _idea_due(entry: Entry, obs: LetterObservation, labelled: TruthItem, gold: date) -> bool:
    window = obs.reminder_windows.get(labelled.kind)
    return (
        labelled.kind in IDEA_KINDS and window is not None and 0 <= (gold - entry.today_date).days <= window
    )


def _idea_right(obs: LetterObservation, item_id: str | None, gold: date) -> bool:
    if item_id is None:
        return False
    for idea in obs.ideas:
        act = parse_iso(idea.due_date)
        if idea.rule_id == IDEA_RULE and item_id in idea.item_ids and act is not None and act <= gold:
            return True
    return False


def _why_not(obs: LetterObservation, item: StoredItem | None, alarms: Sequence[date], gold: date) -> str:
    if obs.status == "failed":
        return "reading_failed"
    if item is None:
        return "not_stored"
    if item.due_date is None:
        return "no_date"
    if item.set_aside:
        return "set_aside:" + "+".join(sorted(item.set_aside))
    if not _has_event(obs, item.id):
        return "not_in_calendar"
    if any(day > gold for day in alarms):
        return "only_after_the_day"
    return "no_alarm_from_the_reading_day"


def check_obligation(
    entry: Entry,
    obs: LetterObservation,
    index: int,
    labelled: TruthItem,
    item: StoredItem | None,
    bench: Mapping[int, str | None] | None,
) -> ObligationVerdict:
    """The verdicts for one genuine labelled obligation (``labelled.expected_date`` is set)."""
    gold = labelled.expected_date
    if gold is None:
        raise ValueError(f"{entry.id}: labelled item {index} has no date to be reminded of")
    stored = item.due_date if item is not None and obs.status != "failed" else None
    alarms = _alarms_from(obs, item.id, entry.today_date) if item is not None else []
    in_time = [day for day in alarms if day <= gold]
    reminded = bool(in_time) and obs.status != "failed"
    late = not reminded and any(day > gold for day in alarms)
    idea_due = _idea_due(entry, obs, labelled, gold)
    item_id = item.id if item is not None else None
    bench_date = bench.get(index) if bench is not None else None
    return ObligationVerdict(
        index=index,
        kind=labelled.kind,
        nature=labelled.nature,
        gold=gold.isoformat(),
        item_id=item_id,
        stored=stored,
        bench=bench_date,
        parity=None if bench is None else stored == bench_date,
        exact=stored == gold.isoformat(),
        reminded=reminded,
        lead_days=(gold - in_time[0]).days if reminded else None,
        late_reminder=late,
        not_reminded=None if reminded else _why_not(obs, item, alarms, gold),
        morning_note=_morning_note(entry, obs, item_id, gold),
        idea_due=idea_due,
        idea_right=_idea_right(obs, item_id, gold) if idea_due else None,
    )


# --------------------------------------------------------------------------------------------------
# the objection letter
# --------------------------------------------------------------------------------------------------


def normalise(text: str) -> str:
    """Upper-case letters and digits only (a reference split over a line or spaced differently still matches)."""
    return re.sub(r"[^0-9A-Z]", "", unicodedata.normalize("NFKC", text).upper())


def date_forms(day: date) -> list[str]:
    """The ways a German letter writes ``day``."""
    month = MONTHS_DE[day.month - 1]
    return [
        f"{day.day:02d}.{day.month:02d}.{day.year}",
        f"{day.day}.{day.month}.{day.year}",
        f"{day.day}. {month} {day.year}",
        f"{day.day:02d}. {month} {day.year}",
        day.isoformat(),
    ]


def _signed(lines: Sequence[str], signer: str) -> bool:
    if not signer.strip():
        return False
    closings = [index for index, line in enumerate(lines) if CLOSING.search(line)]
    if not closings:
        return False
    after = lines[closings[-1] + 1 : closings[-1] + 1 + SIGNATURE_LINES]
    return any(signer.strip().casefold() in line.casefold() for line in after)


def draft_elements(
    truth: Truth, draft: DraftSeen, *, objection_due: date | None, signer: str
) -> dict[str, bool | None]:
    """Each of :data:`DRAFT_ELEMENTS` for an objection letter: ``True``/``False``, or ``None`` when the labels
    cannot judge it."""
    text = "\n".join(draft.pdf_lines)
    folded = text.casefold()
    flat = normalise(text)
    references = [normalise(ref.value) for ref in truth.references]
    references = [ref for ref in references if len(ref) >= MIN_REFERENCE_CHARS]
    decided = parse_iso(truth.document_date)
    word = REMEDY_WORDS.get(truth.remedy_type)
    must, send = parse_iso(draft.must_arrive_by), parse_iso(draft.send_by)
    return {
        "remedy_word": word is not None
        and word in folded
        and not any(other in folded for other in REMEDY_WORDS.values() if other != word),
        "reference": any(ref in flat for ref in references) if references else None,
        "decision_date": any(form in text for form in date_forms(decided)) if decided else None,
        "addressee": bool(truth.sender_name)
        and fuzz.partial_ratio(truth.sender_name.casefold(), draft.recipient_block.casefold())
        >= ADDRESSEE_MIN_SCORE,
        "deadline": must == objection_due if objection_due is not None else None,
        "send_by": send is not None and send <= objection_due if objection_due is not None else None,
        "signature": _signed(draft.pdf_lines, signer),
        "no_placeholder": not PLACEHOLDER.search(text),
    }


def draft_complete(elements: Mapping[str, bool | None]) -> bool:
    """Every element the labels can judge is there."""
    return all(value is not False for value in elements.values())


def check_draft(entry: Entry, draft: DraftSeen) -> DraftVerdict:
    if draft.refused:
        return DraftVerdict(
            refused=True, error=draft.error, elements={}, complete=False, own_checks_failed=[]
        )
    elements = draft_elements(
        entry.truth, draft, objection_due=objection_due(entry.truth), signer=draft.signer
    )
    return DraftVerdict(
        refused=False,
        error=draft.error,
        elements=elements,
        complete=draft_complete(elements),
        own_checks_failed=sorted(draft.own_checks_failed),
    )


# --------------------------------------------------------------------------------------------------
# a letter
# --------------------------------------------------------------------------------------------------


def check_letter(
    entry: Entry, obs: LetterObservation, *, bench: Mapping[int, str | None] | None = None
) -> LetterVerdict:
    """Every verdict for one letter. ``bench``: the benchmark replay's date per labelled item index (``None``: no
    replay, parity unknown)."""
    matched = match_stored(entry, obs.items) if obs.status != "failed" else {}
    obligations = (
        [
            check_obligation(entry, obs, index, labelled, matched.get(index), bench)
            for index, labelled in enumerate(entry.truth.items)
            if labelled.expected_date is not None
        ]
        if genuine(entry)
        else []
    )
    return LetterVerdict(
        entry_id=entry.id,
        split=entry.split,
        family=entry.family,
        variant=entry.variant,
        modality=entry.modality,
        cluster=entry.cluster,
        scam_gold=not genuine(entry),
        status=obs.status,
        hidden_text=obs.hidden_text,
        scam_idea=any(idea.rule_id == SCAM_IDEA_RULE for idea in obs.ideas),
        scam_reasons=sorted(obs.scam_reasons),
        calendar_events=len(obs.events),
        obligations=obligations,
        draft=check_draft(entry, obs.draft) if obs.draft is not None else None,
        objection_on_none=obs.objection_on_none,
    )
