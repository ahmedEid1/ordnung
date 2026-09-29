"""Contract deadlines: when a cancellation must *arrive*, when to send it and when the contract ends.

``compute_contract`` dispatches on a :data:`~ordnung.models.ContractRegime` derived by code
(:func:`regime_for`) from the category, the other party's kind and the dates (SPEC § 21):

* ``bgb309_new`` — consumer contracts concluded from 1 March 2022 (§ 309 Nr. 9 BGB): first term ≤ 2
  years with ≤ 1 month's notice; afterwards indefinite, cancellable any day with ≤ 1 month's notice.
* ``bgb309_old`` — consumer contracts concluded before: first term ≤ 2 years, renewals ≤ 1 year,
  notice ≤ 3 months.
* ``tkg56`` — phone/internet (§ 56 TKG): after the minimum term, one month's notice any day.
* ``vvg11`` — insurance (§ 11 VVG): yearly renewal, 1–3 months' notice before the insurance year ends;
  terms over three years can be left at the end of year 3 and every later year with three months'
  notice (§ 11 Abs. 4 VVG).
* ``sgbv175`` — statutory health insurance (§ 175 Abs. 4 SGB V): 12-month lock-in, then to the end
  of the second month after the month of notice.
* ``stromgvv20`` — basic energy supply (§ 20 StromGVV/GasGVV): two weeks' notice any day.
* ``rent573c`` — tenant (§ 573c BGB): notice by the 3rd *Werktag* of a month ends the lease at the
  end of the month after next. Saturday counts as a Werktag (BGH VIII ZR 206/04); if the 3rd Werktag
  is a Saturday the Saturday is kept (the BGH left a § 193 BGB extension open — safety policy).
* ``employment622`` — employee (§ 622 BGB): four weeks to the 15th or the end of a month.
* ``bgb675h`` — a consumer's current account its terms say can be ended any time (§ 675h Abs. 1 BGB): without
  notice unless one was agreed, at most one month.
* ``as_written`` — anything else: the written terms, with low confidence.

Notice deadlines never move off weekends or holidays (BGH III ZR 172/04); ``safe_date`` is the last
business day on or before ``cancel_by``. ``cancel_by`` is the last day the cancellation must arrive
to reach ``earliest_exit``; it is ``None`` when the contract can be ended any day with a fixed notice
period (the exit then simply moves day by day). ``next_renewal`` is the day the contract continues
if nobody cancels in time; ``None`` means nothing locks you in.

``ContractTerms.renewal_term_months == 0`` means "continues indefinitely after the first term" (the
extraction prompt's convention): such a contract never ends by itself and, after its first term, can
be ended any day with its notice period.

Two terms a notice period can't say (policies in :func:`_notice_day`, :func:`_ends_by_itself` and
:func:`_plan_employment`):

* ``notice_day`` — the contract's own month-end rule, "by the 10th of a month, to the end of that month".
  It is read for ``bgb309_new``, ``tkg56``, ``bgb309_old`` and ``as_written`` when the basis is the end
  of a month. The deadline is that day of the month the contract is to end in (the 29th–31st: a shorter
  month's last day); a notice period the contract states too applies as well, and the earlier deadline
  decides (the person's own notice terms replace the day: the API clears it when they are saved without
  one). The day asks for less than a month before the month's end; after a first term the law may allow
  one month from arrival instead, which a warning names when it would end the contract sooner. With an
  end date, the day means the contract needs notice (:func:`_ends_by_itself`); a first term still running
  is left by the day of its last month.
* ``notice_before_end`` — a fixed-term job whose contract lets it be ended earlier by ordinary notice
  (§ 15 Abs. 4 TzBfG): while its end date is ahead, the job is planned like an open-ended one, with at
  least § 622 Abs. 1 BGB's notice, and ends by itself on that date if the notice can't end it sooner.
  Read for a job only.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import Final, Literal

from ordnung.models import (
    ComputationReceipt,
    ContractCategory,
    ContractComputation,
    ContractRegime,
    ContractTerms,
    NoticeUnit,
)
from ordnung.rules import calendar_de, catalog
from ordnung.rules.deadlines import (
    POSTAL_BUFFER_DAYS,
    RuleContext,
    Trace,
    check_partial_holidays,
    check_regional_holidays,
    parse_date,
    plan_send_by,
)
from ordnung.rules.explain import (
    contract_closed_sentence,
    contract_exit_sentence,
    contract_fixed_end_sentence,
    contract_open_sentence,
    contract_term_sentence,
    fmt_date,
    fmt_period,
    month_name,
    notice_phrase,
    ordinal,
)
from ordnung.rules.periods import add_months, add_period, days_in_month, latest_receipt_for

SendChannelKind = Literal[
    "online_button", "email", "fax", "letter", "registered_letter", "in_person", "portal"
]

#: First conclusion day under the new § 309 Nr. 9 BGB (Art. 229 § 60 EGBGB).
NEW_CONSUMER_LAW_FROM: Final = date(2022, 3, 1)

_SAME_DAY_CHANNELS = ("email", "fax", "portal", "in_person")
_SIGNED_LETTER_CHANNELS = ("letter", "registered_letter", "in_person")

_REGIME_RULE: dict[ContractRegime, str] = {
    "bgb309_new": "bgb_309_9_new",
    "bgb309_old": "bgb_309_9_old",
    "tkg56": "tkg_56",
    "vvg11": "vvg_11",
    "sgbv175": "sgbv_175",
    "stromgvv20": "stromgvv_20",
    "rent573c": "bgb_573c",
    "employment622": "bgb_622",
    "bgb675h": "bgb_675h",
    "as_written": "contract_as_written",
}

_REGIME_NOTE: dict[ContractRegime, str] = {
    "bgb309_new": "After the first term the contract only continues indefinitely, and you can then cancel "
    "any day with at most one month's notice (§ 309 Nr. 9 BGB).",
    "bgb309_old": "For contracts from before March 2022, renewals of up to a year and notice of up to three "
    "months are allowed (§ 309 Nr. 9 BGB, old version).",
    "tkg56": "After the minimum term you can cancel any day with one month's notice, at no cost "
    "(§ 56 Abs. 3, 4 TKG).",
    "vvg11": "Insurance renews for at most a year at a time; notice must be 1–3 months before the insurance "
    "year ends (§ 11 VVG).",
    "sgbv175": "Switching insurer? Just join the new one: its notice to your current insurer replaces your "
    "own cancellation (§ 175 Abs. 2, 4 SGB V).",
    "stromgvv20": "Text form (e.g. email) is enough; you need a new supplier from the end date "
    "(§ 20 StromGVV/GasGVV).",
    "rent573c": "Notice on a flat needs a hand-signed letter; email or fax is not valid (§ 568 BGB).",
    "employment622": "Notice of employment needs a hand-signed letter; email is not valid (§ 623 BGB).",
    "bgb675h": "A current account can be closed any time; a notice period of more than a month is void "
    "(§ 675h Abs. 1 BGB). Move your standing orders and direct debits first — the bank must help you switch "
    "(§ 20 ZKG).",
    "as_written": "These dates follow the contract's own terms — please check them against the contract.",
}


@dataclass(frozen=True)
class Notice:
    """A notice period, e.g. one month or two weeks."""

    amount: int
    unit: NoticeUnit

    @property
    def text(self) -> str:
        """``one month``, ``2 weeks`` …"""
        return fmt_period(self.amount, self.unit)

    @property
    def phrase(self) -> str:
        """``one month's notice``, ``2 weeks' notice`` …"""
        return notice_phrase(self.text)

    def deadline(self, end: date) -> date:
        """Last day notice can arrive for the contract to end at the end of ``end``."""
        return latest_receipt_for(end, self.amount, self.unit)

    def exit_after(self, arrival: date) -> date:
        """Last day of the contract when notice arrives on ``arrival``."""
        return add_period(arrival, self.amount, self.unit)[0]


#: No notice at all: a current account (§ 675h Abs. 1 BGB, :func:`_payment_account`).
NO_NOTICE: Final = Notice(0, "days")
ONE_MONTH: Final = Notice(1, "months")
THREE_MONTHS: Final = Notice(3, "months")
TWO_WEEKS: Final = Notice(2, "weeks")
FOUR_WEEKS: Final = Notice(4, "weeks")


@dataclass(frozen=True)
class DayOfMonth:
    """A contract's own month-end rule (``ContractTerms.notice_day``): a cancellation that arrives by ``day``
    of a month ends the contract at the end of that month ("bis zum 10. eines Monats zum Monatsende"). A
    notice period the contract states too (``notice``, as the regime limits it) applies as well: the earlier
    deadline decides."""

    day: int
    notice: Notice | None = None

    @property
    def text(self) -> str:
        """``the 10th of the month``; with a notice period too, ``10 days' notice by the 10th of the month``"""
        by_day = f"the {ordinal(self.day)} of the month"
        return f"{self.notice.phrase} by {by_day}" if self.notice else by_day

    @property
    def phrase(self) -> str:
        """``notice by the 10th of the month``, ``10 days' notice by the 10th of the month``"""
        return self.text if self.notice else f"notice by {self.text}"

    def deadline(self, end: date) -> date:
        """Last day notice can arrive for the contract to end at the end of ``end``: ``day`` of ``end``'s month,
        or of the month before when ``end`` comes first (the 29th–31st: a shorter month's last day) — or the
        notice period's deadline, when that comes first."""
        on = end.replace(day=min(self.day, days_in_month(end.year, end.month)))
        if on > end:
            before = end_of_month(end.year, end.month - 1)
            on = before.replace(day=min(self.day, before.day))
        return min(on, self.notice.deadline(end)) if self.notice else on


