"""Pairing a phone: the one-time code, its tries, the phone's name and the two check words (policy:
:mod:`ordnung.phone`).

* **The code.** :data:`CODE_LENGTH` characters of Crockford's base 32 (50 bits; no I, L, O or U),
  shown as ``K7QM2-XD9PA`` and in the QR code's link after ``#`` (a fragment never reaches a server's
  request line or a link preview). It works once, for :data:`PAIRING_TTL_S` seconds; a new code replaces
  the open one, and it ends when a phone pairs, the computer's dialog closes, phone access goes off or
  Ordnung restarts. Only its SHA-256 is kept, in memory: no hash of a 50-bit code is ever written where
  it could be guessed offline. A typed code is read leniently (case, spaces, dashes, O for 0, I or L for
  1) and compared in constant time.
* **One answer for every wrong code.** A wrong, expired or missing code all get 422 ``wrong_code``, so
  a guess learns nothing about whether a code is open. One device (address) gets
  :data:`PAIRING_TRIES_PER_CLIENT` wrong tries for a code, then it is locked out of that code (429);
  :data:`PAIRING_TRIES_TOTAL` wrong tries from the whole network cancel the code and tell the computer
  which addresses typed them. With 100 tries a guess succeeds with odds of at most 100 in 2⁵⁰. The
  listener's gate also limits pairing requests to :data:`PAIR_POSTS_PER_CLIENT_PER_MINUTE` per
  address and :data:`PAIR_POSTS_PER_MINUTE` in all.
* **A code used twice pairs nobody.** After a phone pairs, the code's hash stays with that phone's id
  until the code would have expired. If the code comes again from anyone else, two devices had it —
  someone may have seen the screen — so the phone that used it first is removed as well, and the
  computer says so.
* **Atomic.** Checking and spending a code happen in one synchronous step on the event loop, so two
  requests with the right code can't both pair.
* **Names and check words.** A phone's name loses control and invisible formatting characters (bidi
  controls, zero-width spaces), so it reads on the computer as it was typed. The phone and the computer
  both show two words derived from the phone's id with a key only this computer has: a phone showing
  other words than the computer's row isn't that phone.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time
import unicodedata
from collections import deque
from dataclasses import dataclass, field
from typing import Literal

CODE_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
CODE_LENGTH = 10
PAIRING_TTL_S = 600
PAIRING_TRIES_PER_CLIENT = 5
PAIRING_TRIES_TOTAL = 100
PAIR_POSTS_PER_CLIENT_PER_MINUTE = 10
PAIR_POSTS_PER_MINUTE = 60
#: The largest pairing request accepted before a phone is signed in (a code and a name fit easily).
PAIR_MAX_BYTES = 1024
MAX_NAME = 40
DEFAULT_NAME = "Phone"

CHECK_ADJECTIVES = (
    "amber", "brave", "calm", "dusty", "eager", "fuzzy", "gentle", "hollow", "ivory", "jolly", "keen",
    "lucky", "misty", "noble", "olive", "proud", "quiet", "rosy", "sunny", "tidy", "urban", "vivid",
    "warm", "young", "zesty", "bold", "crisp", "dainty", "early", "fancy", "golden", "happy", "icy",
    "jade", "kind", "lively", "merry", "neat", "orange", "plain", "quick", "royal", "silver", "tall",
    "upbeat", "velvet", "wild", "yellow", "breezy", "cosy", "dapper", "fresh", "glossy", "humble",
    "jazzy", "lemon", "mellow", "nimble", "polite", "rapid", "shiny", "tender", "witty", "sandy",
)  # fmt: skip
CHECK_NOUNS = (
    "tulip", "otter", "harbor", "maple", "comet", "pebble", "falcon", "willow", "lantern", "meadow",
    "orchid", "river", "saffron", "thistle", "violet", "walnut", "acorn", "badger", "canyon", "daisy",
    "ember", "fern", "garden", "heron", "island", "jasmine", "kettle", "lagoon", "marble", "nutmeg",
    "oyster", "parrot", "quartz", "robin", "salmon", "tiger", "umbrella", "valley", "whale", "yarrow",
    "almond", "beacon", "cedar", "dolphin", "feather", "glacier", "hazel", "iris", "juniper", "koala",
    "lily", "mango", "nectar", "olive", "panda", "quill", "raven", "spruce", "teapot", "urchin",
    "vessel", "wren", "zebra", "basil",
)  # fmt: skip

_CODE_RE = re.compile(f"^[{CODE_ALPHABET}]{{{CODE_LENGTH}}}$")
_INVISIBLE = {"Cc", "Cf", "Co", "Cs", "Zl", "Zp"}


# --------------------------------------------------------------------------------------------------
# codes, names, words
# --------------------------------------------------------------------------------------------------


def new_code() -> str:
    """A fresh pairing code (50 random bits)."""
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def normalise(raw: str) -> str:
    """A typed code as it is compared: upper case, ``O`` → ``0``, ``I``/``L`` → ``1``, no spaces or dashes."""
    value = raw.upper().replace("O", "0").replace("I", "1").replace("L", "1")
    return re.sub(r"[\s\-‐‑‒–—−]", "", value)


def shown(code: str) -> str:
    """The code as the computer shows it (``K7QM2-XD9PA``)."""
    return f"{code[:5]}-{code[5:]}"


def code_hash(code: str) -> str:
    return hashlib.sha256(normalise(code).encode("ascii", "replace")).hexdigest()


def clean_name(raw: str) -> str:
    """A phone's name without control or invisible formatting characters, spaces collapsed, at most
    :data:`MAX_NAME` characters (``Phone`` when nothing is left)."""
    kept = "".join(
        " " if char.isspace() else char for char in raw if unicodedata.category(char) not in _INVISIBLE
    )
    return " ".join(kept.split())[:MAX_NAME].strip() or DEFAULT_NAME


def unique_name(name: str, taken: set[str]) -> str:
    """``name``, or ``name (2)``, ``name (3)`` … when another phone has it (case-insensitively)."""
    lowered = {value.casefold() for value in taken}
    if name.casefold() not in lowered:
        return name
    number = 2
    while True:
        suffix = f" ({number})"
        candidate = name[: MAX_NAME - len(suffix)].rstrip() + suffix
        if candidate.casefold() not in lowered:
            return candidate
        number += 1


def check_words(key: str, device_id: str) -> str:
    """The two words the phone and the computer both show for a paired phone (“amber tulip”)."""
    digest = hmac.new(bytes.fromhex(key), f"check words {device_id}".encode(), hashlib.sha256).digest()
    return (
        f"{CHECK_ADJECTIVES[digest[0] % len(CHECK_ADJECTIVES)]} {CHECK_NOUNS[digest[1] % len(CHECK_NOUNS)]}"
    )


def new_check_key() -> str:
    return secrets.token_hex(16)


_BROWSERS: tuple[tuple[str, str], ...] = (
    (r"SamsungBrowser/", "Samsung Internet"),
    (r"EdgiOS/|EdgA/|Edg/", "Edge"),
    (r"FxiOS/|Firefox/", "Firefox"),
    (r"OPiOS/|OPR/", "Opera"),
    (r"DuckDuckGo/", "DuckDuckGo"),
    (r"CriOS/|Chrome/", "Chrome"),
    (r"Version/[\d.]+.*Safari/", "Safari"),
)


def platform_label(user_agent: str | None) -> str:
    """A summary of a browser (“iPhone · Safari”, “Android · Chrome”): never the User-Agent itself."""
    agent = user_agent or ""
    if "iPhone" in agent:
        device = "iPhone"
    elif "iPad" in agent or ("Macintosh" in agent and "Mobile/" in agent):
        device = "iPad"
    elif "Android" in agent:
        device = "Android"
    elif "Windows" in agent:
        device = "Windows"
    elif "Macintosh" in agent:
        device = "Mac"
    elif "Linux" in agent:
        device = "Linux"
    else:
        device = "Phone"
    browser = next((name for pattern, name in _BROWSERS if re.search(pattern, agent)), None)
    if browser is None and device in ("iPhone", "iPad"):
        browser = "Safari"  # an in-app browser on iOS is WebKit
    return f"{device} · {browser}" if browser else device


# --------------------------------------------------------------------------------------------------
# rate limits
# --------------------------------------------------------------------------------------------------


class SlidingLimit:
    """At most ``limit`` events per ``window_s`` seconds per key."""

    def __init__(self, limit: int, window_s: float) -> None:
        self.limit = limit
        self.window_s = window_s
        self._events: dict[str, deque[float]] = {}

    def take(self, key: str, now: float | None = None, *, count: int = 1) -> int:
        """``0`` when ``count`` more events are allowed now (and count), else the seconds until they
        would be (then none of them counts). ``count`` must be at most ``limit``."""
        moment = time.monotonic() if now is None else now
        events = self._events.setdefault(key, deque())
        while events and moment - events[0] >= self.window_s:
            events.popleft()
        over = len(events) + count - self.limit
        if over > 0:
            return max(1, int(self.window_s - (moment - events[over - 1])) + 1)
        events.extend([moment] * count)
        return 0

    def give_back(self, key: str) -> None:
        """Undo the latest event of ``key`` (one that turned out not to happen)."""
        events = self._events.get(key)
        if events:
            events.pop()

    def clear(self) -> None:
        self._events.clear()


# --------------------------------------------------------------------------------------------------
# the open code
# --------------------------------------------------------------------------------------------------


@dataclass
class OpenCode:
    """The code waiting for a phone (only its hash)."""

    digest: str
    expires: float
    opened_at: str | None = None
    opened_from: str | None = None
    wrong: dict[str, int] = field(default_factory=dict)

    @property
    def wrong_tries(self) -> int:
        return sum(self.wrong.values())


@dataclass(frozen=True)
class Redeemed:
    """What a pairing request's code turned out to be."""

    outcome: Literal["ok", "wrong", "locked", "reused", "stopped"]
    device_id: str | None = None
    addresses: tuple[str, ...] = ()
    digest: str = ""


