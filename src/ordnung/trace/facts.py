"""What each step of a reading records — the written policy for span attributes.

**Only data Ordnung already has, and never letter text.** A span keeps counts, scores, codes, the
dates the rules engine computed and the ids of the records a step used or produced; the view
(:mod:`ordnung.trace.view`) looks those records up when the trace is shown, so a span *points to*
a to-do's title, a quote or a sender's name instead of copying it, and deleting the letter deletes
everything a trace could say about it. Concretely a span never holds a quote, page text, a
transcript, a title, a summary, a name, an address, an IBAN or a reference number — only the *kind*
of a reference (``steuernummer``) that matched. A DateSpec is kept without its wording (``text``) and
without the model's ``legal_basis``; what is left is structure (``relative``, 1 ``months``,
``deemed_delivery``) and the dates it names, which the to-do holds as well.

One function per kind of step, so the whole vocabulary is on this page:

========  ===============================================================================
kind      attributes
========  ===============================================================================
run       ``reading`` (1, 2 …), ``trigger`` (``read`` | ``read_again``), ``private``, ``timing``;
          at the end ``ended`` (``done`` | ``failed`` | ``paused`` | ``stopped``; the span's error
          is a code — :mod:`ordnung.trace.runs` — never a message) and :func:`outcome`: ``result``
          (the letter's status), ``text_mode``, ``pages``, ``items``, ``needs_check``, ``warnings``
ocr       :func:`text_layer` (pages, text pages, pages to transcribe, words, hidden text);
          the transcription group: ``pages`` (and ``parallel``)
model     :func:`model_call` (call id, purpose, prompt, models, cache hit, outcome, repair of);
          a page transcript adds :func:`transcript` (legible, characters — not the text); the
          completeness re-ask adds :func:`completion` (the gap that triggered it, whether it was used)
verify    :func:`quote` per quote (target, grounding, page, scores, digit groups, reasons);
          the stage: :func:`verification` (counts per grounding) and, for a reading that came back
          incomplete, :func:`reading_check` (why, and which to-do code filed for it)
rules     :func:`dated` per to-do (the DateSpec's structure → due date, send-by, rule ids,
          confidence); a deadline the law adds: :func:`law_deadline`
link      :func:`party_match` (decision, party id, candidates with scores, reference kind);
          thread, contract, payment check and reminder decisions with the ids they chose
plan      :func:`planned` per to-do (action and why), rule to-dos, removed count
========  ===============================================================================
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Literal

from ordnung.models import ComputationReceipt, DateSpec, Evidence, Item, Page

if TYPE_CHECKING:
    from ordnung.ingest.verify import QuoteCheck

#: The fields of a DateSpec a trace keeps (everything but its wording and the model's ``legal_basis``).
SPEC_FIELDS = (
    "type",
    "date",
    "time",
    "anchor",
    "anchor_date",
    "amount",
    "unit",
    "delivery_rule",
    "shift_rule",
    "nature",
)
#: How many other parties a sender's match lists with their scores.
MAX_CANDIDATES = 3

QuoteTarget = Literal["item", "key_fact", "contract", "change", "remedy"]
PartyDecision = Literal["identifier", "name", "similar_name", "new", "none"]
PlanAction = Literal[
    "created",  # a new to-do
    "updated",  # the to-do of this sentence, refreshed from the new reading
    "kept_edited",  # the person edited it: left exactly as they left it
    "kept_later_date",  # recurring: its stored occurrence is later, and reading never moves it back
]


def text_layer(pages: Sequence[Page], hidden: bool) -> dict[str, Any]:
    """The text stage: how many pages had a text layer, how many go to transcription, how many words
    the layer has and whether hidden text was found (and kept from the model)."""
    return {
        "pages": len(pages),
        "text_pages": sum(page.text_source == "text" for page in pages),
        "to_transcribe": sum(page.text_source != "text" for page in pages),
        "words": sum(len(page.words) for page in pages),
        "hidden_text": hidden,
    }


def transcript(page: int, text: str, legible: bool) -> dict[str, Any]:
    """One page read from its image: legible or not, and how many characters came back (not which)."""
    return {"page": page, "legible": legible, "chars": len(text), "empty": not text.strip()}


def model_call(
    *,
    call_id: int | None,
    purpose: str,
    prompt_name: str,
    prompt_version: str,
    request_model: str,
    served_model: str | None,
    cache_hit: bool,
    outcome: str,
    repair_of: int | None,
) -> dict[str, Any]:
    """A model call: the usage-log row it wrote (tokens, cost and latency are read from there) and
    what identifies it — never the prompt or the answer."""
    return {
        "call_id": call_id,
        "purpose": purpose,
        "prompt": prompt_name,
        "prompt_version": prompt_version,
        "request_model": request_model,
        "served_model": served_model,
        "cache_hit": cache_hit,
        "outcome": outcome,
        "repair_of": repair_of,
    }


def quote(
    target: QuoteTarget,
    evidence: Evidence,
    check: QuoteCheck,
    *,
    index: int,
    reasons: Sequence[str] = (),
    item_id: str | None = None,
    slot_key: str | None = None,
) -> dict[str, Any]:
    """One quote looked up on the pages: what it belongs to (the ``index``-th item, key fact or
    contract quote of the reading; a to-do by id and slot), the grounding decided, the page and
    score, the exact-digits rule (groups checked, all matched) and the consistency reasons (codes of
    :mod:`ordnung.ingest.verify`: the quote does not state the date, period or amount)."""
    facts: dict[str, Any] = {
        "target": target,
        "index": index,
        "grounding": evidence.grounding,
        "page": evidence.page,
        "score": evidence.score,
        "best_score": check.best_score,
        "digit_groups": check.digit_groups,
        "digits_matched": check.digits_matched,
        "boxes": len(evidence.boxes),
        "consistent": not reasons,
        "reasons": list(reasons),
    }
    if item_id is not None:
        facts["item_id"] = item_id
    if slot_key is not None:
        facts["slot_key"] = slot_key
    return facts


def verification(groundings: Sequence[str], needs_check: int) -> dict[str, Any]:
    """The verify stage: how many quotes were found in the text layer, only in an AI transcript, or
    not at all, and how many dated to-dos need a check."""
    return {
        "quotes": len(groundings),
        "verified": sum(g == "verified" for g in groundings),
        "model_read": sum(g == "model_read" for g in groundings),
        "unverified": sum(g == "unverified" for g in groundings),
        "needs_check": needs_check,
    }


def completion(gap: str, *, accepted: bool, kept_because: str | None) -> dict[str, object]:
    """The completeness re-ask of a reading found incomplete (:func:`ordnung.ingest.extract.read_document`): the
    gap that triggered it (``empty`` | ``remedy_left_out``), whether its answer replaced the first reading, and
    if not why (:data:`ordnung.ingest.extract.KeptBecause`: ``no_answer`` | ``unanswered`` | ``unusable`` |
    ``not_better`` | ``date`` | ``dropped`` | ``uncovered`` | ``unchecked`` | ``later`` | ``ungrounded`` |
    ``quotes``) — codes only."""
    return {"reading_gap": gap, "accepted": accepted, "kept_because": kept_because}


def reading_check(gap: str, item: str) -> dict[str, object]:
    """A reading found incomplete (:mod:`ordnung.ingest.gaps`): why (``empty`` | ``remedy_left_out``) and the
    to-do code filed for it (``dated`` | ``undated`` | ``read_yourself``) — codes only."""
    return {"reading_gap": gap, "check_item": item}


def spec_structure(spec: DateSpec | None) -> dict[str, Any] | None:
    """A DateSpec without its wording (:data:`SPEC_FIELDS`)."""
    if spec is None:
        return None
    return {name: getattr(spec, name) for name in SPEC_FIELDS}


def dated(
    spec: DateSpec,
    receipt: ComputationReceipt | None,
    *,
    source: str,
    index: int,
    item_id: str | None = None,
    slot_key: str | None = None,
) -> dict[str, Any]:
    """The rules engine's step for one to-do: the DateSpec in (structure only), the dates out, the
    rules it applied and how sure it is (the receipt itself is on the to-do: "Why this date?")."""
    facts: dict[str, Any] = {
        "index": index,
        "spec": spec_structure(spec),
        "source": source,
        "due_date": receipt.due_date if receipt else None,
        "send_by": receipt.send_by if receipt else None,
        "safe_date": receipt.safe_date if receipt else None,
        "rule_ids": list(receipt.rule_ids) if receipt else [],
        "confidence": receipt.confidence if receipt else None,
        "warnings": len(receipt.warnings) if receipt else 0,
        "holiday_calendar": receipt.holiday_calendar if receipt else None,
    }
    if item_id is not None:
        facts["item_id"] = item_id
    if slot_key is not None:
        facts["slot_key"] = slot_key
    return facts


def law_deadline(rule_id: str, receipt: ComputationReceipt, *, filed: bool, reason: str) -> dict[str, Any]:
    """A deadline the law adds to a high-stakes letter: its rule, the date computed, and whether it
    was filed (``reason``: ``filed``; ``covered`` when the letter's own to-do already carries it
    with the same or an earlier date; ``deleted_by_you`` when a recompute finds the to-do deleted)."""
    return {
        "rule_id": rule_id,
        "due_date": receipt.due_date,
        "send_by": receipt.send_by,
        "rule_ids": list(receipt.rule_ids),
        "confidence": receipt.confidence,
        "filed": filed,
        "reason": reason,
    }


def party_match(
    decision: PartyDecision,
    *,
    party_id: str | None,
    score: float | None = None,
    reference_kind: str | None = None,
    candidates: Sequence[tuple[str, float]] = (),
) -> dict[str, Any]:
    """How the sender was matched: by an identifier (``reference_kind`` says which kind, never the
    number), by its exact name or an alias, by a similar name (``score``, 0–100), or as a new party;
    ``candidates`` are the closest other parties with their scores (at most :data:`MAX_CANDIDATES`)."""
    return {
        "decision": decision,
        "party_id": party_id,
        "score": score,
        "reference_kind": reference_kind,
        "candidates": [{"party_id": pid, "score": round(s, 1)} for pid, s in candidates[:MAX_CANDIDATES]],
    }


ThreadDecision = Literal["reference", "email", "same_thread", "new"]
ContractDecision = Literal["created", "refreshed", "filled", "change_recorded", "no_match", "none"]


def thread(decision: ThreadDecision, case_id: str, reference_kind: str | None) -> dict[str, Any]:
    """Which thread the letter joined: one found by a reference of ``reference_kind`` (an
    Aktenzeichen, a Rechnungsnummer …), the thread of the e-mail it came with (or of that e-mail's
    attachments), the thread this sender and reference (or title) already has, or a new one."""
    return {"decision": decision, "case_id": case_id, "reference_kind": reference_kind}


def contract(
    decision: ContractDecision, contract_id: str | None, change: str | None = None
) -> dict[str, Any]:
    """What the letter did to a contract: created it, refreshed the fields the person has not edited
    (the contract's own letter), filled empty fields (a contract known from elsewhere), recorded a
    change or confirmation for the triggers (``change`` is its type; nothing is applied), found no
    contract to record it on, or had nothing to record (a change of a kind that is not recorded)."""
    return {"decision": decision, "contract_id": contract_id, "change": change}


def payment_check(
    *, finding: str | None, iban_valid: bool | None, iban_known: bool, iban_added: bool
) -> dict[str, Any]:
    """The scam check of a payment demand: the finding's kind (``None``: nothing to double-check),
    whether the IBAN's checksum holds, was known for the sender, and was added to its known IBANs."""
    return {"finding": finding, "iban_valid": iban_valid, "iban_known": iban_known, "iban_added": iban_added}


def reminder(invoices: int) -> dict[str, Any]:
    """A payment reminder: how many open invoices of its thread it is about (each gets a warning;
    nothing is closed)."""
    return {"invoices": invoices}


def planned(action: PlanAction, item: Item, *, index: int, moved: bool = False) -> dict[str, Any]:
    """What planning did with one to-do of the reading: its id and slot, the action and whether it
    was carried over from an earlier reading's slot (the person acted on it, or it repeats)."""
    return {
        "index": index,
        "item_id": item.id,
        "slot_key": item.slot_key,
        "action": action,
        "moved": moved,
        "due_date": item.due_date,
        "status": item.status,
    }


def outcome(
    *, result: str, text_mode: str | None, pages: int, items: int, needs_check: int, warnings: int
) -> dict[str, Any]:
    """How the reading ended: the letter's status and what was filed."""
    return {
        "result": result,
        "text_mode": text_mode,
        "pages": pages,
        "items": items,
        "needs_check": needs_check,
        "warnings": warnings,
    }
