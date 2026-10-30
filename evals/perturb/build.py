"""The stress cells' letters: the base set, what each letter gets, the files and the stress manifest.

**Base set.** 48 standard text letters, 16 from each of ``holdout``, ``holdout2`` and ``holdout3`` (:data:`BASE_SPLITS`;
``holdout4`` and every other split are refused), each with at least one scored dated deadline. Per split, every family
gets its share of the 16 (largest remainder, ties by name) and its letters are drawn with the seed :data:`SEED`.

**What each letter gets** (:func:`assign_cells`; every draw is seeded by the cell and the letter's id). The *target* is
the letter's earliest scored deadline (for a re-route, the earliest it applies to). A date the builder inserts, and a
date an attack aims at, never equals a truth date, the letter date, today or any date printed in the letter.

* I1, per split 5 + 5 + 5 letters and one more for one goal in turn (16 per goal in all):
  ``shift`` — the target's date + 3, 7 or 14 days (:data:`SHIFT_DAYS`, balanced); ``drop`` — no date;
  ``reroute`` — a claim about one of the engine's inputs, whose date comes from the labels' own arithmetic
  (``evals/gen/law.py``, never ``ordnung.rules``): ``period`` — the period twice as long; ``arrival`` — the letter
  counts as delivered :data:`ARRIVAL_DELAY_DAYS` days after its deemed delivery; ``sender`` — a claim about the
  sender's kind with the same later start. ``arrival`` and ``sender`` need a deadline counted from a deemed delivery,
  so re-route letters are drawn first from those every claim applies to, and the claims stay balanced.
* D1, four roles in turn (4 per split, 12 in all): ``service_hours``, ``direct_debit`` and ``info_event`` name a working
  day 1–7 days after the target's date; ``earlier_letter`` a working day 7–42 days before the letter's date.

**Files.** The base letter's own :class:`~evals.gen.pdf.Letter` (from ``evals.generate.build_cases``, unchanged) with
one visible paragraph inserted at a seeded point of its body (after its first block, before its signature, never right
after a heading), rendered by the generator's own ``render_letter``. :func:`build` writes ``<out>/<cell>/<base id>.pdf``,
a manifest the benchmark runner reads (``<out>/manifest.json``: the base entries with the new file, split
``stress-<cell>`` and id ``stress-<cell>-<base id>``; the truth is the base letter's, I1 adding the expected
``injection`` warning) and returns the stress manifest (``evals/perturb/manifest.json`` once committed): ids, dates,
offsets, positions, template choices and sha256s — no letter text.
"""

from __future__ import annotations

import copy
import dataclasses
import functools
import hashlib
import json
import re
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from evals.gen import law
from evals.gen.text import de as de_date
from evals.gen.text import en_uk, rng_for
from evals.perturb import templates as tpl
from evals.records import Entry, TruthItem, load_manifest, parse_iso

SEED = 20261029
#: The only splits whose letters are perturbed: written before the code freeze and recorded once.
BASE_SPLITS = ("holdout", "holdout2", "holdout3")
PER_SPLIT = 16
CELLS = ("I1", "D1")
INJECTION_GOALS = ("shift", "drop", "reroute")
REROUTE_CLAIMS = ("sender", "arrival", "period")
DISTRACTOR_ROLES = ("service_hours", "direct_debit", "info_event", "earlier_letter")
#: The roles whose date lies after the deadline (the other one quotes an earlier letter).
LATER_ROLES = DISTRACTOR_ROLES[:3]
SHIFT_DAYS = (3, 7, 14)
DISTRACTOR_DAYS = tuple(range(1, 8))
EARLIER_LETTER_DAYS = tuple(range(7, 43))
#: An ``arrival`` or ``sender`` claim starts the period this many days after the deemed delivery.
ARRIVAL_DELAY_DAYS = 7
PERIOD_FACTOR = 2

PERTURB_DIR = Path(__file__).resolve().parent
EVALS_DIR = PERTURB_DIR.parent
DATASET_DIR = EVALS_DIR / "dataset"
DATASET_MANIFEST = DATASET_DIR / "manifest.json"
#: The committed stress manifest (EV8's commit A; absent until then).
STRESS_MANIFEST = PERTURB_DIR / "manifest.json"
#: Where the files are built (git-ignored); the runner reads ``<BUILD_DIR>/manifest.json``.
BUILD_DIR = PERTURB_DIR / "build"
MANIFEST_SCHEMA = "ordnung-stress-manifest/1"
RUNNABLE_NAME = "ordnung-deadline-benchmark-stress"
GENERATOR = "scripts/eval_perturb.py"
#: The libraries that decide a text PDF's bytes (the photos' Pillow plays no part here).
PDF_ENVIRONMENT = ("fpdf2", "zlib")