@dataclass
class _Plan:
    """What a regime planner found; ``compute_contract`` turns it into a ContractComputation."""

    kind: Literal["term", "open", "exit", "none"]
    earliest_exit: date | None = None
    cancel_by: date | None = None
    current_term_end: date | None = None
    next_renewal: date | None = None
    arrival: date | None = None
    notice: Notice | None = None
    missed: date | None = None
    renews: bool = True
    detail: str | None = None
    reason: str = ""
    #: A fixed-term job's end date: it ends by itself then if no notice ends it sooner.
    fixed_end: date | None = None


@dataclass(frozen=True)
class _Inputs:
    terms: ContractTerms
    today: date
    region: str | None
    arrival: date
    start: date | None
    end: date | None
    origin: date | None


def contract_origin(terms: ContractTerms) -> date | None:
    """Day the contract arose: ``concluded_date``, else ``start_date`` (``None`` if both are missing)."""
    return parse_date(terms.concluded_date) or parse_date(terms.start_date)


def regime_for(terms: ContractTerms) -> ContractRegime:
    """Which cancellation regime applies, derived by code from category, party kind and dates."""
    if terms.category == "rent":
        return "rent573c"
    if terms.category == "employment":
        return "employment622"
    if terms.category in ("energy", "gas") and terms.is_basic_supply:
        return "stromgvv20"
    if terms.category == "insurance":
        return "sgbv175" if terms.party_kind == "health_insurer" else "vvg11"
    if terms.category == "bank" and terms.is_consumer and terms.notice_basis == "any_time":
        # a current account ("jederzeit kündigen"): a payment services framework contract (§ 675h BGB) —
        # other bank contracts (savings, loans, deposits) follow their terms (walkthrough of phase 2)
        return "bgb675h"
    if not terms.is_consumer or terms.category == "bank":
        return "as_written"
    if terms.category in ("mobile", "internet"):
        return "tkg56"
    origin = contract_origin(terms)
    if origin is None:
        return "as_written"
    return "bgb309_new" if origin >= NEW_CONSUMER_LAW_FROM else "bgb309_old"


def term_end(start: date, months: int) -> date:
    """Last day of a term of ``months`` that starts at the beginning of ``start`` (§§ 187 II, 188 II BGB)."""
    return add_period(start, months, "months", mode="day_start")[0]


def end_of_month(year: int, month: int) -> date:
    """Last day of ``month`` in ``year``; months beyond 12 roll into the following years."""
    year, month = year + (month - 1) // 12, (month - 1) % 12 + 1
    return date(year, month, days_in_month(year, month))


def third_werktag(year: int, month: int, region: str | None) -> date:
    """3rd *Werktag* (Mon–Sat, not a public holiday) of a month — the § 573c BGB grace period."""
    return calendar_de.add_werktage(date(year, month, 1) - timedelta(days=1), 3, region)


def _written_notice(terms: ContractTerms) -> Notice | None:
    if terms.notice_value is None or terms.notice_unit is None:
        return None
    return Notice(terms.notice_value, terms.notice_unit)


def _notice_day(terms: ContractTerms) -> DayOfMonth | None:
    """The contract's day of the month for notice, when its basis is the end of a month — with the notice
    period it states too, if any: both apply, so the earlier deadline decides. Neither wins over the other,
    since a misreading can put either in the other's place ("bis zum 10." read as 10 days' notice); the
    person's own notice terms replace the day in the data instead, unless they give one too
    (``api/routes/contracts.py``)."""
    if terms.notice_day is None or terms.notice_basis != "end_of_month":
        return None
    return DayOfMonth(terms.notice_day, _written_notice(terms))


def _shorter(a: Notice, b: Notice, reference: date) -> Notice:
    """The shorter of two notice periods (the one whose deadline for ``reference`` is later)."""
    return a if a.deadline(reference) >= b.deadline(reference) else b


def _limit(
    trace: Trace, written: Notice, cap: Notice, reference: date, rule_id: str, *, term_end_day: bool
) -> Notice:
    """``written`` limited by the statutory maximum ``cap`` (with a warning when it is longer)."""
    notice = _shorter(written, cap, reference)
    if notice != written:
        advice = (
            f" Cancelling by {fmt_date(written.deadline(reference))}, as the contract says, avoids any argument."
            if term_end_day
            else ""
        )
        trace.warnings.append(
            f"Your contract asks for {notice_phrase(written.text)}, but the law allows at most {cap.text} "
            f"({catalog.citation(rule_id)}), so we used {cap.text}.{advice}"
        )
    return notice


