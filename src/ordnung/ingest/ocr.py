"""Text in pictures (ADR 0024): the words in a photo or scan Claude isn't reading, read on this computer by
Tesseract, an optional program the person installs, for the letter search only.

Only letters Claude isn't reading qualify: kept private, held, waiting for Claude, or failed. What Tesseract reads
is kept in ``derived/<doc_id>/picture-text.json`` (:mod:`ordnung.db.scan_text`, through the store) under the
scanner text's rules (ADR 0020): never a page's text, never shown, checked or sent to Claude, never in Ask's
search or the ledger fingerprint, and removed once Claude reads that page.

This module is the engine and nothing else:

* :func:`find` looks for a usable Tesseract (4.1 or newer, with German and/or English) and remembers it. It looks
  on the ``PATH`` (absolute entries only, never the current folder) and then in each system's install folders
  (:func:`candidates`), and asks each one for its version and languages (:func:`look`);
* :func:`page_picture` draws one page as a grayscale PNG: at most :data:`PICTURE_LONG_SIDE` pixels on its long
  side and :data:`MAX_DPI`, never enlarged, with intake's bounded decoder or PDFium under its lock; Tesseract
  never sees the uploaded file itself;
* :func:`recognise` runs Tesseract on that PNG (stdin to stdout): a fixed argv and no shell, one thread
  (``OMP_THREAD_LIMIT=1``), at low priority (niceness :data:`NICENESS`, ``BELOW_NORMAL_PRIORITY_CLASS`` and no
  console window on Windows), in a private temporary folder removed afterwards, polled every :data:`POLL_S`
  seconds, and killed at its time limit or when Ordnung stops (:class:`Stopped`).

What Tesseract prints is never put in an error or a log: a failure names its exit code only.

``ORDNUNG_OCR=off`` (:data:`OCR_SWITCH`, :func:`ordnung.config.ocr_turned_off`) turns it all off: :func:`find`
answers ``None`` and runs nothing, and :func:`recognise` refuses. It can also be off in Settings (*Text in
pictures*, ``read_picture_text``): the worker and the letter routes check that
(:func:`ordnung.config.picture_text_off`); this module, the last guard, keeps to the variable alone. Only the
worker (:mod:`ordnung.ingest.worker`) and the doctor (:mod:`ordnung.doctor`) import this module.
"""

from __future__ import annotations

import contextlib
import io
import logging
import ntpath
import os
import posixpath
import re
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO

import pypdfium2 as pdfium
from PIL import Image

from ordnung import config
from ordnung.ingest import intake
from ordnung.ingest.text import PDFIUM_LOCK

_log = logging.getLogger(__name__)

#: The off switch (``ORDNUNG_OCR=off``; :func:`ordnung.config.ocr_turned_off`).
OCR_SWITCH = config.OCR_SWITCH
#: The oldest Tesseract Ordnung uses.
MIN_VERSION = (4, 1)
#: The languages Ordnung asks for, in this order (``-l deu+eng``), of those installed.
LANGUAGES = ("deu", "eng")
#: The long side of the picture Tesseract gets, in pixels (a photo is never enlarged to it).
PICTURE_LONG_SIDE = 2400
#: A PDF page is never drawn finer than this, so a small page (a receipt) stays small.
MAX_DPI = 300
#: The time limit of ``--version`` and ``--list-langs``.
LOOK_TIMEOUT_S = 10.0
#: The time limit of reading one page.
PAGE_TIMEOUT_S = 120.0
#: How often a reading checks whether Ordnung is stopping.
POLL_S = 0.25
#: The niceness Tesseract runs at on Linux and macOS (``BELOW_NORMAL_PRIORITY_CLASS`` on Windows).
NICENESS = 10

