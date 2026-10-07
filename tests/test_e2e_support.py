"""What the end-to-end tests rely on outside the app: the password store the real servers load for hand-off sync
(``tests/e2e_support/e2e_keyring.py``), and the copies of the server's sentences and of the sync folder's names
that the Playwright specs keep (``web/e2e/``) — so a change to Ordnung fails here, not only in the e2e job.
"""

from __future__ import annotations

import importlib
import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import keyring
import pytest

import ordnung
from ordnung import sync
from ordnung.calendar.secrets import KeyringSecrets, backend_problem

ROOT = Path(__file__).resolve().parents[1]
SUPPORT = ROOT / "tests" / "e2e_support"
E2E = ROOT / "web" / "e2e"


def _e2e_keyring() -> ModuleType:
    if str(SUPPORT) not in sys.path:
        sys.path.insert(0, str(SUPPORT))
    return importlib.import_module("e2e_keyring")


def test_the_e2e_password_store_passes_the_keyring_policy_and_keeps_secrets_in_its_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    previous = keyring.get_keyring()  # the default is chosen before the e2e store is viable
    module = _e2e_keyring()
    file = tmp_path / "keyring.json"
    monkeypatch.setenv(module.FILE_ENV, str(file))
    keyring.set_keyring(module.FileKeyring())
    try:
        secrets = KeyringSecrets()
        assert secrets.problem() is None
        assert backend_problem(keyring.get_keyring()) is None
        secrets.set("computer:abc", "orbit velvet canyon maple thunder")
        assert secrets.get("computer:abc") == "orbit velvet canyon maple thunder"
        if os.name == "posix":
            assert stat.S_IMODE(file.stat().st_mode) == 0o600
        secrets.delete("computer:abc")
        secrets.delete("computer:abc")  # nothing there: no error, as with a real store
        assert secrets.get("computer:abc") is None
    finally:
        keyring.set_keyring(previous)


def test_without_its_file_the_e2e_password_store_is_never_used(monkeypatch: pytest.MonkeyPatch) -> None:
    """Imported into a process without ``ORDNUNG_E2E_KEYRING_FILE`` (this one), it isn't viable, so ``keyring``
    never picks it by itself; and Ordnung refuses it."""
    module = _e2e_keyring()
    monkeypatch.delenv(module.FILE_ENV, raising=False)
    assert not module.FileKeyring.viable
    assert backend_problem(module.FileKeyring()) is not None


def test_a_real_server_s_environment_loads_the_e2e_password_store(tmp_path: Path) -> None:
    """``web/playwright.config.ts`` starts each real app with these variables (``keyringEnv`` in
    ``web/e2e/env.ts``): sync is then available on a computer without a desktop keyring."""
    env = {
        **os.environ,
        "PYTHON_KEYRING_BACKEND": "e2e_keyring.FileKeyring",
        "PYTHONPATH": os.pathsep.join([str(SUPPORT), str(Path(ordnung.__file__).parents[1])]),
        "ORDNUNG_E2E_KEYRING_FILE": str(tmp_path / "keyring.json"),
    }
    script = (
        "from ordnung.calendar.secrets import KeyringSecrets\n"
        "s = KeyringSecrets()\n"
        "assert s.problem() is None, s.problem()\n"
        "s.set('computer:e2e', 'secret words')\n"
        "assert s.get('computer:e2e') == 'secret words'\n"
    )
    subprocess.run([sys.executable, "-c", script], env=env, check=True, timeout=60)
    env_ts = (E2E / "env.ts").read_text(encoding="utf-8")
    assert 'KEYRING_BACKEND = "e2e_keyring.FileKeyring"' in env_ts
    assert 'KEYRING_FILE_ENV = "ORDNUNG_E2E_KEYRING_FILE"' in env_ts
    assert 'join(REPO_DIR, "tests", "e2e_support")' in env_ts


def test_the_e2e_specs_quote_the_server_s_sync_sentences_exactly() -> None:
    demo = (E2E / "reminders-backup-layout.spec.ts").read_text(encoding="utf-8")
    assert f'const SYNC_DEMO_MESSAGE = "{sync.DEMO_MESSAGE}";' in demo
    story = (E2E / "real-app-sync.spec.ts").read_text(encoding="utf-8")
    standby = sync.STANDBY_MESSAGE.replace("{name}", "${name}")
    assert f"const STANDBY_MESSAGE = (name: string) => `{standby}`;" in story


def _ordnung_name(path: str) -> bool:
    """Whether ``path`` (relative to the sync folder, with ``/``) is one of Ordnung's names, by
    :mod:`ordnung.sync`'s own patterns (design §4.1)."""
    parts = path.split("/")
    name = parts[-1]
    where_ok = (
        len(parts) == 1
        or (len(parts) == 2 and parts[0] == sync.HEADS_DIR)
        or (len(parts) == 3 and parts[0] == sync.OBJECTS_DIR and bool(sync.SHARD_RE.match(parts[1])))
    )
    if sync.TEMP_RE.match(name):
        return where_ok
    if len(parts) == 1:
        return bool(sync.KEY_FILE_RE.match(name))
    if len(parts) == 2 and parts[0] == sync.HEADS_DIR:
        return bool(sync.HEAD_RE.match(name))
    if len(parts) == 3 and parts[0] == sync.OBJECTS_DIR and sync.SHARD_RE.match(parts[1]):
        return bool(sync.OBJECT_RE.match(name))
    return False


def test_the_e2e_sync_tool_knows_ordnung_s_names_as_ordnung_does() -> None:
    """``web/e2e/sync-tool.ts``'s ``ORDNUNG_NAMES`` (what the e2e privacy check calls Ordnung's) say yes and no
    exactly where :mod:`ordnung.sync`'s name patterns do."""
    source = (E2E / "sync-tool.ts").read_text(encoding="utf-8")
    block = source.split("export const ORDNUNG_NAMES = {", 1)[1].split("} as const;", 1)[0]
    patterns = [
        re.compile(js.replace("\\/", "/").removesuffix("$") + r"\Z")
        for js in re.findall(r"^\s*\w+: /(.+)/,$", block, re.M)
    ]
    assert len(patterns) == 4
    hexes = {n: "0123456789abcdef" * 4 for n in (2, 16, 30, 32)}
    key, head = hexes[32][:32], hexes[32][:32]
    shard, rest, tmp = hexes[2][:2], hexes[30][:30], f".{hexes[16][:16]}.tmp"
    candidates = [
        key,
        key.upper(),
        key[:31],
        key + "0",
        key + "\n",
        f"h/{head}",
        f"h/{head[:31]}",
        f"h/{head} (conflicted copy 2026-10-07)",
        f"h/{head}.sync-conflict-20261007-091200-E2ESYNC",
        f"o/{shard}/{rest}",
        f"o/{shard}/{rest}0",
        f"o/{shard.upper()}/{rest}",
        f"o/{shard}0/{rest}",
        f"o/{rest}",
        f"x/{head}",
        tmp,
        f"h/{tmp}",
        f"o/{shard}/{tmp}",
        f"o/{tmp}",
        f"x/{tmp}",
        f".{hexes[16][:15]}.tmp",
        ".stfolder",
        "desktop.ini",
        ".DS_Store",
        f"h/{head}/x",
    ]
    for path in candidates:
        assert any(p.match(path) for p in patterns) == _ordnung_name(path), path
