"""Put Ordnung's MCP server into Claude Desktop or Claude Code (``ordnung mcp install``).

Written policy (ADR 0007) — nothing here guesses:

* **Print first.** Without ``--write`` nothing is written: the exact entry, the file it belongs in
  and (for Claude Code) the ``claude mcp add`` command are printed.
* **Where.** Claude Desktop reads ``claude_desktop_config.json`` in its settings folder: macOS
  ``~/Library/Application Support/Claude``, Windows ``%APPDATA%\\Claude``, Linux
  ``$XDG_CONFIG_HOME/Claude`` (default ``~/.config/Claude``). ``--write`` needs that folder to exist
  (Claude Desktop creates it on first start); it never creates an app's settings folder. Claude Code
  reads a project's ``.mcp.json``: ``--write`` merges into the one in the current folder (a new file
  is fine there); for all projects, run the printed ``claude mcp add --scope user`` command.
* **Merge, never clobber.** Only ``mcpServers.<name>`` is added or replaced; every other key and
  server stays as it was, in order. An empty file counts as ``{}``. A file that is not JSON, whose
  top level is not an object or whose ``mcpServers`` is not an object is refused and left untouched.
  An identical entry writes nothing.
* **Back up, then replace atomically.** Before an existing file changes, a copy is written next to
  it (``<file>.bak-<YYYYmmdd-HHMMSS>``, never overwriting an earlier backup). The new content goes to
  a temporary file in the same folder that then replaces the original, with the original's
  permissions (``0600`` for a new file). A symlinked config is written through to its target.
* **The command is absolute.** Apps start servers with a minimal ``PATH``, so the entry runs this
  Python (``sys.executable -m ordnung``) and, for the full server, names the data folder.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, get_args

McpClient = Literal["claude-desktop", "claude-code"]
CLIENTS: tuple[str, ...] = get_args(McpClient)
WriteStatus = Literal["added", "updated", "unchanged"]

DESKTOP_CONFIG_NAME = "claude_desktop_config.json"
CODE_PROJECT_CONFIG_NAME = ".mcp.json"
FULL_SERVER_NAME = "ordnung"
RULES_SERVER_NAME = "ordnung_rules"
NEW_FILE_MODE = 0o600


class InstallError(RuntimeError):
    """The config can't be written as asked; the message says why and nothing was changed."""


@dataclass(frozen=True)
class Plan:
    """What ``ordnung mcp install`` would put where."""

    client: McpClient
    name: str
    entry: dict[str, Any]
    path: Path
    rules_only: bool

    @property
    def snippet(self) -> dict[str, Any]:
        """The config fragment to merge (``{"mcpServers": {name: entry}}``)."""
        return {"mcpServers": {self.name: self.entry}}


@dataclass(frozen=True)
class WriteResult:
    status: WriteStatus
    path: Path
    backup: Path | None = None


# --------------------------------------------------------------------------------------------------
# what and where
# --------------------------------------------------------------------------------------------------


def server_entry(*, rules_only: bool, data_dir: Path | None = None) -> tuple[str, dict[str, Any]]:
    """The server's name and its stdio entry (``command`` and ``args``)."""
    if rules_only:
        return RULES_SERVER_NAME, {
            "command": sys.executable,
            "args": ["-m", "ordnung", "mcp", "--rules-only"],
        }
    if data_dir is None:
        raise ValueError("the full server needs the data folder")
    folder = str(Path(data_dir).expanduser().resolve())
    return FULL_SERVER_NAME, {
        "command": sys.executable,
        "args": ["-m", "ordnung", "mcp", "--data-dir", folder],
    }


