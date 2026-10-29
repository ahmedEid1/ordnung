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
from ordnung.api.app import VIEW_MODELS, openapi_json, openapi_schema
from ordnung.api.routes import documents
from ordnung.api.routes.drafts import DraftCreate
from ordnung.db.store import HOUSEHOLD_META_KEY
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
        "/api/documents.json",
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
        "DocumentRow",
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


def test_text_in_pictures_has_a_setting_and_a_state(schema: dict[str, Any]) -> None:
    """*Text in pictures* (ADR 0024): the person's choice is a setting (``read_picture_text``, on by default,
    changed with ``PUT /api/settings``); this computer's state is ``Health.picture_text`` (none on a phone)."""
    components = schema["components"]["schemas"]
    setting = components["AppSettings"]["properties"]["read_picture_text"]
    assert (setting["type"], setting["default"]) == ("boolean", True)
    assert "read_picture_text" in components["AppSettings"]["required"]
    assert components["SettingsPatch"]["properties"]["read_picture_text"]["anyOf"] == [
        {"type": "boolean"},
        {"type": "null"},
    ]
    state = components["Health"]["properties"]["picture_text"]
    assert state["anyOf"] == [{"$ref": "#/components/schemas/PictureTextStatus"}, {"type": "null"}]
    assert "picture_text" in components["Health"]["required"]
    status = components["PictureTextStatus"]
    assert set(status["properties"]) == set(status["required"]) == {"state", "detail", "fix"}
    assert sorted(status["properties"]["state"]["enum"]) == sorted(get_args(models.PictureTextState))
    assert set(get_args(models.PictureTextState)) == {
        "reading",
        "off",
        "off_by_variable",
        "not_installed",
        "not_usable",
    }
    assert models.AppSettings().read_picture_text is True


def test_a_doctor_check_can_be_info(schema: dict[str, Any]) -> None:
    """A row that is neither ok nor a problem (an optional part not installed, something off by choice): ``info``.
    Only ``fail`` fails the doctor."""
    assert get_args(models.CheckStatus) == ("ok", "info", "warn", "fail")
    status = schema["components"]["schemas"]["DoctorCheck"]["properties"]["status"]
    assert sorted(status["enum"]) == ["fail", "info", "ok", "warn"]


