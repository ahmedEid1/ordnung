"""Text in pictures (ADR 0024), the engine (:mod:`ordnung.ingest.ocr`): where Ordnung looks for Tesseract and which
one it takes, the picture of a page Tesseract gets, and how Tesseract runs: the PNG on stdin, one thread, at low
priority, in a private temporary folder, with a time limit and a stop that kill it, and never a word of what it
printed in an error or a log.

Tesseract itself is played by ``tests/fake_tesseract.py`` (run through ``Tesseract.launcher``, so this runs on
Windows and macOS too). Only :func:`test_real_tesseract_reads_a_scan_and_a_photo` needs the real program, with
German: it skips without it, except where ``ORDNUNG_REQUIRE_TESSERACT=1`` (CI's Linux legs that install it), where a
missing Tesseract fails it.
"""

from __future__ import annotations

import io
import json
import logging
import os
import random
import stat
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from PIL import Image

from helpers_docs import A4, Line, make_pdf, photo, scanned_pdf, scanned_photo
from ordnung.ingest import ocr

FAKE = Path(__file__).resolve().parent / "fake_tesseract.py"
#: What runs the fake. On Windows a virtual environment's ``python.exe`` is a launcher that starts the real one as
#: a child, so killing it would leave that child behind for a moment; the base interpreter is the program itself.
PYTHON = getattr(sys, "_base_executable", sys.executable) if sys.platform == "win32" else sys.executable
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
ECHO_TEXT = "Ihr Kellerabteil 7 · Gebäude Süd\n"  # what the fake reads in any picture (echo, report)
A6 = (297.64, 419.53)
#: ``BELOW_NORMAL_PRIORITY_CLASS``, as ``GetPriorityClass`` answers it on Windows.
BELOW_NORMAL = 0x4000


@pytest.fixture
def turned_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """Text in pictures on for this test (``tests/conftest.py`` turns it off for every test)."""
    monkeypatch.delenv("ORDNUNG_OCR")


