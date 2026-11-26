#!/usr/bin/env bash
# Screenshots for the README and the guide (two from the real app), the demo video, its animation and GIF
# (`make capture`).
# Needs the Python venv, the web app's node_modules and ffmpeg. PW_CHROMIUM_PATH selects a Chromium.
# The court payment order comes from the app's mock mode (see web/scripts/capture.mjs): a build of its own with the
# mock world (VITE_MOCKS=1; the released build has none), under `vite preview` on CAPTURE_MOCK_PORT, removed at the end.
# Pairing a phone and Your computers come from the real app (see web/e2e/readme-pictures.spec.ts).
# The media are public and stay in the history: sharp, and within a budget each (tests/test_media_budget.py keeps
# them there), from replay only, every frame of the video light, and every page and picture checked for a path of this
# computer or a real name while it is captured (web/scripts/capture-guard.mjs). Look at the contact sheets and the
# pictures before you commit them.
set -euo pipefail
# the checkout's physical path, as realpath gives the folders below, also when it is opened through a symlink
cd -P "$(dirname "$0")/.."

PORT=${CAPTURE_PORT:-8797}
# the mock world's build (the court order): after the pictures' and the video's demos (PORT, PORT + 1)
MOCK_PORT=${CAPTURE_MOCK_PORT:-$((PORT + 2))}
# the pictures and the video each on a fresh demo of their own (the video's in "$DATA-video", on PORT + 1): both read
# letters and send a cancellation, so what one does would show in the other
DATA=${CAPTURE_DATA:-$(mktemp -d)/ordnung-capture}
OUT=$(realpath -m "${CAPTURE_OUT:-docs/assets}")
# Every picture and the video's frames at 2 device pixels to the CSS pixel (a 1440×900 window is a 2880×1800 picture),
# the frames as JPEG of quality 95 (web/scripts/capture.mjs reads both)
export CAPTURE_SCALE=${CAPTURE_SCALE:-2}
export CAPTURE_FRAME_QUALITY=${CAPTURE_FRAME_QUALITY:-95}
# the frames held into a video of this many frames a second, which everything below is made from
FPS=${CAPTURE_FPS:-30}
# the whole tour: H.264, 1920 px wide (the 2560 px frames scaled down), sharp text at full size
MP4_WIDTH=${CAPTURE_MP4_WIDTH:-1920}
MP4_CRF=${CAPTURE_MP4_CRF:-23}
# README's animation, the tour's first part: an animated WebP, and a GIF for a reader whose browser shows no WebP
WEBP_WIDTH=${CAPTURE_WEBP_WIDTH:-1280}
WEBP_FPS=${CAPTURE_WEBP_FPS:-15}
WEBP_QUALITY=${CAPTURE_WEBP_QUALITY:-78}
GIF_WIDTH=${CAPTURE_GIF_WIDTH:-880}
GIF_FPS=${CAPTURE_GIF_FPS:-8}
GIF_COLOURS=${CAPTURE_GIF_COLOURS:-128}
# the contact sheets of the video, the WebP and the GIF, and a copy of the pictures, to look at before committing them
REVIEW=$(realpath -m "${CAPTURE_REVIEW:-$(mktemp -d)/ordnung-capture-review}")
case "$REVIEW/" in
  "$PWD/docs/"*)
    echo "CAPTURE_REVIEW is under docs/: the contact sheets are for looking at, not for committing." >&2
    exit 1
    ;;
esac
# words no page or picture may show besides the ones web/scripts/capture-guard.mjs finds itself (comma-separated,
# e.g. a name, each however short)
export CAPTURE_FORBIDDEN=${CAPTURE_FORBIDDEN:-}

# --only shots or --only video makes one of the two (CONTRIBUTING.md)
ONLY=
for arg in "$@"; do
  case "$arg" in
    --only=*) ONLY=${arg#--only=} ;;
    shots | video) [ "${prev:-}" = --only ] && ONLY=$arg ;;
  esac
  prev=$arg
done
rm -rf "$DATA" "$DATA-video"
mkdir -p "$(dirname "$DATA")" "$OUT" "$REVIEW"
rm -f "$REVIEW"/video-sheet-*.png "$REVIEW"/webp-sheet-*.png "$REVIEW"/gif-sheet-*.png "$REVIEW"/capture-error.png
# No model and no words read from pictures, for everything started here: the demo replays its recordings, and the
# `claude` any server would run is tests/fake_claude.py on a scenario that fails and logs every call (a call fails
# the run, below); ORDNUNG_OCR=off keeps a Tesseract installed on this computer out of the demo (ADR 0024)
CLAUDE_LOG="$DATA-claude-calls.jsonl"
SCENARIO="$DATA-claude.json"
.venv/bin/python -c 'import json, sys; print(json.dumps({"log": sys.argv[1], "calls": [{"exit": 1, "stderr": "make capture asks no model"}]}))' \
  "$CLAUDE_LOG" > "$SCENARIO"
