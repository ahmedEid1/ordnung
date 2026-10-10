"""The moving checklist: who needs the new address after the person says they moved (ADR 0021).

A move is said, never guessed: only the person sets ``Profile.moved_on`` ("I moved" in Settings → Profile,
or "Moved recently?" once the new address is saved; ``PUT /api/profile``), and nothing here changes the
profile or sends anything. :func:`moving_ideas` is the ``moved_house`` Idea rule. While the move is at most
:data:`MOVE_WINDOW_DAYS` ago (or still ahead), it turns the move and the ledger into one Idea per row of the
checklist, which Today shows as its own card:

- register the new home at the citizens' office within two weeks of moving in (§ 17 Abs. 1 BMG,
  :data:`~ordnung.secretary.triggers.REGISTRATION_LAW`). The day comes from the rules engine
  (:func:`~ordnung.rules.periods.add_period`) and is never moved off a weekend or holiday: whether that
  applies to this duty is not settled, so the checklist shows the earlier, safe day;
- "Tell X your new address" for each organisation with the old address on record (:func:`who_to_tell`):
  one with a running contract, or one of a kind that keeps your address (:data:`KEEP_INFORMED`) that wrote
  in the last :data:`LOOKBACK_DAYS`. A letter with scam signs is no source, and neither is a letter kept
  private ("Keep private — no AI"), nor a contract read from one: a row's title reaches the weekly Ideas and
  the daily note like every Idea's;
- the broadcasting fee office, when no listed organisation is the broadcaster.

Every row's fingerprint holds the move's day, so the person's ticks ("done", "Not needed") last through
every run and a new move starts a fresh list. A sender's row goes when the person marks a new-address letter
to them as sent (sent at most :data:`LETTER_LEAD_DAYS` before the move): the rule no longer produces it and
the reconcile expires it — nothing is ticked off for the person. No row carries an address: a contract
named after the flat ("Flat Beispielweg 5") is counted without its name.

The rule reads the ledger's shared rows (parties, contracts, letters) and the sent letters once per run, never
once per organisation.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Final

from ordnung.models import Contract, Document, Party, Suggestion, SuggestionAction, SuggestionRef
from ordnung.rules.periods import add_period
from ordnung.secretary.triggers import (
    REGISTRATION_LAW,
    IdeaText,
    Ledger,
    day_label,
    letter_day,
    make_idea,
    parse_day,
)

RULE_ID: Final = "moved_house"
#: The checklist ends this many days after the move (six months).
MOVE_WINDOW_DAYS: Final = 180
#: How far ahead a move may be told (three months): the checklist can start before the moving day.
MOVE_AHEAD_DAYS: Final = 90
#: A sender counts if they wrote in the last three years (a residence permit, a tax office's file or a
#: payslip can be that old).
LOOKBACK_DAYS: Final = 1096
#: A new-address letter marked sent up to this many days before the move answers that sender's row.
LETTER_LEAD_DAYS: Final = 60
#: The kinds of organisation whose letters mean they keep your address (others count with a running contract).
KEEP_INFORMED: Final = frozenset(
    {
        "bank",
        "insurer",
        "health_insurer",
        "employer",
        "university",
        "tax_office",
        "immigration_office",
        "public_broadcaster",
        "utility",
        "telecom",
        "landlord",
    }
)
#: The entity of the registration row's fingerprint (a sender's row uses the party's id).
REGISTRATION_ENTITY: Final = "registration"
#: The entity of the broadcasting fee office's row, when no listed organisation is the broadcaster.
BROADCASTING_ENTITY: Final = "broadcasting_fee"
#: Why a day outside the window is refused (``PUT /api/profile``, and the static demo's mock says the same).
MOVE_WINDOW_PROBLEM: Final = (
    "Ordnung's moving checklist is for a move in the last six months or the next three — check the day."
)

#: The order of the list: by kind, then by name.
_KIND_ORDER: Final = (
    "employer",
    "bank",
    "insurer",
    "health_insurer",
    "public_broadcaster",
    "landlord",
    "utility",
    "telecom",
    "university",
    "tax_office",
    "immigration_office",
)
_BROADCASTING_TIP: Final = (
    "If you pay the broadcasting fee (Rundfunkbeitrag) for your flat, change your address online at "
    "rundfunkbeitrag.de. If you moved in with someone who already pays, you can de-register instead."
)
#: Practical tips by kind of organisation (no legal claims).
_KIND_TIPS: Final = {
    "bank": "Many banks let you change it in online banking.",
    "insurer": "Most insurers let you change it in their app or online account.",
    "health_insurer": "Most insurers let you change it in their app or online account.",
    "employer": "Tell HR or payroll: your payslips and tax papers go there.",
    "landlord": "A landlord you are leaving needs it for your deposit and the last operating-cost statement.",
    "utility": "Note your meter readings on the day you move out and send them in.",
    "telecom": "If they provide your internet at home, ask whether they can move the line to the new address.",
    "public_broadcaster": _BROADCASTING_TIP,
    "tax_office": "Letters about your tax return go there.",
    "immigration_office": "Letters about your residence permit go there.",
    "university": "Letters about your enrolment go there.",
}
#: The same tips by contract category, for a sender of another kind.
_CATEGORY_TIPS: Final = {
    "bank": _KIND_TIPS["bank"],
    "insurance": _KIND_TIPS["insurer"],
    "employment": _KIND_TIPS["employer"],
    "rent": _KIND_TIPS["landlord"],
    "energy": _KIND_TIPS["utility"],
    "gas": _KIND_TIPS["utility"],
    "internet": "Ask whether they can move your line to the new address.",
}
_REGISTRATION_BODY: Final = (
    "Register at the citizens' office (Bürgeramt or Einwohnermeldeamt) where you now live, within two weeks "
    "of moving in. Take your ID card or passport and your landlord's confirmation that you moved in "
    "(Wohnungsgeberbestätigung) — ask your landlord for it."
)
#: The shortest address line a contract's name is checked for (shorter ones, like "5", are everywhere).
_ADDRESS_LINE_MIN: Final = 5
_BOOK_SOON: Final = "Appointments are often booked out, so book one soon."
_REGISTER_NOW: Final = "Register as soon as you can."


def registration_due(moved_on: date) -> date:
    """Two weeks after moving in (§ 17 Abs. 1 BMG): counting starts the next day (§ 187 Abs. 1 BGB), and the
    end is never moved off a weekend or holiday — the safe, earlier day."""
    return add_period(moved_on, 2, "weeks")[0]


def move_problem(moved_on: date, today: date) -> str | None:
    """Why ``moved_on`` can't start a checklist on ``today`` (``None`` when it can): only a move in the last
    :data:`MOVE_WINDOW_DAYS` or the next :data:`MOVE_AHEAD_DAYS`."""
    earliest, latest = today - timedelta(days=MOVE_WINDOW_DAYS), today + timedelta(days=MOVE_AHEAD_DAYS)
    return None if earliest <= moved_on <= latest else MOVE_WINDOW_PROBLEM


@dataclass
class Listed:
    """An organisation the checklist lists, and why: its running contracts, else the day it last wrote."""

    party: Party
    contracts: list[Contract] = field(default_factory=list)
    last_letter: date | None = None
    broadcaster: bool = False


def _letter_day(doc: Document) -> date | None:
    return letter_day(doc) or parse_day(doc.created_at)


def who_to_tell(ledger: Ledger) -> list[Listed]:
    """Every organisation with the old address on record: a running contract (``ledger.active_contracts()``)
    not read from a letter with scam signs or one kept private, or a live incoming letter in the last
    :data:`LOOKBACK_DAYS`, without scam signs and not kept private, from a sender of a :data:`KEEP_INFORMED`
    kind. Ordered by kind (employer, bank, insurers, broadcaster, landlord, utility, telecom, university, tax
    office, immigration office, others), then name. One pass over the shared rows."""
    since = ledger.today - timedelta(days=LOOKBACK_DAYS)
    listed: dict[str, Listed] = {}
    fee_payees: set[str] = set()

    def entry(party: Party) -> Listed:
        return listed.setdefault(party.id, Listed(party))

    for doc in ledger.documents.values():
        party = ledger.parties.get(doc.party_id) if doc.party_id else None
        if party is None or doc.direction != "incoming" or doc.ai_private:
            continue
        day = _letter_day(doc)
        recent = party.kind in KEEP_INFORMED and day is not None and since <= day
        if not (recent or doc.kind == "broadcasting_fee") or ledger.scam_reasons(doc):
            continue
        if doc.kind == "broadcasting_fee":
            fee_payees.add(party.id)
        if recent and day is not None:
            found = entry(party)
            found.last_letter = max(found.last_letter or day, day)
    for contract in ledger.active_contracts():
        party = ledger.parties.get(contract.party_id) if contract.party_id else None
        source = ledger.document(contract.source_doc_id)
        if party is None or (source is not None and (source.ai_private or ledger.scam_reasons(source))):
            continue
        entry(party).contracts.append(contract)
    for found in listed.values():
        found.broadcaster = found.party.kind == "public_broadcaster" or found.party.id in fee_payees

    def order(found: Listed) -> tuple[int, str, str]:
        kind = found.party.kind
        rank = _KIND_ORDER.index(kind) if kind in _KIND_ORDER else len(_KIND_ORDER)
        return rank, found.party.name.casefold(), found.party.id

    return sorted(listed.values(), key=order)


def _told(ledger: Ledger, moved: date) -> set[str]:
    """The senders a new-address letter was marked sent to, at most :data:`LETTER_LEAD_DAYS` before the move."""
    earliest = moved - timedelta(days=LETTER_LEAD_DAYS)
    return {
        draft.party_id
        for draft in ledger.sent_drafts()
        if draft.kind == "address_change"
        and draft.party_id
        and (parse_day(draft.sent_at) or date.min) >= earliest
    }


def address_lines(*addresses: str) -> list[str]:
    """The lines of the person's addresses a contract's name may repeat ("Flat Beispielweg 5"), folded for
    comparing; lines shorter than :data:`_ADDRESS_LINE_MIN` (a lone house number) never match."""
    lines = (" ".join(line.split()).casefold() for address in addresses for line in address.splitlines())
    return [line for line in lines if len(line) >= _ADDRESS_LINE_MIN]


def _names_an_address(name: str, lines: Iterable[str]) -> bool:
    folded = " ".join(name.split()).casefold()
    return any(line in folded for line in lines)


def _reason(found: Listed, today: date, lines: list[str]) -> str:
    """Why a sender is listed: their running contracts by name (at most two, and never a name that repeats a
    line of the person's address), else the day they last wrote."""
    contracts = sorted(found.contracts, key=lambda contract: (contract.name.casefold(), contract.id))
    shown = [f"“{c.name}”" for c in contracts if not _names_an_address(c.name, lines)][:2]
    more = len(contracts) - len(shown)
    if len(contracts) == 1:
        return (
            f"Your contract {shown[0]} with them is running."
            if shown
            else "Your contract with them is running."
        )
    if contracts and not shown:
        return f"Your {len(contracts)} contracts with them are running."
    if contracts:
        named = " and ".join(shown) if not more else f"{', '.join(shown)} and {more} more"
        return f"Your contracts {named} with them are running."
    assert found.last_letter is not None  # listed for a letter
    return f"They last wrote to you on {day_label(found.last_letter, today)}."


def _tip(found: Listed) -> str | None:
    if found.broadcaster:
        return _BROADCASTING_TIP
    tip = _KIND_TIPS.get(found.party.kind)
    if tip is None:
        tip = next(
            (_CATEGORY_TIPS[c.category] for c in found.contracts if c.category in _CATEGORY_TIPS), None
        )
    return tip


def _registration(ledger: Ledger, moved: date) -> Suggestion:
    today = ledger.today
    due = registration_due(moved)
    missed = due < today
    title = (
        f"Register your new address — it was due {day_label(due, today)}"
        if missed
        else f"Register your new address by {day_label(due, today)}"
    )
    return make_idea(
        RULE_ID,
        REGISTRATION_ENTITY,
        (moved.isoformat(),),
        IdeaText(
            title,
            f"{_REGISTRATION_BODY} {_REGISTER_NOW if missed else _BOOK_SOON}",
            f"You moved in on {day_label(moved, today)}; registering is due within two weeks "
            f"({REGISTRATION_LAW}).",
        ),
        kind="deadline",
        priority="high",
        refs=[],
        action=SuggestionAction(type="none", label="Tick it off once you're registered"),
        due_date=due,
    )


def _broadcasting_fee(ledger: Ledger, moved: date) -> Suggestion:
    return make_idea(
        RULE_ID,
        BROADCASTING_ENTITY,
        (moved.isoformat(),),
        IdeaText(
            "Tell the broadcasting fee office your new address",
            _BROADCASTING_TIP,
            f"You moved in on {day_label(moved, ledger.today)}.",
        ),
        kind="hygiene",
        priority="low",
        refs=[],
        action=SuggestionAction(type="none", label="Tick it off once it's changed"),
        due_date=None,
    )


def _tell(ledger: Ledger, found: Listed, moved: date, lines: list[str]) -> Suggestion:
    party = found.party
    body = " ".join(part for part in (_reason(found, ledger.today, lines), _tip(found)) if part)
    return make_idea(
        RULE_ID,
        party.id,
        (moved.isoformat(),),
        IdeaText(
            f"Tell {party.name} your new address",
            body,
            f"You moved in on {day_label(moved, ledger.today)}.",
        ),
        kind="hygiene",
        priority="low",
        refs=[SuggestionRef(type="party", id=party.id)],
        action=SuggestionAction(
            type="open", target_type="party", target_id=party.id, label="Write the letter"
        ),
        due_date=None,
    )


def moving_ideas(ledger: Ledger) -> list[Suggestion]:
    """The ``moved_house`` rows: registration first, the broadcasting fee office when no listed organisation is
    the broadcaster, then every organisation not yet told by a letter marked sent. ``[]`` without a move, or
    once it is more than :data:`MOVE_WINDOW_DAYS` ago."""
    moved = parse_day(ledger.profile.moved_on)
    if moved is None or (ledger.today - moved).days > MOVE_WINDOW_DAYS:
        return []
    listed = who_to_tell(ledger)
    told = _told(ledger, moved)
    ideas = [_registration(ledger, moved)]
    if not any(found.broadcaster for found in listed):
        ideas.append(_broadcasting_fee(ledger, moved))
    lines = address_lines(ledger.profile.address, ledger.profile.old_address)
    ideas += [_tell(ledger, found, moved, lines) for found in listed if found.party.id not in told]
    return ideas