#: The web's contract card reads this warning's start (``NOTICE_ASSUMED`` in ``web/src/features/contracts/model.ts``)
#: to ask "Please check" and offer "Add notice period".
_MISSING_NOTICE = (
    "The contract's notice period wasn't found; we assumed the longest the law allows, which gives the "
    "earliest date."
)


def _capped_notice(trace: Trace, terms: ContractTerms, cap: Notice, reference: date, rule_id: str) -> Notice:
    """Written notice limited by a statutory maximum; the maximum when the contract states none."""
    written = _written_notice(terms)
    if written is None:
        trace.soft(_MISSING_NOTICE)
        return cap
    return _limit(trace, written, cap, reference, rule_id, term_end_day=True)


def _first_reachable(candidates: Iterator[tuple[date, date]], today: date) -> tuple[date, date]:
    """First ``(exit, deadline)`` pair whose deadline has not passed (candidates grow without bound)."""
    return next((exit_day, deadline) for exit_day, deadline in candidates if deadline >= today)


def _term_chain(first_end: date, renewal_months: int, notice: Notice) -> Iterator[tuple[date, date]]:
    end = first_end
    while True:
        yield end, notice.deadline(end)
        end = term_end(end + timedelta(days=1), renewal_months)


def _deadline_step(trace: Trace, exit_day: date, notice: Notice | DayOfMonth, deadline: date) -> None:
    trace.step(
        f"To end the contract on {fmt_date(exit_day)} with {notice.phrase}, it must arrive by {fmt_date(deadline)}",
        deadline,
        "bgb_188" if isinstance(notice, Notice) else "contract_as_written",
    )


def _plan_chain(
    trace: Trace, inp: _Inputs, first_end: date, renewal_months: int, notice: Notice, *, renews: bool
) -> _Plan:
    """Fixed terms that renew: the first term end whose notice deadline is still ahead."""
    exit_day, deadline = _first_reachable(_term_chain(first_end, renewal_months, notice), inp.today)
    current = next(end for end, _ in _term_chain(first_end, renewal_months, notice) if end >= inp.today)
    plan = _Plan(
        "term",
        earliest_exit=exit_day,
        cancel_by=deadline,
        current_term_end=current,
        next_renewal=current + timedelta(days=1),
        renews=renews,
    )
    if current != exit_day:
        plan.missed = notice.deadline(current)
        trace.step(
            f"The deadline for the term ending {fmt_date(current)} was {fmt_date(plan.missed)}",
            plan.missed,
            "notice_no_shift",
        )
    _deadline_step(trace, exit_day, notice, deadline)
    return plan


def _plan_open(trace: Trace, inp: _Inputs, notice: Notice, *, minimum_term_end: date | None = None) -> _Plan:
    """Contracts that can be ended any day with ``notice`` (counted from the expected arrival).

    With a ``minimum_term_end`` still running, the notice is counted from arrival (the consumer-friendly
    reading), but never ends on or before the minimum term's end; the provider-friendly reading —
    counting only after the minimum term — is shown as a warning (legal research verdict on § 56 TKG).
    """
    exit_day = notice.exit_after(inp.arrival)
    trace.step(
        f"If it arrives by {fmt_date(inp.arrival)}, the contract ends {notice.text} later, on {fmt_date(exit_day)}",
        exit_day,
        "bgb_188",
    )
    running = minimum_term_end if minimum_term_end and minimum_term_end >= inp.today else None
    if running is not None:
        after_term = notice.exit_after(running + timedelta(days=1))
        if exit_day <= running:
            trace.soft(
                f"Counted from arrival, the notice would end inside the minimum term, so we used "
                f"{fmt_date(after_term)} — get advice if an earlier end matters."
            )
            exit_day = after_term
        else:
            trace.warnings.append(
                f"Some providers count the notice only from the end of the minimum term; then the contract "
                f"would end on {fmt_date(after_term)}."
            )
    return _Plan(
        "open",
        earliest_exit=exit_day,
        arrival=inp.arrival,
        notice=notice,
        current_term_end=running,
        next_renewal=running + timedelta(days=1) if running else None,
    )


def _plan_month_ends(trace: Trace, inp: _Inputs, notice: Notice | DayOfMonth) -> _Plan:
    """Contracts that can be ended at the end of any month with ``notice`` (or by the contract's day of it)."""

    def candidates() -> Iterator[tuple[date, date]]:
        month = inp.today.month
        while True:
            end = end_of_month(inp.today.year, month)
            yield end, notice.deadline(end)
            month += 1

    exit_day, deadline = _first_reachable(candidates(), inp.today)
    _deadline_step(trace, exit_day, notice, deadline)
    detail = f"{notice.text}, as the contract says" if isinstance(notice, DayOfMonth) else None
    return _Plan("exit", earliest_exit=exit_day, cancel_by=deadline, detail=detail)


def _unknown(trace: Trace, reason: str) -> _Plan:
    trace.hard(reason)
    return _Plan("none", reason=reason)


# ---------------------------------------------------------------------------------------- regimes


def _initial_end(trace: Trace, inp: _Inputs, max_months: int | None) -> date | None:
    """End of the first term: the end date, else start + term (capped at ``max_months`` with a warning)."""
    months = inp.terms.initial_term_months
    if inp.end is not None:
        return inp.end
    if inp.start is None or months is None:
        return None
    if max_months is not None and months > max_months:
        trace.soft(
            f"A first term of {months} months is longer than the law allows ({max_months}); we used "
            f"{max_months} months, which gives the earlier date — get advice if it matters."
        )
        months = max_months
    end = term_end(inp.start, months)
    trace.step(f"The first term runs from {fmt_date(inp.start)} to {fmt_date(end)}", end, "bgb_187_2")
    return end


def _plan_first_term(
    trace: Trace,
    inp: _Inputs,
    first_end: date,
    notice: Notice | DayOfMonth,
    after: Callable[[date | None], _Plan],
) -> _Plan:
    """A first term ending ``first_end`` (left with ``notice``), then indefinite: ``after`` plans that part,
    given the first term's end while it still runs (its deadline has passed), else ``None``."""
    if first_end < inp.today:
        return after(None)
    deadline = notice.deadline(first_end)
    if deadline < inp.today:
        trace.step(
            f"The deadline to leave when the first term ends was {fmt_date(deadline)}",
            deadline,
            "notice_no_shift",
        )
        return after(first_end)
    _deadline_step(trace, first_end, notice, deadline)
    return _Plan(
        "term",
        earliest_exit=first_end,
        cancel_by=deadline,
        current_term_end=first_end,
        next_renewal=first_end + timedelta(days=1),
        renews=False,
    )


