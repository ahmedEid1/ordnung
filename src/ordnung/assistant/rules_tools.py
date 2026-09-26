"""Ordnung's German date rules as MCP tools that need no ledger (``ordnung mcp --rules-only``).

The model reads, code computes (ADR 0002) — also for other clients: Claude Desktop or Claude Code
can hand :meth:`RulesTools.compute_deadline` what a letter *says* (the extractor's ``DateSpec``) and
get the date the rules engine computes, with its steps, rule ids, citations, warnings and
confidence. :meth:`RulesTools.german_holidays`, :meth:`RulesTools.add_working_days` and
:meth:`RulesTools.check_iban` expose the calendar and the IBAN check the app itself uses.

Policies:

* **Nothing personal.** The tools read no data folder, write nothing and call no model. They only
  compute from their arguments, so the rules-only server exposes nothing about the person.
* **Strict input.** A ``spec`` is validated against the ``DateSpec`` model with unknown keys
  refused, and its ``date`` and ``anchor_date`` must be written ``YYYY-MM-DD``; unknown tool
  arguments are refused too. A misspelt field or a date in another format must fail loudly, never
  be dropped silently and change the date. Every argument error names the argument and what is
  allowed, in plain words.
* **Same answers as the app.** The delivery law follows the sender's kind and name exactly as in
  the pipeline (:func:`ordnung.rules.scope_for_party_kind`); the spec's own words (``text``,
  ``legal_basis``) stand in for the letter's remedy notice. Missing facts are never guessed: the
  engine uses the earliest plausible date and says so, and ``hints`` name the argument that would
  settle it (and never one that was given).
* **A model's arrival day is checked.** In the app a person enters ``received_date``; here a model
  passes it, so it is checked first: a day after today is refused, and when the period runs from
  the arrival day, one before the letter's date or more than :data:`LATE_ARRIVAL_DAYS` days after
  it gets a warning and one level less confidence (a wrong arrival day moves the deadline).
* **No letter text in results.** Results are built by code from the engine's receipt and the
  normalised arguments; the spec's ``text`` and the sender's name are not echoed. So results are
  plain JSON, not wrapped as untrusted document text.
* **Information, not legal advice.** Every result carries :data:`DISCLAIMER`.

"Today" is the caller's ``today``, else the server's (``ORDNUNG_TODAY``, a test's pinned day), else
the date in Germany (:data:`HOME_ZONE`) — never the machine's own time zone.

Heavy modules (the rules engine, the holiday calendar, the MCP SDK) are imported on first use.
"""

from __future__ import annotations

import functools
import json
import re
import sys
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Annotated, Any, Literal, get_args
from zoneinfo import ZoneInfo

from pydantic import ConfigDict, Field, ValidationError, field_validator

from ordnung.models import DateSpec, PartyKind, RemedyType

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer
    from mcp.server.mcpserver.tools import Tool

    from ordnung.models import ComputationReceipt, Confidence

