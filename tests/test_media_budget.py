"""README's media are small, light and come from replay only: ``make capture`` (``scripts/capture.sh``,
``web/scripts/capture.mjs``) records the tour video, its GIF and the pictures with settings that keep them small,
asks no model, reads no words in pictures, checks every frame and every page for the theme, a path of the
capturing computer or a name, and leaves contact sheets to look at before anything is committed.

The media are public and stay in the history, so these budgets keep them from growing unseen.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

from helpers_media import gif_info, mp4_info, png_info

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "docs" / "assets"
CAPTURE_SH = ROOT / "scripts" / "capture.sh"
CAPTURE_MJS = ROOT / "web" / "scripts" / "capture.mjs"
#: what no picture may show, shared by ``capture.mjs`` and the real app's pictures
CAPTURE_GUARD = ROOT / "web" / "scripts" / "capture-guard.mjs"
PICTURES_SPEC = ROOT / "web" / "e2e" / "readme-pictures.spec.ts"

GIF_BYTES = 4_500_000
MP4_BYTES = 3_500_000
#: each picture's budget
PNG_BYTES = 650_000
#: everything in ``docs/assets``
ASSETS_BYTES = 12_500_000
GIF_SECONDS_MAX = 45
MP4_SECONDS_MAX = 150
#: mean luma (0 black, 255 white): a picture in the light theme is at least this bright, one in the dark theme at
#: most :data:`DARK`
LIGHT = 150
DARK = 100

DESKTOP = (1440, 900)
#: The pictures ``make capture`` makes, with their size in pixels (``why.png`` is the receipt dialog alone: only
#: its width is fixed, by the dialog).
PICTURES: dict[str, tuple[int, int] | None] = {
    "today.png": DESKTOP,
    "today-dark.png": DESKTOP,
    "document.png": DESKTOP,
    "court-order.png": DESKTOP,
    "pay.png": DESKTOP,
    "numbers.png": DESKTOP,
    "week.png": DESKTOP,
    "timeline.png": DESKTOP,
    "contracts.png": DESKTOP,
    "proof.png": DESKTOP,
    "trace.png": DESKTOP,
    "scam.png": DESKTOP,
    "pair-phone.png": DESKTOP,
    "your-computers.png": DESKTOP,
    "ask.png": (1440, 1500),
    "mobile.png": (780, 1688),
    "mobile-dark.png": (780, 1688),
    "why.png": None,
}
WHY_WIDTH_MAX = 600
#: dark on purpose: README shows the dark theme once on a computer and once on a phone
DARK_PICTURES = frozenset({"today-dark.png", "mobile-dark.png"})
#: the benchmark's chart (``make capture`` doesn't make it): checked by its size only
EVAL_CHART = "eval-due-date-accuracy.png"
#: what a path of the capturing computer starts with, in any file's bytes
PATH_MARKS = (b"/home/", b"/Users/", b"/root/", b"/tmp/", b"\\Users\\")
#: everything else ``docs/assets`` holds: the README's video, its GIF and the logo
OTHER_MEDIA = frozenset({"demo.gif", "demo.mp4", "logo.svg"})

_needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="needs node")


def _capture_sh() -> str:
    return CAPTURE_SH.read_text(encoding="utf-8")


def _capture_mjs() -> str:
    return CAPTURE_MJS.read_text(encoding="utf-8")


def _capture_guard() -> str:
    return CAPTURE_GUARD.read_text(encoding="utf-8")


def _code(script: str) -> str:
    """A shell script without its comments (whole-line ones), so a check never passes on a comment."""
    return "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("#"))


def _function(source: str, name: str) -> str:
    """The body of the top-level JavaScript function ``name`` in ``source``, exported or not (up to the next line that
    is ``}``)."""
    start = re.search(rf"^(?:export )?(?:async )?function {name}\(", source, re.M)
    assert start, f"the script has a function {name}"
    return source[start.start() : source.index("\n}\n", start.start())]


def _demo_server(script: str) -> str:
    """The line of ``capture.sh`` that starts the demo it captures."""
    (line,) = [line for line in script.splitlines() if "/ordnung demo " in line]
    return line


def _pictures_command(script: str) -> str:
    end = script.index("npx playwright test --project pictures)")
    return script[script.rindex("(cd web && ", 0, end) : end]


# --------------------------------------------------------------------------------------------------
# What make capture does
# --------------------------------------------------------------------------------------------------


def test_make_capture_makes_a_720_px_gif_at_6_fps_with_64_colours_and_a_crf_32_mp4() -> None:
    """The GIF is 720 px wide, 6 frames a second and 64 colours; the MP4 is H.264 at CRF 32 and starts playing at
    once (``+faststart``). Each setting has its knob; the GIF's dither stays."""
    script = _code(_capture_sh())
    for default in (
        "GIF_WIDTH=${CAPTURE_GIF_WIDTH:-720}",
        "GIF_FPS=${CAPTURE_GIF_FPS:-6}",
        "GIF_COLOURS=${CAPTURE_GIF_COLOURS:-64}",
        "MP4_CRF=${CAPTURE_MP4_CRF:-32}",
    ):
        assert re.search(rf"^{re.escape(default)}$", script, re.M), default
    mp4 = script[script.index("-c:v libx264") :].split("\n", 1)[0]
    assert '-crf "$MP4_CRF"' in mp4 and "-movflags +faststart" in mp4
    gif = script[script.index('"fps=$GIF_FPS,') :].split("\n", 1)[0]
    assert "scale=$GIF_WIDTH:-1" in gif
    assert "palettegen=max_colors=$GIF_COLOURS:stats_mode=diff" in gif
    assert "paletteuse=dither=bayer" in gif
    assert "-crf 30" not in script and "max_colors=96" not in script