@pytest.fixture
def report(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Where the fake writes how it was run (``FAKE_TESSERACT_REPORT``)."""
    target = tmp_path / "report.json"
    monkeypatch.setenv("FAKE_TESSERACT_REPORT", str(target))
    return target


@pytest.fixture
def mode(monkeypatch: pytest.MonkeyPatch) -> Callable[[str], None]:
    """Set what the fake does (``FAKE_TESSERACT_MODE``)."""
    return lambda value: monkeypatch.setenv("FAKE_TESSERACT_MODE", value)


def _fake_engine(languages: tuple[str, ...] = ("deu", "eng")) -> ocr.Tesseract:
    return ocr.Tesseract(str(FAKE), (5, 3, 4), languages, launcher=(PYTHON, str(FAKE)))


def _png(size: tuple[int, int] = (60, 30)) -> bytes:
    buffer = io.BytesIO()
    Image.new("L", size, 255).save(buffer, "PNG")
    return buffer.getvalue()


def _picture(png: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(png))
    assert image.format == "PNG"
    return image


def _wait_for(path: Path, timeout_s: float = 20.0) -> dict[str, object]:
    """The fake's report, once it wrote it (it writes it after taking its whole stdin)."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            found: dict[str, object] = json.loads(path.read_text("utf-8"))
            return found
        except (OSError, ValueError):
            time.sleep(0.02)
    raise AssertionError("the fake never reported")


def _alive(pid: int) -> bool:
    """Whether process ``pid`` still runs (or, on Linux and macOS, waits to be reaped)."""
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(
            0x00100000 | 0x1000, False, pid
        )  # SYNCHRONIZE | QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            return bool(kernel32.WaitForSingleObject(handle, 0) != 0)  # WAIT_OBJECT_0: it has ended
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _ends(pid: int, within_s: float = 5.0) -> bool:
    """Whether process ``pid`` is gone, at once or within ``within_s`` (Windows ends a killed process a moment
    after it is told to)."""
    deadline = time.monotonic() + within_s
    while _alive(pid):
        if time.monotonic() > deadline:
            return False
        time.sleep(0.05)
    return True


def _is_program_in(places: set[str]) -> Callable[[str], bool]:
    return lambda path: path in places


# --------------------------------------------------------------------------------------------------
# The off switch
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["off", "OFF", " Off ", "0", "false", "FALSE", "no", "No"])
def test_the_off_switch_reads_off_0_false_and_no(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    assert ocr.turned_off({"ORDNUNG_OCR": value})
    assert not ocr.turned_off({"ORDNUNG_OCR": "on"}) and not ocr.turned_off({})
    monkeypatch.setenv("ORDNUNG_OCR", value)
    assert ocr.turned_off()
    monkeypatch.delenv("ORDNUNG_OCR")
    assert not ocr.turned_off()


def test_recognise_never_starts_tesseract_while_turned_off(report: Path) -> None:
    """``ORDNUNG_OCR=off`` (here from ``tests/conftest.py``): Tesseract is never started, whoever asks."""
    with pytest.raises(ocr.RecognitionError, match="turned off"):
        ocr.recognise(_fake_engine(), _png())
    assert not report.exists()


# --------------------------------------------------------------------------------------------------
# Where Ordnung looks: the PATH first, then each system's install folders
# --------------------------------------------------------------------------------------------------

_WINDOWS_ENV = {
    "PATH": r"D:\Werkzeuge;C:\Windows\system32",
    "ProgramFiles": r"C:\Program Files",
    "ProgramFiles(x86)": r"C:\Program Files (x86)",
    "LOCALAPPDATA": r"C:\Users\Ada\AppData\Local",
}


@pytest.mark.parametrize(
    ("platform", "env", "expected"),
    [
        (
            "linux",
            {"PATH": "/opt/werkzeuge/bin:/usr/bin"},
            ["/opt/werkzeuge/bin/tesseract", "/usr/bin/tesseract", "/usr/local/bin/tesseract"],
        ),
        (
            "darwin",
            {"PATH": "/usr/bin:/bin"},  # what a launchd start has: no Homebrew on it
            [
                "/usr/bin/tesseract",
                "/opt/homebrew/bin/tesseract",
                "/usr/local/bin/tesseract",
                "/opt/local/bin/tesseract",
            ],
        ),
        (
            "win32",
            _WINDOWS_ENV,  # the UB Mannheim installer doesn't put itself on the PATH
            [
                r"D:\Werkzeuge\tesseract.exe",
                r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
                r"C:\Users\Ada\AppData\Local\Programs\Tesseract-OCR\tesseract.exe",
            ],
        ),
        (
            "win32",
            {key.upper(): value for key, value in _WINDOWS_ENV.items()},  # Windows' names ignore case
            [
                r"D:\Werkzeuge\tesseract.exe",
                r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
                r"C:\Users\Ada\AppData\Local\Programs\Tesseract-OCR\tesseract.exe",
            ],
        ),
    ],
)
def test_candidates_put_the_path_first_then_each_systems_places(
    platform: str, env: dict[str, str], expected: list[str]
) -> None:
    every = {
        *expected,
        "/opt/elsewhere/tesseract",
        r"C:\Windows\system32\tesseract.cmd",  # Windows runs only tesseract.exe, never a script
    }
    assert ocr.candidates(platform, env, is_file=_is_program_in(every)) == expected
    # only the programs that are there
    assert ocr.candidates(platform, env, is_file=_is_program_in({expected[-1]})) == [expected[-1]]
    assert ocr.candidates(platform, env, is_file=_is_program_in(set())) == []


def test_candidates_read_the_process_environment_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", ":".join(["/opt/eins", "/opt/zwei"]))  # Linux's separator, on any system
    found = ocr.candidates("linux", is_file=_is_program_in({"/opt/zwei/tesseract", "/opt/eins/tesseract"}))
    assert found == ["/opt/eins/tesseract", "/opt/zwei/tesseract"]


@pytest.mark.parametrize(
    ("platform", "path", "kept"),
    [
        ("linux", ":.:bin:./bin:../bin:~/bin:/opt/a", ["/opt/a/tesseract"]),
        ("darwin", "::.:/opt/a:", ["/opt/a/tesseract"]),
        (
            "win32",
            r";.;bin;.\bin;C:rel;\ohne-laufwerk;" + '"C:\\Mit Leerzeichen"' + r";D:\a;\\server\share\tools",
            [
                r"C:\Mit Leerzeichen\tesseract.exe",
                r"D:\a\tesseract.exe",
                r"\\server\share\tools\tesseract.exe",
            ],
        ),
    ],
)
def test_the_path_lookup_skips_the_current_folder_and_relative_entries(
    platform: str, path: str, kept: list[str]
) -> None:
    """An empty, ``.`` or relative entry would run a ``tesseract`` from Ordnung's current folder (Windows'
    ``shutil.which`` even looks there first), so only absolute entries are looked in."""
    every = ocr.candidates(platform, {"PATH": path}, is_file=lambda candidate: True)
    fixed = ocr.candidates(platform, {"PATH": ""}, is_file=lambda candidate: True)
    assert every == kept + fixed


def test_a_tesseract_in_the_current_folder_is_never_a_candidate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """On this system's real files: a program called ``tesseract`` in the current folder is never looked at."""
    here = tmp_path / "here"
    here.mkdir()
    planted = here / ("tesseract.exe" if sys.platform == "win32" else "tesseract")
    planted.write_bytes(b"#!/bin/sh\nexit 0\n")
    planted.chmod(0o755)
    monkeypatch.chdir(here)
    found = ocr.candidates(sys.platform, {"PATH": os.pathsep.join(["", ".", "here"])})
    assert all(Path(candidate).resolve() != planted.resolve() for candidate in found)


@pytest.mark.skipif(sys.platform == "win32", reason="the execute bit is a Linux and macOS thing")
def test_a_file_that_isnt_a_program_is_not_a_candidate(tmp_path: Path) -> None:
    folder = tmp_path / "bin"
    folder.mkdir()
    (folder / "tesseract").write_text("not a program", encoding="utf-8")
    (folder / "tesseract").chmod(0o644)
    assert str(folder / "tesseract") not in ocr.candidates(sys.platform, {"PATH": str(folder)})
    (folder / "tesseract").chmod(0o755)
    assert ocr.candidates(sys.platform, {"PATH": str(folder)})[0] == str(folder / "tesseract")


def test_a_tesseract_named_twice_is_looked_at_once(tmp_path: Path) -> None:
    folder = tmp_path / "bin"
    folder.mkdir()
    program = folder / ("tesseract.exe" if sys.platform == "win32" else "tesseract")
    program.write_bytes(b"")
    program.chmod(0o755)
    twice = os.pathsep.join([str(folder), str(folder) + os.sep, str(folder) + os.sep + "."])
    found = ocr.candidates(sys.platform, {"PATH": twice})
    assert [Path(candidate).resolve() for candidate in found].count(program.resolve()) == 1
    assert found[0] == str(program)
    if sys.platform != "win32":
        alias = tmp_path / "alias"
        alias.symlink_to(folder, target_is_directory=True)
        both = ocr.candidates(sys.platform, {"PATH": os.pathsep.join([str(alias), str(folder)])})
        assert [Path(candidate).resolve() for candidate in both].count(program.resolve()) == 1


# --------------------------------------------------------------------------------------------------
# Looking at a Tesseract: its version and languages
# --------------------------------------------------------------------------------------------------

_LIST = 'List of available languages in "/usr/share/tesseract-ocr/5/tessdata/" (3):\ndeu\neng\nosd\n'


def _answering(tmp_path: Path, version: str, stream: str = "stdout", langs: str = _LIST) -> tuple[str, ...]:
    """A launcher for a program that answers ``--version`` with ``version`` on ``stream`` and ``--list-langs``
    with ``langs``, as an installed Tesseract would."""
    script = tmp_path / "answers.py"
    script.write_text(
        "import sys\n"
        f"VERSION, STREAM, LANGS = {version!r}, {stream!r}, {langs!r}\n"
        "if sys.argv[1:] == ['--version']:\n"
        "    getattr(sys, STREAM).write(VERSION)\n"
        "elif sys.argv[1:] == ['--list-langs']:\n"
        "    getattr(sys, STREAM).write(LANGS)\n"
        "else:\n"
        "    sys.exit(1)\n",
        encoding="utf-8",
    )
    return (PYTHON, str(script))


@pytest.mark.parametrize(
    ("answer", "stream", "version"),
    [
        ("tesseract 5.3.4\n leptonica-1.82.0\n", "stdout", (5, 3, 4)),
        ("tesseract v5.4.0.20240606\n leptonica-1.84.1\n", "stdout", (5, 4, 0)),  # UB Mannheim's build
        ("tesseract 4.1.1\n leptonica-1.79.0\n", "stdout", (4, 1, 1)),
        ("tesseract 3.05.02\n leptonica-1.74.4\n", "stderr", (3, 5, 2)),  # 3.x answered on stderr
        ("Tesseract 5.0\n", "stdout", (5, 0, 0)),
        ("leptonica-1.82.0\n", "stdout", None),
        ("Segmentation fault\n", "stderr", None),
        ("", "stdout", None),
    ],
)
def test_versions_are_read_from_every_known_answer(
    tmp_path: Path, answer: str, stream: str, version: tuple[int, int, int] | None
) -> None:
    launcher = _answering(tmp_path, answer, stream)
    found = ocr.look("/usr/bin/tesseract", launcher=launcher)
    assert found.path == "/usr/bin/tesseract" and found.launcher == launcher
    assert found.version == version
    # a Tesseract that names no version didn't answer: its languages aren't asked for
    assert found.languages == (("deu", "eng") if version else ())


@pytest.mark.parametrize(
    ("listed", "languages"),
    [
        (_LIST, ("deu", "eng")),
        (
            'List of available languages in "C:\\Tess\\tessdata/" (4):\neng\nosd\nscript/Latin\ndeu\n',
            ("deu", "eng"),
        ),
        ("List of available languages (2):\r\neng\r\nfra\r\n", ("eng",)),  # Windows line ends; 3.x's head
        ('List of available languages in "/x/" (1):\nosd\n', ()),
        ("deu\neng\n", ()),  # no list: nothing to trust
        ('Error opening data file /x/eng.traineddata\nList of available languages in "/x/" (0):\n', ()),
        ('List of available languages in "/x/" (2):\n  deu  \nDEU\n', ("deu",)),
    ],
)
def test_languages_are_read_from_the_list_and_kept_in_order(
    tmp_path: Path, listed: str, languages: tuple[str, ...]
) -> None:
    found = ocr.look("/usr/bin/tesseract", launcher=_answering(tmp_path, "tesseract 5.3.4\n", langs=listed))
    assert found.version == (5, 3, 4) and found.languages == languages
    assert found.usable is bool(languages)


@pytest.mark.parametrize(
    ("fake_mode", "version", "languages", "usable"),
    [
        ("ok", (5, 3, 4), ("deu", "eng"), True),
        ("old", (4, 0, 0), ("deu", "eng"), False),
        ("no-deu", (5, 3, 4), ("eng",), True),
        ("no-langs", (5, 3, 4), (), False),
    ],
)
def test_look_asks_the_fake_like_a_real_tesseract(
    mode: Callable[[str], None],
    fake_mode: str,
    version: tuple[int, int, int],
    languages: tuple[str, ...],
    usable: bool,
) -> None:
    mode(fake_mode)
    found = ocr.look(str(FAKE), launcher=(PYTHON, str(FAKE)))
    assert (found.version, found.languages, found.usable) == (version, languages, usable)


def test_a_tesseract_that_doesnt_answer_its_version_is_not_usable(
    mode: Callable[[str], None], tmp_path: Path
) -> None:
    mode("silent")
    started = time.monotonic()
    found = ocr.look(str(FAKE), launcher=(PYTHON, str(FAKE)), timeout_s=0.5)
    assert time.monotonic() - started < 5
    assert found == ocr.Tesseract(str(FAKE), None, (), launcher=(PYTHON, str(FAKE)))
    assert not found.usable
    # one that can't be started at all didn't answer either; look never raises
    missing = str(tmp_path / "nowhere" / "tesseract")
    assert ocr.look(missing) == ocr.Tesseract(missing, None, ())


def test_a_tesseract_whose_language_list_doesnt_answer_is_not_usable(tmp_path: Path) -> None:
    script = tmp_path / "half.py"
    script.write_text(
        "import sys, time\n"
        "if sys.argv[1:] == ['--version']:\n"
        "    print('tesseract 5.3.4')\n"
        "else:\n"
        "    time.sleep(60)\n",
        encoding="utf-8",
    )
    found = ocr.look("/usr/bin/tesseract", launcher=(PYTHON, str(script)), timeout_s=0.5)
    assert found.version is None and found.languages == () and not found.usable


# --------------------------------------------------------------------------------------------------
# find: the first usable one, remembered
# --------------------------------------------------------------------------------------------------


class _Looks:
    """Stands in for :func:`ocr.look`: answers from ``answers`` by path and counts what it was asked."""

    def __init__(self, answers: dict[str, ocr.Tesseract]) -> None:
        self.answers = answers
        self.asked: list[str] = []

    def __call__(self, path: str) -> ocr.Tesseract:
        self.asked.append(path)
        return self.answers.get(path, ocr.Tesseract(path, None, ()))


def _tesseract(path: str, version: tuple[int, int, int] | None = (5, 3, 4), *langs: str) -> ocr.Tesseract:
    return ocr.Tesseract(path, version, langs or ("deu", "eng"))


_FOUR = {"/opt/a/tesseract", "/opt/b/tesseract", "/usr/bin/tesseract", "/usr/local/bin/tesseract"}
_ON_PATH = {"PATH": "/opt/a:/opt/b"}


def test_find_takes_the_first_usable_tesseract_and_remembers_it() -> None:
    looks = _Looks(
        {
            "/opt/a/tesseract": _tesseract("/opt/a/tesseract", (4, 0, 0)),
            "/opt/b/tesseract": _tesseract("/opt/b/tesseract", (5, 3, 4), "eng"),
            "/usr/bin/tesseract": _tesseract("/usr/bin/tesseract"),
        }
    )

    def find(refresh: bool) -> ocr.Tesseract | None:
        return ocr.find(
            refresh=refresh, platform="linux", env=_ON_PATH, is_file=_is_program_in(_FOUR), look_at=looks
        )

    found = find(refresh=True)
    assert found == _tesseract("/opt/b/tesseract", (5, 3, 4), "eng")
    assert looks.asked == ["/opt/a/tesseract", "/opt/b/tesseract"]  # it stops at the first usable one
    assert find(refresh=False) is found
    assert looks.asked == ["/opt/a/tesseract", "/opt/b/tesseract"]  # remembered: nothing runs again
    looks.answers["/opt/b/tesseract"] = _tesseract("/opt/b/tesseract", (5, 3, 4), "deu", "eng")
    assert find(refresh=True) == looks.answers["/opt/b/tesseract"]  # looked at again
    assert looks.asked[2:] == ["/opt/a/tesseract", "/opt/b/tesseract"]
    # another set of candidates is another answer: what was remembered isn't handed out for it
    other = ocr.find(platform="linux", env={"PATH": ""}, is_file=_is_program_in(_FOUR), look_at=looks)
    assert other == looks.answers["/usr/bin/tesseract"]


def test_find_returns_an_old_or_language_less_tesseract_when_none_is_usable() -> None:
    """None of them is usable: the first one found comes back, so the doctor can say why."""
    old = _tesseract("/opt/a/tesseract", (4, 0, 0))
    looks = _Looks(
        {"/opt/a/tesseract": old, "/opt/b/tesseract": ocr.Tesseract("/opt/b/tesseract", (5, 3, 4), ())}
    )
    found = ocr.find(
        refresh=True, platform="linux", env=_ON_PATH, is_file=_is_program_in(_FOUR), look_at=looks
    )
    assert found == old and not found.usable
    assert looks.asked == [
        "/opt/a/tesseract",
        "/opt/b/tesseract",
        "/usr/bin/tesseract",
        "/usr/local/bin/tesseract",
    ]
    silent = _Looks({})  # none answers
    found = ocr.find(
        refresh=True, platform="linux", env=_ON_PATH, is_file=_is_program_in(_FOUR), look_at=silent
    )
    assert found == ocr.Tesseract("/opt/a/tesseract", None, ())


def test_find_is_none_when_nothing_is_installed(tmp_path: Path) -> None:
    """What the macOS and Windows runners prove: no Tesseract on the PATH or in the install folders."""
    looks = _Looks({})
    for platform in ("linux", "darwin", "win32"):
        none = ocr.find(
            refresh=True, platform=platform, env={"PATH": ""}, is_file=lambda p: False, look_at=looks
        )
        assert none is None
        assert ocr.find(platform=platform, env={"PATH": ""}, is_file=lambda p: False, look_at=looks) is None
    # an empty folder on the PATH and no install folders named (on Windows, its real files)
    assert ocr.find(refresh=True, platform="win32", env={"PATH": str(tmp_path)}, look_at=looks) is None
    assert looks.asked == []


def test_find_runs_nothing_while_turned_off() -> None:
    looks = _Looks({"/opt/a/tesseract": _tesseract("/opt/a/tesseract")})
    every = _is_program_in(_FOUR)
    found = ocr.find(refresh=True, platform="linux", env=_ON_PATH, is_file=every, look_at=looks)
    assert found is not None and looks.asked == ["/opt/a/tesseract"]
    for off in ("off", "0", "False", " no "):
        env = {**_ON_PATH, "ORDNUNG_OCR": off}
        assert ocr.find(refresh=True, platform="linux", env=env, is_file=every, look_at=looks) is None
        remembered = ocr.find(platform="linux", env=env, is_file=every, look_at=looks)
        assert remembered is None  # what was found before isn't handed out either
    # the process environment, as tests/conftest.py sets it
    assert ocr.find(refresh=True, is_file=every, look_at=looks) is None
    assert looks.asked == ["/opt/a/tesseract"]


@pytest.mark.skipif(
    sys.platform == "win32", reason="a shell script stands in for tesseract on Linux and macOS"
)
def test_find_looks_at_a_tesseract_on_the_path_and_it_reads(
    turned_on: None, mode: Callable[[str], None], tmp_path: Path
) -> None:
    """The whole way on this system's files: a ``tesseract`` on the PATH is found, asked and run."""
    folder = tmp_path / "bin"
    folder.mkdir()
    program = folder / "tesseract"
    program.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE}" "$@"\n', encoding="utf-8")
    program.chmod(0o755)
    mode("echo")
    found = ocr.find(refresh=True, env={"PATH": str(folder)})
    assert found == ocr.Tesseract(str(program), (5, 3, 4), ("deu", "eng"))
    assert found.argv == (str(program),)
    assert ocr.recognise(found, _png()) == ECHO_TEXT


