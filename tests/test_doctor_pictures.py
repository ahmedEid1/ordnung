"""``ordnung doctor``'s *Text in pictures* row (ADR 0024): whether Ordnung found Tesseract, and what to do when it
didn't. Tesseract is optional, so the row is never a failure: *Not installed (optional)* is info, with the install
line for this system; a Tesseract Ordnung can't use (too old, no German, didn't answer) warns; turned off in
Settings or by ``ORDNUNG_OCR=off`` is info too (the variable wins). The same row, as a state, is what
``GET /api/health`` reports for Settings' card (:func:`ordnung.doctor.picture_text_status`).

The other-systems CI job runs this file on macOS and Windows, where Tesseract is missing: there the real lookup
gives *Not installed (optional)* with that system's line."""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import pytest

from ordnung import doctor
from ordnung.config import OCR_SWITCH, Paths
from ordnung.db.store import Store
from ordnung.ingest import ocr
from ordnung.ingest.ocr import Tesseract
from ordnung.models import AppSettings, DoctorCheck, PictureTextState, PictureTextStatus

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
    """Info, not a warning: Ordnung works the same without it. The fix says what it would add, and how."""
    check = doctor.text_in_pictures_check(platform=platform, env=ON, find=_found(None))
    assert (check.id, check.label, check.status) == ("ocr", "Text in pictures", "info")
    assert check.detail == "Not installed (optional)"
    assert check.fix == (
        f"To find photos and scans Claude doesn't read by their words, install Tesseract: {INSTALL[platform]}"
    )
    assert doctor.tesseract_install(platform) == INSTALL[platform]
    assert doctor.tesseract_german(platform) == GERMAN[platform]


