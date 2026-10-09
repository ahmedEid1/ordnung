"""Whether the disk under the data folder is encrypted (:mod:`ordnung.encryption`): only the system's own
status commands, faked here — never run, never as administrator, never a shell line."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ordnung.encryption import TIMEOUT_S, Encryption, disk_encryption


class FakeSystem:
    """Answers ``fdesetup``, ``findmnt`` and ``lsblk`` from a table; records every call."""

    def __init__(self, answers: dict[str, Any]) -> None:
        self.answers = answers
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    def __call__(self, argv: list[str], **kwargs: Any) -> Any:
        self.calls.append((argv, kwargs))
        answer = self.answers[Path(argv[0]).name]
        if isinstance(answer, BaseException):
            raise answer
        code, out = answer if isinstance(answer, tuple) else (0, answer)
        return SimpleNamespace(returncode=code, stdout=out, stderr="")


def which(*present: str) -> Callable[[str], str | None]:
    return lambda name: f"/usr/bin/{name}" if name in present else None


def not_wsl(_: Path) -> str:
    return "6.8.0-45-generic\n"


def mac(answer: Any) -> tuple[Encryption | None, FakeSystem]:
    run = FakeSystem({"fdesetup": answer})
    return disk_encryption(Path("/Users/sam/Ordnung"), system="darwin", run=run), run


def linux(
    tmp_path: Path, findmnt: Any, lsblk: Any = "", *, tools: tuple[str, ...] = ("findmnt", "lsblk")
) -> tuple[Encryption | None, FakeSystem]:
    run = FakeSystem({"findmnt": findmnt, "lsblk": lsblk})
    found = disk_encryption(tmp_path, system="linux", which=which(*tools), run=run, read_text=not_wsl)
    return found, run


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("FileVault is On.\n", "on"),
        ("Encryption in progress: Percent completed = 31.2\n", "on"),
        ("FileVault is Off.\n", "off"),
        ("Decryption in progress: Percent completed = 12.0\n", "unknown"),
        ((1, ""), "unknown"),
        (FileNotFoundError(2, "No such file"), "unknown"),
        (subprocess.TimeoutExpired(["fdesetup"], TIMEOUT_S), "unknown"),
        (RuntimeError("anything"), "unknown"),
    ],
)
def test_filevault_on_macos(answer: Any, expected: str) -> None:
    found, run = mac(answer)
    assert found is not None and found.answer == expected and found.what == "FileVault"
    ((argv, kwargs),) = run.calls
    assert argv == ["/usr/bin/fdesetup", "status"] and kwargs["timeout"] == TIMEOUT_S == 5.0
    assert "shell" not in kwargs
    if expected == "unknown":
        assert found.reason


def test_luks_under_the_data_folder_is_on(tmp_path: Path) -> None:
    found, run = linux(tmp_path, "/dev/mapper/vgubuntu-root ext4\n", "lvm\ncrypt\npart\ndisk\n")
    assert found == Encryption("on", "LUKS")
    (findmnt, _), (lsblk, kwargs) = run.calls
    assert findmnt == [
        "/usr/bin/findmnt",
        "--noheadings",
        "--output",
        "SOURCE,FSTYPE",
        "--target",
        str(tmp_path),
    ]
    assert lsblk == [
        "/usr/bin/lsblk",
        "--noheadings",
        "--inverse",
        "--output",
        "TYPE",
        "/dev/mapper/vgubuntu-root",
    ]
    assert kwargs["timeout"] == TIMEOUT_S


def test_no_crypt_device_is_found_no_encryption(tmp_path: Path) -> None:
    found, _ = linux(tmp_path, "/dev/sda2 ext4\n", "part\ndisk\n")
    assert found == Encryption("off", "LUKS")


def test_a_btrfs_subvolume_is_looked_up_by_its_device(tmp_path: Path) -> None:
    found, run = linux(tmp_path, "/dev/mapper/luks-1a2b[/@home] btrfs\n", "crypt\npart\ndisk\n")
    assert found is not None and found.answer == "on"
    assert run.calls[1][0][-1] == "/dev/mapper/luks-1a2b"


def test_an_encrypting_file_system_is_on_without_asking_lsblk(tmp_path: Path) -> None:
    found, run = linux(tmp_path, "/home/.ecryptfs/sam/.Private ecryptfs\n")
    assert found == Encryption("on", "eCryptfs")
    assert len(run.calls) == 1


@pytest.mark.parametrize("source", ["overlay overlay", "tmpfs tmpfs", "tank/home zfs", "//nas/share cifs"])
def test_a_source_that_isnt_a_disk_is_unknown(tmp_path: Path, source: str) -> None:
    found, run = linux(tmp_path, source + "\n")
    assert found is not None and found.answer == "unknown" and found.reason
    assert len(run.calls) == 1


@pytest.mark.parametrize("tools", [("lsblk",), ("findmnt",), ()])
def test_a_missing_tool_is_unknown(tmp_path: Path, tools: tuple[str, ...]) -> None:
    found, run = linux(tmp_path, "/dev/sda2 ext4\n", "part\n", tools=tools)
    assert found is not None and found.answer == "unknown" and "isn't installed" in found.reason
    assert run.calls == []


@pytest.mark.parametrize(
    ("findmnt", "lsblk"),
    [
        (FileNotFoundError(2, "No such file"), ""),
        (subprocess.TimeoutExpired(["findmnt"], TIMEOUT_S), ""),
        ((1, ""), ""),
        ("", ""),
        ("/dev/sda2 ext4\n", (32, "")),
        ("/dev/sda2 ext4\n", subprocess.TimeoutExpired(["lsblk"], TIMEOUT_S)),
    ],
)
def test_a_failing_command_is_unknown(tmp_path: Path, findmnt: Any, lsblk: Any) -> None:
    found, _ = linux(tmp_path, findmnt, lsblk)
    assert found is not None and found.answer == "unknown" and found.what == "LUKS" and found.reason


def test_a_data_folder_not_made_yet_is_looked_up_by_its_nearest_folder(tmp_path: Path) -> None:
    run = FakeSystem({"findmnt": "/dev/sda2 ext4\n", "lsblk": "part\n"})
    disk_encryption(
        tmp_path / "not" / "yet", system="linux", which=which("findmnt", "lsblk"), run=run, read_text=not_wsl
    )
    assert run.calls[0][0][-1] == str(tmp_path)


def test_wsl_and_other_systems_have_no_answer(tmp_path: Path) -> None:
    run = FakeSystem({})
    found = disk_encryption(
        tmp_path,
        system="linux",
        which=which("findmnt", "lsblk"),
        run=run,
        read_text=lambda _: "5.15.153.1-microsoft-standard-WSL2\n",
    )
    assert found is None
    for system in ("win32", "cygwin", "freebsd14"):
        assert disk_encryption(tmp_path, system=system, run=run) is None
    assert run.calls == []


def test_an_unreadable_kernel_release_is_not_wsl(tmp_path: Path) -> None:
    def unreadable(_: Path) -> str:
        raise PermissionError(13, "Permission denied")

    run = FakeSystem({"findmnt": "/dev/sda2 ext4\n", "lsblk": "crypt\n"})
    found = disk_encryption(
        tmp_path, system="linux", which=which("findmnt", "lsblk"), run=run, read_text=unreadable
    )
    assert found == Encryption("on", "LUKS")
