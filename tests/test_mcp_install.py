"""``ordnung mcp install``: where Claude Desktop and Claude Code read their servers on each platform,
the entry Ordnung adds, and the merge policy of ``--write`` — never clobber other servers or
settings, back the file up first, refuse invalid JSON and change nothing — in temporary home
folders, through the functions and through the CLI."""

from __future__ import annotations

import json
import os
import stat
import sys
from datetime import datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ordnung.assistant import mcp_install
from ordnung.assistant.mcp_install import (
    FULL_SERVER_NAME,
    RULES_ONLY_PRIVACY,
    RULES_SERVER_NAME,
    InstallError,
    Plan,
    claude_code_command,
    claude_code_remove_command,
    desktop_config_path,
    instructions,
    merge_server,
    other_entry_in,
    plan_install,
    privacy_note,
    server_entry,
    write_command,
    write_config,
    written_message,
)
from ordnung.cli import app
from ordnung.config import Paths

NOW = datetime(2026, 9, 26, 10, 15, 30)
RULES_ENTRY = {"command": sys.executable, "args": ["-m", "ordnung", "mcp", "--rules-only"]}
EXISTING = {
    "globalShortcut": "Ctrl+Space",
    "mcpServers": {"files": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem"]}},
    "preferences": {"theme": "dark"},
}

runner = CliRunner(env={"COLUMNS": "200", "NO_COLOR": "1"})


def desktop_plan(home: Path, *, rules_only: bool = True, data_dir: Path | None = None) -> Plan:
    return plan_install(
        "claude-desktop", rules_only=rules_only, data_dir=data_dir, system="linux", env={}, home=home
    )


def settings_folder(home: Path) -> Path:
    folder = home / ".config" / "Claude"
    folder.mkdir(parents=True)
    return folder


# --------------------------------------------------------------------------------------------------
# what and where
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("system", "env", "expected"),
    [
        ("darwin", {}, "home/Library/Application Support/Claude/claude_desktop_config.json"),
        ("win32", {"APPDATA": "{tmp}/Roaming"}, "Roaming/Claude/claude_desktop_config.json"),
        ("win32", {}, "home/AppData/Roaming/Claude/claude_desktop_config.json"),
        ("linux", {}, "home/.config/Claude/claude_desktop_config.json"),
        ("linux", {"XDG_CONFIG_HOME": "{tmp}/xdg"}, "xdg/Claude/claude_desktop_config.json"),
    ],
)
def test_claude_desktop_config_per_platform(
    tmp_path: Path, system: str, env: dict[str, str], expected: str
) -> None:
    resolved = {key: value.replace("{tmp}", str(tmp_path)) for key, value in env.items()}
    path = desktop_config_path(system=system, env=resolved, home=tmp_path / "home")
    assert path == tmp_path / expected


def test_the_entries(tmp_path: Path) -> None:
    assert server_entry(rules_only=True) == (RULES_SERVER_NAME, RULES_ENTRY)
    name, entry = server_entry(rules_only=False, data_dir=tmp_path / "data" / ".." / "data")
    assert name == FULL_SERVER_NAME
    assert entry == {
        "command": sys.executable,
        "args": ["-m", "ordnung", "mcp", "--data-dir", str((tmp_path / "data").resolve())],
    }
    with pytest.raises(ValueError, match="data folder"):
        server_entry(rules_only=False)


def test_plans(tmp_path: Path) -> None:
    desktop = desktop_plan(tmp_path)
    assert desktop.path == tmp_path / ".config" / "Claude" / "claude_desktop_config.json"
    assert desktop.snippet == {"mcpServers": {RULES_SERVER_NAME: RULES_ENTRY}}
    code = plan_install("claude-code", rules_only=True, cwd=tmp_path / "project")
    assert code.path == tmp_path / "project" / ".mcp.json"
    custom = plan_install("claude-desktop", rules_only=True, config=tmp_path / "elsewhere.json")
    assert custom.path == tmp_path / "elsewhere.json"
    with pytest.raises(ValueError, match="client must be one of"):
        plan_install("chatgpt", rules_only=True)  # type: ignore[arg-type]