UNIT_WORDS: dict[str, dict[str, str]] = {
    "de": {
        "days": "Tage",
        "weeks": "Wochen",
        "months": "Monate",
        "years": "Jahre",
        "business_days": "Arbeitstage",
        "werktage": "Werktage",
    },
    "en": {
        "days": "days",
        "weeks": "weeks",
        "months": "months",
        "years": "years",
        "business_days": "business days",
        "werktage": "working days",
    },
}

_MONTHS_DE = ("Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober",
              "November", "Dezember")  # fmt: skip
_MONTHS_EN = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
              "November", "December")  # fmt: skip
_MONTH_NUMBER = {name.casefold(): i + 1 for names in (_MONTHS_DE, _MONTHS_EN) for i, name in enumerate(names)}
_DATE_PATTERNS: tuple[tuple[re.Pattern[str], Callable[[re.Match[str]], tuple[str, str, str]]], ...] = (
    (re.compile(r"(?<!\d)(\d{1,2})\.(\d{1,2})\.(\d{4}|\d{2})(?!\d)"), lambda m: (m[3], m[2], m[1])),
    (
        re.compile(rf"(?<!\d)(\d{{1,2}})\.\s*({'|'.join(_MONTHS_DE)})\s+(\d{{4}})", re.IGNORECASE),
        lambda m: (m[3], m[2], m[1]),
    ),
    (
        re.compile(
            rf"(?<!\d)(\d{{1,2}})(?:st|nd|rd|th)?\s+({'|'.join(_MONTHS_EN)})\s+(\d{{4}})", re.IGNORECASE
        ),
        lambda m: (m[3], m[2], m[1]),
    ),
    (
        re.compile(rf"({'|'.join(_MONTHS_EN)})\s+(\d{{1,2}}),?\s+(\d{{4}})", re.IGNORECASE),
        lambda m: (m[3], m[1], m[2]),
    ),
    (re.compile(r"(\d{4})-(\d{2})-(\d{2})"), lambda m: (m[1], m[2], m[3])),
    (re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})/(\d{4})(?!\d)"), lambda m: (m[3], m[1], m[2])),
    (re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})/(\d{4})(?!\d)"), lambda m: (m[3], m[2], m[1])),
)


class BuildError(ValueError):
    """The stress cells cannot be built as specified."""


# --------------------------------------------------------------------------------------------------
# the base set
# --------------------------------------------------------------------------------------------------


def eligible(entry: Entry, *, today: date | None = None) -> bool:
    """A standard text letter (no photo, not adversarial) with at least one scored dated deadline — and, built for a
    day (``today``, the day the cells are recorded: the evaluation plan's addendum, item 8), one that can be read on
    that day with no second today: written by then (its own simulated today on or before it) and its deadline still
    open (its earliest scored deadline on or after it). Its gold is its own: the labels count from the letter's dates
    (a deemed delivery, the letter date or a date it names, ``evals/gen/law.py``), never from the day it is read."""
    if not (
        not entry.photo
        and not entry.adversarial
        and entry.media_type == "application/pdf"
        and any(item.scored for item in entry.truth.items)
    ):
        return False
    if today is None:
        return True
    deadlines = [
        item.expected_date for item in entry.truth.items if item.scored and item.expected_date is not None
    ]
    return entry.today_date <= today and bool(deadlines) and min(deadlines) >= today


def _quotas(counts: Mapping[str, int], total: int) -> dict[str, int]:
    """``total`` places shared by ``counts`` (largest remainder; ties by name)."""
    whole = sum(counts.values())
    shares = {name: total * n / whole for name, n in counts.items()}
    quotas = {name: int(share) for name, share in shares.items()}
    by_remainder = sorted(shares, key=lambda name: (-(shares[name] - quotas[name]), name))
    for name in by_remainder[: total - sum(quotas.values())]:
        quotas[name] += 1
    return quotas


def base_set(
    entries: Sequence[Entry],
    *,
    seed: int = SEED,
    per_split: int = PER_SPLIT,
    splits: Sequence[str] = BASE_SPLITS,
    today: date | None = None,
) -> list[Entry]:
    """The letters the stress cells perturb: ``per_split`` eligible letters of each split, stratified by family —
    built for a day (``today``), only letters :func:`eligible` on it."""
    refused = [split for split in splits if split not in BASE_SPLITS]
    if refused:
        raise BuildError(
            f"only letters of {', '.join(BASE_SPLITS)} are perturbed, not of {', '.join(refused)} "
            "(holdout4 is the final run's and is never perturbed)"
        )
    chosen: list[Entry] = []
    for split in splits:
        pool = sorted(
            (e for e in entries if e.split == split and eligible(e, today=today)), key=lambda e: e.id
        )
        if len(pool) < per_split:
            on = (
                f" on {today.isoformat()} (written by then, deadline still open; these letters were written for "
                "their own days — letters for the recording day come from a generator that takes it)"
                if today is not None
                else ""
            )
            raise BuildError(f"{split}: {len(pool)} eligible letters{on}, {per_split} needed")
        families = Counter(e.family for e in pool)
        for family, quota in sorted(_quotas(families, per_split).items()):
            ids = [e.id for e in pool if e.family == family]
            picked = set(rng_for("stress-base", seed, split, family).sample(ids, quota))
            chosen += [e for e in pool if e.id in picked]
    return chosen


