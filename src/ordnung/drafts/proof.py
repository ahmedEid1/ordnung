"""Proof of a sent letter (SPEC § 11): what each kind of proof shows, what is missing, and the letter's
timeline for the "Nachweis". Pure: no store, no files (the service is :mod:`ordnung.drafts.sent`).

Policy:

1. **Ordnung never says a proof is enough.** Each kind states what it shows and what it does not
   (:data:`PROOF_KINDS`), and every overview carries :data:`CAVEAT`: proof of sending never shows what
   was in the envelope, and whether a proof suffices is for a court to decide.
2. **What is missing depends on how the letter was sent** — the channel the person chose when marking
   it as sent (:func:`missing`). A registered letter wants its tracking number, the posting receipt
   (Einlieferungsbeleg) and the delivery record (Auslieferungsbeleg) or return receipt (Rückschein): the
   posting receipt with the online tracking status alone was not accepted as prima facie proof that a
   letter arrived (BAG, 30 January 2025, 2 AZR 68/24), while courts have accepted it together with a copy
   of the delivery record (BGH V ZR 203/22, cited there). A fax wants its transmission report, an
   e-mail the sent message, the cancel button (§ 312k BGB) its saved page and the provider's
   confirmation. A plain letter leaves nothing that shows it arrived, which is said once.
   The delivery record can be asked for only within :data:`DELIVERY_RECORD_MONTHS` months of posting
   (Deutsche Post's Einschreiben FAQ); after that it is no longer suggested.
3. **Only a confirmed answer is proof of arrival** (:class:`RecordedAnswer`): a confirmation of the
   cancelled contract, or a letter — or just the word — of the person that the letter was answered.
   Then nothing about arrival is asked for any more. A later letter that is merely in the same thread
   (:meth:`ordnung.secretary.triggers.Ledger.reply_to`) is only a *possible* answer: it is shown to
   the person as one, never counted as arrival and never written into the Nachweis.
4. **The timeline lists only what the person recorded**: drafted, sent (channel), tracking number,
   each proof on the day it shows, the confirmed answer. A proof without a day is never put on a
   day: it is listed apart, with the day it was added (:attr:`TimelineEvent.added_on`). Nothing is
   inferred from a tracking website.
5. **Days that contradict each other are said** (:func:`conflicts`): a posting receipt, fax report,
   sent e-mail or cancel-button page shows the sending day, so another day than the one the letter is
   marked as sent on is pointed out (one of them is wrong); a delivery can't be before the sending
   (:mod:`ordnung.drafts.sent` refuses it).

Limits: the channel is what the person said; a proof's kind and day are what they chose, not read from
the file (proof files are never sent to a model).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

from ordnung.ids import content_id
from ordnung.models import PROOF_SOURCE as MODEL_PROOF_SOURCE
from ordnung.models import Document, Draft, ProofEvent, ProofKind, RefLink, TrackingInfo
from ordnung.rules.explain import fmt_date
from ordnung.rules.periods import add_months

#: Sent letters get a follow-up to-do with this id (one per letter; marking it sent again updates it).
FOLLOWUP_SLOT = "followup"
#: ``Document.source`` of a proof file (:data:`ordnung.models.PROOF_SOURCE`): a private outgoing
#: document that belongs to its letter. It is listed with the letter, not in the Inbox, search, Today,
#: the timeline or the life areas, and never counted as a letter.
PROOF_SOURCE = MODEL_PROOF_SOURCE

CAVEAT = (
    "Proof of sending shows that something was sent or delivered — never what was inside. Keep a copy "
    "of the letter as sent and, for a letter that matters, have someone see you put it in the envelope. "
    "Whether a proof is enough is for a court to decide; this is not legal advice."
)
#: The same caveat in German, for the Nachweis PDF.
CAVEAT_DE = (
    "Ein Versandnachweis zeigt, dass etwas versandt oder zugestellt wurde – nie, was die Sendung enthielt. "
    "Ob ein Nachweis genügt, entscheidet im Streitfall das Gericht. Diese Übersicht ist keine Rechtsberatung."
)
#: How many proofs one letter can hold (bounds the Nachweis PDF; each file has intake's own limits).
MAX_PROOFS = 20
MAX_NOTE = 500
#: Deutsche Post issues a copy of an Einschreiben's delivery record for this many months after posting.
DELIVERY_RECORD_MONTHS = 15


@dataclass(frozen=True)
class ProofKindInfo:
    """What one kind of proof is called and what it does and doesn't show (English, German)."""

    label: str
    german: str
    shows: str
    does_not_show: str
    #: shows the letter arrived (a delivery record, a return receipt, the button's presumption)
    arrival: bool = False