def test_claude_code_scopes_keep_the_ledger_private() -> None:
    """The rules tools may go into every project; the ledger only into this person's own project scope."""
    rules = plan_install("claude-code", rules_only=True, cwd=Path("/p"))
    full = plan_install("claude-code", rules_only=False, data_dir=Path("/d"), cwd=Path("/p"))
    assert claude_code_command(rules, system="linux").startswith(
        "claude mcp add --scope user ordnung_rules -- "
    )
    assert claude_code_command(full, system="linux").startswith("claude mcp add --scope local ordnung -- ")
    assert claude_code_remove_command(full, system="linux") == "claude mcp remove --scope local ordnung"
    assert claude_code_remove_command(rules, system="linux") == "claude mcp remove --scope user ordnung_rules"


def test_claude_code_command_is_quoted_for_the_shell() -> None:
    plan = Plan(
        client="claude-code",
        name=RULES_SERVER_NAME,
        entry={
            "command": "/Users/Sam Rivera/.local/bin/python",
            "args": ["-m", "ordnung", "mcp", "--rules-only"],
        },
        path=Path(".mcp.json"),
        rules_only=True,
    )
    assert claude_code_command(plan, system="linux") == (
        "claude mcp add --scope user ordnung_rules -- '/Users/Sam Rivera/.local/bin/python' -m ordnung mcp --rules-only"
    )
    assert claude_code_command(plan, system="win32") == (
        'claude mcp add --scope user ordnung_rules -- "/Users/Sam Rivera/.local/bin/python" -m ordnung mcp --rules-only'
    )


def test_printed_instructions(tmp_path: Path) -> None:
    desktop = instructions(desktop_plan(tmp_path))
    assert str(tmp_path / ".config" / "Claude" / "claude_desktop_config.json") in desktop
    assert json.dumps(RULES_ENTRY["args"][-1]) in desktop and '"ordnung_rules": {' in desktop
    assert (
        "  ordnung mcp install --client claude-desktop --write\n" in desktop
    )  # the rules tools: the default
    assert desktop.rstrip().endswith("Then restart Claude Desktop.")
    rules = instructions(plan_install("claude-code", rules_only=True, cwd=tmp_path), system="linux")
    assert "claude mcp add --scope user ordnung_rules -- " in rules and ".mcp.json" in rules
    assert "usually committed with the project" in rules and "this computer's Python" in rules
    assert "To remove it again: claude mcp remove --scope user ordnung_rules" in rules
    full = plan_install("claude-code", rules_only=False, data_dir=tmp_path / "my data", cwd=tmp_path)
    text = instructions(full, data_dir=tmp_path / "my data", system="linux")
    assert "claude mcp add --scope local ordnung -- " in text and "in this project only" in text
    assert '"mcpServers"' not in text and "--write" not in text  # the ledger is never offered for .mcp.json
    assert "To remove it again: claude mcp remove --scope local ordnung" in text
    full_desktop = desktop_plan(tmp_path, rules_only=False, data_dir=tmp_path / "my data")
    assert f"--with-ledger --data-dir '{tmp_path / 'my data'}' --write" in instructions(
        full_desktop, data_dir=tmp_path / "my data", system="linux"
    )
    assert write_command(full, config=tmp_path / "c.json").endswith(f"--config {tmp_path / 'c.json'} --write")


def test_printed_commands_are_quoted_for_windows() -> None:
    """cmd.exe does not understand POSIX single quotes."""
    plan = plan_install("claude-desktop", rules_only=False, data_dir=Path("/d"), system="win32", env={})
    command = write_command(plan, data_dir=Path("C:/Users/A B/Ordnung"), system="win32")
    assert command == (
        'ordnung mcp install --client claude-desktop --with-ledger --data-dir "C:/Users/A B/Ordnung" --write'
    )
    assert "'" not in instructions(plan, data_dir=Path("C:/Users/A B/Ordnung"), system="win32")


# --------------------------------------------------------------------------------------------------
# merging
# --------------------------------------------------------------------------------------------------


def test_merge_adds_next_to_everything_that_is_there() -> None:
    merged, status = merge_server(json.dumps(EXISTING), RULES_SERVER_NAME, RULES_ENTRY)
    assert status == "added"
    assert list(merged) == ["globalShortcut", "mcpServers", "preferences"]  # order kept
    assert merged["mcpServers"] == {**EXISTING["mcpServers"], RULES_SERVER_NAME: RULES_ENTRY}
    assert merged["preferences"] == EXISTING["preferences"]
    again, status = merge_server(json.dumps(merged), RULES_SERVER_NAME, RULES_ENTRY)
    assert status == "unchanged" and again == merged
    changed = {**RULES_ENTRY, "args": ["-m", "ordnung", "mcp", "--rules-only", "--x"]}
    updated, status = merge_server(json.dumps(merged), RULES_SERVER_NAME, changed)
    assert status == "updated" and updated["mcpServers"][RULES_SERVER_NAME] == changed
    assert updated["mcpServers"]["files"] == EXISTING["mcpServers"]["files"]


