"""README's media are sharp, light and come from replay only: ``make capture`` (``scripts/capture.sh``,
``web/scripts/capture.mjs``) records the tour video, its animation (a WebP and a GIF) and the pictures at twice the
pixels of their window, with settings that keep each within its budget, asks no model, reads no words in pictures, checks every frame and every page for the theme, a path of the
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
from evals.present import PRESENTATION_PATH
from evals.present.charts import COMMITTED, committed

from helpers_media import gif_info, mp4_info, png_info, webp_info

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "docs" / "assets"
CAPTURE_SH = ROOT / "scripts" / "capture.sh"
CAPTURE_MJS = ROOT / "web" / "scripts" / "capture.mjs"
#: what no picture may show, shared by ``capture.mjs`` and the real app's pictures
CAPTURE_GUARD = ROOT / "web" / "scripts" / "capture-guard.mjs"
PICTURES_SPEC = ROOT / "web" / "e2e" / "readme-pictures.spec.ts"

# Each budget is what ``make capture`` made when the media were last redone, with about a quarter more for a page
# that shows more (measured then, over three runs: the GIF 2.1 to 2.2 MB, the WebP 2.1 to 2.3 MB, the MP4 6.2 to
# 6.8 MB; the largest picture 1.7 MB and all of ``docs/assets`` 22.2 MB).
#: README's fallback GIF for a browser without WebP: 880×660, 8 frames a second, 128 colours, 2.2 MB
GIF_BYTES = 2_750_000
#: README's animation, 1280×960 at 15 frames a second, 2.1 MB
WEBP_BYTES = 2_750_000
#: the whole tour at 1920×1440: about 0.6 Mbit/s for sharp text, 6.6 MB
MP4_BYTES = 8_500_000
#: each picture's budget: a page at 2880×1800 with a photographed letter on it is the largest
PNG_BYTES = 2_200_000
#: everything in ``docs/assets``
ASSETS_BYTES = 28_000_000
#: README's loop (the WebP and the GIF), from Today to the date's receipt: 29.4 s, the same from run to run since a
#: still page is held for its planned time and a motion for the time the browser gave it, whatever the computer's
#: load. A visitor gives it about half a minute: a beat added to it must make room, not stretch it
LOOP_SECONDS = (20, 30)
#: the whole tour (the MP4): 88.3 s; a visitor who clicks gives it about a minute and a half
TOUR_SECONDS = (70, 95)
#: mean luma (0 black, 255 white): a picture in the light theme is at least this bright, one in the dark theme at
#: most :data:`DARK`
LIGHT = 150
DARK = 100

#: a 1440×900 window at 2 device pixels to the CSS pixel
DESKTOP = (2880, 1800)
#: The pictures ``make capture`` makes, with their size in pixels (``why.png`` is the receipt dialog alone: only
#: its width is fixed, by the dialog). A phone's are its 390×844 window at 2, as before.
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
    "ask.png": (2880, 3400),
    "mobile.png": (780, 1688),
    "mobile-dark.png": (780, 1688),
    "why.png": None,
}
#: the dialog at 2 (770 px when the media were last redone), with about a quarter more
WHY_WIDTH_MAX = 960
#: dark on purpose: README shows the dark theme once on a computer and once on a phone
DARK_PICTURES = frozenset({"today-dark.png", "mobile-dark.png"})


def eval_charts(presentation: Path = PRESENTATION_PATH) -> frozenset[str]:
    """The evaluation's charts ``presentation.json`` commits to ``docs/assets``, light and dark (``charts.committed``):
    today's, and the final run's beside them once it is published."""
    doc = json.loads(presentation.read_text(encoding="utf-8"))
    return frozenset(f"eval-{name}-{theme}.svg" for name in committed(doc) for theme in ("light", "dark"))


#: the evaluation's charts (``python -m evals.present`` writes them, not ``make capture``; tests/test_present.py
#: checks they are what the results files render): hand-written SVG, light and dark, each within its budget; the
#: ones ``presentation.json`` commits, so the final run's join them once it is published
EVAL_CHARTS = eval_charts()
EVAL_CHART_BYTES = 40_000
#: what a path of the capturing computer starts with, in any file's bytes
PATH_MARKS = (b"/home/", b"/Users/", b"/root/", b"/tmp/", b"\\Users\\")
#: everything else ``docs/assets`` holds: the README's video, its WebP and GIF, and the logo
OTHER_MEDIA = frozenset({"demo.webp", "demo.gif", "demo.mp4", "logo.svg"})

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


def _js_code(script: str) -> str:
    """JavaScript without its whole-line comments, so a check never passes on a comment."""
    return "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("//"))


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


def test_make_capture_draws_everything_at_scale_2_with_frames_of_jpeg_quality_95() -> None:
    """Every picture and the video's frames are drawn at 2 device pixels to the CSS pixel (CAPTURE_SCALE): a 1440×900
    window is a 2880×1800 picture, sharp on a high-density screen (at 1 it looked soft). The real app's two pictures
    take the same scale, and the video's frames are JPEG of quality 95 (CAPTURE_FRAME_QUALITY)."""
    script = _code(_capture_sh())
    for default in (
        "export CAPTURE_SCALE=${CAPTURE_SCALE:-2}",
        "export CAPTURE_FRAME_QUALITY=${CAPTURE_FRAME_QUALITY:-95}",
    ):
        assert re.search(rf"^{re.escape(default)}$", script, re.M), default
    capture = _capture_mjs()
    assert 'const SCALE = setting("CAPTURE_SCALE", 2, ' in capture
    assert 'const FRAME_QUALITY = setting("CAPTURE_FRAME_QUALITY", 95, ' in capture
    assert "viewport: DESKTOP, deviceScaleFactor: SCALE," in _function(capture, "newContext")
    assert "deviceScaleFactor: 1" not in capture
    spec = PICTURES_SPEC.read_text(encoding="utf-8")
    assert "const SCALE = Number(process.env.CAPTURE_SCALE || 2);" in spec
    assert "test.use({ deviceScaleFactor: SCALE });" in spec
    assert "deviceScaleFactor: 1" not in spec