: > "$CLAUDE_LOG"
export ORDNUNG_CLAUDE_BIN="$PWD/tests/fake_claude.py" FAKE_CLAUDE_SCENARIO="$SCENARIO" ORDNUNG_OCR=off
export CAPTURE_REVIEW="$REVIEW"
SERVER=
MOCK_SERVER=
MOCK_TMP=$(mktemp -d)
MOCK_DIR=$MOCK_TMP/ordnung-capture-mock
# a run that fails leaves no recording in $OUT, and no half-made video (a clean one removes it itself, once the
# MP4, the WebP and the GIF are made and moved to $OUT); the mock world's build and its server go either way
trap 'status=$?; kill "$SERVER" "$MOCK_SERVER" 2>/dev/null || true; rm -rf "$MOCK_TMP"; [ "$status" = 0 ] || rm -rf "$OUT/video"' EXIT
# the court order's page: the web app built with its mock world into a folder of its own (never the committed build)
(cd web && VITE_MOCKS=1 node node_modules/vite/bin/vite.js build --outDir "$MOCK_DIR" --emptyOutDir >"$MOCK_TMP/build.log" 2>&1) || {
  tail -20 "$MOCK_TMP/build.log" >&2
  echo "The mock world's build failed." >&2
  exit 1
}
# Vite itself, not npx, so the PID kept is the server's
(cd web && exec node node_modules/vite/bin/vite.js preview --outDir "$MOCK_DIR" --host 127.0.0.1 --port "$MOCK_PORT" --strictPort) >"$MOCK_TMP/preview.log" 2>&1 &
MOCK_SERVER=$!
for _ in $(seq 120); do
  curl -sf "http://127.0.0.1:$MOCK_PORT/" >/dev/null && break
  sleep 0.5
done
# capture <shots|video> <data folder> <port>: a fresh demo in the data folder, captured, then stopped
capture() {
  .venv/bin/ordnung demo --serve --no-browser --reset --port "$3" --data-dir "$2" >"$2.log" 2>&1 &
  SERVER=$!
  for _ in $(seq 120); do
    curl -sf "http://127.0.0.1:$3/api/health" >/dev/null && break
    sleep 0.5
  done
  (cd web && node scripts/capture.mjs --only "$1" --data "$2" --port "$3" --mock-port "$MOCK_PORT" --out "$OUT")
  kill "$SERVER" 2>/dev/null || true
  wait "$SERVER" 2>/dev/null || true
}
[ "$ONLY" = video ] || capture shots "$DATA" "$PORT"
[ "$ONLY" = shots ] || capture video "$DATA-video" "$((PORT + 1))"

