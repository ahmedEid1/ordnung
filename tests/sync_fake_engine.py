"""A fake of hand-off sync's engine — the I2 façade of the design (§24.3), as
:class:`ordnung.sync.agent.Engine` names it — for the server, API and command-line tests (no tests here).

It keeps the *protocol* the agent depends on, not the real format: the sync folder holds one JSON file
(:data:`FOLDER_FILE`: the vault, a hash of the passphrase, one head per computer, the versions) and
each version's database and files in plain copies; nothing is encrypted. Lineage is a counter per
computer (the person counter, ``sync_person``, at the time of the save): one version *contains* another
when every computer's counter is at least as high. That is enough for the decisions the agent executes:
in use (``push``, ``become_standby``, ``bring_in``, ``arriving``, ``choice``, ``paused``, ``idle``),
standing by (``up_to_date``, ``arriving``, ``choice``) and "Use Ordnung here" (``nothing``,
``late_push``, ``claim``, ``pull`` with ``keep``, ``wait``, ``choice``).

Hooks for tests: :func:`withhold` / :func:`deliver` mark a version as not arrived / arrived;
:attr:`FakeEngine.hang` makes every folder call block until it is set; :attr:`FakeEngine.fail_push`
makes saves fail; :attr:`FakeEngine.calls` records each call's name; :attr:`FakeEngine.on_apply`
runs inside :meth:`FakeSession.apply` (to prove writes are fenced).

The real engine (``ordnung/sync/engine.py``, package P1) replaces it at integration.
"""

from __future__ import annotations

import hashlib
import json
import secrets as random
import shutil
import sqlite3
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fake_caldav import MemorySecrets
from ordnung import sync
from ordnung.calendar.secrets import SecretStore
from ordnung.config import Paths
from ordnung.db.store import _WRITE_LOCK, PERSON_META_KEY, Store
from ordnung.models import AppSettings
from ordnung.sync.agent import UseHere

FOLDER_FILE = "fake-sync.json"
VERSIONS = "versions"
STATE_FILE = "state.json"
JOURNAL_FILE = "pull.json"
_FOLDER_LOCK = threading.RLock()  # two computers' agents in one test process
_DIGEST_TABLES = ("documents", "items", "contracts", "notes", "chat_messages", "drafts", "parties", "cases")
_PERSON_TABLES = ("documents", "items", "contracts", "drafts", "notes", "chat_messages")
_KEEP_LOCAL = tuple(sorted(sync.LOCAL_META | sync.MERGED_META))


class FolderProblem(sync.SyncError):
    """The folder isn't as it should be (``problem``: the agent's problem code)."""

    def __init__(self, problem: str) -> None:
        super().__init__("folder_problem", f"The sync folder has a problem: {problem}.")
        self.problem = problem


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# --------------------------------------------------------------------------------------------------
# what the agent reads
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class VersionRef:
    id: str
    lineage: tuple[tuple[str, int], ...]


@dataclass
class Summary:
    folder: str
    name: str
    mode: Literal["in_use", "standing_by"]
    in_use_on: str | None
    last_saved_at: str | None
    base_from: str | None
    base_arrived_at: str | None
    notices: list[dict[str, Any]]
    kept: list[dict[str, Any]]
    data_folder_synced: bool
    journal: bool


@dataclass
class Computer:
    key: int
    name: str
    this: bool
    in_use: bool
    state: str
    arrived_at: str | None
    has_latest: bool | None
    app_version: str
    calendar: str


@dataclass
class Problem:
    code: str
    message: str | None = None


@dataclass
class View:
    computers: list[Computer]
    problem: Problem | None
    heads: dict[str, dict[str, Any]] = field(default_factory=dict)
    versions: dict[str, dict[str, Any]] = field(default_factory=dict)
    holder: str | None = None


@dataclass
class Local:
    pending: bool
    person_pending: bool
    computer: str
    mode: str
    base: str | None
    lineage: dict[str, int]
    person_data: int
    keep: str | None
    chosen: bool
    digest: str = ""


@dataclass
class Decision:
    kind: str
    target: VersionRef | None = None
    keep: bool = False
    why: str | None = None
    late_push: bool = False
    may_push: bool = False
    choice: dict[str, Any] | None = None
    arriving: dict[str, Any] | None = None
    problem: Problem | None = None
    from_name: str | None = None


