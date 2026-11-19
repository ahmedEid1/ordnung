"""The sender's-Land hooks of the replays: context managers that change what the Ordnung condition's rules engine
knows about the sender's Land while a replay runs. :func:`sender_land_unknown` takes the Land away, as in the app
until the person sets it for that sender; :func:`sender_land_suggested` gives it the state the postcode on the
sender's letter suggests, as if the person said Yes to every suggestion. ``scripts/eval_without_land.py`` replays
the benchmark with both, and the end-to-end run (:func:`evals.e2e.harness.benchmark_dates`) takes its parity
reference from the first."""

from __future__ import annotations

import contextlib
import dataclasses
from collections.abc import Iterator, Sequence

from evals import conditions
from evals.records import Entry
from ordnung.models import DocumentExtraction, Page
from ordnung.rules import RuleContext
from ordnung.rules.postcodes import Reason, suggest_land_why


@contextlib.contextmanager
def sender_land_unknown() -> Iterator[None]:
    """Within the block, the Ordnung condition's rules engine never learns the sender's Land."""
    original = conditions.ordnung_rule_context

    def unknown(entry: Entry, extraction: DocumentExtraction, pages: Sequence[Page] = ()) -> RuleContext:
        return dataclasses.replace(original(entry, extraction, pages), region=None)

    conditions.ordnung_rule_context = unknown
    try:
        yield
    finally:
        conditions.ordnung_rule_context = original


@contextlib.contextmanager
def sender_land_suggested() -> Iterator[dict[str, tuple[str | None, Reason]]]:
    """Within the block, the Ordnung condition's rules engine is given the state the postcode on the sender's
    letter suggests as the sender's Land (none: nationwide holidays), as if the person said Yes to every
    suggestion. Yields each letter's suggested Land and the reason, by entry id, as the replay fills them in."""
    original = conditions.ordnung_rule_context
    suggested: dict[str, tuple[str | None, Reason]] = {}

    def confirmed(entry: Entry, extraction: DocumentExtraction, pages: Sequence[Page] = ()) -> RuleContext:
        sender = extraction.sender
        hit, reason = suggest_land_why(  # no own-Land check: the benchmark has no profile address
            sender.address if sender else None,
            email=sender.email if sender else None,
            website=sender.website if sender else None,
            visible_text="\n".join(page.text for page in pages),
        )
        region = hit.region if hit else None
        suggested[entry.id] = (region, reason)
        return dataclasses.replace(original(entry, extraction, pages), region=region)

    conditions.ordnung_rule_context = confirmed
    try:
        yield suggested
    finally:
        conditions.ordnung_rule_context = original
