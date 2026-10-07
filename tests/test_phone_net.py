"""Which addresses phone access may listen on (home networks, never a tunnel), whom it answers (its own
subnet only), the tests' loopback hook and the router's fingerprint."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from ordnung.phone import net
from ordnung.phone.net import Candidate, candidate_addresses, client_allowed, usable


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("192.168.1.5", True),
        ("10.0.0.1", True),
        ("172.16.0.1", True),
        ("172.31.255.254", True),
        ("172.32.0.1", False),
        ("100.64.0.1", False),  # carrier-grade NAT
        ("169.254.1.1", False),  # link-local
        ("127.0.0.1", False),
        ("8.8.8.8", False),
        ("fd00::1", False),
        ("0.0.0.0", False),
        ("not an address", False),
    ],
)
def test_usable_addresses_are_ipv4_home_networks(address: str, expected: bool) -> None:
    assert usable(address) is expected


@pytest.mark.parametrize(("value", "expected"), [("127.0.0.1", "127.0.0.1"), ("127.0.0.2", "127.0.0.2")])
def test_the_test_hook_takes_a_loopback_address(
    monkeypatch: pytest.MonkeyPatch, value: str, expected: str
) -> None:
    monkeypatch.setenv(net.TEST_ADDRESS_ENV, value)
    assert net.test_address() == expected
    assert candidate_addresses([("en0", "192.168.1.5", 24)]) == [
        Candidate(expected, "loopback", f"{expected}/32", recommended=True)
    ]


@pytest.mark.parametrize("value", ["192.168.1.5", "0.0.0.0", "localhost", "::1", ""])
def test_the_test_hook_ignores_anything_but_loopback(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv(net.TEST_ADDRESS_ENV, value)
    assert net.test_address() is None


TUNNELS = [
    "utun3",
    "tun0",
    "tap1",
    "wg0",
    "ppp0",
    "ipsec0",
    "tailscale0",
    "zt7nnig26",
    "docker0",
    "br-1a2b3c",
    "veth12ab",
    "virbr0",
    "vboxnet0",
    "vmnet8",
    "vEthernet (WSL)",
    "awdl0",
    "llw0",
]


@pytest.mark.parametrize("name", TUNNELS)
def test_tunnels_vms_and_containers_are_never_offered(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.delenv(net.TEST_ADDRESS_ENV, raising=False)
    found = [(name, "10.8.0.6", 24), ("en0", "192.168.178.23", 24)]
    assert [c.address for c in candidate_addresses(found, default="10.8.0.6")] == ["192.168.178.23"]


def test_candidates_come_from_interfaces_with_the_default_route_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(net.TEST_ADDRESS_ENV, raising=False)
    found = [
        ("lo", "127.0.0.1", 8),
        ("en7", "192.168.0.40", None),
        ("en0", "192.168.178.23", 24),
        ("en0", "192.168.178.23", 24),
        ("en1", "169.254.3.4", 16),
        ("en2", "fd00::1", 64),
    ]
    assert candidate_addresses(found, default="192.168.178.23") == [
        Candidate("192.168.178.23", "en0", "192.168.178.0/24", recommended=True),
        Candidate("192.168.0.40", "en7", "192.168.0.0/24"),  # no netmask: /24
    ]
    # a VPN that took the default route is never recommended
    assert candidate_addresses(found, default="10.8.0.6")[0].address == "192.168.0.40"
    assert candidate_addresses([], default="192.168.1.5") == []


def test_the_interfaces_can_be_listed() -> None:
    found = net.interfaces()
    assert all(isinstance(name, str) and isinstance(address, str) for name, address, _prefix in found)


@pytest.mark.parametrize(
    ("client", "allowed"),
    [
        ("192.168.178.31", True),
        ("192.168.178.23", True),
        ("192.168.178.255", True),
        ("172.17.0.2", False),  # a container
        ("10.8.0.6", False),  # a peer behind a VPN
        ("192.168.179.5", False),
        ("8.8.8.8", False),
        ("::ffff:192.168.178.31", False),
        ("", False),
    ],
)
def test_only_the_bound_address_s_subnet_is_answered(client: str, allowed: bool) -> None:
    assert client_allowed(client, "192.168.178.23", "192.168.178.0/24") is allowed


def test_an_unknown_netmask_means_a_24() -> None:
    assert client_allowed("192.168.178.31", "192.168.178.23", None)
    assert not client_allowed("192.168.177.31", "192.168.178.23", None)
    assert client_allowed("127.0.0.1", "127.0.0.1", "127.0.0.1/32")


def test_sockets_tell_local_addresses_and_free_ports() -> None:
    assert net.address_is_local("127.0.0.1")
    assert not net.address_is_local("192.0.2.77")
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen(1)
        assert not net.port_free("127.0.0.1", taken.getsockname()[1])
    route = net.default_route_address()  # sends nothing; None without a network
    assert route is None or isinstance(route, str)


def _proc(tmp_path: Path, route: str, arp: str) -> Path:
    (tmp_path / "net").mkdir(parents=True, exist_ok=True)
    (tmp_path / "net" / "route").write_text(route, encoding="ascii")
    (tmp_path / "net" / "arp").write_text(arp, encoding="ascii")
    return tmp_path


ROUTE = (
    "Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT\n"
    "wlan0\t00000000\t01B2A8C0\t0003\t0\t0\t600\t00000000\t0\t0\t0\n"
    "wlan0\t00B2A8C0\t00000000\t0001\t0\t0\t600\t00FFFFFF\t0\t0\t0\n"
)
ARP = (
    "IP address       HW type     Flags       HW address            Mask     Device\n"
    "192.168.178.1    0x1         0x2         3c:a6:2f:01:02:03     *        wlan0\n"
)


def test_the_router_s_fingerprint_is_its_address_and_hardware_address(tmp_path: Path) -> None:
    assert net.gateway_fingerprint(_proc(tmp_path, ROUTE, ARP)) == "192.168.178.1 3c:a6:2f:01:02:03"


def test_an_unreadable_router_has_no_fingerprint(tmp_path: Path) -> None:
    no_entry = ARP.splitlines()[0] + "\n"
    assert net.gateway_fingerprint(_proc(tmp_path / "a", ROUTE, no_entry)) is None
    no_route = ROUTE.splitlines()[0] + "\n"
    assert net.gateway_fingerprint(_proc(tmp_path / "b", no_route, ARP)) is None
    incomplete = ARP.replace("3c:a6:2f:01:02:03", "00:00:00:00:00:00")
    assert net.gateway_fingerprint(_proc(tmp_path / "c", ROUTE, incomplete)) is None


def test_the_test_hook_never_reads_the_router(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(net.TEST_ADDRESS_ENV, "127.0.0.1")
    assert net.Network().gateway() is None
    assert [c.address for c in net.Network().candidates()] == ["127.0.0.1"]