@pytest.mark.parametrize("text", [None, "", "  \n", "{}", '{"mcpServers": {}}'])
def test_merge_into_an_empty_config(text: str | None) -> None:
    merged, status = merge_server(text, RULES_SERVER_NAME, RULES_ENTRY)
    assert status == "added" and merged == {"mcpServers": {RULES_SERVER_NAME: RULES_ENTRY}}


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('{"mcpServers": {', "it is not valid JSON"),
        ("[1, 2]", "its top level is not a JSON object"),
        ('"text"', "its top level is not a JSON object"),
        ('{"mcpServers": []}', 'its "mcpServers" is not a JSON object'),
    ],
)
def test_merge_refuses_what_it_cannot_understand(text: str, message: str) -> None:
    with pytest.raises(InstallError, match=message):
        merge_server(text, RULES_SERVER_NAME, RULES_ENTRY)


# --------------------------------------------------------------------------------------------------
# writing
# --------------------------------------------------------------------------------------------------


def test_write_backs_up_then_merges(tmp_path: Path) -> None:
    config = settings_folder(tmp_path) / "claude_desktop_config.json"
    original = json.dumps(EXISTING, indent=4)
    config.write_text(original, encoding="utf-8")
    config.chmod(0o640)
    result = write_config(desktop_plan(tmp_path), now=NOW)
    assert result.status == "added" and result.path == config
    assert result.backup == config.with_name("claude_desktop_config.json.bak-20260926-101530")
    assert result.backup.read_text(encoding="utf-8") == original  # the untouched original
    data = json.loads(config.read_text(encoding="utf-8"))
    assert (
        data["mcpServers"]["files"] == EXISTING["mcpServers"]["files"]
        and data["globalShortcut"] == "Ctrl+Space"
    )
    assert data["mcpServers"][RULES_SERVER_NAME] == RULES_ENTRY
    assert stat.S_IMODE(config.stat().st_mode) == 0o640  # permissions kept
    assert config.read_text(encoding="utf-8").endswith("}\n")
    assert not [p for p in config.parent.iterdir() if p.name.endswith(".tmp")]  # no temp files left

    again = write_config(desktop_plan(tmp_path), now=NOW)
    assert again.status == "unchanged" and again.backup is None
    assert len(list(config.parent.glob("*.bak-*"))) == 1  # nothing written, nothing backed up

    full = write_config(desktop_plan(tmp_path, rules_only=False, data_dir=tmp_path / "data"), now=NOW)
    assert full.status == "added" and full.backup == config.with_name(
        f"{result.backup.name}-1"
    )  # never overwritten
    servers = json.loads(config.read_text(encoding="utf-8"))["mcpServers"]
    assert set(servers) == {"files", RULES_SERVER_NAME, FULL_SERVER_NAME}


