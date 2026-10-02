"""Tests that pin what the completeness re-ask's first tests left loose (review: test strength).

Every letter is synthetic and written in ``tests/test_reading_reask.py`` or here; nothing calls a model.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from fixtures_llm import TODAY
from ordnung import clock
from ordnung.ingest.extract import (
    MISSING_PARTS,
    extract_document,
    judge_completion,
    missing_parts,
    read_document,
)
from ordnung.ingest.gaps import check_item
from ordnung.llm import prompts
from ordnung.llm.base import ClaudeBadOutput, ClaudeTimeout, LLMRequest
from ordnung.llm.fake import FakeBackend
from ordnung.llm.runtime import LLMService
from ordnung.llm.schemas import completion_schema
from ordnung.models import Page
from test_reading_reask import (
    BLANK,
    COMPLETE,
    DECISION,
    HALF,
    OBJECTION,
    answering,
    data_for,
    pages_of,
    read,
    reading,
)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.conditions import CallLog, MeteredBackend, prepare_document, run_ordnung  # noqa: E402
from evals.records import load_manifest  # noqa: E402

MANIFEST = ROOT / "evals" / "dataset" / "manifest.json"


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


class Sink:
    """A usage log and response cache in memory (the subset of the store ``LLMService`` uses)."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.cache: dict[str, dict[str, Any]] = {}

    def cache_get(self, key: str) -> dict[str, Any] | None:
        return self.cache.get(key)

    def cache_put(
        self,
        key: str,
        purpose: str,
        model: str,
        response: dict[str, Any],
        doc_sha: str | None = None,
        *,
        doc_ids: Any = (),
    ) -> bool:
        self.cache[key] = response
        return True

    def log_llm_call(
        self,
        purpose: str,
        model: str,
        backend: str,
        usage: Any,
        ok: bool = True,
        error: str | None = None,
        cache_hit: bool = False,
        *args: Any,
        **kwargs: Any,
    ) -> int:
        self.rows.append(
            {
                "prompt": kwargs.get("prompt_name"),
                "outcome": kwargs.get("outcome"),
                "repair_of": kwargs.get("repair_of"),
                "cache_hit": cache_hit,
            }
        )
        return len(self.rows)


# --------------------------------------------------------------------------------------------------
# The request the pipeline actually sends (not only completion_request called by hand)
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("payload", "gap"), [(BLANK, "empty"), (HALF, "remedy_left_out")])
async def test_the_re_ask_sent_is_keyed_and_worded_for_its_gap(payload: dict[str, Any], gap: str) -> None:
    backend = answering(payload, payload)
    await read(backend)
    first, again = backend.calls
    assert json.loads(again.cache_key or "")["complete"] == [gap]
    _, note = prompts.render("reading_gaps", missing=missing_parts([gap]))
    assert again.prompt == f"{first.prompt}\n\n{note}"  # the assembly is model-facing too, and not locked
    for part in MISSING_PARTS[gap]:
        assert f"- {part}" in again.prompt
    assert again.schema_ == completion_schema()


# --------------------------------------------------------------------------------------------------
# The usage log and the cache
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("second", "outcome"), [(COMPLETE, "repaired"), ({"kind": 42}, "failed")])
async def test_the_re_ask_row_says_whether_its_answer_could_be_read(
    second: dict[str, Any], outcome: str
) -> None:
    sink = Sink()
    await extract_document(LLMService(answering(BLANK, second), sink), data_for(), model="m")
    assert [(row["prompt"], row["outcome"], row["repair_of"]) for row in sink.rows] == [
        ("extract", "ok", None),
        ("reading_gaps", outcome, 1),
    ]


async def test_reprocess_asks_the_re_ask_again_too() -> None:
    sink = Sink()
    backend = answering(BLANK, COMPLETE, BLANK, COMPLETE)
    llm = LLMService(backend, sink)
    assert await extract_document(llm, data_for(), model="m") == reading(COMPLETE)
    assert await extract_document(llm, data_for(), model="m") == reading(COMPLETE)
    assert len(backend.calls) == 2  # both answers from the cache
    assert await extract_document(llm, data_for(), model="m", use_cache=False) == reading(COMPLETE)
    assert [request.prompt_name for request in backend.calls[2:]] == ["extract", "reading_gaps"]