# --------------------------------------------------------------------------------------------------
# recognise: how Tesseract runs
# --------------------------------------------------------------------------------------------------


def test_recognise_sends_a_png_on_stdin_and_reads_utf8_from_stdout(
    turned_on: None, mode: Callable[[str], None], report: Path
) -> None:
    mode("report")
    png = _png()
    assert ocr.recognise(_fake_engine(), png) == ECHO_TEXT
    seen = json.loads(report.read_text("utf-8"))
    assert seen["argv"] == ["stdin", "stdout", "-l", "deu+eng"]
    assert seen["png"] is True
    assert ocr.recognise(_fake_engine(("eng",)), png) == ECHO_TEXT
    assert json.loads(report.read_text("utf-8"))["argv"] == ["stdin", "stdout", "-l", "eng"]
    mode("ok")  # a page without words
    assert ocr.recognise(_fake_engine(), png) == ""


def test_a_picture_larger_than_the_pipe_reaches_a_tesseract_that_takes_it_late(
    turned_on: None, mode: Callable[[str], None]
) -> None:
    """A phone photo's PNG is megabytes; the pipe holds 64 KiB, and Tesseract loads its language data before it
    reads its stdin. The whole picture still reaches it, however many polls pass first."""
    mode("slow")
    noise = random.Random(24).randbytes(400 * 400)
    buffer = io.BytesIO()
    Image.frombytes("L", (400, 400), noise).save(buffer, "PNG")
    png = buffer.getvalue()
    assert len(png) > 2 * 65536
    started = time.monotonic()
    assert ocr.recognise(_fake_engine(), png, timeout_s=10.0) == ECHO_TEXT
    assert time.monotonic() - started < 10