async def test_the_health_of_this_computer_says_nothing_of_text_in_pictures_yet(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        health = (await api.client.get("/api/health")).json()
        assert health["picture_text"] is None


async def test_the_text_in_pictures_setting_is_saved(data_dir: Path) -> None:
    """``PUT /api/settings`` saves the switch (hand-off sync carries it: ``tests/test_sync_contract.py``)."""
    async with api_for(data_dir) as api:
        store = api.ctx.store
        assert (await api.client.get("/api/settings")).json()["read_picture_text"] is True
        saved = await api.client.put("/api/settings", json={"read_picture_text": False})
        assert saved.status_code == 200, saved.text
        assert saved.json()["read_picture_text"] is False
        assert store.get_settings().read_picture_text is False
        assert (await api.client.put("/api/settings", json={"llm_brief": False})).json()[
            "read_picture_text"
        ] is False
        assert (await api.client.put("/api/settings", json={"read_picture_text": "maybe"})).status_code == 422


def test_my_numbers_answers_the_numbers_page(schema: dict[str, Any]) -> None:
    """``GET /api/numbers`` answers ``NumbersPage``: the person's page as before, and each person of the
    household's numbers (``household``), the call-sheet numbers and cases that are only a member's
    (``filed_for``) and the numbers other people's letters show too (``also_for``)."""
    components = schema["components"]["schemas"]
    answer = schema["paths"]["/api/numbers"]["get"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]
    assert answer == {"$ref": "#/components/schemas/NumbersPage"}
    page, person = components["NumbersPage"], components["PersonNumbers"]
    assert set(page["properties"]) == set(models.MyNumbers.model_fields) | {
        "household",
        "filed_for",
        "also_for",
    }
    assert set(page["required"]) == set(page["properties"])
    assert page["properties"]["household"]["items"] == {"$ref": "#/components/schemas/PersonNumbers"}
    assert page["properties"]["filed_for"]["additionalProperties"] == {"type": "string"}
    assert page["properties"]["also_for"]["additionalProperties"] == {
        "items": {"type": "string"},
        "type": "array",
    }
    assert set(person["properties"]) == set(person["required"]) == {"id", "name", "about", "documents"}
    assert issubclass(models.NumbersPage, models.MyNumbers)


async def test_my_numbers_without_a_household_has_empty_household_parts(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        body = await api.upload(("bescheid.pdf", TAX_LETTER.pdf()))
        await api.read_all()
        assert body["documents"]
        page = (await api.client.get("/api/numbers")).json()
        assert (page["household"], page["filed_for"], page["also_for"]) == ([], {}, {})
        models.NumbersPage.model_validate(page)


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
    """``GET /api/documents`` rows are ``DocumentRow``, a view model made by the route: the letter
    without what Claude read from inside it in detail and the file hash (``LEFT_OUT_OF_LIST``), plus
    ``found_in``. The letter itself (what the store keeps and Ask's ledger fingerprint hashes) has no
    such field. A letter's detail lists the pages whose scanner text is kept, for search only."""
    components = schema["components"]["schemas"]
    body = schema["paths"]["/api/documents"]["get"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]
    assert body["items"] == {"$ref": "#/components/schemas/DocumentRow"}
    row, letter = components["DocumentRow"], components["Document"]
    assert (
        set(row["properties"])
        == (set(letter["properties"]) - documents.LEFT_OUT_OF_LIST) | documents.ROUTE_FIELDS
    )
    assert set(row["required"]) == set(row["properties"])
    kept = set(row["properties"]) - documents.ROUTE_FIELDS
    assert {name: row["properties"][name] for name in kept} == {
        name: letter["properties"][name] for name in kept
    }
    found_in = row["properties"]["found_in"]["anyOf"]
    assert sorted(found_in[0]["enum"]) == ["letter", "picture_text", "scanner_text"]
    assert found_in[1] == {"type": "null"}
    assert "found_in" not in models.Document.model_fields
    # the route's own type (ADR 0024 adds picture_text); the unused models.SearchFoundIn and
    # models.DocumentListEntry are gone (in no schema Claude is given: tests/test_llm_schemas.py)
    assert get_args(documents.LetterFoundIn) == ("letter", "scanner_text", "picture_text")
    assert not hasattr(models, "SearchFoundIn") and not hasattr(models, "DocumentListEntry")
    assert row["properties"]["tax_choice"]["anyOf"] == [{"type": "boolean"}, {"type": "null"}]
    assert "DocumentListEntry" not in components
    # the published description names the route's own type, and no model that is gone
    assert "LetterFoundIn" in row["description"]
    assert "SearchFoundIn" not in row["description"] and "DocumentListEntry" not in row["description"]
    detail = components["DocumentDetail"]
    assert detail["properties"]["scan_text_pages"] == {
        "items": {"type": "integer"},
        "type": "array",
        "title": "Scan Text Pages",
    }
    assert "scan_text_pages" in detail["required"]
    assert models.DocumentDetail.model_fields["scan_text_pages"].default_factory is list


def test_the_letter_list_leaves_out_exactly_the_reading_and_the_file_hash() -> None:
    """What the list leaves out is pinned: the letter's explanation, key facts, references, bank
    details and file hash. Every other field of a letter reaches the list by itself."""
    assert documents.LEFT_OUT_OF_LIST == frozenset(
        {"key_facts", "explanation", "references", "payment", "sha256"}
    )
    assert documents.LEFT_OUT_OF_LIST <= set(models.Document.model_fields)
    assert documents.ROUTE_FIELDS == frozenset({"found_in", "tax_choice"})
    assert (
        set(documents.DocumentRow.model_fields)
        == (set(models.Document.model_fields) - documents.LEFT_OUT_OF_LIST) | documents.ROUTE_FIELDS
    )
    assert not issubclass(documents.DocumentRow, models.Document)
    assert not documents.ROUTE_FIELDS & set(models.Document.model_fields)
    for name, field in documents.DocumentRow.model_fields.items():
        if name not in documents.ROUTE_FIELDS:
            assert field.annotation == models.Document.model_fields[name].annotation, name


def test_the_copy_of_your_records_lists_every_letter_whole(schema: dict[str, Any]) -> None:
    """``GET /api/documents.json`` ("Download a copy of your records") answers whole letters, as
    stored, with the person's own "For taxes" choice (``LetterRecord``), for the computer only."""
    assert set(schema["paths"]["/api/documents.json"]) == {"get"}
    operation = schema["paths"]["/api/documents.json"]["get"]
    body = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert body == {
        "type": "array",
        "items": {"$ref": "#/components/schemas/LetterRecord"},
        "title": body["title"],
    }
    assert "parameters" not in operation
    assert "x-ordnung-phone" not in operation
    components = schema["components"]["schemas"]
    record, letter = components["LetterRecord"], components["Document"]
    assert set(record["properties"]) == set(letter["properties"]) | {"tax_choice"}
    assert set(record["required"]) == set(record["properties"])
    assert {name: record["properties"][name] for name in letter["properties"]} == letter["properties"]
    assert record["properties"]["tax_choice"]["anyOf"] == [{"type": "boolean"}, {"type": "null"}]
    assert issubclass(documents.LetterRecord, models.Document)


def test_a_letter_detail_and_patch_carry_the_persons_tax_choice(schema: dict[str, Any]) -> None:
    """The letter's page answers ``LetterDetail``, a route-local ``DocumentDetail`` with the person's own
    "For taxes" choice (``null``: none, Claude's mark counts) and who the letter is for; a PATCH may set the
    choice. The letter itself (what Ask's fingerprint hashes) has no such field."""
    components = schema["components"]["schemas"]
    operation = schema["paths"]["/api/documents/{doc_id}"]["get"]
    body = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert body == {"$ref": "#/components/schemas/LetterDetail"}
    detail, base = components["LetterDetail"], components["DocumentDetail"]
    assert set(detail["properties"]) == set(base["properties"]) | {
        "tax_choice",
        "household",
        "picture_text_pages",
    }
    assert set(detail["required"]) == set(detail["properties"])
    assert detail["properties"]["tax_choice"]["anyOf"] == [{"type": "boolean"}, {"type": "null"}]
    assert detail["properties"]["household"] == {"$ref": "#/components/schemas/LetterFor"}
    assert issubclass(documents.LetterDetail, models.DocumentDetail)
    assert documents.LetterDetail.model_fields["tax_choice"].default is None
    patch = components["DocumentPatch"]
    field = patch["properties"]["tax_choice"]
    assert field["anyOf"] == [{"type": "boolean"}, {"type": "null"}]
    assert field["description"].startswith("For taxes: true or false is the person's own choice")
    assert "tax_choice" not in patch.get("required", [])
    assert "tax_choice" not in models.Document.model_fields
    assert "tax_choice" not in models.DocumentDetail.model_fields
    # DocumentDetail stays a named view model (models.py is a benchmark digest file)
    assert models.DocumentDetail in VIEW_MODELS


def test_a_letters_detail_names_its_picture_text_pages(schema: dict[str, Any]) -> None:
    """The letter's page lists the pages whose words Ordnung read itself from the picture (Tesseract, ADR 0024),
    kept for search only: page numbers, never the words. Route-local: ``models.DocumentDetail`` has no such field
    (models.py is a benchmark digest file)."""
    components = schema["components"]["schemas"]
    detail = components["LetterDetail"]
    assert detail["properties"]["picture_text_pages"] == {
        "items": {"type": "integer"},
        "type": "array",
        "title": "Picture Text Pages",
        "description": (
            "The pages (1-based) whose words Ordnung read itself from the picture (Tesseract), kept for search "
            "only: never shown, checked or sent to Claude."
        ),
    }
    assert "picture_text_pages" in detail["required"]
    assert documents.LetterDetail.model_fields["picture_text_pages"].default_factory is list
    assert "picture_text_pages" not in models.DocumentDetail.model_fields
    assert "picture_text_pages" not in components["DocumentDetail"]["properties"]


async def test_a_letter_with_no_text_read_from_its_picture_names_no_such_page(data_dir: Path) -> None:
    """Without text Ordnung read from a picture, a letter's page names no such page, and a search finds the
    letter by its own words, never as ``picture_text``."""
    async with api_for(data_dir) as api:
        client = api.client
        body = await api.upload(("bescheid.pdf", TAX_LETTER.pdf()))
        await api.read_all()
        doc_id = body["documents"][0]["id"]
        assert (await client.get(f"/api/documents/{doc_id}")).json()["picture_text_pages"] == []
        assert [row["found_in"] for row in (await client.get("/api/documents")).json()] == [None]
        found = (await client.get("/api/documents", params={"q": "Einkommensteuer"})).json()
        assert [row["found_in"] for row in found] == ["letter"]


def test_the_household_has_three_operations_and_its_shapes(schema: dict[str, Any]) -> None:
    """``/api/household``: GET and PATCH (file letters) for the phone too, PUT (edit the people) on the
    computer only. Bodies refuse unknown fields; the caps are in the schema."""
    operations = schema["paths"]["/api/household"]
    assert set(operations) == {"get", "put", "patch"}
    assert operations["get"].get("x-ordnung-phone") is True
    assert operations["patch"].get("x-ordnung-phone") is True
    assert "x-ordnung-phone" not in operations["put"]
    for method in ("get", "put", "patch"):
        answer = operations[method]["responses"]["200"]["content"]["application/json"]["schema"]
        assert answer == {"$ref": "#/components/schemas/Household"}, method
    components = schema["components"]["schemas"]
    for name in ("Household", "HouseholdPerson", "HouseholdMember", "LetterFor"):
        definition = components[name]
        assert set(definition["required"]) == set(definition["properties"]), name
    assert set(components["Household"]["properties"]) == {"members", "filed", "mine", "suggested", "version"}
    assert set(components["HouseholdPerson"]["properties"]) == {"id", "name", "signs", "letters"}
    assert set(components["LetterFor"]["properties"]) == {"filed_for", "mine", "suggested", "add"}
    change = components["HouseholdChange"]
    assert change["additionalProperties"] is False and change["required"] == ["base", "members"]
    assert change["properties"]["members"]["maxItems"] == 50
    assert change["properties"]["also_file"]["maxItems"] == 1
    assert components["MemberIn"]["additionalProperties"] is False
    assert components["MemberIn"]["properties"]["name"]["maxLength"] == 1000
    filing = components["HouseholdFiling"]
    assert filing["additionalProperties"] is False
    letters = filing["properties"]["letters"]
    assert (letters["minProperties"], letters["maxProperties"]) == (1, 1000)


async def test_a_new_library_has_no_tax_choice_and_an_empty_household(data_dir: Path) -> None:
    """Before the person chooses anything: every letter says no tax choice (Claude's mark counts) and
    nobody else it is for, and the household is empty. Bodies that break the contract answer 422."""
    async with api_for(data_dir) as api:
        client = api.client
        body = await api.upload(("bescheid.pdf", TAX_LETTER.pdf()))
        await api.read_all()
        doc_id = body["documents"][0]["id"]
        detail = (await client.get(f"/api/documents/{doc_id}")).json()
        assert detail["tax_choice"] is None
        assert detail["household"] == {"filed_for": None, "mine": False, "suggested": None, "add": None}
        assert [row["tax_choice"] for row in (await client.get("/api/documents")).json()] == [None]
        assert [row["tax_choice"] for row in (await client.get("/api/documents.json")).json()] == [None]
        for bad in ("maybe", 2, []):
            assert (
                await client.patch(f"/api/documents/{doc_id}", json={"tax_choice": bad})
            ).status_code == 422
        assert (await client.patch(f"/api/documents/{doc_id}", json={"title": "Bescheid"})).status_code == 200
        empty = {"members": [], "filed": {}, "mine": [], "suggested": {}, "version": "4f53cda18c2baa0c"}
        assert (await client.get("/api/household")).json() == empty
        change = {"base": empty["version"], "members": [{"name": "Alex Rivera"}]}
        assert (await client.put("/api/household", json={**change, "extra": 1})).status_code == 422
        assert (
            await client.put("/api/household", json={**change, "also_file": ["a", "b"]})
        ).status_code == 422
        assert (await client.patch("/api/household", json={"letters": {}})).status_code == 422
        assert api.ctx.store.tax_choices() == {}
        assert api.ctx.store.get_meta(HOUSEHOLD_META_KEY) is None


def test_the_upload_form_names_every_kind_of_file_it_takes(schema: dict[str, Any]) -> None:
    form = schema["components"]["schemas"]["Body_upload_documents_api_documents_post"]
    assert form["properties"]["files"]["description"] == "The letters (PDF, photos, .txt/.eml/.msg)"


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