# --------------------------------------------------------------------------------------------------
# Every kind of quote counts, wherever it is found
# --------------------------------------------------------------------------------------------------

#: A sentence this file writes and no letter holds.
OFF_PAGE = "Die Frist für einen Widerspruch beträgt ausnahmsweise sechs Monate."


def test_a_to_do_quote_not_on_the_page_counts_against_the_re_ask() -> None:
    pages = pages_of(DECISION)
    # a dated to-do it adds must be found on the letter at all (ADR 0016's rule 6) ...
    dated = {**COMPLETE, "items": [{**OBJECTION, "quote": OFF_PAGE}]}
    assert judge_completion("doc_x", reading(BLANK), reading(dated), pages, gap="empty") == "ungrounded"
    # ... and an undated one still counts in the share of quotes found
    undated = {
        **COMPLETE,
        "items": [OBJECTION, {"kind": "task", "title": "T", "date": {"type": "none"}, "quote": OFF_PAGE}],
    }
    assert judge_completion("doc_x", reading(BLANK), reading(undated), pages, gap="empty") == "quotes"


def test_a_contract_quote_not_on_the_page_counts_against_the_re_ask() -> None:
    second = {**COMPLETE, "contract": {"name": "Fee", "category": "other", "quotes": [OFF_PAGE]}}
    pages = pages_of(DECISION)
    assert judge_completion("doc_x", reading(BLANK), reading(second), pages, gap="empty") == "quotes"


def test_quotes_found_in_a_photo_s_transcript_count_as_found() -> None:
    pages = [page.model_copy(update={"text_source": "transcript"}) for page in pages_of(DECISION)]
    assert judge_completion("doc_x", reading(BLANK), reading(COMPLETE), pages, gap="empty") is None


def two_pages() -> list[Page]:
    """The decision with its instructions on how to object on a second page."""
    [lines] = DECISION.pages
    cut = lines.index("Rechtsbehelfsbelehrung")
    page_one, page_two = pages_of(DECISION)[0], pages_of(DECISION)[0]
    return [
        page_one.model_copy(update={"text": "\n".join(lines[:cut])}),
        page_two.model_copy(update={"page": 2, "text": "\n".join(lines[cut:])}),
    ]


@pytest.mark.parametrize("first", [HALF, BLANK])  # the trigger sees page 2; the quotes are looked for there
async def test_a_notice_on_a_later_page_triggers_and_grounds_the_re_ask(first: dict[str, Any]) -> None:
    data = replace(data_for(), pages=two_pages())
    backend = answering(first, COMPLETE)
    result = await read_document(LLMService(backend), data, model="m")
    assert [request.prompt_name for request in backend.calls] == ["extract", "reading_gaps"]
    assert result.completion is not None and result.completion.accepted


# --------------------------------------------------------------------------------------------------
# The benchmark keeps only a replay miss; every other error is the run's, as live
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "expected"),
    [(ClaudeTimeout("timed out"), None), (ClaudeBadOutput("no output"), "reading_reask:rejected")],
)
async def test_the_benchmark_keeps_the_first_reading_only_for_a_replay_miss(
    tmp_path: Path, error: Exception, expected: str | None
) -> None:
    entry = {e.id: e for e in load_manifest(MANIFEST)}["dev-municipal_decision-A1"]
    document = prepare_document(entry, MANIFEST.parent, tmp_path)

    def respond(request: LLMRequest) -> Any:
        if request.prompt_name == "reading_gaps":
            raise error
        return dict(BLANK)

    llm = LLMService(MeteredBackend(FakeBackend(respond), CallLog(), timeout_s=60))
    if expected is None:
        with pytest.raises(type(error)):
            await run_ordnung(entry, document, llm, model="claude-sonnet-5")
        return
    prediction = await run_ordnung(entry, document, llm, model="claude-sonnet-5")
    assert expected in prediction.signals and "reading_reask_missing" not in prediction.signals


# --------------------------------------------------------------------------------------------------
# Never worse than without the re-ask (fail on d6caeae; pass with the proposed acceptance fix)
# --------------------------------------------------------------------------------------------------

