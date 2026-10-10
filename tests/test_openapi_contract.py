"""The web app's copy of the API contract is current, and live events match their declared models.

``web/openapi.json`` is what ``ordnung openapi`` prints and ``web/src/api/schema.d.ts`` is generated
from it (``make openapi``); the web app derives its API types from them. When the backend's routes
or models change without regenerating both, these tests fail — in CI too — so the web app can't
drift from the API unnoticed.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any, get_args

import pytest
from pydantic import ValidationError

from fixtures_llm import GYM_CONTRACT_LETTER, TAX_LETTER, record_events
from ordnung import clock, models
from ordnung.api.app import openapi_json, openapi_schema
from ordnung.api.routes.drafts import DraftCreate
from ordnung.ingest import pipeline
from test_api_support import TODAY, api_for

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
OPENAPI_JSON = WEB / "openapi.json"
SCHEMA_TS = WEB / "src" / "api" / "schema.d.ts"
SOURCES = ROOT / "src" / "ordnung"
REGENERATE = "run `make openapi` (ordnung openapi > web/openapi.json && cd web && npm run gen:api)"

_TS_COMPONENT = re.compile(
    r"^ {8}(?:\"(?P<quoted>[^\"]+)\"|(?P<plain>[A-Za-z_][\w-]*)): (?P<body>\{|Record<string, never>;)$"
)
_TS_PROPERTY = re.compile(r"^ {12}(?:\"(?P<quoted>[^\"]+)\"|(?P<plain>[A-Za-z_]\w*))\??: ")
_PUBLISH = re.compile(r"""\bpublish\(\s*["'](?P<type>[a-z_]+\.[a-z_]+)["']""")


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    return openapi_schema()


# --------------------------------------------------------------------------------------------------
# the generated files are current
# --------------------------------------------------------------------------------------------------


def _enums_sorted(value: Any) -> Any:
    """``value`` with the values of every ``enum`` sorted. Their order follows Python's ``Literal``
    cache: 3.11–3.13 reuse an equal union created earlier (``TimelineEntry.direction`` comes out as
    ``["out", "in"]``), 3.14 keeps each one's own order."""
    if isinstance(value, dict):
        return {
            key: sorted(item, key=json.dumps) if key == "enum" else _enums_sorted(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_enums_sorted(item) for item in value]
    return value


def test_web_openapi_json_is_current(schema: dict[str, Any]) -> None:
    assert OPENAPI_JSON.is_file(), f"web/openapi.json is missing — {REGENERATE}"
    text = OPENAPI_JSON.read_text(encoding="utf-8")
    stored, current = _enums_sorted(json.loads(text)), _enums_sorted(schema)
    if stored != current:
        changed = sorted(set(stored.get("paths", {})) ^ set(current["paths"]))
        components = stored.get("components", {}).get("schemas", {})
        differing = sorted(
            name
            for name in {*components, *current["components"]["schemas"]}
            if components.get(name) != current["components"]["schemas"].get(name)
        )
        pytest.fail(
            f"web/openapi.json is stale — {REGENERATE}.\n"
            f"Paths added/removed: {changed or 'none'}\nChanged schemas: {differing[:20] or 'none'}"
        )
    assert text == openapi_json(json.loads(text)), (
        f"web/openapi.json is not formatted as `ordnung openapi` prints it — {REGENERATE}"
    )


def test_enum_order_is_not_part_of_the_contract() -> None:
    reordered = {"direction": {"anyOf": [{"type": "string", "enum": ["in", "out"]}, {"type": "null"}]}}
    cached = {"direction": {"anyOf": [{"type": "string", "enum": ["out", "in"]}, {"type": "null"}]}}
    assert _enums_sorted(reordered) == _enums_sorted(cached)
    assert _enums_sorted({"enum": ["in"]}) != _enums_sorted({"enum": ["in", "out"]})


def _ts_components(text: str) -> dict[str, set[str]]:
    """``components.schemas`` of the generated ``schema.d.ts``: name → property names."""
    section = text[text.index("export interface components {") :]
    section = section[: section.index("\n    responses:")]
    found: dict[str, set[str]] = {}
    current: set[str] | None = None
    for line in section.splitlines():
        component = _TS_COMPONENT.match(line)
        if component:
            current = found.setdefault(component["quoted"] or component["plain"], set())
            continue
        prop = _TS_PROPERTY.match(line)
        if prop and current is not None:
            current.add(prop["quoted"] or prop["plain"])
    return found


def test_generated_typescript_types_match_openapi_json() -> None:
    assert SCHEMA_TS.is_file(), f"web/src/api/schema.d.ts is missing — {REGENERATE}"
    stored = json.loads(OPENAPI_JSON.read_text(encoding="utf-8"))
    text = SCHEMA_TS.read_text(encoding="utf-8")
    generated = _ts_components(text)
    expected = {
        name: set(definition.get("properties", {}))
        for name, definition in stored["components"]["schemas"].items()
    }
    assert set(generated) == set(expected), (
        f"schema.d.ts lists other schemas than openapi.json — {REGENERATE}"
    )
    stale = sorted(name for name, props in expected.items() if generated[name] != props)
    assert not stale, f"schema.d.ts is stale for {stale} — {REGENERATE}"
    missing_paths = [path for path in stored["paths"] if f'    "{path}": {{' not in text]
    assert not missing_paths, f"schema.d.ts lacks {missing_paths} — {REGENERATE}"


def test_make_and_npm_regenerate_both_files() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    recipe = makefile[makefile.index("\nopenapi:") :].split("\n\n")[0]
    assert "ordnung openapi > web/openapi.json" in recipe and "npm run gen:api" in recipe
    scripts = json.loads((WEB / "package.json").read_text(encoding="utf-8"))["scripts"]
    assert scripts["gen:api"].startswith("openapi-typescript openapi.json -o src/api/schema.d.ts")


# --------------------------------------------------------------------------------------------------
# the contract's content
# --------------------------------------------------------------------------------------------------


def test_list_endpoints_answer_plain_arrays(schema: dict[str, Any]) -> None:
    for path in (
        "/api/documents",
        "/api/items",
        "/api/contracts",
        "/api/parties",
        "/api/suggestions",
        "/api/drafts",
        "/api/timeline",
        "/api/lanes",
        "/api/activity",
        "/api/rules",
        "/api/jobs",
        "/api/demo/mail",
    ):
        body = schema["paths"][path]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
        assert body["type"] == "array", path


def test_response_models_mark_every_field_required(schema: dict[str, Any]) -> None:
    """Responses always carry every field, so the generated types don't make them optional."""
    components = schema["components"]["schemas"]
    for name in (
        "Document",
        "Item",
        "Contract",
        "Health",
        "UploadResult",
        "Brief",
        "ReviewStarted",
        "UsageStats",
    ):
        definition = components[name]
        assert set(definition.get("required", [])) == set(definition["properties"]), name
    # request bodies keep their optional fields optional
    assert "required" not in components["ItemPatch"]


def test_health_documents_probe_and_rules_date(schema: dict[str, Any]) -> None:
    operation = schema["paths"]["/api/health"]["get"]
    assert [p["name"] for p in operation["parameters"]] == ["probe"]
    assert "429" in operation["responses"]
    assert {"rules_last_checked", "checks"} <= set(schema["components"]["schemas"]["Health"]["properties"])


def test_party_and_letter_details_carry_a_region_suggestion(schema: dict[str, Any]) -> None:
    """The Land the postcode on a sender's letter suggests: on both details, ``null`` when there is none."""
    components = schema["components"]["schemas"]
    suggestion = components["RegionSuggestion"]
    assert set(suggestion["properties"]) == {
        "region",
        "postcode",
        "doc_id",
        "waiting",
        "may_be_late",
        "idea_id",
        "declined",
    }
    assert set(suggestion["required"]) == set(suggestion["properties"])
    for name in ("PartyDetail", "DocumentDetail"):
        field = components[name]["properties"]["region_suggestion"]
        assert field["anyOf"] == [{"$ref": "#/components/schemas/RegionSuggestion"}, {"type": "null"}], name
        assert "region_suggestion" in components[name]["required"], name
        assert getattr(models, name).model_fields["region_suggestion"].default is None, name
    assert "region_suggestion" not in models.Party.model_fields


def test_backup_info_and_weekly_session_carry_the_newest_copy(schema: dict[str, Any]) -> None:
    """The newest copy kept elsewhere: always on the backup's info, on the weekly session only when a
    reminder is due (``null`` otherwise). Never named ``copy``, which would hide ``BaseModel.copy``."""
    components = schema["components"]["schemas"]
    copy = components["BackupCopy"]
    assert set(copy["properties"]) == {
        "last_backup_at",
        "last_backup_restored",
        "sync_saved_at",
        "sync_standing_by",
        "days",
        "due",
        "due_after_days",
    }
    assert set(copy["required"]) == set(copy["properties"])
    info = components["BackupInfo"]
    assert info["properties"]["last_copy"]["$ref"] == "#/components/schemas/BackupCopy"
    assert "last_copy" in info["required"] and "copy" not in info["properties"]
    week = components["WeeklySession"]
    assert week["properties"]["backup"]["anyOf"] == [
        {"$ref": "#/components/schemas/BackupCopy"},
        {"type": "null"},
    ]
    assert "backup" in week["required"]
    assert models.WeeklySession.model_fields["backup"].default is None
    nothing_known = models.BackupCopy()
    assert (nothing_known.last_backup_at, nothing_known.days, nothing_known.due) == (None, None, False)
    assert nothing_known.due_after_days == 30


def test_a_letter_detail_says_who_it_is_addressed_to(schema: dict[str, Any]) -> None:
    """Worked out on read for the letter's page only: the letter itself has no such field."""
    detail = schema["components"]["schemas"]["DocumentDetail"]
    assert detail["properties"]["addressed_to"]["anyOf"] == [{"type": "string"}, {"type": "null"}]
    assert "addressed_to" in detail["required"]
    assert models.DocumentDetail.model_fields["addressed_to"].default is None
    assert "addressed_to" not in models.Document.model_fields


def test_a_letter_can_be_asked_for_in_another_name(schema: dict[str, Any]) -> None:
    """``sender_name`` is optional, one line of at most 120 characters."""
    create = schema["components"]["schemas"]["DraftCreate"]
    assert "sender_name" not in create.get("required", [])
    field = create["properties"]["sender_name"]
    assert field["anyOf"] == [{"type": "string", "maxLength": 120}, {"type": "null"}]
    assert DraftCreate.model_fields["sender_name"].default is None


def test_the_letter_list_says_where_a_search_found_each_letter(schema: dict[str, Any]) -> None:
    """``GET /api/documents`` rows are the letter plus ``found_in``, a view model made by the route: the
    letter itself (what the store keeps and Ask's ledger fingerprint hashes) has no such field. A letter's
    detail lists the pages whose scanner text is kept, for search only."""
    components = schema["components"]["schemas"]
    body = schema["paths"]["/api/documents"]["get"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]
    assert body["items"] == {"$ref": "#/components/schemas/DocumentListEntry"}
    entry = components["DocumentListEntry"]
    assert set(entry["properties"]) == set(components["Document"]["properties"]) | {"found_in"}
    assert set(entry["required"]) == set(entry["properties"])
    found_in = entry["properties"]["found_in"]["anyOf"]
    assert sorted(found_in[0]["enum"]) == ["letter", "scanner_text"] and found_in[1] == {"type": "null"}
    assert issubclass(models.DocumentListEntry, models.Document)
    assert "found_in" not in models.Document.model_fields
    detail = components["DocumentDetail"]
    assert detail["properties"]["scan_text_pages"] == {
        "items": {"type": "integer"},
        "type": "array",
        "title": "Scan Text Pages",
    }
    assert "scan_text_pages" in detail["required"]
    assert models.DocumentDetail.model_fields["scan_text_pages"].default_factory is list


def test_a_profile_keeps_the_move_the_person_told(schema: dict[str, Any]) -> None:
    """``moved_on`` (``null``: no move told) and the address before it; ``""`` clears either on a PUT."""
    components = schema["components"]["schemas"]
    profile = components["Profile"]
    assert profile["properties"]["moved_on"]["anyOf"] == [{"type": "string"}, {"type": "null"}]
    assert profile["properties"]["old_address"]["type"] == "string"
    assert {"moved_on", "old_address"} <= set(profile["required"])
    assert (models.Profile().moved_on, models.Profile().old_address) == (None, "")
    patch = components["ProfilePatch"]
    assert patch["properties"]["moved_on"]["anyOf"][1] == {"type": "null"}
    assert patch["properties"]["old_address"]["anyOf"] == [
        {"type": "string", "maxLength": 1000},
        {"type": "null"},
    ]
    assert "required" not in patch


def test_export_letters_is_a_computer_only_zip_download(schema: dict[str, Any]) -> None:
    operation = schema["paths"]["/api/documents.zip"]["get"]
    assert set(schema["paths"]["/api/documents.zip"]) == {"get"}
    params = {p["name"]: p for p in operation["parameters"]}
    assert list(params) == ["year", "until", "tax", "party_id"]
    assert all(p["in"] == "query" and not p.get("required") for p in params.values())
    year = params["year"]["schema"]["anyOf"][0]
    assert (year["type"], year["minimum"], year["maximum"]) == ("integer", 1900, 2100)
    assert (params["tax"]["schema"]["type"], params["tax"]["schema"]["default"]) == ("boolean", False)
    assert set(operation["responses"]["200"]["content"]) == {"application/zip"}
    assert {"404", "422"} <= set(operation["responses"])
    assert "x-ordnung-phone" not in operation


def test_job_stages_match_the_pipeline() -> None:
    assert get_args(models.JobStage) == get_args(pipeline.Stage)


# --------------------------------------------------------------------------------------------------
# live events (GET /api/events)
# --------------------------------------------------------------------------------------------------


def test_every_published_event_is_declared() -> None:
    published: dict[str, list[str]] = {}
    for source in SOURCES.rglob("*.py"):
        for match in _PUBLISH.finditer(source.read_text(encoding="utf-8")):
            published.setdefault(match["type"], []).append(str(source.relative_to(ROOT)))
    assert published, "no publish() calls found — has the event bus moved?"
    undeclared = {name: where for name, where in published.items() if name not in models.SERVER_EVENTS}
    assert not undeclared, f"declare these events in models.ServerEvents: {undeclared}"


async def test_published_events_match_their_models(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        events = record_events(api.ctx.bus)
        client = api.client
        body = await api.upload(
            ("bescheid.pdf", TAX_LETTER.pdf()), ("vertrag.pdf", GYM_CONTRACT_LETTER.pdf())
        )
        await api.read_all()
        doc_id = body["documents"][0]["id"]
        await client.patch(f"/api/documents/{doc_id}", json={"received_date": "2026-09-20"})
        items = (await client.get("/api/items")).json()
        await client.patch(f"/api/items/{items[0]['id']}", json={"status": "done"})
        contracts = (await client.get("/api/contracts")).json()
        await client.patch(f"/api/contracts/{contracts[0]['id']}", json={"cost_amount": 25.0})
        draft = (await client.post("/api/drafts", json={"kind": "general_reply", "doc_id": doc_id})).json()
        await client.post(f"/api/drafts/{draft['id']}/sent", json={"channel": "letter", "date": TODAY})
        ideas = (await client.get("/api/suggestions")).json()
        if ideas:
            await client.patch(f"/api/suggestions/{ideas[0]['id']}", json={"status": "dismissed"})
        await client.post("/api/brief")
        await client.put("/api/profile", json={"name": "Sam"})
        await client.delete(f"/api/documents/{body['documents'][1]['id']}")

    seen = {name for name, _ in events}
    assert {"job.progress", "document.processed", "item.updated", "draft.created", "brief.updated"} <= seen
    problems = []
    for name, data in events:
        model = models.SERVER_EVENTS.get(name)
        if model is None:
            problems.append(f"{name}: not declared in models.ServerEvents")
            continue
        try:
            model.model_validate(data)
        except ValidationError as exc:
            problems.append(f"{name} {data}: {exc}")
    assert not problems, "\n".join(problems)