SERVER_NAME = "ordnung_rules"
INSTRUCTIONS = (
    "Ordnung's tested rules engine for German deadlines: give compute_deadline what a letter says "
    "(a DateSpec) and get the date the rules give, with its legal steps, citations and warnings — "
    "where facts are missing, the earliest plausible date, and hints on what would settle it; "
    "german_holidays, add_working_days and check_iban answer calendar and IBAN questions. The tools "
    "compute; you read the letter. Results are information, not legal advice."
)
DISCLAIMER_TEMPLATE = (
    "Information, not legal advice: computed by Ordnung's rules engine from the facts given (German "
    "law as of {checked}), not reviewed by a lawyer. Check the result against the letter and get "
    "advice when a lot is at stake."
)
IBAN_NOTE = (
    "A well-formed IBAN says nothing about who owns the account. Compare it with earlier letters or "
    "the sender's official website; if a letter or e-mail says the account has changed, confirm that "
    "through contact details you already know before paying."
)
#: Holidays that apply in parts of a Land only: left out of the calendar (see :data:`PARTIAL_HOLIDAYS_NOTE`).
PARTIAL_HOLIDAYS: dict[str, str] = {
    "BY": "Assumption Day (15 August) in communities with a Catholic majority and the Augsburg Peace "
    "Festival (8 August) in Augsburg",
    "SN": "Corpus Christi in some communities of the Sorbian area",
    "TH": "Corpus Christi in some communities with a Catholic majority",
}
PARTIAL_HOLIDAYS_NOTE = (
    "Only holidays of the whole Land are counted. Left out because they hold only in parts of it: "
    "{what}. Where one of them applies, a date counted forward can only come out earlier than the real "
    "one, but a date counted backwards (a send-by date, negative working days) can come out a day late."
)
NATIONWIDE_NOTE = "Nationwide holidays only: pass region (a Land code such as BY or NW) for its own ones."
#: How the engine's warning starts when a regional holiday could move a date (``check_regional_holidays``).
REGION_UNKNOWN_WARNING = "Holiday region unknown"
#: The engine's warnings when a tax letter's delivery day is a holiday at one of the two places only.
TAX_OFFICE_HOLIDAY_WARNING = "is a public holiday where the tax office is"
HOME_HOLIDAY_WARNING = "is a public holiday where you live"
#: The rule the engine applies when a Land's 4-day rule for its authorities is not confirmed.
LAND_DAYS_RULE = "vwvfg_land_days"
#: Where "today" is when neither the caller nor the server pins it: Ordnung's letters are German.
HOME_ZONE = "Europe/Berlin"
#: An arrival day this many days after the letter's date is unusual for post (checked, see module docstring).
LATE_ARRIVAL_DAYS = 14
_ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_LOWER: dict[str, Confidence] = {"high": "medium", "medium": "low", "low": "low"}
DayType = Literal["business_days", "werktage"]
DAY_TYPES: tuple[str, ...] = get_args(DayType)
MIN_YEAR = 1991  # the first full year of today's nationwide holidays (3 October)
MAX_YEAR = 2100
MAX_WORKING_DAYS = 1000
MAX_LISTED_SKIPS = 40
MAX_IBAN_INPUT = 64
_DELIVERY_LAW = {
    "ao": "tax law (§ 122 AO)",
    "vwvfg": "general administrative law (§ 41 VwVfG)",
    "sgbx": "social law (§ 37 SGB X)",
}
_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


class RulesToolError(ValueError):
    """A tool argument is invalid (the message tells the caller how to fix the call)."""


class DateSpecArg(DateSpec):
    """A ``DateSpec`` as a tool argument: the same fields, unknown keys refused, dates ``YYYY-MM-DD``.

    The engine reads a date it cannot parse as "no date" — right for a letter, wrong for a tool
    argument: ``anchor_date: "02.01.2026"`` would silently drop a stated posting day.
    """

    model_config = ConfigDict(extra="forbid")

    @field_validator("date", "anchor_date", mode="before")
    @classmethod
    def _iso_day(cls, value: Any) -> Any:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        if isinstance(value, str) and _ISO_DAY.match(value.strip()):
            try:
                date.fromisoformat(value.strip())
            except ValueError:
                pass
            else:
                return value.strip()
        shown = repr(value[:40]) if isinstance(value, str) else type(value).__name__
        raise ValueError(f"must be a date written YYYY-MM-DD, or null (got {shown})")


# --------------------------------------------------------------------------------------------------
# the tools
# --------------------------------------------------------------------------------------------------