@dataclass
class Connected:
    created: bool
    choice: dict[str, Any] | None = None


@dataclass
class Chosen:
    pull: VersionRef | None
    complete: bool = True
    arriving: dict[str, Any] | None = None
    why: str | None = None
    from_name: str | None = None


@dataclass
class FolderInfo:
    kind: str
    folder: str
    problem: str | None = None
    examples: list[str] = field(default_factory=list)
    data_folder_synced: bool = False
    links_left_out: list[str] = field(default_factory=list)


@dataclass
class Kept:
    name: str


@dataclass
class Staged:
    version: str
    path: Path


# --------------------------------------------------------------------------------------------------
# the folder and this computer's state on disk
# --------------------------------------------------------------------------------------------------


def _folder_data(folder: Path) -> dict[str, Any] | None:
    path = folder / FOLDER_FILE
    return json.loads(path.read_text()) if path.is_file() else None


def _write_atomic(path: Path, text: str) -> None:
    temp = path.with_name(f".{path.name}.{threading.get_ident()}.part")
    temp.write_text(text)
    temp.replace(path)


def _write_folder(folder: Path, data: dict[str, Any]) -> None:
    _write_atomic(folder / FOLDER_FILE, json.dumps(data, indent=1, sort_keys=True))


def _state(paths: Paths) -> dict[str, Any] | None:
    path = paths.sync / STATE_FILE
    return json.loads(path.read_text()) if path.is_file() else None


def _write_state(paths: Paths, state: dict[str, Any]) -> None:
    paths.sync.mkdir(mode=0o700, exist_ok=True)
    _write_atomic(paths.sync / STATE_FILE, json.dumps(state, indent=1, sort_keys=True))


def withhold(folder: Path, version: str | None = None) -> str:
    """Mark a version (default: the newest) as not arrived yet; returns its id."""
    with _FOLDER_LOCK:
        data = _folder_data(folder)
        assert data is not None
        vid = version or max(data["versions"], key=lambda vid: data["versions"][vid]["order"])
        data["versions"][vid]["complete"] = False
        _write_folder(folder, data)
        return vid


def deliver(folder: Path, version: str | None = None) -> None:
    """Mark a version (default: every one) as arrived."""
    with _FOLDER_LOCK:
        data = _folder_data(folder)
        assert data is not None
        for vid, found in data["versions"].items():
            if version is None or vid == version:
                found["complete"] = True
        _write_folder(folder, data)


def head_of(folder: Path, name: str) -> dict[str, Any]:
    """The head of the computer called ``name``."""
    data = _folder_data(folder)
    assert data is not None
    return next(head for head in data["heads"].values() if head["name"] == name)


def set_head(folder: Path, who: str, **values: Any) -> None:
    """Change the head of the computer called ``who``."""
    with _FOLDER_LOCK:
        data = _folder_data(folder)
        assert data is not None
        head = next(head for head in data["heads"].values() if head["name"] == who)
        head.update(values)
        _write_folder(folder, data)


def counter(store: Store) -> int:
    return int(store.get_meta(PERSON_META_KEY) or 0)


def _counter_at(db: Path) -> int:
    conn = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (PERSON_META_KEY,)).fetchone()
    finally:
        conn.close()
    return int(row[0]) if row else 0


def digest_of(db: Path) -> tuple[str, int, list[str]]:
    """The fake's state digest of a database file (synced rows only), its letters and newest titles."""
    conn = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)
    try:
        parts: list[str] = []
        excluded = ",".join("?" * len(_KEEP_LOCAL + tuple(sync.DEMO_META)))
        rows = conn.execute(
            f"SELECT key, value FROM meta WHERE key NOT IN ({excluded}) ORDER BY key",
            (*_KEEP_LOCAL, *sync.DEMO_META),
        ).fetchall()
        parts.append(json.dumps(rows))
        for table in _DIGEST_TABLES:
            parts.append(
                json.dumps(conn.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall(), default=str)
            )
        letters = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        newest = [row[0] for row in conn.execute("SELECT title FROM documents ORDER BY rowid DESC LIMIT 3")]
    finally:
        conn.close()
    return _hash("\n".join(parts)), int(letters), [str(title) for title in newest]


def person_data(db: Path) -> int:
    conn = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)
    try:
        return sum(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in _PERSON_TABLES)
    finally:
        conn.close()


def _contains(a: dict[str, int], b: dict[str, int]) -> bool:
    return all(a.get(computer, 0) >= number for computer, number in b.items())


