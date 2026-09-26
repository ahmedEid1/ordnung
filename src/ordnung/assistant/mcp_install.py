"""Put Ordnung's MCP server into Claude Desktop or Claude Code (``ordnung mcp install``).

Written policy (ADR 0007) — nothing here guesses:

* **Print first.** Without ``--write`` nothing is written: the exact entry, the file it belongs in
  and (for Claude Code) the ``claude mcp add`` command are printed.
* **Rules only unless asked.** The entry is the rules-only server unless the person asks for the
  ledger (``--with-ledger`` in the CLI); the full server then names the data folder and the privacy
  note is shown before anything is written.
* **Where.** Claude Desktop reads ``claude_desktop_config.json`` in its settings folder: macOS
  ``~/Library/Application Support/Claude``, Windows ``%APPDATA%\\Claude``, Linux
  ``$XDG_CONFIG_HOME/Claude`` (default ``~/.config/Claude``). ``--write`` needs that folder to exist
  (Claude Desktop creates it on first start); it never creates an app's settings folder. Claude Code
  reads a project's ``.mcp.json``: ``--write`` merges the rules tools into the one in the current
  folder (a new file is fine there). That file is meant to be committed and shared, so the full
  server is never written into it: its printed ``claude mcp add --scope local`` command keeps the
  ledger private to this person and project. The rules tools, which expose nothing, are offered for
  all projects (``--scope user``).
* **Merge, never clobber.** Only ``mcpServers.<name>`` is added or replaced; every other key and
  server stays as it was, in order. An empty file counts as ``{}``. A file that is not JSON, whose
  top level is not an object or whose ``mcpServers`` is not an object is refused and left untouched.
  An identical entry writes nothing.
* **Back up, then replace atomically.** Before an existing file changes, a copy is written next to
  it (``<file>.bak-<YYYYmmdd-HHMMSS>``, never overwriting an earlier backup). The new content goes to
  a temporary file in the same folder that then replaces the original, with the original's
  permissions (``0600`` for a new file). A symlinked config is written through to its target.
* **The command is absolute.** Apps start servers with a minimal ``PATH``, so the entry runs this
  Python (``sys.executable -m ordnung``) and, for the full server, names the data folder. That path
  shows this computer's folders (the user name too), so wherever an entry goes into a project's
  ``.mcp.json`` — printed or written — the person is told before they commit it. Printed commands
  are quoted for this platform's shell: POSIX, or on Windows ``cmd.exe``, where an argument with a
  space or one of its metacharacters (``& | < > ^ ( )``) goes in double quotes; a ``%NAME%`` in a
  path would still be expanded there (no quoting stops that at its prompt; paths rarely have one).
* **Only UTF-8 JSON.** The apps read their config as UTF-8; a file in another encoding (a UTF-16
  file written by Windows PowerShell 5.1, say) is refused untouched like invalid JSON.
* **One Ordnung, said plainly.** The rules-only entry (``ordnung_rules``) and the full server
  (``ordnung``) have different names, so installing one leaves the other in place. When the target
  file already has the other one, the person is told — above all when the ledger stays readable
  after they installed "the rules tools alone" — and ``--remove-ledger`` (with the rules tools)
  takes the full server out in the same backed-up write. A full server added with ``claude mcp add
  --scope local`` lives in Claude Code's own settings, which Ordnung does not edit: the printed
  ``claude mcp remove`` command takes it out.
"""

from __future__ import annotations

import json
import os
import re
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
#: Claude Code scopes: the rules tools expose nothing, so every project may have them; the ledger stays
#: private to this person and this project (``local`` is never written to a shared file).
CODE_SCOPE_RULES = "user"
CODE_SCOPE_FULL = "local"
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
    #: False when the person named the file (`--config`): then it is not "the app's" folder that is missing.
    usual_path: bool = True

    @property
    def snippet(self) -> dict[str, Any]:
        """The config fragment to merge (``{"mcpServers": {name: entry}}``)."""
        return {"mcpServers": {self.name: self.entry}}


