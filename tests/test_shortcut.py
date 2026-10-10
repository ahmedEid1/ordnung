"""``ordnung shortcut``: the launcher per operating system (written into a temporary home), quoting of
awkward paths, the shell link format read back by a parser of its own, writing and removing only
Ordnung's own launcher, its state, the command, and ``serve --from-shortcut``, which it runs.

The launchers of every system are planned and written on every system. What needs the real system —
macOS opening the bundle, Windows reading and opening the ``.lnk`` — is skipped elsewhere and runs in
CI's other-systems job, which runs this whole file on macOS and Windows."""

from __future__ import annotations

import contextlib
import io
import json
import os
import plistlib
import re
import select
import shlex
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from platformdirs import user_data_dir
from typer.testing import CliRunner

from ordnung import autostart, cli, shortcut
from ordnung.cli import app
from ordnung.locking import DataDirLocked
from ordnung.server import ServerInfo
from ordnung.shortcut import (
    DESKTOP_FILE,
    ICO,
    LNK,
    LNK_MARK,
    MARK,
    ShortcutError,
    WindowsLink,
    desktop_quote,
    desktop_unquote,
    lnk_bytes,
    location,
    plan,
    read_lnk,
    remove,
    sh_quote,
    split_cmdline,
    state,
    write,
)

runner = CliRunner(env={"COLUMNS": "200", "NO_COLOR": "1"})
#: the real drawing (the tests replace it with a quick one, see ``quick_logo``)
DRAW_LOGO = shortcut.draw_logo

PY = "/opt/ordnung/venv/bin/python3"
PATH_ENV = "/home/sam/.local/bin:/usr/local/bin:/usr/bin:/bin"
FOLDER = Path("/home/sam/.local/share/ordnung")
#: the folders the design's prototype read back through GLib's own parser
AWKWARD = [
    "/home/sam/My Documents/ordnung",
    "/home/sam/100%/ordnung",
    "/home/sam/$HOME/x",
    '/home/sam/"q"/x',
    "/home/sam/back\\slash/x",
    "/home/sam/Ordnung – Größe/x",
    "/home/sam/`tick`/x",
    "/home/sam/a'b/x",
    "/home/sam/%f/x",
    "/home/sam/~/x;&|<>*?#()",
]
#: Windows folders that need care on a command line (no ", <, >, | or * can be in a Windows path)
WINDOWS_AWKWARD = [
    "C:\\Users\\Jürgen Müller\\AppData\\Local\\ordnung",
    "C:\\Users\\sam\\100% & more\\ordnung",
    "C:\\Users\\sam\\ends with a backslash\\",
    "C:\\Users\\sam\\%USERPROFILE%\\x",
    "C:\\Users\\sam\\a'b;c^d\\x",
    "\\\\server\\share\\two  spaces",
    "",
]

#: Linux's and macOS's launchers, simulated with POSIX folders. On Windows a POSIX folder gains a
#: drive (/home/sam becomes D:\home\sam); the tests with temporary folders run everywhere.
POSIX_ONLY = pytest.mark.skipif(sys.platform == "win32", reason="simulates a POSIX data folder")
WINDOWS_ONLY = pytest.mark.skipif(sys.platform != "win32", reason="needs the real Windows shell")
PLATFORMS = [pytest.param("linux", marks=POSIX_ONLY), "darwin", "win32"]


def invoke(*args: str, **kwargs: Any) -> Any:
    return runner.invoke(app, list(args), **kwargs)


def plain(output: str) -> str:
    """Help text without terminal styling (Typer forces Rich styling on CI, e.g. GITHUB_ACTIONS)."""
    return re.sub(r"\x1b\[[0-9;]*m", "", output)


def linux_env(**extra: str) -> dict[str, str]:
    return {"PATH": PATH_ENV, **extra}


def windows_env(root: Path) -> dict[str, str]:
    return {"APPDATA": str(root / "AppData" / "Roaming"), "LOCALAPPDATA": str(root / "AppData" / "Local")}


def env_for(platform: str, root: Path) -> dict[str, str]:
    return windows_env(root) if platform == "win32" else linux_env()


def exec_value(sc: shortcut.Shortcut) -> str:
    line = next(line for line in text_of(sc.files[0]).splitlines() if line.startswith("Exec="))
    return line.removeprefix("Exec=")


def text_of(file: shortcut.File) -> str:
    assert file.content is not None
    return file.content.decode("utf-8")


def file_named(sc: shortcut.Shortcut, name: str) -> shortcut.File:
    return next(file for file in sc.files if file.path.name == name)