def test_recognise_runs_one_thread_at_low_priority(
    turned_on: None, mode: Callable[[str], None], report: Path
) -> None:
    mode("report")
    ocr.recognise(_fake_engine(), _png())
    seen = json.loads(report.read_text("utf-8"))
    assert seen["OMP_THREAD_LIMIT"] == "1"
    if sys.platform == "win32":
        assert seen["priority"] == BELOW_NORMAL
    else:
        assert isinstance(seen["priority"], int) and seen["priority"] >= ocr.NICENESS


def test_recognise_gives_tesseract_a_private_temp_folder_it_removes_afterwards(
    turned_on: None, mode: Callable[[str], None], report: Path
) -> None:
    mode("report")
    ocr.recognise(_fake_engine(), _png())
    seen = json.loads(report.read_text("utf-8"))
    folder = Path(str(seen["TMPDIR"]))
    assert seen["TMP"] == seen["TEMP"] == str(folder)
    assert folder.name.startswith("ordnung-ocr-")
    assert not folder.exists()

    # while it reads: the folder is there, its owner's only; it goes when Tesseract is killed too
    report.unlink()
    mode("hang")
    stop = threading.Event()
    ended: list[BaseException] = []
    reading = threading.Thread(target=_read_until_stopped, args=(stop, ended), daemon=True)
    reading.start()
    try:
        seen = _wait_for(report)
        folder = Path(str(seen["TMPDIR"]))
        assert folder.is_dir() and folder.name.startswith("ordnung-ocr-")
        if sys.platform != "win32":
            assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    finally:
        stop.set()
        reading.join(10)
    assert not reading.is_alive()
    assert [type(error) for error in ended] == [ocr.Stopped]
    assert not folder.exists()