def test_make_capture_asks_no_model_and_turns_text_recognition_off() -> None:
    """Everything ``make capture`` starts runs with the fake ``claude`` (tests/fake_claude.py) on a scenario that
    fails and logs every call, and with ``ORDNUNG_OCR=off``: the demo replays its recordings, a Tesseract on the
    capturing computer changes nothing, and a single call to a model fails the run, saying where the log is."""
    script = _code(_capture_sh())
    before = script[: script.index("/ordnung demo ")]
    (exports,) = [
        line for line in before.splitlines() if line.startswith("export ") and "ORDNUNG_CLAUDE_BIN" in line
    ]
    assert 'ORDNUNG_CLAUDE_BIN="$PWD/tests/fake_claude.py"' in exports
    assert 'FAKE_CLAUDE_SCENARIO="$SCENARIO"' in exports
    assert "ORDNUNG_OCR=off" in exports
    # the scenario: one call that fails, logged to CLAUDE_LOG, which starts empty
    scenario = before[before.index('SCENARIO="') : before.index(exports)]
    assert '"exit": 1' in scenario and '"log"' in scenario and "$CLAUDE_LOG" in scenario
    assert ': > "$CLAUDE_LOG"' in scenario
    # the demo replays (no --live) and the pictures' servers keep the off switch: nothing turns either back on
    server = _demo_server(script)
    assert "demo --serve" in server and "--live" not in server
    pictures = _pictures_command(script)
    assert pictures.startswith("(cd web && env -u ORDNUNG_E2E_REUSE ")
    assert "-u ORDNUNG_E2E_OCR " in pictures  # the real app reads pictures only when the e2e run asks for it
    for override in (
        "--live",
        "ORDNUNG_RECORD",
        "ORDNUNG_OCR=",
        "-u ORDNUNG_OCR",
        "ORDNUNG_CLAUDE_BIN=",
        "unset",
    ):
        assert override not in script.replace(exports, ""), override
    # at the end, after the pictures: a call to the model fails the run
    check = script[script.index("--project pictures") :]
    assert 'if [ -s "$CLAUDE_LOG" ]' in check
    assert "make capture asked a model ($CALLS calls): see $CLAUDE_LOG" in check
    assert check.index('"$CLAUDE_LOG" ]') < check.index("exit 1")