#: Where each system's packages put Tesseract, looked in after the ``PATH``: a launchd or desktop start has a
#: short ``PATH`` (no Homebrew, no MacPorts).
_LINUX_PLACES = ("/usr/bin", "/usr/local/bin")
_MACOS_PLACES = ("/opt/homebrew/bin", "/usr/local/bin", "/opt/local/bin")
#: Windows: the UB Mannheim installer's folders (it doesn't put itself on the ``PATH``), as (variable, below it).
_WINDOWS_PLACES = (
    ("ProgramFiles", "Tesseract-OCR"),
    ("ProgramFiles(x86)", "Tesseract-OCR"),
    ("LOCALAPPDATA", "Programs\\Tesseract-OCR"),
)
#: ``tesseract 5.3.4``, UB Mannheim's ``tesseract v5.4.0.20240606``, and 3.x's answer (on stderr).
_VERSION = re.compile(r"tesseract\s+v?(\d+)\.(\d+)(?:\.(\d+))?", re.IGNORECASE)
#: The line ``--list-langs`` starts its list with (``… in "<tessdata>" (3):``, or 3.x's ``… (3):``).
_LANGUAGE_LIST = "List of available languages"
_COULDNT_START = "Tesseract couldn't be started"
_TEMP_PREFIX = "ordnung-ocr-"


@dataclass(frozen=True, slots=True)
class Tesseract:
    """A Tesseract found on this computer: where, which version (``None``: it didn't answer) and which of
    :data:`LANGUAGES` it has, in that order. ``launcher`` is for tests only: what runs instead of ``path``
    (``(sys.executable, "tests/fake_tesseract.py")``)."""

    path: str
    version: tuple[int, int, int] | None
    languages: tuple[str, ...]
    launcher: tuple[str, ...] = ()

    @property
    def usable(self) -> bool:
        """Whether Ordnung reads pictures with it: :data:`MIN_VERSION` or newer, with German or English."""
        return self.version is not None and self.version >= MIN_VERSION and bool(self.languages)

    @property
    def argv(self) -> tuple[str, ...]:
        """What runs it, before its arguments."""
        return self.launcher or (self.path,)


class RecognitionError(Exception):
    """A page's words couldn't be read. Its message never holds what Tesseract printed."""


class Stopped(RecognitionError):
    """Ordnung stopped while Tesseract was reading a page; Tesseract was killed and nothing is kept."""


def turned_off(env: Mapping[str, str] | None = None) -> bool:
    """Whether ``ORDNUNG_OCR`` turns text in pictures off (:func:`ordnung.config.ocr_turned_off`)."""
    return config.ocr_turned_off(env)


# --------------------------------------------------------------------------------------------------
# Finding Tesseract
# --------------------------------------------------------------------------------------------------


def _is_program(path: str) -> bool:
    """Whether ``path`` is a file this system can run (on Windows: any file; only ``tesseract.exe`` is named)."""
    return Path(path).is_file() and (sys.platform == "win32" or os.access(path, os.X_OK))


def candidates(
    platform: str = sys.platform,
    env: Mapping[str, str] | None = None,
    *,
    is_file: Callable[[str], bool] = _is_program,
) -> list[str]:
    """The Tesseract programs to look at on ``platform``, in order: each absolute ``PATH`` entry, then the
    system's install folders; only those ``is_file`` finds, each once.

    The ``PATH`` is split by hand, not with :func:`shutil.which`: an empty, ``.`` or relative entry is skipped,
    so a ``tesseract`` in Ordnung's current folder is never run on a private letter (Windows' ``which`` even looks
    there first). On Windows only ``tesseract.exe`` is named (never a script), an entry needs a drive or a
    network share, and the environment's names are read in any case, as Windows does."""
    windows = platform == "win32"
    names = os.environ if env is None else env
    if windows:
        names = {name.upper(): value for name, value in names.items()}
    paths = ntpath if windows else posixpath
    program = "tesseract.exe" if windows else "tesseract"

    def absolute(folder: str) -> bool:
        if windows:
            return bool(ntpath.splitdrive(folder)[0]) and ntpath.isabs(folder)
        return posixpath.isabs(folder)

    folders = [
        entry.strip('"') if windows else entry
        for entry in names.get("PATH", "").split(";" if windows else ":")
    ]
    if windows:
        folders += [paths.join(names.get(name.upper(), ""), below) for name, below in _WINDOWS_PLACES]
    else:
        folders += _MACOS_PLACES if platform == "darwin" else _LINUX_PLACES

    found: list[str] = []
    seen: set[str] = set()
    for folder in folders:
        if not absolute(folder):
            continue
        path = paths.join(folder, program)
        same = paths.normcase(os.path.realpath(path))
        if same in seen or not is_file(path):
            continue
        seen.add(same)
        found.append(path)
    return found


