"""Turn a :class:`~ordnung.models.DateSpec` (what a letter says) into a concrete, explained date.

Pipeline for relative dates: anchor → optional deemed delivery → period arithmetic (§§ 187, 188 BGB)
→ weekend/holiday shift for objection, payment and declaration deadlines (§ 193 BGB and siblings) →
safe date for notice deadlines (which never shift, BGH III ZR 172/04) → send-by date. Periods
counted backwards ("one month before …") never shift either; they get a safe date too.

Safety policy (SPEC § 21): when something is uncertain the engine computes the *earliest plausible*
date, lowers the confidence and says why in ``warnings``. The engine judges the rule-related part of
the confidence rubric: anchor present and stated/confirmed, rule known, holiday region known where a
regional holiday could change the result. The pipeline downgrades further for quote problems.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Final, Literal

from ordnung.models import ComputationReceipt, ComputationStep, Confidence, DateNature, DateSpec, PeriodUnit
from ordnung.rules import calendar_de, catalog, routing
from ordnung.rules.delivery import (
    MAY_BE_PUBLIC_KINDS,
    DeliveryChannel,
    DeliveryScope,
    resolve_delivery,
    shows_administrative_act,
)
from ordnung.rules.explain import (
    capitalize_first,
    delivery_clause,
    due_sentence,
    end_clause,
    fmt_date,
    fmt_period,
    reason_phrase,
)
from ordnung.rules.periods import add_period, latest_receipt_for, shift_to_business_day

#: Default business days allowed for a letter to arrive (SPEC § 21).
POSTAL_BUFFER_DAYS: Final = 4
#: Business days a bank transfer may take to reach the payee's bank (§ 675s Abs. 1 BGB).
PAYMENT_BUFFER_DAYS: Final = 1
#: Longest plausible period per unit (100 years); anything longer is a misreading, not a deadline.
MAX_PERIOD: Final[dict[PeriodUnit, int]] = {
    "days": 36_525,
    "weeks": 5_218,
    "months": 1_200,
    "years": 100,
    "business_days": 26_100,
    "werktage": 31_300,
}

ASSUMED_RECEIPT_WARNING: Final = (
    "We assumed the letter arrived on the date printed on it — tell us when it actually arrived."
)
NEEDS_ARRIVAL_WARNING: Final = "We need the day the letter arrived — tell us when it actually arrived."
#: A letter served formally (a court's, a fine's): one date, "delivered" — the date on the yellow envelope.
ASSUMED_DELIVERY_WARNING: Final = (
    "We assumed the letter was delivered on the date printed on it — tell us the delivery date the postman "
    "wrote on the yellow envelope."
)
NEEDS_DELIVERY_WARNING: Final = (
    "We need the day the letter was delivered — the date the postman wrote on the yellow envelope."
)
PRIVATE_SENDER_WARNING: Final = (
    "No delivery days were added: the rule that a letter counts as delivered a few days after posting "
    "is only for authorities' letters, and this sender is not an authority. The period runs from the "
    "day the letter arrived."
)
#: A private sender's period counted from the letter's own date or another date it names, read with a
#: delivery rule: the rule goes, the date stays — the arrival day plays no part, so it is not asked for.
PRIVATE_SENDER_DATED_WARNING: Final = (
    "No delivery days were added: the rule that a letter counts as delivered a few days after posting "
    "is only for authorities' letters, and this sender is not an authority. The period runs from the "
    "date the letter gives, not from the day it arrived."
)
#: The words that mark a warning's situation, shared with the rules tools, whose hints name the argument
#: that would settle it (``ordnung.assistant.rules_tools.deadline_hints``): reword them here, not there.
REGION_UNKNOWN: Final = "Holiday region unknown"
REGION_EARLIER: Final = "where the deadline would be earlier"
HOME_HOLIDAY: Final = "is a public holiday where you live"
TAX_OFFICE_HOLIDAY: Final = "is a public holiday where the tax office is"
#: Words for the app's person (who answers the app); the rules tools put them in their own voice.
TOLD_ARRIVAL: Final = "You told us it arrived on"
ENTER_ENVELOPE_DATE: Final = "enter the envelope date for the exact deadline"

_SHIFTING_NATURES = ("objection", "payment", "declaration")
_SEND_BY_NATURES = ("objection", "payment", "declaration", "notice")
#: Court orders under the ZPO (and at a labour court, § 46a ArbGG): delivered by the court (§ 180 ZPO),
#: shifted by § 222 Abs. 2 ZPO.
_CIVIL_COURT = ("zpo_692", "zpo_339", "arbgg_46a", "arbgg_59")
#: Statutes whose period runs from formal service (yellow envelope), not from a delivery fiction.
_FORMAL_SERVICE = ("owig_67", "stpo_410", *_CIVIL_COURT)
#: Anchors that name the letter's own date ("ab dem Datum dieses Schreibens", "ab heute"): a court's own
#: period counted from one doesn't run from delivery (§ 221 ZPO lets the court set another start).
_OWN_DATE_ANCHORS = ("document_date", "today")
#: A labour court's orders have one week, not two (§ 46a Abs. 3, § 59 S. 1 ArbGG).
_LABOUR_COURT_RULES = {"zpo_692": "arbgg_46a", "zpo_339": "arbgg_59"}
_CHANNEL_BY_RULE: dict[str, DeliveryChannel] = {
    "de_admin_electronic": "electronic",
    "de_admin_portal": "portal",
}

_ONE_MONTH: tuple[tuple[int, PeriodUnit], ...] = ((1, "months"),)
_ONE_OR_THREE_MONTHS: tuple[tuple[int, PeriodUnit], ...] = ((1, "months"), (3, "months"))
_ONE_WEEK: tuple[tuple[int, PeriodUnit], ...] = ((1, "weeks"),)
_TWO_WEEKS: tuple[tuple[int, PeriodUnit], ...] = ((2, "weeks"),)
_THREE_WEEKS: tuple[tuple[int, PeriodUnit], ...] = ((3, "weeks"),)

# Statutes recognised in DateSpec.legal_basis / text, with their statutory periods (first = the usual
# one; the SGG gives three months when delivered abroad). A DateSpec whose period matches none of them
# is also computed with the usual one, and the earlier date wins.
_STATUTES: list[tuple[re.Pattern[str], str, tuple[tuple[int, PeriodUnit], ...]]] = [
    (re.compile(r"\b355\b[^§]{0,20}\bAO\b", re.I), "ao_355", _ONE_MONTH),
    (re.compile(r"\b70\b[^§]{0,20}\bVwGO\b", re.I), "vwgo_70", _ONE_MONTH),
    (re.compile(r"\b84\b[^§]{0,20}\bSGG\b", re.I), "sgg_84", _ONE_OR_THREE_MONTHS),
    (re.compile(r"\b67\b[^§]{0,20}\bOWiG\b", re.I), "owig_67", _TWO_WEEKS),
    (re.compile(r"\b55\b[^§]{0,20}\bOWiG\b|Anhörungsbogen", re.I), "owig_55", ()),
    (re.compile(r"\b410\b[^§]{0,20}\bStPO\b", re.I), "stpo_410", _TWO_WEEKS),
    (re.compile(r"\b87\b[^§]{0,20}\bSGG\b", re.I), "klage_1_month", _ONE_OR_THREE_MONTHS),
    (re.compile(r"\b74\b[^§]{0,20}\bVwGO\b|\b47\b[^§]{0,20}\bFGO\b", re.I), "klage_1_month", _ONE_MONTH),
    (re.compile(r"\b46a\b[^§]{0,20}\bArbGG\b", re.I), "arbgg_46a", _ONE_WEEK),
    (re.compile(r"\b59\b[^§]{0,20}\bArbGG\b", re.I), "arbgg_59", _ONE_WEEK),
    (re.compile(r"\b69[24]\b[^§]{0,20}\bZPO\b", re.I), "zpo_692", _TWO_WEEKS),
    (re.compile(r"\b(?:339|700)\b[^§]{0,20}\bZPO\b", re.I), "zpo_339", _TWO_WEEKS),
    (re.compile(r"\b4\b[^§]{0,20}\bKSchG\b|Kündigungsschutzklage", re.I), "kschg_4", _THREE_WEEKS),
]
_STATUTE_PERIODS = {rule_id: periods for _, rule_id, periods in _STATUTES}
#: Statutes whose periods run from a letter's arrival (§ 130 BGB) whoever sent it: the three weeks for a
#: Kündigungsschutzklage run from the dismissal's receipt (§ 4 S. 1 KSchG) — a public employer's too —,
#: never from a delivery fiction (:func:`from_arrival`).
_PRIVATE_LAW_STATUTES = ("kschg_4",)
#: The court rules only bind the dates they are about: the objection or court action (and, for a
#: Mahnbescheid, paying instead). A hearing or a severance payment whose wording mentions the court
#: action doesn't follow them.
_STATUTE_NATURES: dict[str, tuple[DateNature, ...]] = {
    "zpo_692": ("objection", "payment", "declaration"),
    "zpo_339": ("objection", "declaration"),
    "arbgg_46a": ("objection", "payment", "declaration"),
    "arbgg_59": ("objection", "declaration"),
    "kschg_4": ("objection", "declaration"),
}
#: How a court's period is counted (review round 1: its receipt cited the counting rules of the AO, the
#: VwVfG, the StPO and the SGG): § 222 Abs. 1 ZPO points to §§ 187, 188 BGB — at a labour court through
#: § 46 Abs. 2 ArbGG. A Kündigungsschutzklage's three weeks are a period of substantive law: the BGB's alone.
_COURT_COUNTING = {
    "bgb_187_1": "§ 222 Abs. 1 ZPO; § 187 Abs. 1 BGB",
    "bgb_188": "§ 222 Abs. 1 ZPO; § 188 Abs. 1, 2 BGB",
}
_LABOUR_COURT_COUNTING = {
    rule: f"§ 46 Abs. 2 ArbGG; {citation}" for rule, citation in _COURT_COUNTING.items()
}
#: A social court counts under its own act (§ 64 Abs. 1–3 SGG), not § 222 ZPO — the same dates, the right
#: citation (review round 2 of phase 2).
_SOCIAL_COURT_COUNTING = {"bgb_187_1": "§ 64 Abs. 1 SGG", "bgb_188": "§ 64 Abs. 2 SGG"}
_BGB_COUNTING = {"bgb_187_1": "§ 187 Abs. 1 BGB", "bgb_188": "§ 188 Abs. 1, 2 BGB"}
_SHIFT_RULE_BY_SCOPE: dict[DeliveryScope, str] = {
    "ao": "ao_108_3",
    "vwvfg": "vwvfg_31_3",
    "sgbx": "sgbx_26_3",
}


@dataclass(frozen=True, kw_only=True)
class RuleContext:
    """Facts outside the DateSpec that a computation needs.

    ``region`` is the holiday region (Land code) of the place where the declaration must be received
    (``Party.region``); ``None`` means only nationwide holidays are used. ``document_date`` is the
    date printed on the letter; ``received_date`` counts only when ``received_confirmed`` is true.
    ``delivery_scope`` comes from the sender's party kind
    (:func:`ordnung.rules.delivery.scope_for_party_kind`). ``recipient_region`` is the Land where the
    person lives (``Profile.region``, only once they chose it): a tax letter's deemed delivery day only
    moves for a regional holiday when it applies at both places (legal research verdict, OFD Cottbus
    2004), and a payment to a private creditor uses the payer's holidays, because money is owed at the
    debtor's home (§§ 269, 270 Abs. 4, 193 BGB; research ``bgb_271_286_2_zahlungsziel_rechnung``).
    ``private_sender`` says the sender is known not to be an authority
    (:func:`ordnung.rules.delivery.is_private_sender`): its letter has no deemed delivery, so a period
    from delivery runs from the day it arrived, and one from a date the letter gives runs from that
    date (:func:`from_arrival`). ``sender_kind`` is the sender's party kind and ``quote`` the sentence
    the period was read from (an item's quote, which may say more than the spec's ``text``): for a kind
    a public body may be filed as (:data:`ordnung.rules.delivery.MAY_BE_PUBLIC_KINDS`), an unknown one,
    or a period whose words name an administrative act, a private sender's late arrival never makes the
    date later than deemed delivery would (``private_sender_late_arrival``).
    ``letter_kind`` is the letter's kind (``Document.kind``), which routes the dates of high-stakes
    letters (:mod:`ordnung.rules.routing`); ``end_date`` is the end of the job or tenancy a termination
    announces. ``court``: the sender is a court (:func:`ordnung.rules.routing.is_court`) — its periods
    run from formal service, never from a delivery fiction (unless the letter counts its own period from
    its own date, which a court may set, § 221 ZPO), and none of its dates is ``high``, whatever kind the
    letter was filed as. ``labour_court``: a labour court, whose orders give one week, not two
    (§ 46a Abs. 3, § 59 ArbGG); ``social_court``: a social court, whose periods count under § 64 SGG.
    ``end_date_grounding``: where ``end_date`` is written — in the
    termination's own sentence (``quote``, also for an end the caller knows), only elsewhere in the letter
    (``letter``: one soft failure) or nowhere in it (``none``: the model's reading alone, like an assumed
    anchor — ``low``); the letter rules that count from the end apply it (:mod:`ordnung.rules.letters`).
    """

    today: date
    country: str = "DE"
    region: str | None = None
    document_date: date | None = None
    received_date: date | None = None
    received_confirmed: bool = False
    delivery_scope: DeliveryScope | None = None
    recipient_region: str | None = None
    private_sender: bool = False
    sender_kind: str | None = None
    quote: str | None = None
    letter_kind: str | None = None
    end_date: date | None = None
    court: bool = False
    labour_court: bool = False
    social_court: bool = False
    end_date_grounding: Literal["quote", "letter", "none"] = "quote"


@dataclass
class Trace:
    """Collects steps, rule ids, warnings and confidence reasons for one computation.

    Shared by the rules modules; ``soft`` failures lower confidence one level each (two → low),
    a ``hard`` failure makes it low (SPEC § 21 rubric).
    """

    steps: list[ComputationStep] = field(default_factory=list)
    rule_ids: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    soft_failures: int = 0
    hard_failure: bool = False
    region_flagged: bool = False
    #: A step's citation by the procedure its deadline follows, where the catalog's names several (a court's
    #: period is counted under § 222 ZPO, not the AO or the VwVfG: :data:`_COURT_COUNTING`).
    cite: dict[str, str] = field(default_factory=dict)

    def step(self, label: str, d: date | None, rule_id: str) -> None:
        self.steps.append(
            ComputationStep(
                label=label,
                date=d.isoformat() if d else None,
                rule_id=rule_id,
                citation=self.cite.get(rule_id) or catalog.citation(rule_id),
            )
        )
        self.use(rule_id)

    def extend(self, steps: list[ComputationStep]) -> None:
        self.steps.extend(
            step.model_copy(update={"citation": self.cite[step.rule_id]})
            if step.rule_id in self.cite
            else step
            for step in steps
        )
        for rule_id in [s.rule_id for s in steps if s.rule_id]:
            self.use(rule_id)

    def use(self, rule_id: str) -> None:
        """Record that ``rule_id`` was applied (it must exist in the catalog)."""
        catalog.get_rule(rule_id)
        if rule_id not in self.rule_ids:
            self.rule_ids.append(rule_id)

    def soft(self, warning: str) -> None:
        self.soft_failures += 1
        self.warnings.append(warning)

    def hard(self, warning: str) -> None:
        self.hard_failure = True
        self.warnings.append(warning)

    @property
    def confidence(self) -> Confidence:
        if self.hard_failure or self.soft_failures >= 2:
            return "low"
        return "medium" if self.soft_failures == 1 else "high"


@dataclass(frozen=True)
class _Anchor:
    day: date
    source: Literal["document_date", "posted", "explicit", "receipt", "stated_receipt", "today", "deemed"]
    #: the letter was served formally: its arrival is "the day it was delivered" (the envelope's date)
    served: bool = False

    @property
    def phrase(self) -> str:
        """How the anchor reads after "one month after …"."""
        return {
            "document_date": f"the letter's date ({fmt_date(self.day)})",
            "posted": f"posting on {fmt_date(self.day)}",
            "explicit": fmt_date(self.day),
            "receipt": f"the day it was delivered ({fmt_date(self.day)})"
            if self.served
            else f"the day you received it ({fmt_date(self.day)})",
            "stated_receipt": f"delivery on {fmt_date(self.day)} (as stated on the letter)",
            "today": f"today ({fmt_date(self.day)})",
            "deemed": f"the day it would usually count as delivered ({fmt_date(self.day)})",
        }[self.source]

    @property
    def subject(self) -> str:
        """How the anchor reads as the subject of "… counts as delivered on …"."""
        return (
            f"Letter dated {fmt_date(self.day)}"
            if self.source == "document_date"
            else f"Letter sent {fmt_date(self.day)}"
        )


def parse_date(value: str | None) -> date | None:
    """Parse an ISO ``YYYY-MM-DD`` string; ``None`` for missing or invalid values."""
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def _statute(
    spec: DateSpec, letter_kind: str | None = None, *, labour_court: bool = False
) -> tuple[str, tuple[tuple[int, PeriodUnit], ...]] | None:
    """The statute the DateSpec cites, else the one its kind of letter gives it (court orders); a court
    rule only for a date of a nature it binds (:data:`_STATUTE_NATURES`). At a labour court an order's
    ZPO rule is the ArbGG's one-week rule (§ 46a Abs. 3, § 59 ArbGG)."""
    haystack = f"{spec.legal_basis or ''} {spec.text}"
    found = next(
        (
            (rule_id, periods)
            for pattern, rule_id, periods in _STATUTES
            if pattern.search(haystack) and spec.nature in _STATUTE_NATURES.get(rule_id, (spec.nature,))
        ),
        None,
    )
    by_kind = routing.kind_statute(letter_kind, spec) if found is None else None
    if by_kind is not None:
        found = by_kind, _STATUTE_PERIODS[by_kind]
    if found is not None and labour_court and found[0] in _LABOUR_COURT_RULES:
        rule_id = _LABOUR_COURT_RULES[found[0]]
        return rule_id, _STATUTE_PERIODS[rule_id]
    return found