def test_make_capture_checks_every_frame_and_picture() -> None:
    """``capture.sh`` measures every frame of the MP4 (two a second) and fails on one darker than the light theme,
    then draws contact sheets of the video and the GIF into the review folder (never under ``docs/``) and ends by
    saying what to look at. ``capture.mjs`` guards every page it opens: the theme, and no path of the capturing
    computer, its name, the git e-mail or a word of the author's name, read when it runs (never written here)."""
    script = _code(_capture_sh())
    review = r'^REVIEW=\$\(realpath -m "\$\{CAPTURE_REVIEW:-\$\(mktemp -d\)/[\w-]+\}"\)$'
    assert re.search(review, script, re.M)  # a new folder each run, unless CAPTURE_REVIEW names one
    assert '"$PWD/docs/"*' in script  # a review folder under docs/ is refused
    frames = script[script.index("signalstats") - 200 :]
    assert "fps=2,signalstats" in frames and "lavfi.signalstats.YAVG" in frames and "min=150" in frames
    assert (
        "A frame of demo.mp4 is dark (mean brightness %.0f at %.1f s): the tour must stay in the light theme."
        in frames
    )
    sheets = re.findall(r'-vf "([^"]*tile=[^"]*)" "\$REVIEW/([\w-]+)-%02d\.png"', script)
    assert {name for _, name in sheets} == {"video-sheet", "gif-sheet"}, sheets
    # a dark frame stops the run before the GIF is made
    assert script.index("signalstats") < script.index("palettegen")
    assert script.rstrip().endswith(
        'echo "Look at every picture and every sheet in $REVIEW before you commit them: light theme (today-dark.png '
        "and mobile-dark.png are dark on purpose), no path of this computer's, no real names.\""
    )

    capture = _capture_mjs()
    context = _function(capture, "newContext")
    assert "addInitScript(guardPage, " in context
    for name in ("caption", "shot"):
        assert "await assertClean(" in _function(capture, name), name
    guard = _function(capture, "guardPage")
    # what is on screen, whenever the page changes or scrolls
    assert "MutationObserver" in guard and 'addEventListener("scroll"' in guard and '"cap-leaks"' in guard
    # the words come from capture-guard.mjs, which the real app's pictures share; the capture adds its own folders
    words = _function(_capture_guard(), "forbiddenWords")
    for source in ("homedir()", "hostname()", '"user.email"', "pyproject.toml", "CAPTURE_FORBIDDEN"):
        assert source in words, source
    assert 'import { forbiddenWords, pathRoots } from "./capture-guard.mjs";' in capture
    (found,) = re.findall(r"^const FORBIDDEN = forbiddenWords\((.*)\);$", capture, re.M)
    assert found.startswith("REPO, [") and "resolve(opts.data)" in found and "OUT" in found
    # no name is written into the repo: the author's is read from pyproject.toml when the capture runs
    authors = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["authors"]
    for author in authors:
        for word in re.findall(r"[^\W\d_]{3,}", author["name"]):
            for text in (capture, _capture_guard(), PICTURES_SPEC.read_text(encoding="utf-8"), _capture_sh()):
                assert not re.search(rf"\b{re.escape(word)}\b", text, re.I), "a word of the author's name"


def test_today_s_pictures_show_the_note_claude_wrote_for_the_day() -> None:
    """Today, Today in dark, Today on a phone and the tour's first view of Today show the secretary's note Claude
    wrote for the demo's day ("Written for today"), not the one written from the to-dos and dates, which a letter
    read before them would bring: ``capture.mjs`` waits for it on the page it is about to show, and stops when
    it isn't there."""
    capture = _capture_mjs()
    note = _function(capture, "claudesNote")
    assert '"Your secretary\'s note"' in note and '"Written for today"' in note
    assert "throw new Error(" in note  # a missing note stops the capture
    shots = _function(capture, "screenshots")
    for name in ("today", "today-dark", "mobile"):
        call = re.search(rf'await shot\((\w+), "{name}"\)', shots)
        assert call, name
        before = shots[: call.start()]
        checked = before.rfind(f"await claudesNote({call.group(1)})")
        assert checked >= 0, name
        # nothing opens another page between the check and the picture
        assert ".goto(" not in before[checked:] and ".reload(" not in before[checked:], name
    # the tour: on Today, before its first caption, and never on Today again: once it has read the tax assessment,
    # Today shows the note written from the to-dos (the video ended on it, review of D5)
    tour = _function(capture, "tour")
    today = tour.index("await page.goto(`${BASE}/`)")
    assert "await claudesNote(page)" in tour[today : tour.index("await caption(page, ", today)]
    assert tour.count("`${BASE}/`") == 1
    assert not re.search(r'\bnav\(page, "Today"', tour)