if [ -f "$OUT/video/frames.txt" ]; then
  # the tour's frames as a video of FPS frames a second, each frame held until the next one (the page draws a frame
  # only when something on it changes), losslessly, on the video's clock capture.mjs wrote into frames.txt: from Today,
  # each still page held for its planned time, each motion as long as it took, page loads and readings left out.
  # Then the whole tour as an H.264 MP4, and README's loop (its first part, up to the date's receipt: the seconds in
  # video/cut) as the WebP and the GIF. All three are made in video/ and moved to $OUT together once each is made and
  # checked: a step that fails leaves the media of the run before
  ffmpeg -v error -y -f concat -safe 0 -i "$OUT/video/frames.txt" -vf "fps=$FPS" \
    -c:v libx264 -qp 0 -preset ultrafast -pix_fmt yuv444p "$OUT/video/tour.mkv"
  read -r LOOP_END < "$OUT/video/cut"
  LOOP_SECONDS=${CAPTURE_LOOP_SECONDS:-$LOOP_END}
  ffmpeg -v error -y -i "$OUT/video/tour.mkv" -vf "scale=$MP4_WIDTH:-2:flags=lanczos" \
    -c:v libx264 -pix_fmt yuv420p -crf "$MP4_CRF" -preset slow -movflags +faststart "$OUT/video/demo.mp4"
  # every frame light, two a second (the mean brightness of each, 0 black to 255 white, as tests/test_media_budget.py
  # measures the pictures; ffmpeg gives a video's luma from 16 black to 235 white, mapped here): the tour never shows
  # the dark theme
  DARK=$(ffmpeg -v error -i "$OUT/video/demo.mp4" -vf "fps=2,signalstats,metadata=mode=print:key=lavfi.signalstats.YAVG:file=-" -f null - |
    awk -v min=150 '/pts_time:/ { t = substr($0, index($0, "pts_time:") + 9) + 0 }
      /lavfi.signalstats.YAVG=/ { y = (substr($0, index($0, "=") + 1) - 16) * 255 / 219
        if (y < min && !dark) { printf "A frame of demo.mp4 is dark (mean brightness %.0f at %.1f s): the tour must stay in the light theme.\n", y, t; dark = 1 } }')
  if [ -n "$DARK" ]; then
    echo "$DARK" >&2
    exit 1
  fi
  # the WebP and the GIF from the lossless video, not from the MP4: its compression would only add noise to them
  ffmpeg -v error -y -i "$OUT/video/tour.mkv" -t "$LOOP_SECONDS" \
    -vf "fps=$WEBP_FPS,scale=$WEBP_WIDTH:-2:flags=lanczos" \
    -c:v libwebp_anim -lossless 0 -quality "$WEBP_QUALITY" -compression_level 6 -loop 0 "$OUT/video/demo.webp"
  ffmpeg -v error -y -i "$OUT/video/tour.mkv" -t "$LOOP_SECONDS" -vf \
    "fps=$GIF_FPS,scale=$GIF_WIDTH:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=$GIF_COLOURS:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle" \
    "$OUT/video/demo.gif"
  mv "$OUT/video/demo.mp4" "$OUT/video/demo.webp" "$OUT/video/demo.gif" "$OUT"/
  rm -rf "$OUT/video"
  # contact sheets as README shows them, each frame 880 px wide, six to a sheet (two across, three down): the video
  # a frame a second, the GIF and the WebP two a second
  ffmpeg -v error -y -i "$OUT/demo.mp4" -vf "fps=1,scale=880:-2:flags=lanczos,tile=2x3" "$REVIEW/video-sheet-%02d.png"
  ffmpeg -v error -y -i "$OUT/demo.gif" -vf "fps=2,scale=880:-2:flags=lanczos,tile=2x3" "$REVIEW/gif-sheet-%02d.png"
  # ffmpeg reads no animated WebP: Pillow does
  .venv/bin/python - "$OUT/demo.webp" "$REVIEW/webp-sheet-%02d.png" <<'SHEET'
import sys
from PIL import Image, ImageSequence

path, sheets = sys.argv[1], sys.argv[2]
with Image.open(path) as webp:
    width = 880
    height = round(webp.height * width / webp.width)
    shown, at, step = [], 0, 0
    for frame in ImageSequence.Iterator(webp):
        frame.load()  # a frame's duration is known once it is read
        at += frame.info["duration"]
        while step * 500 < at:  # the frame on screen every half second
            shown.append(frame.convert("RGB").resize((width, height), Image.Resampling.LANCZOS))
            step += 1
for n in range(0, len(shown), 6):
    sheet = Image.new("RGB", (2 * width, 3 * height), "white")
    for i, frame in enumerate(shown[n : n + 6]):
        sheet.paste(frame, ((i % 2) * width, (i // 2) * height))
    sheet.save(sheets % (n // 6 + 1))
SHEET
fi
# Phone access and hand-off sync, which the demo never offers: two pictures from the real app, on the e2e suite's
# own servers, started here (never a running Ordnung) on ports 8807-8810 with throwaway data folders in a new
# temporary folder (web/e2e/readme-pictures.spec.ts). CAPTURE_REAL=0 leaves them out; CAPTURE_REAL_PORT moves them.
# Its real apps run the fake `claude` of their own (the spec counts its calls) and never read pictures.
if [ "${CAPTURE_REAL:-1}" != 0 ]; then
  (cd web && env -u ORDNUNG_E2E_REUSE -u ORDNUNG_E2E_OCR ORDNUNG_CAPTURE_OUT="$OUT" ORDNUNG_E2E_DATA="$(mktemp -d)/ordnung" \
    ORDNUNG_E2E_PORT="${CAPTURE_REAL_PORT:-$((PORT + 10))}" npx playwright test --project pictures)
fi
ls -la "$OUT"
if [ -s "$CLAUDE_LOG" ]; then
  CALLS=$(wc -l < "$CLAUDE_LOG" | tr -d ' ')
  echo "make capture asked a model ($CALLS calls): see $CLAUDE_LOG" >&2
  exit 1
fi
cp "$OUT"/*.png "$REVIEW"/ 2>/dev/null || true
echo "Look at every picture and every sheet in $REVIEW before you commit them: light theme (today-dark.png and mobile-dark.png are dark on purpose), no path of this computer's, no real names."
