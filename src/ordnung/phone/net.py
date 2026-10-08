"""This computer's addresses on a home network, who may talk to the phone listener, and whether the
network is still the one phone access was turned on in (policy: :mod:`ordnung.phone`).

* **Home networks only.** An address is usable when it is IPv4 inside 10/8, 172.16/12 or 192.168/16
  (:data:`HOME_NETWORKS`; ``is_private`` isn't used: it also says yes to link-local 169.254/16 and no
  to nothing else that matters here).
* **Interfaces, not guesses.** The candidates come from the network interfaces with their names and
  netmasks (``ifaddr``; on Windows both the name people see, "vEthernet (WSL)", and the adapter's
  description, "Hyper-V Virtual Ethernet Adapter", are checked). Tunnels and VPNs
  (:data:`TUNNEL_INTERFACES`: ``utun``, ``wg``, ``tailscale``, "WireGuard", "AnyConnect" …) are never
  offered, so the pairing page never ends up on a company VPN; containers and virtual machines
  (:data:`VIRTUAL_INTERFACES`: ``docker``, ``vboxnet``, "Hyper-V" …) neither, unless the router is on
  their network (an external Hyper-V switch or a bridge then carries this computer's own home network).
* **The router's network is recommended.** The candidate whose network holds the router is the
  recommended one; when none does or the router can't be read, the address this computer reaches the
  internet from (a UDP "connect" that sends nothing) when it is a candidate, else the first — so a VPN
  that took the default route isn't recommended over the address on the router's network, even one by
  a name Ordnung doesn't know.
* **Only the home network's own devices.** The listener answers a client in the bound address's subnet
  (``/24`` when the netmask is unknown) or the address itself (:func:`client_allowed`): a Docker
  container on 172.17.0.2 or a peer behind a VPN on 10.8.0.6 is refused.
* **The same address on another network.** :func:`gateway_fingerprint` reads the default gateway and its
  hardware address (``/proc/net/route`` and ``/proc/net/arp`` on Linux, ``route``/``arp`` elsewhere),
  best effort: a café whose router hands out the same address as home is told apart when it can be
  read, and when it can't nothing changes. On Linux the default route of a tunnel or VPN, and the two
  halves of the internet a full-tunnel VPN routes through itself, are passed over for the router's.
* **Tests and the browser tests** set :data:`TEST_ADDRESS_ENV` to a loopback address: it is then the only
  candidate (any other value is ignored).
"""

from __future__ import annotations

import contextlib
import ipaddress
import logging
import os
import re
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("ordnung.phone")

HOME_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
)
#: Tests and the browser tests only: a loopback address phone access then listens on (anything else is
#: ignored, so it can never open the listener to a network).
TEST_ADDRESS_ENV = "ORDNUNG_PHONE_TEST_ADDRESS"
#: Interfaces that are never offered: tunnels and VPNs and Apple's peer-to-peer links. A name starting
#: with one of the first group, or (a Windows adapter's description, mostly) holding one of the second.
TUNNEL_INTERFACES = re.compile(
    r"^(?:utun|tun|tap|wg|ppp|ipsec|tailscale|zt|awdl|llw|cscotun|gpd|nordlynx|nordtun|proton|pvpn|ham)"
    r"|WireGuard|Wintun|\bTAP-|VPN|AnyConnect|Cisco Secure Client|PANGP|Fortinet|ZeroTier|Hamachi"
    r"|Juniper|Mullvad",
    re.IGNORECASE,
)
#: Containers' and virtual machines' networks: never offered either, unless the router is on one (an
#: external Hyper-V switch, or a bridge, then carries this computer's own home network).
VIRTUAL_INTERFACES = re.compile(
    r"^(?:docker|br-|veth|virbr|vboxnet|vmnet|vEthernet|lxdbr|lxcbr|cni|flannel|cali|kube|podman|bridge"
    r"|vmenet|vnic)|Hyper-V|VirtualBox|VMware",
    re.IGNORECASE,
)
#: The netmask assumed when an interface doesn't say.
DEFAULT_PREFIX = 24
_PROBE_TARGET = ("192.0.2.1", 9)  # TEST-NET-1: a UDP "connect" picks the route and sends nothing
_COMMAND_TIMEOUT_S = 2.0
_MAC = re.compile(r"\b([0-9a-f]{1,2}(?:[:-][0-9a-f]{1,2}){5})\b", re.IGNORECASE)


@dataclass(frozen=True)
class Candidate:
    """An address of this computer that phone access could listen on."""

    address: str
    interface: str
    subnet: str
    recommended: bool = False


@dataclass(frozen=True)
class Interface:
    """An IPv4 address of one of this computer's network interfaces."""

    name: str  # the name people see: "en0", "wlan0", "Wi-Fi", "vEthernet (WSL)"
    address: str
    prefix: int | None
    description: str = ""  # Windows: the adapter's ("Hyper-V Virtual Ethernet Adapter")