def test_the_tour_s_clock_is_the_video_s() -> None:
    """A recording's clock starts with its first frame, which comes when the tab first paints a page, not when the
    tab opens. The tour paints one before it starts its own clock, so the seconds it writes for ``make capture``
    (where the video starts, where the GIF ends, the page loads to cut) are the video's. Otherwise each cut comes
    late by the time the first page took to paint: the start of every page load stays in the video, and the GIF
    can end on a blank page."""
    tour = _function(_capture_mjs(), "tour")
    painted = tour.index("await page.setContent(")
    started = tour.index("const started = Date.now();")
    assert painted < started < tour.index("await page.goto(")


def test_a_page_load_is_cut_from_the_video_whole() -> None:
    """A full page load (the app's start screen, then the page) is cut from the video from a still moment before
    it to the page's own heading: not the start screen's (its ``main`` is busy while the app starts, with a heading
    for screen readers only) and not a letter page's stand-in heading while the letter loads (``data-loading``).
    Otherwise the video shows the start screen after each cut, and the GIF, which ends where the next load
    starts, can end on a blank page."""
    capture = _capture_mjs()
    shown = _function(capture, "shown")
    assert 'main:not([aria-busy="true"])' in shown and "h1:not([data-loading])" in shown
    tour = _function(capture, "tour")
    for name in ("reload", "load"):
        start = tour.index(f"const {name} = async (")
        body = tour[start : tour.index("\n  };\n", start)]
        held = body.index("const from = seconds();")
        goto = body.index("await page.goto(url);")
        assert held < body.index("await page.waitForTimeout(HOLD);") < goto, name
        # the cut ends once the page has drawn and its data came, not when its heading is first there
        drawn = body.index("await ready()" if name == "reload" else "await shown(page);")
        assert drawn < body.index("await settle(page, ") < body.index("gaps.push("), name
    assert re.search(r"^const HOLD = [1-9]\d{2};", capture, re.M)  # a moment, in milliseconds


def test_the_guard_sees_a_path_cut_off_at_the_window_s_edge() -> None:
    """A path on screen is often drawn in pieces (a command wraps at each "/") and cut off by the window's edge, so
    the whole path is never there to find. The guard also looks for the start of every path of this computer it
    knows (its first folder: "/home/", "/tmp/", "C:\\Users\\"), wherever the rest is."""
    capture = _capture_mjs()
    roots = _function(_capture_guard(), "pathRoots")
    for source in ("homedir()", "tmpdir()"):
        assert source in roots, source
    (known,) = re.findall(r"^const ROOTS = pathRoots\((.*)\);$", capture, re.M)
    for source in ("REPO", "opts.data", "OUT"):
        assert source in known, source
    context = _function(capture, "newContext")
    assert "addInitScript(guardPage, { forbidden: FORBIDDEN, roots: ROOTS," in context
    guard = _function(capture, "guardPage")
    assert guard.startswith("function guardPage({ forbidden, roots, theme })")
    assert ".includes(root)" in guard


def test_the_tour_keeps_the_trace_export_command_below_the_fold() -> None:
    """How it was read ends with the command that exports a reading, which names the demo's data folder (a path of
    this computer). The tour scrolls "Dates computed" low enough on screen before it clicks it that the command
    stays below the window's edge, before and after the step opens."""
    tour = _function(_capture_mjs(), "tour")
    trace = tour[tour.index('mark("how it was read")') : tour.index('mark("the end")')]
    dates = 'const dates = steps.getByRole("button", { name: /^Dates computed/ }).first();'
    assert dates in trace
    lowered = re.search(r"await scrollTo\(page, dates, (0\.\d+)\);", trace)
    assert lowered and float(lowered.group(1)) >= 0.55, "Dates computed is low enough on screen"
    assert trace.index(lowered.group(0)) < trace.index("await click(page, dates);")