def look(path: str, *, launcher: tuple[str, ...] = (), timeout_s: float = LOOK_TIMEOUT_S) -> Tesseract:
    """Ask the Tesseract at ``path`` for its version (``--version``) and languages (``--list-langs``), each within
    ``timeout_s`` and at the priority a reading runs at. One that can't be started, doesn't answer in time or names
    no version didn't answer (``version`` ``None``). Never raises."""
    silent = Tesseract(path, None, (), launcher)
    argv = silent.argv
    answer = _ask(argv, "--version", timeout_s)
    version = None if answer is None else _version(answer)
    if version is None:
        return silent
    listed = _ask(argv, "--list-langs", timeout_s)
    if listed is None:
        return silent
    return Tesseract(path, version, _languages(listed), launcher)


def _ask(argv: Sequence[str], flag: str, timeout_s: float) -> str | None:
    """What ``argv flag`` printed (stdout, then stderr: 3.x answers there); ``None``: it didn't answer."""
    try:
        _, out, err = _run([*argv, flag], None, timeout_s=timeout_s, stop=None)
    except RecognitionError:
        return None
    return (out + b"\n" + err).decode("utf-8", "replace")


def _version(answer: str) -> tuple[int, int, int] | None:
    match = _VERSION.search(answer)
    if match is None:
        return None
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch or 0)


def _languages(answer: str) -> tuple[str, ...]:
    """Which of :data:`LANGUAGES` the list names, in that order (none without the list's first line)."""
    lines = [line.strip() for line in answer.splitlines()]
    for index, line in enumerate(lines):
        if line.startswith(_LANGUAGE_LIST):
            listed = set(lines[index + 1 :])
            return tuple(language for language in LANGUAGES if language in listed)
    return ()


#: The last :func:`find`'s answer, by the system and candidates it looked at (one entry).
_found: dict[tuple[str, tuple[str, ...]], Tesseract | None] = {}
_found_lock = threading.Lock()


def find(
    *,
    refresh: bool = False,
    platform: str = sys.platform,
    env: Mapping[str, str] | None = None,
    is_file: Callable[[str], bool] = _is_program,
    look_at: Callable[[str], Tesseract] = look,
) -> Tesseract | None:
    """The Tesseract Ordnung reads pictures with: the first usable one of :func:`candidates`, or, when none is
    usable, the first one found (so the doctor can say why); ``None``: not installed, or turned off (then nothing
    runs at all).

    The answer is remembered for the same candidates; ``refresh=True`` looks again (the worker does once per
    start, the doctor on every run). ``is_file`` and ``look_at`` are for tests."""
    if turned_off(env):
        return None
    paths = tuple(candidates(platform, env, is_file=is_file))
    key = (platform, paths)
    with _found_lock:
        if not refresh and key in _found:
            return _found[key]
    found = _first_usable(paths, look_at)
    with _found_lock:
        _found.clear()
        _found[key] = found
    return found


def _first_usable(paths: Sequence[str], look_at: Callable[[str], Tesseract]) -> Tesseract | None:
    first: Tesseract | None = None
    for path in paths:
        found = look_at(path)
        if found.usable:
            return found
        if first is None:
            first = found
    return first


# --------------------------------------------------------------------------------------------------
# The picture of a page
# --------------------------------------------------------------------------------------------------


def page_picture(original: Path, mime: str, page: int) -> bytes:
    """Page ``page`` (1-based) of the letter's file as the PNG Tesseract reads: grayscale, never enlarged.

    A photo (``image/*``, one page) is decoded as intake decodes it (JPEG draft, the pixel limit, turned upright,
    flattened on white) and shrunk to :data:`PICTURE_LONG_SIDE` pixels at most; its PNG names no resolution
    (Tesseract works it out). A PDF page is drawn by PDFium under its lock at :data:`PICTURE_LONG_SIDE` pixels on
    its long side, but never finer than :data:`MAX_DPI` (a receipt stays small), and its PNG names that
    resolution. Anything that can't be drawn — a page that isn't there, a damaged, missing or too large file,
    another kind of file — is a :class:`RecognitionError`."""
    try:
        drawn = _draw(original, mime, page)
    except (ValueError, OSError, pdfium.PdfiumError):  # IntakeError is a ValueError
        drawn = None
    if drawn is None:
        raise RecognitionError(f"page {page} couldn't be drawn")
    image, dpi = drawn
    buffer = io.BytesIO()
    if dpi is None:
        image.save(buffer, "PNG", compress_level=1)
    else:
        image.save(buffer, "PNG", compress_level=1, dpi=(dpi, dpi))
    return buffer.getvalue()