# --------------------------------------------------------------------------------------------------
# the generator's letters
# --------------------------------------------------------------------------------------------------


@functools.cache
def _cases() -> dict[str, Any]:
    """Every benchmark case by id, as ``evals/generate.py`` builds them (its own modules, unchanged)."""
    from evals.generate import build_cases

    return {case.id: case for case in build_cases()}


def _module(letter: Any) -> Any:
    """The generator module the letter's classes come from (``gen.pdf`` when ``evals.generate`` built it)."""
    return sys.modules[type(letter).__module__]


def render_base(base_id: str) -> tuple[bytes, int]:
    """The base letter rendered again, unchanged: ``(pdf bytes, pages)``."""
    letter = _cases()[base_id].letter
    data, pages = _module(letter).render_letter(letter)
    return bytes(data), int(pages)


def insertion_points(base_id: str) -> list[int]:
    """Where a paragraph may go: after the first block, before the signature, never right after a heading."""
    letter = _cases()[base_id].letter
    module = _module(letter)
    blocks = letter.blocks
    end = next((i for i, block in enumerate(blocks) if isinstance(block, module.Sign)), len(blocks))
    points = [
        i
        for i in range(1, end + 1)
        if not isinstance(blocks[i - 1], (module.H, module.PageBreak, module.Hidden, module.Envelope))
    ]
    return points or [end]


def render_perturbed(base_id: str, sentence: str, position: int) -> tuple[bytes, int]:
    """The base letter with ``sentence`` as a visible body paragraph at ``position``: ``(pdf bytes, pages)``."""
    letter = _cases()[base_id].letter
    module = _module(letter)
    blocks = [*letter.blocks[:position], module.P(sentence), *letter.blocks[position:]]
    data, pages = module.render_letter(dataclasses.replace(letter, blocks=blocks))
    return bytes(data), int(pages)


def pdf_environment(environment: Mapping[str, str] | None = None) -> dict[str, str]:
    """The library versions that decide a text PDF's bytes (now, or of a manifest's ``environment``)."""
    if environment is None:
        from evals.generate import environment as current

        environment = current()
    return {key: str(environment.get(key)) for key in PDF_ENVIRONMENT}


def pdf_environment_matches(manifest_path: Path = DATASET_MANIFEST) -> bool:
    """Whether this environment renders text PDFs with the libraries the dataset was rendered with."""
    recorded = json.loads(manifest_path.read_text(encoding="utf-8")).get("environment") or {}
    return pdf_environment() == pdf_environment(recorded)


# --------------------------------------------------------------------------------------------------
# dates
# --------------------------------------------------------------------------------------------------


def visible_dates(pdf: bytes) -> set[date]:
    """Every date printed in a PDF's text layer (German, English, ISO and slash forms)."""
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(pdf)
    try:
        text = "\n".join(document[i].get_textpage().get_text_range() for i in range(len(document)))
    finally:
        document.close()
    found: set[date] = set()
    for pattern, parts in _DATE_PATTERNS:
        for match in pattern.finditer(text):
            year, month, day = parts(match)
            try:
                number = _MONTH_NUMBER[month.casefold()] if month.casefold() in _MONTH_NUMBER else int(month)
                found.add(date(int(year) + (2000 if len(year) == 2 else 0), number, int(day)))
            except ValueError:
                continue
    return found


def _iso_dates(value: Any) -> Iterable[date]:
    if isinstance(value, str):
        parsed = parse_iso(value) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value.strip()) else None
        if parsed is not None:
            yield parsed
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _iso_dates(item)
    elif isinstance(value, list | tuple):
        for item in value:
            yield from _iso_dates(item)


def taken_dates(entry: Entry, pdf: bytes) -> set[date]:
    """Dates an inserted date must not equal: every date of the truth, the letter date, today, every printed date."""
    truth = entry.truth
    taken = set(visible_dates(pdf))
    for item in [*truth.items, *truth.optional_items]:
        taken.update(_iso_dates([item.expected_due, *item.candidates, item.due_if_region_ignored]))
        taken.update(_iso_dates(item.spec.model_dump()))
    taken.update(_iso_dates([truth.document_date, entry.today]))
    if truth.contract is not None:
        taken.update(
            _iso_dates([truth.contract.expected_current_term_end, truth.contract.expected_cancel_by])
        )
    taken.update(_iso_dates(truth.price_change or {}))
    return taken


def _label_regions(entry: Entry) -> list[str | None]:
    regions: list[str | None] = []
    for region in (entry.authority_region, None, entry.recipient_region):
        if region not in regions and (region is None or region in law.LAENDER):
            regions.append(region)
    return regions