def test_the_pictures_of_the_real_app_show_nothing_of_this_computer() -> None:
    """The two pictures from the real app (pairing a phone, Your computers) are checked for what the demo's pictures
    are: no path of the capturing computer or its start, not its name, not the git e-mail, no word of the author's
    name and none of CAPTURE_FORBIDDEN's (``capture-guard.mjs``, shared with ``capture.mjs``; it only checked the
    home folder and the computer's name, review of D5). The spec checks the text of every part it puts in a picture
    (the pairing dialog before and after the phone pairs, the phone's page, the Your computers page as the picture
    shows it), never repeating what it looks for."""
    spec = PICTURES_SPEC.read_text(encoding="utf-8")
    assert 'import { forbiddenWords, leaks, pathRoots } from "../scripts/capture-guard.mjs";' in spec
    start = spec.index("function nothingOfThisComputer(")
    guard = spec[start : spec.index("\n}\n", start)]
    assert "forbiddenWords(" in guard and "pathRoots(" in guard and "leaks(text, " in guard
    assert "homedir()" not in guard and "hostname()" not in guard  # the shared list has them
    assert ".not.toContain(" not in guard  # a failed check says what it found, not the word itself
    words = _function(_capture_guard(), "forbiddenWords")
    assert "length >= 4" in words  # a short computer name would match ordinary words
    # CAPTURE_FORBIDDEN reaches the pictures' run: capture.sh exports it and never takes it away
    script = _code(_capture_sh())
    assert re.search(r"^export CAPTURE_FORBIDDEN=", script, re.M)
    assert "CAPTURE_FORBIDDEN" not in _pictures_command(script)
    start = spec.index('test("pair-phone.png')
    pair = spec[start : spec.index("\n});\n", start)]
    # each part of the picture, by the text checked and the screenshot it becomes
    parts = {
        '(await dialog.innerText(), "the dialog': "codePart",
        '(await mobile.locator("body").innerText(), "the phone': "phonePart",
        '(await dialog.innerText(), "the paired dialog': "pairedPart",
    }
    for text, part in parts.items():
        check = f"nothingOfThisComputer{text}"
        assert check in pair, part
        # checked right before its screenshot is taken
        assert pair.index(check) < pair.index(f"path: {part}"), part
    # Your computers: checked as the picture shows it, once the throwaway folder's path has made way for a typical one
    computers = spec[spec.index('test("your-computers.png') :]
    replaced = computers.index("code.textContent = to")
    picture = computers.index(
        'const picture = (await b.locator("body").innerText()).replaceAll(SHOWN_FOLDER, "");'
    )
    checked = computers.index('nothingOfThisComputer(picture, "Your computers")')
    assert replaced < picture < checked < computers.index("b.screenshot(")


def _guard_in_node(tmp_path: Path, forbidden: str, texts: list[str]) -> dict[str, object]:
    """What ``capture-guard.mjs`` finds in a checkout at ``tmp_path`` whose author is "Jo Bergmann", with
    CAPTURE_FORBIDDEN set to ``forbidden``: its words (word and what it is) and what each of ``texts`` leaks."""
    repo = tmp_path / "checkout"
    repo.mkdir()
    (repo / "pyproject.toml").write_text(
        '[project]\nauthors = [{ name = "Jo Bergmann" }]\n', encoding="utf-8"
    )
    script = (
        f"import {{ forbiddenWords, leaks, pathRoots }} from {json.dumps(CAPTURE_GUARD.as_uri())};\n"
        "const [repo, texts] = [process.argv[1], JSON.parse(process.argv[2])];\n"
        'const words = forbiddenWords(repo, [[`${repo}-data`, "the run\'s data folder"]]);\n'
        "const roots = pathRoots([repo]);\n"
        "console.log(JSON.stringify({ words: words.map((w) => [w.text, w.what]), "
        "leaks: texts.map((t) => leaks(t, words, roots)) }));\n"
    )
    run = subprocess.run(
        ["node", "--input-type=module", "-e", script, str(repo), json.dumps(texts)],
        capture_output=True,
        text=True,
        env={**os.environ, "CAPTURE_FORBIDDEN": forbidden},
        check=False,
    )
    assert run.returncode == 0, run.stderr
    found: dict[str, object] = json.loads(run.stdout)
    return found


@_needs_node
def test_a_word_you_name_is_looked_for_however_short(tmp_path: Path) -> None:
    """CAPTURE_FORBIDDEN's words are the owner's own (a short surname, initials): each is looked for, however short
    (two letters were dropped without a word, review of D5). The author's name in pyproject.toml is split into
    words, and only those keep the three-letter floor ("Jo" would match too much). A word is found on its own,
    never inside a longer one, and the start of a path of this computer wherever it is."""
    found = _guard_in_node(
        tmp_path,
        "Li, Wu ,,",
        ["Frau Li schreibt", "Lieferung an Wuppertal", "Bergmann", "Jo", f"{tmp_path}/x", "nothing"],
    )
    words = {text: what for text, what in found["words"]}  # type: ignore[attr-defined]
    assert words["Li"] == words["Wu"] == "a word of CAPTURE_FORBIDDEN"
    assert words["Bergmann"] == "a word of the author's name"
    assert "Jo" not in words and "" not in words
    assert words[f"{tmp_path / 'checkout'}-data"] == "the run's data folder"
    assert found["leaks"] == [
        ["a word of CAPTURE_FORBIDDEN"],
        [],
        ["a word of the author's name"],
        [],
        ["the start of a path of this computer"],
        [],
    ]