PROOF_KINDS: dict[ProofKind, ProofKindInfo] = {
    "posting_receipt": ProofKindInfo(
        "Posting receipt",
        "Einlieferungsbeleg",
        "That a registered item with this number was handed in at the post office, and when.",
        "Whether it arrived, or what was in the envelope.",
    ),
    "delivery_record": ProofKindInfo(
        "Delivery record",
        "Auslieferungsbeleg",
        "The day the carrier delivered it, as the carrier recorded it — put in their letterbox "
        "(Einwurf-Einschreiben) or handed over against a signature (Übergabe-Einschreiben). With the "
        "posting receipt, courts have accepted it as prima facie proof that the letter arrived.",
        "What was in the envelope.",
        arrival=True,
    ),
    "return_receipt": ProofKindInfo(
        "Return receipt",
        "Rückschein",
        "The day the letter was handed over, signed by whoever took it.",
        "What was in the envelope.",
        arrival=True,
    ),
    "fax_report": ProofKindInfo(
        "Fax transmission report",
        "Sendebericht",
        "That your fax reached this number at this time, and how many pages went through.",
        "That every page arrived readable — an “OK” is an indication, not proof, that they received it.",
    ),
    "sent_email": ProofKindInfo(
        "Sent e-mail",
        "gesendete E-Mail",
        "What you sent and when it left your mailbox.",
        "That it reached them or was read — ask them to confirm it arrived.",
    ),
    "cancel_confirmation": ProofKindInfo(
        "Cancel-button confirmation",
        "Kündigungsbestätigung",
        "Your cancellation with its date and time. The law presumes a cancellation made with the button "
        "reached them right after you sent it (§ 312k Abs. 4 BGB).",
        "That they processed it, if it is only your saved page — their confirmation e-mail shows that.",
        arrival=True,
    ),
    "other": ProofKindInfo(
        "Other proof",
        "sonstiger Nachweis",
        "What it shows — describe it in the note.",
        "Ordnung can't tell; proof files are never read by AI.",
    ),
}

#: Proofs whose day is the day the letter went out (it should be the day it is marked as sent).
SENDING_DAY_KINDS: frozenset[str] = frozenset(
    {"posting_receipt", "fax_report", "sent_email", "cancel_confirmation"}
)
#: Proofs whose day is the delivery (it can't be before the sending).
DELIVERY_DAY_KINDS: frozenset[str] = frozenset({"delivery_record", "return_receipt"})

#: The proof kinds that fit each way of sending, the most useful first (the upload form's default).
CHANNEL_PROOFS: dict[str, tuple[ProofKind, ...]] = {
    "registered_letter": ("posting_receipt", "delivery_record", "return_receipt"),
    "fax": ("fax_report",),
    "email": ("sent_email",),
    "online_button": ("cancel_confirmation",),
    "portal": ("other",),
    "in_person": ("other",),
    "letter": ("other",),
}

CHANNEL_LABELS: dict[str, tuple[str, str]] = {
    "online_button": ("the online cancel button", "Kündigungsbutton"),
    "email": ("e-mail", "E-Mail"),
    "fax": ("fax", "Telefax"),
    "letter": ("letter by post", "Brief"),
    "registered_letter": ("registered letter (Einschreiben)", "Einschreiben"),
    "in_person": ("hand delivery", "persönliche Übergabe"),
    "portal": ("online portal", "Online-Portal"),
}