def _plan_month_day(trace: Trace, inp: _Inputs, day: DayOfMonth, rule_id: str) -> _Plan:
    """``bgb309_new`` and ``tkg56`` after the first term (or without one): the contract's own day of the month
    (with its notice period too, limited to one month).

    It asks for less than a month before the month's end, so its dates stand. Where the contract continued
    after a fixed first term, the law may instead let a cancellation end it one month after it arrives — not
    settled for a contract open-ended from the start — so the dates keep the contract's own rule, and a
    hedged warning names the end one month after arrival when that would come sooner."""
    plan = _plan_month_ends(trace, inp, day)
    sooner = ONE_MONTH.exit_after(inp.arrival)
    if plan.earliest_exit is not None and sooner < plan.earliest_exit:
        trace.warnings.append(
            f"If the contract continued after a fixed first term, the law may let a cancellation that arrives "
            f"by {fmt_date(inp.arrival)} end it one month later, on {fmt_date(sooner)} "
            f"({catalog.citation(rule_id)}); the contract's date avoids any argument."
        )
    return plan


def _plan_minimum_term(trace: Trace, inp: _Inputs, regime: ContractRegime) -> _Plan:
    """``bgb309_new`` and ``tkg56``: a first term, then indefinite with ≤ 1 month's notice any day — or at a
    month's end by the contract's own day of the month (:func:`_notice_day`, :func:`_plan_month_day`)."""
    old_contract = inp.origin is not None and inp.origin < NEW_CONSUMER_LAW_FROM
    cap, cap_rule = (THREE_MONTHS, "bgb_309_9_old") if old_contract else (ONE_MONTH, "bgb_309_9_new")
    rule_id = _REGIME_RULE[regime]
    if inp.terms.renewal_term_months:
        trace.warnings.append(
            f"The contract mentions renewals of {inp.terms.renewal_term_months} months; by law it only "
            f"continues indefinitely after the first term ({catalog.citation(rule_id)})."
        )
    written = _written_notice(inp.terms)
    day = _notice_day(inp.terms)
    if written is None and day is None:
        trace.soft(_MISSING_NOTICE)

    def after(running: date | None) -> _Plan:
        limited = (
            _limit(trace, written, ONE_MONTH, inp.today, rule_id, term_end_day=False) if written else None
        )
        if day is not None:  # a month whose day is still ahead ends after the first term: its day has passed
            return _plan_month_day(trace, inp, replace(day, notice=limited), rule_id)
        return _plan_open(trace, inp, limited or ONE_MONTH, minimum_term_end=running)

    first_end = _initial_end(trace, inp, 24)
    if first_end is None and inp.terms.initial_term_months:
        return _unknown(trace, "We need the start date to tell whether the minimum term is over.")
    if first_end is None or first_end < inp.today:
        return after(None)
    limited = _limit(trace, written, cap, first_end, cap_rule, term_end_day=True) if written else None
    if day is not None:
        return _plan_first_term(trace, inp, first_end, replace(day, notice=limited), after)
    return _plan_first_term(trace, inp, first_end, limited or cap, after)


def _renewing_notice(trace: Trace, inp: _Inputs, regime: ContractRegime, reference: date) -> Notice | None:
    if regime == "as_written":
        return _written_notice(inp.terms)
    return _capped_notice(trace, inp.terms, THREE_MONTHS, reference, _REGIME_RULE[regime])


def _insurance_first_end(trace: Trace, inp: _Inputs) -> tuple[date | None, bool]:
    """First insurance-year end for ``vvg11`` and whether it is the § 11 Abs. 4 VVG exit.

    A contract for more than three years (by its term or by its end date) can be left at the end of
    the third and every later year with three months' notice, so year 3 comes first. The start is
    derived from the end date and the term when only those are known.
    """
    months, start, end = inp.terms.initial_term_months, inp.start, inp.end
    if start is None and end is not None and months is not None:
        start = add_months(end + timedelta(days=1), -months)
    if start is not None and (
        (months is not None and months > 36) or (end is not None and end > term_end(start, 36))
    ):
        trace.warnings.append(
            "Insurance contracts longer than three years can be cancelled at the end of the third and every "
            "later year with three months' notice (§ 11 Abs. 4 VVG); the dates use that right."
        )
        third_year = term_end(start, 36)
        trace.step(f"The third insurance year ends {fmt_date(third_year)}", third_year, "vvg_11")
        return third_year, True
    if end is not None:
        return end, False
    if months is None:
        trace.soft("The insurance year wasn't found; we assumed it runs a year from the start date.")
        months = 12
    if start is None:
        return None, False
    first_end = term_end(start, months)
    trace.step(f"The first term runs from {fmt_date(start)} to {fmt_date(first_end)}", first_end, "bgb_187_2")
    return first_end, False


def _plan_payment_account(trace: Trace, inp: _Inputs) -> _Plan:
    """``bgb675h``: a current account can be ended any time — without notice unless one was agreed, and an
    agreed one counts for at most a month (§ 675h Abs. 1 BGB)."""
    written = _written_notice(inp.terms)
    if written is not None and written.amount > 0:
        return _plan_open(
            trace, inp, _limit(trace, written, ONE_MONTH, inp.today, "bgb_675h", term_end_day=False)
        )
    trace.step(
        f"A current account can be closed any time, without notice unless one was agreed: a cancellation that "
        f"arrives by {fmt_date(inp.arrival)} ends it then",
        inp.arrival,
        "bgb_675h",
    )
    return _Plan("open", earliest_exit=inp.arrival, arrival=inp.arrival, notice=NO_NOTICE)


def _plan_renewing_by_day(trace: Trace, inp: _Inputs, regime: ContractRegime, day: DayOfMonth) -> _Plan:
    """``bgb309_old`` and ``as_written`` by the contract's own day of the month (with its notice period too, as
    the regime limits it): at a month's end, once a first term still running has ended."""
    if day.notice is not None:
        day = replace(day, notice=_renewing_notice(trace, inp, regime, inp.today))
    first_end = _initial_end(trace, inp, 24 if regime == "bgb309_old" else None)
    if first_end is None or first_end < inp.today:
        return _plan_month_ends(trace, inp, day)
    # once the first term's deadline has passed, the next month end whose deadline is ahead lies beyond it
    return _plan_first_term(trace, inp, first_end, day, lambda _: _plan_month_ends(trace, inp, day))


