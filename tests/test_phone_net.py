"""Which addresses phone access may listen on (home networks, never a tunnel, the router's network
recommended), whom it answers (its own subnet only), the tests' loopback hook and the router's fingerprint."""

from __future__ import annotations

import socket
from pathlib import Path

import ifaddr
import pytest

from ordnung.phone import net
from ordnung.phone.net import Candidate, Interface, candidate_addresses, client_allowed, usable


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
    assert candidate_addresses([Interface("en0", "192.168.1.5", 24)]) == [
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
    # VPN clients on Linux: Cisco AnyConnect, GlobalProtect, NordVPN, Proton VPN, Hamachi, a plain "vpn0"
    "cscotun0",
    "gpd0",
    "nordlynx",
    "nordtun",
    "proton0",
    "pvpnksintrf0",
    "ham0",
    "vpn0",
    # containers and virtual machines: LXD and LXC, Kubernetes, Podman, macOS's shared networks, Parallels
    "lxdbr0",
    "lxcbr0",
    "cni0",
    "flannel.1",
    "cali4f2e81a7c3d",
    "kube-ipvs0",
    "podman0",
    "bridge100",
    "vmenet0",
    "vnic0",
]


@pytest.mark.parametrize("name", TUNNELS)
def test_tunnels_vms_and_containers_are_never_offered(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.delenv(net.TEST_ADDRESS_ENV, raising=False)
    found = [Interface(name, "10.8.0.6", 24), Interface("en0", "192.168.178.23", 24)]
    assert [c.address for c in candidate_addresses(found, default="10.8.0.6")] == ["192.168.178.23"]


def test_candidates_come_from_interfaces_with_the_default_route_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(net.TEST_ADDRESS_ENV, raising=False)
    found = [
        Interface("lo", "127.0.0.1", 8),
        Interface("en7", "192.168.0.40", None),
        Interface("en0", "192.168.178.23", 24),
        Interface("en0", "192.168.178.23", 24),
        Interface("en1", "169.254.3.4", 16),
        Interface("en2", "fd00::1", 64),
    ]
    assert candidate_addresses(found, default="192.168.178.23") == [
        Candidate("192.168.178.23", "en0", "192.168.178.0/24", recommended=True),
        Candidate("192.168.0.40", "en7", "192.168.0.0/24"),  # no netmask: /24
    ]
    # a VPN that took the default route is never recommended
    assert candidate_addresses(found, default="10.8.0.6")[0].address == "192.168.0.40"
    assert candidate_addresses([], default="192.168.1.5") == []


def _adapters(monkeypatch: pytest.MonkeyPatch, *adapters: ifaddr.Adapter) -> None:
    monkeypatch.delenv(net.TEST_ADDRESS_ENV, raising=False)
    monkeypatch.setattr(ifaddr, "get_adapters", lambda *args, **kwargs: list(adapters))


def _windows(description: str, name: str, address: str, prefix: int) -> ifaddr.Adapter:
    """An adapter as ``ifaddr`` lists it on Windows: a GUID, the driver's description as the adapter's
    name, and the name people see ("Wi-Fi", "vEthernet (WSL)") on each of its addresses."""
    guid = "{4D36E972-E325-11CE-BFC1-08002BE10318}"
    return ifaddr.Adapter(guid, description, [ifaddr.IP(address, prefix, name)])


def _linux(name: str, address: str, prefix: int) -> ifaddr.Adapter:
    """An adapter as ``ifaddr`` lists it on Linux and macOS: one name everywhere, an IPv6 address too."""
    ips = [ifaddr.IP(address, prefix, name), ifaddr.IP(("fe80::1", 0, 3), 64, name)]
    return ifaddr.Adapter(name, name, ips)


WI_FI = ("Intel(R) Wi-Fi 6 AX201 160MHz", "Wi-Fi", "192.168.178.23", 24)
WINDOWS_TUNNELS = [
    ("Hyper-V Virtual Ethernet Adapter", "vEthernet (WSL)", "172.27.112.1", 20),
    ("Hyper-V Virtual Ethernet Adapter #2", "vEthernet (Default Switch)", "172.20.48.1", 20),
    ("VirtualBox Host-Only Ethernet Adapter", "Ethernet 2", "192.168.56.1", 24),
    ("VMware Virtual Ethernet Adapter for VMnet8", "VMware Network Adapter VMnet8", "192.168.80.1", 24),
    ("WireGuard Tunnel", "wg-home", "10.64.0.2", 32),
    ("Wintun Userspace Tunnel", "ProtonVPN", "10.2.0.2", 32),
    ("TAP-Windows Adapter V9", "Ethernet 6", "10.8.0.6", 24),
    ("OpenVPN Data Channel Offload", "OpenVPN Data Channel Offload", "10.8.1.6", 24),
    (
        "Cisco AnyConnect Secure Mobility Client Virtual Miniport Adapter for Windows x64",
        "Ethernet 3",
        "10.20.30.40",
        24,
    ),
    ("Cisco Secure Client Virtual Miniport Adapter for Windows x64", "Ethernet 7", "10.20.31.40", 24),
    ("PANGP Virtual Ethernet Adapter Secure", "Ethernet 4", "10.21.0.5", 24),
    ("Fortinet SSL VPN Virtual Ethernet Adapter", "Ethernet 5", "10.212.134.200", 32),
    ("Tailscale Tunnel", "Tailscale", "10.99.0.2", 24),
    ("ZeroTier Virtual Port", "ZeroTier One [8056c2e21c000001]", "10.147.17.5", 24),
    ("NordLynx Tunnel", "NordLynx", "10.5.0.2", 32),
    ("LogMeIn Hamachi Virtual Ethernet Adapter", "Hamachi", "10.9.0.3", 24),
    ("Sophos SSL VPN Adapter", "Ethernet 8", "10.242.2.5", 24),
]


@pytest.mark.parametrize("router", ["192.168.178.1", None])
def test_on_windows_a_tunnel_is_known_by_its_adapter_s_description_or_its_name(
    monkeypatch: pytest.MonkeyPatch, router: str | None
) -> None:
    """Risk review: on Windows ``ifaddr`` names an adapter by its description and gives the name people
    see to each address, so a filter of the adapter's name alone offered Hyper-V, WSL, VirtualBox, VMware
    and WireGuard, and recommended a VPN that held the default route."""
    _adapters(monkeypatch, *(_windows(*tunnel) for tunnel in WINDOWS_TUNNELS), _windows(*WI_FI))
    monkeypatch.setattr(net, "default_gateway", lambda: router)
    assert candidate_addresses(default="10.20.30.40") == [
        Candidate("192.168.178.23", "Wi-Fi", "192.168.178.0/24", recommended=True)
    ]


@pytest.mark.parametrize(
    "description",
    [
        "Intel(R) Ethernet Connection (7) I219-V",
        "Realtek PCIe GbE Family Controller",
        "Killer(R) Wi-Fi 6 AX1650i 160MHz Wireless Network Adapter (201NGW)",
        "Realtek USB GbE Family Controller",
        "Apple Mobile Device Ethernet",
        "Microsoft Wi-Fi Direct Virtual Adapter",
    ],
)
def test_on_windows_an_ordinary_adapter_is_offered(monkeypatch: pytest.MonkeyPatch, description: str) -> None:
    _adapters(monkeypatch, _windows(description, "Ethernet", "192.168.178.23", 24))
    found = candidate_addresses(default="192.168.178.23", router="192.168.178.1")
    assert [(c.interface, c.recommended) for c in found] == [("Ethernet", True)]


def test_a_hyper_v_switch_the_router_is_on_carries_the_computer_s_own_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An external Hyper-V switch moves the computer's own address onto a "vEthernet" adapter: offered
    when the router is on its network, while WSL's beside it never is."""
    _adapters(
        monkeypatch,
        _windows("Hyper-V Virtual Ethernet Adapter", "vEthernet (WSL)", "172.27.112.1", 20),
        _windows("Hyper-V Virtual Ethernet Adapter #2", "vEthernet (External)", "192.168.178.23", 24),
    )
    assert candidate_addresses(default="192.168.178.23", router="192.168.178.1") == [
        Candidate("192.168.178.23", "vEthernet (External)", "192.168.178.0/24", recommended=True)
    ]
    monkeypatch.setattr(net, "default_gateway", lambda: None)
    assert candidate_addresses(default="192.168.178.23") == []  # the router unknown: not offered


def test_the_address_on_the_router_s_network_is_recommended_over_a_vpn_s_default_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A full-tunnel VPN owns the default route: the address recommended is the one on the router's
    network, never the tunnel's — not even a tunnel by a name Ordnung doesn't know."""
    _adapters(
        monkeypatch,
        _linux("lo", "127.0.0.1", 8),
        _linux("eth1", "192.168.0.40", 24),
        _linux("wlan0", "192.168.178.23", 24),
        _linux("tun0", "10.8.0.6", 24),
        _linux("docker0", "172.17.0.1", 16),
        _linux("corp0", "10.20.30.40", 24),  # a VPN by a name Ordnung doesn't know
    )
    wlan0 = Candidate("192.168.178.23", "wlan0", "192.168.178.0/24", recommended=True)
    for default in ("10.8.0.6", "10.20.30.40", "192.168.0.40"):
        found = candidate_addresses(default=default, router="192.168.178.1")
        assert found[0] == wlan0, default
        assert [c.address for c in found] == ["192.168.178.23", "192.168.0.40", "10.20.30.40"]
    # the router unknown: the default route's address when it is offered, else the first
    monkeypatch.setattr(net, "default_gateway", lambda: None)
    assert candidate_addresses(default="10.8.0.6")[0].address == "192.168.0.40"
    assert candidate_addresses(default="192.168.178.23")[0].address == "192.168.178.23"


def test_the_router_is_read_with_the_interfaces(monkeypatch: pytest.MonkeyPatch) -> None:
    _adapters(monkeypatch, _linux("eth1", "192.168.0.40", 24), _linux("wlan0", "192.168.178.23", 24))
    monkeypatch.setattr(net, "default_gateway", lambda: "192.168.178.1")
    assert candidate_addresses(default="192.168.0.40")[0].address == "192.168.178.23"


def test_the_interfaces_can_be_listed() -> None:
    found = net.interfaces()
    assert all(isinstance(i.name, str) and isinstance(i.address, str) for i in found)


def test_windows_interfaces_carry_the_name_people_see_and_the_adapter_s_description(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _adapters(monkeypatch, _windows(*WI_FI), _linux("eth0", "192.168.1.5", 24))
    assert net.interfaces() == [
        Interface("Wi-Fi", "192.168.178.23", 24, "Intel(R) Wi-Fi 6 AX201 160MHz"),
        Interface("eth0", "192.168.1.5", 24),
    ]


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


# a full-tunnel VPN: OpenVPN's two halves of the internet and a VPN's own default route (a lower metric),
# all through tun0 and listed before the router's
FULL_TUNNEL_ROUTE = (
    "Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT\n"
    "tun0\t00000000\t0100080A\t0003\t0\t0\t0\t00000080\t0\t0\t0\n"
    "tun0\t00000000\t0100080A\t0003\t0\t0\t50\t00000000\t0\t0\t0\n"
    "wlan0\t00000000\t01B2A8C0\t0003\t0\t0\t600\t00000000\t0\t0\t0\n"
    "tun0\t00000080\t0100080A\t0003\t0\t0\t0\t00000080\t0\t0\t0\n"
    "wlan0\t00B2A8C0\t00000000\t0001\t0\t0\t600\t00FFFFFF\t0\t0\t0\n"
)


def test_the_router_behind_a_full_tunnel_vpn_is_the_home_network_s(tmp_path: Path) -> None:
    proc = _proc(tmp_path, FULL_TUNNEL_ROUTE, ARP)
    assert net.default_gateway(proc) == "192.168.178.1"
    assert net.gateway_fingerprint(proc) == "192.168.178.1 3c:a6:2f:01:02:03"
    assert net.default_gateway(_proc(tmp_path / "plain", ROUTE, ARP)) == "192.168.178.1"
    assert net.default_gateway(_proc(tmp_path / "none", ROUTE.splitlines()[0] + "\n", ARP)) is None


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