#: What a sent letter of each kind waits for (``None``: nothing — an address change only informs).
WAITING_FOR: dict[str, str | None] = {
    "cancellation": "A written confirmation of the end date",
    "objection": "A decision on your objection",
    "general_reply": "An answer to your letter",
    "withdrawal": "Your money back after the withdrawal",
    "extension_request": "An answer to your request for more time",
    "payment_plan": "An answer to your offer to pay in instalments",
    "defect_notice": "The repair of the defect",
    "data_access": "A copy of your data",
    "receipts_inspection": "A date to see the receipts",
    # the letter asks when the deposit will be settled: that answer is due, the money not yet
    "deposit_return": "An answer on when your deposit will be settled",
    "address_change": None,
}

#: What the waiting entry adds for a kind whose own wait is longer than the follow-up (the reason).
WAITING_CONTEXT: dict[str, str] = {
    "deposit_return": (
        "A landlord has a reasonable time to settle the deposit after you move out — how long depends "
        "on the case and can be more than six months (BGH, 18 January 2006, VIII ZR 71/05) — but can "
        "tell you when to expect it."
    ),
}

MISSING_TRACKING = "Add the tracking number from your posting receipt (Einlieferungsbeleg)."
MISSING_POSTING = "Add a photo of the posting receipt — it shows the day you posted the letter."
MISSING_DELIVERY = (
    "Ask Deutsche Post for a copy of the delivery record (Auslieferungsbeleg) — they issue it only within "
    "15 months of posting, so best right after delivery — or keep the return receipt (Rückschein) if you "
    "sent it with one. The online tracking status alone was not accepted as proof that a letter arrived "
    "(BAG 2 AZR 68/24)."
)
MISSING_DELIVERY_LATE = (
    "Keep the return receipt (Rückschein) if you sent it with one. Deutsche Post issues a copy of the "
    "delivery record (Auslieferungsbeleg) only within 15 months of posting — for this letter that time "
    "has passed."
)
MISSING_FAX = "Keep the fax transmission report (Sendebericht): it shows the number, the time and the pages."
MISSING_EMAIL = "Save the sent e-mail as a file or PDF, and ask them to confirm it arrived."
MISSING_BUTTON = (
    "Save the page the cancel button showed and the confirmation e-mail they must send you at once "
    "(§ 312k Abs. 3 and 4 BGB)."
)
MISSING_LETTER = (
    "A normal letter leaves nothing that shows it arrived. If a deadline depends on it, send it again "
    "by Einwurf-Einschreiben."
)
MISSING_IN_PERSON = "Ask them to sign and date your copy as received, or note who saw you hand it over."
MISSING_PORTAL = "Save the portal's confirmation, or a screenshot of the sent message with its date."


#: Ways of sending that leave nothing behind unless the person keeps something.
_NOTHING_KEPT = {"letter": MISSING_LETTER, "in_person": MISSING_IN_PERSON, "portal": MISSING_PORTAL}


def is_proof_file(document: Document) -> bool:
    """Whether a document is the file of a letter's proof (see :data:`PROOF_SOURCE`)."""
    return document.source == PROOF_SOURCE


def followup_item_id(draft_id: str) -> str:
    """The id of a sent letter's follow-up to-do ("Check for a reply")."""
    return content_id("itm", FOLLOWUP_SLOT, draft_id)


def kind_info(kind: str) -> ProofKindInfo:
    """What a proof kind shows (unknown kinds read as "other")."""
    return PROOF_KINDS.get(kind, PROOF_KINDS["other"])  # type: ignore[call-overload]


def channel_label(channel: str | None, *, german: bool = False) -> str:
    """How the letter was sent, in words (``registered letter (Einschreiben)``)."""
    if not channel:
        return "Versand" if german else "sent"
    english, deutsch = CHANNEL_LABELS.get(channel, (channel.replace("_", " "), channel.replace("_", " ")))
    return deutsch if german else english


def waits_for(kind: str) -> str | None:
    """What a sent letter of ``kind`` waits for (``None``: nothing)."""
    return WAITING_FOR.get(kind, WAITING_FOR["general_reply"])


def sent_day(draft: Draft) -> date | None:
    """The day a sent letter went out (``None`` for one not sent, or without a readable day)."""
    if draft.status != "sent" or not draft.sent_at:
        return None
    try:
        return date.fromisoformat(draft.sent_at[:10])
    except ValueError:
        return None