def _plan_renewing(trace: Trace, inp: _Inputs, regime: ContractRegime) -> _Plan:
    """``bgb309_old``, ``vvg11`` and ``as_written``: fixed terms that renew."""
    terms = inp.terms
    if terms.notice_basis in ("any_time", "end_of_month") and regime != "vvg11":
        day = _notice_day(terms)
        if day is not None:
            return _plan_renewing_by_day(trace, inp, regime, day)
        notice = _renewing_notice(trace, inp, regime, inp.today)
        if notice is None:
            return _unknown(trace, "The contract's notice period is missing.")
        if terms.notice_basis == "any_time":
            return _plan_open(trace, inp, notice)
        return _plan_month_ends(trace, inp, notice)
    long_insurance = False
    if regime == "vvg11":
        first_end, long_insurance = _insurance_first_end(trace, inp)
    else:
        first_end = _initial_end(trace, inp, 24 if regime == "bgb309_old" else None)
    if first_end is None:
        return _unknown(trace, "We need the contract's start date and term to compute the deadline.")
    # § 11 Abs. 4 VVG: the exit after year 3 always takes three months' notice.
    notice = THREE_MONTHS if long_insurance else _renewing_notice(trace, inp, regime, first_end)
    if notice is None:
        return _unknown(trace, "The contract's notice period is missing.")
    renewal = 12 if long_insurance else terms.renewal_term_months
    if renewal == 0 and regime != "vvg11":
        return _plan_first_term(
            trace,
            inp,
            first_end,
            notice,
            lambda running: _plan_open(trace, inp, notice, minimum_term_end=running),
        )
    if regime == "as_written":
        if renewal is None:
            if notice.deadline(first_end) < inp.today:
                return _unknown(
                    trace, "The contract's renewal terms are missing, so the next deadline is unknown."
                )
            trace.warnings.append("We couldn't find how the contract continues after this term — check it.")
            return _plan_chain(trace, inp, first_end, 12, notice, renews=False)
        return _plan_chain(trace, inp, first_end, renewal, notice, renews=True)
    if renewal is None:
        trace.soft("The renewal period wasn't found; we assumed one year, the longest allowed.")
        renewal = 12
    elif renewal == 0:
        trace.soft(
            "The insurance continues indefinitely; it can then be cancelled for the end of each insurance "
            "period (§ 11 Abs. 2 VVG) — we assumed yearly periods (§ 12 VVG)."
        )
        renewal = 12
    elif renewal > 12:
        trace.soft(
            f"Renewals of {renewal} months are longer than the law allows (one year); we used one year — get "
            "advice if it matters."
        )
        renewal = 12
    return _plan_chain(trace, inp, first_end, renewal, notice, renews=True)


def _plan_health(trace: Trace, inp: _Inputs) -> _Plan:
    """``sgbv175``: 12-month lock-in, then the end of the second month after the month of notice."""
    lock_in = term_end(inp.start, 12) if inp.start else None
    if lock_in is None:
        trace.soft("The membership start wasn't found; the 12-month minimum membership may still apply.")
    else:
        trace.step(f"The 12-month minimum membership ends {fmt_date(lock_in)}", lock_in, "sgbv_175")

    def exit_for(month: int) -> date:
        # Membership ends at a month end; during the lock-in, at the end of the month it ends in.
        month_end = end_of_month(inp.today.year, month + 2)
        if lock_in is None or month_end >= lock_in:
            return month_end
        return end_of_month(lock_in.year, lock_in.month)

    month = inp.today.month
    exit_day = exit_for(month)
    while exit_for(month + 1) == exit_day:
        month += 1
    deadline = end_of_month(inp.today.year, month)
    trace.step(
        f"Notice given by {fmt_date(deadline)} ends the membership on {fmt_date(exit_day)}",
        exit_day,
        "sgbv_175",
    )
    return _Plan("exit", earliest_exit=exit_day, cancel_by=deadline)


def _plan_rent(trace: Trace, inp: _Inputs) -> _Plan:
    """``rent573c``: notice by the 3rd Werktag of a month → end of the month after next."""

    def candidates() -> Iterator[tuple[date, date]]:
        month = inp.today.month
        while True:
            first = end_of_month(inp.today.year, month).replace(day=1)
            yield end_of_month(inp.today.year, month + 2), third_werktag(first.year, first.month, inp.region)
            month += 1

    exit_day, deadline = _first_reachable(candidates(), inp.today)
    if inp.region is None:
        check_regional_holidays(trace, [deadline.replace(day=d) for d in range(1, deadline.day + 1)])
    trace.step(
        f"3rd working day (Mon–Sat) of {month_name(deadline)} {deadline.year}: {fmt_date(deadline)}",
        deadline,
        "unit_werktage",
    )
    trace.step(f"Notice received by then ends the lease on {fmt_date(exit_day)}", exit_day, "bgb_573c")
    if deadline.weekday() == 5:
        trace.warnings.append(
            f"The 3rd working day is a Saturday ({fmt_date(deadline)}). Some courts would accept the next "
            "Monday (§ 193 BGB), but the Federal Court of Justice left this open (VIII ZR 206/04), so we "
            "keep the Saturday."
        )
    if _written_notice(inp.terms) is not None:
        trace.warnings.append(
            "A tenant's notice period can't be longer than the law's (§ 573c Abs. 4 BGB), so we used the "
            "statutory one. Check your lease for an agreed minimum term (Kündigungsverzicht)."
        )
    return _Plan(
        "exit",
        earliest_exit=exit_day,
        cancel_by=deadline,
        detail=f"the 3rd working day of {month_name(deadline)}",
    )


def _plan_employment(trace: Trace, inp: _Inputs) -> _Plan:
    """``employment622``: four weeks to the 15th or the end of a month, or the written period.

    Before a fixed term's end (``notice_before_end``, :func:`_ends_by_itself`), § 622 Abs. 1 BGB is the floor:
    a notice period shorter than four weeks, or notice to any day, is usually the probation period's (§ 622
    Abs. 3 BGB), and after it a contract can rarely agree less (§ 622 Abs. 4, 5 BGB). So the notice is then at
    least four weeks, to the 15th or the end of a month (only the end of a month when the contract says so)."""
    notice = _written_notice(inp.terms)
    if notice is None:
        trace.soft(
            "No notice period found; we used the statutory four weeks (§ 622 Abs. 1 BGB) — check your contract "
            "or collective agreement for a longer one."
        )
        notice = FOUR_WEEKS
    basis = inp.terms.notice_basis
    if inp.end is not None:  # before a fixed term's end: § 622 Abs. 1 BGB at least
        shorter = notice.deadline(inp.end) > FOUR_WEEKS.deadline(inp.end)
        if shorter or basis == "any_time":
            trace.warnings.append(
                "Before the fixed term's end we used at least four weeks' notice to the 15th or the end of a "
                "month (§ 622 Abs. 1 BGB): a shorter notice, or notice to any day, is usually the probation "
                "period's (§ 622 Abs. 3 BGB), and after it a contract can rarely agree less (§ 622 Abs. 4, 5 BGB)."
            )
            notice, basis = (FOUR_WEEKS if shorter else notice), None
    if basis == "any_time":
        return _plan_open(trace, inp, notice)
    if basis == "end_of_month":
        return _plan_month_ends(trace, inp, notice)

    def candidates() -> Iterator[tuple[date, date]]:
        month = inp.today.month
        while True:
            month_end = end_of_month(inp.today.year, month)
            for exit_day in (month_end.replace(day=15), month_end):
                yield exit_day, notice.deadline(exit_day)
            month += 1

    exit_day, deadline = _first_reachable(candidates(), inp.today)
    _deadline_step(trace, exit_day, notice, deadline)
    return _Plan("exit", earliest_exit=exit_day, cancel_by=deadline)


