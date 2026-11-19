"""Deterministic secretary triggers — the ledger turned into "Ideas" (SPEC §9, §21).

Every trigger reads a :class:`Ledger` (one consistent snapshot of the store for one day) and returns
:class:`~ordnung.models.Suggestion` models with ``source="rule"``: refs to real ids, an action named
after what the person does ("Draft cancellation", "Pay", "Check the letter"), a priority and the day
to act by. Dates come from stored items or from the rules engine — never from a model.

Fingerprints are ``rule_id:entity_id:hash(triggering values)``: while the facts stay the same an
Idea keeps its identity (and the person's "dismissed"/"snoozed" choice); when they change, a fresh
Idea replaces it and the old one expires. :func:`run_and_reconcile` persists everything. Nothing in
this module closes, dismisses or marks an obligation — overdue is computed on read (SPEC §21).

An Idea about letters the person filed for someone of their household names that person ("For Alex Rivera:
…", "Alex Rivera's passport expires …"; :func:`named`, ADR 0023). Who it is is not in the fingerprint, so filing
a letter renames the same Idea and keeps the person's choice; without a household every Idea is as before.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from ordnung.days import parse_day as parse_day
from ordnung.days import parse_timestamp as parse_timestamp
from ordnung.db.store import Store
from ordnung.drafts.proof import (
    channel_label,
    delivery_record_obtainable,
    followup_item_id,
)
from ordnung.drafts.tracking import tracking_info
from ordnung.ingest.gaps import CHECK_SLOT, is_check_slot
from ordnung.ingest.held import is_held
from ordnung.models import (
    Contract,
    Document,
    Draft,
    Item,
    Priority,
    Suggestion,
    SuggestionAction,
    SuggestionRef,
)
from ordnung.payments import is_collected_or_incoming, is_direct_debit
from ordnung.rules import get_rule
from ordnung.rules.deadlines import postal_buffer as postal_buffer
from ordnung.rules.deadlines import sending_time_passed
from ordnung.secretary.ledger import _NOT_A_SIGN as _NOT_A_SIGN
from ordnung.secretary.ledger import CALENDAR_META_KEY as CALENDAR_META_KEY
from ordnung.secretary.ledger import HIDDEN_TEXT_SIGN as HIDDEN_TEXT_SIGN
from ordnung.secretary.ledger import IDEA_LAWS as IDEA_LAWS
from ordnung.secretary.ledger import IDENTITY_WINDOW_DAYS as IDENTITY_WINDOW_DAYS
from ordnung.secretary.ledger import PERMIT_WINDOW_DAYS as PERMIT_WINDOW_DAYS
from ordnung.secretary.ledger import REGISTRATION_LAW as REGISTRATION_LAW
from ordnung.secretary.ledger import (
    RESIDENCE_EXTENSION_LAW,
    STUDENT_WORK_LAW,
    _draft,
    _letter_title,
    _open,
    _ref,
    _sentences,
    iban_fails_checksum,
    in_days,
)
from ordnung.secretary.ledger import SCAM_RULE as SCAM_RULE
from ordnung.secretary.ledger import IdeaText as IdeaText
from ordnung.secretary.ledger import Ledger as Ledger
from ordnung.secretary.ledger import PriceIncreaseWindow as PriceIncreaseWindow
from ordnung.secretary.ledger import _RowsCache as _RowsCache
from ordnung.secretary.ledger import _scam_reasons as _scam_reasons
from ordnung.secretary.ledger import action_day as action_day
from ordnung.secretary.ledger import cancellations_sent as cancellations_sent
from ordnung.secretary.ledger import contract_area as contract_area
from ordnung.secretary.ledger import contract_computation as contract_computation
from ordnung.secretary.ledger import contribution_rate as contribution_rate
from ordnung.secretary.ledger import day_label as day_label
from ordnung.secretary.ledger import english as english
from ordnung.secretary.ledger import eur as eur
from ordnung.secretary.ledger import expiry_class as expiry_class
from ordnung.secretary.ledger import fingerprint as fingerprint
from ordnung.secretary.ledger import is_active as is_active
from ordnung.secretary.ledger import is_decision as is_decision
from ordnung.secretary.ledger import is_overdue as is_overdue
from ordnung.secretary.ledger import is_scam_warning as is_scam_warning
from ordnung.secretary.ledger import letter_day as letter_day
from ordnung.secretary.ledger import make_idea as make_idea
from ordnung.secretary.ledger import money as money
from ordnung.secretary.ledger import paid_at_appointment as paid_at_appointment
from ordnung.secretary.ledger import priority_rank as priority_rank
from ordnung.secretary.ledger import scam_signs as scam_signs
from ordnung.secretary.ledger import unconfirmed_reason as unconfirmed_reason
from ordnung.secretary.ledger import was_history_when_filed as was_history_when_filed
from ordnung.secretary.ledger import zusatzbeitrag_raised as zusatzbeitrag_raised
from ordnung.secretary.tax_choice import for_taxes

if TYPE_CHECKING:
    from ordnung.secretary.household import HouseholdMember

try:  # the scam checks are optional: the triggers work without them
    from ordnung.secretary import scam as _scam
except ImportError:  # pragma: no cover - only while the module is absent
    _scam = None  # type: ignore[assignment]

log = logging.getLogger(__name__)

#: Item kinds reported by ``deadline_soon`` (expiries are handled by ``expiry_soon``).
SOON_KINDS = frozenset({"deadline", "payment", "task", "appointment", "reminder", "milestone"})
CANCEL_WINDOW_DAYS = 60
PASSPORT_MARGIN_DAYS = 180
PASSPORT_CHECK_HORIZON_DAYS = 365
TAX_SEASON_LAST_MONTH = 7
FOLLOWUP_LATE_DAYS = 14
#: calendar sync's connection record (:data:`ordnung.calendar.caldav.STATE_KEY`)
CALENDAR_SYNC_META_KEY = "calendar_sync"
STUDENT_PERMIT_RULE = "student_permit_info"

_PRICE_RULES = ("enwg_41_5", "stromgvv_5_3", "tkg_57", "vvg_40", "sgbv_175_4_zb")
_INTERVAL_PER_YEAR = {"monthly": 12, "quarterly": 4, "yearly": 1}

_PERMIT_LINKS = (
    "https://www.gesetze-im-internet.de/aufenthg_2004/__16b.html",
    "https://www.studierendenwerke.de",
)


# --------------------------------------------------------------------------------------------------
# item actions
# --------------------------------------------------------------------------------------------------


def item_action(ledger: Ledger, item: Item) -> SuggestionAction:
    """The one verb for an item: Pay · Draft objection · Draft cancellation · Check the letter."""
    doc = ledger.document(item.doc_id)
    nature = item.date_spec.nature if item.date_spec else "other"
    if is_check_slot(item.slot_key) and item.slot_key != CHECK_SLOT and doc is not None:
        # a date Ordnung took from the letter for a reading that left it out (check:deadline): a cross-check, never
        # "Pay"
        return _open("document", doc.id, "Check the letter")
    if item.kind == "payment":
        return _open("document", doc.id, "Pay") if doc else _open("item", item.id, "Pay")
    if nature == "objection" and doc and doc.remedy and doc.remedy.type in ("einspruch", "widerspruch"):
        return _draft("objection", "document", doc.id, "Draft objection")
    if nature == "notice" and item.contract_id:
        return _draft("cancellation", "contract", item.contract_id, "Draft cancellation")
    if doc is not None:
        return _open("document", doc.id, "Check the letter")
    return _open("item", item.id, "Open the to-do")


def _item_refs(ledger: Ledger, item: Item) -> list[SuggestionRef]:
    refs = [_ref("item", item.id)]
    if ledger.document(item.doc_id):
        refs.append(_ref("document", item.doc_id or ""))
    if item.contract_id:
        refs.append(_ref("contract", item.contract_id))
    return refs


def _source_line(ledger: Ledger, item: Item) -> str | None:
    doc = ledger.document(item.doc_id)
    if doc is None:
        return None
    sender = ledger.party_name(doc.party_id)
    written = parse_day(doc.doc_date)
    parts = ["From the letter"]
    if written:
        parts.append(f"of {day_label(written, ledger.today)}")
    if sender:
        parts.append(f"from {sender}")
    return " ".join(parts) + "."


def _item_priority(kind: str, days_left: int) -> Priority:
    if kind in ("deadline", "payment"):
        if days_left <= 3:
            return "critical"
        return "high" if days_left <= 7 else "normal"
    return "high" if days_left <= 1 else "normal"


# --------------------------------------------------------------------------------------------------
# triggers
# --------------------------------------------------------------------------------------------------


def _handled_elsewhere(ledger: Ledger, item: Item) -> bool:
    """Money coming in, direct debits (the sender collects them — nothing to do), payment reminders
    (``dunning_escalation``), letters with scam signs the person hasn't checked (``scam_warning``) and
    payments another letter took over (a payment reminder, an e-mail's attached bill) never become "do this
    by" Ideas."""
    return (
        is_collected_or_incoming(item)
        or ledger.is_dunning_item(item)
        or ledger.is_suspicious_item(item)
        or ledger.is_superseded_by_reminder(item)
        or ledger.is_covered_by_attachment(item)
    )


def deadline_soon(ledger: Ledger) -> list[Suggestion]:
    """Open dated items whose day to act is within their reminder window (default 14 d deadlines,
    7 d payments). Payment reminders (dunning) are left to ``dunning_escalation``."""
    ideas: list[Suggestion] = []
    today = ledger.today
    for item in ledger.active_items():
        due, act = parse_day(item.due_date), action_day(item)
        if item.kind not in SOON_KINDS or due is None or act is None or due < today:
            continue
        if _handled_elsewhere(ledger, item):
            continue
        days = (act - today).days
        if days > ledger.reminder_window(item.kind):
            continue
        ideas.append(_soon_idea(ledger, item, due, act, days))
    return ideas


def _soon_idea(ledger: Ledger, item: Item, due: date, act: date, days: int) -> Suggestion:
    today = ledger.today
    if item.kind == "appointment":
        when = f"on {day_label(due, today)}" + (f" at {item.due_time}" if item.due_time else "")
    elif item.kind == "payment":
        when = f"pay by {day_label(act, today)}"
    elif sending_time_passed(item.computation):
        when = f"must arrive by {day_label(due, today)}"
    elif act < due:
        when = f"send by {day_label(act, today)}"
    else:
        when = f"due {day_label(due, today)}"
    send_note = None
    if act < due:
        send_note = f"Send it by {day_label(act, today)} so it arrives by {day_label(due, today)}."
    if days < 0 or sending_time_passed(item.computation):
        send_note = "The usual sending time has passed — use the fastest channel allowed today."
    english_consequence = english(item.consequence)
    consequence = f"If you don't: {english_consequence.rstrip('.')}." if english_consequence else None
    body = _sentences(
        english(item.action) or english(item.description),
        send_note,
        consequence,
        f"That's {in_days(max(days, 0))}.",
    )
    rationale = item.computation.summary if item.computation and item.computation.summary else None
    return make_idea(
        "deadline_soon",
        item.id,
        (item.due_date, item.send_by),
        IdeaText(f"{item.title}: {when}", body, rationale or _source_line(ledger, item)),
        kind="deadline",
        priority=_item_priority(item.kind, days),
        refs=_item_refs(ledger, item),
        action=item_action(ledger, item),
        due_date=max(act, today),
    )


def overdue(ledger: Ledger) -> list[Suggestion]:
    """Active deadlines, payments and tasks whose due date has passed (computed on read)."""
    ideas: list[Suggestion] = []
    today = ledger.today
    for item in ledger.active_items():
        due = parse_day(item.due_date)
        if due is None or not is_overdue(item, today) or _handled_elsewhere(ledger, item):
            continue
        consequence = f"If it stays undone: {item.consequence.rstrip('.')}." if item.consequence else None
        body = _sentences(
            f"This was due on {day_label(due, today)} ({in_days((due - today).days)}).",
            consequence,
            "If you've already dealt with it, mark it as done; otherwise act today and consider getting advice.",
        )
        ideas.append(
            make_idea(
                "overdue",
                item.id,
                (item.due_date,),
                IdeaText(f"Overdue: {item.title}", body, _source_line(ledger, item)),
                kind="deadline",
                priority="critical" if item.kind in ("deadline", "payment") else "high",
                refs=_item_refs(ledger, item),
                action=item_action(ledger, item),
                due_date=due,
            )
        )
    return ideas


def _citations(rule_ids: Iterable[str], wanted: Iterable[str] | None = None) -> str:
    chosen = [rid for rid in rule_ids if wanted is None or rid in wanted]
    texts: list[str] = []
    for rid in chosen:
        try:
            citation = get_rule(rid).citation
        except KeyError:
            continue
        if citation not in texts:
            texts.append(citation)
    return "; ".join(texts)


def _cost_line(contract: Contract) -> str | None:
    monthly = contract.monthly_cost()
    if monthly is None:
        return None
    return f"It costs {eur(monthly)} a month ({eur(round(monthly * 12, 2))} a year)."


def contract_cancel_window(ledger: Ledger) -> list[Suggestion]:
    """Active contracts whose cancellation must be sent within 60 days to avoid a renewal."""
    ideas: list[Suggestion] = []
    today = ledger.today
    decided = ledger.decided_contracts()
    for contract in ledger.active_contracts():
        comp = ledger.computation(contract)
        send = parse_day(comp.send_by)
        if not is_decision(comp) or send is None or (send - today).days > CANCEL_WINDOW_DAYS:
            continue
        if contract.id in decided:
            continue
        days = (send - today).days
        term_end = parse_day(comp.current_term_end)
        keep = None
        if term_end is not None:
            keep = f"If you keep it, you don't need to do anything — it continues after {day_label(term_end, today)}."
        body = _sentences(comp.summary, _cost_line(contract), keep)
        closes = in_days(((parse_day(comp.cancel_by) or send) - today).days)
        citations = _citations(comp.rule_ids[:1])
        rationale = f"The cancellation window closes {closes}" + (f" ({citations})." if citations else ".")
        refs = [_ref("contract", contract.id)]
        if contract.party_id in ledger.parties:
            refs.append(_ref("party", contract.party_id or ""))
        if ledger.document(contract.source_doc_id):
            refs.append(_ref("document", contract.source_doc_id or ""))
        ideas.append(
            make_idea(
                "contract_cancel_window",
                contract.id,
                (comp.cancel_by, comp.current_term_end),
                IdeaText(
                    f"Decide on your {contract.name} — send by {day_label(send, today)}", body, rationale
                ),
                kind="deadline",
                priority="critical" if days <= 3 else "high" if days <= 14 else "normal",
                refs=refs,
                action=_draft("cancellation", "contract", contract.id, "Draft cancellation"),
                due_date=send,
            )
        )
    return ideas


def yearly_extra_cost(old: float | None, new: float | None, interval: str | None) -> float | None:
    """Extra cost per year of a price change (``None`` when it can't be normalised)."""
    per_year = _INTERVAL_PER_YEAR.get(interval or "")
    if old is None or new is None or per_year is None:
        return None
    return round((new - old) * per_year, 2)


def price_increase_right(ledger: Ledger) -> list[Suggestion]:
    """Price-increase letters linked to an active contract with a statutory special cancellation
    window still open (:meth:`Ledger.price_increase_windows`)."""
    ideas: list[Suggestion] = []
    today = ledger.today
    for window in ledger.price_increase_windows():
        doc, contract, change, receipt = window.letter, window.contract, window.change, window.receipt
        due = window.due
        old = change.old_amount if change.old_amount is not None else contract.cost_amount
        extra = yearly_extra_cost(old, change.new_amount, change.cost_interval or contract.cost_interval)
        who = ledger.party_name(contract.party_id) or contract.name
        cost = f": +{eur(extra)}/year extra cost" if extra is not None and extra > 0 else ""
        title = f"{who} raises prices{cost} — you may cancel until {day_label(due, today)}"
        act = parse_day(receipt.send_by) or due
        body = _sentences(receipt.summary, *receipt.warnings[:1], "Compare offers before you decide.")
        rationale = (
            f"Special right to cancel after a price increase ({_citations(receipt.rule_ids, _PRICE_RULES)})."
        )
        switch = "sgbv_175_4_zb" in receipt.rule_ids
        action = (
            _open("document", doc.id, "Compare insurers")
            if switch
            else _draft("cancellation", "contract", contract.id, "Draft cancellation")
        )
        days = (act - today).days
        ideas.append(
            make_idea(
                "price_increase_right",
                doc.id,
                (change.effective_date, receipt.due_date, extra),
                IdeaText(title, body, rationale),
                kind="deadline",
                priority="critical" if days <= 3 else "high" if days <= 14 else "normal",
                refs=[_ref("document", doc.id), _ref("contract", contract.id)],
                action=action,
                due_date=max(act, today),
            )
        )
    return ideas


def _expiry_window(ledger: Ledger, klass: str) -> int:
    if klass == "permit":
        return PERMIT_WINDOW_DAYS
    if klass == "identity":
        return IDENTITY_WINDOW_DAYS
    return ledger.reminder_window("expiry")


def _whose(member: HouseholdMember, what: str) -> str:
    """``what`` (a phrase that starts with a document: "passport expires …") said of a person of the household:
    "Alex Rivera's passport expires …", or "For Kim 2: Passport expires …" for a name that doesn't end in a
    letter (:func:`ordnung.secretary.household.possessive`)."""
    from ordnung.secretary.household import possessive

    owner = possessive(member.name)
    return f"{owner} {what}" if owner else for_member(member, what[:1].upper() + what[1:])


def for_member(member: HouseholdMember, title: str) -> str:
    """An Idea's title about letters filed for a person of the household: "For Alex Rivera: …"."""
    return f"For {member.name}: {title}"


def _member_expiry_text(klass: str, item: Item, member: HouseholdMember, day: str, past: bool) -> IdeaText:
    """:func:`_expiry_text` for a passport or residence permit of a person of the household: their name instead
    of "your" (the rationale is the same)."""
    if klass == "permit":
        if past:
            return IdeaText(
                _whose(member, f"residence permit expired on {day}"),
                "Contact the immigration office (Ausländerbehörde) right away and get advice — a migration "
                "counselling service can help.",
                f"Residence permits must be extended before they expire ({RESIDENCE_EXTENSION_LAW}).",
            )
        return IdeaText(
            _whose(member, f"residence permit expires {day} — apply for the extension now"),
            "Apply at the immigration office (Ausländerbehörde) before it expires. If the application is in time, "
            f"the current permit continues to count until the office decides ({RESIDENCE_EXTENSION_LAW}) — ask "
            "for a Fiktionsbescheinigung. Appointments are often booked out for weeks.",
            f"Residence permits: apply before expiry ({RESIDENCE_EXTENSION_LAW}).",
        )
    document = "passport or ID" if "ausweis" in item.title.casefold() else "passport"
    return IdeaText(
        _whose(member, f"{document} {'expired on' if past else 'expires'} {day}"),
        "Renewing a passport or ID card can take weeks or months (embassy or consulate appointments), so start "
        "early. Their residence permit can usually only run as long as their passport is valid.",
        f"Identity documents are flagged {IDENTITY_WINDOW_DAYS} days before they expire.",
    )


def _expiry_text(
    klass: str, item: Item, expiry: date, today: date, member: HouseholdMember | None = None
) -> IdeaText:
    day = day_label(expiry, today)
    past = expiry < today
    if member is not None and klass in ("permit", "identity"):
        return _member_expiry_text(klass, item, member, day, past)
    if klass == "permit":
        if past:
            return IdeaText(
                f"Your residence permit expired on {day}",
                "Contact the immigration office (Ausländerbehörde) right away and get advice — the "
                "Studierendenwerk, your international office or a migration counselling service can help.",
                f"Residence permits must be extended before they expire ({RESIDENCE_EXTENSION_LAW}).",
            )
        return IdeaText(
            f"Residence permit expires {day} — apply for the extension now",
            "Apply at the immigration office (Ausländerbehörde) before it expires. If you apply in time, "
            f"your current permit continues to count until they decide ({RESIDENCE_EXTENSION_LAW}) — ask for a "
            "Fiktionsbescheinigung. Appointments are often booked out for weeks.",
            f"Residence permits: apply before expiry ({RESIDENCE_EXTENSION_LAW}).",
        )
    if klass == "identity":
        return IdeaText(
            f"Your {'passport or ID' if 'ausweis' in item.title.casefold() else 'passport'} "
            f"{'expired on' if past else 'expires'} {day}",
            "Renewing a passport or ID card can take weeks or months (embassy or consulate appointments), "
            "so start early. Your residence permit can usually only run as long as your passport is valid.",
            f"Identity documents are flagged {IDENTITY_WINDOW_DAYS} days before they expire.",
        )
    return IdeaText(
        f"{item.title}: {'expired' if past else 'expires'} {day}",
        _sentences(item.action or item.description, f"That's {in_days((expiry - today).days)}."),
    )


def expiry_soon(ledger: Ledger) -> list[Suggestion]:
    """Expiring documents: passport/ID 180 days ahead, residence permit 90 days (apply before expiry,
    § 81 Abs. 4 AufenthG), other expiries within their reminder window. Expired ones too."""
    ideas: list[Suggestion] = []
    today = ledger.today
    for item in ledger.active_items():
        expiry = parse_day(item.due_date)
        if item.kind != "expiry" or expiry is None:
            continue
        doc = ledger.document(item.doc_id)
        klass = expiry_class(item, doc)
        days = (expiry - today).days
        if days > _expiry_window(ledger, klass):
            continue
        if klass == "permit":
            priority: Priority = "critical" if days <= 30 else "high"
            label = "Check the permit"
        elif klass == "identity":
            priority = "high" if days <= 60 else "normal"
            label = "Check the passport"
        else:
            priority = "high" if days <= 7 else "normal"
            label = "Check the letter"
        action = _open("document", doc.id, label) if doc else _open("item", item.id, "Open the to-do")
        member = ledger.named_member(item.doc_id)
        text = _expiry_text(klass, item, expiry, today, member)
        if member is not None and klass == "other":
            text = IdeaText(for_member(member, text.title), text.body, text.rationale)
        ideas.append(
            make_idea(
                "expiry_soon",
                item.id,
                (item.due_date, klass),
                text,
                kind="deadline",
                priority=priority,
                refs=_item_refs(ledger, item),
                action=action,
                due_date=expiry,
            )
        )
    return ideas


def _expiries(ledger: Ledger, klass: str) -> list[tuple[Item, date]]:
    found: list[tuple[Item, date]] = []
    for item in ledger.active_items():
        expiry = parse_day(item.due_date)
        if item.kind == "expiry" and expiry and expiry_class(item, ledger.document(item.doc_id)) == klass:
            found.append((item, expiry))
    return sorted(found, key=lambda pair: (pair[1], pair[0].id))


def _passport_first_text(
    member: HouseholdMember | None, relation: str, passport_day: str, permit_day: str
) -> tuple[str, str]:
    """:func:`passport_before_permit`'s title and body, for the person or a person of the household."""
    if member is None:
        return (
            "Renew your passport before extending your residence permit",
            _sentences(
                f"Your passport expires on {passport_day} — {relation} your residence permit ({permit_day}).",
                "The immigration office (Ausländerbehörde) usually extends a permit only as long as your passport "
                "is valid, which would mean another appointment soon. Ask your embassy or consulate about a new "
                "passport now.",
            ),
        )
    from ordnung.secretary.household import possessive

    owner = possessive(member.name)
    title = (
        f"Renew {owner} passport before extending their residence permit"
        if owner
        else for_member(member, "Renew the passport before extending the residence permit")
    )
    body = _sentences(
        f"{owner or 'The'} passport expires on {passport_day} — {relation} their residence permit ({permit_day}).",
        "The immigration office (Ausländerbehörde) usually extends a permit only as long as the passport is "
        "valid, which would mean another appointment soon. Ask the embassy or consulate about a new passport now.",
    )
    return title, body


def passport_before_permit(ledger: Ledger) -> list[Suggestion]:
    """A passport expiring before (or within 180 days after) the residence permit of the same person (the
    person's own, or one person's of the household): the permit can usually only be extended as long as the
    passport is valid, so renew the passport first."""
    today = ledger.today
    # each person's first residence permit to expire, by the person of the household its letter is filed for
    permits: dict[str | None, tuple[Item, date]] = {}
    for item, day in _expiries(ledger, "permit"):
        if (day - today).days <= PASSPORT_CHECK_HORIZON_DAYS:
            owner = ledger.member_of(item.doc_id)
            permits.setdefault(owner.id if owner else None, (item, day))
    if not permits:
        return []
    ideas: list[Suggestion] = []
    for passport, passport_day in _expiries(ledger, "identity"):
        member = ledger.member_of(passport.doc_id)
        pair = permits.get(member.id if member else None)
        if pair is None:
            continue
        permit, permit_day = pair
        if passport_day > permit_day + timedelta(days=PASSPORT_MARGIN_DAYS):
            continue
        relation = "before" if passport_day < permit_day else "soon after"
        # paired by whose they are; named only when neither letter is private (its title reaches Claude)
        named = (
            member if ledger.named_member(passport.doc_id) and ledger.named_member(permit.doc_id) else None
        )
        title, body = _passport_first_text(
            named, relation, day_label(passport_day, today), day_label(permit_day, today)
        )
        doc = ledger.document(passport.doc_id)
        action = (
            _open("document", doc.id, "Check the passport")
            if doc
            else _open("item", passport.id, "Open the to-do")
        )
        ideas.append(
            make_idea(
                "passport_before_permit",
                passport.id,
                (passport.due_date, permit.due_date),
                IdeaText(
                    title,
                    body,
                    f"Passport expires within {PASSPORT_MARGIN_DAYS} days of the residence permit.",
                ),
                kind="risk",
                priority="high",
                refs=[*_item_refs(ledger, passport), *_item_refs(ledger, permit)],
                action=action,
                due_date=permit_day,
            )
        )
    return ideas


def _matching_draft(ledger: Ledger, item: Item) -> Draft | None:
    for draft in ledger.sent_drafts():
        links = (
            (draft.contract_id, item.contract_id),
            (draft.case_id, item.case_id),
            (draft.doc_id, item.doc_id),
            (draft.party_id, item.party_id),
        )
        if any(mine is not None and mine == theirs for mine, theirs in links):
            return draft
    return None


def _followup_draft(ledger: Ledger, item: Item) -> Draft | None:
    """The sent letter whose follow-up to-do ``item`` is (its id is derived from the letter's)."""
    return next((draft for draft in ledger.sent_drafts() if followup_item_id(draft.id) == item.id), None)


def _proof_sentences(ledger: Ledger, draft: Draft) -> list[str]:
    """What the letter's proof adds to a reminder: the delivery day and the tracking number."""
    today = ledger.today
    said: list[str] = []
    delivered = sorted(
        day
        for proof in ledger.proofs_of(draft.id)
        if proof.kind in ("delivery_record", "return_receipt") and (day := parse_day(proof.on_date))
    )
    if delivered:
        said.append(
            f"Your proof shows it was delivered on {day_label(delivered[0], today)} — say so when you remind them."
        )
    tracking = tracking_info(draft.tracking_number)
    if tracking is not None:
        said.append(f"Quote the tracking number {tracking.display} if you call.")
    return said


def _answered_idea(ledger: Ledger, item: Item, draft: Draft, reply: Document, due: date) -> Suggestion:
    today = ledger.today
    who = ledger.party_name(reply.party_id) or ledger.party_name(item.party_id) or "They"
    reply_day = parse_day(reply.doc_date or reply.received_date or reply.created_at)
    when = f" of {day_label(reply_day, today)}" if reply_day else ""
    sent_day = parse_day(draft.sent_at)
    sent = f", sent {day_label(sent_day, today)}" if sent_day else ""
    body = _sentences(
        f"Their letter “{reply.title or reply.filename}”{when} came after yours (“{draft.subject}”{sent}).",
        "Check that it answers your letter, then mark the follow-up done.",
    )
    answer = ledger.answer_of(draft)
    confirmed = answer is not None and answer.document is not None and answer.document.id == reply.id
    # a letter that is only in the same thread may be about something else: ask, don't state
    title = (
        f"{who} confirmed — close the follow-up?"
        if confirmed
        else f"A letter from {who} came — is it the answer?"
    )
    if who == "They" and not confirmed:
        title = "A letter came in the same thread — is it the answer?"
    return make_idea(
        "followup_due",
        item.id,
        (item.due_date, "answered", reply.id),
        IdeaText(title, body, f"Follow-up date {day_label(due, today)}."),
        kind="followup",
        priority="normal",
        refs=[_ref("item", item.id), _ref("draft", draft.id), _ref("document", reply.id)],
        action=_open("draft", draft.id, "Open the letter"),
        due_date=due,
    )


def followup_due(ledger: Ledger) -> list[Suggestion]:
    """A sent letter's follow-up item (created when a draft is marked as sent) has become due.

    With the letter's proof state: when a letter linked to it arrived (:meth:`Ledger.reply_to`) the Idea
    asks the person to check that answer and close the follow-up (it closes nothing itself); otherwise a
    recorded delivery day and tracking number are named for the reminder. A letter without proof keeps
    the plain reminder.
    """
    ideas: list[Suggestion] = []
    today = ledger.today
    for item in ledger.active_items():
        due = parse_day(item.due_date)
        if item.origin != "draft" or due is None or due > today:
            continue
        exact = _followup_draft(ledger, item)
        reply = ledger.reply_to(exact) if exact is not None else None
        if exact is not None and reply is not None:
            ideas.append(_answered_idea(ledger, item, exact, reply, due))
            continue
        draft = exact or _matching_draft(ledger, item)
        refs = [_ref("item", item.id)]
        sent = None
        if draft is not None:
            refs.append(_ref("draft", draft.id))
            sent_day = parse_day(draft.sent_at)
            if sent_day:
                sent = f"You sent “{draft.subject}” on {day_label(sent_day, today)}."
        if item.contract_id:
            refs.append(_ref("contract", item.contract_id))
            action = _draft("general_reply", "contract", item.contract_id, "Write a follow-up")
        elif ledger.document(item.doc_id):
            refs.append(_ref("document", item.doc_id or ""))
            action = _draft("general_reply", "document", item.doc_id or "", "Write a follow-up")
        else:
            action = _open("item", item.id, "Open the to-do")
        body = _sentences(
            sent,
            "If you haven't had an answer, send a short reminder or call them — and keep a note of it.",
            *(_proof_sentences(ledger, exact) if exact is not None else ()),
        )
        ideas.append(
            make_idea(
                "followup_due",
                item.id,
                (item.due_date,),
                IdeaText(f"Follow-up due: {item.title}", body, f"Follow-up date {day_label(due, today)}."),
                kind="followup",
                priority="high" if (today - due).days > FOLLOWUP_LATE_DAYS else "normal",
                refs=refs,
                action=action,
                due_date=due,
            )
        )
    return ideas


#: Days after sending before a registered cancellation or objection without proof becomes an Idea.
PROOF_GRACE_DAYS = 2
#: Letters whose proof of arrival decides a deadline (``proof_missing`` watches these).
PROOF_WATCHED_KINDS = frozenset({"cancellation", "objection"})


def proof_missing(ledger: Ledger) -> list[Suggestion]:
    """A cancellation or objection sent by Einschreiben has no tracking number and no proof two days on.

    Not raised when an answer from them shows it arrived (:meth:`Ledger.answer_of` — a later letter that
    is merely in the same thread is not one, and the person's word that it was answered shows nothing
    about arrival: ``drafts.proof`` policy 3), when the person closed its follow-up themselves, or once
    Deutsche Post no longer issues the delivery record (15 months after posting). Once a tracking
    number or a proof is added the Idea expires.
    """
    ideas: list[Suggestion] = []
    today = ledger.today
    for draft in ledger.sent_drafts():
        sent = parse_day(draft.sent_at)
        if (
            draft.kind not in PROOF_WATCHED_KINDS
            or draft.sent_channel != "registered_letter"
            or sent is None
            or (today - sent).days < PROOF_GRACE_DAYS
            or draft.tracking_number
            or ledger.proofs_of(draft.id)
            or not delivery_record_obtainable(draft, today)
        ):
            continue
        answer = ledger.answer_of(draft)
        if answer is not None and answer.how != "noted":
            continue
        followup = ledger.followup_item(draft)
        # "I got an answer" closes the follow-up too, but says nothing about arrival
        if answer is None and followup is not None and followup.status in ("done", "dismissed"):
            continue
        who = ledger.party_name(draft.party_id) or "the recipient"
        what = "cancellation" if draft.kind == "cancellation" else "objection"
        body = _sentences(
            f"You sent “{draft.subject}” on {day_label(sent, today)} by Einschreiben, but Ordnung has no "
            "tracking number or receipt for it.",
            "Add the tracking number and a photo of the posting receipt (Einlieferungsbeleg) — or, for an "
            "Einschreiben bought online, the number next to the stamp's square code — and ask Deutsche "
            "Post for the delivery record (Auslieferungsbeleg); they issue it only within 15 months of "
            "posting. Together with the posting receipt, that is what courts have accepted as a sign "
            "that a letter arrived — never as proof of what was inside.",
        )
        refs = [_ref("draft", draft.id)]
        if draft.contract_id:
            refs.append(_ref("contract", draft.contract_id))
        if draft.doc_id and ledger.document(draft.doc_id):
            refs.append(_ref("document", draft.doc_id))
        ideas.append(
            make_idea(
                "proof_missing",
                draft.id,
                (draft.sent_at,),
                IdeaText(
                    f"Keep the proof of your {what} to {who}",
                    body,
                    "The posting receipt with the online tracking status alone was not accepted as proof "
                    "that a letter arrived (BAG 2 AZR 68/24).",
                ),
                kind="followup",
                priority="normal",
                refs=refs,
                action=_open("draft", draft.id, "Add proof"),
                due_date=None,
            )
        )
    return ideas


def _unsure_items(items: Iterable[Item]) -> list[Item]:
    # a to-do the person confirmed or dated is theirs: nothing left to check (``plan.needs_check``)
    return [
        item
        for item in items
        if item.grounding != "user"
        and (item.grounding == "unverified" or any(not ev.value_consistent for ev in item.evidence))
    ]


def please_check(ledger: Ledger) -> list[Suggestion]:
    """Documents that need the person's review ("Please check")."""
    ideas: list[Suggestion] = []
    today = ledger.today
    active = ledger.active_items()
    for doc in ledger.documents.values():
        if doc.status != "needs_review":
            continue
        doc_items = [item for item in active if item.doc_id == doc.id]
        unsure = _unsure_items(doc_items)
        days = [day for day in (action_day(item) for item in doc_items) if day is not None]
        first = min(days) if days else None
        if any(item.slot_key == CHECK_SLOT for item in unsure):
            # the to-do Ordnung added itself: nothing was "not found" — the reading came back incomplete
            body = (
                "Claude's reading of this letter came back incomplete, so Ordnung added a to-do from the "
                "letter's own words. Open the letter and check it."
            )
        elif any(is_check_slot(item.slot_key) for item in unsure):
            # a fixed date the letter sets (pay by, send by) that the reading left out: found, not "not found"
            body = (
                "Claude's reading of this letter left out a date the letter sets for you, so Ordnung added a to-do "
                "from the letter's own words. Open the letter and check it."
            )
        elif unsure:
            listed = ", ".join(item.title for item in unsure[:3])
            body = f"We couldn't find some dates or amounts in the letter ({listed}). Open it and confirm or correct them."
        else:
            body = "Some details of this letter need your confirmation before Ordnung relies on them."
        ideas.append(
            make_idea(
                "please_check",
                doc.id,
                tuple(sorted(item.id for item in unsure)),
                IdeaText(f"Please check: {doc.title or doc.filename}", body),
                kind="info",
                priority="high" if first is not None and (first - today).days <= 14 else "normal",
                refs=[_ref("document", doc.id), *(_ref("item", item.id) for item in unsure)],
                action=_open("document", doc.id, "Check the letter"),
                due_date=first,
            )
        )
    return ideas


def _invoices_by_sender(ledger: Ledger) -> dict[str, list[Document]]:
    """Dated invoices by sender (party id)."""
    invoices: dict[str, list[Document]] = {}
    for doc in ledger.documents.values():
        if doc.kind == "invoice" and doc.party_id and doc.doc_date:
            invoices.setdefault(doc.party_id, []).append(doc)
    return invoices


def _earlier_invoice(dunning: Document, invoices: dict[str, list[Document]]) -> Document | None:
    """The sender's latest invoice dated on or before the reminder (:func:`_invoices_by_sender`)."""
    candidates = [
        doc
        for doc in invoices.get(dunning.party_id or "", [])
        if dunning.doc_date is None or (doc.doc_date or "") <= dunning.doc_date
    ]
    return max(candidates, key=lambda doc: (doc.doc_date or "", doc.id), default=None)


#: Senders that are public bodies: a library's, a university's or an authority's fee is never taken to
#: a debt collector or a court payment order — they add reminder fees and, in the end, collect it
#: themselves (administrative enforcement). Before this, a €4.50 library fee warned of a
#: Mahnbescheid.
PUBLIC_CREDITOR_KINDS = frozenset(
    {"authority", "tax_office", "immigration_office", "university", "public_broadcaster"}
)
_PRIVATE_UNPAID = (
    "If it stays unpaid, the next step is usually a debt collector or a court payment order "
    "(Mahnbescheid), which adds costs."
)
_PUBLIC_UNPAID = (
    "If it stays unpaid, more reminder fees can follow, and a public body can in the end collect it "
    "itself (administrative enforcement)."
)


def dunning_escalation(ledger: Ledger) -> list[Suggestion]:
    """Payment reminders (Mahnungen) with an open payment: pay, or object if you don't owe it. What
    follows if it stays unpaid depends on the sender: a company's claim goes to a debt collector or a
    court payment order, a public body's is collected by the body itself (:data:`PUBLIC_CREDITOR_KINDS`)."""
    ideas: list[Suggestion] = []
    today = ledger.today
    invoices = _invoices_by_sender(ledger)
    for doc in ledger.documents.values():
        if doc.kind != "dunning":
            continue
        payments = [
            i
            for i in ledger.items_of(doc.id)
            if is_active(i, today)
            and i.kind == "payment"
            and i.due_date
            # a date code took from the letter is to be checked: never a "Pay" nudge
            and not is_check_slot(i.slot_key)
            and not ledger.is_superseded_by_reminder(i)
            and not ledger.is_covered_by_attachment(i)
        ]
        if not payments or ledger.shows_scam_signs(doc):
            continue  # letters with scam signs get a scam warning instead of "pay"
        payment = min(payments, key=lambda i: (action_day(i) or today, i.id))
        act = action_day(payment) or today
        who = ledger.party_name(doc.party_id) or "the sender"
        amount = f" {eur(payment.amount)}" if payment.amount is not None else ""
        days = (act - today).days
        title = (
            f"Overdue reminder from {who}: pay{amount} now"
            if days < 0
            else f"Pay {who} reminder{amount} by {day_label(act, today)}"
        )
        invoice = _earlier_invoice(doc, invoices)
        invoice_day = parse_day(invoice.doc_date) if invoice else None
        party = ledger.parties.get(doc.party_id) if doc.party_id else None
        body = _sentences(
            "This is a payment reminder (Mahnung)"
            + (f" for the invoice of {day_label(invoice_day, today)}." if invoice_day else "."),
            _PUBLIC_UNPAID if party is not None and party.kind in PUBLIC_CREDITOR_KINDS else _PRIVATE_UNPAID,
            f"If you already paid, tell {who} when and keep the proof; if you don't owe it, say so in writing.",
        )
        refs = [_ref("document", doc.id), _ref("item", payment.id)]
        if invoice is not None:
            refs.append(_ref("document", invoice.id))
        ideas.append(
            make_idea(
                "dunning_escalation",
                doc.id,
                (payment.id, payment.due_date, payment.amount),
                IdeaText(title, body, f"Payment reminder, due {in_days(days)}."),
                kind="risk",
                priority="critical" if days <= 7 else "high",
                refs=refs,
                action=_open("document", doc.id, "Pay"),
                due_date=max(act, today),
            )
        )
    return ideas


def _days_asked(ledger: Ledger, doc: Document) -> str | None:
    """The scam warning's sentence naming the days its letter asks for, so a flagged letter's dates are never
    lost while its to-dos are set aside: each open to-do's due date from today on, earliest first, with the day
    to send or transfer by when that comes first ("It asks you to act by Fri 6 Nov and Mon 9 Nov (send by
    Thu 5 Nov)."); ``None`` when it asks for none."""
    today = ledger.today
    dated = sorted(
        (due, item.id, item)
        for item in ledger.items_of(doc.id)
        if is_active(item, today) and (due := parse_day(item.due_date)) is not None and due >= today
    )
    days: list[str] = []
    for due, _, item in dated:
        act = action_day(item)
        day = day_label(due, today)
        if act is not None and act < due and not paid_at_appointment(item, ledger.items):
            day += f" ({'transfer' if item.kind == 'payment' else 'send'} by {day_label(act, today)})"
        if day not in days:
            days.append(day)
    if not days:
        return None
    listed = days[0] if len(days) == 1 else f"{', '.join(days[:-1])} and {days[-1]}"
    return f"It asks you to act by {listed}."


def scam_warning(ledger: Ledger) -> list[Suggestion]:
    """Scam indicators found by code (hidden text, invalid IBAN, payee mismatch) or flagged in the
    document's warnings. The warning names the days the letter asks for (:func:`_days_asked`); its title and day
    don't change with them (the morning note reads both). Its fingerprint is :func:`scam_fingerprint`."""
    ideas: list[Suggestion] = []
    today = ledger.today
    for doc in ledger.documents.values():
        reasons = ledger.scam_signs(doc)
        if not reasons:
            continue
        pay_days = [
            action_day(i) for i in ledger.items_of(doc.id) if is_active(i, today) and i.kind == "payment"
        ]
        due = min((day for day in pay_days if day is not None), default=None)
        body = _sentences(
            *reasons,
            _days_asked(ledger, doc),
            "Don't pay or reply until you've checked with the sender using contact details you already know "
            "— not the ones in this letter.",
        )
        refs = [_ref("document", doc.id)]
        if doc.party_id in ledger.parties:
            refs.append(_ref("party", doc.party_id or ""))
        ideas.append(
            make_idea(
                SCAM_RULE,
                doc.id,
                tuple(sorted(reasons)),
                IdeaText(
                    f"Possible scam: {_letter_title(doc.title or doc.filename)}",
                    body,
                    "1 warning sign." if len(reasons) == 1 else f"{len(reasons)} warning signs.",
                ),
                kind="scam",
                priority="critical",
                refs=refs,
                action=_open("document", doc.id, "See why"),
                due_date=max(due, today) if due else None,
            )
        )
    return ideas


def iban_misprint(ledger: Ledger) -> list[Suggestion]:
    """A letter asks you to transfer money to an IBAN that fails its checksum, with no other scam signs:
    most likely a misprint (or a misread photo). An Info Idea to check it before paying — no alarm."""
    ideas: list[Suggestion] = []
    today = ledger.today
    active = ledger.actionable_items()
    for doc in ledger.documents.values():
        payment = doc.payment
        if doc.direction != "incoming" or payment is None or not payment.iban or not iban_fails_checksum(doc):
            continue
        if ledger.shows_scam_signs(doc):
            continue  # scam_warning lists the checksum next to the other signs
        days = [
            day
            for item in active
            if item.doc_id == doc.id
            and item.kind == "payment"
            and item.direction != "in"
            and not is_direct_debit(item)
            for day in (action_day(item),)
            if day is not None
        ]
        if not days:
            continue  # nothing to transfer: the IBAN doesn't matter
        who = ledger.party_name(doc.party_id) or "the sender"
        iban = _scam.format_iban(_scam.normalize_iban(payment.iban)) if _scam is not None else payment.iban
        refs = [_ref("document", doc.id)]
        if doc.party_id in ledger.parties:
            refs.append(_ref("party", doc.party_id or ""))
        ideas.append(
            make_idea(
                "iban_misprint",
                doc.id,
                (payment.iban,),
                IdeaText(
                    f"The IBAN from {who} looks misprinted — check it before you pay",
                    _sentences(
                        f"{iban} doesn't pass the bank check, so a transfer to it would fail.",
                        "Most likely a digit is misprinted or was misread. Compare it with the paper letter; if "
                        f"it's printed like that, ask {who} for the right account number.",
                    ),
                    "The IBAN's check digits don't match (ISO 13616).",
                ),
                kind="info",
                priority="normal",
                refs=refs,
                action=_open("document", doc.id, "Check the letter"),
                due_date=max(min(days), today),
            )
        )
    return ideas


def tax_documents(ledger: Ledger) -> list[Suggestion]:
    """January–July: collect last year's letters for taxes for the tax return — the person's own choice,
    else Claude's mark (:func:`~ordnung.secretary.tax_choice.for_taxes`), and not the letters waiting from
    the folder. They are counted by :func:`letter_day`, as the Tax year page files them, and "See the
    documents" opens that page (``target_type="tax_year"``, ``target_id`` the year)."""
    today = ledger.today
    if today.month > TAX_SEASON_LAST_MONTH:
        return []
    year = today.year - 1
    docs = sorted(
        (
            doc
            for doc in ledger.documents.values()
            if for_taxes(doc, ledger.tax_choices)
            and not is_held(doc)
            and (letter_day(doc) or date.min).year == year
        ),
        key=lambda doc: (doc.doc_date or "", doc.id),
    )
    if not docs:
        return []
    body = _sentences(
        f"{len(docs)} letter(s) from {year} could matter for your tax return — payslips, insurance, "
        "receipts for work or study costs.",
        "If you have to file a return it is usually due by the end of July; filing voluntarily is possible "
        "for four years and often brings money back.",
    )
    return [
        make_idea(
            "tax_documents",
            str(year),
            tuple(doc.id for doc in docs),
            IdeaText(
                f"Your {year} tax documents are ready to collect",
                body,
                f"{len(docs)} tax-relevant letter(s).",
            ),
            kind="tax",
            priority="normal",
            refs=[_ref("document", doc.id) for doc in docs[:10]],
            action=_open("tax_year", str(year), "See the documents"),
            due_date=date(today.year, 7, 31),
        )
    ]


def _changed_after(stamp: str, since: datetime | None) -> bool:
    if since is None:
        return True
    moment = parse_timestamp(stamp)
    return moment is None or moment > since


def calendar_outdated(ledger: Ledger) -> list[Suggestion]:
    """Open future dates (items and contract send-by days) added or changed since the last .ics export.

    Only dates the calendar file holds count (``ordnung.calendar.ics``): none set aside
    (:meth:`Ledger.is_set_aside`), no one-off whose date had long passed when its letter was read
    (:func:`was_history_when_filed`), none past the calendar's last day
    (:func:`~ordnung.calendar.ics.fits_a_calendar`) and no decided contract's
    (:meth:`Ledger.decided_contracts`), so "Add your 4 dates" never stands over a file with 2.

    Not while a calendar is connected for calendar sync (paused or not): it gets the dates by itself,
    and importing the file into it as well would clash with the synced events (the same UIDs)."""
    from ordnung.calendar.ics import fits_a_calendar

    if ledger.store.get_meta(CALENDAR_SYNC_META_KEY):
        return []
    today = ledger.today
    raw = ledger.store.get_meta(CALENDAR_META_KEY)
    since = parse_timestamp(raw)
    dates: list[tuple[date, SuggestionRef]] = []
    for item in ledger.active_items():
        due = parse_day(item.due_date)
        if (
            due is not None
            and due >= today
            and _changed_after(item.updated_at, since)
            and not ledger.is_set_aside(item)
            and not (item.recurrence is None and was_history_when_filed(item))
            and fits_a_calendar(item)
        ):
            dates.append((action_day(item) or due, _ref("item", item.id)))
    decided = ledger.decided_contracts()
    for contract in ledger.active_contracts():
        if contract.id in decided:
            continue
        comp = ledger.computation(contract)
        send = parse_day(comp.send_by)
        if is_decision(comp) and send is not None and _changed_after(contract.updated_at, since):
            dates.append((send, _ref("contract", contract.id)))
    if not dates:
        return []
    dates.sort(key=lambda pair: (pair[0], pair[1].id))
    count = len(dates)
    title = (
        f"{count} new date{'s' if count != 1 else ''} since your last calendar update"
        if since
        else f"Add your {count} date{'s' if count != 1 else ''} to your calendar"
    )
    body = "Download the calendar file and import it, so your phone reminds you even when Ordnung is closed."
    return [
        make_idea(
            "calendar_outdated",
            "calendar",
            (raw or "never", *(f"{ref.type}:{ref.id}" for _, ref in dates)),
            IdeaText(title, body),
            kind="hygiene",
            priority="normal",
            refs=[ref for _, ref in dates[:10]],
            action=SuggestionAction(type="none", target_type="calendar", label="Add to calendar"),
            due_date=dates[0][0],
        )
    ]


def _sent_cancellation(ledger: Ledger, contract_id: str) -> Draft | None:
    """The person's latest cancellation of this contract that was marked as sent."""
    return next(
        (
            draft
            for draft in ledger.sent_drafts()
            if draft.kind == "cancellation" and draft.contract_id == contract_id
        ),
        None,
    )


def _cancellation_sent_line(ledger: Ledger, draft: Draft) -> str:
    sent = parse_day(draft.sent_at)
    when = f" on {day_label(sent, ledger.today)}" if sent else ""
    tracking = tracking_info(draft.tracking_number)
    how = f" (tracking number {tracking.display})" if tracking else ""
    return (
        f"It answers your cancellation sent{when} by {channel_label(draft.sent_channel)}{how}: keep the two "
        "together as your proof."
    )


def confirm_cancellation(ledger: Ledger) -> list[Suggestion]:
    """A cancellation confirmation arrived for a contract that is still marked active.

    When the person's own cancellation of that contract was marked as sent, the Idea names it (how and
    when it went, its tracking number) and links it, so the confirmation is kept with the proof.
    """
    ideas: list[Suggestion] = []
    today = ledger.today
    by_id = {contract.id: contract for contract in ledger.contracts}
    for contract_id, (doc, effective) in sorted(ledger.pending_confirmations().items()):
        contract = by_id[contract_id]
        when = f" effective {day_label(effective, today)}" if effective else ""
        who = ledger.party_name(doc.party_id) or ledger.party_name(contract.party_id) or "The provider"
        mine = _sent_cancellation(ledger, contract.id)
        body = _sentences(
            f"{who} confirmed that your contract ends{' on ' + day_label(effective, today) if effective else ''}.",
            _cancellation_sent_line(ledger, mine) if mine is not None else None,
            "Check that this matches what you asked for, then confirm it so Ordnung stops tracking its "
            "deadlines and costs.",
        )
        refs = [_ref("document", doc.id), _ref("contract", contract.id)]
        if mine is not None:
            refs.append(_ref("draft", mine.id))
        ideas.append(
            make_idea(
                "confirm_cancellation",
                doc.id,
                (contract.id, effective.isoformat() if effective else None),
                IdeaText(f"Confirm cancellation of {contract.name}{when}?", body),
                kind="followup",
                priority="normal",
                refs=refs,
                action=SuggestionAction(
                    type="mark_done",
                    target_type="contract",
                    target_id=contract.id,
                    label="Confirm cancellation",
                ),
                due_date=effective,
            )
        )
    return ideas


def student_permit_info(ledger: Ledger) -> list[Suggestion]:
    """Static info card on working with a student residence permit (replaces a work-days trigger, §21). It
    refers to the person's own newest residence permit, never to one filed for someone of their household."""
    if not ledger.profile.is_student_visa:
        return []
    permits = sorted(
        (
            doc
            for doc in ledger.documents.values()
            if doc.kind == "residence_permit" and ledger.member_of(doc.id) is None
        ),
        key=lambda doc: (doc.doc_date or "", doc.id),
    )
    refs = [_ref("document", permits[-1].id)] if permits else []
    action = (
        _open("document", permits[-1].id, "Check the permit")
        if permits
        else SuggestionAction(type="none", label="Read the rules")
    )
    body = _sentences(
        "A student residence permit lets you work up to 140 full or 280 half days a year, plus student "
        f"jobs at your university ({STUDENT_WORK_LAW}).",
        "Check the conditions printed on your permit (Nebenbestimmungen) and ask the international "
        "office or the Studierendenwerk before taking on more.",
        "Law: " + _PERMIT_LINKS[0] + " · Advice: " + _PERMIT_LINKS[1],
    )
    return [
        make_idea(
            STUDENT_PERMIT_RULE,
            "profile",
            ("v1",),
            IdeaText(
                "Working on a student permit: know your limits",
                body,
                "You told us you study on a residence permit.",
            ),
            kind="info",
            priority="low",
            refs=refs,
            action=action,
            due_date=None,
        )
    ]


def sender_land(ledger: Ledger) -> list[Suggestion]:
    """Senders whose letters suggest a Land while a date of theirs may change with it
    (:func:`ordnung.secretary.sender_land.sender_land_ideas`, imported here because it builds on this module)."""
    from ordnung.secretary.sender_land import sender_land_ideas

    return sender_land_ideas(ledger)


def moved_house(ledger: Ledger) -> list[Suggestion]:
    """After the person said they moved: who needs the new address, starting with registering it
    (:func:`ordnung.secretary.moving.moving_ideas`, imported here because it builds on this module)."""
    from ordnung.secretary.moving import moving_ideas

    return moving_ideas(ledger)


Trigger = Callable[[Ledger], list[Suggestion]]

#: Rules whose Ideas never name a person of the household (ADR 0023): the person's own tax return, calendar,
#: profile (the student permit card) and move, a sender's Land, and the decision on a contract, which is the
#: person's (its letters can be several people's).
NEVER_NAMED = frozenset(
    {
        "tax_documents",
        "calendar_outdated",
        STUDENT_PERMIT_RULE,
        "moved_house",
        "sender_land",
        "contract_cancel_window",
    }
)
#: Rules that say whose a passport or a residence permit is in their own words ("Alex Rivera's passport …").
NAMED_BY_THE_RULE = frozenset({"expiry_soon", "passport_before_permit"})

#: Every rule in evaluation order (the keys are the ``rule_id``s stored on the Ideas).
TRIGGERS: dict[str, Trigger] = {
    "deadline_soon": deadline_soon,
    "overdue": overdue,
    "contract_cancel_window": contract_cancel_window,
    "price_increase_right": price_increase_right,
    "expiry_soon": expiry_soon,
    "passport_before_permit": passport_before_permit,
    "followup_due": followup_due,
    "proof_missing": proof_missing,
    "please_check": please_check,
    "sender_land": sender_land,
    "moved_house": moved_house,
    "dunning_escalation": dunning_escalation,
    "scam_warning": scam_warning,
    "iban_misprint": iban_misprint,
    "tax_documents": tax_documents,
    "calendar_outdated": calendar_outdated,
    "confirm_cancellation": confirm_cancellation,
    STUDENT_PERMIT_RULE: student_permit_info,
}


# --------------------------------------------------------------------------------------------------
# running & persisting
# --------------------------------------------------------------------------------------------------


def named(ledger: Ledger, idea: Suggestion) -> Suggestion:
    """``idea`` with "For Alex Rivera: " in front of its title when every letter it refers to is filed for that
    person of the household (:meth:`Ledger.idea_member`). The person isn't in the fingerprint, so filing a letter
    renames the same Idea and keeps the person's choice; without a household nothing changes."""
    rule_id = idea.rule_id or ""
    if rule_id in NEVER_NAMED or rule_id in NAMED_BY_THE_RULE:
        return idea
    member = ledger.idea_member(idea.refs)
    return idea if member is None else idea.model_copy(update={"title": for_member(member, idea.title)})


def run_triggers(store: Store, today: date) -> dict[str, list[Suggestion]]:
    """Evaluate every trigger against the store as of ``today`` (reads only).

    Returns ``{rule_id: [Suggestion, …]}`` for every rule (empty lists included); within a rule each
    fingerprint appears once. An Idea about letters filed for someone of the household names them
    (:func:`named`).
    """
    ledger = Ledger(store, today)
    results: dict[str, list[Suggestion]] = {}
    for rule_id, trigger in TRIGGERS.items():
        unique = {idea.fingerprint: named(ledger, idea) for idea in trigger(ledger)}
        results[rule_id] = list(unique.values())
    return results


@dataclass(frozen=True)
class TriggerRun:
    """Outcome of :func:`run_and_reconcile`."""

    live: int
    new: int
    expired: int
    by_rule: dict[str, int]

    def as_dict(self) -> dict[str, Any]:
        """JSON-friendly counts (for bus events and API responses)."""
        return {"live": self.live, "new": self.new, "expired": self.expired, "by_rule": dict(self.by_rule)}


def run_and_reconcile(store: Store, today: date) -> TriggerRun:
    """Run all triggers, upsert their Ideas and expire rule Ideas that no longer fire.

    ``new`` counts Ideas that were absent or expired before (the person sees them as new). The
    person's status on existing Ideas (dismissed, snoozed, accepted) is kept by the store. Publishes
    nothing — the caller announces ``suggestions.updated``.
    """
    results = run_triggers(store, today)
    live: list[str] = []
    new = 0
    with store.tx():
        for ideas in results.values():
            for idea in ideas:
                before = store.get_suggestion(idea.id)
                store.upsert_suggestion(idea)
                if before is None or before.status == "expired":
                    new += 1
                live.append(idea.fingerprint)
        expired = store.reconcile_suggestions(results.keys(), live)
    return TriggerRun(
        live=len(live),
        new=new,
        expired=expired,
        by_rule={rule_id: len(ideas) for rule_id, ideas in results.items()},
    )
