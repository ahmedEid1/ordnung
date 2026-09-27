"""Dates of high-stakes letters that a plain period can't express (ADR 0002).

:mod:`ordnung.rules.routing` decides which dates come here; this module computes them into the same
receipts as :mod:`ordnung.rules.deadlines` (steps with citations, warnings, confidence):

=============  ==================================  ============================================  ===========================
Rule           Counts from                         Last day                                      Weekend or holiday
=============  ==================================  ============================================  ===========================
``sgb3_38``    the day the person learned the end  3 months before the end, or 3 days after      kept (registering online
               (the dismissal's arrival; a         learning it when less time is left            works any day)
               notice without notice period
               ends the job then)
``bgb_558b``   the day the request arrived         end of the 2nd calendar month after           next working day (§ 193 BGB)
               (the new rent: its first payment)   (the new rent: start of the 3rd month, or     (a payment: none)
                                                   the later start the letter names)
``bgb_574b``   the day the tenancy ends (a notice  2 months before (counted backwards)           never later; safe date
               too short for its period: the
               earliest end it can have, § 573c)
``bgb_355``    the contract, or the goods'         14 days later; sending in time is enough      next working day at the
               arrival                                                                            consumer's home (§ 193 BGB)
=============  ==================================  ============================================  ===========================

Arrival days follow the engine's policy (SPEC § 21): a day stated in the letter or confirmed by the
person counts (both: the earlier); otherwise the letter's date, the earliest plausible day, with ``low``
confidence and the question "when did it arrive?". An end date the model read counts like a stated
anchor only when the termination's own sentence writes it (``RuleContext.end_date_grounding``). When the letter also names its own date for one of these
deadlines and it differs from the law's, the receipt says so; for the rent increase the law's date
is shown (a landlord can't shorten it), for the others the earlier of the two — and a letter's date
later than the law's is a soft failure there (worth a second look: the end it counts from may be
misread). A withdrawal period
the letter states that isn't 14 days (a shop may grant 30) is shown next to the law's: the earlier
date while it lasts, then the later one — never "passed" while either still runs. A passed objection
date for a landlord's notice says when the tenant may still object (§ 574b Abs. 2 S. 2 BGB).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, timedelta

from ordnung.models import ComputationReceipt, DateSpec
from ordnung.rules import calendar_de
from ordnung.rules.consumer import WITHDRAWAL_DAYS, withdrawal_end
from ordnung.rules.deadlines import (
    _BGB_COUNTING,
    RuleContext,
    Trace,
    _no_date,
    _receipt,
    _resolve_anchor,
    _safe_date,
    _same_period,
    _send_by,
    check_regional_holidays,
    parse_date,
    place_region,
    plan_send_by,
)
from ordnung.rules.employment import registration_deadline
from ordnung.rules.explain import fmt_date, fmt_period, month_name
from ordnung.rules.periods import add_period, shift_to_business_day
from ordnung.rules.tenancy import consent_period, next_permissible_end, notice_objection_deadline

_Compute = Callable[[DateSpec, RuleContext, Trace, int], ComputationReceipt]

#: § 574b Abs. 2 S. 2 BGB: without the landlord's timely notice of the right to object, the tenant
#: can still object at the first hearing of an eviction suit.
LATE_NOTICE_OBJECTION = (
    "If the landlord didn't tell you in time about your right to object, its form and its deadline, you can "
    "still object at the first hearing of an eviction suit (§ 574b Abs. 2 S. 2 BGB) — get advice."
)


def _arrival(spec: DateSpec, ctx: RuleContext, trace: Trace) -> date | None:
    """The day the letter arrived: stated, confirmed, else its date (asking for the real one)."""
    as_receipt = spec.model_copy(
        update={"anchor": "receipt", "anchor_date": spec.anchor_date if spec.anchor == "receipt" else None}
    )
    anchor = _resolve_anchor(as_receipt, ctx, trace)
    return anchor.day if anchor else None


def _check_end(trace: Trace, ctx: RuleContext, end: date, what: str) -> None:
    """The rubric's anchor criterion for the end a termination announces (``ctx.end_date``), which the
    model reads: only one written in the termination's own sentence may give ``high``; one written
    elsewhere in the letter is a soft failure, one not written in it at all a hard one (SPEC § 21)."""
    if end != ctx.end_date or ctx.end_date_grounding == "quote":
        return
    if ctx.end_date_grounding == "letter":
        trace.soft(
            f"The end of the {what} ({fmt_date(end)}) is written in the letter, but not in the sentence that "
            "ends it — check it: this date counts from it."
        )
        return
    trace.use("termination_end")
    trace.hard(
        f"We read {fmt_date(end)} as the end of the {what}, but that date isn't written in the letter — check "
        "it: this date counts from it."
    )


def _written_date(spec: DateSpec) -> date | None:
    return parse_date(spec.date) if spec.type == "fixed" else None


def _note_letter_date(trace: Trace, written: date, legal: date, *, keep: str) -> None:
    """The letter names ``written`` for a deadline the law sets to ``legal`` (they differ)."""
    trace.warnings.append(
        f"The letter names {fmt_date(written)}; by law the date is {fmt_date(legal)} — {keep}."
    )


def _later_letter_date(trace: Trace, written: date, legal: date) -> None:
    """The letter names a later day than the law's for a deadline the law sets: the law's earlier date is
    kept, and the difference is a soft failure — the end the law's date counts from may be misread."""
    trace.soft(
        f"The letter names {fmt_date(written)}, later than the law's date ({fmt_date(legal)}) — we show the "
        "earlier. Check the letter: the date it counts from may be different."
    )


