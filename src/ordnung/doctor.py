"""``ordnung doctor``: zero-token health checks with fix hints (SPEC §7, §15).

Checks that the ``claude`` CLI is installed and recent enough, that it is signed in (``claude auth
status``, JSON), warns when ``ANTHROPIC_API_KEY`` is set (it overrides the subscription login and
bills the API), and checks the local machine: SQLite FTS5 + trigram search, a writable data folder,
the database in it (opened read-only: SQLite's quick check and the schema version), free disk space,
the bundled letter fonts and the built web app; when the last copy kept elsewhere was made (a backup, or
hand-off sync's save: :mod:`ordnung.backup.reminder`) and whether the disk under the data folder is
encrypted (:mod:`ordnung.encryption`, on macOS and Linux) — both only ever warn — and, while hand-off sync
is connected, the sync folder (reachable), the password store (usable), the mode and the age of the last
save, never reading the passphrase. ``probe=True`` adds one tiny live model call. The
structured :class:`DoctorReport` feeds the CLI, ``/api/health`` (via :func:`claude_status`) and the
Settings page.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ordnung import clock, encryption
from ordnung.backup import reminder
from ordnung.config import Paths, web_dist_dir
from ordnung.db.migrate import SchemaError, applied_versions, current_version, discover
from ordnung.llm import claude_cli
from ordnung.llm.claude_cli import MIN_CLAUDE_VERSION, parse_version, version_text
from ordnung.models import CheckStatus, ClaudeStatus, DoctorCheck

# re-exported: the check models live in ordnung.models, the version floor with the backend that keeps to it
__all__ = ["MIN_CLAUDE_VERSION", "CheckStatus", "DoctorCheck", "parse_version"]

MIN_FREE_BYTES = 100 * 1024 * 1024
LOW_FREE_BYTES = 1024 * 1024 * 1024
#: Where to get Claude Code — the address every install hint names (the reading job's error names it too).
CLAUDE_CODE_URL = "https://claude.com/claude-code"


def native_install(platform: str = sys.platform) -> str:
    """The installer Anthropic's setup page recommends for ``platform`` (PowerShell's on Windows)."""
    if platform == "win32":
        return "irm https://claude.ai/install.ps1 | iex"
    return "curl -fsSL https://claude.ai/install.sh | bash"


def install_hint(platform: str = sys.platform) -> str:
    """How to install Claude Code on ``platform``; on Windows it says PowerShell (cmd.exe can't run it)."""
    shell = " in PowerShell" if platform == "win32" else ""
    return (
        f"Install Claude Code with `{native_install(platform)}`{shell} (other ways: {CLAUDE_CODE_URL}; it "
        "needs a paid Claude plan or a Console account), run `claude` once to sign in, then run "
        "`ordnung doctor` again."
    )


NATIVE_INSTALL = native_install()
INSTALL_HINT = install_hint()
LOGIN_HINT = "Run `claude auth login` (or start `claude` and type /login), then run `ordnung doctor` again."
MODEL_HINT = (
    "Signed in already? Then `{model}`, the model every call runs on (Settings → Claude connection), may "
    "not be a name Claude Code accepts."
)
UPDATE_HINT = (
    "Update Claude Code with `claude update` (installed with Homebrew: `brew upgrade claude-code`; with "
    "WinGet: `winget upgrade Anthropic.ClaudeCode`), then run `ordnung doctor` again."
)
API_KEY_HINT = "Unset it (`unset ANTHROPIC_API_KEY`) so Claude Code uses your Claude subscription."
RESTORE_HINT = (
    "Restore your latest backup with `ordnung restore FILE --force` (FILE is the .ordnung-backup file; "
    "the damaged data is moved aside, not deleted)."
)


class DoctorReport(BaseModel):
    """All checks plus the Claude summary used by ``/api/health``."""

    checks: list[DoctorCheck] = Field(default_factory=list)
    claude: ClaudeStatus = Field(default_factory=ClaudeStatus)

    @property
    def ok(self) -> bool:
        """No check failed (warnings are fine)."""
        return all(check.status != "fail" for check in self.checks)

    def check(self, check_id: str) -> DoctorCheck | None:
        """The check with this id, if it ran."""
        return next((check for check in self.checks if check.id == check_id), None)


# --------------------------------------------------------------------------------------------------
# Claude
# --------------------------------------------------------------------------------------------------


def _version_check(raw: str | None) -> DoctorCheck:
    label = "Claude Code version"
    version = parse_version(raw)
    if raw is None:
        return DoctorCheck(
            id="claude_version",
            label=label,
            status="fail",
            detail="`claude --version` did not answer.",
            fix=INSTALL_HINT,
        )
    if version is None:
        return DoctorCheck(
            id="claude_version", label=label, status="warn", detail=f"Unrecognised version: {raw}"
        )
    shown = version_text(version)
    if version < MIN_CLAUDE_VERSION:
        needed = version_text(MIN_CLAUDE_VERSION)
        return DoctorCheck(
            id="claude_version",
            label=label,
            status="fail",
            detail=f"{shown} is too old — Ordnung needs {needed} or newer.",
            fix=UPDATE_HINT,
        )
    return DoctorCheck(id="claude_version", label=label, status="ok", detail=shown)


def _auth_check(status: dict[str, Any] | None) -> DoctorCheck:
    label = "Claude sign-in"
    if status is None:
        return DoctorCheck(
            id="claude_auth",
            label=label,
            status="warn",
            detail="Couldn't read `claude auth status`.",
            fix=LOGIN_HINT,
        )
    if not status.get("loggedIn"):
        return DoctorCheck(
            id="claude_auth",
            label=label,
            status="fail",
            detail="Claude Code is not signed in.",
            fix=LOGIN_HINT,
        )
    method = status.get("authMethod")
    return DoctorCheck(
        id="claude_auth", label=label, status="ok", detail=f"Signed in ({method})" if method else "Signed in"
    )


async def _probe_check(binary: str | None, model: str | None) -> DoctorCheck:
    """The live call, on the model every call runs on when the caller knows it (the API, the CLI with
    data): a failure then may as well be that model's name, so the fix says so after the sign-in."""
    probe = await claude_cli.probe(binary, model=model)
    detail = probe.text or ("Claude answered." if probe.ok else "No answer.")
    fix = None if probe.ok else LOGIN_HINT
    if fix and model is not None:
        fix = f"{fix} {MODEL_HINT.format(model=probe.model)}"
    return DoctorCheck(
        id="claude_probe",
        label="Live test call",
        status="ok" if probe.ok else "fail",
        detail=f"{detail} (on {probe.model})",
        fix=fix,
    )


async def check_claude(
    binary: str | None = None, *, probe: bool = False, model: str | None = None
) -> tuple[list[DoctorCheck], ClaudeStatus]:
    """The Claude checks (install, version, sign-in, optional live probe on ``model``) and their summary."""
    path = claude_cli.find_claude(binary)
    if path is None:
        missing = DoctorCheck(
            id="claude_cli",
            label="Claude Code installed",
            status="fail",
            detail="The `claude` command was not found on PATH.",
            fix=INSTALL_HINT,
        )
        return [missing], ClaudeStatus(installed=False, ok=False, detail=missing.detail)
    raw_version, auth = await asyncio.gather(claude_cli.version(path), claude_cli.auth_status(path))
    checks = [
        DoctorCheck(id="claude_cli", label="Claude Code installed", status="ok", detail=path),
        _version_check(raw_version),
        _auth_check(auth),
    ]
    if probe:
        checks.append(await _probe_check(path, model))
    version = parse_version(raw_version)
    problem = next((check for check in checks if check.status == "fail"), None)
    status = ClaudeStatus(
        installed=True,
        version=version_text(version) if version else raw_version,
        path=path,
        ok=problem is None,
        detail=problem.detail if problem else checks[2].detail,
        needs_version=version_text(MIN_CLAUDE_VERSION) if claude_cli.too_old(raw_version) else None,
    )
    return checks, status


async def claude_status(binary: str | None = None) -> ClaudeStatus:
    """Zero-token Claude summary for ``/api/health`` and the Settings page."""
    _, status = await check_claude(binary)
    return status


def api_key_check() -> DoctorCheck:
    """Warn when ``ANTHROPIC_API_KEY`` is set: it overrides the subscription login."""
    label = "ANTHROPIC_API_KEY"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return DoctorCheck(
            id="api_key",
            label=label,
            status="warn",
            detail="Set — Claude Code will use it instead of your subscription login and bill the API.",
            fix=API_KEY_HINT,
        )
    return DoctorCheck(
        id="api_key", label=label, status="ok", detail="Not set — your own Claude login is used."
    )


# --------------------------------------------------------------------------------------------------
# This computer
# --------------------------------------------------------------------------------------------------


def sqlite_check() -> DoctorCheck:
    """SQLite with FTS5 and the trigram tokenizer (search inside German compound words)."""
    label = "Search (SQLite FTS5 + trigram)"
    version = sqlite3.sqlite_version
    fix = "Use a Python whose SQLite is 3.34 or newer with FTS5 (e.g. a python.org or uv-managed Python)."
    try:
        with contextlib.closing(sqlite3.connect(":memory:")) as conn:
            conn.execute("CREATE VIRTUAL TABLE words USING fts5(body)")
            conn.execute("CREATE VIRTUAL TABLE grams USING fts5(body, tokenize='trigram')")
    except sqlite3.Error as exc:
        return DoctorCheck(
            id="sqlite_fts", label=label, status="fail", detail=f"SQLite {version}: {exc}", fix=fix
        )
    return DoctorCheck(id="sqlite_fts", label=label, status="ok", detail=f"SQLite {version}")


def _existing_ancestor(path: Path) -> Path:
    for candidate in (path, *path.parents):
        if candidate.exists():
            return candidate
    return Path(path.anchor or ".")


def data_dir_check(data_dir: Path) -> DoctorCheck:
    """The data folder exists and is writable (or can be created)."""
    label = "Data folder"
    fix = "Choose another folder with --data-dir or ORDNUNG_HOME."
    if not data_dir.exists():
        parent = _existing_ancestor(data_dir)
        if os.access(parent, os.W_OK):
            return DoctorCheck(
                id="data_dir", label=label, status="ok", detail=f"{data_dir} (will be created)"
            )
        return DoctorCheck(
            id="data_dir", label=label, status="fail", detail=f"{parent} is not writable.", fix=fix
        )
    try:
        with tempfile.TemporaryFile(dir=data_dir):
            pass
    except OSError as exc:
        return DoctorCheck(
            id="data_dir", label=label, status="fail", detail=f"{data_dir}: {exc.strerror or exc}", fix=fix
        )
    return DoctorCheck(id="data_dir", label=label, status="ok", detail=str(data_dir))


def database_check(data_dir: Path) -> DoctorCheck:
    """The database of the data folder, opened read-only: SQLite's quick check, and a schema version
    this Ordnung can read (an older one is brought up to date when Ordnung starts)."""
    label = "Database"
    db = Paths(data_dir).db
    if not db.is_file():
        return DoctorCheck(id="database", label=label, status="ok", detail="None yet (it will be created)")
    try:
        with contextlib.closing(sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)) as conn:
            problems = [str(row[0]) for row in conn.execute("PRAGMA quick_check(3)")]
            version = current_version(conn)
            shipped = {migration.version for migration in discover()}
            unknown = applied_versions(conn) - shipped
    except (sqlite3.Error, SchemaError) as exc:
        return DoctorCheck(
            id="database", label=label, status="fail", detail=f"{db} can't be read: {exc}", fix=RESTORE_HINT
        )
    if problems != ["ok"]:
        return DoctorCheck(
            id="database",
            label=label,
            status="fail",
            detail=f"{db} is damaged: {'; '.join(problems)}",
            fix=RESTORE_HINT,
        )
    latest = max(shipped)
    if version > latest or unknown:
        return DoctorCheck(
            id="database",
            label=label,
            status="fail",
            detail=(
                f"A newer version of Ordnung wrote it (schema version {version}; this one reads up to "
                f"{latest})."
            ),
            fix=f"Update Ordnung. Or {RESTORE_HINT[0].lower()}{RESTORE_HINT[1:]}",
        )
    if version < latest:
        detail = f"Schema version {version} (brought up to {latest} when Ordnung starts)"
    else:
        detail = f"Schema version {version}"
    return DoctorCheck(id="database", label=label, status="ok", detail=detail)