def statute_rule(spec: DateSpec) -> str | None:
    """Catalog rule id of the statute named in ``spec.legal_basis`` or ``spec.text``, if recognised."""
    match = _statute(spec)
    return match[0] if match else None


def _same_period(a: tuple[int, PeriodUnit], b: tuple[int, PeriodUnit]) -> bool:
    def in_days(amount: int, unit: PeriodUnit) -> int | None:
        return {"days": amount, "weeks": amount * 7}.get(unit)

    days_a = in_days(*a)
    return a == b or (days_a is not None and days_a == in_days(*b))


def check_regional_holidays(trace: Trace, days: Iterable[date], *, later: bool = True) -> None:
    """Lower confidence (once) if a regional holiday on one of ``days`` could move a date.

    Only used when the holiday region is unknown: nationwide holidays were used. Counted forward,
    that can only give an earlier date, but the person should know the real one may be later. Counted
    backwards (a period before an event, the safe date of a deadline that never moves), a regional
    holiday makes the real date *earlier* (``later=False``): the date shown may then be a day late.
    """
    if trace.region_flagged:
        return
    for d in days:
        lands = calendar_de.regional_holiday_lands(d)
        if lands:
            trace.region_flagged = True
            names = ", ".join(calendar_de.REGION_NAMES[code] for code in lands[:3])
            where = (
                "where the deadline would be later"
                if later
                else f"{REGION_EARLIER} — act a working day before it to be safe"
            )
            trace.soft(
                f"{REGION_UNKNOWN} — {fmt_date(d)} is a public holiday in some Länder (e.g. {names}), "
                f"{where}. We used nationwide holidays only."
            )
            return


