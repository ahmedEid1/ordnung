"""How to send a cancellation or objection: allowed channels, form requirements and send-by dates.

Form rules (SPEC § 11, § 21):

* Consumer cancellations: text form is enough; standard terms can't require more (§ 309 Nr. 13
  BGB). Contracts that could be concluded on a website must offer a cancellation button, which counts
  the moment it is pressed (§ 312k BGB) — not for insurance or bank contracts.
* Tenancy (§ 568 BGB) and employment (§ 623 BGB) notices need a hand-signed letter.
* Tax objections: in writing, electronically (ELSTER, e-mail) or in person for the record (§ 357 AO).
* Other objections (§ 70 VwGO, § 84 SGG): in writing (signed; a fax of the signed letter counts), a
  qualified electronic form or in person for the record — a plain e-mail is not enough.
* Court orders: the objection to a court payment order goes to the court in writing, best on the
  enclosed form, or online at online-mahnantrag.de (§ 694 ZPO; § 692 Abs. 1 Nr. 5 ZPO); the objection
  to an enforcement order in writing to the court (§ 700, § 340 ZPO). Any Amtsgericht's
  Rechtsantragstelle takes either down for the record (§ 702, § 129a ZPO), but at a court other than
  the issuing one it only counts once the record reaches the issuing court (§ 129a Abs. 3 S. 2 ZPO),
  so the channel says to go early (by the send-by date, as for a letter). Never by e-mail. A labour
  court's orders are answered at that court, in writing or for the record at its office (§ 46a ArbGG,
  § 59 S. 2 ArbGG) — not at online-mahnantrag.de, and within one week.
* A tenant's objection to the landlord's notice: text form since 2025 (§ 574b Abs. 1 BGB); a signed
  letter by Einwurf-Einschreiben is still the safest proof.
* A withdrawal (§ 355 BGB): any clear statement; sending it in time is enough, so there is no postal
  buffer. The withdrawal button (§ 356a BGB, since 19 June 2026) only exists for contracts made
  online, so it is offered as one channel, not the recommended one.
* Replies to a rent increase request (consent needs no form but should be provable, § 558b BGB) and
  to an operating-cost statement (objections within twelve months, § 556 Abs. 3 S. 5 BGB) say so.
* The other template letters need no form; channels are ranked by proof.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from ordnung.models import ContractCategory, DraftKind, SendChannel, SendGuidance
from ordnung.rules import calendar_de, catalog
from ordnung.rules.deadlines import POSTAL_BUFFER_DAYS
from ordnung.rules.explain import fmt_date

GuidanceKind = DraftKind

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


def _labour_court_objection(letter_kind: str) -> SendGuidance:
    remedy = "objection (Widerspruch)" if letter_kind == "court_payment_order" else "objection (Einspruch)"
    rule = "arbgg_46a" if letter_kind == "court_payment_order" else "arbgg_59"
    channels = [
        _channel(
            "registered_letter",
            "Signed form or letter by Einwurf-Einschreiben",
            "Send it to the labour court that issued the order. " + _EINSCHREIBEN,
            recommended=True,
        ),
        _channel(
            "in_person",
            "The labour court's office (for the record)",
            "Free: they write it down for you (zu Protokoll); bring the order and its envelope.",
            rule,
        ),
        _channel("fax", "Fax of the signed letter", "Counts as written; keep the transmission report."),
        _channel("letter", "Signed letter by normal post", "Works, but you can't prove it arrived."),
        _channel("email", "E-mail", "Not valid at a court.", allowed=False),
    ]
    note = (
        f"Your {remedy} must reach the labour court that issued the order within one week (§ 46a Abs. 3, § 59 "
        "ArbGG) — in writing or for the record at its office; not by e-mail."
    )
    return SendGuidance(
        form="written_form",
        form_note=note,
        channels=channels,
        tips=["You have one week, not two: send it today or go to the court's office."],
    )


def _court_objection(letter_kind: str) -> SendGuidance:
    payment_order = letter_kind == "court_payment_order"
    # the court rule is cited once, in the form note's own words; channels cite only what they add
    channels = [
        _channel(
            "registered_letter",
            "Signed form or letter by Einwurf-Einschreiben"
            if payment_order
            else "Signed letter by Einwurf-Einschreiben",
            "Send it to the court that issued the order. " + _EINSCHREIBEN,
            recommended=True,
        ),
        _channel(
            "in_person",
            "Rechtsantragstelle (for the record)",
            "Free: they write it down for you (zu Protokoll); bring the order and its envelope. At the court "
            "that issued the order it counts at once. Any other Amtsgericht can take it down too, but then it "
            "only counts once their record reaches the issuing court — go by the send-by date, as for a letter.",
            "zpo_129a",
        ),
        _channel("fax", "Fax of the signed letter", "Counts as written; keep the transmission report."),
        _channel("letter", "Signed letter by normal post", "Works, but you can't prove it arrived."),
        _channel("email", "E-mail", "Not valid at a court.", allowed=False),
    ]
    if payment_order:
        channels.insert(
            1,
            _channel(
                "portal",
                "online-mahnantrag.de",
                "The courts' own site: object online with your ID card, or print a barcode form to sign and post.",
            ),
        )
        note = (
            "In writing to the court that issued the order (§ 694 ZPO) — best on the form that came with it (tick "
            "how much you object to and sign it), or online. No reasons are needed; e-mail is not valid."
        )
        tips = ["Keep a copy of the form you send and the envelope with the delivery date."]
    else:
        note = (
            "In writing to the court that issued the order (§ 700, § 340 ZPO; not by e-mail), or for the record at its "
            "Rechtsantragstelle. Another Amtsgericht can take it down too, but it only counts once their record "
            "reaches the issuing court (§ 129a Abs. 3 S. 2 ZPO) — go early. The period can't be extended."
        )
        tips = ["An objection doesn't stop enforcement by itself — ask for advice about suspending it."]
    return SendGuidance(form="written_form", form_note=note, channels=channels, tips=tips)


def _tenancy_objection() -> SendGuidance:
    return SendGuidance(
        form="text_form",
        form_note="Text form is enough since 2025 (§ 574b Abs. 1 BGB), but a signed letter by Einwurf-Einschreiben "
        "is the safest proof that it arrived in time.",
        channels=[
            _channel(
                "registered_letter",
                "Signed letter by Einwurf-Einschreiben",
                _EINSCHREIBEN,
                "bgb_574b",
                recommended=True,
            ),
            _channel(
                "in_person", "Hand it over in person", "Take a witness who has read the letter.", "bgb_574b"
            ),
            _channel(
                "email", "E-mail", "Valid (text form); ask the landlord to confirm receipt.", "bgb_574b"
            ),
            _channel("letter", "Letter by normal post", "Works, but you can't prove it arrived.", "bgb_574b"),
        ],
        tips=["Get advice from a tenants' association before you send it."],
    )


def _withdrawal() -> SendGuidance:
    return SendGuidance(
        form="text_form",
        form_note="Any clear statement is enough — no reasons, no signature. Sending it in time is enough "
        "(§ 355 Abs. 1 BGB); sending the goods back alone is not a withdrawal.",
        channels=[
            _channel(
                "email",
                "E-mail",
                "Valid; keep the sent e-mail as proof of when you sent it.",
                "bgb_355",
                recommended=True,
            ),
            _channel(
                "online_button",
                "The withdrawal button (contracts made online)",
                "For a contract made on a website or in an app, the company must offer one since 19 June 2026; it "
                "counts when you press it — save the confirmation. Not for contracts made at the door or by phone.",
                "bgb_356a",
            ),
            _channel("registered_letter", "Letter by Einwurf-Einschreiben", _EINSCHREIBEN, "bgb_355"),
            _channel("fax", "Fax", "Keep the transmission report.", "bgb_355"),
            _channel(
                "letter", "Letter by normal post", "Valid, but you can't prove when you sent it.", "bgb_355"
            ),
        ],
        tips=["Send the goods back separately, as the shop's instructions say."],
    )


def _payment_plan(party_kind: str | None) -> SendGuidance:
    if party_kind == "tax_office":
        return SendGuidance(
            form="any",
            form_note="No special form: ELSTER, fax, e-mail or a letter all work (§ 222 AO). Until the tax office "
            "agrees, the full amount stays due.",
            channels=[
                _channel(
                    "portal",
                    "ELSTER ('Sonstige Nachricht')",
                    "Instant, with a receipt.",
                    "ao_222",
                    recommended=True,
                ),
                _channel("fax", "Fax", "Keep the transmission report.", "ao_222"),
                _channel("email", "E-mail", "Ask for a confirmation.", "ao_222"),
                _channel("letter", "Letter", "Keep a copy.", "ao_222"),
            ],
        )
    guidance = _general_reply()
    guidance.form_note = "No special form is needed. Until they agree, the full amount stays due."
    return guidance


def _to_landlord(note: str, rule_id: str | None = None) -> SendGuidance:
    return SendGuidance(
        form="any",
        form_note=note,
        channels=[
            _channel(
                "registered_letter",
                "Letter by Einwurf-Einschreiben",
                _EINSCHREIBEN,
                rule_id,
                recommended=True,
            ),
            _channel("email", "E-mail", "Quick; keep the sent message and ask for a confirmation.", rule_id),
            _channel(
                "in_person", "Hand it over in person", "Take a witness who has read the letter.", rule_id
            ),
            _channel("letter", "Letter by normal post", "Works, but you can't prove it arrived.", rule_id),
        ],
    )


_STATEMENT_OBJECTIONS = (
    "Objections to the statement must reach the landlord within twelve months of receiving it (§ 556 Abs. 3 "
    "S. 5 BGB) — keep proof of when yours arrived."
)


def _rent_increase_reply() -> SendGuidance:
    guidance = _to_landlord(
        "Agreeing needs no special form, but make it provable: a letter by Einwurf-Einschreiben, or an e-mail the "
        "landlord confirms. You can agree to all of the increase or only part of it.",
        "bgb_558b",
    )
    guidance.tips.append(
        "Paying the higher rent without a word can also count as agreeing — decide first, then pay."
    )
    return guidance


def _template(kind: str, party_kind: str | None) -> SendGuidance:
    if kind == "withdrawal":
        return _withdrawal()
    if kind == "payment_plan":
        return _payment_plan(party_kind)
    if kind == "defect_notice":
        return _to_landlord(
            "No special form, but keep proof that you reported the defect: the rent is reduced while it lasts, and "
            "if the landlord didn't know of it you can lose that for the time they couldn't repair it (§ 536c BGB)."
        )
    if kind == "deposit_return":
        return _to_landlord("No special form is needed; keep proof of when you asked.")
    if kind == "receipts_inspection":
        guidance = _to_landlord("No special form is needed; keep proof of when you asked.", "bgb_556_3")
        guidance.tips.append(_STATEMENT_OBJECTIONS)
        return guidance
    guidance = _general_reply()
    if kind == "extension_request":
        guidance.tips.append(
            "An extension only counts once they confirm it. Deadlines set by law — objections, court "
            "deadlines — can't be extended by asking: meet them anyway."
        )
    if kind == "data_access":
        guidance.tips.append(
            "They must answer within one month (Art. 12 Abs. 3 GDPR), in hard cases within three."
        )
    return guidance


#: The letters a person may send to a court whose name they typed in (:func:`send_guidance`).
_SENT_TO_A_COURT: tuple[GuidanceKind, ...] = ("objection", "general_reply", "extension_request")


def _court_channels(*, unsure: bool = False) -> list[SendChannel]:
    """How to write to a court: in writing, signed — plain e-mail isn't valid there. ``unsure``: the
    recipient only may be a court (a name typed in that starts like one, "AG Hagen", "LG Electronics"),
    so e-mail stays allowed with that caveat."""
    email = (
        _channel(
            "email",
            "E-mail",
            "Not valid if this is a court (AG, LG … before a place) — then send the signed letter. Fine for a "
            "company whose name only starts like one.",
        )
        if unsure
        else _channel("email", "E-mail", "Not valid at a court.", allowed=False)
    )
    return [
        _channel(
            "letter",
            "Signed letter",
            "Quote the court's reference (Aktenzeichen); keep a copy.",
            recommended=True,
        ),
        _channel("fax", "Fax of the signed letter", "Keep the transmission report."),
        _channel(
            "in_person",
            "At the court's Rechtsantragstelle",
            "Free: staff take it down for you; bring the court's letter.",
        ),
        email,
    ]


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
    letter_kind: str | None = None,
    due: date | None = None,
    region: str | None = None,
    today: date,
    postal_buffer_days: int = POSTAL_BUFFER_DAYS,
    court: bool = False,
    labour_court: bool = False,
    court_unsure: bool = False,
) -> SendGuidance:
    """Ranked channels, form requirement and dates for sending a letter of ``kind``.

    ``letter_kind`` is the kind of the letter being answered: an objection to a court order or to a
    landlord's notice has its own form. ``court``: the letter goes to a court, which takes it only in
    writing — never by plain e-mail; ``labour_court``: it is a labour court, whose orders are answered
    there within one week; ``court_unsure``: the recipient's name only may be a court's (a name typed in,
    :func:`~ordnung.rules.routing.may_be_court`): a letter people send to a court (an objection, a reply,
    a request for more time) then gets the court's channels, a signed letter first, with e-mail last and
    allowed only for the case it isn't a court; other letters (a withdrawal to "LG Electronics") keep their
    own. ``due`` is the day it must *arrive* (``must_arrive_by``).
    ``send_by`` is the latest day to post a letter: ``postal_buffer_days`` business days before the
    last business day on or before ``due``, never before ``today``; ``None`` without a due date or
    once it has passed. A withdrawal only has to be *sent* by ``due`` (§ 355 Abs. 1 S. 5 BGB).
    """
    if kind == "cancellation":
        guidance = _cancellation(contract_category, party_kind)
    elif kind == "objection" and letter_kind in ("court_payment_order", "enforcement_order"):
        guidance = _labour_court_objection(letter_kind) if labour_court else _court_objection(letter_kind)
    elif kind == "objection" and letter_kind == "landlord_notice":
        guidance = _tenancy_objection()
    elif kind == "objection":
        guidance = _objection(party_kind)
    elif kind == "general_reply" and letter_kind == "rent_increase":
        guidance = _rent_increase_reply()
    elif kind == "general_reply" and letter_kind == "operating_costs":
        guidance = _to_landlord(
            "No special form is needed; keep proof of when your reply arrived.", "bgb_556_3"
        )
        guidance.tips.append(_STATEMENT_OBJECTIONS)
    elif kind == "general_reply":
        guidance = _general_reply()
    else:
        guidance = _template(kind, party_kind)
    unsure = court_unsure and not court and kind in _SENT_TO_A_COURT
    if (court or unsure) and not (
        kind == "objection" and letter_kind in ("court_payment_order", "enforcement_order")
    ):
        guidance.channels = _court_channels(unsure=unsure)
    guidance.tips.append("Keep a copy of what you send and any proof of delivery.")
    if due is None:
        return guidance
    if kind == "withdrawal":
        return _withdrawal_dates(guidance, due, today)
    guidance.must_arrive_by = due.isoformat()
    if due < today:
        guidance.tips.insert(
            0, f"The deadline ({fmt_date(due)}) has passed — get advice quickly; more time may be possible."
        )
        return guidance
    safe = calendar_de.previous_business_day(due, region)
    buffered = calendar_de.add_business_days(safe, -postal_buffer_days, region)
    send_by = max(buffered, today)
    guidance.send_by = send_by.isoformat()
    if buffered < today:
        _too_late_to_post(guidance, due)
    else:
        guidance.tips.insert(
            0,
            f"It must arrive by {fmt_date(due)} — sending it is not enough. Post a letter by {fmt_date(send_by)}.",
        )
    if safe != due:
        guidance.tips.insert(
            1, f"{fmt_date(due)} is not a working day; make sure it arrives by {fmt_date(safe)}."
        )
    return guidance


#: Channels that can reach the recipient the day they are used (a letter by post can't be relied on to).
_SAME_DAY: tuple[str, ...] = ("fax", "online_button", "portal", "email", "in_person")


def _too_late_to_post(guidance: SendGuidance, due: date) -> None:
    """The usual time to post has passed (review round 4 of phase 2: the letter page still said "Post a letter
    by" the last day — for a Notfrist, §§ 700 Abs. 1, 339 ZPO, a letter posted then arrives late): say a letter
    posted today may arrive too late, rank the allowed channels that reach the recipient the same day first and
    recommend the first of them."""
    guidance.post_too_late = True
    fast = [c for c in guidance.channels if c.allowed and c.channel in _SAME_DAY]
    fast.sort(key=lambda c: _SAME_DAY.index(c.channel))
    rest = [c for c in guidance.channels if c not in fast]
    for channel in guidance.channels:
        channel.recommended = False
    for channel in fast[:1]:
        channel.recommended = True
    guidance.channels = [*fast, *rest]
    ways = "; ".join(c.label for c in fast) or "take it there yourself"
    guidance.tips.insert(
        0,
        f"It must arrive by {fmt_date(due)} — sending it is not enough, and the usual time to post it has passed: "
        f"a letter posted today may arrive too late. Use a way that reaches them today: {ways}.",
    )


def _withdrawal_dates(guidance: SendGuidance, due: date, today: date) -> SendGuidance:
    """A withdrawal counts when it is sent, so the send-by date is the deadline itself."""
    if due < today:
        guidance.tips.insert(
            0,
            f"The period to withdraw ended on {fmt_date(due)}. A withdrawal sent now probably comes too late — "
            "get advice before you rely on it.",
        )
        return guidance
    guidance.send_by = due.isoformat()
    guidance.tips.insert(0, f"Send it by {fmt_date(due)} — sending it in time is enough.")
    return guidance