def _draw(original: Path, mime: str, page: int) -> tuple[Image.Image, int | None] | None:
    """The page in grayscale, and the resolution it was drawn at (``None`` for a photo); ``None``: no such page."""
    if mime.startswith("image/"):
        if page != 1:
            return None
        image = intake._load_image(original.read_bytes())
        image.thumbnail((PICTURE_LONG_SIDE, PICTURE_LONG_SIDE), Image.Resampling.LANCZOS)  # never enlarges
        return image.convert("L"), None
    if mime == "application/pdf":
        return _pdf_page(original, page)
    return None


def _pdf_page(original: Path, page: int) -> tuple[Image.Image, int] | None:
    with PDFIUM_LOCK:
        pdf = intake._open_pdf(original)
        try:
            if not 1 <= page <= len(pdf):
                return None
            sheet = pdf[page - 1]
            try:
                width, height = sheet.get_size()  # turned by /Rotate, clipped to the CropBox
                if min(width, height) <= 0:
                    return None
                scale = min(PICTURE_LONG_SIDE / max(width, height), MAX_DPI / 72)
                bitmap = sheet.render(scale=scale, may_draw_forms=True)
                try:
                    image: Image.Image = bitmap.to_pil().convert("L")  # a copy, before the bitmap goes
                finally:
                    bitmap.close()
            finally:
                sheet.close()
        finally:
            pdf.close()
    return image, round(72 * scale)


# --------------------------------------------------------------------------------------------------
# Reading a picture
# --------------------------------------------------------------------------------------------------


def recognise(
    engine: Tesseract,
    png: bytes,
    *,
    stop: threading.Event | None = None,
    timeout_s: float = PAGE_TIMEOUT_S,
) -> str:
    """The words Tesseract reads in ``png`` (from :func:`page_picture`), in the languages it has of
    :data:`LANGUAGES`: ``tesseract stdin stdout -l deu+eng``, the PNG on its stdin, UTF-8 from its stdout.

    It runs with one thread, at low priority, in a private temporary folder that is removed afterwards. Every
    :data:`POLL_S` seconds it checks ``stop`` (set: Tesseract is killed, :class:`Stopped`) and ``timeout_s``
    (past it: killed, :class:`RecognitionError`). It refuses while turned off, for a Tesseract that isn't usable,
    and when Tesseract can't be started or stops with an error; the error names the exit code, never what
    Tesseract printed."""
    if turned_off():
        raise RecognitionError(f"text in pictures is turned off ({OCR_SWITCH}=off)")
    if not engine.usable:
        raise RecognitionError(
            "this Tesseract can't read pictures: it needs 4.1 or newer with German or English"
        )
    argv = [*engine.argv, "stdin", "stdout", "-l", "+".join(engine.languages)]
    code, out, _ = _run(argv, png, timeout_s=timeout_s, stop=stop)
    if code != 0:
        _log.info("Tesseract stopped with exit code %d", code)
        raise RecognitionError(f"Tesseract stopped with exit code {code}")
    return out.decode("utf-8", "replace")