def test_a_stopped_tour_leaves_no_recording_with_the_pictures() -> None:
    """The video records into a temporary folder of its own, never into ``<out>`` (``docs/assets``): when the guard
    stops the tour, the recording up to then, with the page it stopped on, is deleted with that folder, and only a
    clean tour's ``demo.webm`` and ``cut`` reach ``<out>/video``. A stopped run left it in ``docs/assets/video``,
    where ``git add`` would have found it (review of D5). ``capture.sh`` removes ``$OUT/video`` too when the run
    fails, and git ignores that folder."""
    record = _function(_capture_mjs(), "recordVideo")
    assert "const recording = mkdtempSync(join(tmpdir(), " in record
    assert "recordVideo: { dir: recording, size }" in record
    assert "dir: dir" not in record and "recordVideo: { dir," not in record
    # whatever happens, the temporary folder goes
    cleanup = record.index("rmSync(recording, { recursive: true, force: true })")
    assert record.rindex("} finally {", 0, cleanup) > record.index("const recording = ")
    # <out>/video only after the tour ran clean
    clean = record.index("cut = await tour(page);")
    assert clean < record.index("mkdirSync(dir, { recursive: true })")
    assert clean < record.index('join(dir, "demo.webm")')
    script = _code(_capture_sh())
    (trap,) = re.findall(r"^trap '(.*)' EXIT$", script, re.M)
    assert 'kill "$SERVER"' in trap and 'rm -rf "$OUT/video"' in trap
    assert '[ "$status" = 0 ] || rm -rf "$OUT/video"' in trap  # a clean run removes it itself
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "/docs/assets/video/" in gitignore