def delivery_record_obtainable(draft: Draft, today: date) -> bool:
    """Whether Deutsche Post still issues the delivery record of this letter (policy 2); ``True`` when
    the sending day is unknown (Ordnung can't tell that it is too late)."""
    sent = sent_day(draft)
    return sent is None or today <= add_months(sent, DELIVERY_RECORD_MONTHS)


def missing(draft: Draft, proofs: Sequence[RecordedProof], *, answered: bool, today: date) -> list[str]:
    """What would make the proof of a sent letter stronger, by the channel it went by (policy 2 and 3).
    ``answered``: a confirmed answer (:class:`RecordedAnswer`), never a merely possible one."""
    if draft.status != "sent":
        return []
    have = {proof.kind for proof in proofs}
    arrived = answered or any(kind_info(kind).arrival for kind in have)
    found: list[str] = []
    channel = draft.sent_channel
    if channel == "registered_letter":
        if not draft.tracking_number:
            found.append(MISSING_TRACKING)
        if "posting_receipt" not in have:
            found.append(MISSING_POSTING)
        if not arrived:
            found.append(
                MISSING_DELIVERY if delivery_record_obtainable(draft, today) else MISSING_DELIVERY_LATE
            )
    elif channel == "fax" and "fax_report" not in have and not answered:
        found.append(MISSING_FAX)
    elif channel == "email" and "sent_email" not in have:
        found.append(MISSING_EMAIL)
    elif channel == "online_button" and "cancel_confirmation" not in have:
        found.append(MISSING_BUTTON)
    elif not have and not answered and channel in _NOTHING_KEPT:
        found.append(_NOTHING_KEPT[channel])
    return found


def conflicts(draft: Draft, proofs: Sequence[RecordedProof]) -> list[str]:
    """Proof days that contradict the day the letter is marked as sent (policy 5), in the person's words."""
    sent = sent_day(draft)
    if sent is None:
        return []
    found: list[str] = []
    for proof in proofs:
        day = _day(proof.on_date)
        if day is None or proof.kind not in SENDING_DAY_KINDS or day == sent:
            continue
        found.append(
            f"Your {kind_info(proof.kind).label.lower()} says {fmt_date(day)}, but the letter is marked as "
            f"sent on {fmt_date(sent)} — correct one of them, so your records agree."
        )
    return found


def _day(text: str | None) -> date | None:
    try:
        return date.fromisoformat(text[:10]) if text else None
    except ValueError:
        return None


# --------------------------------------------------------------------------------------------------
# timeline
# --------------------------------------------------------------------------------------------------

_ORDER = {
    "created": 0,
    "sent": 1,
    "tracking": 2,
    "proof": 3,
    "delivered": 4,
    "answered": 5,
    "possible_answer": 6,
}
#: Timeline kinds that are shown to the person but never written into the Nachweis.
NOT_IN_NACHWEIS = frozenset({"possible_answer"})


@dataclass(frozen=True)
class TimelineEvent:
    """One line of the timeline in both languages (the web shows English, the Nachweis both).

    ``date`` is ``None`` for a proof without a day: it is listed apart with ``added_on``, the day it was
    added to Ordnung (policy 4)."""

    date: str | None
    kind: str
    english: str
    german: str
    detail: str | None = None
    ref: RefLink | None = None
    added_on: str | None = None

    @property
    def in_nachweis(self) -> bool:
        """Whether the Nachweis states it (a possible answer is only a hint to the person)."""
        return self.kind not in NOT_IN_NACHWEIS

    def event(self) -> ProofEvent:
        return ProofEvent.model_validate(
            {
                "date": self.date,
                "kind": self.kind,
                "label": self.english,
                "detail": self.detail,
                "ref": self.ref,
                "added_on": self.added_on,
            }
        )


@dataclass(frozen=True)
class RecordedProof:
    """A proof as the timeline needs it: its kind, day, note and file."""

    kind: str
    on_date: str | None
    created_day: str
    note: str | None
    document: Document | None


@dataclass(frozen=True)
class RecordedAnswer:
    """A confirmed answer to a sent letter (policy 3): ``confirmation`` — a confirmation of the cancelled
    contract; ``letter`` — a letter the person said is the answer; ``noted`` — the person said it was
    answered (by phone, e-mail …) without a letter in Ordnung."""

    day: str | None
    document: Document | None
    how: Literal["confirmation", "letter", "noted"]