def check_partial_holidays(
    trace: Trace,
    region: str | None,
    due: date,
    *,
    send_by: date | None = None,
    safe: date | None = None,
    moves: bool = False,
    counted_back_from: date | None = None,
    werktage: bool = False,
) -> None:
    """Warn about each holiday of only part of ``region`` that could move a date shown.

    The calendar does not count those holidays (:func:`ordnung.rules.calendar_de.partial_holidays`):
    where one holds, a date counted back over it is a working day earlier — the date shown a day
    late. That is a send-by or safe date counted back from ``due``, a period counted backwards in
    working days from ``counted_back_from`` (``werktage`` for Werktage), and the safe date of a
    deadline on one (it never moves). A due date on one that ``moves`` to the next working day is
    only later there. Each warning names the holiday, where it holds and which date it moves; the
    confidence stays, as the Land's calendar is the rule and the warning says how to be safe.
    """
    # the spans exclude ``due`` by filtering, not by date arithmetic, which fails at the calendar's ends
    back = [day for day in (send_by, safe) if day is not None]
    for day, name in calendar_de.partial_holidays(region, min(back, default=due), due):
        if day < due:
            _partial_holiday(trace, day, name, region, "the send-by or safe date, counted back over it, is")
    if counted_back_from is not None:
        for day, name in calendar_de.partial_holidays(region, due, counted_back_from, werktage=werktage):
            if day > due:
                _partial_holiday(trace, day, name, region, "this date, counted backwards over it, is")
    for day, name in calendar_de.partial_holidays(region, due, due):
        if safe is not None:
            _partial_holiday(
                trace, day, name, region, "this deadline does not move off it, so the safe date is"
            )
        elif moves:
            _partial_holiday(trace, day, name, region, None)


def _partial_holiday(trace: Trace, day: date, name: str, region: str | None, earlier: str | None) -> None:
    """One partial-holiday warning: ``earlier`` names the date that is a working day earlier there,
    ``None`` says the due date moves a working day later there."""
    code = calendar_de.normalize_region(region) or ""
    place = calendar_de.PARTIAL_HOLIDAY_PLACES[code][name]
    start = f"{fmt_date(day)} is {name}, a public holiday only in {place}, which is not counted here. Where it holds, "
    if earlier is None:
        trace.warnings.append(
            start + "the due date moves to the next working day; the date shown is the earlier one."
        )
    else:
        trace.warnings.append(
            start + f"{earlier} a working day earlier: act a working day before it to be safe."
        )