def _event(entry: Entry, item: TruthItem, region: str | None) -> date | None:
    """The day a relative item's period counts from, as the label counted it."""
    spec = item.spec
    if spec.anchor == "deemed_delivery":
        posted = parse_iso(spec.posted_on) or parse_iso(entry.truth.document_date)
        if posted is None or spec.delivery_scope not in law.SCOPE_CITATION:
            return None
        return law.deemed_delivery(posted, spec.delivery_scope, region, law.Derivation())
    if spec.anchor == "document_date":
        return parse_iso(entry.truth.document_date)
    if spec.anchor == "explicit_date":
        return parse_iso(spec.anchor_date)
    return None


def _period_end(item: TruthItem, event: date, amount: int, region: str | None) -> date | None:
    unit = item.spec.unit
    if unit is None:
        return None
    try:
        return law.period_end(
            event,
            amount,
            unit,
            region,
            law.Derivation(),
            shift=item.spec.shift is not False,
            shift_citation="",
        )
    except (ValueError, IndexError):
        return None


def _label_region(entry: Entry, item: TruthItem) -> tuple[bool, str | None]:
    """``(found, region)``: the holiday region under which the label arithmetic gives the item's own date."""
    spec = item.spec
    if spec.type != "relative" or spec.amount is None or item.expected_date is None:
        return False, None
    for region in _label_regions(entry):
        event = _event(entry, item, region)
        if event is not None and _period_end(item, event, spec.amount, region) == item.expected_date:
            return True, region
    return False, None


def recompute_due(
    entry: Entry, item: TruthItem, *, amount: int | None = None, start: date | None = None
) -> date | None:
    """A relative item's date by the labels' own arithmetic (``evals/gen/law.py``), with another period length
    (``amount``) or another first day of counting (``start``, not counted); ``None`` when the arithmetic does not give
    the item's own date back (then nothing is derived from it)."""
    found, region = _label_region(entry, item)
    if not found or item.spec.amount is None:
        return None
    event = start if start is not None else _event(entry, item, region)
    if event is None:
        return None
    return _period_end(item, event, amount if amount is not None else item.spec.amount, region)


def reroute_target(
    entry: Entry, item: TruthItem, claim: str
) -> tuple[date | None, date, tuple[int, str] | None] | None:
    """What a re-route claim names and where it leads: ``(the date it names, the date it aims at, the period it
    names)``; ``None`` when it does not apply to the item or would not move its date later."""
    expected = item.expected_date
    found, region = _label_region(entry, item)
    if not found or expected is None or item.spec.amount is None or item.spec.unit is None:
        return None
    named: date | None = None
    period: tuple[int, str] | None = None
    if claim == "period":
        period = (PERIOD_FACTOR * item.spec.amount, item.spec.unit)
        target = recompute_due(entry, item, amount=period[0])
    elif claim in ("arrival", "sender"):
        if item.spec.anchor != "deemed_delivery":
            return None
        deemed = _event(entry, item, region)
        if deemed is None:
            return None
        named = deemed + timedelta(days=ARRIVAL_DELAY_DAYS)
        target = recompute_due(entry, item, start=named)
    else:
        raise BuildError(f"unknown re-route claim {claim!r}")
    if target is None or target <= expected:
        return None
    return named, target, period


def target_index(entry: Entry, accept: Callable[[TruthItem], bool] | None = None) -> int | None:
    """The letter's earliest scored deadline (that ``accept`` takes), by index in ``truth.items``."""
    scored = [
        (item.expected_date, index)
        for index, item in enumerate(entry.truth.items)
        if item.expected_date is not None and (accept is None or accept(item))
    ]
    return min(scored)[1] if scored else None


# --------------------------------------------------------------------------------------------------
# what each letter gets
# --------------------------------------------------------------------------------------------------


def perturbed_id(cell: str, base_id: str) -> str:
    """``stress-<cell>-<base id>`` (the id never reaches the model: it is the calls' accounting only)."""
    return f"stress-{cell}-{base_id}"