def test_the_video_s_frames_are_device_pixels_of_a_1280_by_960_window() -> None:
    """The tour is recorded as the page's own frames (``page.screencast``) at 2560×1920, twice its 1280×960 window
    (CAPTURE_VIDEO_WIDTH, CAPTURE_VIDEO_HEIGHT): 1280 is the narrowest window in which a letter's page puts the
    photographed letter beside its explanation (narrower, the photo goes under it and out of the frame), and 960 high
    holds a letter's title, what to do and its whole deadline card above the caption band. A screencast gives device
    pixels only when the browser itself draws at that scale: with the context's ``deviceScaleFactor`` alone every
    frame came as CSS pixels. So the video's browser is started at the scale, and a frame of any other size stops the
    capture."""
    capture = _capture_mjs()
    assert 'width: setting("CAPTURE_VIDEO_WIDTH", 1280, { min: 1024, ' in capture
    assert 'height: setting("CAPTURE_VIDEO_HEIGHT", 960, ' in capture
    record = _function(capture, "recordVideo")
    assert "args: [`--force-device-scale-factor=${SCALE}`]" in record
    assert "newContext(browser, { viewport: VIDEO, deviceScaleFactor: SCALE })" in record
    assert "const size = { width: VIDEO.width * SCALE, height: VIDEO.height * SCALE };" in record
    assert "await page.screencast.start({\n      size,\n      quality: FRAME_QUALITY," in record
    assert "recordVideo:" not in _capture_mjs()  # Playwright's own recording: VP8 at about 1 Mbit/s
    checked = record.index("drawn.width !== size.width || drawn.height !== size.height")
    assert checked < record.index('writeFileSync(join(recording, "frames.txt")')


def test_make_capture_makes_a_1920_px_mp4_at_crf_23_a_1280_px_webp_and_an_880_px_gif_at_8_fps_with_128_colours() -> (
    None
):
    """From the frames held at 30 a second: the MP4 is H.264 (yuv420p) at CRF 23, scaled to 1920 px wide with lanczos,
    and starts playing at once (``+faststart``); README's WebP is 1280 px wide, 15 frames a second, lossy at quality
    78 and loops; the GIF is 880 px wide (README's width, which the loop's shorter length leaves room for), 8 frames a
    second and 128 colours. Each setting has its knob; the GIF's dither stays."""
    script = _code(_capture_sh())
    for default in (
        "FPS=${CAPTURE_FPS:-30}",
        "MP4_WIDTH=${CAPTURE_MP4_WIDTH:-1920}",
        "MP4_CRF=${CAPTURE_MP4_CRF:-23}",
        "WEBP_WIDTH=${CAPTURE_WEBP_WIDTH:-1280}",
        "WEBP_FPS=${CAPTURE_WEBP_FPS:-15}",
        "WEBP_QUALITY=${CAPTURE_WEBP_QUALITY:-78}",
        "GIF_WIDTH=${CAPTURE_GIF_WIDTH:-880}",
        "GIF_FPS=${CAPTURE_GIF_FPS:-8}",
        "GIF_COLOURS=${CAPTURE_GIF_COLOURS:-128}",
    ):
        assert re.search(rf"^{re.escape(default)}$", script, re.M), default
    held = script[script.index('-f concat -safe 0 -i "$OUT/video/frames.txt"') :].split("\n", 2)
    assert '-vf "fps=$FPS"' in held[0] and "-qp 0" in held[1]  # lossless: each output is made from it
    mp4 = script[script.index('"scale=$MP4_WIDTH:-2:flags=lanczos"') :].split("\n", 2)
    assert '-c:v libx264 -pix_fmt yuv420p -crf "$MP4_CRF"' in mp4[1] and "-movflags +faststart" in mp4[1]
    webp = script[script.index('"fps=$WEBP_FPS,scale=$WEBP_WIDTH:-2:flags=lanczos"') :].split("\n", 2)
    assert '-c:v libwebp_anim -lossless 0 -quality "$WEBP_QUALITY"' in webp[1] and "-loop 0" in webp[1]
    gif = script[script.index('"fps=$GIF_FPS,') :].split("\n", 1)[0]
    assert "scale=$GIF_WIDTH:-1" in gif
    # the WebP and the GIF are made from the lossless video, not from the MP4, whose compression would add its noise
    animations = re.findall(r'^  ffmpeg -v error -y -i "([^"]+)" -t "\$LOOP_SECONDS"', script, re.M)
    assert animations == ["$OUT/video/tour.mkv", "$OUT/video/tour.mkv"], animations
    assert "palettegen=max_colors=$GIF_COLOURS:stats_mode=diff" in gif
    assert "paletteuse=dither=bayer" in gif
    # the WebP and the GIF end where README's loop does (video/cut), unless CAPTURE_LOOP_SECONDS says otherwise
    assert script.count('-t "$LOOP_SECONDS"') == 2
    assert re.search(r'^  read -r LOOP_END < "\$OUT/video/cut"$', script, re.M)
    assert re.search(r"^  LOOP_SECONDS=\$\{CAPTURE_LOOP_SECONDS:-\$LOOP_END\}$", script, re.M)
    # made in video/ and moved out together once all three are made and checked: a failed step leaves the run before's
    moved = script.index('mv "$OUT/video/demo.mp4" "$OUT/video/demo.webp" "$OUT/video/demo.gif" "$OUT"/')
    assert script.index("signalstats") < moved and script.index("palettegen") < moved
    for name in ("demo.mp4", "demo.webp", "demo.gif"):
        assert f'"$OUT/{name}"' not in script[:moved], name
    assert "-crf 32" not in script and "demo.webm" not in script


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
    then draws contact sheets of the video, the WebP and the GIF into the review folder (never under ``docs/``) and ends by
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
    # what it found stops the run, before anything is moved out of video/
    stop = re.search(r'^  if \[ -n "\$DARK" \]; then\n(?:    .+\n)*?    exit 1\n  fi$', script, re.M)
    assert stop and stop.end() < script.index('mv "$OUT/video/demo.mp4"')
    sheets = re.findall(r'-vf "([^"]*tile=[^"]*)" "\$REVIEW/([\w-]+)-%02d\.png"', script)
    assert {name for _, name in sheets} == {"video-sheet", "gif-sheet"}, sheets
    # ffmpeg reads no animated WebP: Pillow draws its sheets
    assert '.venv/bin/python - "$OUT/demo.webp" "$REVIEW/webp-sheet-%02d.png"' in script
    # a dark frame stops the run before the WebP and the GIF are made
    assert script.index("signalstats") < script.index("libwebp_anim") < script.index("palettegen")
    # each is encoded into video/ and the three move out together once all are made: a run stopped halfway (a dark
    # frame, a failed encode) leaves the committed ones as they were, never a new MP4 beside an old GIF
    encodes = re.findall(r'"\$OUT/((?:[\w-]+/)?demo\.(?:mp4|webp|gif))"$', script, re.M)
    assert encodes == ["video/demo.mp4", "video/demo.webp", "video/demo.gif"], encodes
    move = script.index('mv "$OUT/video/demo.mp4" "$OUT/video/demo.webp" "$OUT/video/demo.gif" "$OUT"/')
    # (the EXIT trap names video/ first: it removes what a failed run made)
    assert script.index("palettegen") < move < script.rindex('rm -rf "$OUT/video"')
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
    shots = _function(capture, "todayShots")
    # before the other pictures, which read the tax assessment and the scam letter (the video has a demo of its own)
    order = re.findall(r"await (askShot|todayShots|recordVideo|screenshots)\(browser\)", capture)
    assert order == ["askShot", "todayShots", "screenshots"], order
    for name in ("today", "today-dark", "mobile"):
        call = re.search(rf'await shot\((\w+), "{name}"\)', shots)
        assert call, name
        before = shots[: call.start()]
        checked = before.rfind(f"await claudesNote({call.group(1)})")
        assert checked >= 0, name
        # nothing opens another page between the check and the picture
        assert ".goto(" not in before[checked:] and ".reload(" not in before[checked:], name
    # the tour: on Today, before its first caption, and never on Today again: once it has read the tax assessment,
    # Today shows the note written from the to-dos (the video ended on it)
    tour = _function(capture, "tour")
    today = tour.index("await page.goto(`${BASE}/`)")
    assert "await claudesNote(page)" in tour[today : tour.index("await caption(page, ", today)]
    assert tour.count("`${BASE}/`") == 1
    assert not re.search(r'\bnav\(page, "Today"', tour)