@pytest.fixture(autouse=True)
def quick_logo(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Icons drawn at a fraction of the cost (the real drawing has a test of its own)."""
    from PIL import Image

    sizes: list[int] = []

    def small_logo(size: int) -> Image.Image:
        sizes.append(size)
        return Image.new("RGBA", (size, size), (15, 110, 102, 255))

    monkeypatch.setattr(shortcut, "draw_logo", small_logo)
    return sizes


# --------------------------------------------------------------------------------------------------
# what each system calls the launcher
# --------------------------------------------------------------------------------------------------


def test_each_system_has_its_launcher_and_the_menu_it_goes_into() -> None:
    assert shortcut.KINDS == {
        "linux": "app menu entry",
        "macos": "app in your Applications folder",
        "windows": "Start menu shortcut",
    }
    assert shortcut.WHERE == {
        "linux": "your app menu",
        "macos": "your Applications folder",
        "windows": "your Start menu",
    }
    assert set(shortcut.KINDS) == set(autostart.KINDS)
    state = shortcut.State(system="windows", path=Path("Ordnung.lnk"), added=False)
    assert state.kind == "Start menu shortcut" and state.ours and not state.current


def test_without_a_window_the_launcher_starts_nothing_and_says_so_with_exit_code_3() -> None:
    """The Mac bundle opens Terminal on that code; the CLI uses 1, 128+n and 130 for everything else."""
    assert shortcut.NO_WINDOW_EXIT == 3


# --------------------------------------------------------------------------------------------------
# Linux
# --------------------------------------------------------------------------------------------------


@POSIX_ONLY
def test_linux_writes_an_app_menu_entry_that_runs_serve_in_a_terminal(tmp_path: Path) -> None:
    home = tmp_path / "home"
    sc = plan(FOLDER, platform="linux", env=linux_env(), home=home, python=PY)
    assert sc.path == home / ".local" / "share" / "applications" / DESKTOP_FILE
    assert sc.kind == "app menu entry" and sc.link is None and [f.path for f in sc.files] == [sc.path]
    assert sc.argv == (PY, "-m", "ordnung", "--data-dir", str(FOLDER), "serve", "--from-shortcut")
    assert write(sc) == "added"
    text = sc.path.read_text(encoding="utf-8")
    assert text == text_of(sc.files[0]) and sc.shown() == text.rstrip("\n")
    lines = text.splitlines()
    assert lines[0] == f"# {MARK}" and lines[1] == "[Desktop Entry]"
    for line in ("Type=Application", "Name=Ordnung", "Terminal=true", "X-Ordnung-Shortcut=1"):
        assert line in lines
    assert (
        f'Exec="/usr/bin/env" "PATH={PATH_ENV}" "/opt/ordnung/venv/bin/python3" "-m" "ordnung" '
        '"--data-dir" "/home/sam/.local/share/ordnung" "serve" "--from-shortcut"'
    ) in lines
    assert sc.path.stat().st_mode & 0o777 == 0o600
    assert write(sc) == "unchanged"


@POSIX_ONLY
def test_linux_honours_xdg_data_home_and_a_port(tmp_path: Path) -> None:
    data_home = tmp_path / "data-home"
    sc = plan(FOLDER, port=8899, platform="linux", env=linux_env(XDG_DATA_HOME=str(data_home)), home=tmp_path)
    assert sc.path == data_home / "applications" / DESKTOP_FILE
    assert sc.argv[-3:] == ("--from-shortcut", "--port", "8899")
    assert exec_value(sc).endswith('"serve" "--from-shortcut" "--port" "8899"')
    default = plan(FOLDER, port=8765, platform="linux", env=linux_env(), home=tmp_path)
    assert default.argv[-1] == "--from-shortcut"


def test_other_unixes_get_the_app_menu_entry(tmp_path: Path) -> None:
    sc = plan(tmp_path / "d", platform="freebsd14", env=linux_env(), home=tmp_path)
    assert sc.system == "linux" and sc.path.name == DESKTOP_FILE


@POSIX_ONLY
@pytest.mark.parametrize("folder", AWKWARD)
def test_desktop_quoting_round_trips_awkward_paths(tmp_path: Path, folder: str) -> None:
    sc = plan(Path(folder), platform="linux", env={"PATH": "/a b:/c$d"}, home=tmp_path, python=PY)
    value = exec_value(sc)
    assert desktop_unquote(value) == ["/usr/bin/env", "PATH=/a b:/c$d", *sc.argv]
    # every % is doubled (a field code otherwise) and every backslash escaped by the string rule
    assert "%" not in value.replace("%%", "") and "\\" not in value.replace("\\\\", "")


def test_desktop_quote_rules() -> None:
    """The quoting rule escapes ", `, $ and \\; the string rule then doubles every backslash."""
    assert desktop_quote('a "b" \\ $c %d') == '"a \\\\"b\\\\" \\\\\\\\ \\\\$c %%d"'
    assert desktop_quote("`x`") == '"\\\\`x\\\\`"'
    assert desktop_unquote('"a \\\\"b\\\\" \\\\\\\\ \\\\$c %%d" plain') == ['a "b" \\ $c %d', "plain"]


@POSIX_ONLY
def test_no_path_no_env_wrapper(tmp_path: Path) -> None:
    sc = plan(FOLDER, platform="linux", env={}, home=tmp_path, python=PY)
    assert exec_value(sc).startswith('"/opt/ordnung/venv/bin/python3" "-m" "ordnung"')
    opted_out = plan(
        FOLDER, platform="linux", env={shortcut.TELEMETRY_OPT_OUT: "1"}, home=tmp_path, python=PY
    )
    assert desktop_unquote(exec_value(opted_out))[:3] == [
        "/usr/bin/env",
        f"{shortcut.TELEMETRY_OPT_OUT}=1",
        PY,
    ]


def test_the_icon_points_into_this_installation_or_is_left_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dist = tmp_path / "site packages" / "ordnung" / "web" / "dist"
    monkeypatch.setattr(shortcut, "web_dist_dir", lambda: dist)
    without = text_of(plan(tmp_path / "d", platform="linux", env={}, home=tmp_path).files[0])
    assert not any(line.startswith("Icon=") for line in without.splitlines())
    dist.mkdir(parents=True)
    (dist / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    with_icon = text_of(plan(tmp_path / "d", platform="linux", env={}, home=tmp_path).files[0])
    assert f"Icon={dist / 'favicon.svg'}".replace("\\", "\\\\") in with_icon.splitlines()


@POSIX_ONLY
def test_glib_reads_the_exec_line_back(tmp_path: Path) -> None:
    """The desktop's own parser (GLib), where the system Python has it."""
    probe = "import gi; gi.require_version('Gio', '2.0'); from gi.repository import Gio, GLib"
    system_python = shutil.which("python3", path="/usr/bin")
    if (
        system_python is None
        or subprocess.run([system_python, "-I", "-c", probe], capture_output=True).returncode
    ):
        pytest.skip("GLib's Python bindings aren't installed here")
    reader = (
        "import json, sys\n" + probe.replace("; ", "\n") + "\n"
        "info = Gio.DesktopAppInfo.new_from_filename(sys.argv[1])\n"
        "ok, argv = GLib.shell_parse_argv(info.get_commandline())\n"
        "print(json.dumps([word.replace('%%', '%') for word in argv]))\n"
    )
    for number, folder in enumerate(AWKWARD):
        sc = plan(
            Path(folder), platform="linux", env={"PATH": "/a b:/c$d"}, home=tmp_path / str(number), python=PY
        )
        write(sc)
        out = subprocess.run(
            [system_python, "-I", "-c", reader, str(sc.path)], capture_output=True, check=True
        )
        assert json.loads(out.stdout) == ["/usr/bin/env", "PATH=/a b:/c$d", *sc.argv], folder


# --------------------------------------------------------------------------------------------------
# macOS
# --------------------------------------------------------------------------------------------------


def test_macos_writes_an_app_bundle(tmp_path: Path, quick_logo: list[int]) -> None:
    from PIL import Image

    home = tmp_path / "home"
    folder = tmp_path / "Application Support" / "ordnung"
    sc = plan(folder, platform="darwin", env=linux_env(), home=home, python=PY)
    bundle = home / "Applications" / "Ordnung.app"
    assert sc.path == bundle and sc.kind == "app in your Applications folder"
    contents = bundle / "Contents"
    expected = [
        contents / "Info.plist",
        contents / "MacOS" / "Ordnung",
        contents / "Resources" / "Ordnung.command",
        contents / "Resources" / "Ordnung.icns",
    ]
    assert [f.path for f in sc.files] == expected
    assert not bundle.exists() and quick_logo == []  # planning draws nothing
    assert write(sc) == "added"
    assert all(path.is_file() for path in expected)
    if os.name == "posix":
        modes = [path.stat().st_mode & 0o777 for path in expected]
        assert modes == [0o600, 0o700, 0o700, 0o600]

    info = plistlib.loads(expected[0].read_bytes())
    assert info == {
        "CFBundleExecutable": "Ordnung",
        "CFBundleIdentifier": "local.ordnung.shortcut",
        "CFBundleName": "Ordnung",
        "CFBundleDisplayName": "Ordnung",
        "CFBundlePackageType": "APPL",
        "CFBundleIconFile": "Ordnung",
        "LSUIElement": True,
        "OrdnungShortcut": MARK,
    }
    command = " ".join(sh_quote(arg) for arg in sc.argv)
    check = expected[1].read_text(encoding="utf-8").splitlines()
    assert check[0] == "#!/bin/sh" and check[1] == f"# {MARK}"
    assert f"{command} >/dev/null 2>&1 && exit 0" in check
    assert check[-1] == 'exec /usr/bin/open -a Terminal "$(dirname "$0")/../Resources/Ordnung.command"'
    window = expected[2].read_text(encoding="utf-8").splitlines()
    assert window[0] == "#!/bin/sh" and f"export PATH={sh_quote(PATH_ENV)}" in window
    assert window[-1] == f"exec {command}" and command.endswith("'serve' '--from-shortcut'")
    with Image.open(expected[3]) as icon:
        assert icon.format == "ICNS"
    assert sorted(set(quick_logo)) == [16, 32, 64, 128, 256, 512]
    assert "Contents/Info.plist:" in sc.shown() and "Contents/Resources/Ordnung.icns" in sc.shown()

    quick_logo.clear()
    assert write(sc) == "unchanged" and quick_logo == []  # the icon is there: not drawn again


@POSIX_ONLY
@pytest.mark.parametrize("folder", AWKWARD)
def test_sh_quoting_round_trips_awkward_paths(tmp_path: Path, folder: str) -> None:
    sc = plan(Path(folder), platform="darwin", env={"PATH": "/a b:/c$d'e"}, home=tmp_path, python=PY)
    window = text_of(file_named(sc, "Ordnung.command")).splitlines()
    assert shlex.split(window[-1]) == ["exec", *sc.argv]
    assert shlex.split(next(line for line in window if line.startswith("export "))) == [
        "export",
        "PATH=/a b:/c$d'e",
    ]
    check = text_of(file_named(sc, "Ordnung")).splitlines()
    words = shlex.split(next(line for line in check if line.endswith("&& exit 0")))
    assert words[: len(sc.argv)] == list(sc.argv) and words[len(sc.argv)] == ">/dev/null"


@pytest.mark.skipif(os.name != "posix" or shutil.which("sh") is None, reason="runs the scripts with sh")
@pytest.mark.parametrize("folder", ["My Documents/$HOME `x` 'q' \"d\" \\ %f"])
def test_the_bundle_s_scripts_run_ordnung_with_the_recorded_path(tmp_path: Path, folder: str) -> None:
    out = tmp_path / "argv.txt"
    python = tmp_path / "bin dir" / "python"
    python.parent.mkdir()
    python.write_text(f'#!/bin/sh\n{{ echo "$PATH"; printf "%s\\n" "$@"; }} > {sh_quote(str(out))}\n')
    python.chmod(0o755)
    sc = plan(
        tmp_path / folder, platform="darwin", env={"PATH": "/x y:/bin"}, home=tmp_path, python=str(python)
    )
    write(sc)
    for script in ("MacOS/Ordnung", "Resources/Ordnung.command"):
        out.unlink(missing_ok=True)
        # exits 0: the windowless check stops there and never runs `open`
        subprocess.run(["sh", str(sc.path / "Contents" / script)], check=True, timeout=30)
        assert out.read_text(encoding="utf-8").splitlines() == ["/x y:/bin", *sc.argv[1:]], script


def test_remove_takes_out_only_the_bundle_s_own_files(tmp_path: Path) -> None:
    sc = plan(tmp_path / "data", platform="darwin", env=linux_env(), home=tmp_path, python=PY)
    write(sc)
    extra = sc.path / "Contents" / "Resources" / "notes.txt"
    extra.write_text("mine", encoding="utf-8")
    removed = remove(sc)
    assert sorted(removed) == sorted(f.path for f in sc.files)
    assert extra.read_text(encoding="utf-8") == "mine" and sc.path.is_dir()
    assert not (sc.path / "Contents" / "MacOS").exists()  # empty, and only Ordnung's

    # what is left isn't an app: adding Ordnung again fills it, replacing nothing
    assert not state(platform="darwin", env=linux_env(), home=tmp_path).added
    assert write(sc) == "added" and extra.read_text(encoding="utf-8") == "mine"
    extra.unlink()
    remove(sc)
    assert not sc.path.exists() and (tmp_path / "Applications").is_dir()


def test_a_bundle_folder_holding_a_file_of_the_shortcut_s_name_is_someone_else_s(tmp_path: Path) -> None:
    sc = plan(tmp_path / "data", platform="darwin", env=linux_env(), home=tmp_path, python=PY)
    script = sc.path / "Contents" / "MacOS" / "Ordnung"
    script.parent.mkdir(parents=True)
    script.write_text("#!/bin/sh\necho another app\n", encoding="utf-8")
    with pytest.raises(ShortcutError, match="wasn't written by"):
        write(sc)
    assert script.read_text(encoding="utf-8") == "#!/bin/sh\necho another app\n"
    assert not (sc.path / "Contents" / "Info.plist").exists()


@pytest.mark.skipif(sys.platform != "darwin", reason="needs macOS's Launch Services")
def test_the_bundle_opens_through_launch_services(tmp_path: Path) -> None:
    session = subprocess.run(["launchctl", "managername"], capture_output=True, text=True)
    if session.stdout.strip() != "Aqua":
        pytest.skip("no GUI session to open an app in")
    out = tmp_path / "argv.txt"
    python = tmp_path / "python"
    python.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > {sh_quote(str(out))}\nexit 0\n')
    python.chmod(0o755)
    sc = plan(
        tmp_path / "data", platform="darwin", env={"PATH": "/usr/bin:/bin"}, home=tmp_path, python=str(python)
    )
    write(sc)
    subprocess.run(["open", "-W", "-n", str(sc.path)], check=True, timeout=60)
    assert out.read_text(encoding="utf-8").splitlines() == list(sc.argv[1:])


# --------------------------------------------------------------------------------------------------
# Windows: the shell link, written and read in pure Python
# --------------------------------------------------------------------------------------------------

LINK_CLSID = bytes.fromhex("0114020000000000C000000000000046")
FLAGS = {
    "HasLinkTargetIDList": 0x1,
    "HasLinkInfo": 0x2,
    "HasName": 0x4,
    "HasRelativePath": 0x8,
    "HasWorkingDir": 0x10,
    "HasArguments": 0x20,
    "HasIconLocation": 0x40,
    "IsUnicode": 0x80,
    "HasExpString": 0x200,
}


def _nul_terminated(data: bytes, at: int, width: int) -> bytes:
    end = at
    while data[end : end + width] != b"\0" * width:
        end += width
        assert end < len(data), "a string runs past its structure"
    return data[at:end]


def parse_shell_link(data: bytes) -> dict[str, Any]:
    """Every field of a shell link (MS-SHLLINK 2.1-2.5), read independently of ``ordnung.shortcut``:
    the header, the LinkInfo with its VolumeID and both local base paths, the StringData, the
    EnvironmentVariableDataBlock (2.5.4) and the terminal block — asserting the sizes and offsets on
    the way."""
    header = struct.unpack_from("<I16sIIQQQIiIHHII", data, 0)
    size, clsid, flags, attributes, created, accessed, written, file_size, icon_index, show, hotkey = header[
        :11
    ]
    assert size == 0x4C and clsid == LINK_CLSID and header[11:] == (0, 0, 0)
    assert (created, accessed, written, file_size, icon_index, hotkey, attributes) == (0, 0, 0, 0, 0, 0, 0)
    names = {name for name, bit in FLAGS.items() if flags & bit}
    assert flags & ~sum(FLAGS.values()) == 0
    at = 0x4C
    assert "HasLinkTargetIDList" not in names  # LinkInfo alone names the target
    info_size, info_header, info_flags, volume_at, base_at, network_at, suffix_at, wide_at, wide_suffix_at = (
        struct.unpack_from("<9I", data, at)
    )
    info = data[at : at + info_size]
    assert info_header == 0x24 and info_flags == 0x1 and network_at == 0  # VolumeIDAndLocalBasePath
    assert volume_at == info_header
    volume_size, drive_type, _serial, label_at = struct.unpack_from("<4I", info, volume_at)
    assert drive_type == 3 and label_at == 0x10  # DRIVE_FIXED, an ANSI label
    assert _nul_terminated(info, volume_at + label_at, 1) == b""
    assert base_at == volume_at + volume_size
    ansi_target = _nul_terminated(info, base_at, 1).decode("cp1252")
    assert suffix_at == base_at + len(ansi_target.encode("cp1252")) + 1
    assert _nul_terminated(info, suffix_at, 1) == b"" and wide_at == suffix_at + 1
    target = _nul_terminated(info, wide_at, 2).decode("utf-16-le")
    assert wide_suffix_at == wide_at + len(target.encode("utf-16-le")) + 2
    assert _nul_terminated(info, wide_suffix_at, 2) == b"" and wide_suffix_at + 2 == info_size
    at += info_size
    strings = {}
    for name in ("HasName", "HasRelativePath", "HasWorkingDir", "HasArguments", "HasIconLocation"):
        if name in names:
            (count,) = struct.unpack_from("<H", data, at)
            strings[name] = data[at + 2 : at + 2 + 2 * count].decode("utf-16-le")
            at += 2 + 2 * count
    # the target again, where Windows' shell reads what a link without an ID list opens
    assert "HasExpString" in names
    block_size, signature = struct.unpack_from("<II", data, at)
    assert (block_size, signature) == (0x314, 0xA0000001)
    exp_ansi = _nul_terminated(data[at + 8 : at + 8 + 260] + b"\0", 0, 1).decode("cp1252")
    exp_wide = _nul_terminated(data[at + 268 : at + block_size] + b"\0\0", 0, 2).decode("utf-16-le")
    assert exp_ansi == ansi_target and exp_wide == target
    at += block_size
    assert data[at:] == b"\0\0\0\0", "the extra data ends with the terminal block"
    return {
        "flags": names,
        "show": show,
        "ansi_target": ansi_target,
        "target": target,
        "description": strings.get("HasName"),
        "relative_path": strings.get("HasRelativePath"),
        "working_dir": strings.get("HasWorkingDir"),
        "arguments": strings.get("HasArguments"),
        "icon": strings.get("HasIconLocation"),
    }


def test_windows_plans_a_start_menu_shortcut(tmp_path: Path, quick_logo: list[int]) -> None:
    from PIL import Image

    env = windows_env(tmp_path)
    folder = tmp_path / "Jürgen Müller" / "AppData" / "Local" / "ordnung"
    sc = plan(folder, platform="win32", env=env, home=tmp_path, python=PY)
    lnk = tmp_path / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / LNK
    icon = tmp_path / "AppData" / "Local" / "Programs" / "Ordnung" / ICO
    assert sc.path == lnk and sc.kind == "Start menu shortcut"
    assert sc.link == WindowsLink(
        target=PY,
        arguments=f'-m ordnung --data-dir "{folder}" serve --from-shortcut',
        working_dir=str(tmp_path),
        icon=str(icon),
        description=f"Ordnung, your paperwork secretary {LNK_MARK}",
        show=1,
    )
    assert [f.path for f in sc.files] == [icon, lnk] and file_named(sc, LNK).content == lnk_bytes(sc.link)
    assert "Arguments: -m ordnung --data-dir" in sc.shown() and f"Icon: {icon}" in sc.shown()
    assert write(sc) == "added"
    assert read_lnk(lnk.read_bytes()) == sc.link
    with Image.open(icon) as drawn:
        assert drawn.format == "ICO" and (256, 256) in drawn.info["sizes"]
    assert MARK.encode() in icon.read_bytes()  # the icon is marked as Ordnung's own too
    assert write(sc) == "unchanged"


def test_a_target_too_long_for_a_windows_shortcut_is_refused() -> None:
    """The block Windows reads the target from holds MAX_PATH characters: a longer path is refused, not cut."""
    fits = WindowsLink(
        target="C:\\" + "a" * 240 + "\\python.exe", arguments="", working_dir="", icon="", description=""
    )
    assert len(fits.target) < 260 and read_lnk(lnk_bytes(fits)) == fits
    too_long = WindowsLink(
        target="C:\\" + "a" * 260 + "\\python.exe", arguments="", working_dir="", icon="", description=""
    )
    with pytest.raises(ShortcutError, match="this long"):
        lnk_bytes(too_long)


@pytest.mark.parametrize("folder", WINDOWS_AWKWARD)
def test_the_link_file_follows_the_shell_link_format(folder: str) -> None:
    link = WindowsLink(
        target="C:\\Users\\Jürgen Müller\\pipx\\venvs\\ordnung\\Scripts\\python.exe",
        arguments=subprocess.list2cmdline(
            ["-m", "ordnung", "--data-dir", folder, "serve", "--from-shortcut"]
        ),
        working_dir="C:\\Users\\Jürgen Müller",
        icon="C:\\Users\\Jürgen Müller\\AppData\\Local\\Programs\\Ordnung\\Ordnung.ico",
        description=f"Ordnung, your paperwork secretary {LNK_MARK}",
    )
    parsed = parse_shell_link(lnk_bytes(link))
    assert parsed["flags"] == {
        "HasLinkInfo",
        "HasName",
        "HasWorkingDir",
        "HasArguments",
        "HasIconLocation",
        "IsUnicode",
        "HasExpString",
    }
    assert parsed["target"] == link.target and parsed["ansi_target"] == link.target  # cp1252 has ü
    assert (parsed["description"], parsed["working_dir"], parsed["arguments"], parsed["icon"]) == (
        link.description,
        link.working_dir,
        link.arguments,
        link.icon,
    )
    assert parsed["show"] == 1 and parsed["relative_path"] is None
    assert read_lnk(lnk_bytes(link)) == link
    assert split_cmdline(link.arguments) == [
        "-m",
        "ordnung",
        "--data-dir",
        folder,
        "serve",
        "--from-shortcut",
    ]


def test_a_target_outside_the_ansi_code_page_keeps_its_unicode_path() -> None:
    link = WindowsLink(
        target="C:\\Users\\Αθηνά\\python.exe", arguments="", working_dir="", icon="", description=""
    )
    parsed = parse_shell_link(lnk_bytes(link))
    assert parsed["target"] == link.target and parsed["ansi_target"] == "C:\\Users\\?????\\python.exe"
    assert read_lnk(lnk_bytes(link)) == link


def test_what_isnt_a_whole_shell_link_reads_as_none() -> None:
    whole = lnk_bytes(WindowsLink("a", "b", "c", "d", "e"))
    assert read_lnk(whole) is not None
    for data in (b"", b"not a link", b"\x4c\0\0\0" + b"\0" * 72, whole[:-10], whole[:-4], whole[:100]):
        assert read_lnk(data) is None, data


def test_the_windows_command_line_splits_as_python_reads_it() -> None:
    awkward = ["a b", 'say "hi"', "back\\", "back\\\\", 'x\\"y', "", "tab\there", "C:\\a b\\"]
    assert split_cmdline(subprocess.list2cmdline(awkward)) == awkward
    assert split_cmdline('"a b" c\\\\"d e" f\\\\\\"g') == ["a b", "c\\d e", 'f\\"g']


def test_windows_without_appdata_uses_the_home_folder(tmp_path: Path) -> None:
    sc = plan(tmp_path / "d", platform="win32", env={}, home=tmp_path, python=PY)
    assert (
        sc.path
        == tmp_path / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / LNK
    )
    assert sc.link is not None
    assert sc.link.icon == str(tmp_path / "AppData" / "Local" / "Programs" / "Ordnung" / ICO)


def test_windows_never_replaces_or_removes_an_icon_it_didn_t_write(tmp_path: Path) -> None:
    sc = plan(tmp_path / "d", platform="win32", env=windows_env(tmp_path), home=tmp_path, python=PY)
    icon = sc.files[0].path
    icon.parent.mkdir(parents=True)
    icon.write_bytes(b"another program's icon")
    with pytest.raises(ShortcutError, match="wasn't written by `ordnung shortcut`"):
        write(sc)
    assert not sc.path.exists() and icon.read_bytes() == b"another program's icon"
    sc.path.parent.mkdir(parents=True)
    sc.path.write_bytes(file_named(sc, LNK).content or b"")  # a link of ours next to that icon
    assert remove(sc) == [sc.path]
    assert icon.read_bytes() == b"another program's icon"


def test_windows_removes_the_icon_first_and_also_once_the_shortcut_was_deleted_by_hand(
    tmp_path: Path,
) -> None:
    """Right-click → Delete takes a Start-menu entry out; ``--remove`` still takes away the icon Ordnung
    drew. The mark goes last: the icon first, then the ``.lnk``."""
    env = windows_env(tmp_path)
    sc = plan(tmp_path / "d", platform="win32", env=env, home=tmp_path, python=PY)
    icon = file_named(sc, ICO).path
    assert write(sc) == "added"
    assert shortcut.removable(sc) == [icon, sc.path]
    sc.path.unlink()  # deleted by hand in the Start menu
    where = location(platform="win32", env=env, home=tmp_path)
    assert shortcut.removable(where) == [icon]
    assert remove(where) == [icon] and not icon.exists() and not icon.parent.exists()
    assert remove(where) == []


@pytest.mark.parametrize(
    "broken", [b"<?xml version='1.0'?><plist version='1.0'><dict><key>CFBundleName</key>", b""]
)
def test_a_property_list_cut_short_is_someone_else_s(tmp_path: Path, broken: bytes) -> None:
    """A bundle whose Info.plist doesn't parse is read as someone else's: never replaced or removed, and
    Settings' status still answers."""
    sc = plan(tmp_path / "d", platform="darwin", env={}, home=tmp_path, python=PY)
    info = sc.path / "Contents" / "Info.plist"
    info.parent.mkdir(parents=True)
    info.write_bytes(broken)
    found = state(tmp_path / "d", platform="darwin", env={}, home=tmp_path, python=PY)
    assert found.added and not found.ours
    for action in (write, shortcut.removable, shortcut.check):
        with pytest.raises(ShortcutError, match="wasn't written by `ordnung shortcut`"):
            action(sc)
    assert info.read_bytes() == broken


@WINDOWS_ONLY
def test_the_shell_reads_the_link_back(tmp_path: Path) -> None:
    """Windows' own reader (test only: the shortcut itself runs no PowerShell and no COM)."""
    folder = tmp_path / "Jürgen Müller" / "ordnung"
    sc = plan(folder, platform="win32", env=windows_env(tmp_path), home=tmp_path, python=sys.executable)
    write(sc)
    script = (
        "[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:ORDNUNG_TEST_LNK); "
        "ConvertTo-Json @{target=$s.TargetPath; arguments=$s.Arguments; working_dir=$s.WorkingDirectory; "
        "icon=$s.IconLocation; description=$s.Description; show=$s.WindowStyle}"
    )
    out = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        env={**os.environ, "ORDNUNG_TEST_LNK": str(sc.path)},
        capture_output=True,
        check=True,
        timeout=120,
    )
    seen = json.loads(out.stdout.decode("utf-8-sig"))  # PowerShell may write a BOM first
    assert sc.link is not None
    assert Path(seen["target"]).resolve() == Path(sys.executable).resolve()
    assert seen["arguments"] == sc.link.arguments and seen["description"] == sc.link.description
    assert seen["working_dir"] == str(tmp_path) and seen["show"] == 1
    assert Path(seen["icon"].rsplit(",", 1)[0]).resolve() == Path(sc.link.icon).resolve()


@WINDOWS_ONLY
def test_windows_arguments_round_trip_through_the_shell_s_parser(tmp_path: Path) -> None:
    import ctypes
    from ctypes import wintypes

    to_argv = ctypes.windll.shell32.CommandLineToArgvW  # type: ignore[attr-defined]
    to_argv.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    to_argv.restype = ctypes.POINTER(wintypes.LPWSTR)
    for folder in WINDOWS_AWKWARD[:-1]:
        sc = plan(
            Path(folder), platform="win32", env=windows_env(tmp_path), home=tmp_path, python=sys.executable
        )
        assert sc.link is not None
        count = ctypes.c_int()
        words = to_argv(f'"{sc.link.target}" {sc.link.arguments}', ctypes.byref(count))
        try:
            assert [words[i] for i in range(count.value)] == list(sc.argv), folder
        finally:
            ctypes.windll.kernel32.LocalFree(words)  # type: ignore[attr-defined]


@WINDOWS_ONLY
def test_the_link_opens_ordnung(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = tmp_path / "fake" / "ordnung"
    fake.mkdir(parents=True)
    out = tmp_path / "argv.json"
    (fake / "__init__.py").write_text("", encoding="utf-8")
    (fake / "__main__.py").write_text(
        "import json, os, sys\n"
        "part = os.environ['ORDNUNG_TEST_ARGV'] + '.part'\n"
        "with open(part, 'w', encoding='utf-8') as handle:\n"
        "    json.dump(sys.argv[1:], handle)\n"
        "os.replace(part, os.environ['ORDNUNG_TEST_ARGV'])\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PYTHONPATH", str(tmp_path / "fake"))
    monkeypatch.setenv("ORDNUNG_TEST_ARGV", str(out))
    folder = tmp_path / "Jürgen Müller" / "ordnung"
    sc = plan(folder, platform="win32", env=windows_env(tmp_path), home=tmp_path, python=sys.executable)
    write(sc)
    os.startfile(sc.path)  # type: ignore[attr-defined]
    deadline = time.monotonic() + 20
    while not out.exists() and time.monotonic() < deadline:
        time.sleep(0.2)
    assert json.loads(out.read_text(encoding="utf-8")) == [
        "--data-dir",
        str(folder),
        "serve",
        "--from-shortcut",
    ]


# --------------------------------------------------------------------------------------------------
# every system
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("platform", ["linux", "darwin", "win32"])
def test_a_line_break_in_any_value_is_refused(tmp_path: Path, platform: str) -> None:
    env = env_for(platform, tmp_path)
    with pytest.raises(ShortcutError, match="line break"):
        plan(tmp_path / "a\nb", platform=platform, env=env, home=tmp_path, python=PY)
    with pytest.raises(ShortcutError, match="line break"):
        plan(tmp_path / "d", platform=platform, env=env, home=tmp_path, python="/opt/py\r/python")
    if platform != "win32":
        with pytest.raises(ShortcutError, match="line break"):
            plan(tmp_path / "d", platform=platform, env={"PATH": "/bin\n/x"}, home=tmp_path, python=PY)


def _foreign_launcher(sc: shortcut.Shortcut) -> list[Path]:
    """A launcher at ``sc``'s place that ``ordnung shortcut`` didn't write; returns its files."""
    if sc.system == "linux":
        sc.path.parent.mkdir(parents=True)
        sc.path.write_text(
            "[Desktop Entry]\nType=Application\nName=Ordnung\nExec=ordnung serve\n", encoding="utf-8"
        )
        return [sc.path]
    if sc.system == "macos":
        info = sc.path / "Contents" / "Info.plist"
        info.parent.mkdir(parents=True)
        info.write_bytes(plistlib.dumps({"CFBundleName": "Ordnung", "CFBundleExecutable": "Ordnung"}))
        return [info]
    sc.path.parent.mkdir(parents=True)
    assert sc.link is not None
    sc.path.write_bytes(lnk_bytes(WindowsLink(sc.link.target, "", "", "", "Ordnung")))
    return [sc.path]


@pytest.mark.parametrize("platform", PLATFORMS)
def test_a_launcher_not_written_by_ordnung_is_never_replaced_or_removed(
    tmp_path: Path, platform: str
) -> None:
    sc = plan(tmp_path / "d", platform=platform, env=env_for(platform, tmp_path), home=tmp_path, python=PY)
    files = _foreign_launcher(sc)
    before = [path.read_bytes() for path in files]
    for action in (write, remove, shortcut.removable):
        with pytest.raises(
            ShortcutError, match="wasn't written by `ordnung shortcut`, so it was left as it is"
        ):
            action(sc)
    assert [path.read_bytes() for path in files] == before
    found = state(
        tmp_path / "d", platform=platform, env=env_for(platform, tmp_path), home=tmp_path, python=PY
    )
    assert found.added and not found.ours and not found.current and found.data_dir is None


@pytest.mark.parametrize("platform", PLATFORMS)
def test_unreadable_bytes_at_the_launcher_s_place_count_as_someone_else_s(
    tmp_path: Path, platform: str
) -> None:
    sc = plan(tmp_path / "d", platform=platform, env=env_for(platform, tmp_path), home=tmp_path, python=PY)
    target = sc.path / "Contents" / "Info.plist" if platform == "darwin" else sc.path
    target.parent.mkdir(parents=True)
    target.write_bytes(b"\xff\xfe\x00 not text")
    with pytest.raises(ShortcutError):
        write(sc)
    assert target.read_bytes() == b"\xff\xfe\x00 not text"


@POSIX_ONLY
def test_a_link_at_the_launcher_s_place_is_never_followed(tmp_path: Path) -> None:
    sc = plan(tmp_path / "d", platform="linux", env={}, home=tmp_path, python=PY)
    elsewhere = tmp_path / "dotfiles" / DESKTOP_FILE
    elsewhere.parent.mkdir()
    elsewhere.write_bytes(sc.files[0].content or b"")
    sc.path.parent.mkdir(parents=True)
    sc.path.symlink_to(elsewhere)
    with pytest.raises(ShortcutError):
        write(sc)
    assert sc.path.is_symlink()


@pytest.mark.parametrize("platform", PLATFORMS)
def test_state_says_added_which_folder_and_whether_current(tmp_path: Path, platform: str) -> None:
    env = env_for(platform, tmp_path)
    folder = tmp_path / "data"

    def found(**kwargs: Any) -> shortcut.State:
        return state(platform=platform, env=env, home=tmp_path, **{"python": PY, **kwargs})

    nothing = found(data_dir=folder)
    assert not nothing.added and nothing.path == location(platform=platform, env=env, home=tmp_path).path
    write(plan(folder, port=8899, platform=platform, env=env, home=tmp_path, python=PY))
    here = found(data_dir=folder)
    assert here.added and here.ours and here.data_dir == folder and here.current
    assert found().current  # its own folder
    assert not found(data_dir=folder, python="/moved/python3").current
    other = found(data_dir=tmp_path / "other")
    assert other.added and other.data_dir == folder and not other.current
    # the recorded variables don't count: they differ between terminals
    write(
        plan(
            folder, port=8899, platform=platform, env={**env, "PATH": "/elsewhere"}, home=tmp_path, python=PY
        )
    )
    assert found(data_dir=folder).current


@pytest.mark.parametrize("platform", ["darwin", "win32"])  # the app menu entry is a single file
def test_a_launcher_missing_a_file_is_not_current_and_writing_restores_it(
    tmp_path: Path, platform: str
) -> None:
    env = env_for(platform, tmp_path)
    sc = plan(tmp_path / "data", platform=platform, env=env, home=tmp_path, python=PY)
    write(sc)
    icon = next(f.path for f in sc.files if f.content is None)
    icon.unlink()
    assert not state(tmp_path / "data", platform=platform, env=env, home=tmp_path, python=PY).current
    assert write(sc) == "updated" and icon.is_file()


@pytest.mark.parametrize("platform", PLATFORMS)
def test_state_reads_the_launcher_without_drawing_anything(
    tmp_path: Path, platform: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Settings asks on every page: a file check and a small read, never Pillow."""
    env = env_for(platform, tmp_path)
    write(plan(tmp_path / "data", platform=platform, env=env, home=tmp_path, python=PY))

    def no_drawing(size: int) -> Any:
        raise AssertionError("state() drew an icon")

    monkeypatch.setattr(shortcut, "draw_logo", no_drawing)
    assert state(tmp_path / "data", platform=platform, env=env, home=tmp_path, python=PY).current
    assert plan(tmp_path / "data", platform=platform, env=env, home=tmp_path, python=PY).shown()


@pytest.mark.parametrize("platform", PLATFORMS)
def test_writing_again_for_another_folder_updates_the_launcher(tmp_path: Path, platform: str) -> None:
    env = env_for(platform, tmp_path)
    write(plan(tmp_path / "one", platform=platform, env=env, home=tmp_path, python=PY))
    assert write(plan(tmp_path / "two", platform=platform, env=env, home=tmp_path, python=PY)) == "updated"
    assert state(platform=platform, env=env, home=tmp_path, python=PY).data_dir == tmp_path / "two"
    assert remove(location(platform=platform, env=env, home=tmp_path))
    assert not state(platform=platform, env=env, home=tmp_path).added
    assert remove(location(platform=platform, env=env, home=tmp_path)) == []


def test_location_matches_plan(tmp_path: Path) -> None:
    for platform in ("linux", "darwin", "win32"):
        env = {"APPDATA": str(tmp_path), "XDG_DATA_HOME": str(tmp_path / "x"), "PATH": "/bin\n/broken"}
        where = location(platform=platform, env=env, home=tmp_path)  # this terminal's PATH plays no part
        planned = plan(
            tmp_path, platform=platform, env={k: v for k, v in env.items() if k != "PATH"}, home=tmp_path
        )
        assert where.path == planned.path
        assert [f.path for f in where.files] == [f.path for f in planned.files]


def test_the_logo_matches_the_favicon() -> None:
    """``draw_logo`` follows ``web/public/favicon.svg`` (64 units): sampled where only one shape is."""
    svg = (Path(__file__).parents[1] / "web" / "public" / "favicon.svg").read_text(encoding="utf-8")
    for code in ("#0F6E66", "#F7F5F0", "#FCD34D", "#0B4F49", 'rx="14"', 'r="9"', 'opacity=".55"'):
        assert code in svg
    teal, paper, disc = (
        tuple(int(code[i : i + 2], 16) for i in (1, 3, 5)) for code in ("#0F6E66", "#F7F5F0", "#FCD34D")
    )
    image = DRAW_LOGO(256)
    assert image.size == (256, 256) and image.mode == "RGBA"

    def pixel(x: float, y: float) -> tuple[int, ...]:
        return tuple(image.getpixel((int(x * 4), int(y * 4))))

    assert pixel(0.5, 0.5)[3] == 0  # the rounded corner is transparent
    assert pixel(4, 32) == (*teal, 255)
    assert pixel(44, 32) == (*paper, 255)  # beside the bars, above the disc
    assert pixel(44, 52) == (*disc, 255)  # in the disc, below the check
    assert pixel(30, 23) == (*teal, 255)  # the first bar: full teal
    faded = tuple(round(t * 0.55 + p * 0.45) for t, p in zip(teal, paper))
    assert pixel(26, 30) == (*faded, 255)  # the other bars: teal at 55 % on the paper
    small = io.BytesIO()
    DRAW_LOGO(16).save(small, "PNG")
    assert len(small.getvalue()) < 2_000


# --------------------------------------------------------------------------------------------------
# the command
# --------------------------------------------------------------------------------------------------


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    import ordnung.demo.loader  # noqa: F401  (the command's lazy imports, made before a system is faked)

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("HOME", str(home))
    for name in ("XDG_DATA_HOME", "APPDATA", "LOCALAPPDATA", shortcut.TELEMETRY_OPT_OUT):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


@POSIX_ONLY
def test_the_command_prints_what_it_writes(fake_home: Path, tmp_path: Path) -> None:
    folder = tmp_path / "data"
    entry = fake_home / ".local" / "share" / "applications" / DESKTOP_FILE

    dry = invoke("shortcut", "--data-dir", str(folder), "--dry-run")
    assert dry.exit_code == 0, dry.output
    assert f"Ordnung for {folder} goes into your app menu, from this file:" in dry.output
    assert (
        f"  {entry}" in dry.output and "Terminal=true" in dry.output and "X-Ordnung-Shortcut=1" in dry.output
    )
    assert dry.output.rstrip().endswith("Nothing was written (--dry-run).") and not entry.exists()

    done = invoke("shortcut", "--data-dir", str(folder))
    assert done.exit_code == 0, done.output
    assert "✓ Added. Look for “Ordnung” in your app menu." in done.output
    assert (
        "When Ordnung isn't running, it starts in a window of its own: closing that window stops Ordnung."
        in done.output
    )
    assert "Take it out again with: ordnung shortcut --remove" in done.output
    assert entry.is_file() and "--from-shortcut" in entry.read_text(encoding="utf-8")

    assert "✓ Already in your app menu like this." in invoke("shortcut", "--data-dir", str(folder)).output
    moved = invoke("shortcut", "--data-dir", str(folder), "--port", "8899")
    assert moved.exit_code == 0 and "✓ Updated the earlier shortcut." in moved.output

    looked = invoke("shortcut", "--remove", "--dry-run")
    assert looked.exit_code == 0 and f"Would remove {entry}" in looked.output
    assert "Nothing was removed (--dry-run)." in looked.output and entry.is_file()

    off = invoke("shortcut", "--remove")
    assert off.exit_code == 0, off.output
    assert f"✓ Removed {entry}" in off.output and not entry.exists()
    assert (
        "Ordnung is no longer in your app menu. A running Ordnung keeps running: this only takes it out of "
        "your app menu." in off.output
    )
    again = invoke("shortcut", "--remove")
    assert again.exit_code == 0 and f"Ordnung isn't in your app menu: there is no {entry}." in again.output


@POSIX_ONLY
def test_the_command_leaves_a_launcher_it_didn_t_write(fake_home: Path, tmp_path: Path) -> None:
    entry = fake_home / ".local" / "share" / "applications" / DESKTOP_FILE
    entry.parent.mkdir(parents=True)
    entry.write_text("[Desktop Entry]\nName=Ordnung\n", encoding="utf-8")
    folder = str(tmp_path / "data")
    for args in (
        ("--data-dir", folder),
        ("--data-dir", folder, "--dry-run"),
        ("--remove",),
        ("--remove", "--dry-run"),
    ):
        result = invoke("shortcut", *args)
        assert result.exit_code == 1, args  # a dry run says what the real run would: it refuses too
        assert f"✗ {entry} wasn't written by `ordnung shortcut`, so it was left as it is." in result.output
        assert "Nothing was written" not in result.output and "[Desktop Entry]" not in result.output
        step = "remove it yourself" if "--remove" in args else "then run `ordnung shortcut` again"
        assert step in " ".join(result.output.split()), args
    assert entry.read_text(encoding="utf-8") == "[Desktop Entry]\nName=Ordnung\n"


def test_the_command_says_why_a_bundle_folder_stays(
    fake_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    assert invoke("shortcut", "--data-dir", str(tmp_path / "data")).exit_code == 0
    bundle = fake_home / "Applications" / "Ordnung.app"
    (bundle / "Contents" / "notes.txt").write_text("mine", encoding="utf-8")
    off = invoke("shortcut", "--remove")
    assert off.exit_code == 0, off.output
    assert f"! {bundle} holds files `ordnung shortcut` didn't write, so the folder stays." in off.output
    assert "Launchpad" not in off.output
    added = invoke("shortcut", "--data-dir", str(tmp_path / "data"))
    assert "goes into your Applications folder, as this app:" in added.output
    # not the Applications folder in Finder's sidebar: where to find it, said plainly
    assert (
        "✓ Added. Find “Ordnung” with Launchpad or Spotlight, or in the Applications folder of your home "
        "folder; drag it to the Dock to keep it there."
    ) in " ".join(added.output.split())


@WINDOWS_ONLY
def test_the_command_on_windows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in windows_env(tmp_path).items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv(shortcut.TELEMETRY_OPT_OUT, raising=False)
    folder = tmp_path / "data"
    lnk = tmp_path / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / LNK
    icon = tmp_path / "AppData" / "Local" / "Programs" / "Ordnung" / ICO

    dry = invoke("shortcut", "--data-dir", str(folder), "--dry-run")
    assert dry.exit_code == 0, dry.output
    assert "goes into your Start menu, as this shortcut:" in dry.output and str(lnk) in dry.output
    assert "Nothing was written" in dry.output and not lnk.exists()
    done = invoke("shortcut", "--data-dir", str(folder))
    assert done.exit_code == 0, done.output
    assert "Right-click it there to pin it to the taskbar." in done.output
    assert lnk.is_file() and icon.is_file()
    assert "Already in your Start menu like this." in invoke("shortcut", "--data-dir", str(folder)).output
    off = invoke("shortcut", "--remove")
    assert off.exit_code == 0 and f"Removed {lnk}" in off.output and f"Removed {icon}" in off.output
    assert not lnk.exists() and not icon.exists()


def test_the_demo_gets_no_shortcut(fake_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import ordnung.demo.loader as loader

    monkeypatch.setattr(loader, "is_demo_dir", lambda _folder: True)
    result = invoke("shortcut", "--data-dir", str(tmp_path / "demo"))
    assert result.exit_code == 1 and "The demo isn't added to your app menu." in result.output
    assert "ordnung demo" in result.output
    assert not (fake_home / ".local").exists()


def test_windows_says_the_shortcut_can_t_carry_the_telemetry_opt_out(
    fake_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    for name, value in windows_env(fake_home).items():
        monkeypatch.setenv(name, value)
    name = shortcut.TELEMETRY_OPT_OUT
    assert name not in invoke("shortcut", "--data-dir", str(tmp_path / "data"), "--dry-run").output
    monkeypatch.setenv(name, "1")
    dry = invoke("shortcut", "--data-dir", str(tmp_path / "data"), "--dry-run")
    assert dry.exit_code == 0, dry.output
    assert (
        f"! The Start-menu shortcut can't carry {name}. To keep it for Ordnung opened from there, "
        f"set it for your account: setx {name} 1"
    ) in dry.output


def test_the_shortcut_command_is_listed() -> None:
    help_text = plain(invoke("shortcut", "--help").output)
    for option in ("--remove", "--dry-run", "--port", "--data-dir"):
        assert option in help_text
    assert "shortcut" in plain(invoke("--help").output)


# --------------------------------------------------------------------------------------------------
# serve --from-shortcut
# --------------------------------------------------------------------------------------------------


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def fake_serve(folder: Path, **kwargs: Any) -> None:
        calls.append({"folder": folder, **kwargs})

    monkeypatch.setattr(cli, "_serve", fake_serve)
    return calls


def test_serve_takes_the_launcher_s_flag_without_listing_it(
    served: list[dict[str, Any]], tmp_path: Path
) -> None:
    result = invoke("serve", "--data-dir", str(tmp_path), "--from-shortcut")
    assert result.exit_code == 0, result.output
    assert served[-1]["from_shortcut"] is True and served[-1]["folder"] == tmp_path
    assert invoke("serve", "--data-dir", str(tmp_path)).exit_code == 0
    assert served[-1]["from_shortcut"] is False
    help_text = plain(invoke("serve", "--help").output)
    assert "--no-browser" in help_text and "--from-shortcut" not in help_text


RUNNING = ServerInfo(port=8765, token="the-secret-session-token", pid=4321)


@pytest.fixture
def launched(monkeypatch: pytest.MonkeyPatch) -> list[ServerInfo]:
    """The browsers opened (none really), with no server running unless a test says so."""
    opened: list[ServerInfo] = []
    monkeypatch.setattr(cli, "launch_browser", lambda folder, info: opened.append(info))
    monkeypatch.setattr(cli, "reachable_server", lambda folder: None)
    return opened


def _never(*_args: Any, **_kwargs: Any) -> Any:
    raise AssertionError("Ordnung was started")


def test_from_shortcut_without_a_terminal_never_starts_ordnung(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, launched: list[ServerInfo]
) -> None:
    import uvicorn

    import ordnung.locking as locking

    monkeypatch.setattr(cli, "_in_terminal", lambda: False)
    monkeypatch.setattr(locking, "DataDirLock", _never)
    monkeypatch.setattr(uvicorn.Server, "run", _never)
    result = invoke("serve", "--data-dir", str(tmp_path / "data"), "--from-shortcut")
    assert result.exit_code == shortcut.NO_WINDOW_EXIT == 3, result.output
    assert "Ordnung isn't running, and there is no window to run it in." in result.output
    assert "Press Enter" not in result.output and launched == []
    # nothing was locked, opened or advertised
    assert not any(
        (tmp_path / "data" / name).exists() for name in (".ordnung.lock", "ordnung.db", "server.json")
    )


def test_from_shortcut_opens_the_running_ordnung_without_printing_its_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, launched: list[ServerInfo]
) -> None:
    monkeypatch.setattr(cli, "reachable_server", lambda folder: RUNNING)
    for terminal in (False, True):
        monkeypatch.setattr(cli, "_in_terminal", lambda terminal=terminal: terminal)
        result = invoke("serve", "--data-dir", str(tmp_path), "--from-shortcut")
        assert result.exit_code == 0, result.output
        assert "Ordnung is already running for this folder: opened it in your browser." in result.output
        assert RUNNING.token not in result.output and "http" not in result.output
    assert launched == [RUNNING, RUNNING]


def test_from_shortcut_waits_for_enter_after_a_failed_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, launched: list[ServerInfo]
) -> None:
    monkeypatch.setattr(cli, "_in_terminal", lambda: True)
    monkeypatch.setattr(cli, "_port_free", lambda host, port: False)
    result = invoke("serve", "--data-dir", str(tmp_path / "data"), "--from-shortcut", input="\n")
    assert result.exit_code == 1
    error = result.output.index("Port 8765 is already in use")
    assert result.output.index("Press Enter to close this window.") > error
    # nobody typed a command, so there is no --port to add: what the person can do instead
    text = " ".join(result.output.split())
    assert "maybe another Ordnung such as `ordnung demo`: stop it and open Ordnung again" in text
    assert "ordnung shortcut --port 8766" in text and "Choose another one" not in text
    # typed by hand, the terminal stays open anyway: no prompt
    plain_run = invoke("serve", "--data-dir", str(tmp_path / "data"), "--no-browser")
    assert plain_run.exit_code == 1 and "Press Enter" not in plain_run.output
    assert "Choose another one, e.g. --port 8766." in plain_run.output
    # Enter never comes (the input ends): it closes all the same
    assert invoke("serve", "--data-dir", str(tmp_path / "data"), "--from-shortcut").exit_code == 1


def _free_port() -> int:
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def test_a_start_that_fails_inside_the_server_waits_for_enter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, launched: list[ServerInfo]
) -> None:
    """uvicorn ends a failed startup (the app's or the port's) with exit code 3, the code that means "no
    window": serve turns it into a failure of its own, so the launcher's window waits for Enter."""

    async def broken(scope: dict[str, Any], receive: Any, send: Any) -> None:
        assert scope["type"] == "lifespan"
        await receive()
        await send({"type": "lifespan.startup.failed", "message": "the watched folder can't be read"})

    folder = tmp_path / "data"
    monkeypatch.setattr(cli, "_in_terminal", lambda: True)
    monkeypatch.setattr(cli, "_create_app", lambda context, token, demo: broken)
    monkeypatch.setattr(cli, "_open_browser_when_ready", lambda folder, info: launched.append(info))
    port = str(_free_port())
    result = invoke("serve", "--data-dir", str(folder), "--port", port, "--from-shortcut", input="\n")
    assert result.exit_code == 1, result.output
    assert result.exit_code != shortcut.NO_WINDOW_EXIT
    failed = result.output.index("Ordnung couldn't start.")
    assert result.output.index("Press Enter to close this window.") > failed
    assert not (folder / "server.json").exists() and not (folder / cli.LOGIN_PAGE_NAME).exists()
    by_hand = invoke("serve", "--data-dir", str(folder), "--port", port, "--no-browser")
    assert by_hand.exit_code == 1 and "Ordnung couldn't start." in by_hand.output
    assert "Press Enter" not in by_hand.output


def test_closing_the_console_on_windows_stops_ordnung_as_ctrl_c_does(monkeypatch: pytest.MonkeyPatch) -> None:
    """Windows sends no signal when its console window closes, only CTRL_CLOSE_EVENT to the console handlers,
    and ends the process once they return (or after about 5 s): the handler asks the server to stop and waits."""

    class Server:
        should_exit = False

    server, hung_up = Server(), []
    registered: list[tuple[Any, bool]] = []
    monkeypatch.setattr(cli, "CLOSE_GRACE_S", 0.0)

    def register(handler: Any, add: bool) -> bool:
        registered.append((handler, add))
        return True

    with cli._stop_on_console_close(server, hung_up, register=register):
        ((handler, added),) = registered
        assert added
        assert handler(0) is False and handler(1) is False  # Ctrl+C, Ctrl+Break: Python's own handlers
        assert not server.should_exit and not hung_up
        assert handler(2) is True  # the window closes
        assert server.should_exit and hung_up
    assert registered[-1] == (handler, False)  # taken away again
    with cli._stop_on_console_close(server, hung_up, register=lambda handler, add: False):
        pass  # a handler Windows doesn't take (no console, say) changes nothing else
    with cli._stop_on_console_close(server, hung_up, register=None):
        pass  # this system's own: none outside Windows; on Windows, the real handler comes and goes


@pytest.mark.skipif(os.name != "posix", reason="a terminal window that closes hangs up (SIGHUP) on POSIX")
def test_closing_the_window_stops_ordnung_as_ctrl_c_does(tmp_path: Path) -> None:
    """Closing the terminal window sends SIGHUP: Ordnung shuts down as after Ctrl+C (the app's shutdown runs,
    with sync's last save) and takes away server.json and the sign-in page, which holds the session token."""
    import signal
    import socket

    folder = tmp_path / "data"
    port = _free_port()
    env = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "BROWSER": "true",
        "ORDNUNG_CLAUDE_BIN": str(tmp_path / "no-claude"),
        "TERM": "dumb",
    }
    leader, follower = os.openpty()
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "ordnung",
            "--data-dir",
            str(folder),
            "serve",
            "--from-shortcut",
            "--port",
            str(port),
        ],
        stdin=follower,
        stdout=follower,
        stderr=follower,
        env=env,
        cwd=Path(__file__).resolve().parents[1],
        start_new_session=True,
    )
    os.close(follower)
    try:
        deadline = time.monotonic() + 60
        answers = False
        while not (answers and (folder / cli.LOGIN_PAGE_NAME).exists()):  # the page: once the browser opens
            assert process.poll() is None and time.monotonic() < deadline, "Ordnung didn't start"
            with contextlib.suppress(OSError), socket.create_connection(("127.0.0.1", port), timeout=0.5):
                answers = True
            with contextlib.suppress(OSError):  # keep the terminal's buffer from filling up
                if select.select([leader], [], [], 0.2)[0]:
                    os.read(leader, 65536)
        assert (folder / "server.json").exists()
        os.close(leader)  # the window closes: the terminal hangs up
        leader = -1
        process.send_signal(signal.SIGHUP)
        assert process.wait(timeout=30) == 128 + signal.SIGHUP
    finally:
        if leader >= 0:
            os.close(leader)
        if process.poll() is None:
            process.kill()
            process.wait()
    assert not (folder / "server.json").exists() and not (folder / cli.LOGIN_PAGE_NAME).exists()
    assert not (folder / "ordnung.db-wal").exists()  # the database was closed, its log written back