class RulesTools:
    """The answers behind the rules tools; each method returns JSON-ready data."""

    def __init__(self, today: Callable[[], date] | None = None) -> None:
        """``today`` is the default "today" (the app's simulated day, a test's pinned day)."""
        self._today = today

    def current_day(self) -> date:
        """The pinned day, else ``ORDNUNG_TODAY``, else today in Germany (:data:`HOME_ZONE`)."""
        if self._today is not None:
            return self._today()
        from ordnung import clock

        if clock.simulated():
            return clock.today()
        return datetime.now(ZoneInfo(HOME_ZONE)).date()

    def compute_deadline(
        self,
        spec: DateSpec | dict[str, Any],
        *,
        document_date: str | None = None,
        sender_kind: str | None = None,
        sender_name: str | None = None,
        remedy_type: str | None = None,
        region: str | None = None,
        recipient_region: str | None = None,
        received_date: str | None = None,
        today: str | None = None,
    ) -> dict[str, Any]:
        """The date a ``DateSpec`` describes, computed by the rules engine, with its receipt."""
        from ordnung.rules import RuleContext, compute_due, scope_for_party_kind

        parsed = parse_spec(spec)
        _check_choice("sender_kind", sender_kind, get_args(PartyKind))
        _check_choice("remedy_type", remedy_type, get_args(RemedyType))
        day = _optional_day("today", today) or self.current_day()
        letter_day = _optional_day("document_date", document_date)
        received = _optional_day("received_date", received_date)
        if received is not None and received > day:
            raise RulesToolError(
                f"received_date ({received.isoformat()}) is after today ({day.isoformat()}): pass the day "
                "the letter actually arrived, or leave it out"
            )
        scope = scope_for_party_kind(
            sender_kind,
            name=sender_name,
            remedy_type=remedy_type,
            remedy_text=f"{parsed.legal_basis or ''} {parsed.text}",
        )
        context = RuleContext(
            today=day,
            region=_region("region", region),
            document_date=letter_day,
            received_date=received,
            received_confirmed=received is not None,
            delivery_scope=scope,
            recipient_region=_region("recipient_region", recipient_region),
        )
        receipt = arrival_checked(
            compute_due(parsed, context), parsed, letter_day=letter_day, received=received
        )
        return {
            "due_date": receipt.due_date,
            "weekday": _weekday(receipt.due_date),
            "send_by": receipt.send_by,
            "safe_date": receipt.safe_date,
            "summary": receipt.summary,
            "confidence": receipt.confidence,
            "warnings": receipt.warnings,
            "steps": [step.model_dump() for step in receipt.steps],
            "rules": _rules(receipt),
            "assumed": {
                "today": day.isoformat(),
                "letter_date": letter_day.isoformat() if letter_day else None,
                "received_date": received.isoformat() if received else None,
                "delivery_law": _DELIVERY_LAW.get(scope or ""),
                "holiday_calendar": receipt.holiday_calendar,
            },
            "hints": deadline_hints(
                parsed,
                receipt,
                letter_day=letter_day,
                received=received,
                scope=scope,
                sender_kind=sender_kind,
                region=context.region,
                recipient_region=context.recipient_region,
            ),
            "disclaimer": disclaimer(),
        }

    def german_holidays(self, year: int, region: str | None = None) -> dict[str, Any]:
        """The public holidays of ``year``: nationwide ones, plus the Land's own for ``region``."""
        from ordnung.rules.calendar_de import holiday_calendar_label, holiday_name

        if isinstance(year, bool) or not isinstance(year, int) or not MIN_YEAR <= year <= MAX_YEAR:
            raise RulesToolError(f"year must be a whole number from {MIN_YEAR} to {MAX_YEAR}")
        code = _region("region", region)
        rows = []
        day = date(year, 1, 1)
        while day.year == year:
            name = holiday_name(day, code)
            if name is not None:
                rows.append(
                    {
                        "date": day.isoformat(),
                        "weekday": _WEEKDAYS[day.weekday()],
                        "name": name,
                        "nationwide": holiday_name(day, None) is not None,
                    }
                )
            day += timedelta(days=1)
        return {
            "year": year,
            "region": code,
            "calendar": holiday_calendar_label(code),
            "holidays": rows,
            "note": NATIONWIDE_NOTE
            if code is None
            else PARTIAL_HOLIDAYS_NOTE.format(what=PARTIAL_HOLIDAYS[code])
            if code in PARTIAL_HOLIDAYS
            else None,
            "disclaimer": disclaimer(),
        }

    def add_working_days(
        self, start: str, days: int, day_type: str = "business_days", region: str | None = None
    ) -> dict[str, Any]:
        """The day ``days`` working days after (or, negative, before) ``start``; ``start`` not counted."""
        from ordnung.rules.calendar_de import (
            add_business_days,
            add_werktage,
            day_kind,
            holiday_calendar_label,
        )

        first = _day("start", start)
        if isinstance(days, bool) or not isinstance(days, int) or abs(days) > MAX_WORKING_DAYS:
            raise RulesToolError(
                f"days must be a whole number from -{MAX_WORKING_DAYS} to {MAX_WORKING_DAYS}"
            )
        _check_choice("day_type", day_type, DAY_TYPES)
        code = _region("region", region)
        werktage = day_type == "werktage"
        try:
            result = (add_werktage if werktage else add_business_days)(first, days, code)
        except OverflowError as exc:
            raise RulesToolError("the result would be outside the calendar") from exc
        skipped = []
        step = timedelta(days=1 if days >= 0 else -1)
        day = first
        while day != result:
            day += step
            kind = day_kind(day, code)
            if kind is not None and not (werktage and kind == "Saturday"):
                skipped.append({"date": day.isoformat(), "weekday": _WEEKDAYS[day.weekday()], "reason": kind})
        return {
            "start": first.isoformat(),
            "days": days,
            "day_type": day_type,
            "date": result.isoformat(),
            "weekday": _WEEKDAYS[result.weekday()],
            "skipped": skipped[:MAX_LISTED_SKIPS],
            "skipped_more": len(skipped) - MAX_LISTED_SKIPS if len(skipped) > MAX_LISTED_SKIPS else None,
            "counting": ("Werktage: Monday to Saturday" if werktage else "Business days: Monday to Friday")
            + ", public holidays excluded; the start day itself is not counted.",
            "calendar": holiday_calendar_label(code),
            "note": PARTIAL_HOLIDAYS_NOTE.format(what=PARTIAL_HOLIDAYS[code])
            if code in PARTIAL_HOLIDAYS
            else None,
            "disclaimer": disclaimer(),
        }

    def check_iban(self, iban: str) -> dict[str, Any]:
        """Country, length, checksum and (where known) the bank code an IBAN carries."""
        from ordnung.money.iban import grouped, inspect_iban

        if not isinstance(iban, str) or not iban.strip():
            raise RulesToolError("iban must be the IBAN as printed, e.g. DE89 3704 0044 0532 0130 00")
        if len(iban) > MAX_IBAN_INPUT:
            raise RulesToolError(f"iban is too long: an IBAN has at most 34 characters (got {len(iban)})")
        check = inspect_iban(iban)
        return {
            "iban": grouped(check.iban),
            "valid": check.valid,
            "problems": check.problems,
            "country": {"code": check.country_code, "name": check.country} if check.country_code else None,
            "length": {"expected": check.length_expected, "actual": len(check.iban)},
            "checksum_ok": check.checksum_ok,
            "bank_code": {"label": check.bank_label, "value": check.bank_code} if check.bank_code else None,
            "branch_code": {"label": check.branch_label, "value": check.branch_code}
            if check.branch_code
            else None,
            "account_number": check.account_number,
            "note": IBAN_NOTE,
            "disclaimer": disclaimer(),
        }


