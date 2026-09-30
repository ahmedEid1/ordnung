"""The daily brief: a deterministic agenda plus an optional short note written by the model (SPEC §9).

:func:`build_agenda` collects what matters today (overdue, today, the next 7 days, payments this
month, contract decisions, new Ideas); :func:`agenda_text` turns it into plain English without any
model, so a note is always available. :func:`brief_text` asks the model for 2–3 friendly sentences
in the person's language and accepts them only if every date and amount they mention is in the
agenda (and no § appears) and no send-by day is called a due date — otherwise the code-generated
text is used. Model calls are cached per day and agenda hash; the latest brief of a day is kept in
meta ``brief:<date>``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ordnung.clock import now_iso
from ordnung.db.store import Store
from ordnung.ingest.held import is_held
from ordnung.ingest.normalize import fold_punctuation
from ordnung.ingest.verify import parse_amounts, parse_dates
from ordnung.llm.base import LLMError, LLMRequest
from ordnung.llm.prompts import render
from ordnung.llm.runtime import LLMService
from ordnung.llm.schemas import brief_schema
from ordnung.models import AppSettings, BriefOutput, Item, Profile, RefLink, Suggestion
from ordnung.secretary.review import (
    Facts,
    correct_weekdays,
    language_name,
    split_sentences,
    stable_hash,
    strip_weekdays,
    untrusted_json,
)
from ordnung.secretary.triggers import (
    Ledger,
    action_day,
    day_label,
    eur,
    is_decision,
    is_overdue,
    money,
    paid_at_appointment,
    parse_day,
    priority_rank,
)

log = logging.getLogger(__name__)

NEXT_DAYS = 7
DECISION_DAYS = 30
MAX_IDEAS = 3
MAX_LISTED = 3
MAX_BRIEF_CHARS = 700
BRIEF_META_PREFIX = "brief:"


class AgendaEntry(BaseModel):
    """One line of the agenda (an item, a contract decision or an Idea).

    ``date`` is the day the entry is listed and sorted by (a to-do's day to act, which may be its
    send-by day; a decision's send-by day; an Idea's day) and stays internal: what the model sees and
    the note is checked against are ``due`` (a to-do's due date) and ``send_by`` (the day to send a
    transfer or letter by, when it comes before the due date and is not past; a decision's send-by day).
    """

    id: str
    ref: RefLink
    title: str
    kind: str
    date: str | None = None
    due: str | None = None
    send_by: str | None = None
    amount: float | None = None
    currency: str | None = None  # of the amount when it is not in euros
    party: str | None = None
    doc_id: str | None = None
    private: bool = False  # from a "Keep private — no AI" letter: never sent to a model


class Agenda(BaseModel):
    """What matters on ``date`` — built by code, never by a model."""

    date: str
    overdue: list[AgendaEntry] = Field(default_factory=list)
    today: list[AgendaEntry] = Field(default_factory=list)
    next_7_days: list[AgendaEntry] = Field(default_factory=list)
    payments_this_month: list[AgendaEntry] = Field(default_factory=list)
    payments_total: float = 0.0  # in euros: payments in other currencies are summed per currency below
    payments_total_other_currencies: dict[str, float] = Field(default_factory=dict)
    decisions: list[AgendaEntry] = Field(default_factory=list)
    new_ideas: list[AgendaEntry] = Field(default_factory=list)
    #: Letters from the watched folder that wait for the person: not read, so nothing of them is above
    #: (never sent to the model; the code-written note then never says "all clear").
    waiting: int = 0

    def entries(self) -> list[AgendaEntry]:
        """Every entry of every section."""
        return [
            *self.overdue,
            *self.today,
            *self.next_7_days,
            *self.payments_this_month,
            *self.decisions,
            *self.new_ideas,
        ]

    def is_empty(self) -> bool:
        """Nothing to report."""
        return not self.entries()


class Brief(BaseModel):
    """The daily note served by ``GET /api/brief``."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    date: str
    text: str
    source: Literal["llm", "template"]
    generated_at: str | None = None


# --------------------------------------------------------------------------------------------------
# agenda
# --------------------------------------------------------------------------------------------------


def _entry_key(entry: AgendaEntry) -> tuple[str, str, str]:
    return (entry.date or "9999-12-31", entry.title.casefold(), entry.id)


def _other_currency(currency: str | None) -> str | None:
    """``currency`` when it is not euros (``None`` for euros or no currency given)."""
    code = (currency or "EUR").upper()
    return None if code == "EUR" else code


def _send_by(ledger: Ledger, item: Item) -> str | None:
    """``item``'s send-by day when it is one to name: before the due date and not past (a missed one
    means "act today"), and not a payment made in person at an appointment (paid on the day)."""
    due, send = parse_day(item.due_date), parse_day(item.send_by)
    if due is None or send is None or not ledger.today <= send < due:
        return None
    return None if paid_at_appointment(item, ledger.items) else send.isoformat()


def _item_entry(ledger: Ledger, item: Item, day: date | None) -> AgendaEntry:
    doc = ledger.document(item.doc_id)
    return AgendaEntry(
        id=item.id,
        ref=RefLink(type="item", id=item.id),
        title=item.title,
        kind=item.kind,
        date=day.isoformat() if day else item.due_date,
        due=item.due_date,
        send_by=_send_by(ledger, item),
        amount=item.amount,
        currency=_other_currency(item.currency),
        party=ledger.party_name(item.party_id or (doc.party_id if doc else None)),
        doc_id=doc.id if doc else None,
        private=bool(doc and doc.ai_private),
    )


def _idea_entry(idea: Suggestion) -> AgendaEntry:
    return AgendaEntry(
        id=idea.id,
        ref=RefLink(type="suggestion", id=idea.id),
        title=idea.title,
        kind=idea.kind,
        date=idea.due_date,
    )


def _sorted(entries: list[AgendaEntry]) -> list[AgendaEntry]:
    return sorted(entries, key=_entry_key)


def _decisions(ledger: Ledger) -> list[AgendaEntry]:
    entries: list[AgendaEntry] = []
    decided = ledger.decided_contracts()  # confirmed, or the person's cancellation was sent
    for contract in ledger.active_contracts():
        if contract.id in decided:
            continue
        comp = ledger.computation(contract)
        send = parse_day(comp.send_by)
        if is_decision(comp) and send is not None and (send - ledger.today).days <= DECISION_DAYS:
            source = ledger.document(contract.source_doc_id)
            entries.append(
                AgendaEntry(
                    id=contract.id,
                    ref=RefLink(type="contract", id=contract.id),
                    title=contract.name,
                    kind="contract",
                    date=send.isoformat(),
                    send_by=send.isoformat(),
                    amount=contract.monthly_cost(),
                    currency=_other_currency(contract.cost_currency),
                    party=ledger.party_name(contract.party_id),
                    doc_id=source.id if source else None,
                    private=bool(source and source.ai_private),
                )
            )
    return _sorted(entries)


def build_agenda(store: Store, today: date) -> Agenda:
    """The deterministic agenda for ``today`` (entries sorted by date, title, id)."""
    ledger = Ledger(store, today)
    overdue, due_today, soon, payments = [], [], [], []
    month_start = today.replace(day=1)
    next_month = (month_start + timedelta(days=32)).replace(day=1)
    for item in ledger.actionable_items():
        due = parse_day(item.due_date)
        # a fee paid in person at an appointment is paid on its day, never transferred ahead
        act = due if paid_at_appointment(item, ledger.items) else action_day(item)
        if due is None or act is None or (item.kind == "payment" and item.direction == "in"):
            continue
        if is_overdue(item, today):
            overdue.append(_item_entry(ledger, item, due))
        elif due >= today:
            day = max(act, today)  # a missed send-by day means "act today"
            if day == today:
                due_today.append(_item_entry(ledger, item, day))
            elif (day - today).days <= NEXT_DAYS:
                soon.append(_item_entry(ledger, item, day))
        if item.kind == "payment" and month_start <= due < next_month:
            payments.append(_item_entry(ledger, item, due))
    ideas = sorted(
        store.list_suggestions(status="new"),
        key=lambda idea: (priority_rank(idea.priority), idea.due_date or "9999", idea.id),
    )[:MAX_IDEAS]
    # a $50 invoice is not €50: one total per currency
    totals: dict[str, float] = {}
    for entry in payments:
        currency = entry.currency or "EUR"
        totals[currency] = totals.get(currency, 0.0) + (entry.amount or 0.0)
    euros = totals.pop("EUR", 0.0)
    return Agenda(
        date=today.isoformat(),
        overdue=_sorted(overdue),
        today=_sorted(due_today),
        next_7_days=_sorted(soon),
        payments_this_month=_sorted(payments),
        payments_total=round(euros, 2),
        payments_total_other_currencies={
            currency: round(total, 2) for currency, total in sorted(totals.items())
        },
        decisions=_decisions(ledger),
        new_ideas=[_idea_entry(idea) for idea in ideas],
        waiting=sum(1 for doc in ledger.documents.values() if is_held(doc)),
    )


# --------------------------------------------------------------------------------------------------
# code-generated text
# --------------------------------------------------------------------------------------------------


def _describe(entry: AgendaEntry, today: date, *, with_date: bool = True) -> str:
    details = []
    day, due = parse_day(entry.date), parse_day(entry.due)
    if with_date and day is not None and entry.send_by == entry.date and due is not None:
        # listed on its send-by day: say so, and when it is due
        details.extend([f"send by {day_label(day, today)}", f"due {day_label(due, today)}"])
    elif with_date and day is not None:
        details.append(day_label(day, today))
    if entry.amount is not None and entry.kind == "payment":
        details.append(money(entry.amount, entry.currency))
    return f"{entry.title} ({', '.join(details)})" if details else entry.title


def _listing(entries: list[AgendaEntry], today: date, *, with_date: bool = True) -> str:
    shown = [_describe(entry, today, with_date=with_date) for entry in entries[:MAX_LISTED]]
    more = len(entries) - len(shown)
    text = "; ".join(shown)
    return f"{text} and {more} more" if more > 0 else text


def agenda_text(agenda: Agenda) -> str:
    """The brief without any model: short plain-English sentences, always available."""
    today = parse_day(agenda.date) or date.today()
    parts: list[str] = []
    if agenda.overdue:
        parts.append(f"Overdue: {_listing(agenda.overdue, today)}.")
    if agenda.today:
        parts.append(f"Today: {_listing(agenda.today, today, with_date=False)}.")
    if agenda.next_7_days:
        parts.append(f"Next 7 days: {_listing(agenda.next_7_days, today)}.")
    if agenda.payments_this_month:
        count = len(agenda.payments_this_month)
        totals = [
            money(total, currency) for currency, total in agenda.payments_total_other_currencies.items()
        ]
        if any(entry.currency is None for entry in agenda.payments_this_month):  # some are in euros
            totals.insert(0, eur(agenda.payments_total))
        parts.append(
            f"Payments this month: {' and '.join(totals)} in {count} payment{'s' if count != 1 else ''}."
        )
    for decision in agenda.decisions[:MAX_LISTED]:
        send = parse_day(decision.date)
        if send is not None:
            parts.append(
                f"Decide on your {decision.title}: send a cancellation by {day_label(send, today)} if you want to leave."
            )
    if agenda.new_ideas:
        count = len(agenda.new_ideas)
        parts.append(
            f"{count} new idea{'s' if count != 1 else ''}: {_listing(agenda.new_ideas, today, with_date=False)}."
        )
    if not (agenda.overdue or agenda.today or agenda.next_7_days):
        # letters that wait unread may ask for anything: only what was read is clear
        parts.insert(
            0,
            "Nothing is due in the next 7 days from the letters that were read."
            if agenda.waiting
            else "All clear — nothing is due in the next 7 days.",
        )
    return " ".join(parts)


# --------------------------------------------------------------------------------------------------
# model-written note
# --------------------------------------------------------------------------------------------------


def _model_payload(agenda: Agenda) -> dict[str, object]:
    """The agenda as the model sees it: private entries removed, internal fields dropped. Its dates are
    labelled: a to-do's ``due`` date and ``send_by`` day, a decision's ``send_by`` day and an Idea's
    ``act_by`` day (the internal ``date`` a to-do is listed by is one of them, or today)."""

    def rows(entries: list[AgendaEntry]) -> list[dict[str, object]]:
        fields = {"id", "title", "kind", "due", "send_by", "amount", "currency", "party"}
        return [entry.model_dump(include=fields, exclude_none=True) for entry in entries if not entry.private]

    def ideas(entries: list[AgendaEntry]) -> list[dict[str, object]]:
        return [
            {
                **entry.model_dump(include={"id", "title", "kind"}),
                **({"act_by": entry.date} if entry.date else {}),
            }
            for entry in entries
            if not entry.private
        ]

    other = agenda.payments_total_other_currencies
    return {
        "date": agenda.date,
        "overdue": rows(agenda.overdue),
        "today": rows(agenda.today),
        "next_7_days": rows(agenda.next_7_days),
        "payments_this_month": rows(agenda.payments_this_month),
        "payments_total": agenda.payments_total,
        **({"payments_total_other_currencies": other} if other else {}),
        "decisions_send_by": rows(agenda.decisions),
        "new_ideas": ideas(agenda.new_ideas),
    }


def _first_name(profile: Profile) -> str:
    parts = profile.name.split()
    return parts[0].replace("{", "").replace("}", "") if parts else "there"


def brief_cache_key(agenda: Agenda, profile: Profile) -> str:
    """``brief:<date>:<hash of the agenda (as sent), language and name>``."""
    basis = {"agenda": _model_payload(agenda), "language": profile.language, "name": _first_name(profile)}
    return f"{BRIEF_META_PREFIX}{agenda.date}:{stable_hash(basis)[:32]}"


def brief_request(agenda: Agenda, profile: Profile, settings: AppSettings) -> LLMRequest:
    """The ``brief`` model call for ``agenda``."""
    system_version, system = render("brief_system", language_name=language_name(profile.language))
    version, prompt = render(
        "brief",
        today=agenda.date,
        first_name=_first_name(profile),
        agenda=untrusted_json(_model_payload(agenda)),
    )
    doc_ids = sorted({entry.doc_id for entry in agenda.entries() if entry.doc_id and not entry.private})
    return LLMRequest.model_validate(
        {
            "purpose": "brief",
            "prompt": prompt,
            "system": system,
            "schema": brief_schema(),
            "model": settings.models.brief,
            "cache_key": brief_cache_key(agenda, profile),
            "prompt_version": f"{system_version}+{version}",
            "doc_ids": doc_ids,
            "timeout_s": 90.0,
        }
    )


#: Words that call a date a due date, in English and German ("due", "payable", "fällig", "Fälligkeit",
#: "zahlbar", "Zahlungsziel"); "due to" means "because of", and "overdue"/"überfällig" describe a
#: to-do ("the overdue library books") rather than name its date.
_DUE_WORD = re.compile(
    r"\bdue\b(?!\s+to\b)|\bpayable\b|\bfällig\w*|\bzahlbar\w*|\bzahlungsziel\w*",
    re.IGNORECASE,
)
#: Words of a clause about sending: a date there is a send-by day, not one a due word elsewhere labels.
_SEND_WORD = re.compile(
    r"\b(?:by|send|sent|transfer\w*|post|mail|bis|spätestens|überweis\w*|absend\w*|abschick\w*|schick\w*"
    r"|senden|sende)\b",
    re.IGNORECASE,
)
#: Where a sentence's clauses end: ", " (not the comma of "640,00"), ";", ": ", brackets (those that
#: hold neither a date nor a due or send word are unwrapped first, :func:`_unbracket`), a spaced dash
#: (typographic dashes are folded to "-") and a few conjunctions ("and"/"und" do not end one).
_CLAUSE_END = re.compile(
    r",\s|;|:\s|[()\[\]]|\s-+\s|\b(?:but|so|then|while|whereas|aber|doch|sondern|dann|während)\b",
    re.IGNORECASE,
)
_BRACKETED = re.compile(r"[(\[]([^()\[\]]*)[)\]]")
_AND = re.compile(r"\b(?:and|und|as well as|sowie)\b", re.IGNORECASE)
_PLURAL = re.compile(r"\b(?:are|were|sind|waren)\b", re.IGNORECASE)
_WORD = re.compile(r"[^\W\d_]{4,}")
#: Days written relative to the agenda's day, by how many days after it they are ("morgen" is
#: tomorrow; "Morgen" inside a clause is the morning: "Guten Morgen", "heute Morgen").
_RELATIVE_DAYS = {
    "the day after tomorrow": 2,
    "übermorgen": 2,
    "tomorrow": 1,
    "morgen": 1,
    "today": 0,
    "heute": 0,
}
_RELATIVE = re.compile(
    r"\b(?:" + "|".join(word.replace(" ", r"\s+") for word in _RELATIVE_DAYS) + r")\b", re.IGNORECASE
)
#: Weekday names a note may write without a date ("due Wednesday"), by weekday (Monday = 0). Names are
#: capitalised, so a lower-case "sat" or "sun" is no weekday; a date's own weekday ("Fri 2 Oct") is
#: removed before (:func:`~ordnung.secretary.review.strip_weekdays`).
_WEEKDAYS = {
    **dict.fromkeys(("Monday", "Mon", "Montag"), 0),
    **dict.fromkeys(("Tuesday", "Tues", "Tue", "Dienstag"), 1),
    **dict.fromkeys(("Wednesday", "Wed", "Mittwoch"), 2),
    **dict.fromkeys(("Thursday", "Thurs", "Thur", "Thu", "Donnerstag"), 3),
    **dict.fromkeys(("Friday", "Fri", "Freitag"), 4),
    **dict.fromkeys(("Saturday", "Sat", "Samstag", "Sonnabend"), 5),
    **dict.fromkeys(("Sunday", "Sun", "Sonntag"), 6),
}
_WEEKDAY = re.compile(
    r"(?:\b(?P<last>(?i:last|previous|letzten|vergangenen))\s+)?"
    r"\b(?P<name>" + "|".join(sorted(_WEEKDAYS, key=len, reverse=True)) + r")\b"
)
#: A "by" before a date ("by Fri 2 Oct", "bis zum 2. Oktober"): a day to act by, which a due word
#: labels only when it governs it directly (:func:`_labels`).
_BY_BEFORE = re.compile(
    r"\b(?:by|until|before|bis|spätestens|vor)(?:\s+(?:the|zum|am|dem|den|spätestens))*\s*$", re.IGNORECASE
)
#: Words that may stand between a due word and a "by" date it governs ("due by", "bis zum … fällig").
_LINK_WORDS = frozenset(
    {"on", "or", "by", "until", "before", "the", "is", "it", "are", "am", "bis", "zum", "spätestens"}
    | {"vor", "dem", "den", "ist", "sind", "sie", "es", "er", "wird", "werden"}
)
#: Words of titles that name no to-do: months, weekdays and a few common ones.
_NOT_NAMES = frozenset(
    {
        *("january", "february", "march", "april", "june", "july", "august", "september", "october"),
        *("november", "december", "januar", "februar", "märz", "juni", "juli", "oktober", "dezember"),
        *("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "montag"),
        *("dienstag", "mittwoch", "donnerstag", "freitag", "samstag", "sonntag"),
        *("your", "with", "from", "this", "that", "payment", "monthly"),
    }
)


@dataclass(frozen=True)
class _Mention:
    """A date in a clause, with where it is: written out ("2 Oct"), or a day word the agenda's day
    resolves ("tomorrow", "Wednesday"; ``written`` is then false)."""

    text: str
    day: int
    month: int
    year: int | None
    start: int
    end: int
    written: bool = True

    def is_day(self, iso: str | None) -> bool:
        """Whether this mention writes the day ``iso`` (by day and month when it has no year)."""
        value = parse_day(iso)
        if value is None:
            return False
        if self.year is not None:
            return (self.year, self.month, self.day) == (value.year, value.month, value.day)
        return (self.month, self.day) == (value.month, value.day)


def _day_word(match: re.Match[str], day: date, group: int | str = 0) -> _Mention:
    start, end = match.span(group)
    return _Mention(match.group(group), day.day, day.month, day.year, start, end, written=False)


def _mentions(clause: str, today: date) -> list[_Mention]:
    """The dates of ``clause`` in order: written ones, and "today"/"tomorrow"/"heute"/"morgen" and bare
    weekday names ("due Wednesday": the next such day after ``today``, as today is "today"; "last
    Friday" is left out)."""
    found: list[_Mention] = []
    cursor = 0
    for mention in parse_dates(clause):
        start = clause.find(mention.text, cursor)
        start = cursor if start < 0 else start
        cursor = start + len(mention.text)
        found.append(_Mention(mention.text, mention.day, mention.month, mention.year, start, cursor))
    for match in _RELATIVE.finditer(clause):
        if match.group() == "Morgen" and clause[: match.start()].strip():
            continue
        ahead = _RELATIVE_DAYS[" ".join(match.group().casefold().split())]
        found.append(_day_word(match, today + timedelta(days=ahead)))
    for match in _WEEKDAY.finditer(clause):
        if match.group("last"):
            continue
        ahead = (_WEEKDAYS[match.group("name")] - today.weekday()) % 7 or 7
        found.append(_day_word(match, today + timedelta(days=ahead), "name"))
    return sorted(found, key=lambda mention: mention.start)


def _unbracket(sentence: str, today: date) -> str:
    """``sentence`` with the brackets that hold no date and no due or send word written as spaces: an
    amount or a word in brackets belongs to its clause ("the gym fee (€29.90) is due", "rent (Miete)")."""

    def unwrap(match: re.Match[str]) -> str:
        inner = match.group(1)
        if _DUE_WORD.search(inner) or _SEND_WORD.search(inner) or _mentions(inner, today):
            return match.group()
        return f" {inner} "

    return _BRACKETED.sub(unwrap, sentence)


def _todos(agenda: Agenda) -> list[AgendaEntry]:
    """The agenda's to-dos and contract decisions (not Ideas), each once."""
    seen: dict[str, AgendaEntry] = {}
    sections = (
        agenda.overdue,
        agenda.today,
        agenda.next_7_days,
        agenda.payments_this_month,
        agenda.decisions,
    )
    for entry in (entry for section in sections for entry in section):
        seen.setdefault(entry.id, entry)
    return list(seen.values())


def _own_words(todos: list[AgendaEntry]) -> dict[str, set[str]]:
    """Per to-do, the words of its title and party that no other to-do has ("rent", "TechMarkt")."""
    words = {
        todo.id: {word.casefold() for word in _WORD.findall(f"{todo.title} {todo.party or ''}")} - _NOT_NAMES
        for todo in todos
    }
    counts: dict[str, int] = {}
    for found in words.values():
        for word in found:
            counts[word] = counts.get(word, 0) + 1
    return {key: {word for word in found if counts[word] == 1} for key, found in words.items()}


def _named(text: str, todos: list[AgendaEntry], words: dict[str, set[str]]) -> list[AgendaEntry]:
    """The to-dos ``text`` talks about: by amount, or by a word of their own."""
    cents = {round(amount * 100) for amount in parse_amounts(text)}
    said = {word.casefold() for word in _WORD.findall(text)}
    return [
        todo
        for todo in todos
        if (todo.amount is not None and round(todo.amount * 100) in cents) or words[todo.id] & said
    ]


def _mislabelled(mention: _Mention, named: list[AgendaEntry], todos: list[AgendaEntry]) -> bool:
    """Whether calling ``mention`` due is wrong: a to-do the text names has it as its send-by day and
    not as its due date; when none it names has that day, when it is only ever a send-by day."""
    about = [todo for todo in named if mention.is_day(todo.due) or mention.is_day(todo.send_by)]
    if about:
        return any(mention.is_day(todo.send_by) and not mention.is_day(todo.due) for todo in about)
    return any(mention.is_day(todo.send_by) for todo in todos) and not any(
        mention.is_day(todo.due) for todo in todos
    )


def _labels(clause: str, word: re.Match[str], mention: _Mention) -> bool:
    """Whether the due word ``word`` can label ``mention``: always, unless the date follows a "by" and
    the due word does not govern it directly — "the amount due of €94.99 by 29 Sep" names a day to pay
    by, "due by 2 Oct" and "bis zum 2. Oktober fällig" a due date."""
    if not _BY_BEFORE.search(clause[: mention.start]):
        return True
    if word.end() <= mention.start:
        between = clause[word.end() : mention.start]
    else:
        between = clause[mention.end : word.start()]
    return all(token.casefold() in _LINK_WORDS for token in re.findall(r"\w+", between))


def _nearest(dates: list[_Mention], word: re.Match[str]) -> _Mention:
    """The date nearest to ``word`` (the later one on a tie)."""
    return min(dates, key=lambda m: (max(m.start - word.end(), word.start() - m.end), -m.start))


def _parts(clause: str) -> list[tuple[int, int]]:
    """The spans of ``clause``'s "and" parts ("the fee is due" · "the rent goes out")."""
    spans: list[tuple[int, int]] = []
    start = 0
    for joint in _AND.finditer(clause):
        spans.append((start, joint.start()))
        start = joint.end()
    spans.append((start, len(clause)))
    return spans


def _about(
    clauses: list[str], index: int, word: re.Match[str], todos: list[AgendaEntry], words: dict[str, set[str]]
) -> list[AgendaEntry]:
    """The to-dos the due word ``word`` of ``clauses[index]`` is about: those named in its "and" part
    (every part not about sending after a plural verb: "the rent and the fee are due"), else in the
    other parts of its clause, else in the other clauses of its sentence — parts and clauses about
    sending left out ("… both due that day, and transfer the rent")."""
    clause = clauses[index]
    parts = [(clause[start:end], start <= word.start() <= end) for start, end in _parts(clause)]
    if _PLURAL.search(clause[: word.start()]):
        subject = " ".join(text for text, own in parts if own or not _SEND_WORD.search(text))
    else:
        subject = next(text for text, own in parts if own)
    other_parts = [text for text, own in parts if not own and not _SEND_WORD.search(text)]
    other_clauses = [
        other for at, other in enumerate(clauses) if at != index and not _SEND_WORD.search(other)
    ]
    for text in (subject, " ".join(other_parts), " ".join(other_clauses)):
        if found := _named(text, todos, words):
            return found
    return []


def mislabelled_dates(text: str, agenda: Agenda) -> list[str]:
    """Dates ``text`` calls due ("due", "fällig", …) that are a send-by day, not the due date.

    Dates are written ones and the day words the agenda's day resolves ("due tomorrow", "due
    Wednesday"). A due word labels the date of its clause nearest to it, in its own "and" part first (a
    "by" date only when the due word governs it, :func:`_labels`). A due word in a clause without any
    date labels the dates of its sentence's clauses that are not about sending ("Then on Fri 2 Oct, the
    rent is due") — but not today's date when the sentence writes it out ("Today is Tue 29 Sep; …" says
    what day it is, so "Today, Tue 29 Sep, the fee is due" is not checked). The to-dos it is about are
    :func:`_about`; whether the label is wrong, :func:`_mislabelled`.
    """
    today = parse_day(agenda.date) or date.today()
    todos = _todos(agenda)
    words = _own_words(todos)
    wrong: list[str] = []
    for sentence in split_sentences(strip_weekdays(fold_punctuation(text))):
        sentence = _unbracket(sentence, today)
        clauses = [clause for clause in _CLAUSE_END.split(sentence) if clause.strip()]
        found = [_mentions(clause, today) for clause in clauses]
        states_today = any(
            mention.written and mention.is_day(agenda.date) for dates in found for mention in dates
        )
        loose = [
            mention
            for clause, dates in zip(clauses, found, strict=True)
            if not _SEND_WORD.search(clause)
            for mention in dates
            if not (states_today and mention.is_day(agenda.date))
        ]
        for index, (clause, dates) in enumerate(zip(clauses, found, strict=True)):
            spans = _parts(clause)
            for word in _DUE_WORD.finditer(clause):
                start, end = next(span for span in spans if span[0] <= word.start() <= span[1])
                candidates = [mention for mention in dates if _labels(clause, word, mention)]
                in_part = [mention for mention in candidates if start <= mention.start < end]
                # its own date; with none, the sentence's (a clause whose only dates are "by" dates has none)
                labelled = [_nearest(in_part or candidates, word)] if candidates else [] if dates else loose
                named = _about(clauses, index, word, todos, words)
                for mention in labelled:
                    if mention.text not in wrong and _mislabelled(mention, named, todos):
                        wrong.append(mention.text)
    return wrong


def grounded_note(text: str, agenda: Agenda) -> bool:
    """Whether a model note is acceptable: short, every date/amount/§ it mentions is in the agenda, and
    no send-by day is called a due date (:func:`mislabelled_dates`)."""
    if not text.strip() or len(text) > MAX_BRIEF_CHARS:
        return False
    if Facts.from_data(agenda.model_dump(exclude={"waiting"})).unsupported(text):
        return False
    return not mislabelled_dates(text, agenda)


def _note_from(data: dict[str, object] | None, text: str) -> str:
    if data is None:
        return text.strip()
    try:
        return BriefOutput.model_validate(data).text.strip()
    except ValidationError:
        return ""


async def brief_text(
    llm: LLMService, agenda: Agenda, profile: Profile, *, settings: AppSettings | None = None
) -> Brief:
    """A 2–3 sentence note by the model, or the code-generated :func:`agenda_text` when the agenda is
    empty, the call fails or the note mentions a date, amount or § that is not in the agenda."""
    fallback = Brief(date=agenda.date, text=agenda_text(agenda), source="template", generated_at=now_iso())
    if agenda.is_empty():
        return fallback
    request = brief_request(agenda, profile, settings or AppSettings())
    try:
        response = await llm.complete(request)
    except LLMError as exc:
        log.info("brief: model unavailable, using the agenda text (%s)", exc)
        return fallback
    note = _note_from(response.data, response.text)
    if not grounded_note(note, agenda):
        log.warning("brief: model note failed the free-text check; using the agenda text")
        return fallback
    note = correct_weekdays(note, date.fromisoformat(agenda.date))
    return Brief(date=agenda.date, text=note, source="llm", generated_at=now_iso())


def brief_key(day: date) -> str:
    """Meta key of the brief of ``day``."""
    return f"{BRIEF_META_PREFIX}{day.isoformat()}"


def get_brief(store: Store, day: date) -> Brief | None:
    """The stored brief of ``day`` (``None`` if none was generated yet)."""
    raw = store.get_meta(brief_key(day))
    return Brief.model_validate_json(raw) if raw else None


def current_brief(store: Store, day: date) -> Brief:
    """The note to show for ``day``: the stored one written by the model, else the code-written note
    as the ledger stands now — the stored one (with the time it was written) while it still says the
    same. A code-written note costs nothing to write again, so it never goes stale: a letter picked up
    from the watched folder or answered since changes it at once."""
    stored = get_brief(store, day)
    if stored is not None and stored.source == "llm":
        return stored
    agenda = build_agenda(store, day)
    text = agenda_text(agenda)
    if stored is not None and stored.text == text:
        return stored
    return Brief(date=agenda.date, text=text, source="template")


async def generate_brief(store: Store, llm: LLMService | None, today: date) -> Brief:
    """Build the agenda, write the note (model if ``llm`` is given, else code) and store it in meta."""
    agenda = build_agenda(store, today)
    if llm is None:
        brief = Brief(date=agenda.date, text=agenda_text(agenda), source="template", generated_at=now_iso())
    else:
        brief = await brief_text(llm, agenda, store.get_profile(), settings=store.get_settings())
    store.set_meta(brief_key(today), brief.model_dump_json())
    return brief