def disk_check(data_dir: Path) -> DoctorCheck:
    """Free space where the data folder lives."""
    label = "Disk space"
    free = shutil.disk_usage(_existing_ancestor(data_dir)).free
    detail = f"{free / 1024**3:.1f} GB free"
    if free < MIN_FREE_BYTES:
        return DoctorCheck(
            id="disk", label=label, status="fail", detail=detail, fix="Free some disk space for your letters."
        )
    if free < LOW_FREE_BYTES:
        return DoctorCheck(
            id="disk",
            label=label,
            status="warn",
            detail=detail,
            fix="Page images need some room — free up space.",
        )
    return DoctorCheck(id="disk", label=label, status="ok", detail=detail)


SYNC_FOLDER_TIMEOUT_S = 5.0
SYNC_STALE_S = 24 * 3600


class _NoSyncEngine(Exception):
    """Hand-off sync is connected, but this installation of Ordnung can't sync."""


def _sync_summary(paths: Paths) -> Any:
    """Hand-off sync's state on this computer (``<data>/sync/state.json``) while it is connected —
    ``None`` when it isn't; raises :class:`_NoSyncEngine`, or whatever reading the state raised."""
    from ordnung.app_context import sync_connected
    from ordnung.sync.agent import load_engine

    if not sync_connected(paths):
        return None
    engine = load_engine()
    if engine is None:
        raise _NoSyncEngine
    return engine.local_summary(paths)


