"""What a paired phone may do: every API operation is classified, the classification holds before
routing (templates, double matches, HEAD), and the OpenAPI schema publishes exactly the phone's list."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, get_args

import pytest
from starlette.routing import compile_path

from ordnung.api.app import openapi_schema
from ordnung.config import Paths
from ordnung.ids import new_id
from ordnung.phone import ERROR_STATUS, PhoneErrorCode, cookie_name, scope
from ordnung.phone.scope import COMPUTER_ONLY, NEVER_ON_PHONE, OPENAPI_MARK, PHONE_ROUTES, classify

ROOT = Path(__file__).resolve().parents[1]
OPENAPI_JSON = ROOT / "web" / "openapi.json"
_PARAM = re.compile(r"\{[^}]+\}")


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    return openapi_schema()


def _marked(schema: dict[str, Any]) -> set[scope.Operation]:
    return {
        (method.upper(), path)
        for path, operations in schema["paths"].items()
        for method, operation in operations.items()
        if isinstance(operation, dict) and operation.get(OPENAPI_MARK) is True
    }


def _example(template: str) -> str:
    """A path the template matches (every parameter ``x1``)."""
    return _PARAM.sub("x1", template)


# --------------------------------------------------------------------------------------------------
# every operation is a decision
# --------------------------------------------------------------------------------------------------


def test_every_operation_is_classified(schema: dict[str, Any]) -> None:
    """A new route is refused on phones until it is added to one of the two lists, and this test fails
    until then."""
    operations = scope.schema_operations(schema)
    unclassified = sorted(operations - PHONE_ROUTES - COMPUTER_ONLY)
    assert not unclassified, f"add these to PHONE_ROUTES or COMPUTER_ONLY: {unclassified}"
    gone = sorted((PHONE_ROUTES | COMPUTER_ONLY) - operations)
    assert not gone, f"classified operations that don't exist: {gone}"
    assert not PHONE_ROUTES & COMPUTER_ONLY
    assert (len(operations), len(PHONE_ROUTES), len(COMPUTER_ONLY)) == (116, 57, 59)


def test_never_on_phone_stays_on_the_computer() -> None:
    assert not set(NEVER_ON_PHONE) & PHONE_ROUTES
    assert set(NEVER_ON_PHONE) <= COMPUTER_ONLY
    assert all(reason.strip() for reason in NEVER_ON_PHONE.values())
    for operation in (
        ("GET", "/api/settings"),
        ("PUT", "/api/settings"),
        ("PUT", "/api/profile"),
        ("GET", "/api/backup"),
        ("POST", "/api/backup"),
        ("DELETE", "/api/data"),
        ("GET", "/api/documents/{doc_id}/file"),
        ("POST", "/api/documents/held/read"),
        ("PUT", "/api/phone"),
        ("POST", "/api/phone/pairing"),
    ):
        assert operation in NEVER_ON_PHONE, operation


def test_calendar_files_stay_on_the_computer() -> None:
    """Review finding: a phone downloaded ``ordnung.ics`` (to-do titles, amounts, what to do) although a
    phone keeps no copy and downloads no records. The files and the note that they were downloaded are
    computer-only."""
    for operation in (
        ("GET", "/api/calendar.ics"),
        ("GET", "/api/items/{item_id}.ics"),
        ("POST", "/api/calendar/exported"),
    ):
        assert operation in COMPUTER_ONLY and operation not in PHONE_ROUTES, operation
        assert operation not in scope.CHANGE_LABELS
    assert NEVER_ON_PHONE[("GET", "/api/calendar.ics")] == "records leave the computer"
    assert scope.match("GET", "/api/calendar.ics") is None
    assert scope.match("GET", "/api/items/itm_1.ics") is None


def test_the_letters_zip_stays_on_the_computer() -> None:
    """Export letters: the ZIP holds every original, like a letter's own file, so it never reaches a
    phone; it is a download, not a change of the ledger."""
    operation = ("GET", "/api/documents.zip")
    assert operation in COMPUTER_ONLY and operation not in PHONE_ROUTES
    assert NEVER_ON_PHONE[operation] == "originals leave the computer"
    assert operation not in scope.CHANGE_LABELS
    assert classify("GET", "/api/documents.zip") == "computer"
    assert classify("HEAD", "/api/documents.zip") == "computer"
    assert scope.match("GET", "/api/documents.zip") is None


def test_the_only_delete_on_a_phone_is_the_undo_of_answered(schema: dict[str, Any]) -> None:
    deletes = {operation for operation in scope.schema_operations(schema) if operation[0] == "DELETE"}
    assert deletes & PHONE_ROUTES == {("DELETE", "/api/drafts/{draft_id}/answered")}
    assert deletes - PHONE_ROUTES - {("DELETE", "/api/phone/pairing")} <= set(NEVER_ON_PHONE)


def test_phone_access_itself_is_computer_only_except_pairing(schema: dict[str, Any]) -> None:
    phone_access = {op for op in scope.schema_operations(schema) if op[1].startswith("/api/phone")}
    assert phone_access & PHONE_ROUTES == {("POST", "/api/phone/pair")}
    assert len(phone_access) == 7


# --------------------------------------------------------------------------------------------------
# classifying a request before routing
# --------------------------------------------------------------------------------------------------


def test_every_operation_classifies_as_its_list(schema: dict[str, Any]) -> None:
    """A path each template matches classifies as that operation's list: no phone template is shadowed
    by a computer-only one."""
    wrong = []
    for method, template in sorted(scope.schema_operations(schema)):
        expected = "phone" if (method, template) in PHONE_ROUTES else "computer"
        got = classify(method, _example(template))
        if got != expected:
            wrong.append(f"{method} {template}: {got}, expected {expected}")
    assert not wrong, "\n".join(wrong)


@pytest.mark.parametrize(
    ("method", "path", "expected"),
    [
        ("GET", "/api/documents/doc_ab/pages/1.jpg", "phone"),
        ("HEAD", "/api/documents/doc_x/thumbnail.jpg", "phone"),
        ("get", "/api/items/itm_x", "phone"),
        ("GET", "/api/items/itm_x", "phone"),
        ("GET", "/api/items/itm_x.ics", "computer"),  # matches {item_id} (phone) and {item_id}.ics (not)
        ("HEAD", "/api/calendar.ics", "computer"),
        ("DELETE", "/api/drafts/drf_1/answered", "phone"),
        ("POST", "/api/phone/pair", "phone"),
        ("GET", "/api/health", "phone"),
        ("DELETE", "/api/drafts/drf_1", "computer"),
        ("HEAD", "/api/documents/doc_x/file", "computer"),
        ("GET", "/api/documents/doc_x/file", "computer"),
        ("POST", "/api/documents/held/read", "computer"),
        ("GET", "/api/phone", "computer"),
        ("DELETE", "/api/phone/devices/phn_x", "computer"),
        ("GET", "/api/openapi.json", "unknown"),
        ("GET", "/api/nothing-here", "unknown"),
        ("GET", "/api/items/", "unknown"),
        ("OPTIONS", "/api/items", "unknown"),
        ("POST", "/api/health", "unknown"),
        ("PUT", "/api/items/itm_x", "unknown"),
        ("GET", "/api/documents/a/b/file", "unknown"),
        ("GET", "/", "unknown"),
    ],
)
def test_classify(method: str, path: str, expected: str) -> None:
    assert classify(method, path) == expected


def test_a_double_match_is_a_phone_request_only_when_every_match_is(monkeypatch: pytest.MonkeyPatch) -> None:
    table = (
        ("GET", compile_path("/api/things/{thing_id}")[0], True),
        ("GET", compile_path("/api/things/{thing_id}.ics")[0], False),
    )
    monkeypatch.setattr(scope, "_COMPILED", table)
    assert classify("GET", "/api/things/t1") == "phone"
    assert classify("GET", "/api/things/t1.ics") == "computer"
    assert classify("HEAD", "/api/things/t1.ics") == "computer"


# --------------------------------------------------------------------------------------------------
# the scope in OpenAPI
# --------------------------------------------------------------------------------------------------


def test_the_openapi_marks_are_exactly_the_phone_routes(schema: dict[str, Any]) -> None:
    assert _marked(schema) == PHONE_ROUTES
    stored = json.loads(OPENAPI_JSON.read_text(encoding="utf-8"))
    assert _marked(stored) == PHONE_ROUTES, "web/openapi.json is stale — run `make openapi`"


def test_mark_openapi_skips_operations_a_schema_lacks() -> None:
    schema: dict[str, Any] = {"paths": {"/api/health": {"get": {}}, "/api/settings": {"get": {}}}}
    scope.mark_openapi(schema)
    assert schema["paths"]["/api/health"]["get"] == {OPENAPI_MARK: True}
    assert schema["paths"]["/api/settings"]["get"] == {}


# --------------------------------------------------------------------------------------------------
# the rest of the contract
# --------------------------------------------------------------------------------------------------


def test_the_cookie_is_named_per_port_with_the_host_prefix() -> None:
    assert cookie_name(8767) == "__Host-ordnung_phone_8767"
    assert cookie_name(8768) != cookie_name(8767)


def test_every_error_code_has_its_status() -> None:
    codes = set(get_args(PhoneErrorCode))
    assert set(ERROR_STATUS) == codes
    assert {
        "phone_not_paired",
        "computer_only",
        "wrong_code",
        "code_used",
        "too_many_phones",
        "unavailable",
        "not_set_up",
        "no_network",
        "port_busy",
        "not_listening",
        "not_phone",
        "too_many",
        "length_required",
        "too_large",
    } <= codes
    assert "no_code" not in codes  # wrong, expired and missing codes get one answer: wrong_code
    assert (ERROR_STATUS["phone_not_paired"], ERROR_STATUS["computer_only"]) == (401, 403)
    assert (ERROR_STATUS["wrong_code"], ERROR_STATUS["code_used"], ERROR_STATUS["not_phone"]) == (
        422,
        409,
        404,
    )
    assert (ERROR_STATUS["length_required"], ERROR_STATUS["too_large"], ERROR_STATUS["too_many"]) == (
        411,
        413,
        429,
    )


def test_phones_get_ids_and_a_folder_made_only_when_needed(tmp_path: Path) -> None:
    assert re.fullmatch(r"phn_[0-9a-z]{12}", new_id("phn"))
    paths = Paths(tmp_path / "data").ensure()
    assert paths.phone == paths.data_dir / "phone"
    assert not paths.phone.exists()


def test_health_says_who_asked(schema: dict[str, Any]) -> None:
    health = schema["components"]["schemas"]["Health"]
    assert sorted(health["properties"]["client"]["enum"]) == ["computer", "phone"]
    assert "client" in health["required"]


@pytest.mark.parametrize(
    ("method", "path", "expected"),
    [
        ("PATCH", "/api/items/itm_1", (("PATCH", "/api/items/{item_id}"), {"item_id": "itm_1"})),
        ("HEAD", "/api/items/x", (("GET", "/api/items/{item_id}"), {"item_id": "x"})),
        ("HEAD", "/api/items/x.ics", None),  # the calendar file of a to-do stays on the computer
        (
            "GET",
            "/api/documents/doc_1/pages/2.jpg",
            (("GET", "/api/documents/{doc_id}/pages/{page}.jpg"), {"doc_id": "doc_1", "page": "2"}),
        ),
        ("POST", "/api/phone/pair", (("POST", "/api/phone/pair"), {})),
        ("DELETE", "/api/items/itm_1", None),
        ("GET", "/api/settings", None),
        ("GET", "/api/nothing-here", None),
    ],
)
def test_a_phone_request_names_its_operation_and_parameters(
    method: str, path: str, expected: tuple[scope.Operation, dict[str, str]] | None
) -> None:
    assert scope.match(method, path) == expected


def test_a_refusal_answers_with_its_code_s_status() -> None:
    from ordnung.phone import PhoneRefusal

    refused = PhoneRefusal("too_many", "Wait a minute.", retry_after=60)
    assert (refused.status, refused.body(), refused.headers()) == (
        429,
        {"detail": "Wait a minute.", "code": "too_many"},
        {"Retry-After": "60"},
    )
    assert PhoneRefusal("computer_only", "x").headers() is None