def _read_until_stopped(stop: threading.Event, ended: list[BaseException]) -> None:
    try:
        ocr.recognise(_fake_engine(), _png(), stop=stop)
    except BaseException as error:  # handed to the test's own thread
        ended.append(error)


def test_a_page_past_its_time_limit_is_killed(
    turned_on: None, mode: Callable[[str], None], report: Path
) -> None:
    mode("hang")
    started = time.monotonic()
    with pytest.raises(ocr.RecognitionError, match=r"^Tesseract took longer than 1 s$") as raised:
        ocr.recognise(_fake_engine(), _png(), timeout_s=1.0)
    assert type(raised.value) is ocr.RecognitionError  # not a stop
    assert 1.0 <= time.monotonic() - started < 10
    pid = json.loads(report.read_text("utf-8"))["pid"]
    assert _ends(pid)
    assert raised.value.__cause__ is None and raised.value.__context__ is None


def test_stop_kills_tesseract_within_a_poll(
    turned_on: None, mode: Callable[[str], None], report: Path
) -> None:
    mode("hang")
    stop = threading.Event()
    threading.Timer(0.2, stop.set).start()
    started = time.monotonic()
    with pytest.raises(ocr.Stopped):
        ocr.recognise(_fake_engine(), _png(), stop=stop)
    assert time.monotonic() - started < 1.0
    if report.exists():  # it got as far as taking its picture
        assert _ends(json.loads(report.read_text("utf-8"))["pid"])