@dataclass(frozen=True)
class WriteResult:
    status: WriteStatus
    path: Path
    backup: Path | None = None
    #: The other Ordnung entry this write took out (``--remove-ledger``).
    removed: str | None = None
    #: The other Ordnung entry still in the file afterwards (see :func:`other_entry_name`).
    other: str | None = None


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
    return Plan(
        client=client, name=name, entry=entry, path=path, rules_only=rules_only, usual_path=config is None
    )


def code_scope(plan: Plan) -> str:
    """The Claude Code scope to add ``plan``'s server with (see :data:`CODE_SCOPE_RULES`)."""
    return CODE_SCOPE_RULES if plan.rules_only else CODE_SCOPE_FULL


def claude_code_command(plan: Plan, *, system: str | None = None) -> str:
    """The ``claude mcp add --scope user|local …`` command line, quoted for this platform's shell."""
    argv = ["claude", "mcp", "add", "--scope", code_scope(plan), plan.name, "--"]
    return shell_join([*argv, plan.entry["command"], *plan.entry["args"]], system=system)


def claude_code_remove_command(plan: Plan, *, system: str | None = None) -> str:
    """The ``claude mcp remove`` command that undoes :func:`claude_code_command`."""
    return shell_join(["claude", "mcp", "remove", "--scope", code_scope(plan), plan.name], system=system)


#: The characters cmd.exe acts on outside double quotes (``&`` starts a second command, ``|`` a pipe …).
_CMD_META = re.compile(r"[&|<>^()]")


def shell_join(argv: list[str], *, system: str | None = None) -> str:
    """``argv`` as one command line quoted for this (or the given) platform's shell (module policy).

    Windows: each argument as the program's C runtime parses it (:func:`subprocess.list2cmdline`),
    in double quotes when it has a cmd.exe metacharacter too, so that cmd.exe passes it on whole.
    """
    if (system or sys.platform).startswith("win"):
        return " ".join(_cmd_arg(arg) for arg in argv)
    return shlex.join(argv)


def _cmd_arg(arg: str) -> str:
    """One argument for cmd.exe: :func:`subprocess.list2cmdline`'s quoting, forced for a metacharacter.

    In double quotes, backslashes before a quote (and at the end) are doubled, as the C runtime
    reads them; an argument with a double quote of its own cannot be made safe for cmd.exe (it
    toggles quoting), but no Windows path has one.
    """
    if not _CMD_META.search(arg) or " " in arg or "\t" in arg:
        return subprocess.list2cmdline([arg])
    out: list[str] = []
    slashes = 0
    for char in arg:
        if char == "\\":
            slashes += 1
            continue
        out.append("\\" * (2 * slashes + 1) + char if char == '"' else "\\" * slashes + char)
        slashes = 0
    return '"' + "".join(out) + "\\" * (2 * slashes) + '"'


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


def other_entry_name(plan: Plan) -> str:
    """The name of the other Ordnung server: the full one for the rules tools, and the other way round."""
    return FULL_SERVER_NAME if plan.rules_only else RULES_SERVER_NAME


def other_entry_in(plan: Plan) -> str | None:
    """The other Ordnung server's name if ``plan``'s config file already has it, else ``None``.

    Best effort, for what is printed before anything is written: a missing or unreadable file
    counts as not having it (:func:`write_config` reports such a file).
    """
    path = plan.path.resolve() if plan.path.is_symlink() else plan.path
    try:
        data = json.loads(_read(path) or "{}")
    except (InstallError, OSError, ValueError):
        return None
    servers = data.get("mcpServers") if isinstance(data, dict) else None
    name = other_entry_name(plan)
    return name if isinstance(servers, dict) and name in servers else None