# --------------------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------------------


def disclaimer() -> str:
    from ordnung.rules import LAST_CHECKED

    return DISCLAIMER_TEMPLATE.format(checked=LAST_CHECKED)


def parse_spec(spec: DateSpec | dict[str, Any]) -> DateSpec:
    """``spec`` validated strictly (unknown keys refused), as a plain ``DateSpec``."""
    raw = spec.model_dump() if isinstance(spec, DateSpec) else spec
    if not isinstance(raw, dict):
        raise RulesToolError("spec must be an object with the DateSpec fields (type, date, anchor, …)")
    try:
        checked = DateSpecArg.model_validate(raw)
    except ValidationError as exc:
        raise RulesToolError(spec_problems(exc)) from exc
    return DateSpec.model_validate(checked.model_dump())


def spec_problems(exc: ValidationError) -> str:
    """A validation error as one line per problem, e.g. ``spec.unit: Input should be 'days', …``."""
    lines = []
    for error in exc.errors():
        where = ".".join(str(part) for part in ("spec", *error["loc"]))
        if error["type"] == "extra_forbidden":
            allowed = ", ".join(DateSpec.model_fields)
            lines.append(f"{where}: unknown field (a DateSpec has: {allowed})")
        else:
            lines.append(f"{where}: {_message(error)}")
    return "invalid spec — " + "; ".join(lines)


def argument_problems(tool: str, exc: ValidationError, allowed: list[str]) -> str:
    """A tool's argument errors as one line, e.g. ``sender_kind: Input should be 'authority', …``.

    Plain words only (no pydantic type codes or links); an unknown argument names the ones allowed.
    """
    lines = []
    for error in exc.errors():
        where = ".".join(str(part) for part in error["loc"]) or "arguments"
        if error["type"] == "extra_forbidden":
            lines.append(f"{where}: unknown argument ({tool} takes: {', '.join(allowed)})")
        elif error["type"] == "missing":
            lines.append(f"{where}: required")
        else:
            lines.append(f"{where}: {_message(error)}")
    return "invalid arguments — " + "; ".join(lines)