def test_a_second_click_opens_the_ordnung_that_is_starting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, launched: list[ServerInfo]
) -> None:
    import ordnung.locking as locking

    folder = tmp_path / "data"

    class Held:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def acquire(self) -> Any:
            raise DataDirLocked(folder, "pid 1: ordnung serve")

        __enter__ = acquire

        def __exit__(self, *_exc: Any) -> None:
            pass

    answers = iter([None, None, RUNNING])
    monkeypatch.setattr(locking, "DataDirLock", Held)
    monkeypatch.setattr(cli, "reachable_server", lambda _folder: next(answers))
    monkeypatch.setattr(cli, "_in_terminal", lambda: True)
    result = invoke("serve", "--data-dir", str(folder), "--from-shortcut")
    assert result.exit_code == 0, result.output
    assert launched == [RUNNING] and "Another Ordnung process" not in result.output
    assert RUNNING.token not in result.output

    # typed by hand, a second start still says who holds the folder
    monkeypatch.setattr(cli, "reachable_server", lambda _folder: None)
    by_hand = invoke("serve", "--data-dir", str(folder))
    assert by_hand.exit_code == 1 and "Another Ordnung process (pid 1: ordnung serve)" in by_hand.output


def test_a_second_click_gives_up_when_nothing_answers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, launched: list[ServerInfo]
) -> None:
    import ordnung.locking as locking

    folder = tmp_path / "data"

    class Held:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def acquire(self) -> Any:
            raise DataDirLocked(folder, None)

    monkeypatch.setattr(locking, "DataDirLock", Held)
    monkeypatch.setattr(cli, "_in_terminal", lambda: True)
    monkeypatch.setattr(cli, "BROWSER_WAIT_S", 0.3)
    result = invoke("serve", "--data-dir", str(folder), "--from-shortcut", input="\n")
    assert result.exit_code == 1 and "Another Ordnung process" in result.output
    assert "Press Enter to close this window." in result.output and launched == []


