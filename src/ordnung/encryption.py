"""Whether the disk under the data folder is encrypted — a best effort, for ``ordnung doctor``.

Ordnung keeps letters, the numbers in them (a tax ID, IBANs) and the ledger in the data folder, private to
the person's account but not encrypted by Ordnung: on a lost laptop, disk encryption decides who can read
them. This module only *reads* what the system says, without administrator rights, and never changes
anything.

Written policy:

* **macOS**: ``/usr/bin/fdesetup status``. "FileVault is On." or "Encryption in progress" → on;
  "FileVault is Off." → off; anything else → unknown.
* **Linux**: inside WSL (``/proc/sys/kernel/osrelease`` names Microsoft) there is no answer: the disk is
  Windows', and so is its encryption. Otherwise ``findmnt`` names the file system holding the data folder
  (its nearest folder that exists). An encrypting file system (eCryptfs, gocryptfs, EncFS, CryFS) → on.
  A source that isn't a device under ``/dev/`` once a btrfs ``[subvolume]`` is stripped (an overlay, tmpfs,
  a ZFS dataset, a network share) → unknown. Otherwise ``lsblk --inverse`` lists the device and every
  device below it: a ``crypt`` one (LUKS or plain dm-crypt, also under LVM or btrfs) → on, else off — said
  as "found no disk encryption (LUKS)", never "not encrypted": fscrypt or ZFS's own encryption aren't seen.
* **Every other system** (Windows among them) has no answer: no check is shown, and the docs say where
  BitLocker and Device encryption are. Windows reports BitLocker without administrator rights only through
  values Microsoft doesn't document.
* Each command is an argument list (never a shell line) with a :data:`TIMEOUT_S` limit. Anything that
  goes wrong — a tool missing, a timeout, an odd answer, an exception — is "unknown", never an error.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

__all__ = ["TIMEOUT_S", "Answer", "Encryption", "disk_encryption"]

TIMEOUT_S = 5.0
FDESETUP = "/usr/bin/fdesetup"
OSRELEASE = Path("/proc/sys/kernel/osrelease")
#: File systems that encrypt what they hold (``findmnt``'s FSTYPE), by the name people know them by.
ENCRYPTING_FILE_SYSTEMS = {
    "ecryptfs": "eCryptfs",
    "fuse.gocryptfs": "gocryptfs",
    "fuse.encfs": "EncFS",
    "fuse.cryfs": "CryFS",
}
_SUBVOLUME = re.compile(r"\[[^\]]*\]$")

Answer = Literal["on", "off", "unknown"]
Runner = Callable[..., Any]


@dataclass(frozen=True)
class Encryption:
    """What the system says about the disk under the data folder."""

    answer: Answer
    #: what was looked for or found: "FileVault", "LUKS", "eCryptfs" …
    what: str
    #: why the answer is unknown (a tool missing, its odd answer), for the doctor's line
    reason: str = ""


def _existing(path: Path) -> Path:
    for candidate in (path, *path.parents):
        if candidate.exists():
            return candidate
    return Path(path.anchor or ".")


def _output(run: Runner, argv: list[str]) -> str | None:
    """What ``argv`` printed, or ``None`` when it failed (a tool that can't start, or doesn't answer in
    time, raises: :func:`disk_encryption` turns that into "unknown")."""
    done = run(argv, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=TIMEOUT_S, check=False)
    if getattr(done, "returncode", 0) != 0:
        return None
    out = getattr(done, "stdout", "")
    return out if isinstance(out, str) else None


def _macos(run: Runner) -> Encryption:
    out = _output(run, [FDESETUP, "status"])
    if out is None:
        return Encryption("unknown", "FileVault", "`fdesetup status` didn't answer")
    if "FileVault is On." in out or "Encryption in progress" in out:
        return Encryption("on", "FileVault")
    if "FileVault is Off." in out:
        return Encryption("off", "FileVault")
    return Encryption("unknown", "FileVault", "`fdesetup status` gave an answer Ordnung doesn't know")


def _in_wsl(read_text: Callable[[Path], str]) -> bool:
    try:
        return "microsoft" in read_text(OSRELEASE).lower()
    except OSError:
        return False


def _linux(path: Path, which: Callable[[str], str | None], run: Runner) -> Encryption:
    findmnt, lsblk = which("findmnt"), which("lsblk")
    if findmnt is None or lsblk is None:
        missing = "findmnt" if findmnt is None else "lsblk"
        return Encryption("unknown", "LUKS", f"{missing} isn't installed")
    out = _output(
        run, [findmnt, "--noheadings", "--output", "SOURCE,FSTYPE", "--target", str(_existing(path))]
    )
    line = next((text.strip() for text in (out or "").splitlines() if text.strip()), "")
    source, _, fstype = line.rpartition(" ")
    if not source:
        return Encryption("unknown", "LUKS", "findmnt didn't name the file system")
    if fstype in ENCRYPTING_FILE_SYSTEMS:
        return Encryption("on", ENCRYPTING_FILE_SYSTEMS[fstype])
    device = _SUBVOLUME.sub("", source.strip())
    if not device.startswith("/dev/"):
        return Encryption("unknown", "LUKS", f"the data folder is on {device} ({fstype}), not on a disk")
    tree = _output(run, [lsblk, "--noheadings", "--inverse", "--output", "TYPE", device])
    if tree is None:
        return Encryption("unknown", "LUKS", f"lsblk didn't answer for {device}")
    found = any(kind.strip() == "crypt" for kind in tree.splitlines())
    return Encryption("on" if found else "off", "LUKS")


def disk_encryption(
    path: Path,
    *,
    system: str | None = None,
    which: Callable[[str], str | None] = shutil.which,
    run: Runner = subprocess.run,
    read_text: Callable[[Path], str] = Path.read_text,
) -> Encryption | None:
    """Whether the disk under ``path`` is encrypted (module policy); ``None`` where Ordnung can't tell
    on this system at all. Never raises."""
    platform = system or sys.platform
    mac = platform == "darwin"
    if not mac and not (platform.startswith("linux") and not _in_wsl(read_text)):
        return None
    what = "FileVault" if mac else "LUKS"
    try:
        return _macos(run) if mac else _linux(path, which, run)
    except subprocess.TimeoutExpired:
        return Encryption("unknown", what, f"the system didn't answer within {TIMEOUT_S:.0f} seconds")
    except Exception as exc:  # a tool that can't start, or anything else: never the doctor's failure
        return Encryption("unknown", what, f"the system's answer couldn't be read ({exc})")