# --------------------------------------------------------------------------------------------------
# addresses
# --------------------------------------------------------------------------------------------------


def usable(ip: str) -> bool:
    """An IPv4 address on a home network (10/8, 172.16/12, 192.168/16)."""
    try:
        parsed = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return isinstance(parsed, ipaddress.IPv4Address) and any(parsed in net for net in HOME_NETWORKS)


def test_address() -> str | None:
    """The loopback address :data:`TEST_ADDRESS_ENV` names (``None``: unset, or not a loopback address)."""
    value = os.environ.get(TEST_ADDRESS_ENV, "").strip()
    try:
        parsed = ipaddress.ip_address(value)
    except ValueError:
        return None
    return value if isinstance(parsed, ipaddress.IPv4Address) and parsed.is_loopback else None


def subnet_of(address: str, prefix: int | None) -> str:
    """The network of ``address`` (``/24`` when the prefix is unknown or implausible)."""
    bits = prefix if prefix is not None and 8 <= prefix <= 32 else DEFAULT_PREFIX
    return str(ipaddress.ip_network(f"{address}/{bits}", strict=False))


def default_route_address() -> str | None:
    """The address this computer reaches the internet from (no packet is sent)."""
    with contextlib.suppress(OSError), socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect(_PROBE_TARGET)
        address = sock.getsockname()[0]
        return str(address) if address and address != "0.0.0.0" else None
    return None


def interfaces() -> list[Interface]:
    """Every IPv4 address of every interface, with the interface's names and the netmask (``ifaddr``)."""
    import ifaddr  # pure Python; imported on first use

    found: list[Interface] = []
    for adapter in ifaddr.get_adapters():
        # Windows names an adapter by a GUID and its description ("Hyper-V Virtual Ethernet Adapter") and
        # each of its addresses by the name people see ("vEthernet (WSL)"); elsewhere all are one name
        adapter_name = str(adapter.nice_name or adapter.name or "")
        for ip in adapter.ips:
            if isinstance(ip.ip, str):  # IPv6 addresses are tuples
                name = str(ip.nice_name or adapter_name)
                prefix = ip.network_prefix if isinstance(ip.network_prefix, int) else None
                found.append(Interface(name, ip.ip, prefix, adapter_name if adapter_name != name else ""))
    return found


def _named(pattern: re.Pattern[str], *names: str) -> bool:
    return any(pattern.search(name.strip()) for name in names if name)


def is_tunnel(*names: str) -> bool:
    """A tunnel, VPN, container, virtual machine or peer-to-peer interface by any of its names (never
    offered, but for a container's or virtual machine's network the router is on)."""
    return _named(TUNNEL_INTERFACES, *names) or _named(VIRTUAL_INTERFACES, *names)


def _holds(subnet: str, router: str | None) -> bool:
    """Whether the router's address is in ``subnet``."""
    if router is None:
        return False
    try:
        return ipaddress.ip_address(router) in ipaddress.ip_network(subnet, strict=False)
    except ValueError:
        return False


def _offered(interface: Interface, subnet: str, router: str | None) -> bool:
    names = (interface.name, interface.description)
    if _named(TUNNEL_INTERFACES, *names):
        return False
    return not _named(VIRTUAL_INTERFACES, *names) or _holds(subnet, router)


def candidate_addresses(
    found: list[Interface] | None = None, default: str | None = None, router: str | None = None
) -> list[Candidate]:
    """This computer's addresses on home networks, the recommended one first: never a tunnel's or a VPN's,
    and a container's or virtual machine's only when the router is on its network. The one on the
    router's network is recommended; when none is or the router can't be read, the default route's
    address when it is a candidate, else the first.

    ``found``, ``default`` and ``router`` replace :func:`interfaces`, :func:`default_route_address` and
    :func:`default_gateway` (tests; with ``found`` given, the router is only what ``router`` says).
    """
    loopback = test_address()
    if loopback is not None:
        return [Candidate(loopback, "loopback", subnet_of(loopback, 32), recommended=True)]
    if found is None:
        try:
            found = interfaces()
        except Exception:  # an interface listing that fails is no reason to fail the page
            log.warning("phone access: the network interfaces couldn't be read", exc_info=True)
            found = []
        if router is None:
            router = default_gateway()
    route = default if default is not None else default_route_address()
    seen: set[str] = set()
    candidates: list[Candidate] = []
    for interface in found:
        address = interface.address
        if not usable(address) or address in seen:
            continue
        subnet = subnet_of(address, interface.prefix)
        if not _offered(interface, subnet, router):
            continue
        seen.add(address)
        candidates.append(Candidate(address, interface.name, subnet))
    if not candidates:
        return []
    home = [c for c in candidates if _holds(c.subnet, router)] or candidates
    chosen = next((c for c in home if c.address == route), home[0])
    ordered = [chosen, *(c for c in candidates if c is not chosen)]
    return [Candidate(c.address, c.interface, c.subnet, recommended=c is chosen) for c in ordered]