def test_from_shortcut_runs_ordnung_in_its_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, launched: list[ServerInfo]
) -> None:
    import socket

    import uvicorn

    titles: list[str] = []
    monkeypatch.setattr(cli, "_in_terminal", lambda: True)
    monkeypatch.setattr(cli.console, "set_window_title", lambda title: titles.append(title) or True)
    monkeypatch.setattr(cli, "_create_app", lambda context, token, demo: object())
    monkeypatch.setattr(cli, "_open_browser_when_ready", lambda folder, info: launched.append(info))
    monkeypatch.setattr(uvicorn.Server, "run", lambda self: None)
    monkeypatch.setattr(cli, "_shortcut_missing", lambda: True)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    result = invoke("serve", "--data-dir", str(tmp_path / "data"), "--port", str(port), "--from-shortcut")
    assert result.exit_code == 0, result.output
    text = " ".join(result.output.replace("│", " ").split())
    assert (
        "Close this window (or press Ctrl+C) to stop Ordnung." in text and "Press Ctrl+C to stop." not in text
    )
    assert "ordnung shortcut" not in text  # opened from it already
    assert titles == ["Ordnung"] and len(launched) == 1 and launched[0].port == port


def test_serve_suggests_the_shortcut_only_in_a_terminal_and_only_when_there_is_none(
    fake_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    info = ServerInfo(port=8765, token="t", pid=1)
    hint = "Open it without a terminal next time: ordnung shortcut"

    def panel(*, demo: bool = False, from_shortcut: bool = False, folder: Path = tmp_path / "data") -> str:
        cli._announce(info, demo=demo, data_dir=folder, from_shortcut=from_shortcut)
        return " ".join(capsys.readouterr().out.replace("│", " ").split())

    def unwrapped(text: str) -> str:  # the panel wraps a long path (Windows' temporary folders) at its edge
        return "".join(text.split())

    monkeypatch.setattr(cli, "_in_terminal", lambda: True)
    # the command sets up this data folder, as the one Settings offers does
    command = shortcut.command(tmp_path / "data")
    assert command.startswith("ordnung shortcut --data-dir ")
    assert unwrapped(f"Open it without a terminal next time: {command}") in unwrapped(panel())
    assert "Press Ctrl+C to stop." in panel()
    default = Path(user_data_dir("ordnung", appauthor=False))
    in_default = panel(folder=default)
    assert hint in in_default and "--data-dir" not in in_default
    assert hint not in panel(demo=True) and hint not in panel(from_shortcut=True)
    monkeypatch.setattr(cli, "_in_terminal", lambda: False)  # e.g. started at login: nobody reads it
    assert hint not in panel()
    monkeypatch.setattr(cli, "_in_terminal", lambda: True)
    write(plan(tmp_path / "data", python=PY))
    assert hint not in panel()


@POSIX_ONLY
def test_autostart_points_to_the_shortcut_for_opening_the_app(fake_home: Path, tmp_path: Path) -> None:
    folder = tmp_path / "data"
    enabled = invoke("autostart", "enable", "--data-dir", str(folder))
    assert enabled.exit_code == 0, enabled.output
    # both commands name this data folder, as Settings' do
    assert (
        f"Open the app any time from your app menu (ordnung shortcut --data-dir {folder} adds it) or with: "
        f"ordnung serve --data-dir {folder}"
    ) in enabled.output