def test_the_review_folder_is_refused_under_docs_also_through_a_symlink(tmp_path: Path) -> None:
    """``CAPTURE_REVIEW`` under ``docs/`` is refused before anything starts, also when the checkout is opened through
    a symlink: the review folder is a physical path (``realpath``), so the checkout's must be too (review of D5: the
    logical one let ``docs/review`` through)."""
    real = tmp_path / "real"
    (real / "scripts").mkdir(parents=True)
    (real / "docs").mkdir()
    shutil.copy2(CAPTURE_SH, real / "scripts" / "capture.sh")
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    env = {
        **os.environ,
        "CAPTURE_REVIEW": "docs/review",
        "CAPTURE_DATA": str(tmp_path / "data" / "ordnung-capture"),
        "CAPTURE_OUT": str(tmp_path / "out"),
    }
    run = subprocess.run(
        ["bash", str(link / "scripts" / "capture.sh")],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert run.returncode == 1, run.stderr
    assert "CAPTURE_REVIEW is under docs/" in run.stderr
    assert not (real / "docs" / "review").exists()


def test_the_frame_check_measures_brightness_from_0_to_255(tmp_path: Path) -> None:
    """ffmpeg measures an H.264 frame's luma on the video range, 16 black to 235 white. The frame check maps it to
    0–255 before it compares and says it, so its 150 is :data:`LIGHT`, the pictures' measure (review of D5: a white
    frame read 235, a frame of 32 read 43)."""
    script = _capture_sh()
    (program,) = re.findall(r"awk -v min=150 '(.*?)'\)", script, re.S)
    metadata = "".join(
        f"frame:{i}    pts:{i}       pts_time:{i / 2:g}\nlavfi.signalstats.YAVG={luma}\n"
        for i, luma in enumerate(("235.000000", "145.000000", "60.000000", "16.000000"))
    )
    run = subprocess.run(
        ["awk", "-v", "min=150", program], input=metadata, capture_output=True, text=True, check=False
    )
    assert run.returncode == 0, run.stderr
    # 145 on the video range is 150 from 0 to 255: light; 60 is 51
    assert run.stdout.strip() == (
        "A frame of demo.mp4 is dark (mean brightness 51 at 1.0 s): the tour must stay in the light theme."
    )


def test_the_tour_cuts_the_letter_as_it_was_while_being_read() -> None:
    """Once the tax assessment is read, the app opens it by itself and draws it first as it was while being read
    (its file name, "Reading your letter", "Not sent to Claude"), under the caption that says Claude reads it. The
    tour cuts that from the video: from a moment before the letter's page opens until its own title, as read, is
    its heading (review of D5)."""
    tour = _function(_capture_mjs(), "tour")
    arrives = tour[tour.index('mark("a letter arrives")') : tour.index('mark("the letter")')]
    clicked = arrives.index('getByRole("button", { name: "Let Ordnung read it" })')
    opened = arrives.index("await page.waitForURL(/\\/documents\\/doc_/")
    titled = arrives.index("await (await titleOf(page, taxId)).waitFor(")
    cut = arrives.index("gaps.push([opening, seconds()]);")
    assert clicked < opened < titled < cut
    assert re.search(r"const opening = seconds\(\) - 0\.\d+;", arrives)
    title = _function(_capture_mjs(), "titleOf")
    assert 'getByRole("heading", { level: 1, name: shownAs(' in title


# --------------------------------------------------------------------------------------------------
# What it made
# --------------------------------------------------------------------------------------------------


def test_docs_assets_holds_the_readme_media_only() -> None:
    """``docs/assets`` holds README's pictures, the benchmark chart, the video, its GIF and the logo, and nothing else:
    no folder (a stopped capture's ``video``) and no recording."""
    entries = {path.name: path for path in ASSETS.iterdir()}
    assert not [name for name, path in entries.items() if path.is_dir()]
    assert set(entries) == set(PICTURES) | {EVAL_CHART} | OTHER_MEDIA, set(entries) ^ (
        set(PICTURES) | {EVAL_CHART} | OTHER_MEDIA
    )


def test_the_readme_pictures_are_small_and_in_their_theme() -> None:
    """Every picture in ``docs/assets`` is one ``make capture`` makes, or the benchmark chart; each is within its
    budget and has its size, and is light, except the two dark on purpose."""
    found = {path.name for path in ASSETS.glob("*.png")}
    assert found == set(PICTURES) | {EVAL_CHART}, found ^ (set(PICTURES) | {EVAL_CHART})
    assert (ASSETS / EVAL_CHART).stat().st_size <= PNG_BYTES
    for name, size in PICTURES.items():
        path = ASSETS / name
        assert path.stat().st_size <= PNG_BYTES, name
        info = png_info(path)
        if size is None:
            assert info.width <= WHY_WIDTH_MAX, name
        else:
            assert (info.width, info.height) == size, name
        if name in DARK_PICTURES:
            assert info.mean_luma <= DARK, (name, info.mean_luma)
        else:
            assert info.mean_luma >= LIGHT, (name, info.mean_luma)


def test_no_picture_or_video_carries_a_path() -> None:
    """No media file holds a path of the computer that made it (a file name in its metadata, say)."""
    media = [path for path in ASSETS.iterdir() if path.suffix in {".png", ".gif", ".mp4", ".svg"}]
    assert {path.name for path in media} >= {"demo.gif", "demo.mp4", "logo.svg", *PICTURES}
    for path in media:
        data = path.read_bytes()
        for mark in PATH_MARKS:
            assert mark not in data, (path.name, mark)


def test_the_demo_gif_is_what_make_capture_makes() -> None:
    """README's GIF: 720 px wide, 6 frames a second, at most 64 colours, every frame light, the first part of the
    tour (up to the court order) and within its budget."""
    path = ASSETS / "demo.gif"
    assert path.stat().st_size <= GIF_BYTES
    gif = gif_info(path)
    assert gif.width == 720
    assert abs(gif.frames / gif.seconds - 6) <= 0.2, gif
    assert gif.colours <= 64
    assert gif.darkest >= LIGHT
    assert gif.seconds <= GIF_SECONDS_MAX


def test_the_tour_video_starts_at_once_and_fits_its_budget() -> None:
    path = ASSETS / "demo.mp4"
    assert path.stat().st_size <= MP4_BYTES
    video = mp4_info(path)
    assert video.faststart
    assert video.seconds <= MP4_SECONDS_MAX


def test_the_readme_media_fit_their_budget() -> None:
    total = sum(path.stat().st_size for path in ASSETS.rglob("*") if path.is_file())
    assert total <= ASSETS_BYTES, total