def _plan_regime(trace: Trace, inp: _Inputs, regime: ContractRegime) -> _Plan:
    if regime in ("bgb309_new", "tkg56"):
        return _plan_minimum_term(trace, inp, regime)
    if regime == "sgbv175":
        return _plan_health(trace, inp)
    if regime == "stromgvv20":
        return _plan_open(trace, inp, TWO_WEEKS)
    if regime == "rent573c":
        return _plan_rent(trace, inp)
    if regime == "employment622":
        return _plan_employment(trace, inp)
    if regime == "bgb675h":
        return _plan_payment_account(trace, inp)
    return _plan_renewing(trace, inp, regime)


# ---------------------------------------------------------------------------------------- output


def _arrival(today: date, channel: SendChannelKind, region: str | None, buffer: int) -> date:
    """When a cancellation sent today is expected to arrive."""
    if channel == "online_button":
        return today
    if channel in _SAME_DAY_CHANNELS:
        return calendar_de.next_business_day(today, region)
    return calendar_de.add_business_days(today, buffer, region)


def _send_by(
    trace: Trace,
    cancel_by: date,
    safe: date,
    channel: SendChannelKind,
    region: str | None,
    buffer: int,
    *,
    today: date,
    late_advice: str,
) -> date:
    """When to send the cancellation; never before ``today`` (the step always shows the final date)."""
    if channel == "online_button":
        send_by, rule_id = cancel_by, "bgb_312k"
        label = (
            f"An online cancellation button counts the moment you press it (§ 312k BGB): use it by "
            f"{fmt_date(cancel_by)}"
        )
    elif channel in _SAME_DAY_CHANNELS:
        send_by, rule_id = safe, "postal_buffer"
        label = f"Send it by {fmt_date(safe)}, during business hours"
    else:
        send_by, rule_id = calendar_de.add_business_days(safe, -buffer, region), "postal_buffer"
        label = f"Post it by {fmt_date(send_by)} to allow {buffer} business days for delivery"
    if send_by < today:
        trace.warnings.append(f"The usual sending time has passed — {late_advice} today.")
        send_by = today
        label = f"The usual sending time has passed: send it today, {fmt_date(today)}"
    trace.step(label, send_by, rule_id)
    return send_by


def _summary(plan: _Plan, send_by: date | None) -> str:
    sentence = _plan_sentence(plan, send_by)
    if plan.fixed_end is None:
        return sentence
    return f"{sentence} If you don't give notice, it ends by itself on {fmt_date(plan.fixed_end)}."


def _plan_sentence(plan: _Plan, send_by: date | None) -> str:
    if plan.kind == "term" and plan.earliest_exit and plan.cancel_by:
        return contract_term_sentence(
            plan.earliest_exit,
            plan.cancel_by,
            send_by,
            renews=plan.renews,
            missed=plan.missed,
            renewal=plan.next_renewal,
        )
    if plan.kind == "open" and plan.notice == NO_NOTICE and plan.earliest_exit and plan.arrival:
        return (
            f"You can cancel any time, without notice (§ 675h Abs. 1 BGB): if your cancellation arrives by "
            f"{fmt_date(plan.arrival)}, the account ends then."
        )
    if plan.kind == "open" and plan.notice and plan.earliest_exit and plan.arrival:
        return contract_open_sentence(
            plan.notice.text, plan.earliest_exit, plan.arrival, minimum_term_end=plan.current_term_end
        )
    if plan.kind == "exit" and plan.earliest_exit and plan.cancel_by:
        return contract_exit_sentence(plan.earliest_exit, plan.cancel_by, send_by, plan.detail)
    return f"We couldn't compute a cancellation date: {plan.reason[0].lower()}{plan.reason[1:]}"


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


#: Longest plausible term (100 years) and notice period per unit; longer values are misreadings.
MAX_TERM_MONTHS: Final = 1_200
MAX_NOTICE: Final[dict[NoticeUnit, int]] = {"days": 36_525, "weeks": 5_218, "months": 1_200}
_NUMBER_LABELS = {
    "initial_term_months": "minimum term (months)",
    "renewal_term_months": "renewal term (months)",
    "notice_value": "notice period",
    "notice_day": "day of the month for notice",
}


def _without_implausible_numbers(trace: Trace, terms: ContractTerms) -> ContractTerms:
    """Treat misread terms and notice periods as missing.

    Zero or negative values are dropped silently (the regime then assumes the statutory worst case),
    except ``renewal_term_months == 0``, which means "continues indefinitely". Values beyond 100 years
    (a day of the month beyond the 31st) are dropped with a hard warning, so they can neither crash the
    date arithmetic nor look reliable.
    """
    bad: dict[str, None] = {}
    for name, label in _NUMBER_LABELS.items():
        value = getattr(terms, name)
        if value is None:
            continue
        floor = 0 if name == "renewal_term_months" else 1
        if name == "notice_value":
            cap = MAX_NOTICE[terms.notice_unit or "days"]
        else:
            cap = 31 if name == "notice_day" else MAX_TERM_MONTHS
        if value < floor:
            bad[name] = None
        elif value > cap:
            bad[name] = None
            trace.hard(
                f"The contract's {label} ({value}) can't be right, so we ignored it — please check it."
            )
    return terms.model_copy(update=bad) if bad else terms


def _ends_by_itself(terms: ContractTerms, regime: ContractRegime, *, past: bool) -> bool:
    """A contract with an end date ends by itself unless its terms say it renews or needs notice (a notice
    period, or a day of the month for it: :func:`_notice_day`).

    A flat let always does here (the summary says it may still need notice). A job does too (§ 15 Abs. 1
    TzBfG) unless its contract lets it be ended earlier by ordinary notice (``notice_before_end``, § 15 Abs.
    4 TzBfG) and its end date is still ahead: it is then planned like an open-ended job whose notice must end
    it before that date (``past``: the end date has passed). A notice period read alone doesn't set it, as
    it may be the probation clause's (§ 622 Abs. 3 BGB); one agreed for the time after probation is the § 15
    Abs. 4 agreement (BAG 6 AZR 436/10), the flag's (read, or set on the card)."""
    if regime == "rent573c":
        return True
    if regime == "employment622":
        return past or not terms.notice_before_end
    return terms.renewal_term_months is None and terms.notice_value is None and _notice_day(terms) is None


