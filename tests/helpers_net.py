"""A loopback port for a test that starts a server (or has ``ordnung serve`` check one) on a port it names.

Asking the system for a free port (bind to port 0, read it, close) hands back a port from its ephemeral
range, the range it also hands every other process that binds port 0 or opens a connection: between the
close and the server's bind, a test in a parallel worker can be given the same port. These ports come from
below every system's ephemeral range (Linux from 32768, macOS and Windows from 49152), which no process is
handed without asking for it by number, and each pytest-xdist worker counts through a slice of its own, so
two tests of one run never meet on a port. A port that something holds after all (another run on the same
computer, a port Windows reserves) fails the bind here and the next one is taken.
"""

from __future__ import annotations

import itertools
import os
import random
import socket

FIRST_PORT = 20000
PORTS = 10000
SLICES = 40  # workers beyond this many share a slice and rely on the bind below
LOOPBACK = "127.0.0.1"


def _slice() -> range:
    worker = os.environ.get("PYTEST_XDIST_WORKER", "gw0")  # "gw3" in worker 3; unset outside xdist
    digits = worker.removeprefix("gw")
    index = int(digits) % SLICES if digits.isdigit() else 0
    size = PORTS // SLICES
    return range(FIRST_PORT + index * size, FIRST_PORT + (index + 1) * size)


_SLICE = _slice()
# a random start, so two runs on one computer (each with its own worker 0) rarely count through the same ports
_NEXT = itertools.islice(itertools.cycle(_SLICE), random.randrange(len(_SLICE)), None)


def free_port(host: str = LOOPBACK) -> int:
    """A port on ``host`` that nothing holds now and no other test of this run will be given."""
    for _ in range(len(_SLICE)):
        port = next(_NEXT)
        with socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET) as probe:
            try:
                probe.bind((host, port))
            except OSError:
                continue
        return port
    raise RuntimeError(f"no free port on {host} in {_SLICE.start}-{_SLICE.stop - 1}")