def _message(error: Any) -> str:
    """A pydantic error's message without the "Value error, " prefix of a validator's own words."""
    message = str(error["msg"])
    return message.removeprefix("Value error, ") if error["type"] == "value_error" else message


def arrival_checked(
    receipt: ComputationReceipt, spec: DateSpec, *, letter_day: date | None, received: date | None
) -> ComputationReceipt:
    """``receipt`` with a warning and one level less confidence for an implausible arrival day.

    Only where the period runs from the arrival day (``anchor: receipt``): elsewhere the engine
    already treats an arrival day it is given (deemed delivery keeps the earlier, safe day).
    """
    if received is None or letter_day is None or spec.type != "relative" or spec.anchor != "receipt":
        return receipt
    gap = (received - letter_day).days
    if gap < 0:
        warning = (
            f"The arrival day given ({_long(received)}) is before the letter's date ({_long(letter_day)}). "
            "A letter rarely arrives before the date printed on it — check both dates: a wrong arrival "
            "day gives a wrong deadline."
        )
    elif gap > LATE_ARRIVAL_DAYS:
        warning = (
            f"The arrival day given ({_long(received)}) is {gap} days after the letter's date "
            f"({_long(letter_day)}), which is unusually late for post. Check it: a later arrival day "
            "moves the deadline later. If it is right, keep the envelope as proof."
        )
    else:
        return receipt
    return receipt.model_copy(
        update={"warnings": [*receipt.warnings, warning], "confidence": _LOWER[receipt.confidence]}
    )


def _long(day: date) -> str:
    return f"{_WEEKDAYS[day.weekday()][:3]} {day.day} {day.strftime('%b %Y')}"


def deadline_hints(
    spec: DateSpec,
    receipt: ComputationReceipt,
    *,
    letter_day: date | None,
    received: date | None,
    scope: str | None,
    sender_kind: str | None = None,
    region: str | None = None,
    recipient_region: str | None = None,
) -> list[str]:
    """Which missing argument would settle what the engine had to assume (empty when none).

    Only arguments that were *not* given are named; for a sender whose kind has no deemed-delivery
    rule, the hint says so instead of asking for the kind again.
    """
    hints: list[str] = []
    delivered = "posting_day" in receipt.rule_ids  # the deemed-delivery step ran
    if spec.type == "relative":
        anchor = spec.anchor or "document_date"
        counts_from_letter = anchor in ("document_date", "deemed_delivery", "today") or (
            anchor == "receipt" and received is None
        )
        if counts_from_letter and letter_day is None and not spec.anchor_date:
            hints.append(
                "Pass document_date: the date printed on the letter, which the period counts from"
                + (" ('today' in a letter is the day it was written)." if anchor == "today" else ".")
            )
        if anchor == "receipt" and received is None:
            hints.append(
                "Pass received_date if you know the day the letter arrived; until then the letter's date "
                "is used (the earliest plausible start)."
            )
        if anchor == "explicit_date" and not spec.anchor_date:
            hints.append("Set spec.anchor_date to the day the period runs from.")
    if spec.type == "relative" and scope is None and (delivered or spec.anchor == "deemed_delivery"):
        if not sender_kind:
            hints.append(
                "Pass sender_kind (tax_office, authority, immigration_office, health_insurer, university …) "
                "and sender_name so the right delivery law applies; without them the earliest plausible "
                "date is used."
            )
        else:
            hints.append(
                f"No deemed-delivery rule applies to a sender of kind {sender_kind}: those rules are for "
                "authorities. If the letter is from an authority, pass its kind (authority, tax_office …); "
                "otherwise use anchor document_date or receipt and delivery_rule none."
            )
    not_an_authority = sender_kind is not None and scope is None
    if region is None and LAND_DAYS_RULE in receipt.rule_ids and not not_an_authority:
        hints.append(
            "Pass region — the Land of the authority: where its own law is confirmed to use the 4-day "
            "rule (e.g. NW or BY), the letter counts as delivered a day later, and so may the deadline."
        )
    if recipient_region is None and _warned(receipt, TAX_OFFICE_HOLIDAY_WARNING):
        hints.append(
            "Pass recipient_region — the Land where the person lives: if it is the tax office's Land, "
            "its holiday moves the delivery day and the deadline a day later."
        )
    if region is None and _warned(receipt, HOME_HOLIDAY_WARNING):
        hints.append(
            "Pass region — the tax office's Land: if it is where the person lives, that holiday moves the "
            "delivery day and the deadline a day later."
        )
    if _warned(receipt, REGION_UNKNOWN_WARNING, start=True):
        hints.append(
            "Pass region — the Land of the office or company (for a payment to a company or person: "
            "recipient_region, the payer's Land; for a tax letter both). A regional holiday may make "
            "this date later."
        )
    return hints