def test_write_creates_a_new_file_privately(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    plan = plan_install("claude-code", rules_only=True, cwd=project)
    result = write_config(plan, now=NOW)
    assert result.status == "added" and result.backup is None
    assert json.loads((project / ".mcp.json").read_text(encoding="utf-8")) == plan.snippet
    if os.name == "posix":
        assert stat.S_IMODE((project / ".mcp.json").stat().st_mode) == 0o600


def test_write_refuses_invalid_json_and_changes_nothing(tmp_path: Path) -> None:
    config = settings_folder(tmp_path) / "claude_desktop_config.json"
    config.write_text('{"mcpServers": {"files": ', encoding="utf-8")
    with pytest.raises(InstallError, match=r"Nothing was changed: .* it is not valid JSON") as raised:
        write_config(desktop_plan(tmp_path), now=NOW)
    assert "Fix or move that file" in str(raised.value)
    assert config.read_text(encoding="utf-8") == '{"mcpServers": {"files": '
    assert list(config.parent.iterdir()) == [config]  # no backup, no temp file


def test_write_needs_claude_desktops_settings_folder(tmp_path: Path) -> None:
    with pytest.raises(InstallError, match="is Claude Desktop installed"):
        write_config(desktop_plan(tmp_path), now=NOW)
    assert not (tmp_path / ".config").exists()  # never creates an app's settings folder
    with pytest.raises(InstallError, match="does not exist"):
        write_config(plan_install("claude-code", rules_only=True, cwd=tmp_path / "missing"), now=NOW)
    named = plan_install("claude-desktop", rules_only=True, config=tmp_path / "elsewhere" / "config.json")
    with pytest.raises(InstallError) as raised:  # a file the person named: no talk of Claude Desktop
        write_config(named, now=NOW)
    assert str(raised.value) == f"The folder {tmp_path / 'elsewhere'} does not exist."


def test_write_through_a_symlink_keeps_the_link(tmp_path: Path) -> None:
    dotfiles = tmp_path / "dotfiles"
    dotfiles.mkdir()
    target = dotfiles / "claude.json"
    target.write_text(json.dumps(EXISTING), encoding="utf-8")
    link = settings_folder(tmp_path) / "claude_desktop_config.json"
    link.symlink_to(target)
    result = write_config(desktop_plan(tmp_path), now=NOW)
    assert link.is_symlink() and result.path == target
    assert RULES_SERVER_NAME in json.loads(target.read_text(encoding="utf-8"))["mcpServers"]
    assert result.backup is not None and result.backup.parent == dotfiles


def test_write_refuses_a_file_that_is_not_utf8_and_changes_nothing(tmp_path: Path) -> None:
    """Windows PowerShell 5.1's `>` writes UTF-16 with a byte-order mark: refused, never a traceback."""
    config = settings_folder(tmp_path) / "claude_desktop_config.json"
    utf16 = "\ufeff".encode("utf-16-le") + json.dumps(EXISTING).encode("utf-16-le")
    config.write_bytes(utf16)
    with pytest.raises(InstallError, match=r"Nothing was changed: .* it is not UTF-8 text") as raised:
        write_config(desktop_plan(tmp_path), now=NOW)
    assert "Save it as UTF-8" in str(raised.value)
    assert config.read_bytes() == utf16 and list(config.parent.iterdir()) == [config]


def test_the_ledger_is_never_written_into_a_projects_shared_mcp_json(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".mcp.json").write_text(json.dumps(EXISTING), encoding="utf-8")
    full = plan_install("claude-code", rules_only=False, data_dir=tmp_path / "data", cwd=project)
    with pytest.raises(InstallError, match="usually committed with the project") as raised:
        write_config(full, now=NOW)
    assert "claude mcp add --scope local" in str(raised.value)
    assert json.loads((project / ".mcp.json").read_text(encoding="utf-8")) == EXISTING
    assert list(project.iterdir()) == [project / ".mcp.json"]  # no backup either


def test_the_rules_tools_do_not_hide_a_ledger_left_in_the_config(tmp_path: Path) -> None:
    """Re-running the default install to take back ledger access must not say "none of your data"
    while the full server stays in the file."""
    config = settings_folder(tmp_path) / "claude_desktop_config.json"
    config.write_text(json.dumps(EXISTING), encoding="utf-8")
    full_plan = desktop_plan(tmp_path, rules_only=False, data_dir=tmp_path / "data")
    rules_plan = desktop_plan(tmp_path)
    assert other_entry_in(rules_plan) is None and privacy_note(rules_plan) == RULES_ONLY_PRIVACY
    write_config(full_plan, now=NOW)
    assert other_entry_in(rules_plan) == FULL_SERVER_NAME
    note = privacy_note(rules_plan, other=FULL_SERVER_NAME)
    assert "none of your data" not in note and "it can still read your ledger" in note
    assert "--remove-ledger" in note and "rules tools twice" in note

    kept = write_config(rules_plan, now=NOW)
    assert (kept.status, kept.other, kept.removed) == ("added", FULL_SERVER_NAME, None)
    assert "It still has “ordnung”, which reads your ledger" in written_message(rules_plan, kept)
    again = write_config(rules_plan, now=NOW)
    assert again.status == "unchanged" and again.other == FULL_SERVER_NAME
    assert written_message(rules_plan, again).endswith("add --remove-ledger to take it out.")

    backups = len(list(config.parent.glob("*.bak-*")))
    removed = write_config(rules_plan, now=NOW, remove_ledger=True)
    assert (removed.status, removed.removed, removed.other) == ("unchanged", FULL_SERVER_NAME, None)
    assert removed.backup is not None and len(list(config.parent.glob("*.bak-*"))) == backups + 1
    assert FULL_SERVER_NAME in json.loads(removed.backup.read_text(encoding="utf-8"))["mcpServers"]
    assert set(json.loads(config.read_text(encoding="utf-8"))["mcpServers"]) == {"files", RULES_SERVER_NAME}
    assert "took out “ordnung” (Ordnung with your data)" in written_message(rules_plan, removed)
    assert write_config(rules_plan, now=NOW, remove_ledger=True).status == "unchanged"  # nothing left to do

    # the full server notes the rules entry it duplicates; remove_ledger is for the rules tools only
    assert "“ordnung_rules” is there too" in privacy_note(full_plan, other=RULES_SERVER_NAME)
    with pytest.raises(ValueError, match="remove_ledger goes with the rules tools"):
        write_config(full_plan, remove_ledger=True)
    # an unreadable config is not "having" it (write_config reports that file)
    config.write_text("{oops", encoding="utf-8")
    assert other_entry_in(rules_plan) is None
    assert other_entry_in(desktop_plan(tmp_path / "nowhere")) is None


def test_instructions_to_take_the_ledger_out(tmp_path: Path) -> None:
    desktop = instructions(desktop_plan(tmp_path), remove_ledger=True, system="linux")
    assert (
        "(keep the servers that are already there)\nand take “ordnung” (Ordnung with your data) out of it:"
        in desktop
    )
    assert "  ordnung mcp install --client claude-desktop --remove-ledger --write\n" in desktop
    code = instructions(plan_install("claude-code", rules_only=True, cwd=tmp_path), system="linux")
    assert "run this there to take it out:\n  claude mcp remove --scope local ordnung\n" in code


def test_write_refuses_a_folder_and_reads_a_bom(tmp_path: Path) -> None:
    (settings_folder(tmp_path) / "claude_desktop_config.json").mkdir()
    with pytest.raises(InstallError, match="is not a file"):
        write_config(desktop_plan(tmp_path), now=NOW)
    bom = tmp_path / "bom.json"
    bom.write_bytes(b"\xef\xbb\xbf" + json.dumps(EXISTING).encode())
    plan = plan_install("claude-code", rules_only=True, config=bom)
    assert write_config(plan, now=NOW).status == "added"
    assert not bom.read_bytes().startswith(b"\xef\xbb\xbf")


# --------------------------------------------------------------------------------------------------
# the CLI, in a temporary home folder
# --------------------------------------------------------------------------------------------------


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "home"
    folder.mkdir()
    monkeypatch.setenv("HOME", str(folder))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(folder / ".config"))
    monkeypatch.setenv("APPDATA", str(folder / "AppData" / "Roaming"))
    monkeypatch.setattr(sys, "platform", "linux")
    return folder


