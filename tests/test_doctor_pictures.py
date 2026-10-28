"""``ordnung doctor``'s *Text in pictures* row (ADR 0024): whether Ordnung found Tesseract, and what to do when it
didn't. Tesseract is optional, so the row is never a failure: *Not installed (optional)* is ok, with the install
line for this system; a Tesseract Ordnung can't use (too old, no German, didn't answer) warns.

The other-systems CI job runs this file on macOS and Windows, where Tesseract is missing: there the real lookup
gives *Not installed (optional)* with that system's line."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from ordnung import doctor
from ordnung.config import OCR_SWITCH, Paths
from ordnung.db.store import Store
from ordnung.ingest import ocr
from ordnung.ingest.ocr import Tesseract

SYSTEMS = ("linux", "darwin", "win32")
#: the install line per system, exactly as the doctor gives it (and the README, which P5 checks against it)
INSTALL = {
    "linux": "`sudo apt install tesseract-ocr tesseract-ocr-deu` (Fedora: `sudo dnf install tesseract "
    "tesseract-langpack-deu`), then restart Ordnung.",
    "darwin": "`brew install tesseract tesseract-lang`, then restart Ordnung.",
    "win32": "the installer from https://github.com/UB-Mannheim/tesseract/wiki, with German ticked under "
    "“Additional language data”, then restart Ordnung.",
}
GERMAN = {
    "linux": "Install the German language data: `sudo apt install tesseract-ocr-deu` (Fedora: `sudo dnf install "
    "tesseract-langpack-deu`), then restart Ordnung.",
    "darwin": "Install the German language data: `brew install tesseract-lang`, then restart Ordnung.",
    "win32": "Run the Tesseract installer again and tick German under “Additional language data”, then restart "
    "Ordnung.",
}
FOUND = Tesseract("/usr/bin/tesseract", (5, 3, 4), ("deu", "eng"))
#: the environment of a person who didn't turn it off
ON: dict[str, str] = {}


def _found(engine: Tesseract | None) -> doctor.FindTesseract:
    return lambda: engine


def _never() -> Tesseract | None:
    raise AssertionError("the doctor looked for Tesseract while it was turned off")


def test_text_in_pictures_names_the_version_and_languages() -> None:
    check = doctor.text_in_pictures_check(env=ON, find=_found(FOUND))
    assert (check.id, check.label, check.status, check.fix) == ("ocr", "Text in pictures", "ok", None)
    assert check.detail == (
        "Tesseract 5.3.4 (German and English): photos and scans Claude doesn't read are found by their words, "
        "not checked"
    )
    german_only = Tesseract("/usr/bin/tesseract", (4, 1, 1), ("deu",))
    german = doctor.text_in_pictures_check(env=ON, find=_found(german_only))
    assert german.status == "ok" and german.detail.startswith("Tesseract 4.1.1 (German): photos and scans")


@pytest.mark.parametrize("platform", SYSTEMS)
def test_text_in_pictures_warns_without_german(platform: str) -> None:
    """English alone misreads ä, ö, ü and ß; neither language reads nothing. Both say how to add German."""
    english = Tesseract("/usr/bin/tesseract", (5, 3, 4), ("eng",))
    check = doctor.text_in_pictures_check(platform=platform, env=ON, find=_found(english))
    assert (check.id, check.status) == ("ocr", "warn")
    assert check.detail == (
        "Tesseract 5.3.4 has no German language data: words with ä, ö, ü or ß are often misread"
    )
    assert check.fix == GERMAN[platform]
    neither = Tesseract("/usr/bin/tesseract", (5, 3, 4), ())
    check = doctor.text_in_pictures_check(platform=platform, env=ON, find=_found(neither))
    assert check.status == "warn"
    assert check.detail == (
        "Tesseract 5.3.4 has neither German nor English language data, so Ordnung reads no pictures"
    )
    assert check.fix == GERMAN[platform]


@pytest.mark.parametrize("platform", SYSTEMS)
def test_text_in_pictures_warns_when_older_than_4_1(platform: str) -> None:
    old = Tesseract("/usr/bin/tesseract", (4, 0, 0), ("deu", "eng"))
    check = doctor.text_in_pictures_check(platform=platform, env=ON, find=_found(old))
    assert check.status == "warn"
    assert check.detail == "Tesseract 4.0.0 is too old: Ordnung needs 4.1 or newer, so it reads no pictures"
    assert check.fix == f"Install a newer one: {INSTALL[platform]}"


@pytest.mark.parametrize("platform", SYSTEMS)
def test_text_in_pictures_warns_when_tesseract_doesnt_answer(platform: str) -> None:
    """A broken install says why, and never claims "not installed"."""
    silent = Tesseract(r"C:\Program Files\Tesseract-OCR\tesseract.exe", None, ())
    check = doctor.text_in_pictures_check(platform=platform, env=ON, find=_found(silent))
    assert check.status == "warn"
    assert check.detail == (
        r"Tesseract at C:\Program Files\Tesseract-OCR\tesseract.exe didn't answer, so Ordnung reads no pictures"
    )
    assert check.fix == f"Install it again: {INSTALL[platform]}"


@pytest.mark.parametrize("platform", SYSTEMS)
def test_text_in_pictures_is_optional_when_not_installed(platform: str) -> None:
    """Ok, not a warning: Ordnung works the same without it. The fix says what it would add, and how."""
    check = doctor.text_in_pictures_check(platform=platform, env=ON, find=_found(None))
    assert (check.id, check.label, check.status) == ("ocr", "Text in pictures", "ok")
    assert check.detail == "Not installed (optional)"
    assert check.fix == (
        f"To find photos and scans Claude doesn't read by their words, install Tesseract: {INSTALL[platform]}"
    )
    assert doctor.tesseract_install(platform) == INSTALL[platform]
    assert doctor.tesseract_german(platform) == GERMAN[platform]


@pytest.mark.parametrize("value", ["off", "OFF", " 0 ", "false", "No"])
def test_text_in_pictures_says_when_turned_off(value: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Turned off, nothing is looked for or run, and the row is ok: the person chose it."""
    monkeypatch.setattr(ocr, "find", lambda **_: _never())
    check = doctor.text_in_pictures_check(env={OCR_SWITCH: value}, find=_never)
    assert (check.id, check.status, check.fix) == ("ocr", "ok", None)
    assert check.detail == "Turned off (ORDNUNG_OCR=off)"
    # the process environment by default (the tests' own switch is off)
    monkeypatch.setenv(OCR_SWITCH, value)
    assert doctor.text_in_pictures_check().detail == "Turned off (ORDNUNG_OCR=off)"