def sync_check(data_dir: Path) -> DoctorCheck | None:
    """Hand-off sync (only when it is connected): the sync folder reachable, the password store usable,
    whether this computer is in use or standing by, and when it last saved. Never reads the passphrase
    or opens the folder's files."""
    from concurrent.futures import ThreadPoolExecutor
    from concurrent.futures import TimeoutError as FutureTimeout

    from ordnung.sync.agent import default_secrets

    paths = Paths(data_dir)
    label = "Hand-off sync"
    try:
        summary = _sync_summary(paths)
    except _NoSyncEngine:
        return DoctorCheck(
            id="sync",
            label=label,
            status="warn",
            detail="This installation of Ordnung can't sync between computers.",
            fix="Install the same Ordnung version as on your other computers.",
        )
    except Exception as exc:
        return DoctorCheck(id="sync", label=label, status="warn", detail=f"Its state can't be read: {exc}")
    if summary is None:
        return None
    keyring = default_secrets().problem()
    if keyring is not None:
        return DoctorCheck(
            id="sync", label=label, status="fail", detail=str(keyring), fix=keyring.install or None
        )
    pool = ThreadPoolExecutor(max_workers=1)
    try:  # a hung network share must not hang the doctor
        reachable = pool.submit(Path(summary.folder).is_dir).result(timeout=SYNC_FOLDER_TIMEOUT_S)
    except (FutureTimeout, OSError):
        reachable = False
    finally:
        pool.shutdown(wait=False)
    if not reachable:
        return DoctorCheck(
            id="sync",
            label=label,
            status="warn",
            detail=f"The sync folder {summary.folder} can't be reached.",
            fix="Connect its drive or share, and check that your sync tool runs.",
        )
    mode = (
        "in use here"
        if summary.mode == "in_use"
        else f"standing by (in use on {summary.in_use_on or 'another computer'})"
    )
    saved = "never saved yet"
    status: CheckStatus = "ok"
    if summary.last_saved_at:
        try:
            moment = datetime.fromisoformat(summary.last_saved_at)
            age = (datetime.now(moment.tzinfo) - moment).total_seconds()
        except ValueError:
            age = 0.0
        saved = f"last saved {int(age // 3600)} h ago" if age >= 3600 else "last saved within the hour"
        if summary.mode == "in_use" and age > SYNC_STALE_S:
            status = "warn"
    detail = f"{summary.name}: {mode}, {saved} ({summary.folder})"
    fix = "Open Settings → Your computers to see why it doesn't save." if status == "warn" else None
    return DoctorCheck(id="sync", label=label, status=status, detail=detail, fix=fix)