def _warned(receipt: ComputationReceipt, text: str, *, start: bool = False) -> bool:
    return any(w.startswith(text) if start else text in w for w in receipt.warnings)


def _rules(receipt: ComputationReceipt) -> list[dict[str, Any]]:
    from ordnung.rules import RULES

    wanted = dict.fromkeys([*receipt.rule_ids, *(s.rule_id for s in receipt.steps if s.rule_id)])
    return [
        RULES[rid].model_dump(include={"id", "title", "citation", "url"}) for rid in wanted if rid in RULES
    ]


def _weekday(value: str | None) -> str | None:
    return _WEEKDAYS[date.fromisoformat(value).weekday()] if value else None


def _check_choice(name: str, value: str | None, choices: tuple[str, ...]) -> None:
    if value is not None and value not in choices:
        raise RulesToolError(f"{name} must be one of: {', '.join(choices)}")


def _day(name: str, value: str) -> date:
    if not isinstance(value, str):
        raise RulesToolError(f"{name} must be a date written YYYY-MM-DD")
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise RulesToolError(f"{name} must be a date written YYYY-MM-DD (got {value[:40]!r})") from exc


def _optional_day(name: str, value: str | None) -> date | None:
    return None if value is None or not str(value).strip() else _day(name, value)


def _region(name: str, value: str | None) -> str | None:
    """A Land code from a code or name; ``None`` for no region; an error for an unknown one."""
    from ordnung.rules.calendar_de import REGION_NAMES, normalize_region

    if value is None:
        return None
    if not isinstance(value, str):
        raise RulesToolError(f"{name} must be a German Land code such as NW, or null")
    if not value.strip():
        return None
    code = normalize_region(value)
    if code is None:
        raise RulesToolError(
            f"{name} must be a German Land: one of {', '.join(REGION_NAMES)} (or its name), or null"
        )
    return code


#: Result fields kept even when empty: "no due date" must be visible, not an absent key.
ALWAYS_SHOWN = frozenset({"due_date"})


def compact(value: Any, *, top: bool = True) -> Any:
    """Drop ``None`` and empty strings, and (below the top level) empty lists and objects.

    :data:`ALWAYS_SHOWN` fields stay at the top level, as ``null`` when empty.
    """
    if isinstance(value, dict):
        kept = {key: compact(item, top=False) for key, item in value.items()}
        return {
            k: v
            for k, v in kept.items()
            if (top and k in ALWAYS_SHOWN) or (v is not None and v != "" and (top or v not in ([], {})))
        }
    if isinstance(value, list):
        return [compact(item, top=False) for item in value]
    return value


def render(data: dict[str, Any]) -> str:
    """A tool result as compact JSON (what the model reads). A success is always a JSON object."""
    return json.dumps(compact(data), ensure_ascii=False, separators=(",", ":"))


def _spec_schema(schema: dict[str, Any]) -> None:
    """Give the ``spec`` argument the full ``DateSpec`` schema (enums included) in the tool listing.

    The argument itself is a plain object, so :func:`parse_spec` — not the SDK — validates it and
    returns readable errors.
    """
    full = DateSpecArg.model_json_schema()
    for key in ("title", "description"):
        full.pop(key, None)
    schema.update(full)


# --------------------------------------------------------------------------------------------------
# the MCP tools
# --------------------------------------------------------------------------------------------------