def place_region(spec: DateSpec, ctx: RuleContext) -> str | None:
    """Holiday region of the place where the deadline is met (SPEC § 21 "Holidays").

    The sender's (``ctx.region``: the authority's or company's seat), except for a payment to a
    private creditor: money is owed at the debtor's home (§§ 269, 270 Abs. 4 BGB), so § 193 BGB uses
    the payer's holidays (``ctx.recipient_region``; unknown → nationwide only, the earlier date). A
    Kündigungsschutzklage may be filed at the labour court of the employer's seat or of the place of work
    (§ 48 Abs. 1a ArbGG), which may be in another Land: a regional holiday counts only where it holds at
    the employer's seat and where the person lives (the place of work's stand-in), else nationwide
    holidays only — the earlier date, with the warning that a Land's holiday may make it later.
    """
    if spec.nature == "payment" and ctx.delivery_scope is None:
        return calendar_de.normalize_region(ctx.recipient_region)
    region = calendar_de.normalize_region(ctx.region)
    statute = _statute(spec, ctx.letter_kind, labour_court=ctx.labour_court)
    if (
        statute is not None
        and statute[0] == "kschg_4"
        and region != calendar_de.normalize_region(ctx.recipient_region)
    ):
        return None
    return region


def _receipt(
    trace: Trace,
    ctx: RuleContext,
    *,
    due: date | None,
    summary: str,
    send_by: date | None = None,
    safe_date: date | None = None,
    region: str | None = None,
) -> ComputationReceipt:
    return ComputationReceipt(
        due_date=due.isoformat() if due else None,
        send_by=send_by.isoformat() if send_by else None,
        safe_date=safe_date.isoformat() if safe_date else None,
        holiday_calendar=calendar_de.holiday_calendar_label(region),
        summary=summary,
        steps=trace.steps,
        rule_ids=trace.rule_ids,
        warnings=trace.warnings,
        confidence=trace.confidence,
    )


def _no_date(trace: Trace, ctx: RuleContext, reason: str) -> ComputationReceipt:
    trace.hard(reason)
    return _receipt(
        trace,
        ctx,
        due=None,
        summary=f"No date could be computed: {reason[0].lower()}{reason[1:]}",
        region=ctx.region,
    )


def plan_send_by(
    trace: Trace,
    today: date,
    must_arrive_by: date,
    *,
    region: str | None,
    buffer: int,
    what: str = "a letter",
    rule_id: str = "postal_buffer",
    bank: bool = False,
) -> date | None:
    """Latest day to send something so it arrives by ``must_arrive_by``.

    Counts ``buffer`` business days back from the last business day on or before
    ``must_arrive_by`` (so weekend deadlines are treated like the Friday before); with ``bank=True``
    bank business days, which also skip 24 and 31 December. Never earlier than ``today`` (with a
    warning when the usual time has passed); ``None`` if the date itself has passed.
    """
    if must_arrive_by < today:
        trace.warnings.append(f"This date ({fmt_date(must_arrive_by)}) has already passed.")
        return None
    counts = calendar_de.is_bank_business_day if bank else calendar_de.is_business_day
    send_by, remaining = must_arrive_by, buffer
    while not counts(send_by, region):
        send_by -= timedelta(days=1)
    while remaining:
        send_by -= timedelta(days=1)
        if counts(send_by, region):
            remaining -= 1
    if send_by < today:
        trace.warnings.append(
            "The usual sending time has passed — send it today, by the fastest channel allowed "
            "(online, fax or in person)."
        )
        send_by = today
    days = "business day" if buffer == 1 else "business days"
    trace.step(f"Send by {fmt_date(send_by)} to allow {buffer} {days} for {what} to arrive", send_by, rule_id)
    return send_by


def _send_by(
    trace: Trace, ctx: RuleContext, due: date, nature: str, region: str | None, postal_buffer_days: int
) -> date | None:
    if nature == "payment":
        return plan_send_by(
            trace,
            ctx.today,
            due,
            region=region,
            buffer=PAYMENT_BUFFER_DAYS,
            what="a bank transfer",
            rule_id="bgb_675s",
            bank=True,
        )
    return plan_send_by(trace, ctx.today, due, region=region, buffer=postal_buffer_days)


def _safe_date(trace: Trace, due: date, region: str | None, *, backward: bool = False) -> date:
    """The working day on or before a deadline that never moves (notice periods, backward periods)."""
    safe = calendar_de.previous_business_day(due, region)
    if safe != due:
        why = reason_phrase(calendar_de.day_kind(due, region))
        if backward:
            label, rule_id = "a period counted backwards never moves to a later day", "backward_no_shift"
        else:
            label, rule_id = "notice deadlines never move to the next working day", "notice_no_shift"
        trace.step(f"{fmt_date(due)} is {why}, but {label}", due, rule_id)
        trace.step(f"Safe date: make sure it arrives by {fmt_date(safe)}", safe, "safe_date")
    return safe


def _end_clause(
    raw: date, final: date, region: str | None, *, safe: date | None = None, backward: bool = False
) -> str:
    why = reason_phrase(calendar_de.day_kind(raw, region))
    if backward:
        return end_clause(raw, final, why, safe=safe, kept="deadlines counted backwards don't move")
    return end_clause(raw, final, why, safe=safe)


def _shift_rule_id(ctx: RuleContext, statute: str | None) -> str:
    if statute in ("owig_67", "stpo_410"):
        return "stpo_43"
    if ctx.court and statute is None and ctx.social_court:
        return "sgg_64"
    if statute in _CIVIL_COURT or (ctx.court and statute is None):
        return "zpo_222"
    if statute == "kschg_4":
        return "bgb_193"
    return _SHIFT_RULE_BY_SCOPE[ctx.delivery_scope] if ctx.delivery_scope else "bgb_193"


def _shift_applies(spec: DateSpec) -> bool:
    if spec.nature in ("notice", "appointment"):
        return False
    if spec.nature in _SHIFTING_NATURES:
        return spec.shift_rule != "none"
    return spec.shift_rule == "next_business_day"


def _compute_fixed(
    spec: DateSpec, ctx: RuleContext, trace: Trace, postal_buffer_days: int
) -> ComputationReceipt:
    region = place_region(spec, ctx)
    written = parse_date(spec.date)
    if written is None:
        return _no_date(trace, ctx, "The date in the letter could not be read.")
    trace.step(f"The date given is {fmt_date(written)}", written, "date_as_written")
    due, safe, moves = written, None, False
    if spec.nature == "notice":
        safe = _safe_date(trace, written, region)
        if region is None:
            check_regional_holidays(trace, [written], later=False)
    elif spec.nature == "appointment":
        trace.use("authority_deadline")
    elif spec.shift_rule == "next_business_day":
        due, steps = shift_to_business_day(written, region, _shift_rule_id(ctx, statute_rule(spec)))
        trace.extend(steps)
        moves = True
        if region is None:
            check_regional_holidays(trace, [due])
    elif spec.nature in _SHIFTING_NATURES and not calendar_de.is_business_day(written, region):
        later = calendar_de.next_business_day(written, region)
        trace.warnings.append(
            f"{fmt_date(written)} is not a working day. If this deadline was set by an authority or is a "
            f"payment or declaration deadline, it may legally move to {fmt_date(later)}; we keep the "
            "date as written to be safe."
        )
        trace.use("authority_deadline")
    send_by = (
        _send_by(trace, ctx, due, spec.nature, region, postal_buffer_days)
        if spec.nature in _SEND_BY_NATURES
        else None
    )
    check_partial_holidays(trace, region, due, send_by=send_by, safe=safe, moves=moves)
    if spec.nature == "notice":
        summary = f"The notice must arrive by {_end_clause(written, written, region, safe=safe)}."
    else:
        summary = f"The date given is {_end_clause(written, due, region)}."
    return _receipt(trace, ctx, due=due, summary=summary, send_by=send_by, safe_date=safe, region=region)


