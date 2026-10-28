"""Text in pictures (ADR 0024), the parts every package builds on: the off switch ``ORDNUNG_OCR``, the names and
limits of the engine (:mod:`ordnung.ingest.ocr`), the fake ``tesseract`` the tests run, and the switches that keep
a Tesseract installed on this computer out of every test and end-to-end run that doesn't ask for it."""

from __future__ import annotations

import dataclasses
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from ordnung import config
from ordnung.ingest import ocr

ROOT = Path(__file__).resolve().parents[1]
FAKE = Path(__file__).resolve().parent / "fake_tesseract.py"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


# --------------------------------------------------------------------------------------------------
# The off switch
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["off", "OFF", " Off ", "0", "false", "False", "no", "NO", "\toff\n"])
def test_the_off_switch_reads_off_0_false_and_no_in_any_case(value: str) -> None:
    assert config.OCR_SWITCH == "ORDNUNG_OCR"
    assert config.ocr_turned_off({"ORDNUNG_OCR": value})
    assert ocr.turned_off({"ORDNUNG_OCR": value})


@pytest.mark.parametrize("value", ["", " ", "on", "1", "true", "yes", "offf", "of", "nope", "0ff"])
def test_any_other_value_leaves_it_on(value: str) -> None:
    assert not config.ocr_turned_off({"ORDNUNG_OCR": value})
    assert not config.ocr_turned_off({})


def test_the_switch_is_read_again_on_every_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ORDNUNG_OCR")
    assert not config.ocr_turned_off() and not ocr.turned_off()
    monkeypatch.setenv("ORDNUNG_OCR", "off")
    assert config.ocr_turned_off() and ocr.turned_off()
    monkeypatch.setenv("ORDNUNG_OCR", "on")
    assert not config.ocr_turned_off()


def test_every_test_runs_with_text_in_pictures_turned_off() -> None:
    """``tests/conftest.py`` turns it off for every test, so a Tesseract installed here never runs unless a test
    turns it on (``monkeypatch.delenv("ORDNUNG_OCR")``)."""
    assert os.environ["ORDNUNG_OCR"] == "off"
    assert config.ocr_turned_off() and ocr.turned_off()


# --------------------------------------------------------------------------------------------------
# The engine's names and limits
# --------------------------------------------------------------------------------------------------


def test_the_engine_s_limits_are_the_decided_ones() -> None:
    assert ocr.OCR_SWITCH == config.OCR_SWITCH
    assert ocr.MIN_VERSION == (4, 1)
    assert ocr.LANGUAGES == ("deu", "eng")
    assert (ocr.PICTURE_LONG_SIDE, ocr.MAX_DPI) == (2400, 300)
    assert (ocr.LOOK_TIMEOUT_S, ocr.PAGE_TIMEOUT_S, ocr.POLL_S) == (10.0, 120.0, 0.25)
    assert ocr.NICENESS == 10


@pytest.mark.parametrize(
    ("version", "languages", "usable"),
    [
        ((5, 3, 4), ("deu", "eng"), True),
        ((5, 3, 4), ("eng",), True),
        ((4, 1, 0), ("deu",), True),
        ((4, 0, 0), ("deu", "eng"), False),
        ((3, 5, 2), ("deu",), False),
        ((5, 3, 4), (), False),
        (None, ("deu", "eng"), False),
    ],
)
def test_a_tesseract_is_usable_from_4_1_with_german_or_english(
    version: tuple[int, int, int] | None, languages: tuple[str, ...], usable: bool
) -> None:
    assert ocr.Tesseract("/usr/bin/tesseract", version, languages).usable is usable


def test_a_tesseract_runs_by_its_path_or_through_a_launcher() -> None:
    found = ocr.Tesseract("/usr/bin/tesseract", (5, 3, 4), ("deu", "eng"))
    assert found.launcher == () and found.argv == ("/usr/bin/tesseract",)
    fake = ocr.Tesseract(str(FAKE), (5, 3, 4), ("deu",), launcher=(sys.executable, str(FAKE)))
    assert fake.argv == (sys.executable, str(FAKE))
    with pytest.raises(dataclasses.FrozenInstanceError):
        found.path = "/tmp/tesseract"  # type: ignore[misc]


def test_stopping_is_a_recognition_error_too() -> None:
    assert issubclass(ocr.Stopped, ocr.RecognitionError)
    assert issubclass(ocr.RecognitionError, Exception)


def test_find_runs_nothing_while_turned_off() -> None:
    assert ocr.find() is None
    assert ocr.find(refresh=True) is None


# --------------------------------------------------------------------------------------------------
# The fake tesseract (tests/fake_tesseract.py)
# --------------------------------------------------------------------------------------------------


def _fake(
    mode: str, *args: str, stdin: bytes = b"", report: Path | None = None, timeout: float = 30
) -> subprocess.CompletedProcess[bytes]:
    env = {**os.environ, "FAKE_TESSERACT_MODE": mode}
    if report is not None:
        env["FAKE_TESSERACT_REPORT"] = str(report)
    return subprocess.run(
        [sys.executable, str(FAKE), *args], input=stdin, capture_output=True, env=env, timeout=timeout
    )