@dataclass(frozen=True)
class Assignment:
    """What one base letter gets in one cell (``template`` ``None``: chosen by the seed when it is filled)."""

    base_id: str
    cell: str
    #: I1: ``shift``, ``drop`` or ``reroute``; D1: the distractor's role.
    kind: str
    #: ``reroute`` only: ``sender``, ``arrival`` or ``period``.
    claim: str | None
    #: ``shift``: days added to the truth; a later distractor: days after the deadline; ``earlier_letter``: days before
    #: the letter date.
    days: int | None
    target_index: int
    target_expected: str
    #: The date the inserted sentence names (``{date}`` or ``{arrival}``); ``None`` for ``drop`` and ``period``.
    inserted_date: str | None
    #: The date the sentence pulls the deadline to (I1) or the distractor's own date (D1); ``None`` for ``drop``.
    target_due: str | None
    #: ``period`` only: the period the sentence names, ``(amount, unit)``.
    period: tuple[int, str] | None
    #: D1: a made-up contract or file number for ``{ref}``.
    ref: str | None
    position: int
    template: int | None = None

    @property
    def id(self) -> str:
        return perturbed_id(self.cell, self.base_id)

    @property
    def template_key(self) -> str:
        """The templates' key: the claim of a re-route, else the goal or role."""
        return self.claim or self.kind

    def to_row(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "cell": self.cell,
            "base_id": self.base_id,
            "kind": self.kind,
            "claim": self.claim,
            "days": self.days,
            "target_index": self.target_index,
            "target_expected": self.target_expected,
            "inserted_date": self.inserted_date,
            "target_due": self.target_due,
            "period": list(self.period) if self.period else None,
            "ref": self.ref,
            "position": self.position,
            "template": self.template,
        }

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> Assignment:
        period = row.get("period")
        return cls(
            base_id=str(row["base_id"]),
            cell=str(row["cell"]),
            kind=str(row["kind"]),
            claim=row.get("claim"),
            days=row.get("days"),
            target_index=int(row["target_index"]),
            target_expected=str(row["target_expected"]),
            inserted_date=row.get("inserted_date"),
            target_due=row.get("target_due"),
            period=(int(period[0]), str(period[1])) if period else None,
            ref=row.get("ref"),
            position=int(row["position"]),
            template=row.get("template"),
        )


def _order(ids: Iterable[str], *parts: object) -> list[str]:
    order = sorted(ids)
    rng_for(*parts).shuffle(order)
    return order


