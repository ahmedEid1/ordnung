"""The pairing code (alphabet, lenient reading, one use, expiry, tries per device and in all, a reused
code), phones' names, the check words, platform labels and the sliding limits."""

from __future__ import annotations

import pytest

from ordnung.phone import pairing
from ordnung.phone.pairing import (
    CODE_ALPHABET,
    CODE_LENGTH,
    PAIRING_TRIES_PER_CLIENT,
    PAIRING_TRIES_TOTAL,
    PAIRING_TTL_S,
    PairingDesk,
    SlidingLimit,
    check_words,
    clean_name,
    new_check_key,
    new_code,
    normalise,
    platform_label,
    shown,
    unique_name,
)

NOW = 1_800_000_000.0


def test_the_alphabet_has_no_letters_that_look_alike() -> None:
    assert len(CODE_ALPHABET) == 32 and len(set(CODE_ALPHABET)) == 32
    assert not set("ILOU") & set(CODE_ALPHABET)
    codes = {new_code() for _ in range(200)}
    assert len(codes) == 200
    assert all(len(code) == CODE_LENGTH and set(code) <= set(CODE_ALPHABET) for code in codes)
    assert CODE_LENGTH * 5 == 50  # bits


def test_a_typed_code_is_read_leniently() -> None:
    assert normalise("k7qm2-xd9pa") == "K7QM2XD9PA"
    assert normalise(" K7QM2‑XD9PA ") == "K7QM2XD9PA"
    assert normalise("O1IL0") == "01110"
    assert shown("K7QM2XD9PA") == "K7QM2-XD9PA"


def _desk() -> tuple[PairingDesk, str]:
    desk = PairingDesk()
    code, expires = desk.start(NOW)
    assert expires == NOW + PAIRING_TTL_S
    return desk, code


def test_a_code_works_once() -> None:
    desk, code = _desk()
    assert desk.redeem(code.lower(), "192.168.1.57", NOW).outcome == "ok"
    desk.spend("phn_first")
    assert desk.current(NOW) is None
    again = desk.redeem(code, "192.168.1.58", NOW + 1)
    assert (again.outcome, again.device_id) == ("reused", "phn_first")
    desk.forget_used(again.digest)
    assert desk.redeem(code, "192.168.1.58", NOW + 2).outcome == "wrong"


def test_a_used_code_is_forgotten_once_it_would_have_expired() -> None:
    desk, code = _desk()
    desk.redeem(code, "a", NOW)
    desk.spend("phn_first")
    assert desk.redeem(code, "b", NOW + PAIRING_TTL_S + 1).outcome == "wrong"


def test_a_code_expires() -> None:
    desk, code = _desk()
    assert desk.redeem(code, "a", NOW + PAIRING_TTL_S - 1).outcome == "ok"
    desk, code = _desk()
    assert desk.redeem(code, "a", NOW + PAIRING_TTL_S).outcome == "wrong"


def test_a_new_code_replaces_the_open_one() -> None:
    desk, first = _desk()
    second, _expires = desk.start(NOW + 5)
    assert desk.redeem(first, "a", NOW + 6).outcome == "wrong"
    assert desk.redeem(second, "a", NOW + 7).outcome == "ok"


def test_five_wrong_tries_lock_one_device_out_of_the_code() -> None:
    desk, code = _desk()
    outcomes = [
        desk.redeem("WRONGCODE1", "192.168.1.66", NOW).outcome for _ in range(PAIRING_TRIES_PER_CLIENT)
    ]
    assert outcomes == ["wrong"] * PAIRING_TRIES_PER_CLIENT
    assert desk.redeem(code, "192.168.1.66", NOW).outcome == "locked"
    assert desk.redeem(code, "192.168.1.57", NOW).outcome == "ok"  # another device isn't