def test_the_tour_s_clock_is_the_video_s() -> None:
    """Each frame comes with the moment it was drawn, on the clock the tour reads (``Date.now()``), and the page draws
    one only when something on it changes. ``frames.txt`` holds each frame on the video's clock (``videoClock``): the
    tour keeps a list of what the video shows (``film``), and ``capture.sh`` turns it into a video of 30 frames a
    second, the whole of which is the MP4 and whose first seconds, up to where README's loop ends (``video/cut``), are
    the WebP and the GIF. The tour paints a page before its clock starts, so there is a frame on screen when the first
    moment it keeps begins."""
    capture = _capture_mjs()
    tour = _function(capture, "tour")
    reset = tour.index("film.length = 0;")
    painted = tour.index("await page.setContent(")
    started = tour.index("const started = Date.now();")
    assert reset < painted < started < tour.index("await page.goto(")
    assert "return { started, loopEnd };" in tour
    record = _function(capture, "recordVideo")
    assert "frames.push({ name, at: timestamp," in record
    assert "concatList(frames, film, stopped)" in record
    assert 'writeFileSync(join(recording, "cut"), `${loop.toFixed(2)}\\n`);' in record
    assert "const loop = clock(cut.loopEnd);" in record
    script = _code(_capture_sh())
    assert script.index('-i "$OUT/video/frames.txt" -vf "fps=$FPS"') < script.index('< "$OUT/video/cut"')
    # no frame filter cuts the video afterwards: frames.txt already left out what the video does not show
    assert "select=" not in script and "-ss " not in script


