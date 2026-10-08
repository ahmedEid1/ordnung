"""The lookups that differ per operating system, run for real on this machine: the network interfaces and
the router phone access reads, sync's computer id and the durable writes' flush. Only types and shapes are
checked, and that nothing failed on the way — the router lookup and the interface listing are best effort
and log what they swallow, so a swallowed error fails here too.

CI runs this file on Linux in every job and on macOS and Windows in the "Other systems" job, where the
``route``/``arp``, ``ioreg``, registry and ``F_FULLFSYNC`` branches run (the other tests replace them).
"""

from __future__ import annotations

import ipaddress
import logging
import os
import re
import shutil
import sys
from pathlib import Path

import pytest

from ordnung import durable
from ordnung.phone import net
from ordnung.sync import local

OTHER_SYSTEM = sys.platform in ("darwin", "win32")


def _swallowed(caplog: pytest.LogCaptureFixture) -> list[str]:
    """What the best-effort lookups caught and logged with its traceback instead of raising."""
    return [record.getMessage() for record in caplog.records if record.exc_info]


def test_the_network_interfaces_can_be_listed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(net.TEST_ADDRESS_ENV, raising=False)
    found = net.interfaces()
    assert isinstance(found, list)
    for row in found:
        assert isinstance(row.name, str) and isinstance(row.description, str)
        ipaddress.IPv4Address(row.address)
        assert row.prefix is None or isinstance(row.prefix, int)


def test_the_addresses_phone_access_offers(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv(net.TEST_ADDRESS_ENV, raising=False)
    caplog.set_level(logging.DEBUG, logger="ordnung.phone")
    route = net.default_route_address()
    candidates = net.candidate_addresses()
    assert _swallowed(caplog) == []
    if route is not None:
        ipaddress.IPv4Address(route)
    for candidate in candidates:
        assert net.usable(candidate.address) and isinstance(candidate.interface, str)
        assert ipaddress.IPv4Address(candidate.address) in ipaddress.IPv4Network(candidate.subnet)
    assert [c.recommended for c in candidates[:1]] == [True] * len(candidates[:1])
    assert not any(c.recommended for c in candidates[1:])


def test_the_router_can_be_looked_up(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="ordnung.phone")
    fingerprint = net.gateway_fingerprint()
    assert _swallowed(caplog) == []
    if fingerprint is not None:
        assert re.fullmatch(r"\d{1,3}(\.\d{1,3}){3} [0-9a-f]{2}(:[0-9a-f]{2}){5}", fingerprint), fingerprint
    if OTHER_SYSTEM:
        # there the router is read with these system tools: a missing one would read as "no router"
        assert shutil.which("route") and shutil.which("arp")


def test_the_computer_id_sync_uses() -> None:
    machine = local._read_machine_id()
    assert machine is None or (isinstance(machine, str) and machine.strip() == machine and machine)
    if OTHER_SYSTEM:
        # macOS (ioreg) and Windows (the registry) always have one; None would mean the lookup broke and
        # sync fell back to a random id of its own
        assert machine is not None


def test_a_file_and_its_folder_can_be_flushed_to_the_disk(tmp_path: Path) -> None:
    path = tmp_path / "written"
    path.write_bytes(b"on disk")
    fd = os.open(path, os.O_RDWR)  # writable, as every writer's: Windows can't flush a read-only handle
    try:
        durable.fsync(fd)
    finally:
        os.close(fd)
    durable.fsync_dir(tmp_path)
    assert path.read_bytes() == b"on disk"


def test_fsync_asks_macos_to_flush_the_drive_s_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``durable.fsync`` looked for ``F_FULLFSYNC`` in ``os``, where Python doesn't have it (it is in
    ``fcntl``), so on macOS it was a plain fsync: the bytes could still sit in the drive's cache. Off macOS
    this test plays macOS; there it watches the real call."""
    fcntl = pytest.importorskip("fcntl")  # not on Windows
    calls: list[tuple[int, int]] = []
    real = fcntl.fcntl if sys.platform == "darwin" else None
    full = getattr(fcntl, "F_FULLFSYNC", 51)  # its value on macOS

    def watched(fd: int, command: int, *arg: int) -> object:
        calls.append((fd, command))
        return real(fd, command, *arg) if real is not None else 0

    path = tmp_path / "written"
    path.write_bytes(b"on disk")
    fd = os.open(path, os.O_RDONLY)
    try:
        with monkeypatch.context() as patch:
            if real is None:
                patch.setattr(sys, "platform", "darwin")
                patch.setattr(fcntl, "F_FULLFSYNC", full, raising=False)
            patch.setattr(fcntl, "fcntl", watched)
            durable.fsync(fd)
    finally:
        os.close(fd)
    assert calls == [(fd, full)]