def _registration(spec: DateSpec, ctx: RuleContext, trace: Trace, buffer: int) -> ComputationReceipt:
    end = parse_date(spec.anchor_date) if spec.anchor == "explicit_date" else None
    end = end or ctx.end_date
    # a dismissal without notice period ends the job when it arrives: an end the letter gives belongs to the
    # notice given in the alternative (review round 4 of phase 2: counted from it, the date was days late)
    alternative_end, end = (end, None) if ctx.ends_on_arrival else (None, end)
    learned = _arrival(spec, ctx, trace)
    if learned is None:
        return _receipt(trace, ctx, due=None, summary="No date could be computed: the start date is missing.")
    due, basis = registration_deadline(learned, end)
    trace.step(f"You learned when the job ends on {fmt_date(learned)}", learned, "sgb3_38")
    if ctx.ends_on_arrival:
        trace.step(
            f"A dismissal without notice period (fristlos) ends the job when it arrives, so less than three "
            f"months are left: register within three days, by {fmt_date(due)}",
            due,
            "sgb3_38",
        )
        why = f"three days after the dismissal without notice period arrived ({fmt_date(learned)})"
        if alternative_end is not None:
            trace.warnings.append(
                f"The letter also names {fmt_date(alternative_end)}: the end of a notice with a notice period "
                "given in the alternative (hilfsweise). Register within the three days anyway — also if you "
                "challenge the dismissal (§ 38 Abs. 1 S. 3 SGB III)."
            )
    elif basis == "before_end" and end is not None:
        trace.step(
            f"The job ends on {fmt_date(end)}; three months before that is {fmt_date(due)}", due, "sgb3_38"
        )
        why = f"three months before the job ends on {fmt_date(end)}"
        # a later end than the real one gives a later date (three days after learning never does)
        _check_end(trace, ctx, end, "job")
    elif basis == "boundary" and end is not None:
        trace.step(
            f"The job ends on {fmt_date(end)}; three months before that is {fmt_date(due - timedelta(days=1))} "
            f"or, as some read it, {fmt_date(due)} — the day you learned it: on that reading three months were "
            "still left, so the deadline is that same day (the earlier date)",
            due,
            "sgb3_38",
        )
        why = f"three months before the job ends on {fmt_date(end)}, the day you learned it"
        _check_end(trace, ctx, end, "job")
    else:
        label = "less than three months are left" if end is not None else "we don't know when the job ends"
        trace.step(f"As {label}, register within three days: by {fmt_date(due)}", due, "sgb3_38")
        why = f"three days after you learned the end date ({fmt_date(learned)})"
        if end is None:
            trace.soft(
                "We don't know when the job ends. If it ends more than three months after you learned of it, "
                "you have until three months before the end — we show the earlier date."
            )
    written = _written_date(spec)
    if written is not None and written < due:
        trace.warnings.append(
            f"The letter names {fmt_date(written)}, earlier than the law's date — we show the earlier."
        )
        due = written
    elif written is not None and written > due:
        _later_letter_date(trace, written, due)
    if not calendar_de.is_business_day(due, None):
        trace.warnings.append(
            f"{fmt_date(due)} is not a working day. The deadline may run to the next working day "
            "(§ 26 Abs. 3 SGB X), but registering online works on any day — do it in time."
        )
    trace.step("Register online, by phone or in person — it counts the day you do it", due, "sgb3_38")
    return _receipt(trace, ctx, due=due, summary=f"Register as job-seeking by {fmt_date(due)}: {why}.")