def _title(document: Document) -> str:
    return document.title or document.filename


def letter_day(document: Document) -> str:
    """The day a letter shows: its date, else the day it arrived, else the day it was added."""
    return document.doc_date or document.received_date or document.created_at[:10]


def _answer_event(answer: RecordedAnswer) -> TimelineEvent | None:
    doc = answer.document
    day = answer.day or (letter_day(doc) if doc is not None else None)
    if day is None:
        return None
    ref = RefLink(type="document", id=doc.id) if doc is not None else None
    if answer.how == "noted" or doc is None:
        return TimelineEvent(
            day, "answered", "Answered — as you noted", "Beantwortet (laut Angabe des Absenders)", None, ref
        )
    if answer.how == "confirmation":
        return TimelineEvent(
            day,
            "answered",
            f"Cancellation confirmed: “{_title(doc)}”",
            f"Kündigung bestätigt: „{_title(doc)}“",
            None,
            ref,
        )
    return TimelineEvent(
        day, "answered", f"Answer received: “{_title(doc)}”", f"Antwort erhalten: „{_title(doc)}“", None, ref
    )


def timeline(
    draft: Draft,
    tracking: TrackingInfo | None,
    proofs: Sequence[RecordedProof],
    answer: RecordedAnswer | None,
    possible: Document | None = None,
) -> list[TimelineEvent]:
    """The letter's timeline (policy 4), oldest first, then the proofs without a day. A letter drafted
    in Ordnung after the day the person says it went out (recorded afterwards) starts with its sending.
    ``possible`` is a letter that may be the answer: listed (last of the dated ones) only while no answer
    is confirmed, and never in the Nachweis (:attr:`TimelineEvent.in_nachweis`)."""
    created = draft.created_at[:10]
    sent_on = draft.sent_at[:10] if draft.status == "sent" and draft.sent_at else None
    events = []
    if sent_on is None or created <= sent_on:
        events.append(TimelineEvent(created, "created", "Letter drafted", "Schreiben erstellt"))
    if sent_on:
        events.append(
            TimelineEvent(
                sent_on,
                "sent",
                f"Sent by {channel_label(draft.sent_channel)}",
                f"Versandt per {channel_label(draft.sent_channel, german=True)}",
            )
        )
        if tracking is not None:
            detail = "check digit correct" if tracking.checked else "not checked"
            events.append(
                TimelineEvent(
                    sent_on,
                    "tracking",
                    f"Tracking number {tracking.display}",
                    f"Sendungsnummer {tracking.display}",
                    detail,
                )
            )
    undated: list[TimelineEvent] = []
    for proof in proofs:
        info = kind_info(proof.kind)
        ref = RefLink(type="document", id=proof.document.id) if proof.document else None
        if proof.on_date is None:
            undated.append(
                TimelineEvent(
                    None, "proof", info.label, info.german, proof.note, ref, added_on=proof.created_day
                )
            )
            continue
        delivered = info.arrival and proof.kind != "cancel_confirmation"
        english = f"Delivered — {info.label.lower()}" if delivered else info.label
        german = f"Zugestellt laut {info.german}" if delivered else info.german
        events.append(
            TimelineEvent(
                proof.on_date, "delivered" if delivered else "proof", english, german, proof.note, ref
            )
        )
    answered = _answer_event(answer) if answer is not None else None
    if answered is not None:
        events.append(answered)
    elif possible is not None:
        events.append(
            TimelineEvent(
                letter_day(possible),
                "possible_answer",
                f"Their letter “{_title(possible)}” arrived — is it the answer?",
                f"Schreiben im selben Vorgang: „{_title(possible)}“",
                "Not confirmed as the answer: open it, and if it answers yours, say so.",
                RefLink(type="document", id=possible.id),
            )
        )
    dated = sorted(events, key=lambda e: (e.date or "", _ORDER.get(e.kind, 9)))
    return dated + sorted(undated, key=lambda e: e.added_on or "")


def day_words(day: str) -> str:
    """``Tue 1 Sep 2026`` for a ``YYYY-MM-DD`` day (as typed when it isn't one)."""
    try:
        return fmt_date(date.fromisoformat(day[:10]))
    except ValueError:
        return day