def _run(
    argv: Sequence[str], data: bytes | None, *, timeout_s: float, stop: threading.Event | None
) -> tuple[int, bytes, bytes]:
    """Run ``argv`` (``data`` on its stdin; ``None``: no stdin) at low priority, with one thread, in a private
    temporary folder (its working folder and ``TMPDIR``/``TMP``/``TEMP``) removed afterwards; its exit code,
    stdout and stderr. Raises :class:`Stopped` or :class:`RecognitionError` (couldn't start, too slow)."""
    if stop is not None and stop.is_set():
        raise Stopped("Ordnung is stopping")
    with tempfile.TemporaryDirectory(prefix=_TEMP_PREFIX, ignore_cleanup_errors=True) as folder:
        env = {**os.environ, "OMP_THREAD_LIMIT": "1", "TMPDIR": folder, "TMP": folder, "TEMP": folder}
        try:
            process: subprocess.Popen[bytes] | None = _start(argv, env, folder, piped=data is not None)
        except (OSError, ValueError):
            process = None
        if process is None:
            raise RecognitionError(_COULDNT_START)
        try:
            out, err = _communicate(process, data, timeout_s=timeout_s, stop=stop)
        finally:
            if process.poll() is None:  # only on the way out of an unexpected error
                _kill(process)
        return process.returncode, out, err


def _start(argv: Sequence[str], env: dict[str, str], folder: str, *, piped: bool) -> subprocess.Popen[bytes]:
    stdin = subprocess.PIPE if piped else subprocess.DEVNULL
    if sys.platform == "win32":  # pragma: no cover - exercised on Windows only
        flags = subprocess.BELOW_NORMAL_PRIORITY_CLASS | subprocess.CREATE_NO_WINDOW
        return subprocess.Popen(
            argv,
            stdin=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=folder,
            creationflags=flags,
        )
    else:
        process = subprocess.Popen(
            argv, stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=folder
        )
        # From here, not preexec_fn (not safe with threads): the child gets its stdin only after this, so it reads
        # nothing at normal priority. Never lower than Ordnung's own niceness.
        with contextlib.suppress(OSError):
            os.setpriority(os.PRIO_PROCESS, process.pid, max(os.getpriority(os.PRIO_PROCESS, 0), NICENESS))
        return process


def _communicate(
    process: subprocess.Popen[bytes], data: bytes | None, *, timeout_s: float, stop: threading.Event | None
) -> tuple[bytes, bytes]:
    """Hand ``data`` over and wait, checking ``stop`` and the time limit every :data:`POLL_S` seconds.

    ``data`` goes to stdin from a thread of its own (:func:`_hand_over`), never through ``communicate(input=…)``:
    after a poll that timed out, Python before 3.13 never writes the rest of the input nor closes stdin, so a
    picture larger than the pipe holds would never reach a Tesseract that loads its language data first, and on
    Windows the first ``communicate`` writes it all before it looks at the time. So the stop and the time limit
    apply while Tesseract takes its picture too."""
    deadline = time.monotonic() + timeout_s
    writer: threading.Thread | None = None
    if data is not None and process.stdin is not None:
        stdin, process.stdin = process.stdin, None  # communicate() leaves it to the thread
        writer = threading.Thread(
            target=_hand_over, args=(stdin, data), name="ordnung-ocr-stdin", daemon=True
        )
        writer.start()
    try:
        while True:
            try:
                return process.communicate(timeout=POLL_S)
            except subprocess.TimeoutExpired:  # what it printed so far stays in there
                pass
            if stop is not None and stop.is_set():
                _kill(process)
                raise Stopped("Ordnung stopped while Tesseract was reading a page")
            if time.monotonic() >= deadline:
                _kill(process)
                _log.info("Tesseract took longer than %g s and was stopped", timeout_s)
                raise RecognitionError(f"Tesseract took longer than {timeout_s:g} s")
    finally:
        if writer is not None:
            if process.poll() is None:  # only on the way out of an unexpected error: its stdin breaks with it
                _kill(process)
            writer.join(LOOK_TIMEOUT_S)


def _hand_over(stdin: IO[bytes], data: bytes) -> None:
    """Write the picture to Tesseract's stdin and close it (in a thread: it blocks while the pipe is full). A
    Tesseract that ended or was killed meanwhile breaks the pipe; there is nothing left to do then."""
    try:
        stdin.write(data)
    except OSError:  # BrokenPipeError; EINVAL on Windows
        pass
    finally:
        with contextlib.suppress(OSError):
            stdin.close()


def _kill(process: subprocess.Popen[bytes]) -> None:
    process.kill()
    try:
        process.communicate(timeout=LOOK_TIMEOUT_S)  # reaps it and closes the pipes
    except subprocess.TimeoutExpired:
        _log.warning("Tesseract (process %d) didn't end when it was killed", process.pid)