def _consent(spec: DateSpec, ctx: RuleContext, trace: Trace, buffer: int) -> ComputationReceipt:
    region = calendar_de.normalize_region(ctx.region)
    arrived = _arrival(spec, ctx, trace)
    if arrived is None:
        return _receipt(trace, ctx, due=None, summary="No date could be computed: the start date is missing.")
    last, rent_from = consent_period(arrived)
    trace.step(f"The request arrived on {fmt_date(arrived)}", arrived, "bgb_558b")
    trace.step(
        f"The end of the second calendar month after {month_name(arrived)}: {fmt_date(last)}",
        last,
        "bgb_558b",
    )
    due, steps = shift_to_business_day(last, region, "bgb_193")
    trace.extend(steps)
    if region is None:
        check_regional_holidays(trace, [due])
    trace.step(
        f"Only if you agree, the higher rent is owed from {fmt_date(rent_from)}", rent_from, "bgb_558b"
    )
    written = _written_date(spec)
    if written is not None and written != due:
        keep = (
            "a landlord can't shorten the time you have to decide, so the law's date is shown"
            if written < due
            else "the law's date is shown, the earlier one"
        )
        _note_letter_date(trace, written, due, keep=keep)
    send_by = plan_send_by(trace, ctx.today, due, region=region, buffer=buffer)
    summary = (
        f"You have until {fmt_date(due)} to decide whether to agree; if you agree, the higher rent is owed "
        f"from {fmt_date(rent_from)}."
    )
    return _receipt(trace, ctx, due=due, summary=summary, send_by=send_by, region=region)


def _new_rent(spec: DateSpec, ctx: RuleContext, trace: Trace, buffer: int) -> ComputationReceipt:
    """The first payment of a rent increase's higher rent: never before the law allows it — the start of
    the third calendar month after the request arrived (§ 558b Abs. 1 BGB), and only once the person agrees
    (the payment's note says so). A later start the letter names is kept; an earlier one is noted."""
    arrived = _arrival(spec, ctx, trace)
    if arrived is None:
        return _receipt(trace, ctx, due=None, summary="No date could be computed: the start date is missing.")
    rent_from = consent_period(arrived)[1]
    trace.step(f"The request arrived on {fmt_date(arrived)}", arrived, "bgb_558b")
    trace.step(
        f"The start of the third calendar month after {month_name(arrived)}: the higher rent can be owed from "
        f"{fmt_date(rent_from)} at the earliest, and only if you agree",
        rent_from,
        "bgb_558b",
    )
    due = rent_from
    written = _written_date(spec)
    if written is not None and written > rent_from:
        trace.step(
            f"The letter asks for it from {fmt_date(written)}, later than the law allows", written, "bgb_558b"
        )
        due = written
    elif written is not None and written < rent_from:
        _note_letter_date(
            trace,
            written,
            rent_from,
            keep="a landlord can't ask for the higher rent earlier, so the law's date is shown",
        )
    region = place_region(spec, ctx)
    send_by = _send_by(trace, ctx, due, "payment", region, buffer)
    summary = f"If you agree to the increase, the higher rent is owed from {fmt_date(due)}."
    return _receipt(trace, ctx, due=due, summary=summary, send_by=send_by, region=region)


def _rent_increase(spec: DateSpec, ctx: RuleContext, trace: Trace, buffer: int) -> ComputationReceipt:
    """A rent increase's dates: the new rent's first payment, else the decision (§ 558b BGB)."""
    return (_new_rent if spec.nature == "payment" else _consent)(spec, ctx, trace, buffer)


#: A notice whose end is the next permissible date: the objection counts back from the earliest one.
_NEXT_END = re.compile(r"\b573c\b[^§]{0,20}\bBGB\b|nächstmöglich", re.I)
NEXT_END_WARNING = (
    "The notice's end is too early for a landlord's notice period, or it gives none that fits: a notice with "
    "a notice period usually ends the tenancy at the next date the law allows — the end of the month after "
    "next when it arrived by the third working day of a month, later after five or eight years of tenancy "
    "(§ 573c Abs. 1 BGB). This date counts back from the earliest such end; get advice on the real one."
)


