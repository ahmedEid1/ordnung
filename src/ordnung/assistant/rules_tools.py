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
  refused, and every date — the spec's ``date`` and ``anchor_date`` and the date arguments — must
  be written ``YYYY-MM-DD``; a whole number must be a number (``true`` is not 1); unknown tool
  arguments are refused too. A misspelt field or a date in another format must fail loudly, never
  be dropped silently and change the date. Every argument error names the argument and what is
  allowed, in plain words.
* **Same answers as the app.** Which delivery law applies — and whether the sender is an
  authority at all — follows the sender's kind, name and remedy exactly as in the pipeline
  (:func:`ordnung.rules.scope_for_party_kind`, :func:`ordnung.rules.is_private_sender`); the spec's
  own words (``text``, ``legal_basis``) stand in for the letter's remedy notice. So a company's,
  landlord's or employer's letter runs from its arrival even when a model asks for deemed delivery
  (the engine's rule, :func:`ordnung.rules.deadlines.from_arrival`) — naming a *Klage* or
  *Widerspruch* changes that only with a notice naming an administrative route — and an unknown
  sender (none, ``other``) keeps the earliest plausible deemed delivery. Missing facts are never guessed: the engine uses the
  earliest plausible date and says so, and ``hints`` name the argument that would settle it (and
  never one that was given).
* **Formal service.** A letter served in a yellow envelope has no deemed delivery; the spec help
  says how to pass its date, and a result that applied deemed delivery to a posted letter says so.
* **A model's arrival day is checked.** In the app a person enters ``received_date``; here a model
  passes it, or a delivery day the letter states (``spec.anchor_date`` with ``anchor: receipt``,
  which the engine counts from when it is not before the letter's date). The day the period
  actually runs from is checked: a day after today is refused, and one before the letter's date or
  more than :data:`LATE_ARRIVAL_DAYS` days after it gets a warning and one level less confidence (a
  wrong arrival day moves the deadline). A stated posting or delivery day can only be checked
  against the letter's date: without ``document_date`` it gets one level less confidence and a hint
  (:data:`UNCHECKED_DAY_HINT`). ``assumed`` reports the arrival day the period ran from
  and where it came from — none when it did not run from an arrival — and an arrival day given but
  not used. A letter dated after today gets a warning and one level less confidence too (usually a
  misread year).
* **"Today" is the server's.** A model's own idea of the date may be stale, and a wrong today makes
  a live deadline look missed. So a result is always for the server's today, whether the deadline
  has passed and the send-by date included; a caller's ``today`` more than a day off only adds
  ``for_today_given`` (that day's view) and a warning. A server started with ``today`` pinned
  (:func:`rules_server_config`, the benchmark) does not use a caller's ``today`` at all.
* **Partial holidays.** The calendar counts only holidays of a whole Land
  (:data:`PARTIAL_HOLIDAYS`). Where one of the others holds, a date counted back over it comes out
  a working day late; the engine warns about it (``check_partial_holidays`` in
  :mod:`ordnung.rules.deadlines`), so the app says so too.
* **Warnings for the person, hints for the caller.** A model relays warnings: they say what the
  person should know, in the tools' voice (:data:`TOOL_VOICE` replaces the engine's words for the
  app's person), and how to call again is a hint.
* **Next to the ledger** (the full server) a letter already in the ledger keeps its stored date:
  the instructions and ``compute_deadline``'s description say so (:data:`WITH_LEDGER_INSTRUCTIONS`).
* **No letter text in results.** Results are built by code from the engine's receipt and the
  normalised arguments; the spec's ``text`` and the sender's name are not echoed. So results are
  plain JSON, not wrapped as untrusted document text.
* **Information, not legal advice.** Every result carries a disclaimer that fits it: the deadline
  one (:func:`disclaimer`) for dates, the calendar's for holidays, the IBAN check's for an IBAN.

"Today" is the server's pinned day (``RulesTools(today=…)``, ``ORDNUNG_TODAY``), else the date in
Germany (:data:`HOME_ZONE`) — never the machine's own time zone; a caller's ``today`` replaces it
unless the server pins it (see above).

The tools' descriptions, :data:`SPEC_HELP`, :data:`INSTRUCTIONS` and the input schemas (generated
from ``DateSpec``, ``PartyKind`` and ``RemedyType`` in :mod:`ordnung.models`) are what a model reads,
so the benchmark treats them as part of its prompt (``evals.conditions.tool_definitions_digest``):
changing any of them makes the recorded ``llm_rules_tool`` answers miss on replay until that
condition is recorded again live (``python -m evals.run --live --conditions llm_rules_tool``). The
results the tools return are not part of that digest. Recording both splits costs about $5 — the six
recordings so far cost $14.91 in all (``docs/evals.md``) — so record again only with the owner's
approval, and prefer fixes in results, hints and the engine to changes of what a model reads.

Heavy modules (the rules engine, the holiday calendar, the MCP SDK) are imported on first use.
"""

from __future__ import annotations

import functools
import json
import os
import re
import sys
from collections.abc import Callable
from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Annotated, Any, Literal, get_args
from zoneinfo import ZoneInfo

from pydantic import BeforeValidator, ConfigDict, Field, ValidationError, field_validator

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
#: For the full server (``--with-ledger``): its instructions and ``compute_deadline``'s description say
#: which date wins for a letter in the ledger — the stored one, which may rest on facts the model
#: cannot see (the arrival day the person confirmed, a corrected sender, a date they set).
WITH_LEDGER_INSTRUCTIONS = (
    "For a letter that is in the ledger, its dates come from list_items and explain_date: quote them — "
    "they may rest on facts you cannot see (the day the person confirmed it arrived, a corrected sender, "
    "a date they set). compute_deadline is for letters that are not in the ledger."
)
WITH_LEDGER_NOTE = (
    "Not for a letter already in the ledger: quote its stored date from list_items or explain_date instead."
)
DISCLAIMER_TEMPLATE = (
    "Information, not legal advice: computed by Ordnung's rules engine from the facts given (German "
    "law as of {checked}), not reviewed by a lawyer. Check the result against the letter and get "
    "advice when a lot is at stake."
)
IBAN_NOTE = (
    "A well-formed IBAN says nothing about who owns the account. Compare it with earlier letters or "
    "the sender's official website; if a letter or e-mail says the account has changed, confirm that "
    "through contact details you already know before paying. For a euro transfer the bank also "
    "checks the payee's name against the account before it is sent (Empfängerüberprüfung, required "
    "since 9 October 2025): if it reports no match or only a close one, do not pay until you have "
    "confirmed the account."
)
#: The deadline disclaimer does not fit a calendar or a checksum: those tools say what they are.
HOLIDAYS_DISCLAIMER_TEMPLATE = (
    "Information, not legal advice: the public holidays in Ordnung's calendar (German federal and Land "
    "law as of {checked}), not reviewed by a lawyer."
)
IBAN_DISCLAIMER = (
    "Information, not legal or financial advice: what the IBAN's own characters show, checked by "
    "Ordnung's code. It cannot tell whether the account exists or who holds it."
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
#: Warnings say what the person should know; how to call the tool again is a hint (a model relays warnings).
FORMAL_SERVICE_WARNING = (
    "Deemed delivery was applied: the letter counts as delivered some days after it was posted. If it was "
    "formally served instead — in a yellow envelope (Postzustellungsurkunde), or it says it was "
    "'zugestellt' on a date — that rule does not apply and the period runs from the date written on the "
    "envelope, usually earlier."
)
FORMAL_SERVICE_HINT = (
    "If the letter was formally served (a yellow envelope, or 'zugestellt am …'), pass spec.anchor receipt "
    "with the envelope's date as spec.anchor_date and spec.delivery_rule none."
)
UNCHECKED_DAY_HINT = (
    "Pass document_date: the engine checks a stated posting or delivery day against the letter's date "
    "(it counts from the letter's date when a stated posting day is later)."
)
#: The engine speaks to the app's person, who can enter the arrival day there; in the tools' results the
#: same facts are said without an app to tell (the hints name the argument instead).
TOOL_VOICE: dict[str, str] = {
    "assumed_receipt": "The day the letter arrived was not given, so the period was counted from the date "
    "printed on it — the earliest plausible start.",
    "needs_arrival": "The period runs from the day the letter arrived, and neither that day nor the letter's "
    "date was given.",
    "told_arrival": "The letter arrived on",
    "enter_envelope_date": "the envelope's date gives the exact deadline",
}
#: add_working_days is a count on the calendar, not a deadline: its own disclaimer says so.
CALENDAR_DISCLAIMER_TEMPLATE = (
    "Information, not legal advice: working days counted on Ordnung's holiday calendar (German federal and "
    "Land law as of {checked}), not reviewed by a lawyer. A legal period may count differently — "
    "compute_deadline applies the deadline rules."
)
#: The rule the engine applies when a Land's 4-day rule for its authorities is not confirmed.
LAND_DAYS_RULE = "vwvfg_land_days"
#: Where "today" is when neither the caller nor the server pins it: Ordnung's letters are German.
HOME_ZONE = "Europe/Berlin"
#: Set to "1" (with ``ORDNUNG_TODAY``) to make the rules-only server ignore a caller's ``today``.
PIN_TODAY_ENV = "ORDNUNG_PIN_TODAY"
#: A caller's today this many days from the server's is not flagged (a time zone apart).
TODAY_TOLERANCE_DAYS = 1
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


def _not_a_bool(value: Any) -> Any:
    """Refuse ``true``/``false`` where a whole number is expected (pydantic would read them as 1 and 0)."""
    if isinstance(value, bool):
        raise ValueError(f"must be a whole number (got {json.dumps(value)})")
    return value


class DateSpecArg(DateSpec):
    """A ``DateSpec`` as a tool argument: the same fields, unknown keys refused, dates ``YYYY-MM-DD``.

    The engine reads a date it cannot parse as "no date" — right for a letter, wrong for a tool
    argument: ``anchor_date: "02.01.2026"`` would silently drop a stated posting day. A period of
    ``true`` is refused rather than read as 1.
    """

    model_config = ConfigDict(extra="forbid")

    @field_validator("amount", mode="before")
    @classmethod
    def _whole_amount(cls, value: Any) -> Any:
        return _not_a_bool(value)

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

    def __init__(self, today: Callable[[], date] | None = None, *, pin_today: bool = False) -> None:
        """``today`` is the default "today" (the app's simulated day, a test's pinned day);
        ``pin_today`` ignores a caller's ``today`` (a benchmark letter's day must hold)."""
        self._today = today
        self._pin_today = pin_today

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
        from ordnung.rules import RuleContext, compute_due, is_private_sender, scope_for_party_kind
        from ordnung.rules.deadlines import from_arrival

        parsed = parse_spec(spec)
        _check_choice("sender_kind", sender_kind, get_args(PartyKind))
        _check_choice("remedy_type", remedy_type, get_args(RemedyType))
        server_day = self.current_day()
        given_today = _optional_day("today", today)
        day, other_day = self._days(given_today, server_day)
        letter_day = _optional_day("document_date", document_date)
        received = _optional_day("received_date", received_date)
        if received is not None and received > day:
            raise RulesToolError(
                f"received_date ({received.isoformat()}) is after today ({day.isoformat()}): pass the day "
                "the letter actually arrived, or leave it out"
            )
        notice = f"{parsed.legal_basis or ''} {parsed.text}"  # the spec's words stand in for the notice
        scope = scope_for_party_kind(
            sender_kind, name=sender_name, remedy_type=remedy_type, remedy_text=notice
        )
        context = RuleContext(
            today=day,
            region=_region("region", region),
            document_date=letter_day,
            received_date=received,
            received_confirmed=received is not None,
            delivery_scope=scope,
            recipient_region=_region("recipient_region", recipient_region),
            private_sender=is_private_sender(
                sender_kind, scope=scope, remedy_type=remedy_type, remedy_text=notice
            ),
        )
        # The period the engine counts: a private sender's letter runs from its arrival, not deemed delivery.
        counted = from_arrival(parsed, context)
        stated = stated_receipt(counted, letter_day)
        if stated is not None and stated > day:
            raise RulesToolError(
                f"spec.anchor_date ({stated.isoformat()}) is after today ({day.isoformat()}): with anchor "
                "receipt it is the day the letter was delivered — pass the delivery day the letter states, "
                "or leave it out"
            )
        payer_pays = counted.nature == "payment" and scope is None  # place_region's rule (§ 270 BGB)
        receipt = compute_due(parsed, context)
        receipt = receipt.model_copy(update={"warnings": [tool_voice(w) for w in receipt.warnings]})
        formal = formal_service_warning(counted, receipt)
        found: list[tuple[str, bool]] = []
        found += arrival_warnings(counted, letter_day=letter_day, received=received, stated=stated)
        found += [(w, True) for w in _future_letter_warning(counted, letter_day, day)]
        found += [(w, True) for w in unchecked_day_warning(counted, letter_day)]
        found += [(w, False) for w in formal]
        found += [(w, False) for w in _today_warning(given_today, server_day, pinned=self._pin_today)]
        receipt = with_warnings(receipt, found)
        arrival, arrival_from = arrival_day(
            counted, receipt, letter_day=letter_day, received=received, stated=stated
        )
        other = compute_due(parsed, replace(context, today=other_day)) if other_day is not None else None
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
                "today_given": given_today.isoformat() if given_today not in (None, day) else None,
                "server_today": server_day.isoformat() if server_day != day else None,
                "letter_date": letter_day.isoformat() if letter_day else None,
                "received_date": arrival.isoformat() if arrival else None,
                "received_date_from": arrival_from,
                "received_date_not_used": received.isoformat()
                if received is not None and received != arrival
                else None,
                "delivery_law": _DELIVERY_LAW.get(scope or ""),
                "holiday_calendar": receipt.holiday_calendar,
                "holidays_from": None if counted.type == "none" else _holidays_from(payer_pays),
            },
            "hints": deadline_hints(
                counted,
                receipt,
                letter_day=letter_day,
                received=received,
                stated=stated,
                scope=scope,
                sender_kind=sender_kind,
                region=context.region,
                recipient_region=context.recipient_region,
                counted_from_arrival=counted is not parsed,
                formally_served_may_apply=bool(formal),
            ),
            "for_today_given": for_other_day(other, receipt, other_day),
            "disclaimer": disclaimer(),
        }

    def _days(self, given: date | None, server_day: date) -> tuple[date, date | None]:
        """The day a result is for, and a caller's other day to report on as well (module docstring).

        A caller's today within :data:`TODAY_TOLERANCE_DAYS` of the server's is used (a time zone
        apart); one further off only gets ``for_today_given``, and on a pinned server it is not used.
        """
        if given is None or self._pin_today:
            return server_day, None
        if abs((given - server_day).days) <= TODAY_TOLERANCE_DAYS:
            return given, None
        return server_day, given

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
            "disclaimer": holidays_disclaimer(),
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
        counted: list[date] = []
        step = timedelta(days=1 if days >= 0 else -1)
        day = first
        while day != result:
            day += step
            kind = day_kind(day, code)
            if kind is not None and not (werktage and kind == "Saturday"):
                skipped.append({"date": day.isoformat(), "weekday": _WEEKDAYS[day.weekday()], "reason": kind})
            else:
                counted.append(day)
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
            else regional_note(counted, later=days >= 0)
            if code is None
            else None,
            "disclaimer": calendar_disclaimer(),
        }

    def check_iban(self, iban: str) -> dict[str, Any]:
        """Country, length, checksum and (where known) the bank code an IBAN carries."""
        from ordnung.money.iban import INVALID_IBAN_ADVICE, grouped, inspect_iban

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
            "note": IBAN_NOTE if check.valid else INVALID_IBAN_ADVICE,
            "disclaimer": IBAN_DISCLAIMER,
        }


# --------------------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------------------


def regional_note(counted: list[date], *, later: bool) -> str | None:
    """With no region: say when a day counted is a public holiday in some Länder (``None`` if none is).

    There that day is no working day, so the count ends a working day later — or, counting
    backwards, a working day earlier, which makes the date shown too late.
    """
    from ordnung.rules.calendar_de import REGION_NAMES, regional_holiday_lands
    from ordnung.rules.explain import fmt_date

    for day in counted:
        lands = regional_holiday_lands(day)
        if lands:
            names = ", ".join(REGION_NAMES[code] for code in lands[:3])
            there = (
                "the result is a working day later there"
                if later
                else "the result is a working day earlier there, so this date may be a day late"
            )
            return (
                f"Nationwide holidays only: {fmt_date(day)}, counted here as a working day, is a public "
                f"holiday in some Länder (e.g. {names}) — {there}. Pass region for a Land's own holidays."
            )
    return None


def disclaimer() -> str:
    from ordnung.rules import LAST_CHECKED

    return DISCLAIMER_TEMPLATE.format(checked=LAST_CHECKED)


def holidays_disclaimer() -> str:
    from ordnung.rules import LAST_CHECKED

    return HOLIDAYS_DISCLAIMER_TEMPLATE.format(checked=LAST_CHECKED)


def calendar_disclaimer() -> str:
    from ordnung.rules import LAST_CHECKED

    return CALENDAR_DISCLAIMER_TEMPLATE.format(checked=LAST_CHECKED)


def tool_voice(warning: str) -> str:
    """An engine warning in the tools' voice (:data:`TOOL_VOICE`): no "tell us", no "enter".

    The engine's words for the app's person are its own constants, so a reworded warning is matched
    exactly or not at all (then it is passed on unchanged).
    """
    from ordnung.rules.deadlines import (
        ASSUMED_RECEIPT_WARNING,
        ENTER_ENVELOPE_DATE,
        NEEDS_ARRIVAL_WARNING,
        TOLD_ARRIVAL,
    )

    if warning == ASSUMED_RECEIPT_WARNING:
        return TOOL_VOICE["assumed_receipt"]
    if warning == NEEDS_ARRIVAL_WARNING:
        return TOOL_VOICE["needs_arrival"]
    return warning.replace(TOLD_ARRIVAL, TOOL_VOICE["told_arrival"]).replace(
        ENTER_ENVELOPE_DATE, TOOL_VOICE["enter_envelope_date"]
    )


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


def with_warnings(receipt: ComputationReceipt, found: list[tuple[str, bool]]) -> ComputationReceipt:
    """``receipt`` with the tool's own warnings added; each one flagged ``True`` lowers confidence a level."""
    confidence = receipt.confidence
    for _, lower in found:
        if lower:
            confidence = _LOWER[confidence]
    warnings = [*receipt.warnings, *(warning for warning, _ in found)]
    return receipt.model_copy(update={"warnings": warnings, "confidence": confidence})


def stated_receipt(spec: DateSpec, letter_day: date | None) -> date | None:
    """The delivery day the letter states that the engine counts from (``anchor: receipt``), if any.

    That is ``spec.anchor_date`` when it is not before the letter's date (``_resolve_anchor`` in
    :mod:`ordnung.rules.deadlines`); an earlier one is not used.
    """
    if spec.type != "relative" or spec.anchor != "receipt" or not spec.anchor_date:
        return None
    stated = date.fromisoformat(spec.anchor_date)
    return stated if letter_day is None or stated >= letter_day else None


def arrival_day(
    spec: DateSpec,
    receipt: ComputationReceipt,
    *,
    letter_day: date | None,
    received: date | None,
    stated: date | None,
) -> tuple[date | None, str | None]:
    """The arrival day the period ran from, and where it came from (for ``assumed``).

    Only a period that runs from the letter's arrival has one (``anchor: receipt``, after
    :func:`ordnung.rules.deadlines.from_arrival`), or a deemed delivery the engine counted from the
    day the letter arrived because that was before its date. Otherwise ``(None, None)``: an arrival
    day given is then reported as not used.
    """
    if stated is not None:
        return stated, "spec.anchor_date: the delivery day the letter states"
    if spec.type == "relative" and spec.anchor == "receipt":
        if received is not None:
            return received, "received_date"
        if letter_day is not None:
            return letter_day, "document_date: assumed, the earliest plausible arrival"
        return None, None
    if received is not None and counted_from(receipt) == received:
        return received, "received_date: it arrived before the letter's date, so the period runs from it"
    return None, None


def counted_from(receipt: ComputationReceipt) -> date | None:
    """The day a forward period was counted from (the engine's § 187 step), if any."""
    day = next((step.date for step in receipt.steps if step.rule_id == "bgb_187_1"), None)
    return date.fromisoformat(day) if day else None


def formal_service_warning(spec: DateSpec, receipt: ComputationReceipt) -> list[str]:
    """:data:`FORMAL_SERVICE_WARNING` when deemed delivery was applied to a letter sent by post."""
    posted = spec.delivery_rule in ("de_admin_post", "none")
    return [FORMAL_SERVICE_WARNING] if posted and "posting_day" in receipt.rule_ids else []


def for_other_day(
    other: ComputationReceipt | None, receipt: ComputationReceipt, day: date | None
) -> dict[str, Any] | None:
    """What ``other`` — the computation for a caller's today far from the server's — says for that day.

    The result itself is for the server's today; this block only answers "on that day, had it
    passed, and when was the send-by date?" (a hypothetical must never make a live deadline look
    missed). The due date is repeated only when that day changes it (a letter counting from "today").
    """
    if other is None or day is None:
        return None
    due = other.due_date
    return {
        "today": day.isoformat(),
        "due_date": due if due != receipt.due_date else None,
        "send_by": other.send_by,
        "passed": date.fromisoformat(due) < day if due else None,
    }


def arrival_warnings(
    spec: DateSpec, *, letter_day: date | None, received: date | None, stated: date | None
) -> list[tuple[str, bool]]:
    """Warnings on the arrival day a period runs from (``anchor: receipt``); ``True`` lowers confidence.

    The day checked is the one the engine used: the delivery day the letter states, else the
    arrival day given. One before the letter's date or more than :data:`LATE_ARRIVAL_DAYS` days
    after it is flagged; an arrival day the engine did not use is named. Other anchors are left to
    the engine (deemed delivery already keeps the earlier, safe day for a late arrival).
    """
    from ordnung.rules.explain import fmt_date

    if spec.type != "relative" or spec.anchor != "receipt":
        return []
    found: list[tuple[str, bool]] = []
    if spec.anchor_date and stated is None and letter_day is not None:
        start = f"the arrival day given ({fmt_date(received)})" if received else "the letter's date"
        found.append(
            (
                f"spec.anchor_date ({fmt_date(date.fromisoformat(spec.anchor_date))}) is before the letter's "
                f"date ({fmt_date(letter_day)}), so it was not used as the delivery day; the period was "
                f"counted from {start}.",
                False,
            )
        )
    if stated is not None and received is not None and received != stated:
        found.append(
            (
                f"received_date ({fmt_date(received)}) was not used: the letter states it was delivered on "
                f"{fmt_date(stated)} (spec.anchor_date), and the period runs from that day.",
                False,
            )
        )
    arrival, what = (
        (stated, "delivery day in spec.anchor_date") if stated else (received, "arrival day given")
    )
    if arrival is None or letter_day is None:
        return found
    gap = (arrival - letter_day).days
    if gap < 0:
        found.append(
            (
                f"The {what} ({fmt_date(arrival)}) is before the letter's date ({fmt_date(letter_day)}). "
                "A letter rarely arrives before the date printed on it — check both dates: a wrong arrival "
                "day gives a wrong deadline.",
                True,
            )
        )
    elif gap > LATE_ARRIVAL_DAYS:
        found.append(
            (
                f"The {what} ({fmt_date(arrival)}) is {gap} days after the letter's date "
                f"({fmt_date(letter_day)}), which is unusually late for post. Check it: a later arrival day "
                "moves the deadline later. If it is right, keep the envelope as proof.",
                True,
            )
        )
    return found


def _future_letter_warning(spec: DateSpec, letter_day: date | None, today: date) -> list[str]:
    """A letter dated after today — usually a misread year — when the period counts from its date.

    A letter counting from "today" is left to the engine, which already warns about it.
    """
    from ordnung.rules.explain import fmt_date

    if letter_day is None or letter_day <= today or spec.type != "relative" or spec.anchor == "today":
        return []
    return [
        f"The letter's date given ({fmt_date(letter_day)}) is after today ({fmt_date(today)}). A letter "
        "is rarely dated later than the day it is read — check the date, the year above all: a wrong "
        "letter date gives a wrong deadline."
    ]


def unchecked_day_warning(spec: DateSpec, letter_day: date | None) -> list[str]:
    """A stated posting or delivery day that could not be checked, the letter's date missing.

    The engine counts from ``spec.anchor_date`` as a posting day (deemed delivery) only when it is
    before the letter's date, and as a delivery day (``anchor: receipt``) only when it is not before
    it: its earliest-plausible policy. Without the letter's date that check cannot run.
    """
    from ordnung.rules.explain import fmt_date

    if letter_day is not None or spec.type != "relative" or not spec.anchor_date:
        return []
    what = {"deemed_delivery": "posting", "receipt": "delivery"}.get(spec.anchor or "")
    if what is None:
        return []
    return [
        f"The letter's date was not given, so the {what} day stated "
        f"({fmt_date(date.fromisoformat(spec.anchor_date))}) could not be checked against it: a stated day "
        "that is wrong or later than the letter's date moves the deadline later."
    ]


def _today_warning(given: date | None, server_day: date, *, pinned: bool) -> list[str]:
    """A caller's today that is not the server's (see the module docstring)."""
    from ordnung.rules.explain import fmt_date

    if given is None or given == server_day:
        return []
    if pinned:
        return [
            f"The today given ({fmt_date(given)}) was not used: this server counts from "
            f"{fmt_date(server_day)}, the day it is set to."
        ]
    gap = abs((given - server_day).days)
    if gap <= TODAY_TOLERANCE_DAYS:
        return []
    return [
        f"The today given ({fmt_date(given)}) is {gap} days {'after' if given > server_day else 'before'} "
        f"this server's today ({fmt_date(server_day)}). The result is for the server's today — whether the "
        "deadline has passed and the send-by date included; for_today_given shows them for the day given. "
        "Leave today out unless you mean another day."
    ]


def _holidays_from(payer_pays: bool) -> str:
    """Which argument's Land the holidays come from, and why (for ``assumed``)."""
    if payer_pays:
        return (
            "recipient_region: a payment to a company or person is made where the payer lives "
            "(§§ 269, 270 Abs. 4 BGB), so that Land's holidays apply"
        )
    return "region: the Land where the deadline is met (the sender's seat)"


def deadline_hints(
    spec: DateSpec,
    receipt: ComputationReceipt,
    *,
    letter_day: date | None,
    received: date | None,
    scope: str | None,
    stated: date | None = None,
    sender_kind: str | None = None,
    region: str | None = None,
    recipient_region: str | None = None,
    counted_from_arrival: bool = False,
    formally_served_may_apply: bool = False,
) -> list[str]:
    """Which missing argument would settle what the engine had to assume (empty when none).

    ``spec`` is the one computed (after :func:`from_arrival`; ``counted_from_arrival`` says it
    ran). Only arguments that were *not* given are named, and a holiday region by the argument the
    engine reads for this date; for a sender whose kind has no deemed-delivery rule, the hint says
    how to get it instead of asking for the kind again. The situations come from the engine's
    warnings, by the words :mod:`ordnung.rules.deadlines` shares for them (``REGION_UNKNOWN`` …).
    """
    from ordnung.rules.deadlines import HOME_HOLIDAY, REGION_EARLIER, REGION_UNKNOWN, TAX_OFFICE_HOLIDAY

    hints: list[str] = []
    delivered = "posting_day" in receipt.rule_ids  # the deemed-delivery step ran
    if spec.type == "relative":
        anchor = spec.anchor or "document_date"
        from_letter = anchor == "receipt" and received is None and stated is None
        counts_from_letter = anchor in ("document_date", "deemed_delivery", "today") or from_letter
        if counts_from_letter and letter_day is None and not spec.anchor_date:
            hints.append(
                "Pass document_date: the date printed on the letter, which the period counts from"
                + (" ('today' in a letter is the day it was written)." if anchor == "today" else ".")
            )
        elif letter_day is None and unchecked_day_warning(spec, letter_day):
            hints.append(UNCHECKED_DAY_HINT)
        if from_letter:
            hints.append(
                "Pass received_date if you know the day the letter arrived; until then the letter's date "
                "is used (the earliest plausible start)."
            )
        if anchor == "explicit_date" and not spec.anchor_date:
            hints.append("Set spec.anchor_date to the day the period runs from.")
    if counted_from_arrival:
        hints.append(
            "If the letter is an authority's decision after all (a Bescheid), pass its kind (authority, "
            "tax_office, immigration_office …): its deemed-delivery rule then applies. A Klage to a labour "
            "or civil court, or a Widerspruch under the BGB or VVG, does not make it one."
        )
    elif (
        spec.type == "relative"
        and scope is None
        and sender_kind in (None, "other")
        and (delivered or spec.anchor == "deemed_delivery")
    ):
        hints.append(
            "Pass sender_kind (tax_office, authority, immigration_office, health_insurer, university, or "
            "company, landlord …) and sender_name so the right delivery law applies; without them the "
            "earliest plausible date is used."
        )
    if region is None and LAND_DAYS_RULE in receipt.rule_ids:
        hints.append(
            "Pass region — the Land of the authority: where its own law is confirmed to use the 4-day "
            "rule (e.g. NW or BY), the letter counts as delivered a day later, and so may the deadline."
        )
    if formally_served_may_apply:
        hints.append(FORMAL_SERVICE_HINT)
    if recipient_region is None and _warned(receipt, TAX_OFFICE_HOLIDAY):
        hints.append(
            "Pass recipient_region — the Land where the person lives: if it is the tax office's Land, "
            "its holiday moves the delivery day and the deadline a day later."
        )
    if region is None and _warned(receipt, HOME_HOLIDAY):
        hints.append(
            "Pass region — the tax office's Land: if it is where the person lives, that holiday moves the "
            "delivery day and the deadline a day later."
        )
    if _warned(receipt, REGION_UNKNOWN, start=True):
        way = "earlier" if _warned(receipt, REGION_EARLIER) else "later"
        if spec.nature == "payment" and scope is None:  # the engine's place_region: the payer's Land
            if recipient_region is None:
                hints.append(
                    "Pass recipient_region — the Land where the payer lives: a payment to a company or "
                    "person is made there (§§ 269, 270 Abs. 4 BGB), so its holidays apply, not region's. "
                    f"A regional holiday may make this date {way}."
                )
        elif region is None:
            both = scope == "ao" and recipient_region is None
            hints.append(
                "Pass region — the Land of the office or company where the deadline is met"
                + (
                    ", and recipient_region — the Land where the person lives (a tax letter's delivery "
                    "day depends on both)"
                    if both
                    else ""
                )
                + f". A regional holiday may make this date {way}."
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
    """A date written ``YYYY-MM-DD`` — not another ISO form such as ``20260901`` or ``2026-W36-1``."""
    if not isinstance(value, str):
        raise RulesToolError(f"{name} must be a date written YYYY-MM-DD")
    try:
        if not _ISO_DAY.match(value.strip()):
            raise ValueError(value)
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
    "letter sent by ordinary post or electronically counts as delivered; set delivery_rule too), "
    "receipt (from the day it arrived or was served), explicit_date (from anchor_date) or today. "
    "anchor_date (YYYY-MM-DD): that start day, or a posting day the letter states. A letter formally "
    "served — a yellow envelope (Postzustellungsurkunde), 'Zustellung', 'zugestellt am' — has no "
    "deemed delivery: use anchor receipt, anchor_date = the date written on the envelope (or stated "
    "as served), delivery_rule none. amount: a whole number, negative for 'before'. unit: days, "
    "weeks, months, years, business_days (Mon-Fri) or werktage (Mon-Sat). delivery_rule: "
    "de_admin_post (posted by an authority), de_admin_electronic, de_admin_portal or none. nature: "
    "objection, payment, declaration, notice (giving notice on a contract), appointment or other. "
    "shift_rule: auto (decided by nature), none or next_business_day. legal_basis and text: the "
    "statute and the sentence as printed; an Anhörungsbogen's reply date is a request, not a legal "
    "deadline: put 'Anhörungsbogen' in legal_basis and the result says so."
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
                description="Who sent it: tax_office, authority, immigration_office, health_insurer, "
                "company, landlord … (a company's letter has no deemed delivery), or null if unknown"
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
                "holidays only, and the warnings say when a Land's holiday could move the date"
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
        today: Annotated[
            str | None,
            Field(
                description="Leave null: the server knows today's date in Germany. Pass a date "
                "(YYYY-MM-DD) only to ask about another day; the result stays for the real today and "
                "for_today_given adds that day's view"
            ),
        ] = None,
    ) -> str:
        """Compute a German deadline with Ordnung's tested rules engine: deemed delivery of authority
        letters (tax, administrative and social law: 4 days for items posted since 2025, 3 where a
        Land's own law is not confirmed), counting under §§ 187-193 BGB, weekend and public-holiday
        shifts, working days and a send-by date. Give it what the letter says (spec) plus the
        letter's date and sender; it returns the due date with every step, the rules and citations,
        warnings, a confidence and hints for missing facts. Where the facts leave room it returns the
        earliest plausible date, and its warnings say when the real one may differ. Information,
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
        year: Annotated[
            int,
            Field(ge=MIN_YEAR, le=MAX_YEAR, description="The year, e.g. 2026"),
            BeforeValidator(_not_a_bool),  # after Field, or its bounds leave the schema
        ],
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
            BeforeValidator(_not_a_bool),  # pydantic reads true as 1 before the method's own check
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


def rules_tools(
    *, today: Callable[[], date] | None = None, pin_today: bool = False, with_ledger: bool = False
) -> list[Tool]:
    """The rules tools (read-only, no data) as MCP tools; ``today`` is their default today, and
    ``pin_today`` makes it the only one (a caller's ``today`` is not used). ``with_ledger`` (the full
    server) adds :data:`WITH_LEDGER_NOTE` to ``compute_deadline``'s description."""
    from mcp.server.mcpserver.utilities.func_metadata import ArgModelBase
    from mcp.types import ToolAnnotations

    read_only = ToolAnnotations(
        read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
    )
    tools = []
    for fn in tool_functions(RulesTools(today=today, pin_today=pin_today)):
        description = _description(fn)
        if with_ledger and fn.__name__ == "compute_deadline":
            description = f"{description} {WITH_LEDGER_NOTE}"
        tool = _strict_tool_class().from_function(
            fn, name=fn.__name__, description=description, annotations=read_only, structured_output=False
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


def build_rules_server(*, today: Callable[[], date] | None = None, pin_today: bool = False) -> MCPServer:
    """An ``MCPServer('ordnung_rules')`` with only the rules tools — no data folder, nothing personal."""
    from mcp.server.mcpserver import MCPServer

    return MCPServer(
        SERVER_NAME,
        instructions=INSTRUCTIONS,
        log_level="WARNING",
        tools=rules_tools(today=today, pin_today=pin_today),
    )


def run_rules_only() -> None:
    """Serve the rules tools over stdio until the client disconnects (``ordnung mcp --rules-only``).

    With :data:`PIN_TODAY_ENV` set to "1" a caller's ``today`` is not used (see :func:`rules_server_config`).
    """
    build_rules_server(pin_today=os.environ.get(PIN_TODAY_ENV) == "1").run("stdio")


def rules_server_config(*, today: str | None = None) -> dict[str, Any]:
    """The ``--mcp-config`` JSON that makes ``claude`` spawn the rules-only server.

    ``today`` pins the tools' today (``ORDNUNG_TODAY`` and :data:`PIN_TODAY_ENV`), e.g. to a
    benchmark letter's day: a ``today`` the model passes is then not used. The ``claude`` CLI tells
    the model the real date, which is not the letter's.
    """
    server: dict[str, Any] = {"command": sys.executable, "args": ["-m", "ordnung", "mcp", "--rules-only"]}
    if today is not None:
        server["env"] = {"ORDNUNG_TODAY": today, PIN_TODAY_ENV: "1"}
    return {"mcpServers": {SERVER_NAME: server}}
