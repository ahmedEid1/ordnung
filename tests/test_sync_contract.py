"""Hand-off sync's contract (wave 0): the refusal codes, what travels and what stays, the key file's
scrypt, the new folder's passphrase rule, kept-copy names, the gate's lists and a status that reads no
secret. The packages that build sync on it keep these true."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, get_args

import pytest

from fake_caldav import MemorySecrets
from ordnung import sync
from ordnung.api.app import openapi_schema
from ordnung.api.routes import sync as sync_routes
from ordnung.backup.container import MAX_SCRYPT_BYTES, KdfParams
from ordnung.models import AppSettings
from ordnung.phone import scope
from test_api_support import api_for


class _NeverRead(MemorySecrets):
    """A password store the status must never read from."""

    def get(self, account: str) -> str | None:
        raise AssertionError("the status read the password store")


def test_every_refusal_code_has_its_status() -> None:
    assert set(sync.ERROR_STATUS) == set(get_args(sync.SyncErrorKind))
    assert set(sync.ERROR_STATUS.values()) == {404, 409, 422, 507}
    assert sync.ERROR_STATUS["standby"] == 409
    assert sync.ERROR_STATUS["no_space"] == 507
    refused = sync.WrongSyncPassphrase()
    assert (refused.status, refused.body()["code"]) == (422, "wrong_passphrase")
    assert isinstance(refused, sync.SyncError)
    assert sync.SyncRefused().kind == "unavailable"


def test_what_travels_and_what_stays_are_apart() -> None:
    groups = (sync.LOCAL_META, sync.MERGED_META, sync.DEMO_META, sync.SYNCED_META)
    for index, group in enumerate(groups):
        for other in groups[index + 1 :]:
            assert not group & other
    assert {"phone_access", "calendar_sync", "sync_mark", "sync_person", "inbox_seen"} <= sync.LOCAL_META
    assert sync.MERGED_META == {"own_pdfs", "folder_taken"} == set(sync.MERGED_META_MAX)
    local, synced = set(sync.LOCAL_SETTINGS), set(sync.SYNCED_SETTINGS)
    assert not local & synced
    assert local | synced == set(AppSettings.model_fields), "decide which side a new settings field is on"
    assert sync.SYNCED_DIRS == ("files", "derived", "drafts")


def test_the_keys_other_modules_name_are_the_contract_s() -> None:
    """The store and the watched folder can't import ``ordnung.sync`` (it imports them): their own
    names for the person counter and the watched folder's memory are pinned here."""
    from ordnung.db import store
    from ordnung.ingest import watcher

    assert store.PERSON_META_KEY == sync.PERSON_META_KEY
    assert (watcher.FOLDER_TAKEN_META_KEY, watcher.FOLDER_TAKEN_MAX) == (
        sync.FOLDER_TAKEN_META_KEY,
        sync.FOLDER_TAKEN_MAX,
    )
    assert sync.INTERRUPTIONS_META_KEY == store._INTERRUPTIONS_KEY


def test_the_key_file_takes_256_mib_of_scrypt() -> None:
    assert sync.SYNC_KDF == KdfParams(log2_n=18, r=8, p=1)
    assert sync.SYNC_KDF.memory == 256 * 1024 * 1024 == MAX_SCRYPT_BYTES
    sync.SYNC_KDF.check()  # a reader accepts it


@pytest.mark.parametrize(
    ("passphrase", "bits", "accepted"),
    [
        ("aqua-blunt-clay-dove-erupt", 70.0, True),  # five words: the suggestion's shape
        ("CorrectHorseBatteryStapleDoor", 70.0, True),  # camel case is five words too
        ("correct horse battery staple", 56.0, False),  # four
        ("password password password password password", 14.0, False),  # a repeated word counts once
        ("xkqmzvtpwbrnyhdflcga", 14.0, False),  # one run of letters is at best one word
        ("Sommer 2025 Urlaub Sommer", 28 + 4 * math.log2(10), False),  # four digits: about 13 bits
    ],
)
def test_a_new_folder_s_passphrase_needs_about_70_bits(passphrase: str, bits: float, accepted: bool) -> None:
    assert sync.passphrase_bits(passphrase) == pytest.approx(bits)
    problem = sync.passphrase_problem(passphrase)
    assert (problem is None) is accepted
    if not accepted:
        assert passphrase not in (problem or "")


def test_passphrase_tokens_and_the_length_rule() -> None:
    assert sync.passphrase_tokens("Sommer2025Urlaub!grün") == ["Sommer", "2025", "Urlaub", "grün"]
    assert sync.passphrase_problem("a b c d e") is not None  # shorter than the backup rule's 12
    assert sync.passphrase_problem("x" * 1025) is not None
    assert sync.MIN_PASSPHRASE_BITS == sync.SUGGESTED_WORDS * sync.TOKEN_BITS_MAX


@pytest.mark.parametrize(
    ("name", "kept"),
    [
        ("ordnung-kept-2026-10-07-0912.ordnung-backup", True),
        ("ordnung-kept-2026-10-07-0912-2.ordnung-backup", True),
        ("ordnung-kept-2026-10-07-0912.ordnung-backup.part", False),
        ("../ordnung-kept-2026-10-07-0912.ordnung-backup", False),
        ("ordnung-backup-2026-10-07.ordnung-backup", False),
        ("ordnung-kept-2026-10-07-0912.ordnung-backup\n", False),
        ("ordnung-kept-٢٠٢٦-10-07-0912.ordnung-backup", False),
    ],
)
def test_kept_copy_names(name: str, kept: bool) -> None:
    assert bool(sync.KEPT_RE.fullmatch(name)) is kept


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    return openapi_schema()


def test_the_gate_s_lists_name_real_operations(schema: dict[str, Any]) -> None:
    operations = scope.schema_operations(schema)
    assert sync.ALLOWED_IN_STANDBY <= sync.NOT_PERSON_CHANGES <= operations
    own = {operation for operation in operations if operation[1].split("/")[:3] == ["", "api", "sync"]}
    assert len(own) == 13
    assert own <= scope.COMPUTER_ONLY
    assert all(scope.NEVER_ON_PHONE[operation] == "hand-off sync" for operation in own)


async def test_the_status_reads_no_secret_and_the_demo_never_syncs(data_dir: Path) -> None:
    from sync_fake_engine import FakeEngine  # until the sync engine is part of this branch

    async with api_for(data_dir) as api:
        api.app.state.ordnung.sync.engine = FakeEngine()
        api.app.dependency_overrides[sync_routes.get_secrets] = lambda: _NeverRead()
        status = (await api.client.get("/api/sync")).json()
        assert (status["available"], status["connected"], status["mode"]) == (True, False, "off")
        assert 0 < len(status["suggested_name"]) <= sync.NAME_MAX_CHARS
    async with api_for(data_dir, demo=True) as api:
        api.app.dependency_overrides[sync_routes.get_secrets] = lambda: _NeverRead()
        status = (await api.client.get("/api/sync")).json()
        assert (status["available"], status["unavailable"]) == (False, sync.DEMO_MESSAGE)
        refused = await api.client.post("/api/sync/use-here", json={})
        assert refused.status_code == 409 and refused.json()["code"] == "unavailable"