SPEC_HELP = (
    "What the letter SAYS about the date — not a date you computed. type: fixed (a calendar date is "
    "printed: set date, YYYY-MM-DD), relative (a period: set amount, unit, anchor) or none. anchor: "
    "document_date (from the letter's date), deemed_delivery (from the day a German authority's "
    "letter counts as delivered; set delivery_rule too), receipt (from the day it arrived), "
    "explicit_date (from anchor_date) or today. anchor_date (YYYY-MM-DD): that start day, or a "
    "posting day the letter states. amount: a whole number, negative for 'before'. unit: days, weeks,"
    " months, years, business_days (Mon-Fri) or werktage (Mon-Sat). delivery_rule: de_admin_post "
    "(posted by an authority), de_admin_electronic, de_admin_portal or none. nature: objection, "
    "payment, declaration, notice (giving notice on a contract), appointment or other. shift_rule: "
    "auto (decided by nature), none or next_business_day. legal_basis and text: the statute and the "
    "sentence as printed."
)
OptionalDate = Annotated[str | None, Field(description="A date written YYYY-MM-DD, or null")]
RegionArg = Annotated[
    str | None,
    Field(
        description="German Land whose public holidays apply: a code such as BY or NW, or its name; "
        "null = nationwide holidays only"
    ),
]


def tool_functions(rules: RulesTools) -> list[Callable[..., str]]:
    """The MCP tool functions over ``rules`` (their docstrings are the tool descriptions)."""
    from mcp.server.mcpserver.exceptions import ToolError

    def answer(call: Callable[[], dict[str, Any]]) -> str:
        try:
            return render(call())
        except RulesToolError as exc:
            raise ToolError(str(exc)) from exc

    def compute_deadline(
        spec: Annotated[dict[str, Any], Field(description=SPEC_HELP, json_schema_extra=_spec_schema)],
        document_date: Annotated[
            str | None, Field(description="The date printed on the letter (YYYY-MM-DD), or null")
        ] = None,
        sender_kind: Annotated[
            PartyKind | None,
            Field(
                description="Who sent it: tax_office, authority, immigration_office, health_insurer … or null"
            ),
        ] = None,
        sender_name: Annotated[
            str | None,
            Field(
                description="The sender as printed, e.g. 'Jobcenter Musterstadt' (refines which law applies)"
            ),
        ] = None,
        remedy_type: Annotated[
            RemedyType | None,
            Field(description="The remedy the letter names (einspruch, widerspruch, klage …), or null"),
        ] = None,
        region: Annotated[
            str | None,
            Field(
                description="The Land whose public holidays apply where the deadline is met: the "
                "authority's or company's seat (a code such as NW, or its name); null = nationwide "
                "holidays only, the earliest date"
            ),
        ] = None,
        recipient_region: Annotated[
            str | None,
            Field(
                description="The Land where the person lives (a code such as NW): used for a tax "
                "letter's delivery day and for payments to a company or person; null if unknown"
            ),
        ] = None,
        received_date: Annotated[
            str | None,
            Field(
                description="The day the letter actually arrived, if the person said so (YYYY-MM-DD, "
                "not after today); null if unknown"
            ),
        ] = None,
        today: Annotated[str | None, Field(description="Today (YYYY-MM-DD); null = today")] = None,
    ) -> str:
        """Compute a German deadline with Ordnung's tested rules engine: deemed delivery of authority
        letters (tax, administrative and social law: 4 days for items posted since 2025, 3 where a
        Land's own law is not confirmed), counting under §§ 187-193 BGB, weekend and public-holiday
        shifts, working days and a send-by date. Give it what the letter says (spec) plus the
        letter's date and sender; it returns the due date with every step, the rules and citations,
        warnings, a confidence and hints for missing facts. Where the facts leave room it returns the
        earliest plausible date, and its warnings say when the real one may be later. Information,
        not legal advice."""
        return answer(
            lambda: rules.compute_deadline(
                spec,
                document_date=document_date,
                sender_kind=sender_kind,
                sender_name=sender_name,
                remedy_type=remedy_type,
                region=region,
                recipient_region=recipient_region,
                received_date=received_date,
                today=today,
            )
        )

    def german_holidays(
        year: Annotated[int, Field(ge=MIN_YEAR, le=MAX_YEAR, description="The year, e.g. 2026")],
        region: RegionArg = None,
    ) -> str:
        """The public holidays of a year in Germany: the nationwide ones, plus a Land's own when
        region is given (German names, dates and weekdays)."""
        return answer(lambda: rules.german_holidays(year, region))

    def add_working_days(
        start: Annotated[str, Field(description="The day to count from (YYYY-MM-DD); it is not counted")],
        days: Annotated[
            int,
            Field(
                ge=-MAX_WORKING_DAYS,
                le=MAX_WORKING_DAYS,
                description="How many working days to add (negative counts backwards)",
            ),
        ],
        day_type: Annotated[
            DayType,
            Field(description="business_days (Monday-Friday) or werktage (Monday-Saturday)"),
        ] = "business_days",
        region: RegionArg = None,
    ) -> str:
        """Count working days from a date (German business days or Werktage, public holidays
        excluded) and list the days that were skipped."""
        return answer(lambda: rules.add_working_days(start, days, day_type, region))

    def check_iban(
        iban: Annotated[str, Field(max_length=MAX_IBAN_INPUT, description="The IBAN as printed")],
    ) -> str:
        """Check an IBAN: country, length and checksum, and the bank code where the country's
        format shows it. A valid IBAN does not prove who owns the account."""
        return answer(lambda: rules.check_iban(iban))

    return [compute_deadline, german_holidays, add_working_days, check_iban]


