"""Plain-English wording for receipts: date and period formatting and the one-sentence summaries.

Weekday and month names are English on purpose (the UI is English; German legal terms are shown
separately with a glossary). Functions here are pure: callers pass in the facts (dates, reasons)
and get back text, so every summary sentence is built in one place.
"""

from __future__ import annotations

from datetime import date

_UNIT_WORDS: dict[str, tuple[str, str]] = {
    "days": ("day", "days"),
    "weeks": ("week", "weeks"),
    "months": ("month", "months"),
    "years": ("year", "years"),
    "business_days": ("business day", "business days"),
    "werktage": ("working day (Mon–Sat)", "working days (Mon–Sat)"),
}

_SMALL_NUMBERS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}

# Fixed English names: strftime would follow the process locale.
_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def month_name(d: date) -> str:
    """English month name of ``d``, e.g. ``October``."""
    return _MONTHS[d.month - 1]


def fmt_date(d: date, *, year: bool = True) -> str:
    """Format a date like ``Mon 21 Sep 2026`` (``Mon 21 Sep`` without the year)."""
    text = f"{_WEEKDAYS[d.weekday()]} {d.day} {month_name(d)[:3]}"
    return f"{text} {d.year}" if year else text


def fmt_period(amount: int, unit: str) -> str:
    """Format a period like ``one month``, ``2 weeks`` or ``10 business days``."""
    singular, plural = _UNIT_WORDS[unit]
    count = abs(amount)
    number = _SMALL_NUMBERS.get(count, str(count)) if unit in ("months", "years", "weeks") else str(count)
    return f"{number} {singular if count == 1 else plural}"


def notice_phrase(period: str) -> str:
    """``one month's notice`` / ``two weeks' notice``."""
    return f"{period}' notice" if period.endswith("s") else f"{period}'s notice"


def ordinal(day: int) -> str:
    """A day of the month as an English ordinal: ``1st``, ``2nd``, ``3rd``, ``10th``, ``11th``, ``21st``."""
    suffix = "th" if 11 <= day % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix}"


def capitalize_first(text: str) -> str:
    """Upper-case only the first character (``str.capitalize`` would lower-case month names)."""
    return text[:1].upper() + text[1:]


def join_clauses(clauses: list[str]) -> str:
    """Join clauses into one sentence (``;``-separated), capitalised and ending with a full stop."""
    text = capitalize_first("; ".join(c for c in clauses if c))
    return text if not text or text.endswith(".") else text + "."


def reason_phrase(kind: str | None) -> str | None:
    """Describe why a day is not a working day: ``a Saturday`` / ``a public holiday, <name>``."""
    if kind is None:
        return None
    if kind in ("Saturday", "Sunday"):
        return f"a {kind}"
    return f"a public holiday, {kind}"


def end_clause(
    raw: date,
    final: date,
    why: str | None,
    *,
    safe: date | None = None,
    kept: str = "notice deadlines don't move",
) -> str:
    """How a period's end reads, e.g. ``Sat 3 Oct 2026, a Saturday, so the deadline moves to …``.

    ``why`` describes ``raw`` when it is not a working day. ``safe`` is set for deadlines that never
    move (notice deadlines, periods counted backwards); the clause then says why (``kept``) and points
    to the earlier safe date instead.
    """
    if safe is not None and safe != raw:
        return f"{fmt_date(raw)}, {why}; {kept}, so aim for {fmt_date(safe)}"
    if raw == final:
        return fmt_date(final)
    return f"{fmt_date(raw)}, {why}, so the deadline moves to {fmt_date(final)}"


def delivery_clause(subject: str, raw: date, final: date, *, no_shift_note: str | None = None) -> str:
    """``Letter dated Tue 15 Sep 2026 counts as delivered on Sat 19 Sep, moved to Mon 21 Sep``."""
    clause = f"{subject} counts as delivered on {fmt_date(raw, year=False)}"
    if final != raw:
        return f"{clause}, moved to {fmt_date(final, year=False)}"
    return f"{clause} ({no_shift_note})" if no_shift_note else clause


