"""Dates of high-stakes letters that a plain period can't express (ADR 0002).

:mod:`ordnung.rules.routing` decides which dates come here; this module computes them into the same
receipts as :mod:`ordnung.rules.deadlines` (steps with citations, warnings, confidence):

=============  ==================================  ============================================  ===========================
Rule           Counts from                         Last day                                      Weekend or holiday
=============  ==================================  ============================================  ===========================
``sgb3_38``    the day the person learned the end  3 months before the end, or 3 days after      kept (registering online
               (the dismissal's arrival)           learning it when less time is left            works any day)
``bgb_558b``   the day the request arrived         end of the 2nd calendar month after           next working day (§ 193 BGB)
``bgb_574b``   the day the tenancy ends            2 months before (counted backwards)           never later; safe date
``bgb_355``    the contract, or the goods'         14 days later; sending in time is enough      next working day at the
               arrival                                                                            consumer's home (§ 193 BGB)
=============  ==================================  ============================================  ===========================

Arrival days follow the engine's policy (SPEC § 21): a day stated in the letter or confirmed by the
person counts; otherwise the letter's date, the earliest plausible day, with ``low`` confidence and
the question "when did it arrive?". When the letter also names its own date for one of these
deadlines and it differs from the law's, the receipt says so; for the rent increase the law's date
is shown (a landlord can't shorten it), for the others the earlier of the two.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from ordnung.models import ComputationReceipt, DateSpec
from ordnung.rules import calendar_de
from ordnung.rules.consumer import WITHDRAWAL_DAYS, withdrawal_end
from ordnung.rules.deadlines import (
    RuleContext,
    Trace,
    _no_date,
    _receipt,
    _resolve_anchor,
    _safe_date,
    check_regional_holidays,
    parse_date,
    plan_send_by,
)
from ordnung.rules.employment import registration_deadline
from ordnung.rules.explain import fmt_date, month_name
from ordnung.rules.periods import shift_to_business_day
from ordnung.rules.tenancy import consent_period, notice_objection_deadline

_Compute = Callable[[DateSpec, RuleContext, Trace, int], ComputationReceipt]


def _arrival(spec: DateSpec, ctx: RuleContext, trace: Trace) -> date | None:
    """The day the letter arrived: stated, confirmed, else its date (asking for the real one)."""
    as_receipt = spec.model_copy(
        update={"anchor": "receipt", "anchor_date": spec.anchor_date if spec.anchor == "receipt" else None}
    )
    anchor = _resolve_anchor(as_receipt, ctx, trace)
    return anchor.day if anchor else None


def _written_date(spec: DateSpec) -> date | None:
    return parse_date(spec.date) if spec.type == "fixed" else None


def _note_letter_date(trace: Trace, spec: DateSpec, legal: date, *, keep: str) -> None:
    written = _written_date(spec)
    if written is not None and written != legal:
        trace.warnings.append(
            f"The letter names {fmt_date(written)}; by law the date is {fmt_date(legal)} — {keep}."
        )


def _registration(spec: DateSpec, ctx: RuleContext, trace: Trace, buffer: int) -> ComputationReceipt:
    end = parse_date(spec.anchor_date) if spec.anchor == "explicit_date" else None
    end = end or ctx.end_date
    learned = _arrival(spec, ctx, trace)
    if learned is None:
        return _receipt(trace, ctx, due=None, summary="No date could be computed: the start date is missing.")
    due, basis = registration_deadline(learned, end)
    trace.step(f"You learned when the job ends on {fmt_date(learned)}", learned, "sgb3_38")
    if basis == "before_end" and end is not None:
        trace.step(
            f"The job ends on {fmt_date(end)}; three months before that is {fmt_date(due)}", due, "sgb3_38"
        )
        why = f"three months before the job ends on {fmt_date(end)}"
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
    if not calendar_de.is_business_day(due, None):
        trace.warnings.append(
            f"{fmt_date(due)} is not a working day. The deadline may run to the next working day "
            "(§ 26 Abs. 3 SGB X), but registering online or by phone works on any day — do it in time."
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
    _note_letter_date(trace, spec, due, keep="a landlord can't shorten the time you have to decide")
    send_by = plan_send_by(trace, ctx.today, due, region=region, buffer=buffer)
    summary = (
        f"You have until {fmt_date(due)} to decide whether to agree; if you agree, the higher rent is owed "
        f"from {fmt_date(rent_from)}."
    )
    return _receipt(trace, ctx, due=due, summary=summary, send_by=send_by, region=region)


def _notice_objection(spec: DateSpec, ctx: RuleContext, trace: Trace, buffer: int) -> ComputationReceipt:
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
    trace.step(f"Two months before that, the objection must arrive by {fmt_date(due)}", due, "bgb_574b")
    if written is not None and written < due:
        _note_letter_date(trace, spec, due, keep="we show the earlier")
        due = written
    safe = _safe_date(trace, due, region, backward=True)
    send_by = plan_send_by(trace, ctx.today, safe, region=region, buffer=buffer)
    summary = (
        f"Your objection must reach the landlord by {fmt_date(due)}, two months before the tenancy ends."
    )
    return _receipt(trace, ctx, due=due, summary=summary, send_by=send_by, safe_date=safe, region=region)


def _withdrawal(spec: DateSpec, ctx: RuleContext, trace: Trace, buffer: int) -> ComputationReceipt:
    region = calendar_de.normalize_region(ctx.recipient_region)
    written = _written_date(spec)
    anchor = _resolve_anchor(spec, ctx, trace) if spec.type == "relative" else None
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
    if region is None:
        check_regional_holidays(trace, [due])
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
    "bgb_558b": _consent,
    "bgb_574b": _notice_objection,
    "bgb_355": _withdrawal,
}


def compute_letter_date(
    rule_id: str, spec: DateSpec, ctx: RuleContext, trace: Trace, postal_buffer_days: int
) -> ComputationReceipt:
    """The receipt of ``spec`` under the letter rule ``rule_id`` (one of :data:`_RULES`)."""
    return _RULES[rule_id](spec, ctx, trace, postal_buffer_days)