def address_is_local(ip: str) -> bool:
    """Whether this computer has ``ip`` now (a socket can be bound to it)."""
    with contextlib.suppress(OSError), socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((ip, 0))
        return True
    return False


def port_free(ip: str, port: int) -> bool:
    """Whether a listener could bind ``ip:port`` now (the same test as ``ordnung serve``'s)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((ip, port))
        except OSError:
            return False
    return True


def client_allowed(client_ip: str, bound: str, subnet: str | None) -> bool:
    """A client the phone listener answers: the bound address itself or a device in its subnet."""
    if client_ip == bound:
        return True
    try:
        client = ipaddress.ip_address(client_ip)
        network = ipaddress.ip_network(subnet or subnet_of(bound, None), strict=False)
    except ValueError:
        return False
    return isinstance(client, ipaddress.IPv4Address) and client in network


# --------------------------------------------------------------------------------------------------
# the network's router (best effort)
# --------------------------------------------------------------------------------------------------


def _run(*args: str) -> str:
    try:
        done = subprocess.run(  # fixed system tools, no shell
            args, capture_output=True, text=True, timeout=_COMMAND_TIMEOUT_S, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout or ""


def _linux_gateway(proc: Path) -> str | None:
    try:
        lines = (proc / "net" / "route").read_text(encoding="ascii").splitlines()[1:]
    except OSError:
        return None
    for line in lines:
        fields = line.split()
        if (
            len(fields) > 7
            and fields[1] == "00000000"
            and fields[7] == "00000000"  # to everywhere, not a full-tunnel VPN's 0/1 or 128/1
            and int(fields[3], 16) & 0x2  # RTF_GATEWAY
            and not _named(TUNNEL_INTERFACES, fields[0])
        ):
            return str(ipaddress.IPv4Address(bytes.fromhex(fields[2])[::-1]))
    return None


def _linux_mac(proc: Path, gateway: str) -> str | None:
    try:
        lines = (proc / "net" / "arp").read_text(encoding="ascii").splitlines()[1:]
    except OSError:
        return None
    for line in lines:
        fields = line.split()
        if len(fields) > 3 and fields[0] == gateway and fields[3] != "00:00:00:00:00:00":
            return fields[3]
    return None


def _command_gateway() -> str | None:
    if sys.platform == "win32":
        output = _run("route", "print", "-4", "0.0.0.0")
        for line in output.splitlines():
            fields = line.split()
            if len(fields) >= 3 and fields[0] == "0.0.0.0" and fields[1] == "0.0.0.0" and usable(fields[2]):
                return fields[2]
        return None
    output = _run("route", "-n", "get", "default")
    match = re.search(r"gateway:\s*(\S+)", output)
    return match.group(1) if match and usable(match.group(1)) else None


def _command_mac(gateway: str) -> str | None:
    output = _run("arp", "-a", gateway) if sys.platform == "win32" else _run("arp", "-n", gateway)
    for line in output.splitlines():
        if gateway in line:
            match = _MAC.search(line)
            if match:
                return match.group(1)
    return None


def _normalised_mac(mac: str) -> str:
    return ":".join(part.zfill(2) for part in re.split(r"[:-]", mac.lower()))


def default_gateway(proc: Path = Path("/proc")) -> str | None:
    """The router's address: the default gateway's (``None``: unreadable)."""
    try:
        return _linux_gateway(proc) if (proc / "net" / "route").is_file() else _command_gateway()
    except Exception:  # best effort: an unreadable router is not an error
        log.debug("phone access: the router couldn't be read", exc_info=True)
        return None


def gateway_fingerprint(proc: Path = Path("/proc")) -> str | None:
    """The default gateway's address and hardware address (``"192.168.178.1 3c:a6:2f:…"``), or ``None``
    when either can't be read (then nothing is compared)."""
    gateway = default_gateway(proc)
    if not gateway:
        return None
    try:
        mac = _linux_mac(proc, gateway) if (proc / "net" / "route").is_file() else _command_mac(gateway)
    except Exception:  # best effort: an unreadable router is not an error
        log.debug("phone access: the router couldn't be read", exc_info=True)
        return None
    if not mac:
        return None
    return f"{gateway} {_normalised_mac(mac)}"


# --------------------------------------------------------------------------------------------------
# what phone access asks of the network (replaced in tests)
# --------------------------------------------------------------------------------------------------


class Network:
    """The network as phone access sees it; tests replace it with a fake."""

    def candidates(self) -> list[Candidate]:
        """This computer's addresses on home networks now."""
        return candidate_addresses()

    def is_local(self, address: str) -> bool:
        """Whether this computer has ``address`` now."""
        return address_is_local(address)

    def port_free(self, address: str, port: int) -> bool:
        """Whether ``address:port`` can be bound now."""
        return port_free(address, port)

    def gateway(self) -> str | None:
        """The router's fingerprint (``None``: unreadable)."""
        if test_address() is not None:
            return None
        return gateway_fingerprint()