def write_config(plan: Plan, *, now: datetime | None = None, remove_ledger: bool = False) -> WriteResult:
    """Merge ``plan``'s entry into its config file (see the module policy); never clobbers.

    ``remove_ledger`` (rules-only plans) also takes the full server's entry out, in the same write.
    """
    if remove_ledger and not plan.rules_only:
        raise ValueError("remove_ledger goes with the rules tools")
    path = plan.path
    if path.is_symlink():
        path = path.resolve()
    if not plan.rules_only and path.name == CODE_PROJECT_CONFIG_NAME:
        raise InstallError(
            f"Nothing was changed: {path} is a project's shared server list, usually committed with the "
            "project, so Ordnung doesn't put your ledger there. Run the printed `claude mcp add --scope "
            "local …` command instead: it keeps the ledger private to you and this project."
        )
    if path.exists() and not path.is_file():
        raise InstallError(f"{path} is not a file")
    if not path.parent.is_dir():
        if plan.client == "claude-desktop" and plan.usual_path:
            raise InstallError(
                f"Claude Desktop's settings folder {path.parent} does not exist — is Claude Desktop "
                "installed? Start it once, then run this again."
            )
        raise InstallError(f"The folder {path.parent} does not exist.")
    try:
        existing = _read(path)
        merged, status = merge_server(existing, plan.name, plan.entry)
    except InstallError as exc:
        raise InstallError(
            f"Nothing was changed: {path} — {exc}. Fix or move that file, then run this again."
        ) from exc
    servers: dict[str, Any] = merged.get("mcpServers", {})
    other = other_entry_name(plan)
    removed = other if remove_ledger and other in servers else None
    if removed is not None:
        merged = {**merged, "mcpServers": {name: entry for name, entry in servers.items() if name != removed}}
    left = other if other in servers and removed is None else None
    if status == "unchanged" and removed is None:
        return WriteResult(status=status, path=path, other=left)
    backup = _backup(path, now or datetime.now()) if existing is not None else None
    mode = path.stat().st_mode & 0o7777 if existing is not None else NEW_FILE_MODE
    _replace(path, render_json(merged), mode)
    return WriteResult(status=status, path=path, backup=backup, removed=removed, other=left)


def _read(path: Path) -> str | None:
    """The config's text (a UTF-8 BOM is fine), ``None`` for no file; :class:`InstallError` if not UTF-8."""
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InstallError(
            "it is not UTF-8 text, which the Claude apps read (a UTF-16 file from Windows PowerShell? "
            f"Save it as UTF-8) ({exc.reason} at byte {exc.start})"
        ) from exc


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
    "reads through it becomes part of the conversation, where the client's other tools can pass it on: "
    "other MCP servers loaded there and, in Claude Code, its own shell and web tools. Leave out "
    "--with-ledger (the rules tools alone) unless you need your letters there."
)
NEXT_STEP: dict[str, str] = {
    "claude-desktop": "Restart Claude Desktop to use it.",
    "claude-code": "Claude Code asks before it starts a project's servers; say yes to use it.",
}
_CLIENT_NAMES = {"claude-desktop": "Claude Desktop", "claude-code": "Claude Code"}


def privacy_note(plan: Plan, *, other: str | None = None, remove_ledger: bool = False) -> str:
    """What the client will be able to read — said before anything is printed to copy or written.

    ``other`` is the other Ordnung entry already in the config (:func:`other_entry_in`): with the
    rules tools, a ledger that stays readable must not be hidden behind "none of your data".
    """
    if not plan.rules_only:
        if other is None:
            return FULL_PRIVACY
        return (
            f"{FULL_PRIVACY} (“{other}” is there too; this server has the same rules tools, so you can "
            "remove that entry.)"
        )
    if other is None:
        return RULES_ONLY_PRIVACY
    if remove_ledger:
        return f"{RULES_ONLY_PRIVACY} “{other}”, which reads your ledger, will be removed."
    return ledger_left_note(plan)


def ledger_left_note(plan: Plan) -> str:
    """The warning when a rules-only install leaves the full server in the config."""
    return (
        f"{_CLIENT_NAMES[plan.client]} also has Ordnung with your data (“{FULL_SERVER_NAME}” in "
        f"{plan.path}): it can still read your ledger, and Claude gets the rules tools twice. Add "
        "--remove-ledger to take that entry out (the file is backed up first)."
    )


def what(plan: Plan) -> str:
    return "Ordnung's rules tools" if plan.rules_only else "Ordnung with your data"