def test_an_unexpected_error_while_reading_never_leaves_tesseract_running(
    turned_on: None, mode: Callable[[str], None], report: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mode("hang")

    def breaks(process: subprocess.Popen[bytes], data: bytes | None, **_: object) -> tuple[bytes, bytes]:
        """Hands the picture over as the real loop does, then fails once Tesseract took it and reads."""
        with pytest.raises(subprocess.TimeoutExpired):
            process.communicate(input=data, timeout=ocr.POLL_S)
        _wait_for(report)
        raise MemoryError("out of memory")

    monkeypatch.setattr(ocr, "_communicate", breaks)
    with pytest.raises(MemoryError):
        ocr.recognise(_fake_engine(), _png())
    seen = json.loads(report.read_text("utf-8"))
    assert _ends(seen["pid"])
    assert not Path(str(seen["TMPDIR"])).exists()


def test_a_stop_before_the_reading_starts_nothing(
    turned_on: None, mode: Callable[[str], None], report: Path
) -> None:
    mode("report")
    stop = threading.Event()
    stop.set()
    with pytest.raises(ocr.Stopped):
        ocr.recognise(_fake_engine(), _png(), stop=stop)
    assert not report.exists()


def test_a_failing_tesseract_is_an_error_that_never_carries_its_output(
    turned_on: None, mode: Callable[[str], None], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    mode("fail")
    with pytest.raises(ocr.RecognitionError) as raised:
        ocr.recognise(_fake_engine(), _png())
    assert str(raised.value) == "Tesseract stopped with exit code 1"
    assert raised.value.args == ("Tesseract stopped with exit code 1",)
    assert raised.value.__cause__ is None and raised.value.__context__ is None
    assert "exit code 1" in caplog.text
    for said in ("pixReadMem", "what the page said"):
        assert said not in caplog.text and said not in repr(raised.value)


def test_recognise_refuses_a_tesseract_it_cant_use(turned_on: None, report: Path, tmp_path: Path) -> None:
    for unusable in (
        ocr.Tesseract(str(FAKE), (4, 0, 0), ("deu",), launcher=(PYTHON, str(FAKE))),
        ocr.Tesseract(str(FAKE), (5, 3, 4), (), launcher=(PYTHON, str(FAKE))),
        ocr.Tesseract(str(FAKE), None, (), launcher=(PYTHON, str(FAKE))),
    ):
        with pytest.raises(ocr.RecognitionError, match="can't read pictures"):
            ocr.recognise(unusable, _png())
    assert not report.exists()
    gone = ocr.Tesseract(str(tmp_path / "gone" / "tesseract"), (5, 3, 4), ("deu",))
    with pytest.raises(ocr.RecognitionError, match=r"^Tesseract couldn't be started$") as raised:
        ocr.recognise(gone, _png())
    assert raised.value.__cause__ is None and raised.value.__context__ is None


# --------------------------------------------------------------------------------------------------
# page_picture: what Tesseract gets
# --------------------------------------------------------------------------------------------------


def test_page_picture_never_enlarges_a_photo_and_turns_it_upright(tmp_path: Path) -> None:
    small = tmp_path / "small.jpg"
    small.write_bytes(photo("JPEG", size=(800, 600)))
    picture = _picture(ocr.page_picture(small, "image/jpeg", 1))
    assert picture.size == (800, 600) and picture.mode == "L"
    assert "dpi" not in picture.info  # Tesseract works the resolution out itself

    large = tmp_path / "large.png"
    large.write_bytes(photo("PNG", size=(4000, 3000)))
    assert _picture(ocr.page_picture(large, "image/png", 1)).size == (2400, 1800)

    sideways = tmp_path / "sideways.jpg"
    sideways.write_bytes(photo("JPEG", orientation=6, size=(800, 600)))
    upright = _picture(ocr.page_picture(sideways, "image/jpeg", 1))
    assert upright.size == (600, 800)
    # the photo's red band, on its left edge as stored, is at the top once upright
    assert upright.getpixel((300, 20)) < 160 and upright.getpixel((300, 780)) > 240

    see_through = tmp_path / "logo.png"
    see_through.write_bytes(photo("PNG", alpha=True, size=(200, 100)))
    flat = _picture(ocr.page_picture(see_through, "image/png", 1))
    assert flat.mode == "L" and flat.getpixel((150, 50)) > 240  # flattened on white, not black


def test_page_picture_draws_a_pdf_page_at_2400_px_but_no_finer_than_300_dpi(tmp_path: Path) -> None:
    a4 = tmp_path / "a4.pdf"
    a4.write_bytes(make_pdf([[Line(72, 100, "Seite eins")], [Line(72, 100, "Seite zwei")]], size=A4))
    picture = _picture(ocr.page_picture(a4, "application/pdf", 2))
    assert picture.mode == "L"
    assert abs(picture.height - 2400) <= 1 and abs(picture.width - round(2400 * A4[0] / A4[1])) <= 1
    assert [round(dpi) for dpi in picture.info["dpi"]] == [205, 205]  # 2400 px over 11.69 in

    a6 = tmp_path / "a6.pdf"
    a6.write_bytes(make_pdf([[Line(20, 40, "Kassenbon")]], size=A6))
    receipt = _picture(ocr.page_picture(a6, "application/pdf", 1))
    assert abs(receipt.height - round(A6[1] * 300 / 72)) <= 1  # 1748 px: 300 dpi, not blown up to 2400
    assert abs(receipt.width - round(A6[0] * 300 / 72)) <= 1
    assert [round(dpi) for dpi in receipt.info["dpi"]] == [300, 300]

    landscape = tmp_path / "landscape.pdf"
    landscape.write_bytes(make_pdf([[Line(72, 100, "Quer")]], size=(A4[1], A4[0])))
    wide = _picture(ocr.page_picture(landscape, "application/pdf", 1))
    assert abs(wide.width - 2400) <= 1 and wide.height < wide.width


@pytest.mark.filterwarnings("ignore::PIL.Image.DecompressionBombWarning")
def test_page_picture_refuses_a_picture_too_large_to_decode_safely(tmp_path: Path) -> None:
    huge = tmp_path / "huge.png"
    buffer = io.BytesIO()
    Image.new("1", (10_000, 9_000)).save(buffer, "PNG")  # 90 megapixels, more than intake decodes
    huge.write_bytes(buffer.getvalue())
    with pytest.raises(ocr.RecognitionError, match=r"^page 1 couldn't be drawn$") as raised:
        ocr.page_picture(huge, "image/png", 1)
    assert raised.value.__cause__ is None


@pytest.mark.parametrize(
    ("name", "content", "mime", "page"),
    [
        ("one.pdf", "pdf", "application/pdf", 2),
        ("one.pdf", "pdf", "application/pdf", 0),
        ("one.pdf", "pdf", "application/pdf", -1),
        ("photo.jpg", "photo", "image/jpeg", 2),
        ("photo.jpg", "photo", "image/jpeg", 0),
        ("broken.pdf", "broken-pdf", "application/pdf", 1),
        ("broken.jpg", "broken-photo", "image/jpeg", 1),
        ("missing.pdf", None, "application/pdf", 1),
        ("missing.jpg", None, "image/jpeg", 1),
        ("note.txt", "text", "text/plain", 1),
    ],
)
def test_page_picture_of_a_page_that_isnt_there_is_an_error(
    tmp_path: Path, name: str, content: str | None, mime: str, page: int
) -> None:
    original = tmp_path / name
    data = {
        "pdf": make_pdf([[Line(72, 100, "Eine Seite")]]),
        "photo": photo("JPEG"),
        "broken-pdf": b"%PDF-1.4\nthis is not really a pdf",
        "broken-photo": b"\xff\xd8\xff\xe0" + b"\x00" * 40,
        "text": b"Nur Text",
    }
    if content is not None:
        original.write_bytes(data[content])
    with pytest.raises(ocr.RecognitionError, match=rf"^page {page} couldn't be drawn$") as raised:
        ocr.page_picture(original, mime, page)
    assert raised.value.__cause__ is None


# --------------------------------------------------------------------------------------------------
# The real Tesseract
# --------------------------------------------------------------------------------------------------


def _real_tesseract() -> ocr.Tesseract:
    """The Tesseract installed here, with German; the test skips without one, except where
    ``ORDNUNG_REQUIRE_TESSERACT=1`` (CI's Linux legs that install it): there a missing or unusable one fails it."""
    engine = ocr.find(refresh=True)
    if engine is None or not engine.usable or "deu" not in engine.languages:
        why = f"needs Tesseract 4.1 or newer with German (found: {engine})"
        if os.environ.get("ORDNUNG_REQUIRE_TESSERACT") == "1":
            pytest.fail(why)
        pytest.skip(why)
    return engine


def test_real_tesseract_reads_a_scan_and_a_photo(turned_on: None, tmp_path: Path) -> None:
    """A scan without a text layer, and a photo of the same lines taken with the phone on its side: Tesseract reads
    the words, umlaut and ß included, from the pictures Ordnung draws."""
    engine = _real_tesseract()
    scan = tmp_path / "scan.pdf"
    scan.write_bytes(scanned_pdf())
    sideways = tmp_path / "photo.jpg"
    sideways.write_bytes(scanned_photo(orientation=6))
    for original, mime in ((scan, "application/pdf"), (sideways, "image/jpeg")):
        words = ocr.recognise(engine, ocr.page_picture(original, mime, 1))
        assert "Einkommensteuer" in words, mime
        assert "Steuerstraße" in words, mime
