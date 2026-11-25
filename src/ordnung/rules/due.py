"""Compute the date a :class:`~ordnung.models.DateSpec` describes: the way in to both kinds of date rule.

:func:`compute_due` sends a high-stakes letter's date to :mod:`ordnung.rules.letters`
(:mod:`ordnung.rules.routing` decides which) and every other date to the period pipeline in
:mod:`ordnung.rules.deadlines`. It sits above both because the letter rules build on the deadline
receipts: the deadline pipeline never imports the letter rules, so the two are not one import cycle.
"""

from __future__ import annotations

from ordnung.models import ComputationReceipt, ComputationStep, DateSpec
from ordnung.rules import catalog, routing
from ordnung.rules.deadlines import (
    POSTAL_BUFFER_DAYS,
    RuleContext,
    Trace,
    _compute_fixed,
    _compute_relative,
    _court_notes,
    _no_date,
    _receipt,
)
from ordnung.rules.letters import compute_letter_date


def compute_due(
    spec: DateSpec, ctx: RuleContext, *, postal_buffer_days: int = POSTAL_BUFFER_DAYS
) -> ComputationReceipt:
    """Compute the date a :class:`DateSpec` describes, with steps, citations and a plain summary.

    * ``none`` → no date.
    * ``fixed`` → the date as written; moved to the next business day only when
      ``shift_rule == "next_business_day"`` (never for appointments or notice deadlines).
    * ``relative`` → anchor (document date, deemed delivery, confirmed receipt, explicit date or
      today) → optional deemed delivery → period → shift for objection/payment/declaration
      deadlines (unless ``shift_rule == "none"``); notice deadlines never shift but get a safe date.
      A negative ``amount`` counts backwards ("2 weeks before …"); such a deadline never moves to a
      later day either (it gets a safe date instead).

    ``send_by`` is set for objection, payment, declaration and notice deadlines: the due date minus
    ``postal_buffer_days`` business days (one business day for payments by bank transfer), never
    before ``ctx.today``; ``None`` if the due date has passed. Periods longer than
    :data:`MAX_PERIOD` and dates outside the calendar give a "no date" receipt, never an exception.
    """
    trace = Trace()
    if spec.type == "none":
        return _receipt(trace, ctx, due=None, summary="This letter doesn't set a date.", region=ctx.region)
    if ctx.country != "DE":
        trace.hard(
            f"Ordnung only knows German rules; this date was computed as if the letter were German ({ctx.country})."
        )
    try:
        _court_notes(trace, spec, ctx)
        special = routing.special_rule(
            spec, ctx.letter_kind, authority=ctx.delivery_scope is not None or ctx.court
        )
        if special is not None:
            return compute_letter_date(special, spec, ctx, trace, postal_buffer_days)
        if spec.type == "fixed":
            return _compute_fixed(spec, ctx, trace, postal_buffer_days)
        return _compute_relative(spec, ctx, trace, postal_buffer_days)
    except (OverflowError, ValueError):  # a misread date or period near the ends of the calendar
        return _no_date(Trace(), ctx, "The dates in the letter are out of range — please check them.")


def compute_one_year_fallback(spec: DateSpec, ctx: RuleContext) -> ComputationReceipt:
    """Outer limit if the instructions on how to object were missing or wrong (one year).

    § 356 Abs. 2 AO, § 58 Abs. 2 VwGO (with § 70 Abs. 2 VwGO), § 66 Abs. 2 SGG. Counted from the same
    delivery day as the regular deadline. Whether the instructions are really wrong is a legal
    judgement, so the result always has ``low`` confidence and is meant to be shown only as a
    warning. Do not use it for fines or penal orders (OWiG and StPO have no one-year rule).
    """
    one_year = spec.model_copy(
        update={
            "type": "relative",
            "amount": 1,
            "unit": "years",
            "nature": "objection",
            "shift_rule": "auto",
            "legal_basis": None,
            "text": "",
        }
    )
    receipt = compute_due(one_year, ctx)
    receipt.rule_ids.append("rbb_one_year")
    receipt.steps.append(
        ComputationStep(
            label="One year applies only if the instructions on how to object were missing or wrong",
            date=receipt.due_date,
            rule_id="rbb_one_year",
            citation=catalog.citation("rbb_one_year"),
        )
    )
    receipt.warnings.insert(
        0,
        "Only if the instructions on how to object (Rechtsbehelfsbelehrung) were missing or wrong — "
        "get advice before relying on this date.",
    )
    receipt.confidence = "low"
    if receipt.due_date:
        receipt.summary = (
            f"If the instructions on how to object were missing or wrong: {receipt.summary[:1].lower()}"
            f"{receipt.summary[1:]}"
        )
    return receipt
