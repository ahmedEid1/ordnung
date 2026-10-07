"""What a paired phone may do: the allow-list, checked before routing (policy: :mod:`ordnung.phone`).

Every API operation is in exactly one of :data:`PHONE_ROUTES` and :data:`COMPUTER_ONLY` (a test makes
a new route a deliberate decision). :data:`NEVER_ON_PHONE` is part of :data:`COMPUTER_ONLY`, with the
reason each stays on the computer; a test keeps it apart from :data:`PHONE_ROUTES`, so moving one of
them by mistake fails loudly.

:func:`classify` matches a request against the OpenAPI templates (``starlette.routing.compile_path``,
HEAD counting as GET) before any route runs: a request that matches no template is ``"unknown"`` and
refused, and one that matches several (``/api/items/x.ics`` matches ``{item_id}`` and
``{item_id}.ics``) is a phone request only when every match is. :func:`mark_openapi` adds
``"x-ordnung-phone": true`` to each phone operation of the schema, so the web app's tests and mocks
read the same list.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any, Literal

from starlette.routing import compile_path

#: ``(METHOD, OpenAPI path template)``.
Operation = tuple[str, str]
Classification = Literal["phone", "computer", "unknown"]

#: The OpenAPI extension that marks an operation a paired phone may call.
OPENAPI_MARK = "x-ordnung-phone"


def _operations(lines: str) -> tuple[Operation, ...]:
    found: list[Operation] = []
    for line in lines.strip().splitlines():
        method, path = line.split()
        found.append((method, path))
    return tuple(found)


_PHONE = _operations(
    """
    GET /api/health
    GET /api/rules
    GET /api/jobs
    GET /api/events
    GET /api/profile
    GET /api/documents
    POST /api/documents
    GET /api/documents/{doc_id}
    PATCH /api/documents/{doc_id}
    POST /api/documents/{doc_id}/reprocess
    GET /api/documents/{doc_id}/pages/{page}.jpg
    GET /api/documents/{doc_id}/thumbnail.jpg
    GET /api/documents/{doc_id}/trace
    GET /api/documents/{doc_id}/trace/compare
    GET /api/items
    POST /api/items
    GET /api/items/{item_id}
    PATCH /api/items/{item_id}
    POST /api/items/{item_id}/confirm
    POST /api/items/{item_id}/girocode/confirm
    GET /api/contracts
    PATCH /api/contracts/{contract_id}
    GET /api/parties
    GET /api/parties/{party_id}
    PATCH /api/parties/{party_id}
    GET /api/cases/{case_id}
    GET /api/dashboard
    GET /api/timeline
    GET /api/lanes
    GET /api/numbers
    GET /api/week
    POST /api/week/done
    POST /api/week/dismiss
    GET /api/suggestions
    PATCH /api/suggestions/{suggestion_id}
    GET /api/brief
    POST /api/brief
    POST /api/ask
    GET /api/chat/{thread_id}
    GET /api/drafts
    POST /api/drafts
    GET /api/drafts/{draft_id}
    PATCH /api/drafts/{draft_id}
    POST /api/drafts/{draft_id}/translate
    GET /api/drafts/{draft_id}/preview.png
    POST /api/drafts/{draft_id}/sent
    GET /api/drafts/{draft_id}/proof
    PUT /api/drafts/{draft_id}/tracking
    POST /api/drafts/{draft_id}/proofs
    PATCH /api/drafts/{draft_id}/proofs/{proof_id}
    POST /api/drafts/{draft_id}/answered
    DELETE /api/drafts/{draft_id}/answered
    GET /api/waiting
    GET /api/calls
    POST /api/calls
    PATCH /api/calls/{call_id}
    POST /api/phone/pair
    """
)
"""System and live updates, reading the profile, letters received (upload, correct, read again, page
images), to-dos, records, the overview, Ideas and the daily note, Ask, letters you write (including
"answered" and its undo, which deletes no data), waiting and calls, and pairing itself — the only
operation a phone reaches before it is paired. ``GET /api/health`` with ``probe`` is refused by the
gate. The calendar files (``.ics``) are computer-only: they are a copy of the records (to-dos, amounts,
what to do) that a phone would keep in its Downloads."""

#: Operations that stay on the computer, and why. Every one is in :data:`COMPUTER_ONLY`.
NEVER_ON_PHONE: dict[Operation, str] = {
    ("GET", "/api/settings"): "settings",
    ("PUT", "/api/settings"): "settings",
    ("PUT", "/api/profile"): "profile edits",
    ("POST", "/api/onboarding"): "profile edits",
    ("GET", "/api/phone"): "phone access",
    ("PUT", "/api/phone"): "phone access",
    ("POST", "/api/phone/pairing"): "phone access",
    ("DELETE", "/api/phone/pairing"): "phone access",
    ("DELETE", "/api/phone/devices/{device_id}"): "phone access",
    ("POST", "/api/phone/reset"): "phone access",
    ("GET", "/api/backup"): "backups",
    ("POST", "/api/backup"): "backups",
    ("DELETE", "/api/data"): "deleting",
    ("DELETE", "/api/documents/{doc_id}"): "deleting",
    ("DELETE", "/api/items/{item_id}"): "deleting",
    ("DELETE", "/api/drafts/{draft_id}"): "deleting",
    ("DELETE", "/api/drafts/{draft_id}/proofs/{proof_id}"): "deleting",
    ("DELETE", "/api/calls/{call_id}"): "deleting",
    ("GET", "/api/documents/{doc_id}/file"): "originals leave the computer",
    ("GET", "/api/calendar.ics"): "records leave the computer",
    ("GET", "/api/items/{item_id}.ics"): "records leave the computer",
    ("POST", "/api/documents/held/read"): "held-letter decisions",
    ("POST", "/api/documents/held/keep-private"): "held-letter decisions",
    ("POST", "/api/documents/held/wait"): "held-letter decisions",
    ("GET", "/api/sync"): "hand-off sync",
    ("PUT", "/api/sync"): "hand-off sync",
    ("PATCH", "/api/sync"): "hand-off sync",
    ("DELETE", "/api/sync"): "hand-off sync",
    ("POST", "/api/sync/inspect"): "hand-off sync",
    ("POST", "/api/sync/use-here"): "hand-off sync",
    ("POST", "/api/sync/choose"): "hand-off sync",
    ("POST", "/api/sync/save"): "hand-off sync",
    ("POST", "/api/sync/passphrase"): "hand-off sync",
    ("POST", "/api/sync/refill"): "hand-off sync",
    ("DELETE", "/api/sync/computers/{key}"): "hand-off sync",
    ("GET", "/api/sync/kept/{name}"): "hand-off sync",
    ("DELETE", "/api/sync/kept/{name}"): "hand-off sync",
}

_COMPUTER = _operations(
    """
    GET /api/settings
    PUT /api/settings
    PUT /api/profile
    POST /api/onboarding
    GET /api/phone
    PUT /api/phone
    POST /api/phone/pairing
    DELETE /api/phone/pairing
    DELETE /api/phone/devices/{device_id}
    POST /api/phone/reset
    GET /api/backup
    POST /api/backup
    DELETE /api/data
    DELETE /api/documents/{doc_id}
    DELETE /api/items/{item_id}
    DELETE /api/drafts/{draft_id}
    DELETE /api/drafts/{draft_id}/proofs/{proof_id}
    DELETE /api/calls/{call_id}
    GET /api/documents/{doc_id}/file
    GET /api/drafts/{draft_id}/pdf
    GET /api/drafts/{draft_id}/proof.pdf
    GET /api/calendar.ics
    GET /api/items/{item_id}.ics
    POST /api/calendar/exported
    GET /api/traces
    GET /api/folder
    POST /api/documents/held/read
    POST /api/documents/held/keep-private
    POST /api/documents/held/wait
    GET /api/calendar/sync
    PUT /api/calendar/sync
    GET /api/calendar/sync/preview
    POST /api/calendar/sync/discover
    POST /api/calendar/sync/run
    POST /api/calendar/sync/disconnect
    GET /api/reminders/desktop
    POST /api/reminders/desktop/test
    GET /api/activity
    GET /api/usage
    POST /api/suggestions/review
    GET /api/demo/tour
    PATCH /api/demo/tour
    GET /api/demo/questions
    GET /api/demo/mail
    POST /api/demo/mail
    GET /api/sync
    PUT /api/sync
    PATCH /api/sync
    DELETE /api/sync
    POST /api/sync/inspect
    POST /api/sync/use-here
    POST /api/sync/choose
    POST /api/sync/save
    POST /api/sync/passphrase
    POST /api/sync/refill
    DELETE /api/sync/computers/{key}
    GET /api/sync/kept/{name}
    DELETE /api/sync/kept/{name}
    """
)
"""Admin settings and profile edits, phone access and its devices, backups, deleting data, files and
records that would leave the computer (originals, generated PDFs, the calendar files and the note that
they were downloaded, traces), the watched folder and held
letters (privacy decisions), calendar sync (its password is in the computer's keyring), desktop
notifications (they appear on the computer), the privacy log and usage, the Ideas review (background
model work no phone waits for), the demo, and hand-off sync between computers (the passphrase lives in
this computer's keyring, and taking over replaces the data). ``/api/openapi.json`` and any unknown
``/api`` path are refused as ``"unknown"``."""

PHONE_ROUTES: frozenset[Operation] = frozenset(_PHONE)
COMPUTER_ONLY: frozenset[Operation] = frozenset(_COMPUTER)

#: What a phone's change says in the privacy log (“Changed a to-do on Anna's iPhone”): every phone
#: operation that isn't a GET, except :data:`NOT_CHANGES`.
CHANGE_LABELS: dict[Operation, str] = {
    ("POST", "/api/documents"): "Added letters",
    ("PATCH", "/api/documents/{doc_id}"): "Corrected a letter",
    ("POST", "/api/documents/{doc_id}/reprocess"): "Had a letter read again",
    ("POST", "/api/items"): "Added a to-do",
    ("PATCH", "/api/items/{item_id}"): "Changed a to-do",
    ("POST", "/api/items/{item_id}/confirm"): "Confirmed a to-do's date",
    ("POST", "/api/items/{item_id}/girocode/confirm"): "Confirmed payment details against the letter",
    ("PATCH", "/api/contracts/{contract_id}"): "Changed a contract",
    ("PATCH", "/api/parties/{party_id}"): "Changed a sender's details",
    ("POST", "/api/week/done"): "Finished the weekly session",
    ("POST", "/api/week/dismiss"): "Put off the weekly session",
    ("PATCH", "/api/suggestions/{suggestion_id}"): "Answered an Idea",
    ("POST", "/api/brief"): "Made the daily note",
    ("POST", "/api/drafts"): "Started a letter",
    ("PATCH", "/api/drafts/{draft_id}"): "Edited a letter",
    ("POST", "/api/drafts/{draft_id}/translate"): "Translated a letter",
    ("POST", "/api/drafts/{draft_id}/sent"): "Marked a letter as sent",
    ("PUT", "/api/drafts/{draft_id}/tracking"): "Added a letter's tracking number",
    ("POST", "/api/drafts/{draft_id}/proofs"): "Added proof of sending",
    ("PATCH", "/api/drafts/{draft_id}/proofs/{proof_id}"): "Changed proof of sending",
    ("POST", "/api/drafts/{draft_id}/answered"): "Marked a letter as answered",
    ("DELETE", "/api/drafts/{draft_id}/answered"): "Took back “answered” on a letter",
    ("POST", "/api/calls"): "Noted a call",
    ("PATCH", "/api/calls/{call_id}"): "Changed a call note",
}
#: Phone operations that change nothing of the ledger: a question to Ask (it has its own entry) and
#: pairing itself (``phone.paired``).
NOT_CHANGES: frozenset[Operation] = frozenset({("POST", "/api/ask"), ("POST", "/api/phone/pair")})
#: Phone operations each phone may do only so often an hour (``ordnung.phone.access.DEVICE_LIMITS``).
LIMITED: dict[Operation, str] = {
    ("POST", "/api/ask"): "ask",
    ("POST", "/api/documents/{doc_id}/reprocess"): "model",
    ("POST", "/api/drafts/{draft_id}/translate"): "model",
    ("POST", "/api/drafts"): "model",
    ("POST", "/api/brief"): "model",
    ("POST", "/api/documents"): "upload",
    ("POST", "/api/drafts/{draft_id}/proofs"): "upload",
}
#: Live streams (ended at once when the phone is removed) and uploads (told the phone went away);
#: every other request finishes.
STREAMS: dict[Operation, Literal["events", "ask"]] = {
    ("GET", "/api/events"): "events",
    ("POST", "/api/ask"): "ask",
}
UPLOADS: frozenset[Operation] = frozenset(
    {("POST", "/api/documents"), ("POST", "/api/drafts/{draft_id}/proofs")}
)

_COMPILED: tuple[tuple[str, re.Pattern[str], bool], ...] = tuple(
    (method, compile_path(path)[0], (method, path) in PHONE_ROUTES)
    for method, path in sorted(PHONE_ROUTES | COMPUTER_ONLY)
)
# for :func:`match`: a template without an extension first (``{item_id}`` before ``{item_id}.ics``)
_PHONE_TEMPLATES: tuple[tuple[str, re.Pattern[str], str], ...] = tuple(
    (method, compile_path(path)[0], path)
    for method, path in sorted(PHONE_ROUTES, key=lambda op: ("." in op[1], op))
)


def _wanted(method: str) -> str:
    return "GET" if method.upper() == "HEAD" else method.upper()


def classify(method: str, path: str) -> Classification:
    """Whether a request for ``path`` (an ``/api`` path as routed, without the query) is a phone
    operation, a computer-only one, or matches no operation at all (refused on a phone too)."""
    wanted = _wanted(method)
    found = [phone for verb, pattern, phone in _COMPILED if verb == wanted and pattern.match(path)]
    if not found:
        return "unknown"
    return "phone" if all(found) else "computer"


def match(method: str, path: str) -> tuple[Operation, dict[str, str]] | None:
    """The phone operation a request is, with its path parameters (``None``: not a phone operation).
    When two templates match, the one without an extension wins (``{item_id}`` over ``{item_id}.ics``)."""
    if classify(method, path) != "phone":
        return None
    wanted = _wanted(method)
    for verb, pattern, template in _PHONE_TEMPLATES:
        found = pattern.match(path) if verb == wanted else None
        if found:
            return (verb, template), {key: str(value) for key, value in found.groupdict().items()}
    return None


def schema_operations(schema: dict[str, Any]) -> set[Operation]:
    """Every operation of an OpenAPI schema as ``(METHOD, template)``."""
    methods = {"get", "put", "post", "delete", "patch", "head", "options", "trace"}
    return {
        (method.upper(), path)
        for path, operations in schema.get("paths", {}).items()
        for method in operations
        if method in methods
    }


def mark_openapi(schema: dict[str, Any], phone: Iterable[Operation] = PHONE_ROUTES) -> None:
    """Add ``"x-ordnung-phone": true`` to each phone operation of ``schema`` (in place)."""
    paths = schema.get("paths", {})
    for method, path in phone:
        operation = paths.get(path, {}).get(method.lower())
        if operation is not None:
            operation[OPENAPI_MARK] = True