def compute_contract(
    terms: ContractTerms,
    ctx: RuleContext,
    *,
    postal_buffer_days: int = POSTAL_BUFFER_DAYS,
    channel: SendChannelKind = "letter",
) -> ContractComputation:
    """Cancellation deadline, send-by date and earliest exit for a contract (relative to ``ctx.today``).

    ``channel`` is how the person plans to cancel: a letter must be posted ``postal_buffer_days``
    business days before the safe date; email, fax, portal or in person must arrive on a business
    day (the safe date); an online cancellation button counts the moment it is pressed (§ 312k BGB),
    so it works up to ``cancel_by`` itself. Rent and employment notices always need a signed letter.
    ``ctx.region`` is the holiday region of the other party (``None`` → nationwide holidays only).
    Misread numbers or dates never raise: the result then has no dates and ``low`` confidence.
    """
    try:
        return _compute_contract(terms, ctx, postal_buffer_days, channel)
    except (OverflowError, ValueError):  # dates near the ends of the calendar
        reason = "The contract's dates are out of range — please check them."
        return ContractComputation(
            regime=regime_for(terms),
            summary=f"We couldn't compute a cancellation date: {reason[0].lower()}{reason[1:]}",
            warnings=[reason],
            confidence="low",
        )


def _compute_contract(
    terms: ContractTerms, ctx: RuleContext, postal_buffer_days: int, channel: SendChannelKind
) -> ContractComputation:
    trace = Trace()
    region = calendar_de.normalize_region(ctx.region)
    terms = _without_implausible_numbers(trace, terms)
    regime = regime_for(terms)
    rule_id = _REGIME_RULE[regime]
    trace.step(f"Rules that apply: {catalog.get_rule(rule_id).title}", None, rule_id)
    end = parse_date(terms.end_date)
    if terms.concluded_date is None and terms.start_date and regime in ("bgb309_new", "bgb309_old", "tkg56"):
        trace.soft("The contract date is missing; we used the start date to decide which rules apply.")
    if regime == "as_written":
        trace.hard("No special consumer rule applies that we know of, so we used the contract's own terms.")
    if ctx.country != "DE":
        trace.hard(f"Ordnung only knows German rules; this contract was treated as German ({ctx.country}).")
    if regime in ("rent573c", "employment622") and channel not in _SIGNED_LETTER_CHANNELS:
        trace.warnings.append("This notice needs a hand-signed letter, so the dates assume a letter by post.")
        channel = "letter"
    notes = [
        _REGIME_NOTE[regime],
        "Cancellations count when they arrive, not when they are sent (§ 130 BGB).",
    ]
    if terms.category in ("energy", "gas") and regime in ("bgb309_new", "bgb309_old"):
        notes.append(
            "For electricity and gas contracts these consumer rules apply where the terms are worse than basic "
            "supply (§ 310 Abs. 2 BGB) — minimum terms and renewals usually are. District heating is different "
            "(AVBFernwärmeV: up to 9 months' notice): if this is heating, check the contract."
        )

    def result(
        summary: str, plan: _Plan | None = None, send_by: date | None = None, safe: date | None = None
    ) -> ContractComputation:
        return ContractComputation(
            regime=regime,
            current_term_end=_iso((plan.current_term_end or plan.fixed_end) if plan else end),
            cancel_by=_iso(plan.cancel_by if plan else None),
            send_by=_iso(send_by),
            safe_date=_iso(safe),
            next_renewal=_iso(plan.next_renewal if plan else None),
            earliest_exit=_iso(plan.earliest_exit if plan else end),
            summary=summary,
            notes=notes,
            steps=trace.steps,
            rule_ids=trace.rule_ids,
            warnings=trace.warnings,
            confidence=trace.confidence,
        )

    if terms.status != "active":
        if end is None:
            trace.hard("The end date of the cancelled contract is unknown.")
        return result(contract_closed_sentence(terms.status, end))
    if end is not None and _ends_by_itself(terms, regime, past=end < ctx.today):
        trace.step(f"Fixed term: it ends on {fmt_date(end)}", end, "fixed_term")
        return result(contract_fixed_end_sentence(end, past=end < ctx.today, regime=regime))

    inp = _Inputs(
        terms=terms,
        today=ctx.today,
        region=region,
        arrival=_arrival(ctx.today, channel, region, postal_buffer_days),
        start=parse_date(terms.start_date) or parse_date(terms.concluded_date),
        end=end,
        origin=contract_origin(terms),
    )
    fixed_end = end if regime == "employment622" else None  # notice_before_end (:func:`_ends_by_itself`)
    if fixed_end is not None:
        # would the notice end it sooner? (asked on a scratch trace: if not, only the fixed term explains it)
        sooner = _plan_regime(Trace(), inp, regime).earliest_exit
        if sooner is None or sooner >= fixed_end:
            trace.step(
                f"Fixed term: notice can't end it sooner, so it ends on {fmt_date(fixed_end)}",
                fixed_end,
                "fixed_term",
            )
            return result(contract_fixed_end_sentence(fixed_end, past=False, regime=regime))
    plan = _plan_regime(trace, inp, regime)
    if fixed_end is not None:
        trace.step(
            f"If you don't give notice, it ends by itself on {fmt_date(fixed_end)}", fixed_end, "fixed_term"
        )
        plan.fixed_end = fixed_end
    if plan.cancel_by is None:
        return result(_summary(plan, None), plan)
    safe = calendar_de.previous_business_day(plan.cancel_by, region)
    if safe != plan.cancel_by:
        trace.step(f"Safe date: make sure it arrives by {fmt_date(safe)}", safe, "safe_date")
    fastest = (
        "hand the signed letter over in person (with a witness) or by messenger"
        if regime in ("rent573c", "employment622")
        else "use the fastest channel allowed (online button, email, fax or in person)"
    )
    send_by = _send_by(
        trace, plan.cancel_by, safe, channel, region, postal_buffer_days, today=ctx.today, late_advice=fastest
    )
    check_partial_holidays(trace, region, plan.cancel_by, send_by=send_by, safe=safe)
    return result(_summary(plan, send_by), plan, send_by, safe)


# ---------------------------------------------------------------------------------------- price increases


def _window_receipt(
    trace: Trace,
    ctx: RuleContext,
    *,
    due: date | None,
    summary: str,
    buffer: int,
    region: str | None,
) -> ComputationReceipt:
    safe = send_by = None
    if due is not None:
        safe = calendar_de.previous_business_day(due, region)
        if safe != due:
            trace.step(f"Safe date: make sure it arrives by {fmt_date(safe)}", safe, "safe_date")
        send_by = plan_send_by(trace, ctx.today, due, region=region, buffer=buffer)
        check_partial_holidays(trace, region, due, send_by=send_by, safe=safe)
    return ComputationReceipt(
        due_date=_iso(due),
        send_by=_iso(send_by),
        safe_date=_iso(safe),
        holiday_calendar=calendar_de.holiday_calendar_label(ctx.region),
        summary=summary,
        steps=trace.steps,
        rule_ids=trace.rule_ids,
        warnings=trace.warnings,
        confidence=trace.confidence,
    )


def _told_on(trace: Trace, notified_on: date | None, ctx: RuleContext) -> date | None:
    if notified_on is not None:
        return notified_on
    if ctx.document_date is not None:
        trace.soft(
            "We assumed you received the notice on the date printed on it, the earliest possible day — "
            "tell us when it arrived."
        )
    return ctx.document_date