def _resolve_anchor(
    spec: DateSpec, ctx: RuleContext, trace: Trace, *, served: bool = False
) -> _Anchor | None:
    anchor = spec.anchor
    if anchor is None:
        if ctx.document_date is None:
            trace.hard("The letter doesn't say from when the period runs, and its date is missing.")
            return None
        trace.soft(
            "The letter doesn't say from when the period runs; we counted from the letter's date, "
            "the earliest plausible start."
        )
        return _Anchor(ctx.document_date, "document_date")
    if anchor == "today":
        return _today_anchor(ctx, trace)
    if anchor == "explicit_date":
        explicit = parse_date(spec.anchor_date)
        if explicit is None:
            trace.hard("The start date of the period could not be read.")
            return None
        return _Anchor(explicit, "explicit")
    if anchor == "receipt":
        stated = parse_date(spec.anchor_date)
        if stated is not None and (ctx.document_date is None or stated >= ctx.document_date):
            # The letter itself states the delivery day (e.g. "zugestellt am …" / the date written on a
            # Postzustellungsurkunde envelope): that is the legal start, not an assumption — unless the
            # person entered another day, then the earlier of the two counts.
            return _against_entered(_Anchor(stated, "stated_receipt"), ctx, trace)
        if ctx.received_confirmed and ctx.received_date:
            return _Anchor(ctx.received_date, "receipt", served=served)
        if ctx.document_date is None:
            trace.hard(NEEDS_DELIVERY_WARNING if served else NEEDS_ARRIVAL_WARNING)
            return None
        trace.hard(ASSUMED_DELIVERY_WARNING if served else ASSUMED_RECEIPT_WARNING)
        return _Anchor(ctx.document_date, "document_date")
    if anchor == "deemed_delivery":
        posted = parse_date(spec.anchor_date)
        if posted is not None and (ctx.document_date is None or posted < ctx.document_date):
            return _Anchor(posted, "posted")
        if posted is not None and ctx.document_date is not None and posted > ctx.document_date:
            trace.warnings.append(
                f"The letter mentions {fmt_date(posted)} as the posting day, later than its date "
                f"({fmt_date(ctx.document_date)}). If that is when it was really posted, the deadline may be "
                "a few days later — we count from the letter's date to be safe."
            )
    if ctx.document_date is None:
        trace.hard("The letter's date is missing, so this date can't be computed.")
        return None
    return _Anchor(ctx.document_date, "document_date")


def from_arrival(spec: DateSpec, ctx: RuleContext) -> DateSpec:
    """The period :func:`compute_due` counts: without deemed delivery when the sender is no authority.

    For ``ctx.private_sender`` (and a relative period whose letter names none of the remedy statutes,
    which only authorities' decisions and courts' orders have, nor a court rule its kind of letter gives
    it; never for a court's letter) — and for a private-law period such as the Kündigungsschutzklage's
    (:data:`_PRIVATE_LAW_STATUTES`) whoever sent it: a dismissal is a declaration under private law that
    takes effect when it arrives (§ 130 BGB, § 4 S. 1 KSchG), from a city or a university as from a
    company —, ``anchor: deemed_delivery`` becomes ``receipt`` — a
    posting day in ``anchor_date`` is no arrival day, so it is dropped — and a delivery rule on a period
    from the letter's or another date is dropped: that period keeps its date (the letter says it runs
    from there), so its arrival day is never asked for. Without a confirmed arrival day a period from
    arrival runs from the letter's date, never later than with deemed delivery; a confirmed one after
    the day a letter usually counts as delivered does not move it later either when the sender may be a
    public body after all (``private_sender_late_arrival`` in :func:`compute_due`). Words
    alone never bring deemed delivery back: counted from arrival, the date is never later than with it.
    Anything else is returned unchanged (the same object), so callers can tell whether it applied
    (and by the anchor, which of the two).
    """
    statute = _statute(spec, ctx.letter_kind, labour_court=ctx.labour_court)
    private_law = statute is not None and statute[0] in _PRIVATE_LAW_STATUTES
    if ctx.court or spec.type != "relative" or not (private_law or (ctx.private_sender and statute is None)):
        return spec
    if spec.anchor == "deemed_delivery":
        return spec.model_copy(update={"anchor": "receipt", "anchor_date": None, "delivery_rule": "none"})
    if spec.delivery_rule != "none" and spec.anchor in ("document_date", "explicit_date"):
        return spec.model_copy(update={"delivery_rule": "none"})
    return spec


def _against_entered(named: _Anchor, ctx: RuleContext, trace: Trace) -> _Anchor:
    """A start the reading names (a stated delivery day, a court order's explicit start) checked against
    the day the person entered: the earlier of the two counts (SPEC § 21, the earliest plausible date),
    and a soft warning names both — the reading may have misread a hand-written envelope date, or the
    person may have entered the day they opened it."""
    received = ctx.received_date if ctx.received_confirmed else None
    if received is None or received == named.day:
        return named
    if received < named.day:
        trace.soft(
            f"You entered {fmt_date(received)} as the day it was delivered; the letter as read names "
            f"{fmt_date(named.day)}. We count from the earlier day, the one you entered."
        )
        return _Anchor(received, "receipt", served=True)
    trace.soft(
        f"The letter as read names {fmt_date(named.day)} as the start; you entered {fmt_date(received)} as the "
        f"day it was delivered. We count from the earlier day, {fmt_date(named.day)} — check both against "
        "the letter (a court's letter: the date on the yellow envelope)."
    )
    return named


def _today_anchor(ctx: RuleContext, trace: Trace) -> _Anchor:
    """A letter's "today" is the day it was written: its date, never the (later) day it is processed.

    Counting from the processing day would move the deadline later on every reprocess, and that day is
    neither stated in the letter nor confirmed by the person (SPEC § 21 rubric). Without the letter's date,
    the day the person entered as its arrival is the latest it can be dated (a court's letter: its envelope
    date), and only then the processing day — both with a warning that the real deadline may be earlier.
    """
    written = ctx.document_date
    if written is None and ctx.received_confirmed and ctx.received_date and ctx.received_date < ctx.today:
        # the letter can be dated at the latest the day it arrived: nearer its real date than today
        trace.hard(_undated_note(ctx.received_date))
        return _Anchor(ctx.received_date, "receipt")
    if written is None:
        trace.hard(
            "The letter counts from 'today', but its date is missing, so we counted from today — the real "
            "deadline may be earlier. Check the letter's date."
        )
        return _Anchor(ctx.today, "today")
    if written > ctx.today:
        trace.soft(
            f"The letter counts from 'today' but is dated later ({fmt_date(written)}); we counted from today, "
            "the earlier day."
        )
        return _Anchor(ctx.today, "today")
    trace.soft(
        f"The letter counts from 'today'; we took that to be the letter's date ({fmt_date(written)}), the "
        "earliest plausible start."
    )
    return _Anchor(written, "document_date")


