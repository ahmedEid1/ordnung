"""The factual claims of README.md and docs/, checked against the code.

Written by a documentation audit: each test states a documented claim as an assertion, so a change
that makes the docs untrue fails here.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tomllib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from helpers_secretary import TODAY, seed_ledger
from ordnung import clock
from ordnung.app_context import AppContext, build_context
from ordnung.db.store import Store
from ordnung.drafts.compose import compose
from ordnung.ingest.extract import ExtractionInput, extraction_request
from ordnung.ingest.plan import VerifiedItem
from ordnung.llm.base import LLMRequest
from ordnung.llm.fake import FakeBackend
from ordnung.llm.runtime import LLMService
from ordnung.models import DateSpec, Evidence, ExtractedItem, Identifier, Page, Party, Profile
from ordnung.tick import DailyTick

ROOT = Path(__file__).resolve().parents[1]
NOW = "2026-09-25T10:00:00Z"


# --------------------------------------------------------------------------------------------------
# README.md
# --------------------------------------------------------------------------------------------------


def test_readme_has_no_unrendered_placeholders() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert re.findall(r"\{\{[A-Z_]+\}\}", text) == []


def test_a_git_install_contains_the_built_web_app() -> None:
    tracked = subprocess.run(
        ["git", "ls-files", "src/ordnung/web/dist/index.html"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert tracked == "src/ordnung/web/dist/index.html"


def _photo_read_item() -> VerifiedItem:
    """A photo-read deadline whose quote is found in the AI transcript and states its values."""
    spec = DateSpec(type="fixed", date="2026-10-02", nature="payment", text="bis zum 02.10.2026")
    item = ExtractedItem(kind="payment", title="Pay the fine", date=spec, quote="Zahlbar bis zum 02.10.2026")
    evidence = Evidence(doc_id="doc_x", page=1, quote=item.quote, grounding="model_read", score=100.0)
    return VerifiedItem(item=item, evidence=evidence, reasons=(), slot_key="payment:1")


def test_a_date_read_from_a_photo_is_labelled_not_flagged() -> None:
    """README: a date whose sentence is found (in the text layer or the photo's transcript) and states
    its numbers is not marked Please check; a photo-read one is labelled as read from the photo."""
    item = _photo_read_item()
    assert not item.needs_check and item.evidence is not None and item.evidence.grounding == "model_read"


def _wrong_llm_only_items(results: dict[str, Any]) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    wrong = []
    for entry in results["entries"]:
        condition = entry["conditions"]["llm_only"]
        for scored in condition["score"]["items"]:
            if scored.get("required") and scored["outcome"] == "wrong":
                predicted = condition["prediction"]["items"][scored["pred_index"]]
                wrong.append((entry["id"], scored, predicted))
    return wrong


_THIRD_DAY = re.compile(r"third day|3rd day|3 days after|\+ ?3 days", re.IGNORECASE)


def test_readme_llm_only_error_counts_that_hold() -> None:
    """README.md:193-196: 10 of 56 wrong, all four late answers moved a delivery day off a weekend."""
    results = json.loads((ROOT / "evals/results/2026-09-25-sonnet-test.json").read_text(encoding="utf-8"))
    wrong = _wrong_llm_only_items(results)
    assert len(wrong) == 10
    late = [(entry, predicted) for entry, scored, predicted in wrong if scored["direction"] == "late"]
    assert len(late) == 4
    assert all(re.search(r"shift|moves|next working day|Werktag", p["explanation"]) for _, p in late)


def test_readme_eight_llm_only_errors_used_the_three_day_rule() -> None:
    """README: 'Eight of those used the 3-day delivery rule' (from the stored explanations)."""
    assert "Eight of those used the 3-day delivery rule" in (ROOT / "README.md").read_text(encoding="utf-8")
    results = json.loads((ROOT / "evals/results/2026-09-25-sonnet-test.json").read_text(encoding="utf-8"))
    three_day = [
        entry
        for entry, _, predicted in _wrong_llm_only_items(results)
        if _THIRD_DAY.search(predicted["explanation"])
    ]
    assert len(three_day) == 8, three_day


def test_rules_branch_coverage_is_a_ci_gate() -> None:
    """README.md:232 lists '100 % branch coverage of rules/' as a quality gate: CI must measure
    branches and fail under 100 % (it used to do neither)."""
    config = "\n".join(
        (ROOT / name).read_text(encoding="utf-8")
        for name in (".github/workflows/ci.yml", "Makefile", "pyproject.toml")
    )
    assert re.search(r"cov-branch|branch\s*=\s*true", config) and re.search(r"fail[-_]under", config)


def test_mypy_is_strict_on_the_rules_engine() -> None:
    """README.md:232 says 'mypy (strict on the core)': pyproject.toml gives the rules engine the
    per-module checks of ``mypy --strict``."""
    mypy = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["mypy"]
    strict = [o for o in mypy.get("overrides", []) if "ordnung.rules.*" in o["module"]]
    assert strict and all(
        strict[0].get(flag) is True
        for flag in ("disallow_untyped_defs", "disallow_any_generics", "warn_return_any", "strict_equality")
    )
    assert strict[0].get("implicit_reexport") is False


def test_demo_check_runs_in_ci() -> None:
    """README.md:232 and docs/privacy.md:87: CI runs ``ordnung demo --check`` (added in abe86a7)."""
    assert "ordnung demo --check" in (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")


# --------------------------------------------------------------------------------------------------
# docs/privacy.md — what each feature sends
# --------------------------------------------------------------------------------------------------


def _page(text: str) -> Page:
    return Page.model_validate(
        {
            "doc_id": "doc_x",
            "page": 1,
            "width": 10,
            "height": 10,
            "image_path": "p.jpg",
            "text": text,
            "text_source": "text",
        }
    )


def _party(name: str, **fields: Any) -> Party:
    return Party.model_validate(
        {
            "id": f"pty_{hashlib.sha1(name.encode()).hexdigest()[:12]}",
            "name": name,
            "created_at": NOW,
            "updated_at": NOW,
            **fields,
        }
    )


def test_reading_a_letter_sends_only_the_names_of_known_organisations() -> None:
    """docs/privacy.md: reading a letter sends the names and kinds of known organisations, no numbers
    read from other letters (they used to include passport and staff numbers)."""
    passport_office = _party(
        "Ministry of Interior", kind="authority", identifiers=[{"label": "Passport No.", "value": "X1234567"}]
    )
    employer = _party(
        "Muster Tech GmbH", kind="employer", identifiers=[{"label": "Personalnummer", "value": "10482"}]
    )
    data = ExtractionInput(
        doc_id="doc_x",
        sha256="f" * 64,
        pages=[_page("Rechnung Nr. 1 vom 01.09.2026 über 12,00 EUR.")],
        today="2026-09-25",
        language="en",
        region="NW",
        country="DE",
        person_name="Sam Rivera",
        known_parties=[passport_office, employer],
    )
    request = extraction_request(data, model="sonnet")
    sent = request.prompt + request.system
    assert "Ministry of Interior" in sent and "Muster Tech GmbH" in sent  # the documented part
    assert "X1234567" not in sent and "10482" not in sent


@pytest.fixture
def draft_ctx(data_dir: Path) -> Iterator[tuple[AppContext, FakeBackend]]:
    answer = {
        "subject": "",
        "body": "Vielen Dank.",
        "body_translation": "Thank you.",
        "enclosures": [],
        "notes_for_user": [],
    }
    backend = FakeBackend({"draft": answer})
    clock.set_today(TODAY)
    context = build_context(data_dir, backend_obj=backend)
    yield context, backend
    context.close()
    clock.set_today(None)


async def test_drafting_a_letter_never_sends_your_address(draft_ctx: tuple[AppContext, FakeBackend]) -> None:
    """docs/privacy.md: your address is never sent; drafting sends the recipient's name (first line)."""
    ctx, backend = draft_ctx
    ctx.store.save_profile(
        Profile(name="Sam Rivera", address="Beispielweg 5\n12345 Musterstadt", language="en", region="NW")
    )
    telecom = ctx.store.add_party(
        name="FunkNetz Mobile",
        kind="telecom",
        address="Funkallee 1\n10115 Berlin",
        identifiers=[Identifier(label="Kundennummer", value="4711-0815")],
    ).id
    contract = ctx.store.add_contract(
        name="FunkNetz Mobil",
        category="mobile",
        party_id=telecom,
        customer_number="4711-0815",
        concluded_date="2025-01-10",
        start_date="2025-01-15",
        initial_term_months=24,
        notice_value=1,
        notice_unit="months",
    ).id
    draft = await compose(ctx, "cancellation", contract_id=contract, instructions="Bitte bestätigen")
    assert "Beispielweg 5" in draft.sender_block  # the letter itself has the address
    (request,) = [call for call in backend.calls if isinstance(call, LLMRequest) and call.purpose == "draft"]
    sent = request.prompt + request.system
    assert "Beispielweg 5" not in sent and "12345 Musterstadt" not in sent
    assert "10115 Berlin" not in sent


async def test_weekly_review_can_be_switched_off(store: Store) -> None:
    """docs/privacy.md: the weekly Ideas review can be switched off in Settings."""
    ids = seed_ledger(store)
    backend = FakeBackend(
        {
            "brief": {"text": "Good morning."},
            "review": {
                "suggestions": [
                    {
                        "kind": "saving",
                        "title": "Check your ticket",
                        "body": "You pay for a ticket.",
                        "rationale": "An active contract.",
                        "refs": [{"type": "contract", "id": ids["ticket"]}],
                    }
                ]
            },
        }
    )

    class Ctx:
        def __init__(self) -> None:
            self.store = store
            self.llm = LLMService(backend, sink=store)
            self.bus = None

    clock.set_today(TODAY)
    try:
        settings = store.get_settings()
        every_switch_off = {
            name: False
            for name, field in type(settings).model_fields.items()
            if field.annotation is bool and name != "demo"
        }
        store.save_settings(settings.model_copy(update=every_switch_off))
        tick = DailyTick(Ctx())  # type: ignore[arg-type]
        result = await tick.check()
        await tick.stop()
    finally:
        clock.set_today(None)
    assert not result.review_started