def _objection_before_next_end(
    spec: DateSpec, ctx: RuleContext, trace: Trace, buffer: int
) -> ComputationReceipt:
    """The objection to a notice that ends the tenancy at the next permissible date (a notice too short
    for its period, or given in the alternative "zum nächstmöglichen Termin"): two months before the
    earliest such end after the notice arrived (:func:`~ordnung.rules.tenancy.next_permissible_end`)."""
    region = calendar_de.normalize_region(ctx.region)
    arrived = _arrival(spec, ctx, trace)
    if arrived is None:
        return _no_date(trace, ctx, "We need the day the notice arrived to count from it.")
    end = next_permissible_end(arrived, calendar_de.normalize_region(ctx.recipient_region))
    trace.step(f"The notice arrived on {fmt_date(arrived)}", arrived, "bgb_573c_landlord")
    trace.step(
        f"The earliest end a notice with a notice period can have: {fmt_date(end)}", end, "bgb_573c_landlord"
    )
    trace.soft(NEXT_END_WARNING)
    due = notice_objection_deadline(end)
    trace.step(f"Two months before that, the objection must arrive by {fmt_date(due)}", due, "bgb_574b")
    safe = _safe_date(trace, due, region, backward=True)
    send_by = plan_send_by(trace, ctx.today, safe, region=region, buffer=buffer)
    if due < ctx.today:
        trace.warnings.append(LATE_NOTICE_OBJECTION)
    summary = (
        f"If the notice ends your tenancy at the earliest date the law allows ({fmt_date(end)}), your objection "
        f"must reach the landlord by {fmt_date(due)}."
    )
    return _receipt(trace, ctx, due=due, summary=summary, send_by=send_by, safe_date=safe, region=region)


def _notice_objection(spec: DateSpec, ctx: RuleContext, trace: Trace, buffer: int) -> ComputationReceipt:
    if spec.anchor != "explicit_date" and _NEXT_END.search(f"{spec.legal_basis or ''} {spec.text}"):
        return _objection_before_next_end(spec, ctx, trace, buffer)
    region = calendar_de.normalize_region(ctx.region)
    end = parse_date(spec.anchor_date) if spec.anchor == "explicit_date" else None
    end = end or ctx.end_date
    written = _written_date(spec)
    if end is None:
        if written is None:
            return _no_date(trace, ctx, "We need the day the tenancy ends to count back two months.")
        trace.step(f"The date given is {fmt_date(written)}", written, "bgb_574b")
        trace.soft("We don't know when the tenancy ends, so we used the letter's date as written.")
        safe = _safe_date(trace, written, region, backward=True)
        send_by = plan_send_by(trace, ctx.today, safe, region=region, buffer=buffer)
        summary = f"Your objection must reach the landlord by {fmt_date(written)}."
        return _receipt(
            trace, ctx, due=written, summary=summary, send_by=send_by, safe_date=safe, region=region
        )
    due = notice_objection_deadline(end)
    trace.step(f"The tenancy ends on {fmt_date(end)}", end, "bgb_574b")
    _check_end(trace, ctx, end, "tenancy")
    trace.step(f"Two months before that, the objection must arrive by {fmt_date(due)}", due, "bgb_574b")
    if written is not None and written < due:
        _note_letter_date(trace, written, due, keep="we show the earlier")
        due = written
    elif written is not None and written > due:
        _later_letter_date(trace, written, due)
    safe = _safe_date(trace, due, region, backward=True)
    send_by = plan_send_by(trace, ctx.today, safe, region=region, buffer=buffer)
    if due < ctx.today:
        trace.warnings.append(LATE_NOTICE_OBJECTION)
    summary = (
        f"Your objection must reach the landlord by {fmt_date(due)}, two months before the tenancy ends."
    )
    return _receipt(trace, ctx, due=due, summary=summary, send_by=send_by, safe_date=safe, region=region)