@pytest.mark.parametrize("value", ["off", "OFF", " 0 ", "false", "No"])
def test_text_in_pictures_says_when_turned_off(value: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Turned off, nothing is looked for or run, and the row is info: the person chose it."""
    monkeypatch.setattr(ocr, "find", lambda **_: _never())
    check = doctor.text_in_pictures_check(env={OCR_SWITCH: value}, find=_never)
    assert (check.id, check.status, check.fix) == ("ocr", "info", None)
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
    assert (row.status, row.detail) == ("info", "Not installed (optional)")
    assert doctor.DoctorReport(checks=[row]).ok


def test_the_row_on_this_system_is_never_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """With the real lookup on this computer: *Not installed (optional)* with this system's line where Tesseract is
    missing (the macOS and Windows runners), and never a failure. With ``ORDNUNG_REQUIRE_TESSERACT=1`` (CI's Linux
    3.12 leg, where Tesseract and its German data are installed) the row must name the real one."""
    monkeypatch.delenv(OCR_SWITCH)
    check = doctor.text_in_pictures_check()
    assert check.id == "ocr" and check.status in ("ok", "info", "warn"), check
    if check.detail == "Not installed (optional)":
        assert check.status == "info" and check.fix is not None
        assert check.fix.endswith(doctor.tesseract_install(sys.platform))
    if os.environ.get("ORDNUNG_REQUIRE_TESSERACT") == "1":
        assert check.status == "ok" and check.fix is None, check
        assert check.detail.startswith("Tesseract ") and "(German" in check.detail, check


# --------------------------------------------------------------------------------------------------
# Off in Settings (Settings → Data → Text in pictures)
# --------------------------------------------------------------------------------------------------

#: what the row says when the person turned it off in Settings
OFF_IN_SETTINGS = "Off (Settings → Data → Text in pictures)"


def test_text_in_pictures_off_in_settings_is_an_info_row(monkeypatch: pytest.MonkeyPatch) -> None:
    """Off in Settings: nothing is looked for or run, the row is info and names where it was turned off, with no
    fix (the person chose it)."""
    monkeypatch.setattr(ocr, "find", lambda **_: _never())
    check = doctor.text_in_pictures_check(read_picture_text=False, env=ON, find=_never)
    assert (check.id, check.label, check.status, check.fix) == ("ocr", "Text in pictures", "info", None)
    assert check.detail == OFF_IN_SETTINGS
    assert doctor.DoctorReport(checks=[check]).ok


def test_the_variable_wins_over_the_setting() -> None:
    """``ORDNUNG_OCR=off`` turns it off whatever Settings says, and the row names the variable; it never turns it on:
    with the variable set to anything else, the setting decides."""
    for read in (True, False):
        check = doctor.text_in_pictures_check(read_picture_text=read, env={OCR_SWITCH: "off"}, find=_never)
        assert (check.status, check.detail, check.fix) == ("info", "Turned off (ORDNUNG_OCR=off)", None)
    check = doctor.text_in_pictures_check(read_picture_text=False, env={OCR_SWITCH: "on"}, find=_never)
    assert check.detail == OFF_IN_SETTINGS
    check = doctor.text_in_pictures_check(read_picture_text=True, env={OCR_SWITCH: "on"}, find=_found(FOUND))
    assert check.status == "ok" and check.detail.startswith("Tesseract 5.3.4")


def _ocr_row(data_dir: Path, settings: AppSettings | None = None) -> DoctorCheck:
    (row,) = [check for check in doctor.local_checks(data_dir, settings) if check.id == "ocr"]
    return row


def test_the_cli_doctor_reads_the_setting_without_creating_the_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``ordnung doctor`` (no settings handed in) reads the switch from the data folder's database, read-only: off
    there, the row says so. No folder or database yet, or one that can't be read: on (the default), and nothing is
    created. The app hands in its own settings, which count over the database's."""
    monkeypatch.delenv(OCR_SWITCH)
    monkeypatch.setattr(ocr, "find", lambda **_: None)
    missing = tmp_path / "nowhere"
    assert _ocr_row(missing).detail == "Not installed (optional)"
    assert not missing.exists()

    data_dir = tmp_path / "data"
    with Store.open(Paths(data_dir)) as store:
        store.save_settings(store.get_settings().model_copy(update={"read_picture_text": False}))
    before = Paths(data_dir).db.read_bytes()
    assert _ocr_row(data_dir).detail == OFF_IN_SETTINGS
    assert Paths(data_dir).db.read_bytes() == before
    # the app's own settings count
    assert _ocr_row(data_dir, AppSettings(read_picture_text=True)).detail == "Not installed (optional)"
    assert _ocr_row(tmp_path / "other", AppSettings(read_picture_text=False)).detail == OFF_IN_SETTINGS
    # a database whose settings can't be read: on
    with sqlite3.connect(Paths(data_dir).db) as conn:
        conn.execute("UPDATE meta SET value = 'not json' WHERE key = 'settings'")
    assert _ocr_row(data_dir).detail == "Not installed (optional)"
    broken = tmp_path / "broken"
    broken.mkdir()
    Paths(broken).db.write_bytes(b"not a database")
    assert _ocr_row(broken).detail == "Not installed (optional)"


# --------------------------------------------------------------------------------------------------
# The same row as Settings' card reads it (Health.picture_text)
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("read", "env", "engine", "state"),
    [
        (True, ON, FOUND, "reading"),
        (False, ON, FOUND, "off"),
        (True, {OCR_SWITCH: "off"}, FOUND, "off_by_variable"),
        (False, {OCR_SWITCH: "off"}, FOUND, "off_by_variable"),
        (True, ON, None, "not_installed"),
        (True, ON, Tesseract("/usr/bin/tesseract", (4, 0, 0), ("deu", "eng")), "not_usable"),
        (True, ON, Tesseract("/usr/bin/tesseract", (5, 3, 4), ("eng",)), "not_usable"),
        (True, ON, Tesseract("/usr/bin/tesseract", None, ()), "not_usable"),
    ],
)
def test_picture_text_status_is_the_doctor_s_row_as_a_state(
    read: bool, env: dict[str, str], engine: Tesseract | None, state: PictureTextState
) -> None:
    """Settings' card shows the doctor's own words: each state carries the row's detail and fix."""
    find = _never if state in ("off", "off_by_variable") else _found(engine)
    status = doctor.picture_text_status(read, platform="linux", env=env, find=find)
    row = doctor.text_in_pictures_check(read_picture_text=read, platform="linux", env=env, find=find)
    assert status == PictureTextStatus(state=state, detail=row.detail, fix=row.fix)


def test_picture_text_status_uses_the_answer_already_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """``GET /api/health`` stays cheap: it asks the engine for the Tesseract it already found (the worker looks again
    once per start, the doctor on every run), never for a fresh look."""
    asked: list[dict[str, object]] = []

    def find(**kwargs: object) -> Tesseract | None:
        asked.append(kwargs)
        return FOUND

    monkeypatch.setattr(ocr, "find", find)
    status = doctor.picture_text_status(True, platform="darwin", env=ON)
    assert status.state == "reading"
    assert asked == [{"platform": "darwin", "env": ON}]