class PairingDesk:
    """The open code, the codes already used (until they would have expired) and the wrong tries."""

    def __init__(self) -> None:
        self.open: OpenCode | None = None
        self._consumed: dict[str, tuple[str, float]] = {}

    def start(self, now: float) -> tuple[str, float]:
        """A new code (replacing the open one) and when it expires (wall clock, seconds)."""
        code = new_code()
        self.open = OpenCode(digest=code_hash(code), expires=now + PAIRING_TTL_S)
        return code, self.open.expires

    def cancel(self) -> None:
        self.open = None

    def clear(self) -> None:
        self.open = None
        self._consumed.clear()

    def current(self, now: float) -> OpenCode | None:
        """The open code, if it hasn't expired."""
        if self.open is not None and now >= self.open.expires:
            self.open = None
        return self.open

    def opened(self, client: str, now: float, at: str) -> None:
        """A phone that isn't paired opened the pairing page while a code is open (the first one counts)."""
        code = self.current(now)
        if code is not None and code.opened_at is None:
            code.opened_at, code.opened_from = at, client

    def redeem(self, raw: str, client: str, now: float) -> Redeemed:
        """Check (and, when right, spend) a code — synchronously, so two requests can't both pay with it."""
        for digest, (_device, until) in list(self._consumed.items()):
            if now >= until:
                del self._consumed[digest]
        candidate = normalise(raw)
        digest = code_hash(candidate) if _CODE_RE.match(candidate) else ""
        used = self._consumed.get(digest) if digest else None
        if used is not None:
            return Redeemed("reused", device_id=used[0], digest=digest)
        code = self.current(now)
        if code is None:
            return Redeemed("wrong")
        if code.wrong.get(client, 0) >= PAIRING_TRIES_PER_CLIENT:
            return Redeemed("locked")
        if digest and hmac.compare_digest(digest, code.digest):
            return Redeemed("ok")
        code.wrong[client] = code.wrong.get(client, 0) + 1
        if code.wrong_tries >= PAIRING_TRIES_TOTAL:
            self.open = None
            return Redeemed("stopped", addresses=tuple(code.wrong))
        return Redeemed("wrong")  # the next try from this address is locked out once it had its five

    def spend(self, device_id: str) -> None:
        """The open code paired ``device_id``: it ends, and its hash remembers who used it."""
        if self.open is not None:
            self._consumed[self.open.digest] = (device_id, self.open.expires)
            self.open = None

    def forget_used(self, digest: str) -> None:
        """A used code came again from another device: it is spent for good."""
        self._consumed.pop(digest, None)

    def used_by(self, device_id: str) -> None:
        """Forget the used codes of a removed phone (a later use is then just a wrong code)."""
        for digest, (device, _until) in list(self._consumed.items()):
            if device == device_id:
                del self._consumed[digest]
