"""A child process for ``test_sync_pull_process.py``: it takes Ordnung over on one computer (a pull) and
is killed at a random moment by the test. Arguments: the computer's root, its sync folder, its machine id;
the passphrase comes in ``ORDNUNG_SYNC_PASSPHRASE``."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from fakes import MemorySecrets, use_fast_keys
from ordnung.config import Paths
from ordnung.db.store import Store
from ordnung.sync.engine import Session, resume_interrupted
from ordnung.sync.local import keyring_account, load_state


def main() -> None:
    root, machine = Path(sys.argv[1]), sys.argv[2]
    patch = pytest.MonkeyPatch()
    use_fast_keys(patch)
    paths = Paths(root / "data")
    resume_interrupted(paths)
    state = load_state(paths)
    assert state is not None
    secrets = MemorySecrets()
    secrets.set(keyring_account(state.computer), os.environ["ORDNUNG_SYNC_PASSPHRASE"])
    store = Store.open(paths)
    session = Session.open(paths, secrets, machine=lambda: machine)
    session.start(store)
    print("ready", flush=True)
    session.use_here(store)
    print("done", flush=True)


if __name__ == "__main__":
    main()
