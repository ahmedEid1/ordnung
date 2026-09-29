"""Write the static demo's My numbers and weekly session from Ordnung's own code.

The hosted demo runs on hand-written mocks without the backend (``web/src/mocks``). What its My numbers
page and weekly session show must still be what the real app computes for the same letters, with the
same ids, so this script reads the mock world (``web/scripts/mock-world.mjs``, the mock database as it
starts), files it in a throw-away ledger and runs :func:`ordnung.views.my_numbers` and
:func:`ordnung.views.weekly_session` for the mock demo's today — with every day to act the session's
ending chooses from (:func:`ordnung.secretary.week.deadlines`), so the demo can end on the next one
when the visitor pays or closes the first. Run it after changing
:mod:`ordnung.numbers`, :mod:`ordnung.secretary.week` or the mock letters::

    .venv/bin/python scripts/gen_mock_numbers.py > web/src/mocks/data/numbers.ts
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

from ordnung import clock
from ordnung.config import Paths
from ordnung.db.store import Store
from ordnung.drafts.proof import followup_item_id
from ordnung.models import CallNote, Case, Contract, Document, Draft, Item, Party, Proof
from ordnung.secretary.brief import build_agenda
from ordnung.secretary.triggers import Ledger
from ordnung.secretary.week import deadlines
from ordnung.views import my_numbers, weekly_session

ROOT = Path(__file__).resolve().parents[1]
WORLD_SCRIPT = ROOT / "web" / "scripts" / "mock-world.mjs"
#: Document fields ``add_document`` takes; the rest are written by ``update_document``.
_ADD_FIELDS = {
    "id",
    "sha256",
    "filename",
    "mime",
    "pages",
    "source",
    "direction",
    "received_date",
    "status",
    "ai_private",
}
_STAMPS = {"created_at", "updated_at"}


def mock_world() -> dict[str, Any]:
    """The mock database as the static demo starts it (JSON from ``mock-world.mjs``)."""
    out = subprocess.run(["node", str(WORLD_SCRIPT)], capture_output=True, text=True, check=True, cwd=ROOT)
    world: dict[str, Any] = json.loads(out.stdout)
    return world


def _sha(document: Document) -> str:
    return hashlib.sha256(document.id.encode()).hexdigest()


def followup_ids(world: dict[str, Any]) -> dict[str, str]:
    """The mock world's follow-up to-do of each sent letter (``followupIdFor`` in
    ``web/src/mocks/data/proof.ts``) → the id Ordnung gives it (:func:`ordnung.drafts.proof.followup_item_id`):
    filed under Ordnung's id, so the Waiting for step finds it, and written back with the mock's."""
    items = {raw["id"] for raw in world["items"]}
    found: dict[str, str] = {}
    for raw in world["drafts"]:
        draft_id = raw["id"]
        mock = (
            "itm_followup_wohnbau"
            if draft_id == "drf_wohnbau"
            else f"itm_followup_{draft_id.removeprefix('drf_')}"
        )
        if raw.get("status") == "sent" and mock in items:
            found[mock] = followup_item_id(draft_id)
    return found


def _renamed(value: Any, names: dict[str, str]) -> Any:
    """``value`` (JSON) with every string that is a key of ``names`` replaced by its value."""
    if isinstance(value, dict):
        return {key: _renamed(inner, names) for key, inner in value.items()}
    if isinstance(value, list):
        return [_renamed(inner, names) for inner in value]
    return names.get(value, value) if isinstance(value, str) else value


def file_world(store: Store, world: dict[str, Any]) -> date:
    """File the mock world in ``store``; returns its today."""
    store.save_profile(world["profile"])
    for raw in world["parties"]:
        store.add_party(**Party.model_validate(raw).model_dump())
    for raw in world["cases"]:
        store.add_case(**Case.model_validate(raw).model_dump())
    for raw in world["documents"]:
        doc = Document.model_validate(raw)
        fields = doc.model_dump()
        store.add_document(
            **{key: fields[key] for key in _ADD_FIELDS - {"sha256"}},
            sha256=_sha(doc),
            file_path=f"files/{doc.id}",
        )
        store.update_document(doc.id, **{k: v for k, v in fields.items() if k not in _ADD_FIELDS | _STAMPS})
        with store.tx() as conn:  # the day each letter entered Ordnung ("new since your last session")
            conn.execute("UPDATE documents SET created_at = ? WHERE id = ?", (doc.created_at, doc.id))
    for raw in world["contracts"]:
        store.add_contract(
            **Contract.model_validate(raw).model_dump(
                exclude={"cancellable", "cancel_hint", "cancellation_sent"}
            )
        )
    known = {
        "party_id": {p["id"] for p in world["parties"]},
        "case_id": {c["id"] for c in world["cases"]},
        "doc_id": {d["id"] for d in world["documents"]},
        "contract_id": {c["id"] for c in world["contracts"]},
    }
    followups = followup_ids(world)
    for raw in world["items"]:
        item = Item.model_validate(raw).model_dump()
        item["id"] = followups.get(item["id"], item["id"])
        # a link to a record the mock world leaves out (a New-mail letter's party) is dropped
        store.add_item(**{k: (v if k not in known or v in known[k] else None) for k, v in item.items()})
    for raw in world["drafts"]:
        draft = Draft.model_validate(raw).model_dump()
        store.add_draft(**{k: (v if k not in known or v in known[k] else None) for k, v in draft.items()})
    # the Post and Waiting for steps read a letter's proofs and the promises noted on the phone
    for raw in world.get("proofs", []):
        store.add_proof(**Proof.model_validate(raw).model_dump())
    for raw in world.get("calls", []):
        call = CallNote.model_validate(raw).model_dump()
        store.add_call_note(**{k: (v if k not in known or v in known[k] else None) for k, v in call.items()})
    return date.fromisoformat(world["today"])


def main() -> None:
    world = mock_world()
    with tempfile.TemporaryDirectory() as tmp:
        store = Store.open(Paths(Path(tmp)).ensure())
        try:
            today = file_world(store, world)
            clock.set_today(today)
            numbers = my_numbers(store, today).model_dump(mode="json")
            week = weekly_session(store, today).model_dump(mode="json")
            # the ending needs no to-do behind a row (Pay and Confirm do, in the steps)
            ahead = [
                row.model_copy(update={"item": None}).model_dump(mode="json")
                for row in deadlines(Ledger(store, today), build_agenda(store, today))
            ]
        finally:
            clock.set_today(None)
            store.close()
    back = {ours: mock for mock, ours in followup_ids(world).items()}
    back |= {f"item:{ours}": f"item:{mock}" for ours, mock in list(back.items())}
    numbers, week, ahead = _renamed(numbers, back), _renamed(week, back), _renamed(ahead, back)

    def dump(value: object) -> str:
        return json.dumps(value, ensure_ascii=False, indent=2)

    print(
        "// Generated by scripts/gen_mock_numbers.py from Ordnung's own code over the mock letters — do not"
    )
    print("// edit by hand (web/scripts/mock-world.mjs gives it the letters of src/mocks/db.ts).")
    print('import type { MyNumbers, WeekEntry, WeeklySession } from "@/api/types";')
    print()
    print("/** `GET /api/numbers` for the mock demo's letters, as the real app computes it. */")
    print(f"export const MOCK_NUMBERS: MyNumbers = {dump(numbers)};")
    print()
    print("/** `GET /api/week` for the mock demo's letters on its today, before any session. */")
    print(f"export const MOCK_WEEK: WeeklySession = {dump(week)};")
    print()
    print(
        "/** Every day to act from the demo's today on, the earliest first (`week.deadlines`): the ending's"
    )
    print(" * candidates, so it moves on to the next one when the visitor pays or closes the first. */")
    print(f"export const MOCK_WEEK_DEADLINES: WeekEntry[] = {dump(ahead)};")


if __name__ == "__main__":
    sys.exit(main())