def desktop_config_path(
    *, system: str | None = None, env: Mapping[str, str] | None = None, home: Path | None = None
) -> Path:
    """Claude Desktop's config file on this (or the given) platform (``sys.platform`` values)."""
    system = system or sys.platform
    env = os.environ if env is None else env
    home = home or Path.home()
    if system == "darwin":
        folder = home / "Library" / "Application Support" / "Claude"
    elif system.startswith(("win", "cygwin")):
        folder = Path(env.get("APPDATA") or home / "AppData" / "Roaming") / "Claude"
    else:
        folder = Path(env.get("XDG_CONFIG_HOME") or home / ".config") / "Claude"
    return folder / DESKTOP_CONFIG_NAME


def plan_install(
    client: McpClient,
    *,
    rules_only: bool,
    data_dir: Path | None = None,
    config: Path | None = None,
    cwd: Path | None = None,
    system: str | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Plan:
    """The entry and target file for ``client`` (``config`` overrides the target)."""
    if client not in CLIENTS:
        raise ValueError(f"client must be one of: {', '.join(CLIENTS)}")
    name, entry = server_entry(rules_only=rules_only, data_dir=data_dir)
    if config is not None:
        path = Path(config).expanduser()
    elif client == "claude-desktop":
        path = desktop_config_path(system=system, env=env, home=home)
    else:
        path = (cwd or Path.cwd()) / CODE_PROJECT_CONFIG_NAME
    return Plan(client=client, name=name, entry=entry, path=path, rules_only=rules_only)


def claude_code_command(plan: Plan, *, system: str | None = None) -> str:
    """The ``claude mcp add --scope user …`` command line, quoted for this platform's shell."""
    argv = [
        "claude",
        "mcp",
        "add",
        "--scope",
        "user",
        plan.name,
        "--",
        plan.entry["command"],
        *plan.entry["args"],
    ]
    if (system or sys.platform).startswith("win"):
        return subprocess.list2cmdline(argv)
    return shlex.join(argv)


def render_json(data: Mapping[str, Any]) -> str:
    """JSON as the apps write it: two-space indent, UTF-8 kept, a final newline."""
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


# --------------------------------------------------------------------------------------------------
# merging and writing
# --------------------------------------------------------------------------------------------------


def merge_server(text: str | None, name: str, entry: dict[str, Any]) -> tuple[dict[str, Any], WriteStatus]:
    """The config ``text`` with ``mcpServers[name] = entry``, and whether that changed anything.

    ``None`` or blank text is an empty config. Raises :class:`InstallError` for anything that is not
    a JSON object with an object (or absent) ``mcpServers``.
    """
    data: Any = {}
    if text is not None and text.strip():
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise InstallError(f"it is not valid JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise InstallError("its top level is not a JSON object")
    servers = data.get("mcpServers", {})
    if not isinstance(servers, dict):
        raise InstallError('its "mcpServers" is not a JSON object')
    if servers.get(name) == entry:
        return data, "unchanged"
    status: WriteStatus = "updated" if name in servers else "added"
    return {**data, "mcpServers": {**servers, name: entry}}, status


def write_config(plan: Plan, *, now: datetime | None = None) -> WriteResult:
    """Merge ``plan``'s entry into its config file (see the module policy); never clobbers."""
    path = plan.path
    if path.is_symlink():
        path = path.resolve()
    if path.exists() and not path.is_file():
        raise InstallError(f"{path} is not a file")
    if not path.parent.is_dir():
        if plan.client == "claude-desktop":
            raise InstallError(
                f"Claude Desktop's settings folder {path.parent} does not exist — is Claude Desktop "
                "installed? Start it once, then run this again."
            )
        raise InstallError(f"the folder {path.parent} does not exist")
    existing = path.read_text(encoding="utf-8-sig") if path.exists() else None
    try:
        merged, status = merge_server(existing, plan.name, plan.entry)
    except InstallError as exc:
        raise InstallError(
            f"Nothing was changed: {path} — {exc}. Fix or move that file, then run this again."
        ) from exc
    if status == "unchanged":
        return WriteResult(status=status, path=path)
    backup = _backup(path, now or datetime.now()) if existing is not None else None
    mode = path.stat().st_mode & 0o7777 if existing is not None else NEW_FILE_MODE
    _replace(path, render_json(merged), mode)
    return WriteResult(status=status, path=path, backup=backup)


def _backup(path: Path, now: datetime) -> Path:
    stem = f"{path.name}.bak-{now.strftime('%Y%m%d-%H%M%S')}"
    candidate = path.with_name(stem)
    counter = 1
    while candidate.exists():
        candidate = path.with_name(f"{stem}-{counter}")
        counter += 1
    shutil.copy2(path, candidate)
    return candidate


def _replace(path: Path, text: str, mode: int) -> None:
    handle, temp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            out.write(text)
        Path(temp).chmod(mode)
        Path(temp).replace(path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


# --------------------------------------------------------------------------------------------------
# what the person reads
# --------------------------------------------------------------------------------------------------

RULES_ONLY_PRIVACY = "The rules tools compute from what you give them; they read none of your data."
FULL_PRIVACY = (
    "This gives the client read access to your Ordnung ledger (letters, to-dos, contracts). What Claude "
    "reads through it becomes part of the conversation, where other MCP servers loaded in the same "
    "client can see it too. Use --rules-only unless you need your letters there."
)
NEXT_STEP: dict[str, str] = {
    "claude-desktop": "Restart Claude Desktop to use it.",
    "claude-code": "Claude Code asks before it starts a project's servers; say yes to use it.",
}
_CLIENT_NAMES = {"claude-desktop": "Claude Desktop", "claude-code": "Claude Code"}


def privacy_note(plan: Plan) -> str:
    return RULES_ONLY_PRIVACY if plan.rules_only else FULL_PRIVACY


def what(plan: Plan) -> str:
    return "Ordnung's rules tools" if plan.rules_only else "Ordnung with your data"


def write_command(plan: Plan, *, data_dir: Path | None = None, config: Path | None = None) -> str:
    """The ``ordnung mcp install … --write`` command that does what the printed instructions say."""
    argv = ["ordnung", "mcp", "install", "--client", plan.client]
    if plan.rules_only:
        argv.append("--rules-only")
    elif data_dir is not None:
        argv += ["--data-dir", str(data_dir)]
    if config is not None:
        argv += ["--config", str(config)]
    return shlex.join([*argv, "--write"])


def instructions(
    plan: Plan, *, data_dir: Path | None = None, config: Path | None = None, system: str | None = None
) -> str:
    """What ``ordnung mcp install`` prints without ``--write`` (plain text, nothing wrapped)."""
    entry = render_json(plan.snippet).rstrip()
    again = write_command(plan, data_dir=data_dir, config=config)
    if plan.client == "claude-code":
        lines = [
            f"To add {what(plan)} to Claude Code for all your projects, run:",
            f"  {claude_code_command(plan, system=system)}",
            "",
            "Or, for one project, add this entry to its .mcp.json:",
            f"  {plan.path}",
            "",
            entry,
            "",
            "Ordnung can merge it into that file for you (the file is backed up first):",
            f"  {again}",
        ]
    else:
        lines = [
            f'To add {what(plan)} to Claude Desktop, add this entry to "mcpServers" in',
            f"  {plan.path}",
            "(keep the servers that are already there):",
            "",
            entry,
            "",
            "Ordnung can merge it in for you (the file is backed up first):",
            f"  {again}",
            "",
            "Then restart Claude Desktop.",
        ]
    return "\n".join(lines)


def written_message(plan: Plan, result: WriteResult) -> str:
    """One line on what ``--write`` did."""
    target = f"“{plan.name}” in {result.path}"
    client = _CLIENT_NAMES[plan.client]
    if result.status == "unchanged":
        return f"{client} already has {what(plan)} as {target}; nothing changed."
    verb = "Added" if result.status == "added" else "Updated"
    return f"{verb} {what(plan)} for {client} as {target}."