def price_increase_window(
    effective_date: date,
    category: ContractCategory,
    notified_on: date | None,
    ctx: RuleContext,
    *,
    is_basic_supply: bool = False,
    party_kind: str | None = None,
    postal_buffer_days: int = POSTAL_BUFFER_DAYS,
) -> ComputationReceipt:
    """Special cancellation right after a price increase: the last day the cancellation must arrive.

    * energy/gas (§ 41 Abs. 5 EnWG; basic supply § 5 Abs. 3 StromGVV/GasGVV): cancel without notice
      effective when the new price applies; it must arrive the day before (BNetzA).
    * phone/internet (§ 57 Abs. 1, 2 TKG): within three months after you were told (if you were told
      one to two months ahead); the contract ends at the earliest when the change takes effect.
    * insurance (§ 40 VVG): within one month after you were told; statutory health insurance
      (§ 175 Abs. 4 SGB V): until the end of the month for which the higher contribution is charged.
    * other contracts: no statutory special right (``due_date`` is ``None``).

    ``notified_on`` is the day the notice arrived (``None`` → the letter's date from ``ctx``, the
    earliest possible day). Deadlines are not moved off weekends; ``safe_date`` is the business day
    before when needed, and ``send_by`` allows ``postal_buffer_days`` for a letter.
    """
    trace = Trace()
    region = calendar_de.normalize_region(ctx.region)
    day_before = effective_date - timedelta(days=1)
    if category in ("energy", "gas"):
        told = notified_on or ctx.document_date
        trace.step(
            f"The new price applies from {fmt_date(effective_date)}; a cancellation that arrives by "
            f"{fmt_date(day_before)} ends the contract before it",
            day_before,
            "enwg_41_5",
        )
        if is_basic_supply:  # the StromGVV/GasGVV apply to basic supply only (walkthrough of phase 2)
            trace.use("stromgvv_5_3")
            if effective_date.day != 1:
                trace.soft(
                    "In basic supply, price changes only take effect on the 1st of a month (§ 5 Abs. 2 StromGVV)."
                )
            latest = latest_receipt_for(day_before, 6, "weeks")
            if told is not None and told > latest:
                how = "only just" if told == latest + timedelta(days=1) else "less than"
                trace.warnings.append(
                    f"The change was announced {how} six weeks ahead (latest day: {fmt_date(latest)}, § 5 Abs. 2 "
                    "StromGVV) — it may not be valid yet. Object to it, and cancel in time to be safe."
                )
        elif told is not None and told > latest_receipt_for(day_before, 1, "months"):
            trace.warnings.append(
                "You were told less than a month ahead (§ 41 Abs. 5 EnWG), so the increase may not be valid. "
                "Object to it, and cancel in time to be safe."
            )
        summary = (
            f"The price goes up on {fmt_date(effective_date)}: cancel without notice so it arrives by "
            f"{fmt_date(day_before)}, and the new price never applies."
        )
        return _window_receipt(
            trace, ctx, due=day_before, summary=summary, buffer=postal_buffer_days, region=region
        )
    if category in ("mobile", "internet"):
        told = _told_on(trace, notified_on, ctx)
        if told is None:
            trace.hard("We don't know when you were told about the change.")
            return _window_receipt(
                trace,
                ctx,
                due=day_before,
                summary=f"Cancel so it arrives by {fmt_date(day_before)}, before the change applies.",
                buffer=postal_buffer_days,
                region=region,
            )
        timely = add_months(effective_date, -2) <= told <= latest_receipt_for(day_before, 1, "months")
        if not timely:
            trace.soft(
                "You weren't told one to two months before the change (§ 57 Abs. 2 TKG), so the three-month "
                "window may not have started and the change may not be valid — object, and cancel before it "
                "applies to be safe."
            )
            trace.step(f"Cancel so it arrives by {fmt_date(day_before)}", day_before, "tkg_57")
            summary = (
                f"Cancel without notice so it arrives by {fmt_date(day_before)}, before the change applies."
            )
            return _window_receipt(
                trace, ctx, due=day_before, summary=summary, buffer=postal_buffer_days, region=region
            )
        window_end, _ = add_period(told, 3, "months")
        trace.step(
            f"You were told on {fmt_date(told)}; you can cancel without notice for three months, until "
            f"{fmt_date(window_end)}",
            window_end,
            "tkg_57",
        )
        trace.step(
            f"If it arrives by {fmt_date(day_before)}, the new terms never apply", day_before, "tkg_57"
        )
        summary = (
            f"You can cancel without notice until {fmt_date(window_end)} (three months after you were told); "
            f"if it arrives by {fmt_date(day_before)}, the new price never applies."
        )
        return _window_receipt(
            trace, ctx, due=window_end, summary=summary, buffer=postal_buffer_days, region=region
        )
    if category == "insurance" and party_kind == "health_insurer":
        month_end = end_of_month(effective_date.year, effective_date.month)
        trace.step(
            f"The higher contribution applies from {fmt_date(effective_date)}; you can switch until the end of "
            f"that month, {fmt_date(month_end)}",
            month_end,
            "sgbv_175_4_zb",
        )
        summary = (
            f"Because the contribution goes up on {fmt_date(effective_date)}, you can switch health insurer until "
            f"{fmt_date(month_end)} — join the new one and it tells your current insurer."
        )
        return _window_receipt(
            trace, ctx, due=month_end, summary=summary, buffer=postal_buffer_days, region=region
        )
    if category == "insurance":
        told = _told_on(trace, notified_on, ctx)
        if told is None:
            trace.hard("We don't know when you were told about the increase.")
            return _window_receipt(
                trace,
                ctx,
                due=None,
                summary="Tell us when the notice arrived: you have one month from then to cancel.",
                buffer=postal_buffer_days,
                region=region,
            )
        if told > latest_receipt_for(day_before, 1, "months"):
            trace.warnings.append(
                "The notice arrived less than a month before the increase (§ 40 Abs. 1 VVG) — ask the insurer "
                "when it really takes effect."
            )
        window_end, _ = add_period(told, 1, "months")
        trace.step(
            f"You were told on {fmt_date(told)}; you can cancel within one month, until {fmt_date(window_end)}",
            window_end,
            "vvg_40",
        )
        summary = (
            f"You can cancel within one month of being told, so it must arrive by {fmt_date(window_end)}; the "
            f"contract then ends when the higher premium would start ({fmt_date(effective_date)})."
        )
        return _window_receipt(
            trace, ctx, due=window_end, summary=summary, buffer=postal_buffer_days, region=region
        )
    trace.hard(
        "There's no statutory right to cancel after a price increase for this kind of contract. A price rise "
        "usually needs a valid clause in your terms or your consent — you can object to it."
    )
    return _window_receipt(
        trace,
        ctx,
        due=None,
        summary="No special cancellation right applies; your normal notice options still do.",
        buffer=postal_buffer_days,
        region=region,
    )