FEE_DUE = "Die Gebühr von 85,00 EUR ist bis zum 15.10.2026 zu zahlen."
PAYMENT = {
    "kind": "payment",
    "title": "Pay the fee",
    "amount": 85.0,
    "currency": "EUR",
    "direction": "out",
    "date": {"type": "fixed", "date": "2026-10-15", "nature": "payment", "text": "bis zum 15.10.2026"},
    "quote": FEE_DUE,
}
DUE_DECISION_PAGES = [
    pages_of(DECISION)[0].model_copy(
        update={
            "text": pages_of(DECISION)[0].text.replace(
                "Sehr geehrte Frau Probe,", f"Sehr geehrte Frau Probe,\n{FEE_DUE}"
            )
        }
    )
]


@pytest.mark.parametrize(
    "second_items",
    [
        [OBJECTION],  # the payment left out
        [
            OBJECTION,
            {**PAYMENT, "date": {**PAYMENT["date"], "date": "2026-11-15"}},
        ],  # the payment a month later
    ],
)
def test_an_answer_that_drops_or_postpones_a_dated_to_do_is_not_used(
    second_items: list[dict[str, Any]],
) -> None:
    first = {**HALF, "remedy": None, "items": [PAYMENT]}
    second = {**first, "items": second_items}
    verdict = judge_completion(
        "doc_x", reading(first), reading(second), DUE_DECISION_PAGES, gap="remedy_left_out"
    )
    assert verdict is not None


SW_NOTICE = (
    "Gegen diese Entscheidung können Sie innerhalb eines Monats nach Zugang schriftlich Widerspruch einlegen."
)
SW_PAGES = [
    pages_of(DECISION)[0].model_copy(
        update={
            "text": "\n".join(
                (
                    "Studierendenwerk Musterstadt · Amt für Ausbildungsförderung · Ringstraße 4 · 54321 Musterstadt",
                    "Datum: 15.09.2026",
                    "Ihr Antrag auf Förderung",
                    "Sehr geehrte Frau Probe,",
                    "Ihrem Antrag können wir leider nicht entsprechen.",
                    "Rechtsbehelfsbelehrung",
                    SW_NOTICE,
                )
            )
        }
    )
]


@pytest.mark.parametrize(
    ("first", "gap"),
    [
        (BLANK, "empty"),
        (
            {
                **BLANK,
                "sender": {"name": "Studierendenwerk Musterstadt", "kind": "authority"},
                "document_date": "2026-09-15",
            },
            "remedy_left_out",
        ),
    ],
)
def test_a_sender_read_as_a_firm_does_not_lift_the_check_s_deadline(first: dict[str, Any], gap: str) -> None:
    """The check files a deadline for the first reading; the second only reads the sender differently and dates
    nothing — using it would leave the letter with no deadline at all."""
    second = {
        **BLANK,
        "sender": {"name": "Studierendenwerk Musterstadt", "kind": "company"},
        "document_date": "2026-09-15",
        "items": [],
    }
    found = check_item(reading(first), SW_PAGES)
    assert found is not None and found.gap == gap and found.item.kind == "deadline"
    assert judge_completion("doc_x", reading(first), reading(second), SW_PAGES, gap=gap) is not None


def test_a_re_read_without_a_to_do_does_not_lift_the_read_it_yourself_to_do() -> None:
    """No notice code can read: the check asks the person to read the letter; a second reading that gives a sender
    and a date but no to-do must not take that away (the letter's own period stays unread by anyone)."""
    pages = [
        pages_of(DECISION)[0].model_copy(
            update={
                "text": "\n".join(
                    (
                        "Stadt Musterhausen · Ordnungsamt · Marktplatz 3 · 54321 Musterhausen",
                        "Datum: 15.09.2026",
                        "Sehr geehrte Frau Probe,",
                        "bitte melden Sie sich binnen zwei Wochen bei uns.",
                    )
                )
            }
        )
    ]
    found = check_item(reading(BLANK), pages)
    assert found is not None and found.gap == "empty" and found.item.kind == "task"
    second = {
        **BLANK,
        "sender": {"name": "Stadt Musterhausen", "kind": "authority"},
        "document_date": "2026-09-15",
    }
    assert judge_completion("doc_x", reading(BLANK), reading(second), pages, gap="empty") is not None