def test_a_hundred_wrong_tries_on_the_network_cancel_the_code() -> None:
    desk, _code = _desk()
    clients = [f"192.168.1.{n}" for n in range(PAIRING_TRIES_TOTAL // PAIRING_TRIES_PER_CLIENT)]
    outcomes = [desk.redeem("WRONGCODE1", client, NOW).outcome for client in clients for _ in range(5)]
    assert outcomes[:-1] == ["wrong"] * (PAIRING_TRIES_TOTAL - 1)
    stopped = desk.redeem("x", "192.168.1.200", NOW)  # no code: nothing is counted any more
    assert stopped.outcome == "wrong" and desk.current(NOW) is None
    desk, _code = _desk()
    last = None
    for client in clients:
        for _ in range(5):
            last = desk.redeem("WRONGCODE1", client, NOW)
    assert last is not None and last.outcome == "stopped" and last.addresses == tuple(clients)


def test_an_open_code_s_progress_counts_wrong_tries_and_who_opened_it() -> None:
    desk, _code = _desk()
    desk.opened("192.168.1.57", NOW, "2026-10-07T08:00:00Z")
    desk.opened("192.168.1.99", NOW, "2026-10-07T08:00:05Z")
    desk.redeem("WRONGCODE1", "192.168.1.66", NOW)
    current = desk.current(NOW)
    assert current is not None
    assert (current.opened_at, current.opened_from) == ("2026-10-07T08:00:00Z", "192.168.1.57")
    assert (current.wrong_tries, list(current.wrong)) == (1, ["192.168.1.66"])


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Sam's iPhone", "Sam's iPhone"),
        ("Sam‮'s iPhone", "Sam's iPhone"),  # a right-to-left override
        ("Sam's​ iPhone", "Sam's iPhone"),  # zero-width space
        ("Sam's⁦ iPhone⁩", "Sam's iPhone"),  # isolates
        ("Sam's\x07\x1b iPhone\n", "Sam's iPhone"),
        ("  Sam's    iPhone  ", "Sam's iPhone"),
        ("​‮", "Phone"),
        ("x" * 60, "x" * 40),
    ],
)
def test_a_phone_s_name_is_cleaned(raw: str, expected: str) -> None:
    assert clean_name(raw) == expected


def test_a_taken_name_is_numbered() -> None:
    assert unique_name("iPhone", set()) == "iPhone"
    assert unique_name("iPhone", {"iphone"}) == "iPhone (2)"
    assert unique_name("iPhone", {"iPhone", "iPhone (2)"}) == "iPhone (3)"
    long = "x" * 40
    assert unique_name(long, {long}) == "x" * 36 + " (2)"


def test_check_words_are_two_words_derived_with_this_computer_s_key() -> None:
    key = new_check_key()
    words = check_words(key, "phn_k3m7q2x8v4ta")
    adjective, noun = words.split(" ")
    assert adjective in pairing.CHECK_ADJECTIVES and noun in pairing.CHECK_NOUNS
    assert check_words(key, "phn_k3m7q2x8v4ta") == words
    others = {check_words(key, f"phn_{n:012d}") for n in range(50)}
    assert len(others) > 30
    assert len({check_words(new_check_key(), "phn_k3m7q2x8v4ta") for _ in range(20)}) > 5


UA = {
    "iPhone · Safari": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1",
    "iPhone · Chrome": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/124.0.6367.88 Mobile/15E148 Safari/604.1",
    "iPhone · Firefox": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) FxiOS/125.0 Mobile/15E148 Safari/605.1.15",
    "iPhone · Edge": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 EdgiOS/124.2478.71 Mobile/15E148 Safari/605.1.15",
    "iPad · Safari": "Mozilla/5.0 (iPad; CPU OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
    "Android · Chrome": "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.6422.53 Mobile Safari/537.36",
    "Android · Samsung Internet": "Mozilla/5.0 (Linux; Android 14; SM-S921B) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/25.0 Chrome/121.0.0.0 Mobile Safari/537.36",
    "Android · Firefox": "Mozilla/5.0 (Android 14; Mobile; rv:126.0) Gecko/126.0 Firefox/126.0",
    "Android · Opera": "Mozilla/5.0 (Linux; Android 13; SM-A536B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36 OPR/82.0.4227.79000",
    "iPhone · DuckDuckGo": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 DuckDuckGo/7 Safari/605.1.15",
}


@pytest.mark.parametrize(("label", "agent"), sorted(UA.items()))
def test_a_browser_is_summed_up_never_kept(label: str, agent: str) -> None:
    assert platform_label(agent) == label


def test_an_unknown_browser_is_a_phone() -> None:
    assert platform_label(None) == "Phone"
    assert platform_label("curl/8.5") == "Phone"


def test_a_sliding_limit_counts_per_key_and_recovers() -> None:
    limit = SlidingLimit(2, 60.0)
    assert [limit.take("a", 0), limit.take("a", 1)] == [0, 0]
    assert limit.take("a", 2) == 59
    assert limit.take("b", 2) == 0
    assert limit.take("a", 61) == 0


def test_a_sliding_limit_takes_several_at_once_or_none() -> None:
    """An upload's letters count together: all of them fit, or none counts (scope review)."""
    limit = SlidingLimit(3, 60.0)
    assert limit.take("a", 0) == 0
    assert limit.take("a", 10, count=3) == 51  # 1 + 3 > 3: until the first one leaves the window
    assert limit.take("a", 10, count=2) == 0  # nothing of the refused three was counted
    assert limit.take("a", 11) == 50
    limit.give_back("a")  # the last one turned out not to happen
    assert limit.take("a", 11) == 0
    assert limit.take("a", 70.5, count=2) == 0  # two went out of the window