def write_command(
    plan: Plan,
    *,
    data_dir: Path | None = None,
    config: Path | None = None,
    system: str | None = None,
    remove_ledger: bool = False,
) -> str:
    """The ``ordnung mcp install … --write`` command that does what the printed instructions say."""
    argv = ["ordnung", "mcp", "install", "--client", plan.client]
    if not plan.rules_only:
        argv.append("--with-ledger")
        if data_dir is not None:
            argv += ["--data-dir", str(data_dir)]
    if config is not None:
        argv += ["--config", str(config)]
    if remove_ledger:
        argv.append("--remove-ledger")
    return shell_join([*argv, "--write"], system=system)


def instructions(
    plan: Plan,
    *,
    data_dir: Path | None = None,
    config: Path | None = None,
    system: str | None = None,
    remove_ledger: bool = False,
) -> str:
    """What ``ordnung mcp install`` prints without ``--write`` (plain text, nothing wrapped).

    ``remove_ledger``: also say to take the full server's entry out of the file.
    """
    entry = render_json(plan.snippet).rstrip()
    again = write_command(plan, data_dir=data_dir, config=config, system=system, remove_ledger=remove_ledger)
    remove = f"To remove it again: {claude_code_remove_command(plan, system=system)}"
    full = Plan(client=plan.client, name=FULL_SERVER_NAME, entry={}, path=plan.path, rules_only=False)
    ledger = f"“{FULL_SERVER_NAME}” (Ordnung with your data)"
    take_out = [f"and take {ledger} out of it:"] if remove_ledger else []
    colon = "" if remove_ledger else ":"
    if plan.client == "claude-code" and not plan.rules_only:
        lines = [
            f"To add {what(plan)} to Claude Code for you, in this project only, run here:",
            f"  {claude_code_command(plan, system=system)}",
            "",
            "(Not in a .mcp.json: that file is usually committed and shared with the project.)",
            remove,
        ]
    elif plan.client == "claude-code":
        lines = [
            f"To add {what(plan)} to Claude Code for all your projects, run:",
            f"  {claude_code_command(plan, system=system)}",
            remove,
            f"If you gave a project {ledger} before, run this there to take it out:",
            f"  {claude_code_remove_command(full, system=system)}",
            "",
            "Or, for one project, add this entry to its .mcp.json (usually committed with the project;",
            f"the entry names this computer's Python, so others may need to change that path){colon}",
            *take_out,
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
            f"(keep the servers that are already there){colon}",
            *take_out,
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
    """What ``--write`` did (and on the other Ordnung entry, if the file has one); for a project's
    ``.mcp.json``, also that its entry names this computer's Python (module policy)."""
    target = f"“{plan.name}” in {result.path}"
    client = _CLIENT_NAMES[plan.client]
    if result.removed is not None:
        taken = f"took out “{result.removed}” (Ordnung with your data)"
        if result.status == "unchanged":
            line = f"{client} keeps {what(plan)} as {target}; {taken}."
        else:
            verb = "Added" if result.status == "added" else "Updated"
            line = f"{verb} {what(plan)} for {client} as {target}, and {taken}."
    elif result.status == "unchanged":
        line = f"{client} already has {what(plan)} as {target}; nothing changed."
    else:
        verb = "Added" if result.status == "added" else "Updated"
        line = f"{verb} {what(plan)} for {client} as {target}."
    if result.removed is None and result.other is not None and plan.rules_only:
        line += (
            f" It still has “{result.other}”, which reads your ledger: add --remove-ledger to take it out."
        )
    if result.path.name == CODE_PROJECT_CONFIG_NAME:
        line += f" {project_file_note(plan)}"
    return line


def project_file_note(plan: Plan) -> str:
    """What committing a project's ``.mcp.json`` with ``plan``'s entry would share."""
    return (
        f"The entry runs this computer's Python ({plan.entry['command']}): if you commit "
        f"{CODE_PROJECT_CONFIG_NAME}, that path shows others your folders and user name, and on their "
        "computers it needs changing."
    )