BACKUP_FIX = (
    "Run `ordnung backup --to FOLDER` with a folder on another drive or in the cloud (or Settings → Data → "
    "Download encrypted backup). Backups of the whole computer (Time Machine, File History) don't count: "
    "Ordnung can't see them."
)


def _is_demo(data_dir: Path, conn: sqlite3.Connection) -> bool:
    """A demo folder: its marker, or the demo setting in its database."""
    from ordnung.db.store import SETTINGS_META_KEY
    from ordnung.demo.loader import is_demo_dir

    if is_demo_dir(data_dir):
        return True
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (SETTINGS_META_KEY,)).fetchone()
    try:
        settings = json.loads(row[0]) if row is not None else None
    except ValueError:
        return False
    return isinstance(settings, dict) and settings.get("demo") is True


def _days_words(days: int) -> str:
    return "today" if days == 0 else "yesterday" if days == 1 else f"{days} days ago"


def backup_check(data_dir: Path) -> DoctorCheck | None:
    """When the last copy kept elsewhere was made — a backup made or restored here, or hand-off sync's
    save (:mod:`ordnung.backup.reminder`) — warning when there is none within 30 days. ``None`` for a
    folder without a database, a demo folder, or a database that can't be read (the database check says
    why). Never fails; days count in this computer's zone."""
    label = "Backup"
    folder = Path(data_dir)
    db = Paths(folder).db
    if not db.is_file():
        return None
    try:
        with contextlib.closing(sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)) as conn:
            if _is_demo(folder, conn):
                return None
            last_backup, restored = reminder.newest_backup(conn)
            has_letters = bool(conn.execute("SELECT EXISTS(SELECT 1 FROM documents)").fetchone()[0])
    except sqlite3.Error:
        return None
    try:
        summary = _sync_summary(Paths(folder))
    except Exception:  # the sync row says why
        summary = None
    sync = (
        reminder.SyncCopy.of(connected=True, mode=summary.mode, saved_at=summary.last_saved_at)
        if summary is not None
        else None
    )
    zone = datetime.now().astimezone().tzinfo or UTC
    copy = reminder.backup_copy(
        last_backup=last_backup,
        restored=restored,
        sync=sync,
        has_letters=has_letters,
        demo=False,
        zone=zone,
        today=clock.today(),
    )
    if not has_letters:
        return DoctorCheck(id="backup", label=label, status="ok", detail="Nothing to back up yet")
    if copy.sync_standing_by:
        detail = "Hand-off sync: the computer in use keeps an encrypted copy in the sync folder"
        return DoctorCheck(id="backup", label=label, status="ok", detail=detail)
    if copy.days is None:
        detail = "Ordnung has no record of a backup made on this computer"
        return DoctorCheck(id="backup", label=label, status="warn", detail=detail, fix=BACKUP_FIX)
    made = reminder.parse_moment(copy.last_backup_at)
    saved = reminder.parse_moment(copy.sync_saved_at)
    if made is not None and (saved is None or made >= saved):
        detail = f"Last backup {_days_words(copy.days)} ({made.astimezone(zone).date().isoformat()})"
        if copy.last_backup_restored:
            detail += ", the one this copy was restored from"
    else:
        detail = f"Hand-off sync saved an encrypted copy {_days_words(copy.days)}"
    if copy.due:
        return DoctorCheck(id="backup", label=label, status="warn", detail=detail, fix=BACKUP_FIX)
    return DoctorCheck(id="backup", label=label, status="ok", detail=detail)


