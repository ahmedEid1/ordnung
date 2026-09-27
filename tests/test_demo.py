"""Demo mode: building the demo from a (mini) sample life with recorded answers, the strict replay,
the recorder's privacy guard, snapshots, ``check_demo``, the New-mail tray and the tour."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from fixtures_llm import (
    APPOINTMENT_LETTER,
    GYM_CONTRACT_LETTER,
    PRICE_INCREASE_LETTER,
    TAX_LETTER,
    Router,
    record_events,
)
from helpers_docs import photo
from ordnung import clock
from ordnung.app_context import AppContext, build_context
from ordnung.config import Paths
from ordnung.db.store import Store
from ordnung.demo import DemoError, load_manifest, tour
from ordnung.demo.loader import (
    MARKER_NAME,
    build_demo,
    canonical_dump,
    check_demo,
    demo_version,
    dump_differences,
    is_demo_dir,
    prepare_demo,
    recording_backend,
    snapshot_version,
    tray_states,
)
from ordnung.ids import doc_id_for_sha
from ordnung.llm.base import LLMError, LLMRequest, ReplayMiss, StreamEvent
from ordnung.llm.fake import FakeBackend
from ordnung.llm.replay import ReplayBackend
from ordnung.models import TourState
from ordnung.secretary.brief import get_brief

TODAY = "2026-09-25"
QUESTIONS = ["What is due soon?", "When does my gym contract end?"]
BRIEF_TEXT = "Good morning Sam, a few letters need a look this week."


# --------------------------------------------------------------------------------------------------
# a mini sample life: two letters already read, two in the tray (one of them two photos)
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SampleLife:
    samples: Path
    fixtures: Path
    snapshot: Path
    ids: dict[str, str]
    recorded: Path


def _entry(order: int, slug: str, files: list[tuple[str, bytes]], **fields: Any) -> dict[str, Any]:
    hashes = [hashlib.sha256(data).hexdigest() for _, data in files]
    names = [name for name, _ in files]
    entry: dict[str, Any] = {"order": order, "slug": slug, "title": slug.title(), "subject": f"About {slug}"}
    if len(files) > 1:
        entry |= {"files": names, "sha256": hashes, "combine": True}
    else:
        entry |= {"file": names[0], "sha256": hashes[0]}
    return entry | {"pages": len(files), "received_date": "2026-09-20", **fields}


def write_sample_life(root: Path) -> Path:
    """A tiny manifest + files in ``root`` (same layout as the packaged sample life)."""
    root.mkdir(parents=True, exist_ok=True)
    pdf = {"mime": "application/pdf", "photo": False}
    files = {
        "tax": [("01_tax.pdf", TAX_LETTER.pdf())],
        "gym": [("02_gym.pdf", GYM_CONTRACT_LETTER.pdf())],
        "price": [("03_price.pdf", PRICE_INCREASE_LETTER.pdf())],
        "appointment": [
            ("04_appointment_p1.jpg", photo("jpeg")),
            ("04_appointment_p2.jpg", photo("jpeg", size=(240, 120))),
        ],
    }
    for group in files.values():
        for name, data in group:
            (root / name).write_bytes(data)
    documents = [
        _entry(
            1,
            "tax",
            files["tax"],
            tray=False,
            truth={"kind": "tax_assessment", "sender_name": "Finanzamt"},
            **pdf,
        ),
        _entry(
            2,
            "gym",
            files["gym"],
            tray=False,
            truth={"kind": "contract", "sender_name": "Muster Fitness"},
            **pdf,
        ),
        _entry(
            3,
            "price",
            files["price"],
            tray=True,
            truth={"kind": "price_increase", "sender_name": "Muster Fitness"},
            **pdf,
        ),
        _entry(
            4,
            "appointment",
            files["appointment"],
            tray=True,
            mime="image/jpeg",
            photo=True,
            truth={"kind": "appointment", "sender_name": "Bürgeramt"},
        ),
    ]
    manifest = {
        "schema_version": 1,
        "persona": {"name": "Sam Rivera", "address": "Beispielweg 5, 12345 Musterstadt", "region": "NW"},
        "simulated_today": TODAY,
        "documents": documents,
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return root


def model_answers(ids: dict[str, str]) -> FakeBackend:
    """What "Claude" answers while recording the mini sample life."""
    router = Router(transcript=APPOINTMENT_LETTER.transcript())

    def answer(req: LLMRequest) -> dict[str, Any] | str:
        if req.purpose == "brief":
            return {"text": BRIEF_TEXT}
        if req.purpose == "review":
            return {"suggestions": []}
        if req.purpose == "ask":
            return f"Your gym membership is on file [doc:{ids['gym']}]."
        return router(req)

    return FakeBackend(answer)


def record(life_root: Path, target: Path, **options: Any) -> Any:
    samples = life_root / "samples"
    ids = load_manifest(samples).document_ids(samples)
    return build_demo(
        target,
        backend="record",
        samples=samples,
        fixtures=life_root / "fixtures",
        live=model_answers(ids),
        questions=QUESTIONS,
        snapshot=life_root / "snapshot",
        **options,
    )


@pytest.fixture(autouse=True)
def unpinned_clock() -> Iterator[None]:
    yield
    clock.set_today(None)


@pytest.fixture(scope="module")
def life(tmp_path_factory: pytest.TempPathFactory) -> SampleLife:
    """The mini sample life, recorded once (fixtures + snapshot) for the whole module."""
    root = tmp_path_factory.mktemp("life")
    samples = write_sample_life(root / "samples")
    record(root, root / "recorded", rebuild=True)
    clock.set_today(None)
    return SampleLife(
        samples=samples,
        fixtures=root / "fixtures",
        snapshot=root / "snapshot",
        ids=load_manifest(samples).document_ids(samples),
        recorded=root / "recorded",
    )


def open_demo(life: SampleLife, folder: Path) -> AppContext:
    prepared = prepare_demo(folder, samples=life.samples, fixtures=life.fixtures, snapshot=life.snapshot)
    return build_context(prepared.data_dir, backend_obj=ReplayBackend(life.fixtures))


# --------------------------------------------------------------------------------------------------
# manifest
# --------------------------------------------------------------------------------------------------


def test_document_ids_match_what_the_pipeline_stores(life: SampleLife) -> None:
    manifest = load_manifest(life.samples)
    tax = manifest.document("tax")
    assert tax is not None
    assert life.ids["tax"] == doc_id_for_sha(tax.hashes[0])
    photos = manifest.document("appointment")
    assert photos is not None and len(photos.filenames) == 2
    assert life.ids["appointment"] not in {doc_id_for_sha(sha) for sha in photos.hashes}
    assert [doc.slug for doc in manifest.library] == ["tax", "gym"]
    assert [doc.slug for doc in manifest.tray] == ["price", "appointment"]
    assert [len(state) for state in tray_states(manifest)] == [0, 1, 1, 2]


def test_a_changed_sample_file_is_refused(tmp_path: Path) -> None:
    samples = write_sample_life(tmp_path / "samples")
    (samples / "01_tax.pdf").write_bytes(b"%PDF-1.4 tampered")
    manifest = load_manifest(samples)
    with pytest.raises(DemoError, match="does not match the manifest"):
        manifest.document_ids(samples)


def test_a_missing_manifest_is_a_demo_error(tmp_path: Path) -> None:
    with pytest.raises(DemoError, match="missing"):
        load_manifest(tmp_path)


def test_the_packaged_sample_life_loads() -> None:
    manifest = load_manifest()
    assert manifest.simulated_today == "2026-09-28"
    assert len(manifest.tray) == 3 and len(manifest.library) == len(manifest.documents) - 3
    assert len(tray_states(manifest)) == 8
    assert len(tour.suggested_questions()) >= 3


# --------------------------------------------------------------------------------------------------
# building
# --------------------------------------------------------------------------------------------------


def test_recording_writes_fixtures_for_every_purpose(life: SampleLife) -> None:
    purposes = {path.parent.name for path in life.fixtures.rglob("*.json")}
    assert purposes == {"extract", "transcribe", "review", "brief", "ask"}
    asks = list((life.fixtures / "ask").glob("*.json"))
    assert len(asks) == len(QUESTIONS) * 4  # every question in every tray state
    for path in life.fixtures.rglob("*.json"):
        request = json.loads(path.read_text(encoding="utf-8"))["request"]
        assert set(request["doc_ids"]) <= set(life.ids.values())


def test_replay_builds_the_demo_from_the_recordings(life: SampleLife, tmp_path: Path) -> None:
    built = build_demo(tmp_path / "demo", samples=life.samples, fixtures=life.fixtures)
    assert built.documents == 2 and built.asks == 0 and built.snapshot is None
    assert is_demo_dir(built.data_dir)
    assert built.version == demo_version(samples=life.samples, fixtures=life.fixtures)
    store = Store.open(Paths(built.data_dir))
    try:
        settings = store.get_settings()
        assert settings.demo and settings.simulated_today == TODAY
        assert store.get_meta("simulated_today") == TODAY
        assert store.get_meta("last_tick_date") == TODAY
        assert store.get_profile().name == "Sam Rivera" and store.get_profile().onboarded
        documents = {doc.id: doc for doc in store.list_documents()}
        assert set(documents) == {life.ids["tax"], life.ids["gym"]}
        assert all(doc.status in ("processed", "needs_review") for doc in documents.values())
        assert all(doc.received_date == "2026-09-20" for doc in documents.values())
        brief = get_brief(store, date.fromisoformat(TODAY))  # the demo's day, not the real one
        assert brief is not None and brief.source == "llm" and brief.text == BRIEF_TEXT
        assert [item.opened for item in tour.tray_items(store, load_manifest(life.samples))] == [False, False]
        assert tour.get_tour(store).active
    finally:
        store.close()


def test_a_replay_miss_fails_the_build(life: SampleLife, tmp_path: Path) -> None:
    fixtures = tmp_path / "fixtures"
    shutil.copytree(life.fixtures, fixtures)
    for path in (fixtures / "extract").glob("*.json"):
        path.unlink()
    with pytest.raises(DemoError, match="replay miss: extract"):
        build_demo(tmp_path / "demo", samples=life.samples, fixtures=fixtures)


def test_the_build_never_overwrites_real_data(life: SampleLife, tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    (real / "ordnung.db").write_bytes(b"precious")
    with pytest.raises(DemoError, match="refusing to overwrite"):
        build_demo(real, samples=life.samples, fixtures=life.fixtures)
    assert (real / "ordnung.db").read_bytes() == b"precious"


def test_recording_prunes_fixtures_it_no_longer_uses(tmp_path: Path) -> None:
    samples = write_sample_life(tmp_path / "samples")
    stale = tmp_path / "fixtures" / "extract" / "000000000000000000000000.json"
    stale.parent.mkdir(parents=True)
    stale.write_text("{}", encoding="utf-8")
    ids = load_manifest(samples).document_ids(samples)
    built = build_demo(
        tmp_path / "demo",
        backend="record",
        samples=samples,
        fixtures=tmp_path / "fixtures",
        live=model_answers(ids),
        questions=QUESTIONS[:1],
    )
    assert built.asks == 4 and built.pruned == 1
    assert not stale.exists()
    assert list((tmp_path / "fixtures" / "extract").glob("*.json"))


# --------------------------------------------------------------------------------------------------
# privacy: the recorder
# --------------------------------------------------------------------------------------------------


def _request(doc_ids: list[str]) -> LLMRequest:
    return LLMRequest(purpose="extract", prompt="p", system="s", doc_ids=doc_ids, cache_key="k")


async def test_the_recorder_refuses_documents_outside_the_sample_life(
    life: SampleLife, tmp_path: Path
) -> None:
    folder = tmp_path / "demo"
    folder.mkdir()
    (folder / MARKER_NAME).write_text(json.dumps({"version": ""}), encoding="utf-8")
    live = FakeBackend({"extract": {"kind": "other"}})
    backend = recording_backend(folder, tmp_path / "fixtures", set(life.ids.values()), live)
    with pytest.raises(LLMError, match="non-sample"):
        await backend.complete(_request(["doc_personal0000"]))
    assert live.calls == []
    assert not (tmp_path / "fixtures").exists()
    recorded = await backend.complete(_request([life.ids["tax"]]))
    assert recorded.data == {"kind": "other"}
    assert list((tmp_path / "fixtures" / "extract").glob("*.json"))


def test_recording_is_only_allowed_into_a_demo_folder(tmp_path: Path) -> None:
    with pytest.raises(DemoError, match="only allowed into a demo folder"):
        recording_backend(tmp_path, tmp_path / "fixtures", set(), FakeBackend())


# --------------------------------------------------------------------------------------------------
# snapshot & opening
# --------------------------------------------------------------------------------------------------


def test_prepare_uses_the_snapshot_then_keeps_the_folder(life: SampleLife, tmp_path: Path) -> None:
    assert snapshot_version(life.snapshot) == demo_version(samples=life.samples, fixtures=life.fixtures)
    assert (life.snapshot / "ordnung.db").is_file() and (life.snapshot / "derived").is_dir()
    assert not (life.snapshot / "ordnung.db-wal").exists()
    folder = tmp_path / "demo"
    options: dict[str, Any] = {"samples": life.samples, "fixtures": life.fixtures, "snapshot": life.snapshot}
    assert prepare_demo(folder, **options).source == "snapshot"
    assert prepare_demo(folder, **options).source == "existing"
    assert prepare_demo(folder, reset=True, **options).source == "snapshot"
    store = Store.open(Paths(folder))
    try:
        assert store.get_settings().demo
        assert len(store.list_documents()) == 2
    finally:
        store.close()


def test_prepare_rebuilds_from_fixtures_when_the_snapshot_is_stale(life: SampleLife, tmp_path: Path) -> None:
    stale = tmp_path / "snapshot"
    shutil.copytree(life.snapshot, stale)
    (stale / "VERSION").write_text("old\n", encoding="utf-8")
    prepared = prepare_demo(tmp_path / "demo", samples=life.samples, fixtures=life.fixtures, snapshot=stale)
    assert prepared.source == "fixtures"


def test_prepare_without_recordings_explains_how_to_record(life: SampleLife, tmp_path: Path) -> None:
    with pytest.raises(DemoError, match="ORDNUNG_RECORD=1"):
        prepare_demo(
            tmp_path / "demo", samples=life.samples, fixtures=tmp_path / "none", snapshot=tmp_path / "x"
        )


# --------------------------------------------------------------------------------------------------
# checking
# --------------------------------------------------------------------------------------------------


def test_check_demo_passes_on_a_complete_recording(life: SampleLife) -> None:
    report = check_demo(
        samples=life.samples, fixtures=life.fixtures, snapshot=life.snapshot, questions=QUESTIONS
    )
    assert report.ok, report.problems
    assert report.documents == 2
    assert report.asks == len(QUESTIONS) * 4
    assert report.fixtures == len(list(life.fixtures.rglob("*.json")))
    assert report.warnings == []


def test_check_demo_reports_every_kind_of_problem(life: SampleLife, tmp_path: Path) -> None:
    fixtures = tmp_path / "fixtures"
    shutil.copytree(life.fixtures, fixtures)
    foreign = {
        "request": {"purpose": "extract", "doc_ids": ["doc_personal0000"]},
        "response": {"data": {"title": "no kind"}},
    }
    (fixtures / "extract" / "ffffffffffffffffffffffff.json").write_text(json.dumps(foreign), encoding="utf-8")
    ask = next((fixtures / "ask").glob("*.json"))
    recorded = json.loads(ask.read_text(encoding="utf-8"))
    recorded["response"]["text"] = "See [doc:doc_missing00000]."
    ask.write_text(json.dumps(recorded), encoding="utf-8")
    report = check_demo(
        samples=life.samples, fixtures=fixtures, snapshot=life.snapshot, questions=[*QUESTIONS, "Unrecorded?"]
    )
    problems = "\n".join(report.problems)
    assert not report.ok
    assert "references non-sample documents doc_personal0000" in problems
    assert "does not match DocumentExtraction" in problems
    assert "cites a missing record doc_missing00000" in problems
    assert "replay miss: ask" in problems
    assert "out of date" in problems  # the fixtures changed, so the snapshot no longer matches


def test_check_demo_warns_when_there_is_no_snapshot(life: SampleLife, tmp_path: Path) -> None:
    report = check_demo(
        samples=life.samples, fixtures=life.fixtures, snapshot=tmp_path / "none", questions=[]
    )
    assert report.ok
    assert report.asks == 0
    assert any("No demo snapshot" in warning for warning in report.warnings)


def test_check_demo_without_recordings_says_how_to_record(life: SampleLife, tmp_path: Path) -> None:
    report = check_demo(samples=life.samples, fixtures=tmp_path / "none", snapshot=life.snapshot)
    assert not report.ok
    assert len(report.problems) == 1 and "ORDNUNG_RECORD=1" in report.problems[0]


def test_canonical_dumps_ignore_timestamps_only(life: SampleLife, tmp_path: Path) -> None:
    first = build_demo(tmp_path / "a", samples=life.samples, fixtures=life.fixtures).data_dir
    second = build_demo(tmp_path / "b", samples=life.samples, fixtures=life.fixtures).data_dir
    assert dump_differences(canonical_dump(first / "ordnung.db"), canonical_dump(second / "ordnung.db")) == []
    store = Store.open(Paths(second))
    try:
        store._conn().execute("UPDATE documents SET created_at = '2000-01-01T00:00:00Z'")
        assert canonical_dump(first / "ordnung.db") == canonical_dump(second / "ordnung.db")
        store._conn().execute("UPDATE documents SET title = 'Changed'")
    finally:
        store.close()
    assert dump_differences(canonical_dump(first / "ordnung.db"), canonical_dump(second / "ordnung.db"))


# --------------------------------------------------------------------------------------------------
# the New-mail tray and the tour
# --------------------------------------------------------------------------------------------------


async def test_opening_a_tray_letter_reads_it_live(life: SampleLife, tmp_path: Path) -> None:
    ctx = open_demo(life, tmp_path / "demo")
    manifest = load_manifest(life.samples)
    events = record_events(ctx.bus)
    try:
        opening = await tour.start_tray_item(ctx, "price", manifest=manifest, samples=life.samples)
        assert opening.job is not None and opening.job.status == "running"
        assert ctx.store.claim_next_job() is None  # the background worker cannot take it too
        assert opening.item.opened and opening.item.doc_id == life.ids["price"]
        document = await tour.finish_tray_item(ctx, opening, stage_delay=0)
        assert document.id == life.ids["price"]
        assert document.status in ("processed", "needs_review")
        assert {"demo.mail", "suggestions.updated"} <= {name for name, _ in events}
        items = {item.id: item for item in tour.tray_items(ctx.store, manifest)}
        assert items["price"].opened and items["price"].doc_id == life.ids["price"]
        assert not items["appointment"].opened
        again = await tour.start_tray_item(ctx, "price", manifest=manifest, samples=life.samples)
        assert again.job is None and again.document.id == life.ids["price"]
    finally:
        ctx.close()


async def test_opening_photos_combines_them_into_one_letter(life: SampleLife, tmp_path: Path) -> None:
    ctx = open_demo(life, tmp_path / "demo")
    try:
        doc_id = await tour.open_tray_item(
            ctx, "appointment", stage_delay=0, manifest=load_manifest(life.samples), samples=life.samples
        )
        document = ctx.store.get_document(doc_id)
        assert doc_id == life.ids["appointment"]
        assert document is not None and document.pages == 2 and document.text_mode == "vision"
    finally:
        ctx.close()


async def test_an_unknown_tray_letter_is_not_found(life: SampleLife, tmp_path: Path) -> None:
    ctx = open_demo(life, tmp_path / "demo")
    try:
        with pytest.raises(tour.TrayItemNotFound):
            await tour.start_tray_item(ctx, "tax", manifest=load_manifest(life.samples), samples=life.samples)
    finally:
        ctx.close()


async def test_stages_are_paced_in_demo_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    assert tour.paced(0) is None
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    pause = tour.paced(tour.DEMO_STAGE_DELAY_S)
    assert pause is not None
    for stage in ("intake", "extract", "done"):
        waiting = pause(stage, 0.5)
        assert waiting is not None
        await waiting
    assert slept == [0.6, 0.6]


async def test_recorded_questions_replay_after_opening_tray_letters(life: SampleLife, tmp_path: Path) -> None:
    from ordnung.assistant.ask import ask_stream

    ctx = open_demo(life, tmp_path / "demo")
    try:
        await tour.open_tray_item(
            ctx, "price", stage_delay=0, manifest=load_manifest(life.samples), samples=life.samples
        )
        answered = [event async for event in tour.demo_safe_stream(ask_stream(ctx, QUESTIONS[1]), demo=True)]
        assert answered[-1].type == "done"
        assert answered[-1].text is not None and answered[-1].text.startswith(
            "Your gym membership is on file"
        )
        missed = [
            event async for event in tour.demo_safe_stream(ask_stream(ctx, "Anything free?"), demo=True)
        ]
        assert [event.type for event in missed] == ["error"]
        assert missed[0].error == tour.DEMO_MISS_MESSAGE
        assert getattr(missed[0], "error_code", None) == "demo_miss"
    finally:
        ctx.close()


async def test_demo_safe_stream_passes_everything_through_outside_the_demo() -> None:
    async def events() -> Any:
        yield StreamEvent(type="error", error="no recorded response for ask (x)")

    passed = [event async for event in tour.demo_safe_stream(events(), demo=False)]
    assert passed[0].error == "no recorded response for ask (x)"
    assert tour.is_replay_miss(passed[0])
    assert not tour.is_replay_miss(StreamEvent(type="text", text="hi"))


def test_friendly_llm_error() -> None:
    miss = ReplayMiss("no recorded response for draft (k)")
    assert tour.friendly_llm_error(miss, demo=True) == tour.DEMO_MISS_MESSAGE
    assert tour.friendly_llm_error(miss, demo=False) == str(miss)
    assert tour.friendly_llm_error(LLMError("Claude is busy"), demo=True) == "Claude is busy"


def test_tour_state_round_trip(store: Store) -> None:
    assert tour.get_tour(store) == TourState()
    tour.reset_demo_state(store)
    assert tour.get_tour(store).active and tour.get_tour(store).step == 0
    updated = tour.set_tour(store, {"step": 2})
    assert updated.step == 2 and updated.active
    finished = tour.set_tour(
        store, tour.get_tour(store).model_copy(update={"completed": True, "active": False})
    )
    assert finished.completed and not tour.get_tour(store).active


def test_suggested_questions_must_be_a_list(tmp_path: Path) -> None:
    path = tmp_path / "asks.json"
    path.write_text(json.dumps(["  When   is rent due? ", ""]), encoding="utf-8")
    assert tour.suggested_questions(path) == ["When is rent due?"]
    path.write_text(json.dumps({"questions": []}), encoding="utf-8")
    with pytest.raises(DemoError, match="JSON list"):
        tour.suggested_questions(path)


# --------------------------------------------------------------------------------------------------
# what /api/demo calls
# --------------------------------------------------------------------------------------------------


async def test_open_mail_answers_at_once_and_reads_in_the_background(
    life: SampleLife, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ORDNUNG_SAMPLES", str(life.samples))
    ctx = open_demo(life, tmp_path / "demo")
    try:
        assert [item.id for item in tour.list_mail(ctx)] == ["price", "appointment"]
        monkeypatch.setattr(tour, "DEMO_STAGE_DELAY_S", 0.0)
        document, job = await tour.open_mail(ctx, "price")
        assert document.id == life.ids["price"] and job.status == "running"
        await asyncio.gather(*tour._READING)
        read = ctx.store.get_document(document.id)
        assert read is not None and read.status in ("processed", "needs_review")
        again, same_job = await tour.open_mail(ctx, "price")
        assert again.id == document.id and same_job.id == job.id
        with pytest.raises(KeyError):
            await tour.open_mail(ctx, "nope")
        assert tour.update_tour(ctx.store, step=3).step == 3
    finally:
        ctx.close()


async def test_the_demo_api_uses_the_tray(
    life: SampleLife, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("ordnung.api.app")
    import httpx

    from ordnung.api.app import create_app

    monkeypatch.setenv("ORDNUNG_SAMPLES", str(life.samples))
    monkeypatch.setattr(tour, "DEMO_STAGE_DELAY_S", 0.0)
    ctx = open_demo(life, tmp_path / "demo")
    transport = httpx.ASGITransport(app=create_app(ctx, token=None, demo=True))
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            tray = (await client.get("/api/demo/mail")).json()
            assert [item["id"] for item in tray] == ["price", "appointment"]
            opened = await client.post(
                "/api/demo/mail", json={"id": "price"}, headers={"X-Ordnung-Client": "test"}
            )
            assert opened.status_code == 200, opened.text
            assert opened.json()["document"]["id"] == life.ids["price"]
            await asyncio.gather(*tour._READING)
            tray = (await client.get("/api/demo/mail")).json()
            assert tray[0]["opened"] and tray[0]["doc_id"] == life.ids["price"]
            missing = await client.post(
                "/api/demo/mail", json={"id": "nope"}, headers={"X-Ordnung-Client": "test"}
            )
            assert missing.status_code == 404
            tour_state = await client.patch(
                "/api/demo/tour", json={"step": 1}, headers={"X-Ordnung-Client": "test"}
            )
            assert tour_state.json()["step"] == 1
    finally:
        ctx.close()