def _apply_delivery(
    spec: DateSpec, ctx: RuleContext, trace: Trace, anchor: _Anchor, region: str | None
) -> tuple[date, str]:
    """Deemed delivery counted from ``anchor``; returns the event day and the summary's first clause."""
    if spec.delivery_rule == "none":
        trace.soft("The letter didn't say how it was sent; we assumed ordinary post.")
    channel = _CHANNEL_BY_RULE.get(spec.delivery_rule, "post")
    scope = ctx.delivery_scope
    if scope is None:
        trace.soft(
            "We couldn't tell which law governs this sender, so the delivery day was not moved off "
            "weekends (the earliest plausible date)."
        )
    stand_in = (
        " (the letter's date; the real posting day can only be later)"
        if anchor.source == "document_date"
        else ""
    )
    trace.step(f"Posting day: {fmt_date(anchor.day)}{stand_in}", anchor.day, "posting_day")
    delivery_region = region
    if scope == "ao" and calendar_de.normalize_region(ctx.recipient_region) != region:
        delivery_region = None  # regional holidays only count when they apply at both places
    delivery = resolve_delivery(anchor.day, scope=scope, channel=channel, region=delivery_region)
    trace.extend(delivery.steps)
    if delivery.uncertainty:
        trace.soft(delivery.uncertainty)
    if scope == "ao" and delivery_region is None:
        _check_fiction_day(trace, delivery.day, region, calendar_de.normalize_region(ctx.recipient_region))
    no_shift = None
    if scope != "ao" and not calendar_de.is_business_day(delivery.raw_day, region):
        no_shift = "this day does not move for this kind of letter"
    clause = delivery_clause(anchor.subject, delivery.raw_day, delivery.day, no_shift_note=no_shift)
    received = ctx.received_date if ctx.received_confirmed else None
    if received is not None and received < anchor.day:
        trace.soft(
            f"The letter arrived on {fmt_date(received)}, before its printed date — we count from the "
            "day it arrived to be safe. You may be able to get more time (Wiedereinsetzung)."
        )
        trace.step(f"Counting from the day it arrived, {fmt_date(received)}", received, "early_receipt")
        return received, f"The letter arrived on {fmt_date(received, year=False)}, before its printed date"
    if received is not None and received < delivery.day:
        trace.step(
            f"It arrived on {fmt_date(received)}, earlier than that — this does not change the date",
            received,
            "early_receipt",
        )
    return delivery.day, clause


def _check_fiction_day(trace: Trace, day: date, region: str | None, recipient: str | None) -> None:
    """Flag a tax letter's delivery day that may move for a regional holiday we could not apply.

    The holidays where the person lives decide (OFD Cottbus 2004); the engine only applies one that
    holds at both places, so a holiday at the person's home alone is flagged, one at the tax office alone
    is not.
    """
    if recipient is not None:
        if calendar_de.is_holiday(day, recipient):
            trace.soft(
                f"{fmt_date(day)} {HOME_HOLIDAY} ({calendar_de.REGION_NAMES[recipient]}); "
                "tax offices may then count the letter as delivered a working day later, so the deadline may "
                "be later too. We kept the earlier date."
            )
    elif region is None:
        check_regional_holidays(trace, [day])
    elif calendar_de.is_holiday(day, region):
        trace.soft(
            f"{fmt_date(day)} {TAX_OFFICE_HOLIDAY}; if you live in the same Land, the "
            "letter counts as delivered a working day later and the deadline may be later too."
        )


def _date_from(start: date, period: tuple[int, PeriodUnit], region: str | None, shift: bool) -> date:
    """The end of a period counted forward from ``start``, moved off a weekend or holiday if ``shift``."""
    end, _ = add_period(start, *period, region=region)
    return calendar_de.next_business_day(end, region) if shift else end


def _late_receipt_note(
    ctx: RuleContext,
    trace: Trace,
    event: date,
    due: date,
    period: tuple[int, PeriodUnit],
    region: str | None,
    shift: bool,
) -> None:
    """The note on a confirmed arrival after the deemed delivery day: the date from it, once shown.

    None when the arrival day gives the same date (a weekend or holiday between the two days).
    """
    received = ctx.received_date if ctx.received_confirmed else None
    if received is None or received <= event:
        return
    alt = _date_from(received, period, region, shift)
    if alt == due:
        return
    trace.warnings.append(
        f"{TOLD_ARRIVAL} {fmt_date(received)}, after the day it legally counts as delivered "
        f"({fmt_date(event)}). If you can show that (keep the envelope), the deadline may be "
        f"{fmt_date(alt)} instead — we still show the earlier, safe date." + _still_open(ctx, due, alt)
    )
    trace.use("late_receipt")


def _served(spec: DateSpec, ctx: RuleContext, trace: Trace) -> _Anchor | None:
    """The start of a period that runs from formal service, whatever anchor the letter was read with.

    The delivery day the person entered (the envelope date, § 180 ZPO) counts — unless the reading
    names a start of its own (an explicit start, or a delivery day on or after the letter's date) that
    is earlier: then that one, with a warning naming both (:func:`_against_entered`). Without either,
    as the anchor says (the letter's date, the earliest plausible start — :func:`_formal_service_note`
    asks for the envelope date)."""
    explicit = parse_date(spec.anchor_date) if spec.anchor == "explicit_date" else None
    if explicit is not None:
        return _against_entered(_Anchor(explicit, "explicit"), ctx, trace)
    stated = parse_date(spec.anchor_date) if spec.anchor == "receipt" else None
    if stated is not None and (ctx.document_date is None or stated >= ctx.document_date):
        return _resolve_anchor(spec, ctx, trace, served=True)
    if ctx.received_confirmed and ctx.received_date:
        if spec.anchor in _OWN_DATE_ANCHORS and ctx.document_date is None:
            trace.hard(_undated_note(ctx.received_date))
        return _Anchor(ctx.received_date, "receipt", served=True)
    return _resolve_anchor(spec, ctx, trace, served=True)


def _undated_note(received: date) -> str:
    """Why a period the letter counts from its own date ("ab heute") ran from the day it arrived."""
    return (
        f"The letter counts from its own date, which is missing; we counted from {fmt_date(received)}, the day "
        "you entered as its arrival — the latest it can be dated, so the real deadline may be earlier. Check "
        "the letter's date."
    )


def _formal_service_note(trace: Trace, spec: DateSpec, anchor: _Anchor, statute: str) -> None:
    """Fines, penal orders and court orders run from formal service, which the letter's date can only
    precede. A court order's envelope date is its start (§ 180 ZPO) even while it is unknown."""
    if anchor.source in ("explicit", "receipt", "stated_receipt") or spec.anchor == "receipt":
        if statute in _CIVIL_COURT:
            trace.use("zpo_180")
        return  # known, or already asked for ("when did it arrive?")
    if statute in _CIVIL_COURT:
        trace.use("zpo_180")
        trace.soft(
            "The period runs from delivery (Zustellung): the date the postman wrote on the yellow "
            f"envelope (§ 180 ZPO). We counted from {anchor.phrase}, which can only be earlier — "
            f"{ENTER_ENVELOPE_DATE}."
        )
        return
    trace.soft(
        "The period runs from formal delivery: the date written on the yellow envelope, or for an "
        "Übergabe-Einschreiben the 4th day after posting (§ 4 Abs. 2 VwZG). We counted from "
        f"{anchor.phrase}, which can only be earlier — {ENTER_ENVELOPE_DATE}."
    )


def _period(spec: DateSpec) -> tuple[int, PeriodUnit] | str:
    """A relative period's amount and unit, or why it cannot be computed at all."""
    if spec.amount is None or spec.unit is None:
        return "The length of the period could not be read."
    if abs(spec.amount) > MAX_PERIOD[spec.unit]:
        return f"A period of {fmt_period(spec.amount, spec.unit)} can't be right — please check the letter."
    return spec.amount, spec.unit


def period_problem(spec: DateSpec) -> str | None:
    """Why a relative period cannot be computed at all (its length unreadable or implausible), else ``None``:
    then :func:`compute_due` gives no date and applies no other rule."""
    found = _period(spec)
    return found if isinstance(found, str) else None


def may_be_public(spec: DateSpec, ctx: RuleContext) -> bool:
    """Whether a sender filed as private may be a public body after all.

    That a sender is no authority is read from its kind, name and words, not known: a municipal
    utility's Gebührenbescheid may be filed as a ``utility``, a statutory health insurer as an
    ``insurer`` (:data:`ordnung.rules.delivery.MAY_BE_PUBLIC_KINDS`; an unknown kind counts as one), and
    a letter filed under any kind may name an administrative act in the period's own words — its
    ``text`` and ``legal_basis``, and ``ctx.quote``, the sentence it was read from
    (:func:`ordnung.rules.delivery.shows_administrative_act`). Those words are no proof (a firm may
    write "nach Bekanntgabe der Preiserhöhung"), so they never bring deemed delivery back
    (:func:`from_arrival`); they only keep a late arrival from moving the date later.
    """
    return (
        ctx.sender_kind is None
        or ctx.sender_kind in MAY_BE_PUBLIC_KINDS
        or shows_administrative_act(f"{spec.legal_basis or ''} {spec.text} {ctx.quote or ''}")
    )