@_needs_node
def test_each_frame_is_held_on_the_video_s_clock() -> None:
    """``concatList`` (``capture.mjs``) holds each frame from the moment it was drawn until the next, on the video's
    clock: a hold (the page standing still under its caption) lasts exactly its planned time however long it really
    took, so the tour is as long on a busy computer as on a quiet one; a motion (the pointer, a scroll) keeps the
    time it took; what lies between them (a page load, the reading of a letter) is left out, and a frame drawn only
    there is not shown at all. The frame on screen when the first moment kept starts is the first, from 0.
    Now and then a frame came with a later moment than the next (the browser gave it none, and Playwright took the
    moment it arrived; 29 in one tour), which made a negative duration: such a frame is taken as drawn no later than
    the next, and left out when it is then on screen for no time."""
    capture = _capture_mjs()
    held = f"{_function(capture, 'videoClock')}\n}}\n{_function(capture, 'concatList')}\n}}\n"
    frames = [
        {"name": "a.jpg", "at": 900},  # before the first moment kept
        {"name": "b.jpg", "at": 950},  # on screen when it starts
        # halfway through the hold, which really took 1000 ms of its planned 2000
        {"name": "c.jpg", "at": 1500},
        {"name": "late.jpg", "at": 2300},  # came with the moment it arrived
        {"name": "d.jpg", "at": 2000},  # drawn as the hold ends, during what is left out (2000 to 3000)
        {"name": "e.jpg", "at": 2500},  # drawn and replaced while left out: never shown
        {"name": "f.jpg", "at": 2900},  # on screen when the motion (3000 to 3400, kept as it was) starts
        {"name": "g.jpg", "at": 3200},
    ]
    film = [{"from": 1000, "to": 2000, "ms": 2000}, {"from": 3000, "to": 3400}]
    script = f"{held}process.stdout.write(concatList({json.dumps(frames)}, {json.dumps(film)}, 3400));"
    run = subprocess.run(
        ["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=False
    )
    assert run.returncode == 0, run.stderr
    assert run.stdout.splitlines() == [
        "ffconcat version 1.0",
        "file 'b.jpg'",
        "duration 1.000",
        "file 'c.jpg'",
        "duration 1.000",
        "file 'f.jpg'",
        "duration 0.200",
        "file 'g.jpg'",
        "duration 0.200",
        "file 'g.jpg'",
    ]
    # no frame yet when the first moment kept started: the first is held from 0, so the next is still where the
    # video's clock puts it (2.0 s in), not 1.5 s early
    after = [{"name": "boot.jpg", "at": 1500}, {"name": "today.jpg", "at": 2000}]
    film = [{"from": 1000, "to": 4000, "ms": 3000}]
    script = f"{held}process.stdout.write(concatList({json.dumps(after)}, {json.dumps(film)}, 4000));"
    run = subprocess.run(
        ["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=False
    )
    assert run.returncode == 0, run.stderr
    assert run.stdout.splitlines()[1:] == [
        "file 'boot.jpg'",
        "duration 1.000",
        "file 'today.jpg'",
        "duration 2.000",
        "file 'today.jpg'",
    ]
    # and the tour's clock starts once the first page's frame has come, so that case is rare
    tour = _function(capture, "tour")
    assert (
        tour.index("setContent(") < tour.index("!frames.length") < tour.index("const started = Date.now();")
    )


def test_page_loads_and_readings_are_left_out_of_the_video() -> None:
    """The video keeps only the tour's holds and motions (``film``): a full page load (the app's start screen, the
    page's skeleton) happens between them and is left out whole, the caption cleared first so the page before never
    shows it over the next. A page counts as loaded once its own heading is on screen: not the start screen's (its
    ``main`` is busy while the app starts, with a heading for screen readers only) and not a letter page's stand-in
    heading while the letter loads (``data-loading``). A sidebar link's click is kept, and the page's loading after
    it is not: the press is held a quarter of a second, its ring spreading over the page before, and the click's
    motion ends where the app goes to the next page (``__navAt``, set when the app changes its address). The band is
    emptied before the press, so the caption before never stands over the next page."""
    capture = _capture_mjs()
    shown = _function(capture, "shown")
    assert 'main:not([aria-busy="true"])' in shown and "h1:not([data-loading])" in shown
    tour = _function(capture, "tour")
    start = tour.index("const load = async (")
    load = tour[start : tour.index("\n  };\n", start)]
    assert load.index('await caption(page, "");') < load.index("await page.goto(url);")
    assert "hold(" not in load and "motion(" not in load
    nav = _function(capture, "nav")
    # nothing after the app went to the next page is kept: its skeleton would show under the caption before
    assert "{ press: 200, after: 250, blank: true }" in nav
    assert 'if (blank) await caption(page, "");' in _function(capture, "click")
    # what is kept after a caption changes starts with a frame that shows it, not the caption before over a new page
    caption = _function(capture, "caption")
    assert (
        "!(recorded.at(-1)?.at >= drawn.at)" in caption
        and "captions.push({ text, at: drawn.at });" in caption
    )
    assert "recorded = frames;" in tour
    overlay = _function(capture, "overlay")
    assert (
        "History.prototype[name] = function (...args) {" in overlay and "window.__navAt = now();" in overlay
    )
    assert "window.__navAt > pressed ? Math.min(end, window.__navAt) : end" in overlay
    clicked = nav.index("await click(page, ")
    assert clicked < nav.index("await page.waitForURL(") < nav.index("await shown(page);")
    assert "hold(" not in nav[clicked + 1 :] and "motion(" not in nav[clicked + 1 :]
    assert "const HOLD" not in capture and "gaps" not in tour


def test_a_still_page_is_held_for_its_planned_time_and_motion_for_its_own() -> None:
    """``hold`` records the page standing still for its planned milliseconds, ``motion`` what moves for the time the
    browser gave it. The pointer glides, the page scrolls and a click's answer is kept for times the browser keeps
    (the overlay's ``__glide``, ``__scroll`` and ``__settled``, which say when the motion started and ended on the
    browser's clock), not for the time the capture took to ask for it and hear back: that grew on a busy computer
    (a quiet run was 0.9 s shorter than one under load). So the tour's length is the same from run to run, and
    README's "N min S s" stays true."""
    capture = _capture_mjs()
    assert "keep({ from, to: Date.now(), ms });" in _function(capture, "hold")
    motion = _function(capture, "motion")
    assert "keep({ from: moved.start, to: moved.end });" in motion and "Date.now()" not in motion
    assert "window.__glide(" in _function(capture, "glide")
    assert "window.__scroll(null, " in _function(capture, "scrollPage")
    clicked = _function(capture, "click")
    assert "window.__settled(ms)" in clicked and "waitForTimeout(" not in clicked
    overlay = _function(capture, "overlay")
    assert "window.__glide = (x, y) =>" in overlay and "window.__scroll = (el, dy, fixed) =>" in overlay
    assert "window.__settled = (after) =>" in overlay
    assert "const now = () => performance.timeOrigin + performance.now();" in overlay
    assert "window.__pressedAt = performance.timeOrigin + e.timeStamp;" in overlay
    assert "requestAnimationFrame(step)" in overlay
    # no motion waits in the capture's own time: what it waits for (a photo drawn, a box standing still) is left out
    for name in ("glide", "scrollPage", "click", "restWhile"):
        body = _function(capture, name)
        assert "still(" not in body and "waitForFunction(" not in body and "waitForTimeout(" not in body, name
    for name in ("pointAt", "click", "nav", "tour"):
        body = _function(capture, name)
        assert "steps: " not in body and "mouse.wheel(" not in body, name
    clock = _function(capture, "videoClock")
    assert "length: ms ?? to - from" in clock


def test_a_click_shows_and_the_caption_is_a_band_along_the_bottom() -> None:
    """A click shows (the pointer presses in and a ring spreads from it). The caption is a band flush with the bottom
    of the window across the main column (the sidebar stays whole), 56 px high, near-black with the caption in white,
    21 px semi-bold, on one line, with no rounded corners and no shadow: the page is cut by a straight edge, as by the
    window's own. It is always in the same place, there from the first frame to the last and empty between captions,
    so the page never jumps."""
    capture = _capture_mjs()
    overlay = _function(capture, "overlay")
    pressed = overlay[overlay.index('document.addEventListener(\n      "mousedown",') :]
    assert 'cursor.style.transform = "scale(.82)";' in pressed[:400] and "ring.animate(" in pressed[:1200]
    bar = overlay[overlay.index('bar.id = "cap-caption";') : overlay.index("document.body.appendChild(bar);")]
    for style in (
        "position:fixed;left:0;right:0;bottom:0;height:56px;",
        "background:#111418;",
        "color:#fff;",
    ):
        assert style in bar, style
    assert "font:600 21px/56px " in bar and "white-space:nowrap;" in bar
    assert "border-radius" not in bar and "box-shadow" not in bar and "opacity" not in bar
    # it starts where the sidebar (the app's aside along the window's left edge) ends
    assert 'document.querySelectorAll("aside")' in overlay and "bar.style.left = left;" in overlay
    assert "const BAND = 56;" in capture
    # one place for every caption: no side to put it on
    assert "window.__caption = (text) =>" in overlay
    assert '"left"' not in _function(capture, "tour") and "side" not in _function(capture, "caption")


def _captions(name: str) -> list[str]:
    """The captions of ``capture.mjs``'s ``LOOP`` or ``TOUR``, in their order."""
    found = re.search(rf"^const {name} = \[\n(.*?)\n\];$", _capture_mjs(), re.M | re.S)
    assert found, name
    return re.findall(r'^  "([^"]+)",$', found.group(1), re.M)


def test_readme_s_loop_is_the_tour_s_first_six_beats_with_by_when_fourth() -> None:
    """README's loop (the WebP and the GIF) is the tour's first six captions, in order: what Ordnung is, a letter
    arrives, Claude reads it, what it is, what to do and BY WHEN, the sentence the date came from, and why this date.
    The tour shows them in that order, ends the loop after the sixth (on the date's receipt), and only then goes on
    with the rest: so a later edit cannot quietly move "by when" out of the loop or the loop's end past it."""
    loop, rest = _captions("LOOP"), _captions("TOUR")
    assert len(loop) == 6, loop
    assert loop[0].startswith("Ordnung: ")
    assert "by when" in loop[3]
    assert loop[4] == "Every fact links to the sentence it came from."
    assert loop[5].startswith("Why this date?")
    assert not any("by when" in caption for caption in rest)
    assert rest[-1].endswith("Try it: ordnung demo")
    tour = _function(_capture_mjs(), "tour")
    used = re.findall(r"\b(LOOP|TOUR)\[(\d+)\]", tour)
    order = []
    for name, i in used:  # each caption where it is first shown
        if (name, int(i)) not in order:
            order.append((name, int(i)))
    assert order == [("LOOP", i) for i in range(6)] + [("TOUR", i) for i in range(len(rest))], order
    ended = tour.index("const loopEnd = Date.now();")
    assert tour.rindex("LOOP[5]", 0, ended) < ended < tour.index("TOUR[0]")
    # the loop ends on the receipt's steps, held long enough to read (3 s, in a loop under 30 s): its last step brought
    # above the caption, then nothing but a hold
    held = re.search(
        r"await rulesInView\(page, receipt, \d+\);\n  await hold\(page, (\d+)\);\n  const loopEnd",
        _js_code(tour),
    )
    assert held and int(held.group(1)) >= 3000
    assert "await restWhile(page, y, receipt);" in _function(_capture_mjs(), "rulesInView")
    scrolls = _function(_capture_mjs(), "restWhile")
    assert "box.scrollHeight - box.clientHeight - box.scrollTop" in scrolls and "motion(" in scrolls
    # opened from the deadline card itself, so the receipt opens beside the date while the photo stays on screen
    why = tour[tour.index("LOOP[5]") : tour.index("const loopEnd")]
    assert "await click(page, deadline, " in why


def test_the_deadline_card_stands_whole_above_the_caption() -> None:
    """When the caption says "by when", the letter's deadline card (the date, "in N weeks", "Why this date?") is whole
    on screen, below the sticky top bar and above the caption band, with nothing on it: ``deadlineInView`` scrolls it
    there before the caption comes, and stops the capture when the window is too short for it, and the pointer goes
    to its rest in the window's right margin."""
    capture = _capture_mjs()
    tour = _function(capture, "tour")
    by_when = tour.index("LOOP[3]")
    placed = tour.rindex("await deadlineInView(page, deadline);", 0, by_when)
    assert tour.index("await (await titleOf(page, taxId)).waitFor(") < placed < by_when
    assert "await rest(" in tour[placed:by_when] and "glide(" not in tour[placed:by_when]
    assert "const rest = (y) => glide(page, VIDEO.width - 20, y);" in tour
    # nothing scrolls or opens between it and the end of the beat: the next motion is the next beat's
    assert "scroll" not in tour[placed + 40 : tour.index("LOOP[4]")]
    check = _function(capture, "deadlineInView")
    assert "window.innerHeight - band" in check and "BAND" in check and "throw new Error(" in check


def test_the_pictures_and_the_video_each_have_a_fresh_demo_of_their_own() -> None:
    """The pictures and the video each read letters and send the phone contract's cancellation, so what one does would
    show in the other (a new tour once drew an Inbox badge on eight pictures). ``capture.sh`` starts a fresh demo
    (``--reset``) in a data folder of its own for each, one after the other, and ``capture.mjs`` makes only one of the
    two in a run: so a change of the tour never changes a picture, and what ``make capture`` makes is what is
    committed."""
    capture = _capture_mjs()
    assert 'if (opts.only !== "shots" && opts.only !== "video") {' in capture
    main = capture[capture.rindex("const browser = await chromium.launch(LAUNCH);") :]
    shots = main[main.index('if (opts.only === "shots") {') : main.index("} else {")]
    assert re.findall(r"await (\w+)\(", shots) == ["askShot", "todayShots", "screenshots"]
    assert re.search(r"\} else \{\n    await recordVideo\(\);\n  \}", main)
    # nothing to take back: the video's cancellation is on a demo of its own
    assert "withdrawCancellation" not in capture
    script = _code(_capture_sh())
    start = script.index("capture() {")
    serve = script[start : script.index("\n}\n", start)]
    assert '--reset --port "$3" --data-dir "$2"' in _demo_server(script) and _demo_server(script) in serve
    assert 'node scripts/capture.mjs --only "$1" --data "$2" --port "$3"' in serve
    assert serve.index("/ordnung demo ") < serve.index("capture.mjs") < serve.index('kill "$SERVER"')
    assert re.search(r'^\[ "\$ONLY" = video \] \|\| capture shots "\$DATA" "\$PORT"$', script, re.M)
    assert re.search(
        r'^\[ "\$ONLY" = shots \] \|\| capture video "\$DATA-video" "\$\(\(PORT \+ 1\)\)"$', script, re.M
    )
    assert 'rm -rf "$DATA" "$DATA-video"' in script


@_needs_node
def test_every_caption_stays_its_reading_time() -> None:
    """A caption stays on screen long enough to read twice at a calm pace, 2.5 s and 0.25 s a word, on the video's
    clock (``readingTimes``: until the next caption or the band emptied for a page load), and the capture stops when
    one is shown for less, so no take with a hurried caption is made."""
    capture = _capture_mjs()
    assert "const readingTime = (text) => 2500 + 250 * text.split(/\\s+/).length;" in capture
    record = _function(capture, "recordVideo")
    # the check is wired: a caption shown too briefly throws, and nothing in between turns it off
    assert re.search(
        r"const short = shown\.filter\(\(\{ text, seconds \}\) => seconds \* 1000 < readingTime\(text\)\);\n"
        r"    if \(short\.length\) \{\n      throw new Error\(`a caption is shown for less than its reading time",
        record,
    )
    held = f"{_function(capture, 'videoClock')}\n}}\n{_function(capture, 'readingTimes')}\n}}\n"
    # a 3 s hold that really took 1 s, a motion of 0.5 s, a load left out (6000 to 9000) and a 2 s hold
    film = [
        {"from": 1000, "to": 2000, "ms": 3000},
        {"from": 2000, "to": 2500},
        {"from": 9000, "to": 10000, "ms": 2000},
    ]
    captions = [
        {"text": "One two three four", "at": 1000},
        {"text": "", "at": 6000},
        {"text": "Five", "at": 8000},
    ]
    script = (
        f"{held}const clock = videoClock({json.dumps(film)});"
        f"process.stdout.write(JSON.stringify(readingTimes({json.dumps(captions)}, clock, 10000)));"
    )
    run = subprocess.run(
        ["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=False
    )
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout) == [
        {"text": "One two three four", "at": 0, "seconds": 3.5},
        {"text": "Five", "at": 3.5, "seconds": 2},
    ]


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
    trace = tour[tour.index('mark("14 how it was read")') : tour.index('mark("15 the end")')]
    dates = 'const dates = steps.getByRole("button", { name: /^Dates computed/ }).first();'
    assert dates in trace
    lowered = re.search(r"await scrollTo\(page, dates, (0\.\d+)\);", trace)
    assert lowered and float(lowered.group(1)) >= 0.55, "Dates computed is low enough on screen"
    assert trace.index(lowered.group(0)) < trace.index("await click(page, dates);")


def test_the_bill_s_pay_panel_opens_in_one_motion_without_the_window_scrolling() -> None:
    """The bill's Pay panel (about 770 CSS px high) opens above its button. With the button higher in the window there
    was no room for it, and the window jumped up and back while the panel placed itself. The tour brings the button
    low in the window first (just above the caption band), holds, and clicks it where it is: the panel opens where
    there is room, and its opening is kept until it stands still (700 ms from the press)."""
    tour = _function(_capture_mjs(), "tour")
    bill = _js_code(tour[tour.index('mark("8 ') : tour.index('mark("9 ')])
    placed = re.search(r"await scrollTo\(page, pay\(\), (0\.\d+)\);", bill)
    assert placed, "the Pay button is placed before it is clicked"
    assert 0.85 <= float(placed.group(1)) <= 0.9, "low enough for the panel above it, above the caption band"
    clicked = re.search(r"await click\(page, pay\(\), \{ after: (\d+), clear: BAND \+ 8 \}\);", bill)
    assert clicked, "the Pay click leaves the button where it is and keeps the panel's opening"
    assert int(clicked.group(1)) >= 700, "kept until the panel stands still"
    between = bill[placed.end() : clicked.start()]
    assert "await hold(page, " in between
    assert "scroll" not in between and "glide(" not in between and "rest(" not in between
    point = _function(_capture_mjs(), "pointAt")
    assert "clear = 110" in point and "r.bottom < window.innerHeight - below" in point


def test_the_court_order_s_free_help_stands_above_the_caption_band() -> None:
    """The court order ends on its advice card: its title ("act within two weeks") near the top and under it the free
    help, whose first entry stands whole above the caption band. The tour scrolls to the title, then stops the
    capture when that entry ends lower than the window's height less the band, and only then holds the beat's end."""
    tour = _function(_capture_mjs(), "tour")
    court = _js_code(tour[tour.index('mark("13 ') : tour.index('mark("14 ')])
    scroll = 'await scrollTo(page, page.getByRole("heading", { name: /act within two weeks/ }).first(), '
    assert scroll in court, "the advice card's title is what the tour scrolls to"
    helps = 'page.getByRole("heading", { name: "Free or low-cost help" })'
    assert helps in court, "the free help is looked up under its heading"
    check = re.search(r"getBoundingClientRect\(\)\.bottom <= window\.innerHeight - band\b", court)
    stop = 'throw new Error("the court order\'s first free help is not above the caption band");'
    assert check and stop in court, "the capture stops when the free help is under the band"
    assert "BAND" in court[check.end() : court.index(stop)]
    last_hold = court.rindex("await hold(page, ")
    assert court.index(scroll) < court.index(helps) < check.start() < court.index(stop) < last_hold
    assert "scroll" not in court[court.index(stop) :], "nothing moves the page after the check"


def test_the_pictures_of_the_real_app_show_nothing_of_this_computer() -> None:
    """The two pictures from the real app (pairing a phone, Your computers) are checked for what the demo's pictures
    are: no path of the capturing computer or its start, not its name, not the git e-mail, no word of the author's
    name and none of CAPTURE_FORBIDDEN's (``capture-guard.mjs``, shared with ``capture.mjs``; it only checked the
    home folder and the computer's name). The spec checks the text of every part it puts in a picture
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
    (two letters were dropped without a word). The author's name in pyproject.toml is split into
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
    """The video's frames go into a temporary folder of their own, never into ``<out>`` (``docs/assets``): when the
    guard stops the tour, the frames up to then, with the page it stopped on, are deleted with that folder, and only a
    clean tour's frames, ``frames.txt`` and ``cut`` reach ``<out>/video``. A stopped run left it in ``docs/assets/video``,
    where ``git add`` would have found it. ``capture.sh`` removes ``$OUT/video`` too when the run
    fails, and git ignores that folder."""
    record = _function(_capture_mjs(), "recordVideo")
    assert "const recording = mkdtempSync(join(tmpdir(), " in record
    assert "writeFileSync(join(recording, name), data);" in record
    assert "join(dir, name)" not in record
    # whatever happens, the temporary folder goes
    cleanup = record.index("rmSync(recording, { recursive: true, force: true })")
    assert record.rindex("} finally {", 0, cleanup) > record.index("const recording = ")
    # <out>/video only after the tour ran clean
    clean = record.index("cut = await tour(page, frames);")
    assert clean < record.index("renameSync(recording, dir);")
    assert clean < record.index("cpSync(recording, dir, { recursive: true });")
    script = _code(_capture_sh())
    (trap,) = re.findall(r"^trap '(.*)' EXIT$", script, re.M)
    assert 'kill "$SERVER"' in trap and 'rm -rf "$OUT/video"' in trap
    assert '[ "$status" = 0 ] || rm -rf "$OUT/video"' in trap  # a clean run removes it itself
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "/docs/assets/video/" in gitignore


def test_the_review_folder_is_refused_under_docs_also_through_a_symlink(tmp_path: Path) -> None:
    """``CAPTURE_REVIEW`` under ``docs/`` is refused before anything starts, also when the checkout is opened through
    a symlink: the review folder is a physical path (``realpath``), so the checkout's must be too (the
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
    0–255 before it compares and says it, so its 150 is :data:`LIGHT`, the pictures' measure (a white
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
    (its file name, "Reading your letter", "Not sent to Claude"). The video keeps the click, then nothing until the
    letter's own title, as read, is its heading: the reading is left out whole."""
    tour = _function(_capture_mjs(), "tour")
    arrives = tour[tour.index('mark("3 ') : tour.index('mark("4 ')]
    clicked = arrives.index("await page.mouse.click(")
    opened = arrives.index("await page.waitForURL(/\\/documents\\/doc_/")
    titled = arrives.index("await (await titleOf(page, taxId)).waitFor(")
    kept = arrives.index("await hold(page, ", titled)
    assert clicked < opened < titled < kept
    assert "hold(" not in arrives[opened:titled] and "motion(" not in arrives[opened:titled]
    title = _function(_capture_mjs(), "titleOf")
    assert 'getByRole("heading", { level: 1, name: shownAs(' in title


# --------------------------------------------------------------------------------------------------
# What it made
# --------------------------------------------------------------------------------------------------


def test_docs_assets_holds_the_readme_media_only() -> None:
    """``docs/assets`` holds README's pictures, the benchmark chart, the video, its WebP and GIF and the logo, and nothing else:
    no folder (a stopped capture's ``video``) and no recording."""
    entries = {path.name: path for path in ASSETS.iterdir()}
    assert not [name for name, path in entries.items() if path.is_dir()]
    assert set(entries) == set(PICTURES) | EVAL_CHARTS | OTHER_MEDIA, set(entries) ^ (
        set(PICTURES) | EVAL_CHARTS | OTHER_MEDIA
    )


def test_the_readme_pictures_are_2880_by_1800_within_budget_and_in_their_theme() -> None:
    """Every picture in ``docs/assets`` is one ``make capture`` makes, or an evaluation chart; each is within its
    budget and has its size (a desktop's 2880×1800, Ask's 2880×3400, a phone's 780×1688), and is light, except the
    two dark on purpose."""
    found = {path.name for path in ASSETS.glob("*.png")}
    assert found == set(PICTURES), found ^ set(PICTURES)
    for name in EVAL_CHARTS:
        assert (ASSETS / name).stat().st_size <= EVAL_CHART_BYTES, name
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
    media = [path for path in ASSETS.iterdir() if path.suffix in {".png", ".gif", ".webp", ".mp4", ".svg"}]
    assert {path.name for path in media} >= {"demo.gif", "demo.webp", "demo.mp4", "logo.svg", *PICTURES}
    for path in media:
        data = path.read_bytes()
        for mark in PATH_MARKS:
            assert mark not in data, (path.name, mark)


def _within(seconds: float, limits: tuple[int, int]) -> bool:
    low, high = limits
    return low <= seconds <= high


def test_the_demo_webp_is_1280_by_960_at_15_fps_looping_and_within_budget() -> None:
    """README's animation: an animated WebP of 1280×960 (the 1280×960 window's frames scaled down), README's loop (the
    tour's first six beats, from Today to the date's receipt), 20 to 30 s, as long as the GIF, looping, and within its
    budget. libwebp shows a frame that doesn't change for longer instead of again, so it has at most 15 frames a
    second, not exactly 15. Its frames are the MP4's, which ``make capture`` checked for a dark one."""
    path = ASSETS / "demo.webp"
    assert path.stat().st_size <= WEBP_BYTES
    webp = webp_info(path)
    assert (webp.width, webp.height) == (1280, 960)
    assert webp.loops == 0  # for ever
    assert webp.frames / webp.seconds <= 15.2, webp
    assert _within(webp.seconds, LOOP_SECONDS), webp
    assert abs(webp.seconds - gif_info(ASSETS / "demo.gif").seconds) <= 0.5


def test_the_demo_gif_is_880_px_at_8_fps_with_at_most_128_colours() -> None:
    """README's fallback GIF: 880×660 (README's width), 8 frames a second, at most 128 colours, every frame light,
    README's loop (20 to 30 s) and within its budget."""
    path = ASSETS / "demo.gif"
    assert path.stat().st_size <= GIF_BYTES
    gif = gif_info(path)
    assert (gif.width, gif.height) == (880, 660)
    assert abs(gif.frames / gif.seconds - 8) <= 0.2, gif
    assert gif.colours <= 128
    assert gif.darkest >= LIGHT
    assert _within(gif.seconds, LOOP_SECONDS), gif


def test_the_tour_video_is_1920_by_1440_starts_at_once_and_fits_its_budget() -> None:
    """The whole tour: 1920×1440 (the 1280×960 window's frames scaled down), 70 to 95 s, starts playing at once and
    is within its budget."""
    path = ASSETS / "demo.mp4"
    assert path.stat().st_size <= MP4_BYTES
    video = mp4_info(path)
    assert video.faststart
    assert (video.width, video.height) == (1920, 1440)
    assert _within(video.seconds, TOUR_SECONDS), video


def test_the_length_limits_hold_the_loop_under_30_s_and_the_tour_under_95_s() -> None:
    """The limits themselves: a loop of 30.5 s or a tour of 95.5 s fails, as one of 19 s or 69 s does."""
    assert _within(29.4, LOOP_SECONDS) and _within(88.3, TOUR_SECONDS)
    for seconds in (19.0, 30.5):
        assert not _within(seconds, LOOP_SECONDS), seconds
    for seconds in (69.0, 95.5):
        assert not _within(seconds, TOUR_SECONDS), seconds


def test_the_readme_media_fit_their_budget() -> None:
    total = sum(path.stat().st_size for path in ASSETS.rglob("*") if path.is_file())
    assert total <= ASSETS_BYTES, total


def test_the_evaluation_charts_are_the_ones_presentation_json_commits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The evaluation's charts in ``docs/assets`` are the ones ``presentation.json`` commits: today's while there is
    no final run, and the final run's beside them once it is published (the published one in this checkout once the
    publish PR is merged, and a synthetic one, in a temporary folder, over the results with no final run)."""
    from evals.present import final as final_sentences
    from evals.present import model

    import helpers_final
    from helpers_publication import final_published, results_before_publication

    def charts(*names: str) -> set[str]:
        return {f"eval-{name}-{theme}.svg" for name in names for theme in ("light", "dark")}

    today = charts(*COMMITTED)
    published: set[str] = set()
    if final_published():
        # the published final run's: its headline and differences, and the stability over its reads (two or more)
        found = final_sentences.published(ROOT)
        assert found is not None
        stability = ("final-stability",) if found[0]["primary"]["reads"] >= 2 else ()
        published = charts("final", "final-differences", *stability)
        monkeypatch.setattr(helpers_final, "RESULTS", results_before_publication(tmp_path / "results-before"))
    assert eval_charts() == EVAL_CHARTS == today | published
    root = helpers_final.scenario_root(tmp_path, "one_read")
    presentation = tmp_path / "presentation.json"
    presentation.write_text(model.dumps(model.build(root / "evals" / "results")), encoding="utf-8")
    assert eval_charts(presentation) == today | charts("final", "final-differences")
