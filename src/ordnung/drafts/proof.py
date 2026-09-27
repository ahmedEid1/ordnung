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
3. **An answer is proof of arrival.** When a letter linked to the sent one arrived
   (:meth:`ordnung.secretary.triggers.Ledger.reply_to`), nothing about arrival is asked for any more.
4. **The timeline lists only what the person recorded**: drafted, sent (channel), tracking number,
   each proof on the day it shows, the answer. Nothing is inferred from a tracking website.

Limits: the channel is what the person said; a proof's kind and day are what they chose, not read from
the file (proof files are never sent to a model).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

from ordnung.ids import content_id
from ordnung.models import Document, Draft, ProofEvent, ProofKind, RefLink, TrackingInfo
from ordnung.rules.explain import fmt_date

#: Sent letters get a follow-up to-do with this id (one per letter; marking it sent again updates it).
FOLLOWUP_SLOT = "followup"
#: ``Document.source`` of a proof file: a private outgoing document that belongs to its letter. It is
#: listed with the letter, not in the Inbox, search, Today, the timeline or the life areas.
PROOF_SOURCE = "proof"

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
        "The day the carrier put it in their letterbox, confirmed by the carrier. With the posting "
        "receipt, courts have accepted it as prima facie proof that the letter arrived.",
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
    "deposit_return": "Your deposit back",
    "address_change": None,
}

MISSING_TRACKING = "Add the tracking number from your posting receipt (Einlieferungsbeleg)."
MISSING_POSTING = "Add a photo of the posting receipt — it shows the day you posted the letter."
MISSING_DELIVERY = (
    "Ask Deutsche Post for a copy of the delivery record (Auslieferungsbeleg) while they still issue it, "
    "or keep the return receipt (Rückschein) if you sent it with one. The online tracking status alone "
    "was not accepted as proof that a letter arrived (BAG 2 AZR 68/24)."
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


def missing(draft: Draft, kinds: Iterable[str], *, answered: bool) -> list[str]:
    """What would make the proof of a sent letter stronger, by the channel it went by (policy 2 and 3)."""
    if draft.status != "sent":
        return []
    have = set(kinds)
    arrived = answered or any(kind_info(kind).arrival for kind in have)
    found: list[str] = []
    channel = draft.sent_channel
    if channel == "registered_letter":
        if not draft.tracking_number:
            found.append(MISSING_TRACKING)
        if "posting_receipt" not in have:
            found.append(MISSING_POSTING)
        if not arrived:
            found.append(MISSING_DELIVERY)
    elif channel == "fax" and "fax_report" not in have and not answered:
        found.append(MISSING_FAX)
    elif channel == "email" and "sent_email" not in have:
        found.append(MISSING_EMAIL)
    elif channel == "online_button" and "cancel_confirmation" not in have:
        found.append(MISSING_BUTTON)
    elif not have and not answered and channel in _NOTHING_KEPT:
        found.append(_NOTHING_KEPT[channel])
    return found


# --------------------------------------------------------------------------------------------------
# timeline
# --------------------------------------------------------------------------------------------------

_ORDER = {"created": 0, "sent": 1, "tracking": 2, "proof": 3, "delivered": 4, "answered": 5}


@dataclass(frozen=True)
class TimelineEvent:
    """One line of the timeline in both languages (the web shows English, the Nachweis both)."""

    date: str
    kind: str
    english: str
    german: str
    detail: str | None = None
    ref: RefLink | None = None

    def event(self) -> ProofEvent:
        return ProofEvent.model_validate(
            {
                "date": self.date,
                "kind": self.kind,
                "label": self.english,
                "detail": self.detail,
                "ref": self.ref,
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


def _title(document: Document) -> str:
    return document.title or document.filename


def timeline(
    draft: Draft,
    tracking: TrackingInfo | None,
    proofs: Sequence[RecordedProof],
    reply: Document | None,
) -> list[TimelineEvent]:
    """The letter's timeline (policy 4), oldest first. A letter drafted in Ordnung after the day the
    person says it went out (recorded afterwards) starts with its sending."""
    created = draft.created_at[:10]
    sent_day = draft.sent_at[:10] if draft.status == "sent" and draft.sent_at else None
    events = []
    if sent_day is None or created <= sent_day:
        events.append(TimelineEvent(created, "created", "Letter drafted", "Schreiben erstellt"))
    if sent_day:
        events.append(
            TimelineEvent(
                sent_day,
                "sent",
                f"Sent by {channel_label(draft.sent_channel)}",
                f"Versandt per {channel_label(draft.sent_channel, german=True)}",
            )
        )
        if tracking is not None:
            detail = "check digit correct" if tracking.checked else "not checked"
            events.append(
                TimelineEvent(
                    sent_day,
                    "tracking",
                    f"Tracking number {tracking.display}",
                    f"Sendungsnummer {tracking.display}",
                    detail,
                )
            )
    for proof in proofs:
        info = kind_info(proof.kind)
        delivered = info.arrival and proof.kind != "cancel_confirmation" and proof.on_date is not None
        day = proof.on_date or proof.created_day
        english = f"Delivered — {info.label.lower()}" if delivered else info.label
        german = f"Zugestellt laut {info.german}" if delivered else info.german
        ref = RefLink(type="document", id=proof.document.id) if proof.document else None
        events.append(
            TimelineEvent(day, "delivered" if delivered else "proof", english, german, proof.note, ref)
        )
    if reply is not None:
        day = reply.doc_date or reply.received_date or reply.created_at[:10]
        events.append(
            TimelineEvent(
                day,
                "answered",
                f"Answer received: “{_title(reply)}”",
                f"Antwort erhalten: „{_title(reply)}“",
                None,
                RefLink(type="document", id=reply.id),
            )
        )
    return sorted(events, key=lambda e: (e.date, _ORDER.get(e.kind, 9)))


def day_words(day: str) -> str:
    """``Tue 1 Sep 2026`` for a ``YYYY-MM-DD`` day (as typed when it isn't one)."""
    try:
        return fmt_date(date.fromisoformat(day[:10]))
    except ValueError:
        return day