#: What disk encryption looked for or found, in the doctor's words when it is on.
_ENCRYPTED = {
    "FileVault": "FileVault is on",
    "LUKS": "The disk under the data folder is encrypted (LUKS)",
}
FILEVAULT_FIX = "Turn it on in System Settings → Privacy & Security → FileVault."
LINUX_ENCRYPTION_FIX = (
    "Most Linux installers offer to encrypt the disk; adding it later means reinstalling or `cryptsetup "
    "reencrypt`, so back up first. Encrypted another way (fscrypt, ZFS)? Then this is fine."
)


def disk_encryption_check(
    data_dir: Path, *, probe: Callable[[Path], encryption.Encryption | None] | None = None
) -> DoctorCheck | None:
    """Whether the disk under the data folder is encrypted (:mod:`ordnung.encryption`, a best effort):
    on is fine, off or "couldn't tell" warn — never a failure. ``None`` where Ordnung can't tell on this
    system (Windows, WSL, others). It describes this computer, so a demo folder gets it too."""
    label = "Disk encryption"
    found = (probe or encryption.disk_encryption)(Path(data_dir))
    if found is None:
        return None
    mac = found.what == "FileVault"
    if found.answer == "on":
        detail = _ENCRYPTED.get(found.what, f"The data folder is on an encrypted file system ({found.what})")
        return DoctorCheck(id="disk_encryption", label=label, status="ok", detail=detail)
    if found.answer == "off":
        detail = (
            "FileVault is off: whoever has this Mac can read your letters, tax ID and IBANs."
            if mac
            else "Ordnung found no disk encryption (LUKS) under the data folder."
        )
    else:
        what = "FileVault is on" if mac else "the disk under the data folder is encrypted"
        reason = f": {found.reason}" if found.reason else ""
        detail = f"Ordnung couldn't tell whether {what}{reason}."
    fix = FILEVAULT_FIX if mac else LINUX_ENCRYPTION_FIX
    if found.answer == "unknown" and mac:
        fix = "Check it in System Settings → Privacy & Security → FileVault."
    return DoctorCheck(id="disk_encryption", label=label, status="warn", detail=detail, fix=fix)