def default_data_folder(home: Path) -> Path:
    """A database in the default data folder — what most people have."""
    folder = home / "data"
    folder.mkdir()
    Paths(folder).db.write_bytes(b"")
    return folder


def test_cli_installs_the_rules_tools_unless_the_ledger_is_asked_for(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The command most people type must not hand their ledger to the client (ADR 0008)."""
    monkeypatch.setenv("ORDNUNG_HOME", str(default_data_folder(home)))
    config = settings_folder(home) / "claude_desktop_config.json"
    result = runner.invoke(app, ["mcp", "install", "--client", "claude-desktop", "--write"])
    assert result.exit_code == 0, result.output
    assert set(json.loads(config.read_text(encoding="utf-8"))["mcpServers"]) == {RULES_SERVER_NAME}
    assert "Added Ordnung's rules tools" in result.output and "ledger" not in result.output


def test_cli_prints_without_writing(home: Path) -> None:
    result = runner.invoke(app, ["mcp", "install", "--client", "claude-desktop", "--rules-only"])
    assert result.exit_code == 0, result.output
    assert str(home / ".config" / "Claude" / "claude_desktop_config.json") in result.output
    assert '"ordnung_rules"' in result.output and "--write" in result.output
    assert "they read none of your data" in result.output
    assert not (home / ".config").exists()


def test_cli_writes_into_claude_desktop(home: Path) -> None:
    config = settings_folder(home) / "claude_desktop_config.json"
    config.write_text(json.dumps(EXISTING), encoding="utf-8")
    result = runner.invoke(app, ["mcp", "install", "--client", "claude-desktop", "--rules-only", "--write"])
    assert result.exit_code == 0, result.output
    assert "Added Ordnung's rules tools for Claude Desktop" in result.output
    assert "The previous version is saved as" in result.output and "Restart Claude Desktop" in result.output
    assert set(json.loads(config.read_text(encoding="utf-8"))["mcpServers"]) == {"files", RULES_SERVER_NAME}
    again = runner.invoke(app, ["mcp", "install", "--client", "claude-desktop", "--rules-only", "--write"])
    assert again.exit_code == 0 and "nothing changed" in again.output and "Restart" not in again.output


def test_cli_refuses_invalid_json(home: Path) -> None:
    config = settings_folder(home) / "claude_desktop_config.json"
    config.write_text("{oops", encoding="utf-8")
    result = runner.invoke(app, ["mcp", "install", "--client", "claude-desktop", "--rules-only", "--write"])
    assert result.exit_code == 1 and "not valid JSON" in result.stderr
    assert config.read_text(encoding="utf-8") == "{oops"


def test_cli_full_server_needs_a_database_and_warns_about_privacy_first(home: Path, tmp_path: Path) -> None:
    data = tmp_path / "data"
    ledger = ["mcp", "install", "--client", "claude-desktop", "--with-ledger", "--data-dir", str(data)]
    missing = runner.invoke(app, ledger)
    assert missing.exit_code == 1 and "There is no Ordnung database" in missing.stderr
    data.mkdir()
    Paths(data).db.write_bytes(b"")
    config = tmp_path / "claude.json"
    args = [*ledger, "--config", str(config)]
    printed = runner.invoke(app, args)
    assert printed.exit_code == 0, printed.output
    assert f"--data-dir {data.resolve()}" in printed.output
    assert "other MCP servers loaded there and, in Claude Code, its own shell and web tools" in printed.output
    assert not config.exists()
    written = runner.invoke(app, [*args, "--write"])
    assert written.exit_code == 0, written.output
    # the warning comes before the file is changed, not as a footnote after it
    assert written.output.index("read access to your Ordnung ledger") < written.output.index("Added Ordnung")
    entry = json.loads(config.read_text(encoding="utf-8"))["mcpServers"][FULL_SERVER_NAME]
    assert entry["args"] == ["-m", "ordnung", "mcp", "--data-dir", str(data.resolve())]


def test_cli_refuses_the_ledger_in_a_projects_mcp_json(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = default_data_folder(home)
    monkeypatch.chdir(tmp_path)
    args = ["mcp", "install", "--client", "claude-code", "--with-ledger", "--data-dir", str(data), "--write"]
    result = runner.invoke(app, args)
    assert result.exit_code == 1 and "usually committed with the project" in result.stderr
    assert not (tmp_path / ".mcp.json").exists()


@pytest.mark.parametrize(
    "before",
    [["--rules-only"], ["--data-dir", "/somewhere"], ["--print-config"]],
)
def test_cli_options_before_install_fail_loudly(
    home: Path, monkeypatch: pytest.MonkeyPatch, before: list[str]
) -> None:
    """`ordnung mcp --rules-only install …` used to drop the flag and install the whole ledger."""
    monkeypatch.setenv("ORDNUNG_HOME", str(default_data_folder(home)))
    config = settings_folder(home) / "claude_desktop_config.json"
    result = runner.invoke(
        app, ["mcp", *before, "install", "--client", "claude-desktop", "--with-ledger", "--write"]
    )
    assert result.exit_code == 1 and f"{before[0]} before “install” would not be used" in result.stderr
    assert "Put the options after it" in result.stderr
    assert not config.exists()


@pytest.mark.parametrize(
    "args",
    [
        ["mcp", "install", "--client", "claude-desktop", "--data-dir", "{data}"],
        ["--data-dir", "{data}", "mcp", "install", "--client", "claude-desktop"],  # the global option too
    ],
)
def test_cli_a_data_folder_without_the_ledger_is_a_mistake(
    home: Path, tmp_path: Path, args: list[str]
) -> None:
    result = runner.invoke(app, [arg.format(data=tmp_path) for arg in args])
    assert result.exit_code == 1 and "--data-dir would not be used" in result.stderr
    assert "--with-ledger" in result.stderr


@pytest.mark.parametrize(
    "args",
    [
        ["mcp", "--rules-only", "--data-dir", "{data}", "--print-config"],
        ["--data-dir", "{data}", "mcp", "--rules-only", "--print-config"],
    ],
)
def test_cli_serving_the_rules_tools_refuses_a_data_folder(
    home: Path, tmp_path: Path, args: list[str]
) -> None:
    result = runner.invoke(app, [arg.format(data=tmp_path) for arg in args])
    assert result.exit_code == 1 and "The rules tools read no data folder" in result.stderr
    assert result.stdout == ""


def test_cli_reinstalling_the_rules_tools_says_the_ledger_is_still_there(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ORDNUNG_HOME", str(default_data_folder(home)))
    config = settings_folder(home) / "claude_desktop_config.json"
    config.write_text(json.dumps(EXISTING), encoding="utf-8")
    desktop = ["mcp", "install", "--client", "claude-desktop"]
    assert runner.invoke(app, [*desktop, "--with-ledger", "--write"]).exit_code == 0
    rules = runner.invoke(app, [*desktop, "--write"])
    assert rules.exit_code == 0, rules.output
    assert "none of your data" not in rules.output
    assert "also has Ordnung with your data (“ordnung” in" in rules.output
    assert "It still has “ordnung”, which reads your ledger: add --remove-ledger" in rules.output
    assert set(json.loads(config.read_text(encoding="utf-8"))["mcpServers"]) == {
        "files",
        FULL_SERVER_NAME,
        RULES_SERVER_NAME,
    }
    printed = runner.invoke(app, [*desktop, "--remove-ledger"])
    assert printed.exit_code == 0 and "will be removed" in printed.output
    assert "--remove-ledger --write" in printed.output
    removed = runner.invoke(app, [*desktop, "--remove-ledger", "--write"])
    assert removed.exit_code == 0, removed.output
    assert (
        "took out “ordnung” (Ordnung with your data)" in removed.output
        and "Restart Claude Desktop" in removed.output
    )
    assert set(json.loads(config.read_text(encoding="utf-8"))["mcpServers"]) == {"files", RULES_SERVER_NAME}
    nothing = runner.invoke(app, [*desktop, "--remove-ledger", "--write"])
    assert nothing.exit_code == 0 and "There was no “ordnung” entry" in nothing.output
    both = runner.invoke(app, [*desktop, "--with-ledger", "--remove-ledger"])
    assert both.exit_code == 1 and "exclude each other" in both.stderr


def test_cli_errors_keep_paths_whole(home: Path) -> None:
    """A narrow terminal must not split a path over two lines: it could not be copied."""
    narrow = CliRunner(env={"COLUMNS": "60", "NO_COLOR": "1"})
    result = narrow.invoke(app, ["mcp", "install", "--client", "claude-desktop", "--write"])
    assert result.exit_code == 1
    folder = str(home / ".config" / "Claude")
    assert len(folder) > 30 and f"settings folder {folder} does not exist" in result.stderr


def test_cli_reports_a_config_that_is_not_utf8(home: Path) -> None:
    config = settings_folder(home) / "claude_desktop_config.json"
    config.write_bytes(b"\xff\xfe{\x00}\x00")
    result = runner.invoke(app, ["mcp", "install", "--client", "claude-desktop", "--write"])
    assert result.exit_code == 1 and isinstance(result.exception, SystemExit)  # a message, no traceback
    assert "not UTF-8 text" in result.stderr
    assert config.read_bytes() == b"\xff\xfe{\x00}\x00"


def test_cli_rejects_an_unknown_client(home: Path) -> None:
    result = runner.invoke(app, ["mcp", "install", "--client", "chatgpt", "--rules-only"])
    assert result.exit_code == 2


def test_cli_reports_an_unwritable_file(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings_folder(home)

    def denied(*args: object, **kwargs: object) -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(mcp_install, "_replace", denied)
    result = runner.invoke(app, ["mcp", "install", "--client", "claude-desktop", "--rules-only", "--write"])
    assert (
        result.exit_code == 1 and "Couldn't write" in result.stderr and "Permission denied" in result.stderr
    )