#: How a letter's own day reads by how it was sent: posted, sent electronically, or put in a portal.
_SENT_ON: dict[DeliveryChannel, str] = {
    "post": "posted on",
    "electronic": "sent on",
    "portal": "made available on",
}


@dataclass(frozen=True)
class _LateArrival:
    """A private sender's confirmed arrival after the day its letter would usually count as delivered.

    ``later`` is the date counted from the arrival day (``None`` for a period counted backwards)."""

    arrived: date
    posted: _Anchor
    channel: DeliveryChannel
    deemed: date
    later: date | None

    @property
    def usually(self) -> str:
        """How the capped start reads: "a letter dated … usually counts as delivered (…)"."""
        what = "dated" if self.posted.source == "document_date" else _SENT_ON[self.channel]
        usual = fmt_date(self.deemed)
        return f"a letter {what} {fmt_date(self.posted.day)} usually counts as delivered ({usual})"


def _private_late_arrival(
    read: DateSpec,
    ctx: RuleContext,
    arrived: date,
    region: str | None,
    *,
    period: tuple[int, PeriodUnit],
    place: str | None,
    shift: bool,
) -> _LateArrival | None:
    """A private sender's confirmed arrival day that the period does not run from, else ``None``.

    For a sender that :func:`may_be_public`, an arrival day after the day the letter ``read`` would
    count as delivered from an unknown authority (:func:`ordnung.rules.delivery.resolve_delivery`
    without a scope: its earliest plausible day) does not move the start later — the earliest plausible
    date (SPEC § 21). Both readings count from the later arrival only once it is shown: a private
    sender's letter takes effect when it arrives (§ 130 Abs. 1 BGB), and an authority's counts from a
    later arrival too (§ 41 Abs. 2 S. 3 VwVfG, § 122 Abs. 2 AO, § 37 Abs. 2 S. 3 SGB X).
    :func:`_private_late_note` says so and gives the date from the arrival day. A kind no public body
    goes by (a gym, a landlord, a bank …) whose words name no administrative act counts from the day it
    arrived — and so does any sender's letter when a ``period`` running forward ends on the same date
    from either day (a weekend or holiday in between): there is nothing to cap and nothing to warn about.
    """
    if not may_be_public(read, ctx):
        return None
    posted = _resolve_anchor(read, ctx, Trace())
    if posted is None:
        return None
    channel = _CHANNEL_BY_RULE.get(read.delivery_rule, "post")
    deemed = resolve_delivery(posted.day, scope=None, channel=channel, region=region).day
    if arrived <= deemed:
        return None
    if period[0] < 0:
        return _LateArrival(arrived, posted, channel, deemed, None)
    later = _date_from(arrived, period, place, shift)
    if later == _date_from(deemed, period, place, shift):
        return None
    return _LateArrival(arrived, posted, channel, deemed, later)


def _private_late_note(trace: Trace, ctx: RuleContext, late: _LateArrival, due: date) -> None:
    """The warning for a late arrival the period did not run from, in place of "runs from the day it
    arrived", with one level less confidence: the sender's kind was read, and the later date may hold."""
    later = late.later
    may_be = f"may be {fmt_date(later)}" if later is not None else "may be later"
    trace.soft(
        f"{TOLD_ARRIVAL} {fmt_date(late.arrived)}, later than {late.usually}. If you can show that (keep the "
        f"envelope), the deadline {may_be}, whether or not the sender is an authority; we show the earlier, "
        "safe date." + _still_open(ctx, due, later)
    )


def _still_open(ctx: RuleContext, due: date, later: date | None) -> str:
    """A late-arrival note's last words when the date shown has passed but the one from arrival has not."""
    if later is None or due >= ctx.today or later < ctx.today:
        return ""
    return " The earlier date has passed, the later one has not: the deadline may still be open."


#: Letters from a court: none of their dates is ever ``high`` (brief C1, SPEC § 21).
_COURT_LETTERS = ("court_payment_order", "enforcement_order")
_COURT_LETTER_NOTE = (
    "This date is on a court order. Ordnung's date is information, not legal advice — get advice (see the "
    "card on this letter)."
)
#: Any other letter from a court (not filed as a court order).
_COURT_SENDER_NOTE = (
    "This is a court's letter: its periods usually run from delivery (Zustellung, the date on the yellow "
    "envelope), never from a 4-day rule. Ordnung's date is information, not legal advice — get advice if "
    "a lot is at stake."
)
#: What each court deadline means for the person (a soft note: court dates are never ``high``).
_COURT_NOTES: dict[str, str] = {
    "zpo_692": (
        "This is a court deadline. Ordnung's date is information, not legal advice — if you don't owe the "
        "money, object in time and get advice (see the card on this letter)."
    ),
    "zpo_339": (
        "This is a court deadline that can't be extended (Notfrist), and the order can be enforced "
        "meanwhile. Get advice now (see the card on this letter)."
    ),
    "arbgg_46a": (
        "This is a labour court's deadline: one week, not two (§ 46a Abs. 3 ArbGG). Ordnung's date is "
        "information, not legal advice — if you don't owe the money, object in time and get advice."
    ),
    "arbgg_59": (
        "This is a labour court's deadline that can't be extended: one week (Notfrist, § 59 ArbGG), and the "
        "order can be enforced meanwhile. Get advice now (see the card on this letter)."
    ),
    "kschg_4": (
        "This is the deadline for a court action at the labour court (Kündigungsschutzklage). Ordnung "
        "can't draft or file it — get advice now from a union, an employment lawyer or the court's "
        "Rechtsantragstelle."
    ),
}


def _court_notes(trace: Trace, spec: DateSpec, ctx: RuleContext) -> None:
    """Court deadlines and every date on a court order are never ``high``, whatever the DateSpec's
    type: a soft note says why, and the court rule is cited. Only a date of a nature the court rule
    binds is one (:func:`_statute`): a hearing or a severance payment that mentions the court action
    is not."""
    statute = (_statute(spec, ctx.letter_kind, labour_court=ctx.labour_court) or (None, ()))[0]
    if statute in _COURT_NOTES:
        trace.use(statute)
        trace.soft(_COURT_NOTES[statute])
    elif ctx.letter_kind in _COURT_LETTERS:
        trace.soft(_COURT_LETTER_NOTE)
    elif ctx.court:
        trace.soft(_COURT_SENDER_NOTE)
    if statute in ("zpo_692", "arbgg_46a"):
        trace.warnings.append(
            "A late objection still counts until the enforcement order is issued (§ 694 ZPO) — but don't "
            "rely on that."
        )