def fonts_check() -> DoctorCheck:
    """The DejaVu fonts the letter PDFs are set in."""
    from ordnung.drafts.pdf import FONT_DIR

    missing = [name for name in ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf") if not (FONT_DIR / name).is_file()]
    if missing:
        return DoctorCheck(
            id="fonts",
            label="Letter fonts",
            status="fail",
            detail=f"Missing: {', '.join(missing)}",
            fix="Reinstall Ordnung (pip install --force-reinstall ordnung).",
        )
    return DoctorCheck(id="fonts", label="Letter fonts", status="ok", detail="DejaVu Sans")


def web_app_fix(dist: Path) -> str:
    """How to get the web app missing from ``dist``: build it in a source checkout; a pip/pipx/uv
    install has no ``web/`` folder or Makefile to build from, so there the answer is to reinstall."""
    checkout = dist.parents[3]  # <checkout>/src/ordnung/web/dist
    if (checkout / "Makefile").is_file() and (checkout / "web" / "package.json").is_file():
        return "In the source checkout run `make build-web` (npm --prefix web run build)."
    return (
        "Reinstall Ordnung: `pipx reinstall ordnung`, or run your `uv tool install --reinstall …` "
        "or `pip install --force-reinstall …` again."
    )


def web_ui_check() -> DoctorCheck:
    """The built web app (``web/dist``) that ``ordnung serve`` shows."""
    dist = web_dist_dir()
    index = dist / "index.html"
    if not index.is_file():
        return DoctorCheck(
            id="web_ui",
            label="Web app",
            status="warn",
            detail="The web app is not part of this installation.",
            fix=web_app_fix(dist),
        )
    return DoctorCheck(id="web_ui", label="Web app", status="ok", detail=str(index.parent))


# --------------------------------------------------------------------------------------------------
# All together
# --------------------------------------------------------------------------------------------------


def local_checks(data_dir: str | Path) -> list[DoctorCheck]:
    """The checks of this computer (no Claude involved), in the order shown; the backup, disk-encryption
    and sync rows only where they apply."""
    folder = Path(data_dir).expanduser()
    checks: list[DoctorCheck | None] = [
        api_key_check(),
        sqlite_check(),
        fonts_check(),
        web_ui_check(),
        data_dir_check(folder),
        database_check(folder),
        disk_check(folder),
        backup_check(folder),
        disk_encryption_check(folder),
        sync_check(folder),
    ]
    return [check for check in checks if check is not None]


async def run_doctor(
    data_dir: str | Path, *, probe: bool = False, binary: str | None = None, model: str | None = None
) -> DoctorReport:
    """Run every check. Zero tokens unless ``probe`` is set (one tiny live call, on ``model`` — the one
    every call runs on — when the caller knows it)."""
    claude_checks, status = await check_claude(binary, probe=probe, model=model)
    checks = await asyncio.to_thread(local_checks, data_dir)
    return DoctorReport(checks=[*claude_checks, *checks], claude=status)


def run_doctor_sync(
    data_dir: str | Path, *, probe: bool = False, binary: str | None = None, model: str | None = None
) -> DoctorReport:
    """:func:`run_doctor` for synchronous callers (the CLI)."""
    return asyncio.run(run_doctor(data_dir, probe=probe, binary=binary, model=model))