def _stated_period(spec: DateSpec, start: date, legal: date, region: str | None, trace: Trace) -> date | None:
    """The end of a withdrawal period the letter states when it isn't the law's 14 days (a shop may
    grant more, e.g. 14 Werktage; a shorter one doesn't count against the consumer), after the § 193
    shift."""
    if (
        spec.amount is None
        or spec.unit is None
        or _same_period((spec.amount, spec.unit), (WITHDRAWAL_DAYS, "days"))
    ):
        return None
    if spec.amount <= 0:
        return None
    # working days (Werktage) count without a regional holiday we can't place: the earlier day
    raw, _ = add_period(start, spec.amount, spec.unit, region=region)
    stated, _ = shift_to_business_day(raw, region, "bgb_193")
    if stated == legal:
        return None  # another way of writing the same day (10 working days, two weeks)
    period = fmt_period(spec.amount, spec.unit)
    if stated > legal:
        trace.soft(
            f"The letter gives you {period} (until {fmt_date(stated)}), longer than the 14 days of § 355 BGB "
            f"(until {fmt_date(legal)}). A longer period counts — the seller may grant it, and some contracts "
            "have one by law (life insurance: 30 days, § 152 VVG); keep the letter as proof. We show the earlier "
            "date while it lasts."
        )
    else:
        trace.soft(
            f"The letter says {period} (until {fmt_date(stated)}), but § 355 BGB gives 14 days (until "
            f"{fmt_date(legal)}) — a shorter period doesn't count against you. We show the earlier date while it "
            "lasts."
        )
    return stated


def _withdrawal(spec: DateSpec, ctx: RuleContext, trace: Trace, buffer: int) -> ComputationReceipt:
    region = calendar_de.normalize_region(ctx.recipient_region)
    trace.cite.update(_BGB_COUNTING)  # a consumer's period counts under the BGB alone (review round 4)
    written = _written_date(spec)
    anchor = _resolve_anchor(spec, ctx, trace) if spec.type == "relative" else None
    stated: date | None = None
    if anchor is None:
        if written is None:
            return _receipt(
                trace, ctx, due=None, summary="No date could be computed: the start date is missing."
            )
        start, raw = None, written
        trace.step(f"The date given is {fmt_date(written)}", written, "bgb_355")
    else:
        start, raw = anchor.day, withdrawal_end(anchor.day)
        trace.step(f"Counting starts the day after {fmt_date(start)}", start, "bgb_187_1")
        trace.step(f"{WITHDRAWAL_DAYS} days later: {fmt_date(raw)}", raw, "bgb_355")
        if spec.anchor != "receipt":
            trace.warnings.append(
                "For goods the 14 days only start when they arrive (the last item of a split delivery) — "
                "if they came later, you have longer."
            )
    due, steps = shift_to_business_day(raw, region, "bgb_193")
    trace.extend(steps)
    if start is not None:
        stated = _stated_period(spec, start, due, region, trace)
    later = max(due, stated) if stated is not None else None
    due = min(due, stated) if stated is not None else due
    if region is None:
        check_regional_holidays(trace, [due])
    if later is not None and due < ctx.today:
        if later >= ctx.today:
            trace.warnings.append(
                f"The earlier date ({fmt_date(due)}) has passed, but you can still withdraw until {fmt_date(later)}."
            )
        due = later
    send_by: date | None = due
    if due < ctx.today:
        trace.warnings.append(
            f"This date ({fmt_date(due)}) has already passed. If you were never properly told about the right "
            "to withdraw, it may last up to 12 months and 14 days — get advice."
        )
        send_by = None
    else:
        trace.step(
            f"Sending the withdrawal by {fmt_date(due)} is enough — it doesn't have to arrive by then",
            due,
            "bgb_355",
        )
    first = f"counted from {fmt_date(start)}, " if start else ""
    summary = f"You can withdraw until {fmt_date(due)} ({first}sending it in time is enough)."
    return _receipt(trace, ctx, due=due, summary=summary, send_by=send_by, region=region)


_RULES: dict[str, _Compute] = {
    "sgb3_38": _registration,
    "bgb_558b": _rent_increase,
    "bgb_574b": _notice_objection,
    "bgb_355": _withdrawal,
}


def compute_letter_date(
    rule_id: str, spec: DateSpec, ctx: RuleContext, trace: Trace, postal_buffer_days: int
) -> ComputationReceipt:
    """The receipt of ``spec`` under the letter rule ``rule_id`` (one of :data:`_RULES`)."""
    return _RULES[rule_id](spec, ctx, trace, postal_buffer_days)