@pytest.mark.parametrize(
    ("mode", "version", "languages"),
    [
        ("ok", "5.3.4", ["deu", "eng", "osd"]),
        ("echo", "5.3.4", ["deu", "eng", "osd"]),
        ("old", "4.0.0", ["deu", "eng", "osd"]),
        ("no-deu", "5.3.4", ["eng", "osd"]),
        ("no-langs", "5.3.4", ["osd"]),
    ],
)
def test_the_fake_answers_its_version_and_languages_like_tesseract(
    mode: str, version: str, languages: list[str]
) -> None:
    answer = _fake(mode, "--version")
    assert answer.returncode == 0
    assert answer.stdout.decode().splitlines()[0] == f"tesseract {version}"
    listed = _fake(mode, "--list-langs")
    assert listed.returncode == 0
    head, *names = listed.stdout.decode().splitlines()
    assert re.fullmatch(r'List of available languages in "[^"]+" \(\d+\):', head), head
    assert names == languages and head.endswith(f"({len(languages)}):")


def test_the_fake_reads_a_picture_from_stdin_and_prints_its_words_to_stdout() -> None:
    png = PNG_SIGNATURE + b"picture"
    assert _fake("ok", "stdin", "stdout", "-l", "deu+eng", stdin=png).stdout == b""
    echoed = _fake("echo", "stdin", "stdout", "-l", "deu+eng", stdin=png)
    assert echoed.returncode == 0 and echoed.stdout.decode("utf-8") == "Ihr Kellerabteil 7 · Gebäude Süd\n"
    failed = _fake("fail", "stdin", "stdout", "-l", "deu", stdin=png)
    assert failed.returncode == 1 and failed.stdout  # it says something a caller must never pass on


def test_the_fake_reports_how_it_was_run(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    answer = _fake("report", "stdin", "stdout", "-l", "deu+eng", stdin=PNG_SIGNATURE + b"x", report=report)
    assert answer.returncode == 0 and answer.stdout.decode("utf-8").startswith("Ihr Kellerabteil")
    seen = json.loads(report.read_text("utf-8"))
    assert seen["argv"] == ["stdin", "stdout", "-l", "deu+eng"]
    assert seen["png"] is True and seen["pid"] > 0
    assert set(seen) == {"argv", "png", "pid", "priority", "OMP_THREAD_LIMIT", "TMPDIR", "TMP", "TEMP"}
    assert isinstance(seen["priority"], int)
    _fake("report", "stdin", "stdout", "-l", "deu", stdin=b"not a picture", report=report)
    assert json.loads(report.read_text("utf-8"))["png"] is False


@pytest.mark.parametrize(("mode", "args"), [("silent", ("--version",)), ("hang", ("stdin", "stdout"))])
def test_the_fake_can_hang_until_it_is_killed(mode: str, args: tuple[str, ...]) -> None:
    with pytest.raises(subprocess.TimeoutExpired):
        _fake(mode, *args, stdin=PNG_SIGNATURE, timeout=1.0)


def test_the_fake_knows_only_its_modes() -> None:
    answer = _fake("sing", "--version")
    assert answer.returncode == 2 and b"FAKE_TESSERACT_MODE" in answer.stderr


# --------------------------------------------------------------------------------------------------
# End to end: the servers' switches
# --------------------------------------------------------------------------------------------------


def _servers(config_ts: str) -> list[str]:
    """The ``webServer`` entries of ``web/playwright.config.ts``, in order: the demo, real app A, real app B."""
    block = config_ts.split("webServer: [", 1)[1].split("\n  ],", 1)[0]
    return block.split("\n    {")[1:]


def test_the_e2e_servers_read_no_picture_unless_the_run_asks() -> None:
    """``web/playwright.config.ts``: the demo server and the second real app run with ``ORDNUNG_OCR`` off; the
    first real app turns it on only with ``ORDNUNG_E2E_OCR=on`` (``E2E_OCR`` in ``web/e2e/env.ts``), as CI's
    end-to-end job runs it with Tesseract installed."""
    env_ts = (ROOT / "web" / "e2e" / "env.ts").read_text(encoding="utf-8")
    assert 'export const E2E_OCR = process.env.ORDNUNG_E2E_OCR === "on";' in env_ts
    config_ts = (ROOT / "web" / "playwright.config.ts").read_text(encoding="utf-8")
    demo, real, real_b = _servers(config_ts)
    assert " demo --serve " in demo and 'ORDNUNG_OCR: "off"' in demo
    assert "${REAL_PORT}" in real and 'ORDNUNG_OCR: E2E_OCR ? "on" : "off"' in real
    assert "${REAL_B_PORT}" in real_b and 'ORDNUNG_OCR: "off"' in real_b
    assert config_ts.count("ORDNUNG_OCR: ") == 3  # no other server, no other value