def _description(fn: Callable[..., Any]) -> str:
    return " ".join((fn.__doc__ or "").split())  # the docstring on one line


@functools.cache
def _strict_tool_class() -> type[Tool]:
    """An MCP ``Tool`` that refuses unknown arguments and reports argument errors in plain words.

    The SDK drops arguments a function does not take and reports type errors as pydantic dumps; a
    misspelt ``recieved_date`` must not vanish and change the date (module policy).
    """
    from mcp.server.mcpserver.exceptions import ToolError
    from mcp.server.mcpserver.tools import Tool

    class StrictTool(Tool):
        async def run(self, arguments: dict[str, Any], context: Any, convert_result: bool = False) -> Any:
            try:
                self.fn_metadata.validate_arguments(arguments)
            except ValidationError as exc:
                problems = argument_problems(self.name, exc, list(self.parameters.get("properties", {})))
                raise ToolError(f"Error executing tool {self.name}: {problems}") from exc
            return await super().run(arguments, context, convert_result=convert_result)

    return StrictTool


def rules_tools(*, today: Callable[[], date] | None = None) -> list[Tool]:
    """The rules tools (read-only, no data) as MCP tools; ``today`` is their default today."""
    from mcp.server.mcpserver.utilities.func_metadata import ArgModelBase
    from mcp.types import ToolAnnotations

    read_only = ToolAnnotations(
        read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
    )
    tools = []
    for fn in tool_functions(RulesTools(today=today)):
        tool = _strict_tool_class().from_function(
            fn, name=fn.__name__, description=_description(fn), annotations=read_only, structured_output=False
        )
        base = tool.fn_metadata.arg_model
        strict: type[ArgModelBase] = type(
            base.__name__, (base,), {"model_config": ConfigDict(extra="forbid")}
        )
        tool.fn_metadata.arg_model = strict
        tool.parameters = strict.model_json_schema(by_alias=True)
        tools.append(tool)
    return tools


def tool_definitions() -> list[dict[str, Any]]:
    """Name, description and input schema of every rules tool, as a client sees them."""
    return [
        {"name": tool.name, "description": tool.description, "input_schema": tool.parameters}
        for tool in rules_tools()
    ]


def build_rules_server(*, today: Callable[[], date] | None = None) -> MCPServer:
    """An ``MCPServer('ordnung_rules')`` with only the rules tools — no data folder, nothing personal."""
    from mcp.server.mcpserver import MCPServer

    return MCPServer(
        SERVER_NAME, instructions=INSTRUCTIONS, log_level="WARNING", tools=rules_tools(today=today)
    )


def run_rules_only() -> None:
    """Serve the rules tools over stdio until the client disconnects (``ordnung mcp --rules-only``)."""
    build_rules_server().run("stdio")


def rules_server_config(*, today: str | None = None) -> dict[str, Any]:
    """The ``--mcp-config`` JSON that makes ``claude`` spawn the rules-only server.

    ``today`` pins the tools' default today (``ORDNUNG_TODAY``), e.g. to a benchmark letter's day.
    """
    server: dict[str, Any] = {"command": sys.executable, "args": ["-m", "ordnung", "mcp", "--rules-only"]}
    if today is not None:
        server["env"] = {"ORDNUNG_TODAY": today}
    return {"mcpServers": {SERVER_NAME: server}}
