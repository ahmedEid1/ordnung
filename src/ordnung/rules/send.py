"""How to send a cancellation or objection: allowed channels, form requirements and send-by dates.

Form rules (SPEC § 11, § 21):

* Consumer cancellations: text form is enough; standard terms can't require more (§ 309 Nr. 13
  BGB). Contracts that could be concluded on a website must offer a cancellation button, which counts
  the moment it is pressed (§ 312k BGB) — not for insurance or bank contracts.
* Tenancy (§ 568 BGB) and employment (§ 623 BGB) notices need a hand-signed letter.
* Tax objections: in writing, electronically (ELSTER, e-mail) or in person for the record (§ 357 AO).
* Other objections (§ 70 VwGO, § 84 SGG): in writing (signed; a fax of the signed letter counts), a
  qualified electronic form or in person for the record — a plain e-mail is not enough.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from ordnung.models import ContractCategory, SendChannel, SendGuidance
from ordnung.rules import calendar_de, catalog
from ordnung.rules.deadlines import POSTAL_BUFFER_DAYS
from ordnung.rules.explain import fmt_date

GuidanceKind = Literal["cancellation", "objection", "general_reply"]

_EINSCHREIBEN = (
    "Einwurf-Einschreiben (registered letter): keep the posting receipt and ask for the delivery record "
    "(Auslieferungsbeleg) — online tracking alone is no proof (BAG 2 AZR 68/24)."
)


def _channel(
    channel: Literal["online_button", "email", "fax", "letter", "registered_letter", "in_person", "portal"],
    label: str,
    note: str,
    rule_id: str | None = None,
    *,
    allowed: bool = True,
    recommended: bool = False,
) -> SendChannel:
    return SendChannel(
        channel=channel,
        label=label,
        allowed=allowed,
        recommended=recommended,
        note=note,
        citation=catalog.citation(rule_id) if rule_id else None,
    )


def _signed_letter_channels(rule_id: str, what: str) -> list[SendChannel]:
    not_valid = f"Not valid: {what} needs a handwritten signature."
    return [
        _channel(
            "registered_letter",
            "Signed letter by Einwurf-Einschreiben",
            _EINSCHREIBEN,
            rule_id,
            recommended=True,
        ),
        _channel("in_person", "Hand it over in person", "Take a witness who has read the letter.", rule_id),
        _channel("letter", "Signed letter by normal post", "Works, but you can't prove it arrived.", rule_id),
        _channel("email", "E-mail", not_valid, rule_id, allowed=False),
        _channel("fax", "Fax", not_valid, rule_id, allowed=False),
        _channel("online_button", "Online cancellation button", not_valid, "bgb_312k", allowed=False),
    ]


def _cancellation(contract_category: ContractCategory | None, party_kind: str | None) -> SendGuidance:
    if contract_category == "rent":
        return SendGuidance(
            form="written_form",
            form_note="A hand-signed letter is required, signed by every tenant — or enclose each missing "
            "tenant's original written authorisation (§ 568 BGB, § 174 BGB).",
            channels=_signed_letter_channels("bgb_568", "notice on a flat"),
            tips=[
                "A PDF with a qualified electronic signature is also valid (§ 126a BGB), but acceptance and "
                "proof are harder — paper is safer."
            ],
        )
    if contract_category == "employment":
        return SendGuidance(
            form="written_form",
            form_note="A hand-signed letter is required; electronic form is excluded (§ 623 BGB).",
            channels=_signed_letter_channels("bgb_623", "notice of employment"),
        )
    if contract_category == "insurance" and party_kind == "health_insurer":
        return SendGuidance(
            form="written_form",
            form_note="To switch, just join the new health insurer: it notifies your current one, which "
            "replaces your cancellation (§ 175 Abs. 2, 4 SGB V). Only if you leave statutory insurance "
            "altogether do you send a signed letter.",
            channels=[
                _channel(
                    "portal",
                    "Apply to your new health insurer",
                    "Its notice to your current insurer counts as your cancellation.",
                    "sgbv_175",
                    recommended=True,
                ),
                _channel(
                    "registered_letter",
                    "Signed letter by Einwurf-Einschreiben",
                    "Only needed if you leave statutory insurance altogether.",
                    "sgbv_175",
                ),
            ],
        )
    financial = contract_category in ("insurance", "bank")
    button_note = (
        "Insurers and banks don't have to offer one (§ 312k Abs. 1 BGB), but use it if they do."
        if financial
        else "If you could sign up on their website, they must offer a 'Verträge hier kündigen' button. It counts "
        "the moment you press it — save the confirmation page."
    )
    return SendGuidance(
        form="text_form",
        form_note="Text form is enough — e-mail, fax or letter, no signature needed; the company can't insist "
        "on more (§ 309 Nr. 13 BGB).",
        channels=[
            _channel(
                "online_button",
                "Online cancellation button",
                button_note,
                "bgb_312k",
                recommended=not financial,
            ),
            _channel(
                "registered_letter",
                "Letter by Einwurf-Einschreiben",
                _EINSCHREIBEN,
                "bgb_130",
                recommended=financial,
            ),
            _channel("fax", "Fax", "Keep the transmission report.", "bgb_309_13"),
            _channel(
                "email",
                "E-mail",
                "Valid (text form); ask for a written confirmation of the end date as proof.",
                "bgb_309_13",
            ),
            _channel("letter", "Letter by normal post", "Works, but you can't prove it arrived.", "bgb_130"),
        ],
        tips=[
            "For contracts from before October 2016 the terms may still require a signed letter — send one to be safe."
        ],
    )


def _objection(party_kind: str | None) -> SendGuidance:
    if party_kind == "tax_office":
        return SendGuidance(
            form="text_form",
            form_note="In writing or electronically — ELSTER, e-mail or fax are fine — or in person for the "
            "record (§ 357 Abs. 1 AO).",
            channels=[
                _channel(
                    "portal",
                    "ELSTER ('Einspruch')",
                    "Instant, with a receipt; works until midnight.",
                    "ao_357",
                    recommended=True,
                ),
                _channel("fax", "Fax", "Keep the transmission report.", "ao_357"),
                _channel("email", "E-mail", "Allowed for tax objections; ask for a confirmation.", "ao_357"),
                _channel("registered_letter", "Letter by Einwurf-Einschreiben", _EINSCHREIBEN, "ao_357"),
                _channel(
                    "letter", "Letter by normal post", "Works, but you can't prove it arrived.", "ao_357"
                ),
                _channel(
                    "in_person",
                    "In person at the tax office",
                    "They write it down for you (zur Niederschrift).",
                    "ao_357",
                ),
            ],
        )
    rule_id = "sgg_84" if party_kind == "health_insurer" else "vwgo_70"
    extra = (
        " Any German authority or social insurer also accepts it in time (§ 84 Abs. 2 SGG)."
        if rule_id == "sgg_84"
        else ""
    )
    return SendGuidance(
        form="written_form",
        form_note="In writing and signed, or in person for the record; a plain e-mail is not enough "
        f"({catalog.citation(rule_id)}).{extra}",
        channels=[
            _channel(
                "registered_letter",
                "Signed letter by Einwurf-Einschreiben",
                _EINSCHREIBEN,
                rule_id,
                recommended=True,
            ),
            _channel(
                "fax", "Fax of the signed letter", "Counts as written; keep the transmission report.", rule_id
            ),
            _channel("in_person", "In person", "They write it down for you (zur Niederschrift).", rule_id),
            _channel(
                "letter", "Signed letter by normal post", "Works, but you can't prove it arrived.", rule_id
            ),
            _channel(
                "portal",
                "The authority's online form",
                "Only if the letter offers one with ID login (BundID/eID).",
                rule_id,
            ),
            _channel("email", "Plain e-mail", "Not enough for an objection.", rule_id, allowed=False),
        ],
        tips=[
            "Use exactly the remedy and addressee named in the letter's instructions (Rechtsbehelfsbelehrung)."
        ],
    )


def _general_reply() -> SendGuidance:
    return SendGuidance(
        form="any",
        form_note="No special form is needed.",
        channels=[
            _channel("email", "E-mail", "Quick; keep the sent message.", recommended=True),
            _channel("portal", "The sender's online portal", "If the letter mentions one."),
            _channel("letter", "Letter", "Keep a copy."),
            _channel("fax", "Fax", "Keep the transmission report."),
        ],
    )


def send_guidance(
    kind: GuidanceKind,
    *,
    contract_category: ContractCategory | None = None,
    party_kind: str | None = None,
    due: date | None = None,
    region: str | None = None,
    today: date,
    postal_buffer_days: int = POSTAL_BUFFER_DAYS,
) -> SendGuidance:
    """Ranked channels, form requirement and dates for sending a letter of ``kind``.

    ``due`` is the day it must *arrive* (``must_arrive_by``). ``send_by`` is the latest day to post a
    letter: ``postal_buffer_days`` business days before the last business day on or before ``due``,
    never before ``today``; ``None`` without a due date or once it has passed.
    """
    if kind == "cancellation":
        guidance = _cancellation(contract_category, party_kind)
    elif kind == "objection":
        guidance = _objection(party_kind)
    else:
        guidance = _general_reply()
    guidance.tips.append("Keep a copy of what you send and any proof of delivery.")
    if due is None:
        return guidance
    guidance.must_arrive_by = due.isoformat()
    if due < today:
        guidance.tips.insert(
            0, f"The deadline ({fmt_date(due)}) has passed — get advice quickly; more time may be possible."
        )
        return guidance
    safe = calendar_de.previous_business_day(due, region)
    send_by = max(calendar_de.add_business_days(safe, -postal_buffer_days, region), today)
    guidance.send_by = send_by.isoformat()
    guidance.tips.insert(
        0,
        f"It must arrive by {fmt_date(due)} — sending it is not enough. Post a letter by {fmt_date(send_by)}.",
    )
    if safe != due:
        guidance.tips.insert(
            1, f"{fmt_date(due)} is not a working day; make sure it arrives by {fmt_date(safe)}."
        )
    return guidance