def due_sentence(lead: str, period: str, relation: str, end: str) -> str:
    """Summary of a relative deadline: ``<lead>; one month later is <end>.``"""
    return join_clauses([lead, f"{period} {relation} is {end}"])


def contract_term_sentence(
    term_end: date,
    cancel_by: date,
    send_by: date | None,
    *,
    renews: bool,
    missed: date | None = None,
    renewal: date | None = None,
) -> str:
    """Summary when a cancellation deadline for the end of a term is ahead.

    ``missed``/``renewal``: the deadline for the current term has passed and it renews on ``renewal``.
    """
    send = f" — send it by {fmt_date(send_by, year=False)}" if send_by and send_by != cancel_by else ""
    after = "otherwise it renews" if renews else "otherwise it continues"
    main = (
        f"to leave when the term ends on {fmt_date(term_end)}, your cancellation must arrive by "
        f"{fmt_date(cancel_by)}{send}; {after}"
    )
    if missed and renewal:
        lead = f"The deadline for the current term ({fmt_date(missed)}) has passed, so it renews on {fmt_date(renewal)}"
        return join_clauses([lead, main])
    return join_clauses([main])


def contract_open_sentence(
    notice: str, exit_day: date, arrival: date, *, minimum_term_end: date | None
) -> str:
    """Summary for a contract that can be ended any day with ``notice``."""
    lead = f"After the minimum term (until {fmt_date(minimum_term_end)}) you" if minimum_term_end else "You"
    return (
        f"{lead} can cancel any time with {notice_phrase(notice)}: if your cancellation arrives by "
        f"{fmt_date(arrival)}, the contract ends on {fmt_date(exit_day)}."
    )


def contract_exit_sentence(exit_day: date, cancel_by: date, send_by: date | None, detail: str | None) -> str:
    """Summary for set exit dates (e.g. rent): ``To leave on …, notice must arrive by … (<detail>)``.

    ``detail`` explains the deadline, e.g. ``the 3rd working day of October``.
    """
    send = f"; send it by {fmt_date(send_by, year=False)}" if send_by and send_by != cancel_by else ""
    extra = f" ({detail})" if detail else ""
    return f"To leave on {fmt_date(exit_day)}, your notice must arrive by {fmt_date(cancel_by)}{extra}{send}."


def contract_fixed_end_sentence(end: date, *, past: bool, regime: str | None = None) -> str:
    """Summary for a fixed-term contract with an end date.

    Most end by themselves. A flat let (``rent573c``) only where the lease gives a legal reason for its
    fixed term in writing — otherwise it counts as open-ended and ending it needs notice (§ 575 Abs. 1 S. 2
    BGB) — and a lease or job used on after its end may continue (§ 545 BGB, § 15 Abs. 6 TzBfG): an active
    one past its end date may not have ended, never "ended".
    """
    if regime == "rent573c":
        if past:
            return (
                f"This lease's fixed-term end date, {fmt_date(end)}, has passed. If you still live there, it may "
                "not have ended (§ 575 Abs. 1 S. 2, § 545 BGB) — check the lease or get advice."
            )
        return (
            f"This lease's fixed term ends on {fmt_date(end)}. It ends then without notice only if the lease "
            "gives a legal reason for the fixed term in writing (§ 575 Abs. 1 BGB); otherwise it counts as "
            "open-ended and ending it needs notice — check the lease or ask a tenants' association."
        )
    if past and regime == "employment622":
        return (
            f"This job's fixed-term end date, {fmt_date(end)}, has passed. If you still work there with the "
            "employer's knowledge, it may continue with no fixed term (§ 15 Abs. 6 TzBfG)."
        )
    if past:
        return f"This contract ended on {fmt_date(end)}."
    return f"This contract ends by itself on {fmt_date(end)} — no cancellation needed."


def contract_closed_sentence(status: str, end: date | None) -> str:
    """Summary for a contract already cancelled or ended."""
    if end is None:
        return "This contract is cancelled; check the confirmation for the end date."
    verb = "ended" if status == "ended" else "is cancelled and ends"
    return f"This contract {verb} on {fmt_date(end)}."