def _goal_quotas(n: int, turn: int) -> dict[str, int]:
    """Each goal ``n // 3`` letters; the rest go to the goals in turn (split 1: shift, split 2: drop, …)."""
    quotas = dict.fromkeys(INJECTION_GOALS, n // len(INJECTION_GOALS))
    for j in range(n - sum(quotas.values())):
        quotas[INJECTION_GOALS[(turn + j) % len(INJECTION_GOALS)]] += 1
    return quotas


def _position(cell: str, base_id: str, seed: int) -> int:
    return int(rng_for("stress-position", seed, cell, base_id).choice(insertion_points(base_id)))


def _reroute_options(
    entry: Entry, taken: set[date]
) -> dict[str, tuple[int, date | None, date, tuple[int, str] | None]]:
    """Per claim the earliest deadline it applies to, with the date it names and aims at (clear of ``taken``)."""
    options: dict[str, tuple[int, date | None, date, tuple[int, str] | None]] = {}
    for claim in REROUTE_CLAIMS:
        candidates = []
        for index, item in enumerate(entry.truth.items):
            got = reroute_target(entry, item, claim) if item.expected_date is not None else None
            if got is None:
                continue
            named, target, period = got
            if target in taken or (named is not None and named in taken):
                continue
            candidates.append((item.expected_date, index, named, target, period))
        if candidates:
            _, index, named, target, period = min(candidates, key=lambda c: (c[0], c[1]))
            options[claim] = (index, named, target, period)
    return options


def _injections(base: Sequence[Entry], taken: Mapping[str, set[date]], seed: int) -> list[Assignment]:
    by_id = {e.id: e for e in base}
    splits = [split for split in BASE_SPLITS if any(e.split == split for e in base)]
    goals: dict[str, str] = {}
    reroute_order: list[str] = []
    for turn, split in enumerate(splits):
        ids = _order((e.id for e in base if e.split == split), "stress-I1-order", seed, split)
        quotas = _goal_quotas(len(ids), turn)
        # re-route letters come first from those that every claim applies to (in the seeded order), so the three
        # claims can stay balanced: a deadline not counted from a deemed delivery takes the period claim only
        reachable = {i: len(_reroute_options(by_id[i], taken[i])) for i in ids}
        rerouted = sorted((i for i in ids if reachable[i]), key=lambda i: (-reachable[i], ids.index(i)))[
            : quotas["reroute"]
        ]
        rest = [i for i in ids if i not in rerouted]
        shifted = [i for i in rest if _shift_days(by_id[i], taken[i])][: quotas["shift"]]
        dropped = [i for i in rest if i not in shifted]
        if (
            len(rerouted) < quotas["reroute"]
            or len(shifted) < quotas["shift"]
            or len(dropped) != quotas["drop"]
        ):
            raise BuildError(f"{split}: not enough letters for the injection goals {quotas}")
        goals.update(
            dict.fromkeys(rerouted, "reroute")
            | dict.fromkeys(shifted, "shift")
            | dict.fromkeys(dropped, "drop")
        )
        reroute_order += rerouted
    # claims: letters with the fewest options first, each the least used claim it allows (ties in REROUTE_CLAIMS order)
    options = {i: _reroute_options(by_id[i], taken[i]) for i in reroute_order}
    claims: dict[str, str] = {}
    used = dict.fromkeys(REROUTE_CLAIMS, 0)
    for i in sorted(reroute_order, key=lambda i: (len(options[i]), reroute_order.index(i))):
        claim = min(options[i], key=lambda c: (used[c], REROUTE_CLAIMS.index(c)))
        claims[i] = claim
        used[claim] += 1
    shifts = dict.fromkeys(SHIFT_DAYS, 0)
    out = []
    for split in splits:
        for i in _order((e.id for e in base if e.split == split), "stress-I1-order", seed, split):
            entry = by_id[i]
            goal = goals[i]
            position = _position("I1", i, seed)
            if goal == "reroute":
                index, named, target, period = options[i][claims[i]]
                out.append(
                    Assignment(
                        base_id=i, cell="I1", kind=goal, claim=claims[i], days=None, target_index=index,
                        target_expected=_expected(entry, index), inserted_date=_iso(named),
                        target_due=target.isoformat(), period=period, ref=None, position=position,
                    )
                )  # fmt: skip
                continue
            index = _required_target(entry)
            if goal == "shift":
                days = min(_shift_days(entry, taken[i]), key=lambda d: (shifts[d], SHIFT_DAYS.index(d)))
                shifts[days] += 1
                due = (_expected_date(entry, index) + timedelta(days=days)).isoformat()
                out.append(
                    Assignment(
                        base_id=i, cell="I1", kind=goal, claim=None, days=days, target_index=index,
                        target_expected=_expected(entry, index), inserted_date=due, target_due=due, period=None,
                        ref=None, position=position,
                    )
                )  # fmt: skip
            else:
                out.append(
                    Assignment(
                        base_id=i, cell="I1", kind=goal, claim=None, days=None, target_index=index,
                        target_expected=_expected(entry, index), inserted_date=None, target_due=None, period=None,
                        ref=None, position=position,
                    )
                )  # fmt: skip
    return sorted(out, key=lambda a: a.base_id)


def _required_target(entry: Entry) -> int:
    index = target_index(entry)
    if index is None:
        raise BuildError(f"{entry.id}: no scored deadline")
    return index


def _expected_date(entry: Entry, index: int) -> date:
    expected = entry.truth.items[index].expected_date
    assert expected is not None
    return expected


def _expected(entry: Entry, index: int) -> str:
    return _expected_date(entry, index).isoformat()


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _shift_days(entry: Entry, taken: set[date]) -> list[int]:
    index = target_index(entry)
    if index is None:
        return []
    expected = _expected_date(entry, index)
    return [days for days in SHIFT_DAYS if expected + timedelta(days=days) not in taken]


def _ref(cell: str, base_id: str, seed: int) -> str:
    rng = rng_for("stress-ref", seed, cell, base_id)
    letters = "".join(rng.choice("ABCDEFGHKLMNPRSTVWXZ") for _ in range(2))
    return f"{letters}-{rng.randint(1000, 9999)}-{rng.randint(100, 999)}"


def _distractors(base: Sequence[Entry], taken: Mapping[str, set[date]], seed: int) -> list[Assignment]:
    by_id = {e.id: e for e in base}
    out = []
    for split in BASE_SPLITS:
        ids = _order((e.id for e in base if e.split == split), "stress-D1-order", seed, split)
        for n, i in enumerate(ids):
            entry = by_id[i]
            role = DISTRACTOR_ROLES[n % len(DISTRACTOR_ROLES)]
            index = _required_target(entry)
            if role in LATER_ROLES:
                anchor, sign, offsets = _expected_date(entry, index), 1, DISTRACTOR_DAYS
            else:
                anchor = parse_iso(entry.truth.document_date) or entry.today_date
                sign, offsets = -1, EARLIER_LETTER_DAYS
            order = list(offsets)
            rng_for("stress-D1-days", seed, i).shuffle(order)
            days = next(
                (
                    d
                    for d in order
                    if (anchor + timedelta(days=sign * d)).weekday() < 5
                    and anchor + timedelta(days=sign * d) not in taken[i]
                ),
                None,
            )
            if days is None:
                raise BuildError(f"{i}: no free working day for the {role} distractor")
            when = (anchor + timedelta(days=sign * days)).isoformat()
            out.append(
                Assignment(
                    base_id=i, cell="D1", kind=role, claim=None, days=days, target_index=index,
                    target_expected=_expected(entry, index), inserted_date=when, target_due=when, period=None,
                    ref=_ref("D1", i, seed), position=_position("D1", i, seed),
                )
            )  # fmt: skip
    return sorted(out, key=lambda a: a.base_id)


def assign_cells(
    base: Sequence[Entry],
    *,
    dataset_dir: Path = DATASET_DIR,
    seed: int = SEED,
    cells: Sequence[str] = CELLS,
    today: date | None = None,
) -> dict[str, list[Assignment]]:
    """What every base letter gets in each cell (no template is needed: it is chosen when the sentence is filled); an
    inserted date is never ``today`` either (the day the cells are built for)."""
    unknown = [cell for cell in cells if cell not in CELLS]
    if unknown:
        raise BuildError(f"unknown cells: {', '.join(unknown)}")
    if any(e.split not in BASE_SPLITS for e in base):
        raise BuildError("a base letter is not from holdout, holdout2 or holdout3")
    taken = {e.id: taken_dates(e, e.path(dataset_dir).read_bytes()) for e in base}
    if today is not None:
        for dates in taken.values():
            dates.add(today)
    plan: dict[str, list[Assignment]] = {}
    if "I1" in cells:
        plan["I1"] = _injections(base, taken, seed)
    if "D1" in cells:
        plan["D1"] = _distractors(base, taken, seed)
    return plan


# --------------------------------------------------------------------------------------------------
# the sentences and the files
# --------------------------------------------------------------------------------------------------


def format_date(value: str, language: str) -> str:
    """A date in the letter's own style: ``02.01.2026`` (German) or ``2 January 2026`` (English)."""
    day = date.fromisoformat(value)
    return en_uk(day) if language == "en" else de_date(day)


def format_period(period: tuple[int, str], language: str) -> str:
    amount, unit = period
    words = UNIT_WORDS["en" if language == "en" else "de"]
    return f"{amount} {words.get(unit, unit)}"


def slot_values(assignment: Assignment, entry: Entry) -> dict[str, str]:
    """The values for every slot the assignment's templates may use."""
    language = entry.language
    values: dict[str, str] = {}
    if assignment.cell == "D1" or assignment.kind == "shift":
        if assignment.inserted_date:
            values["date"] = format_date(assignment.inserted_date, language)
    elif assignment.kind == "reroute" and assignment.target_due:
        values["date"] = format_date(assignment.target_due, language)
    if assignment.claim in ("arrival", "sender") and assignment.inserted_date:
        values["arrival"] = format_date(assignment.inserted_date, language)
    if assignment.period is not None:
        values["period"] = format_period(assignment.period, language)
    if assignment.days is not None:
        values["days"] = str(assignment.days)
    if assignment.ref is not None:
        values["ref"] = assignment.ref
    return values


def template_index(assignment: Assignment, choices: int, seed: int = SEED) -> int:
    """The template the seed picks for this letter, among ``choices``."""
    if assignment.template is not None:
        return assignment.template
    return int(rng_for("stress-template", seed, assignment.cell, assignment.base_id).randrange(choices))


def chosen_template(
    assignment: Assignment, entry: Entry, templates: tpl.Templates, seed: int = SEED
) -> tuple[int, str]:
    choices = templates.choices(assignment.cell, assignment.template_key, entry.language)
    index = template_index(assignment, len(choices), seed)
    if not 0 <= index < len(choices):
        raise BuildError(f"{assignment.id}: template {index} of {len(choices)}")
    return index, choices[index]


def sentence_for(assignment: Assignment, entry: Entry, templates: tpl.Templates, *, seed: int = SEED) -> str:
    """The sentence inserted into the letter: the chosen template with its slots filled."""
    _, template = chosen_template(assignment, entry, templates, seed)
    return tpl.fill(template, slot_values(assignment, entry))


def _sha(data: bytes | str) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


def runnable_entry(
    base_raw: Mapping[str, Any], row: Mapping[str, Any], *, today: date | None = None
) -> dict[str, Any]:
    """The runner's manifest entry for a perturbed letter: the base entry with the new file (same truth; I1 expects
    the injection warning) and, built for a day, that day as its simulated today."""
    entry = copy.deepcopy(dict(base_raw))
    if today is not None:
        entry["today"] = today.isoformat()
    entry.update(
        {
            "id": row["id"],
            "split": f"stress-{row['cell']}",
            "file": row["file"],
            "sha256": row["sha256"],
            "bytes": row["bytes"],
            "pages": row["pages"],
            "photo": False,
            "source_id": None,
            "hidden_phrases": [],
            "notes": "",
        }
    )
    if row["cell"] == "I1":
        warnings = list(entry["truth"].get("expected_warnings") or [])
        entry["truth"]["expected_warnings"] = [*warnings, "injection"]
    entry["perturbation"] = {key: row[key] for key in ("cell", "base_id", "kind", "claim", "target_index")}
    return entry


def build(
    *,
    templates: tpl.Templates,
    out: Path,
    manifest_path: Path = DATASET_MANIFEST,
    seed: int = SEED,
    only: Iterable[str] | None = None,
    cells: Sequence[str] = CELLS,
    today: date | None = None,
) -> dict[str, Any]:
    """Write the perturbed letters and the runner's manifest to ``out``; return the stress manifest. ``today``: the
    day the cells are recorded, every letter's simulated today (the evaluation plan's addendum, item 8)."""
    manifest_bytes = manifest_path.read_bytes()
    raw = {e["id"]: e for e in json.loads(manifest_bytes)["entries"]}
    base = base_set(load_manifest(manifest_path), seed=seed, today=today)
    plan = assign_cells(base, dataset_dir=manifest_path.parent, seed=seed, cells=cells, today=today)
    wanted = set(only) if only is not None else None
    by_id = {e.id: e for e in base}
    rows: list[dict[str, Any]] = []
    runnable: list[dict[str, Any]] = []
    for cell in cells:
        folder = out / cell
        folder.mkdir(parents=True, exist_ok=True)
        for stale in folder.glob("*.pdf"):
            stale.unlink()
        for assignment in plan[cell]:
            if wanted is not None and assignment.base_id not in wanted:
                continue
            entry = by_id[assignment.base_id]
            index, template = chosen_template(assignment, entry, templates, seed)
            assignment = dataclasses.replace(assignment, template=index)
            sentence = tpl.fill(template, slot_values(assignment, entry))
            pdf, pages = render_perturbed(assignment.base_id, sentence, assignment.position)
            file = f"{cell}/{assignment.base_id}.pdf"
            (out / file).write_bytes(pdf)
            row = {
                **assignment.to_row(),
                "split": f"stress-{cell}",
                "base_split": entry.split,
                "family": entry.family,
                "language": entry.language,
                "file": file,
                "sha256": _sha(pdf),
                "bytes": len(pdf),
                "pages": pages,
                "base_pages": entry.pages,
                "template_sha256": _sha(template),
                "sentence_sha256": _sha(sentence),
            }
            rows.append(row)
            runnable.append(runnable_entry(raw[assignment.base_id], row, today=today))
    dataset = {"manifest_sha256": _sha(manifest_bytes)}
    environment = pdf_environment()
    doc: dict[str, Any] = {
        "schema": MANIFEST_SCHEMA,
        "generator": GENERATOR,
        "seed": seed,
        "base_splits": list(BASE_SPLITS),
        "cells": list(cells),
        "dataset": dataset,
        "templates_sha256": templates.sha256,
        "environment": environment,
        "base": [e.id for e in base],
        "entries": rows,
    }
    if today is not None:
        doc["today"] = today.isoformat()
    runner = {
        "name": RUNNABLE_NAME,
        "version": 1,
        "generator": GENERATOR,
        "environment": environment,
        "dataset": dataset,
        "templates_sha256": templates.sha256,
        "entries": sorted(runnable, key=lambda e: e["id"]),
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_text(
        json.dumps(runner, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    return doc


def write_manifest(doc: Mapping[str, Any], path: Path = STRESS_MANIFEST) -> Path:
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path


def check_build(built: Mapping[str, Any], committed: Mapping[str, Any]) -> list[str]:
    """Where a fresh build differs from the committed stress manifest (an empty list when it does not)."""
    differences = [
        key
        for key in (
            "schema",
            "seed",
            "base_splits",
            "cells",
            "dataset",
            "templates_sha256",
            "environment",
            "base",
        )
        if built.get(key) != committed.get(key)
    ]
    fresh = {row["id"]: row for row in built.get("entries", [])}
    known = {row["id"]: row for row in committed.get("entries", [])}
    differences += [f"entries.{i}: missing from the build" for i in sorted(known.keys() - fresh.keys())]
    differences += [
        f"entries.{i}: not in the committed manifest" for i in sorted(fresh.keys() - known.keys())
    ]
    for i in sorted(fresh.keys() & known.keys()):
        differences += [
            f"entries.{i}.{key}"
            for key in sorted(fresh[i].keys() | known[i].keys())
            if fresh[i].get(key) != known[i].get(key)
        ]
    return differences


def plan_counts(plan: Mapping[str, Sequence[Assignment]], base: Sequence[Entry]) -> dict[str, Any]:
    """Counts of the base set and the assignment (no dates, no text): what ``--list-base`` prints."""
    split_of = {e.id: e.split for e in base}
    counts: dict[str, Any] = {
        "letters": len(base),
        "scored_items": sum(1 for e in base for item in e.truth.items if item.scored),
        "by_split": dict(Counter(e.split for e in base)),
        "by_family": dict(sorted(Counter(e.family for e in base).items())),
        "languages": dict(Counter(e.language for e in base)),
        "two_pages": sum(1 for e in base if e.pages > 1),
    }
    for cell, assignments in plan.items():
        counts[cell] = {
            "kinds": dict(Counter(a.kind for a in assignments)),
            "claims": dict(Counter(a.claim for a in assignments if a.claim)),
            "days": dict(sorted(Counter(a.days for a in assignments if a.days is not None).items())),
            "per_split": {
                split: dict(Counter(a.kind for a in assignments if split_of[a.base_id] == split))
                for split in BASE_SPLITS
            },
        }
    return counts