def test_the_doctor_looks_for_tesseract_again_on_every_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """Installed while Ordnung runs? The next ``ordnung doctor`` (or Settings' *Run check*) sees it: the engine
    is asked to look again, on this system, in this environment."""
    asked: list[dict[str, object]] = []

    def find(**kwargs: object) -> Tesseract | None:
        asked.append(kwargs)
        return FOUND

    monkeypatch.setattr(ocr, "find", find)
    env = {"PATH": "/opt/bin"}
    check = doctor.text_in_pictures_check(platform="darwin", env=env)
    assert check.status == "ok" and check.detail.startswith("Tesseract 5.3.4")
    assert asked == [{"refresh": True, "platform": "darwin", "env": env}]


def test_the_row_comes_right_after_the_web_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Right after *Web app*: the rows about this installation come first, the data folder's after them."""
    data_dir = tmp_path / "data"
    with Store.open(Paths(data_dir)) as store:
        store.set_meta("probe", "1")
    monkeypatch.delenv(OCR_SWITCH)
    monkeypatch.setattr(ocr, "find", lambda **_: None)
    checks = doctor.local_checks(data_dir)
    ids = [check.id for check in checks]
    assert ids.index("ocr") == ids.index("web_ui") + 1 == ids.index("data_dir") - 1
    (row,) = [check for check in checks if check.id == "ocr"]
    assert (row.status, row.detail) == ("ok", "Not installed (optional)")
    assert doctor.DoctorReport(checks=[row]).ok


def test_the_row_on_this_system_is_never_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """With the real lookup on this computer: *Not installed (optional)* with this system's line where Tesseract is
    missing (the macOS and Windows runners), and never a failure. With ``ORDNUNG_REQUIRE_TESSERACT=1`` (CI's Linux
    3.12 leg, where Tesseract and its German data are installed) the row must name the real one."""
    monkeypatch.delenv(OCR_SWITCH)
    check = doctor.text_in_pictures_check()
    assert check.id == "ocr" and check.status in ("ok", "warn"), check
    if check.detail == "Not installed (optional)":
        assert check.status == "ok" and check.fix is not None
        assert check.fix.endswith(doctor.tesseract_install(sys.platform))
    if os.environ.get("ORDNUNG_REQUIRE_TESSERACT") == "1":
        assert check.status == "ok" and check.fix is None, check
        assert check.detail.startswith("Tesseract ") and "(German" in check.detail, check