def _compute_relative(
    spec: DateSpec, ctx: RuleContext, trace: Trace, postal_buffer_days: int
) -> ComputationReceipt:
    region = calendar_de.normalize_region(ctx.region)
    place = place_region(spec, ctx)
    found = _period(spec)
    if isinstance(found, str):
        return _no_date(trace, ctx, found)
    amount, unit = found
    period = fmt_period(amount, unit)
    read = spec
    counted = from_arrival(spec, ctx)
    no_delivery, spec = counted is not spec, counted
    # a period from delivery now runs from arrival (the app asks for that day); one from a date stays there
    from_receipt = no_delivery and spec.anchor == "receipt"
    # the arrival day the period then runs from (from_arrival dropped any stated day), unless it came late
    arrived = ctx.received_date if from_receipt and ctx.received_confirmed else None
    late = (
        _private_late_arrival(
            read, ctx, arrived, region, period=(amount, unit), place=place, shift=_shift_applies(spec)
        )
        if arrived is not None
        else None
    )
    if no_delivery and late is None:
        trace.warnings.append(PRIVATE_SENDER_WARNING if from_receipt else PRIVATE_SENDER_DATED_WARNING)
    statute, statutory_periods = _statute(spec, ctx.letter_kind, labour_court=ctx.labour_court) or (None, ())
    if statute == "kschg_4":
        trace.cite.update(_BGB_COUNTING)
    elif statute in _CIVIL_COURT or ctx.court:
        labour = ctx.labour_court or statute in ("arbgg_46a", "arbgg_59")
        social = ctx.social_court and statute is None
        trace.cite.update(
            _LABOUR_COURT_COUNTING if labour else _SOCIAL_COURT_COUNTING if social else _COURT_COUNTING
        )
    # Fines, penal orders and a court's letters run from formal service (yellow envelope, § 4 VwZG,
    # § 180 ZPO), never from the 4th-day fiction of ordinary authority letters: without the envelope
    # date the letter's own date is the earliest plausible start (legal research
    # owig_einspruch_bussgeldbescheid_2_wochen); with it, that date, whatever anchor the letter was read with.
    formal = statute in _FORMAL_SERVICE or ctx.court
    # ... except a court's own period that the letter counts from its own date ("binnen zwei Wochen ab dem
    # Datum dieses Schreibens"): a court may set another start than delivery (§ 221 ZPO), so the envelope
    # date entered never moves it later. A statute's period (a Mahnbescheid's) always runs from delivery.
    # Without the letter's date, though, the envelope date is the latest it can be dated: counted from there.
    served = statute in _FORMAL_SERVICE or (
        ctx.court and (spec.anchor not in _OWN_DATE_ANCHORS or ctx.document_date is None)
    )
    anchor = _served(spec, ctx, trace) if served else _resolve_anchor(spec, ctx, trace)
    if anchor is None:
        if from_receipt:  # the rule that makes the app ask for the arrival day, even without a date
            trace.step(
                "Not an authority's letter, so no delivery days: the period runs from the day it arrived",
                None,
                "private_sender_arrival",
            )
        return _receipt(
            trace,
            ctx,
            due=None,
            summary="No date could be computed: the start date is missing.",
            region=place,
        )
    if late is not None:
        trace.step(
            f"It arrived on {fmt_date(late.arrived)}, later than {late.usually}: we count from that earlier, "
            "safe day",
            late.deemed,
            "private_sender_late_arrival",
        )
        anchor = _Anchor(late.deemed, "deemed")
    elif no_delivery:
        trace.step(
            f"Not an authority's letter, so no delivery days: the period runs from {anchor.phrase}",
            anchor.day,
            "private_sender_arrival" if from_receipt else "private_sender_no_delivery",
        )
    uses_delivery = not formal and (
        spec.anchor == "deemed_delivery"
        or (spec.delivery_rule != "none" and spec.anchor in ("document_date", "explicit_date"))
    )
    if uses_delivery:
        event, lead = _apply_delivery(spec, ctx, trace, anchor, region)
        relation = "later"
    else:
        event, lead = anchor.day, ""
        relation = f"after {anchor.phrase}"

    backward = amount < 0
    counted_back_from: date | None = None
    if not backward:
        raw_end, steps = add_period(event, amount, unit, region=place)
        trace.step(f"Counting starts the day after {fmt_date(event)}", event, "bgb_187_1")
        trace.extend(steps[1:])
        if (
            statute
            and statutory_periods
            and not any(_same_period((amount, unit), p) for p in statutory_periods)
        ):
            legal = statutory_periods[0]
            legal_end, _ = add_period(event, *legal, region=place)
            trace.soft(
                f"The letter says {period}, but the law ({catalog.citation(statute)}) gives "
                f"{fmt_period(*legal)} — please check. We use the earlier of the two dates."
            )
            if legal_end < raw_end:
                raw_end, period = legal_end, fmt_period(*legal)
                trace.step(
                    capitalize_first(f"{period} later (statutory period): {fmt_date(raw_end)}"),
                    raw_end,
                    statute,
                )
        if unit in ("business_days", "werktage") and place is None:
            check_regional_holidays(
                trace, (event + timedelta(days=i) for i in range(1, (raw_end - event).days + 1))
            )
    else:
        inclusive_end = event if spec.nature == "notice" else event - timedelta(days=1)
        raw_end = latest_receipt_for(inclusive_end, -amount, unit, place)
        if unit in ("business_days", "werktage"):
            counted_back_from = inclusive_end
        relation = f"before {anchor.phrase}"
        trace.step(
            capitalize_first(f"{period} before {fmt_date(event)}: it must arrive by {fmt_date(raw_end)}"),
            raw_end,
            "bgb_188",
        )
        if unit in ("business_days", "werktage") and place is None:
            # A regional holiday among the days counted back does not count there: the date is earlier.
            counts = calendar_de.is_werktag if unit == "werktage" else calendar_de.is_business_day
            span = (raw_end + timedelta(days=i) for i in range(1, (inclusive_end - raw_end).days + 1))
            check_regional_holidays(trace, (d for d in span if counts(d)), later=False)

    if statute is not None:
        trace.use(statute)
    if statute == "owig_55":
        trace.soft(
            "This reply date is a request, not a legal deadline (§ 55 OWiG). You must give your "
            "personal details; the binding two-week deadline only starts when a fine notice "
            "(Bußgeldbescheid) is formally delivered."
        )
    if statute in _FORMAL_SERVICE:
        _formal_service_note(trace, spec, anchor, statute)
    if ctx.court and served and spec.anchor != "explicit_date":
        # a court's periods run from delivery (the envelope date, § 180 ZPO): cited, so the person is
        # asked "when was it delivered?", never "when did it arrive?" with today filled in
        trace.use("zpo_180")
    if statute == "klage_1_month":
        trace.soft(
            "This is the deadline for a court action (Klage). Ordnung can't draft or file court actions — "
            "get advice (e.g. a Verbraucherzentrale or a lawyer) well before this date."
        )

    due, safe = raw_end, None
    shift = _shift_applies(spec)
    if shift and not backward:
        due, steps = shift_to_business_day(raw_end, place, _shift_rule_id(ctx, statute))
        trace.extend(steps)
        if place is None:
            check_regional_holidays(trace, [due])
    elif spec.nature == "notice" or shift:
        # § 193 BGB only extends periods that run forward: "one month before …" must never end later.
        safe = _safe_date(trace, raw_end, place, backward=spec.nature != "notice")
        if place is None:
            check_regional_holidays(trace, [raw_end], later=False)
    if uses_delivery and not backward:
        _late_receipt_note(ctx, trace, event, due, (amount, unit), place, shift)
    if late is not None:
        _private_late_note(trace, ctx, late, due)

    send_by = (
        _send_by(trace, ctx, due, spec.nature, place, postal_buffer_days)
        if spec.nature in _SEND_BY_NATURES
        else None
    )
    check_partial_holidays(
        trace,
        place,
        due,
        send_by=send_by,
        safe=safe,
        moves=shift and not backward,
        counted_back_from=counted_back_from,
        werktage=unit == "werktage",
    )
    end = _end_clause(raw_end, due, place, safe=safe, backward=backward and spec.nature != "notice")
    summary = due_sentence(lead, period, relation, end)
    return _receipt(trace, ctx, due=due, summary=summary, send_by=send_by, safe_date=safe, region=place)


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
            # the letter rules build on this module's receipts, so they are imported where needed
            from ordnung.rules.letters import compute_letter_date

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