def _merged(*lineages: dict[str, int]) -> dict[str, int]:
    merged: dict[str, int] = {}
    for lineage in lineages:
        for computer, number in lineage.items():
            merged[computer] = max(merged.get(computer, 0), number)
    return merged


def _ref(vid: str, version: dict[str, Any]) -> VersionRef:
    return VersionRef(vid, tuple(sorted(version["person"].items())))


def _copy_data(source: Path, target: Path) -> None:
    for name in sync.SYNCED_DIRS:
        if (source / name).is_dir():
            if (target / name).exists():
                shutil.rmtree(target / name)
            shutil.copytree(source / name, target / name)


def _snapshot(db: Path, target: Path) -> None:
    source = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)
    copy = sqlite3.connect(target)
    try:
        source.backup(copy)
    finally:
        copy.close()
        source.close()


# --------------------------------------------------------------------------------------------------
# the engine
# --------------------------------------------------------------------------------------------------


class FakeEngine:
    """:class:`ordnung.sync.agent.Engine` for tests (module docstring)."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.hang: threading.Event | None = None
        self.fail_push: BaseException | None = None
        self.on_apply: Callable[[], None] | None = None
        self.resumed = 0
        self.keyrings: dict[Path, MemorySecrets] = {}

    def keyring(self, data_dir: Path) -> MemorySecrets:
        """The password store of the computer whose data folder is ``data_dir``."""
        return self.keyrings.setdefault(Path(data_dir).resolve(), MemorySecrets())

    def _call(self, name: str) -> None:
        self.calls.append(name)
        if self.hang is not None:
            self.hang.wait()

    # ------------------------------------------------------------------------------ keyless

    def local_summary(self, paths: Paths) -> Summary | None:
        state = _state(paths)
        if state is None:
            return None
        data = _folder_data(Path(state["folder"])) or {"heads": {}}
        holder = _holder(data["heads"])
        return Summary(
            folder=state["folder"],
            name=state["name"],
            mode=state["mode"],
            in_use_on=data["heads"][holder]["name"] if holder else None,
            last_saved_at=state.get("last_saved_at"),
            base_from=state.get("base_from"),
            base_arrived_at=state.get("base_arrived_at"),
            notices=list(state.get("notices", [])),
            kept=[
                {**kept, "path": str(paths.sync / sync.KEPT_DIR / kept["name"])}
                for kept in state.get("kept", [])
            ],
            data_folder_synced=False,
            journal=(paths.sync / JOURNAL_FILE).is_file(),
        )

    def writes_refused(self, paths: Paths) -> str | None:
        summary = self.local_summary(paths)
        if summary is None or summary.mode != "standing_by":
            return None
        return f"Ordnung is in use on {summary.in_use_on or 'another computer'}."

    def resume_interrupted(self, paths: Paths) -> None:
        self.resumed += 1

    def inspect_folder(self, value: str, paths: Paths, settings: AppSettings) -> FolderInfo:
        self._call("inspect_folder")
        folder = Path(value).expanduser()
        if not folder.is_absolute():
            return FolderInfo("refused", value, problem="Choose a folder by its full path.")
        if not folder.parent.is_dir():
            return FolderInfo("refused", str(folder), problem="Its parent folder doesn't exist.")
        if folder.exists() and not folder.is_dir():
            return FolderInfo("refused", str(folder), problem="This is a file, not a folder.")
        if folder == paths.data_dir or folder.is_relative_to(paths.data_dir):
            return FolderInfo("refused", str(folder), problem="That is Ordnung's own data folder.")
        names = sorted(entry.name for entry in folder.iterdir()) if folder.is_dir() else []
        if FOLDER_FILE in names:
            return FolderInfo("existing", str(folder))
        others = [name for name in names if name != VERSIONS and not name.startswith(".")]
        if others:
            return FolderInfo(
                "refused", str(folder), problem="This folder has other files in it.", examples=others[:3]
            )
        return FolderInfo("new", str(folder))

    def connect(
        self,
        paths: Paths,
        folder: Path,
        name: str,
        passphrase: str,
        *,
        secrets: SecretStore,
        keep: Literal["this", "folder"] | None,
    ) -> Connected:
        self._call("connect")
        with _FOLDER_LOCK:
            data = _folder_data(folder)
            created = data is None
            computer = random.token_hex(16)
            if data is None:
                folder.mkdir(exist_ok=True)
                data = {
                    "vault": random.token_hex(16),
                    "passphrase": _hash(passphrase),
                    "heads": {},
                    "versions": {},
                }
            elif data["passphrase"] != _hash(passphrase):
                raise sync.WrongSyncPassphrase()
            elif len([h for h in data["heads"].values() if h["state"] != "left"]) >= sync.MAX_COMPUTERS:
                raise sync.SyncError("full", "This folder already serves 8 computers.")
            names = {head["name"] for head in data["heads"].values()}
            shown, n = name, 2
            while shown in names:
                shown, n = f"{name} ({n})", n + 1
            letters = person_data(paths.db) if paths.db.is_file() else 0
            if not created and letters and keep is None:
                return Connected(created=False, choice=self._joining_choice(paths, data, shown))
            key = 1 + max((head["key"] for head in data["heads"].values()), default=0)
            data["heads"][computer] = {
                "key": key,
                "name": shown,
                "state": "in_use" if created else "standing_by",
                "epoch": 1 if created else 0,
                "version": None,
                "has": None,
                "forgotten": [],
                "calendar": "none",
            }
            _write_folder(folder, data)
        secrets.set(sync.KEYRING_ACCOUNT.format(computer=computer), passphrase)
        _write_state(
            paths,
            {
                "folder": str(folder),
                "vault": data["vault"],
                "check": data["passphrase"],
                "computer": computer,
                "name": shown,
                "mode": "in_use" if created else "standing_by",
                "base": None,
                "pushed": 0,
                "seq": 0,
                "keep": keep,
                "notices": [],
                "kept": [],
            },
        )
        return Connected(created=created)

    def _joining_choice(self, paths: Paths, data: dict[str, Any], name: str) -> dict[str, Any]:
        holder = _holder(data["heads"])
        _, letters, newest = digest_of(paths.db)
        sides = [_side(0, name, True, letters, newest, complete=True)]
        if holder is not None and data["heads"][holder]["version"]:
            version = data["versions"][data["heads"][holder]["version"]]
            sides.append(
                _side(
                    data["heads"][holder]["key"],
                    data["heads"][holder]["name"],
                    False,
                    version["letters"],
                    version["newest"],
                    complete=version["complete"],
                )
            )
        return {"joining": True, "sides": sides}

    def open_session(self, paths: Paths, secrets: SecretStore) -> FakeSession:
        self._call("open_session")
        state = _state(paths)
        if state is None:
            raise sync.SyncError("not_connected", sync.NOT_CONNECTED_MESSAGE)
        passphrase = secrets.get(sync.KEYRING_ACCOUNT.format(computer=state["computer"]))
        if passphrase is None:
            raise sync.SyncError("passphrase_needed", "The passphrase isn't in the password store.")
        data = _folder_data(Path(state["folder"]))
        if data is not None and data["passphrase"] != _hash(passphrase):
            raise sync.WrongSyncPassphrase()
        return FakeSession(self, paths)

    def decide(self, local: Local, view: View, action: UseHere | None) -> Decision:
        return _decide(local, view, action)

    def push_once(self, paths: Paths, secrets: SecretStore) -> str:
        try:
            session = self.open_session(paths, secrets)
            with Store.open(paths) as store:
                session.push(store, reason="change")
        except Exception as exc:
            return f"Not saved to the sync folder: {exc}"
        return "Saved to the sync folder."

    def set_passphrase(self, paths: Paths, secrets: SecretStore, passphrase: str) -> None:
        self._call("set_passphrase")
        state = _state(paths)
        assert state is not None
        data = _folder_data(Path(state["folder"]))
        if data is None or data["passphrase"] != _hash(passphrase):
            raise sync.WrongSyncPassphrase()
        secrets.set(sync.KEYRING_ACCOUNT.format(computer=state["computer"]), passphrase)

    def change(
        self,
        paths: Paths,
        *,
        name: str | None = None,
        folder: Path | None = None,
        confirm_same_computer: bool = False,
        abandon_pull: bool = False,
        dismiss_notice: str | None = None,
        notice: tuple[str, str, str | None] | None = None,
    ) -> None:
        self._call("change")
        state = _state(paths)
        assert state is not None
        if name is not None:
            set_head(Path(state["folder"]), state["name"], name=name)
            state["name"] = name
        if folder is not None:
            state["folder"] = str(folder)
        if abandon_pull:
            (paths.sync / JOURNAL_FILE).unlink(missing_ok=True)
            state["mode"] = "standing_by"
        if dismiss_notice is not None:
            state["notices"] = [found for found in state["notices"] if found["id"] != dismiss_notice]
        if notice is not None:
            code, message, kept = notice
            state["notices"].append(
                {"id": random.token_hex(4), "code": code, "message": message, "kept": kept, "at": _now()}
            )
        state["confirmed_same"] = state.get("confirmed_same", False) or confirm_same_computer
        _write_state(paths, state)

    def disconnect(self, paths: Paths, secrets: SecretStore, *, forget_passphrase: bool) -> None:
        self._call("disconnect")
        state = _state(paths)
        if state is None:
            return
        if forget_passphrase:
            secrets.delete(sync.KEYRING_ACCOUNT.format(computer=state["computer"]))
        for entry in paths.sync.iterdir():
            if entry.name == sync.KEPT_DIR:
                continue
            if entry.is_dir():
                shutil.rmtree(entry)
            else:
                entry.unlink()

    def delete_kept(self, paths: Paths, name: str) -> bool:
        state = _state(paths)
        path = paths.sync / sync.KEPT_DIR / name
        if state is None or not path.is_file():
            return False
        path.unlink()
        state["kept"] = [kept for kept in state["kept"] if kept["name"] != name]
        _write_state(paths, state)
        return True


def _side(
    key: int, name: str, this: bool, letters: int, newest: Sequence[str], *, complete: bool
) -> dict[str, Any]:
    return {
        "key": key,
        "computer": name,
        "this": this,
        "letters": letters,
        "added": letters,
        "newest": [{"label": title, "added_on": "2026-10-07"} for title in newest],
        "arrived_at": None,
        "complete": complete,
        "arriving": None if complete else _arriving(name),
    }


def _arriving(name: str) -> dict[str, Any]:
    return {
        "from_computer": name,
        "have": 1,
        "need": 2,
        "have_bytes": 10,
        "need_bytes": 20,
        "since": _now(),
        "stalled": False,
        "online_only": 0,
    }


def _holder(heads: dict[str, dict[str, Any]]) -> str | None:
    live = [
        (head["epoch"], cid) for cid, head in heads.items() if head["state"] != "left" and head["epoch"] > 0
    ]
    return max(live)[1] if live else None


# --------------------------------------------------------------------------------------------------
# the decision (design §9, simplified)
# --------------------------------------------------------------------------------------------------


def _decide(local: Local, view: View, action: UseHere | None) -> Decision:
    if view.problem is not None:
        return Decision("paused", problem=view.problem, may_push=view.problem.code == "newer_ordnung")
    me, heads, versions = local.computer, view.heads, view.versions
    holder = view.holder
    lineage = dict(local.lineage)
    if local.person_pending:
        lineage[me] = lineage.get(me, 0) + 1  # an unknown own change
    others = [
        (cid, head)
        for cid, head in heads.items()
        if cid != me and head["version"] and cid not in heads[me].get("forgotten", [])
    ]
    ahead, diverged, same = [], [], []
    for cid, head in others:
        theirs = versions[head["version"]]["person"]
        if theirs == lineage:
            if versions[head["version"]]["digest"] != local.digest:
                same.append((cid, head))
            continue
        if _contains(lineage, theirs):
            continue
        if _contains(theirs, lineage):
            ahead.append((cid, head))
        else:
            diverged.append((cid, head))

    def target_of(cid: str) -> tuple[VersionRef, dict[str, Any]]:
        vid = heads[cid]["version"]
        return _ref(vid, versions[vid]), versions[vid]

    def choice(joining: bool = False) -> Decision:
        sides = [_side(heads[me]["key"], heads[me]["name"], True, 0, [], complete=True)]
        for cid, head in diverged or ahead:
            _, version = target_of(cid)
            sides.append(
                _side(
                    head["key"],
                    head["name"],
                    False,
                    version["letters"],
                    version["newest"],
                    complete=version["complete"],
                )
            )
        return Decision("choice", choice={"joining": joining, "sides": sides})

    if action is None and local.mode == "in_use":
        if holder is not None and holder != me:
            return Decision("become_standby", late_push=local.person_pending)
        if diverged:
            return Decision("choice", choice=choice().choice)
        if ahead and not local.person_pending:
            cid, head = max(ahead, key=lambda found: found[1]["epoch"])
            target, version = target_of(cid)
            if version["complete"]:
                return Decision("bring_in", target=target, from_name=head["name"])
            return Decision(
                "arriving", target=target, arriving=_arriving(head["name"]), from_name=head["name"]
            )
        return Decision("push") if local.pending else Decision("idle")
    if action is None:  # standing by: report only
        if diverged:
            return choice()
        if holder is not None and holder != me and heads[holder]["version"]:
            target, version = target_of(holder)
            if not version["complete"]:
                return Decision("arriving", target=target, arriving=_arriving(heads[holder]["name"]))
        return Decision("up_to_date")
    # "Use Ordnung here"
    if holder == me and local.mode == "in_use":
        return Decision("nothing")
    if action.older_copy:
        return Decision("claim")
    if local.person_pending:
        return Decision("late_push")
    if local.base is None and local.keep is None and local.person_data and (ahead or diverged):
        return choice(joining=True)
    if local.keep == "this" and not local.chosen and (ahead or diverged):
        return Decision("late_push")
    if diverged and not (local.keep == "folder"):
        return choice()
    candidates = ahead + (diverged if local.keep == "folder" else [])
    if not candidates:  # U2: the other computer's background results come along
        candidates = [(cid, head) for cid, head in same if cid == holder]
    if not candidates:
        return Decision("claim", from_name=heads[holder]["name"] if holder and holder != me else None)
    cid, head = max(candidates, key=lambda found: found[1]["epoch"])
    target, version = target_of(cid)
    keep = local.keep == "folder" or me in version.get("dropped", [])
    if not version["complete"]:
        return Decision("wait", target=target, arriving=_arriving(head["name"]), from_name=head["name"])
    return Decision(
        "pull",
        target=target,
        keep=keep,
        why=f"before you kept {head['name']}'s Ordnung",
        from_name=head["name"],
    )


# --------------------------------------------------------------------------------------------------
# the session
# --------------------------------------------------------------------------------------------------


class FakeSession:
    """:class:`ordnung.sync.agent.Session` for tests."""

    def __init__(self, engine: FakeEngine, paths: Paths) -> None:
        self.engine = engine
        self.paths = paths

    @property
    def state(self) -> dict[str, Any]:
        found = _state(self.paths)
        assert found is not None, "not connected"
        return found

    @property
    def folder(self) -> Path:
        return Path(self.state["folder"])

    def scan(self) -> View:
        self.engine._call("scan")
        state = self.state
        folder = Path(state["folder"])
        if not folder.is_dir():
            return View([], Problem("folder_missing"))
        with _FOLDER_LOCK:
            data = _folder_data(folder)
            if data is None:
                return View([], Problem("folder_empty"))
            if data["vault"] != state["vault"]:
                return View([], Problem("folder_other"))
            heads, versions = data["heads"], data["versions"]
            me = state["computer"]
            if any(me in head.get("forgotten", []) for head in heads.values()):
                return View([], Problem("forgotten"), heads=heads, versions=versions)
            holder = _holder(heads)
            # standing by: say which of the holder's versions has arrived here
            if holder and holder != me and state["mode"] == "standing_by":
                vid = heads[holder]["version"]
                if vid and versions[vid]["complete"] and heads[me]["has"] != vid:
                    heads[me]["has"] = vid
                    _write_folder(folder, data)
        mine = heads[me]["version"]
        computers = [
            Computer(
                key=head["key"],
                name=head["name"],
                this=cid == me,
                in_use=cid == holder,
                state=head["state"],
                arrived_at=None,
                has_latest=None
                if cid == me
                else bool(mine) and (head["has"] == mine or head["version"] == mine),
                app_version="test",
                calendar=head.get("calendar", "none"),
            )
            for cid, head in sorted(heads.items(), key=lambda item: item[1]["key"])
            if cid not in heads[me].get("forgotten", [])
        ]
        return View(computers, None, heads=heads, versions=versions, holder=holder)

    def local_view(self, store: Store) -> Local:
        self.engine._call("local_view")
        state = self.state
        data = _folder_data(self.folder) or {"versions": {}}
        base = data["versions"].get(state["base"]) if state["base"] else None
        digest, _, _ = digest_of(self.paths.db)
        now = counter(store)
        return Local(
            pending=now > state["pushed"] or base is None or digest != base["digest"],
            person_pending=now > state["pushed"],
            computer=state["computer"],
            mode=state["mode"],
            base=state["base"],
            lineage=dict(base["person"]) if base else {},
            person_data=person_data(self.paths.db),
            keep=state.get("keep"),
            chosen=bool(state.get("chosen")),
            digest=digest,
        )

    def push(self, store: Store, *, reason: str, hand_over: bool = False) -> None:
        self.engine._call(f"push:{reason}")
        if self.engine.fail_push is not None:
            raise self.engine.fail_push
        if store.get_settings().demo:
            raise sync.SyncRefused()
        with _FOLDER_LOCK:
            state = self.state
            folder = self.folder
            data = _folder_data(folder)
            if data is None:
                raise FolderProblem("folder_empty" if folder.is_dir() else "folder_missing")
            me = state["computer"]
            head = data["heads"][me]
            base = data["versions"].get(state["base"]) if state["base"] else None
            digest, letters, newest = digest_of(self.paths.db)
            now = counter(store)
            changed = base is None or digest != base["digest"] or now > state["pushed"] or state.get("chosen")
            if changed:
                lineage = dict(base["person"]) if base else {}
                if now > state["pushed"]:
                    lineage[me] = max(lineage.get(me, 0), now)
                dropped: list[str] = []
                if state.get("chosen") or state.get("keep") == "this":
                    everyone = [
                        data["versions"][h["version"]]["person"]
                        for h in data["heads"].values()
                        if h["version"]
                    ]
                    lineage = _merged(lineage, *everyone)
                    if state.get("chosen") == "this" or state.get("keep") == "this":
                        dropped = [cid for cid, h in data["heads"].items() if cid != me and h["version"]]
                state["seq"] += 1
                vid = f"{me[:6]}-{state['seq']}"
                where = folder / VERSIONS / vid
                where.mkdir(parents=True)
                _snapshot(self.paths.db, where / "ordnung.db")
                _copy_data(self.paths.data_dir, where)
                data["versions"][vid] = {
                    "computer": me,
                    "person": lineage,
                    "dropped": dropped,
                    "digest": digest,
                    "letters": letters,
                    "newest": newest,
                    "complete": True,
                    "order": len(data["versions"]) + 1,
                }
                head["version"] = vid
                state.update(base=vid, pushed=now, last_saved_at=_now(), chosen=None, keep=None)
            holder = _holder(data["heads"])
            if reason == "leave":
                head["state"] = "left"
            elif reason == "shutdown":
                head["state"] = "closed"
            elif hand_over or (holder is not None and holder != me):  # the fence
                head["state"] = "standing_by"
                state["mode"] = "standing_by"
            else:
                head["state"] = "in_use"
            _write_folder(folder, data)
            _write_state(self.paths, state)

    def stage(self, target: VersionRef) -> Staged:
        self.engine._call("stage")
        data = _folder_data(self.folder)
        assert data is not None
        version = data["versions"][target.id]
        if not version["complete"]:
            raise sync.NotArrived()
        incoming = self.paths.sync / sync.INCOMING_DIR
        if incoming.exists():
            shutil.rmtree(incoming)
        incoming.mkdir(parents=True)
        shutil.copy2(self.folder / VERSIONS / target.id / "ordnung.db", incoming / "ordnung.db")
        return Staged(target.id, incoming)

    def discard(self, staged: Staged) -> None:
        self.engine._call("discard")
        shutil.rmtree(staged.path, ignore_errors=True)

    def keep_local(self, paths: Paths, why: str) -> Kept:
        self.engine._call("keep_local")
        kept_dir = paths.sync / sync.KEPT_DIR
        kept_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d-%H%M")
        name, n = f"ordnung-kept-{stamp}.ordnung-backup", 2
        while (kept_dir / name).exists():
            name, n = f"ordnung-kept-{stamp}-{n}.ordnung-backup", n + 1
        _snapshot(paths.db, kept_dir / name)
        state = self.state
        state["kept"].append(
            {
                "name": name,
                "size": (kept_dir / name).stat().st_size,
                "created_at": _now(),
                "why": why or "kept",
            }
        )
        _write_state(self.paths, state)
        return Kept(name)

    def apply(self, staged: Staged, store: Store) -> None:
        self.engine._call("apply")
        if self.engine.on_apply is not None:
            self.engine.on_apply()
        staged_db = staged.path / "ordnung.db"
        with _WRITE_LOCK:
            live = sqlite3.connect(store.db_path)
            source = sqlite3.connect(staged_db)
            try:
                marks = ",".join("?" * len(_KEEP_LOCAL))
                rows = live.execute(
                    f"SELECT key, value FROM meta WHERE key IN ({marks})", _KEEP_LOCAL
                ).fetchall()
                settings = live.execute("SELECT value FROM meta WHERE key = 'settings'").fetchone()
                source.execute(f"DELETE FROM meta WHERE key IN ({marks})", _KEEP_LOCAL)
                source.executemany("INSERT INTO meta (key, value) VALUES (?, ?)", rows)
                if settings is not None:
                    incoming = source.execute("SELECT value FROM meta WHERE key = 'settings'").fetchone()
                    merged = json.loads(incoming[0]) if incoming else {}
                    merged.update({key: json.loads(settings[0]).get(key) for key in sync.LOCAL_SETTINGS})
                    source.execute(
                        "INSERT INTO meta (key, value) VALUES ('settings', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                        (json.dumps(merged),),
                    )
                source.commit()
                source.backup(live)
                live.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            finally:
                source.close()
                live.close()
        _copy_data(self.folder / VERSIONS / staged.version, self.paths.data_dir)
        shutil.rmtree(staged.path, ignore_errors=True)
        data = _folder_data(self.folder)
        assert data is not None
        state = self.state
        source_head = next(head for head in data["heads"].values() if head["version"] == staged.version)
        state.update(
            base=staged.version,
            pushed=counter(store),
            base_from=source_head["name"],
            base_arrived_at=_now(),
            keep=None if state.get("keep") == "folder" else state.get("keep"),
        )
        _write_state(self.paths, state)
        with _FOLDER_LOCK:
            data = _folder_data(self.folder)
            assert data is not None
            data["heads"][state["computer"]]["version"] = staged.version
            _write_folder(self.folder, data)

    def claim(self) -> None:
        self.engine._call("claim")
        with _FOLDER_LOCK:
            data = _folder_data(self.folder)
            assert data is not None
            state = self.state
            head = data["heads"][state["computer"]]
            head.update(
                epoch=1 + max(found["epoch"] for found in data["heads"].values()),
                state="in_use",
                version=state["base"],
                has=None,
            )
            _write_folder(self.folder, data)
            state.update(mode="in_use", keep=None)
            _write_state(self.paths, state)

    def choose(self, store: Store, key: int) -> Chosen:
        self.engine._call("choose")
        data = _folder_data(self.folder)
        assert data is not None
        state = self.state
        me = state["computer"]
        if data["heads"][me]["key"] == key or key == 0:
            state["chosen"] = "this"
            _write_state(self.paths, state)
            return Chosen(pull=None)
        head = next(head for head in data["heads"].values() if head["key"] == key)
        version = data["versions"][head["version"]]
        state["chosen"] = "other"
        _write_state(self.paths, state)
        return Chosen(
            pull=_ref(head["version"], version),
            complete=version["complete"],
            arriving=None if version["complete"] else _arriving(head["name"]),
            why=f"before you kept {head['name']}'s Ordnung",
            from_name=head["name"],
        )

    def forget(self, key: int) -> None:
        self.engine._call("forget")
        with _FOLDER_LOCK:
            data = _folder_data(self.folder)
            assert data is not None
            cid = next(cid for cid, head in data["heads"].items() if head["key"] == key)
            data["heads"][self.state["computer"]]["forgotten"].append(cid)
            _write_folder(self.folder, data)

    def refill(self, store: Store) -> None:
        self.engine._call("refill")
        state = self.state
        with _FOLDER_LOCK:
            _write_folder(
                self.folder,
                {
                    "vault": state["vault"],
                    "passphrase": state["check"],
                    "heads": {
                        state["computer"]: {
                            "key": 1,
                            "name": state["name"],
                            "state": "in_use",
                            "epoch": 1,
                            "version": None,
                            "has": None,
                            "forgotten": [],
                            "calendar": "none",
                        }
                    },
                    "versions": {},
                },
            )
            state.update(base=None)
            _write_state(self.paths, state)

    def gc(self) -> None:
        self.engine._call("gc")

    def keep_as_is(self, store: Store) -> None:
        self.engine._call("keep_as_is")
