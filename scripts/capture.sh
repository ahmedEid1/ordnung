#!/usr/bin/env bash
# README screenshots and the demo video, captured from a fresh demo (`make capture`).
# Needs the Python venv, the web app's node_modules and ffmpeg. PW_CHROMIUM_PATH selects a Chromium.
# The court payment order comes from the app's mock mode (see web/scripts/capture.mjs).
# Pairing a phone and Your computers come from the real app (see web/e2e/readme-pictures.spec.ts).
# The media are public and stay in the history: small by design (tests/test_media_budget.py keeps them in
# budget), from replay only, every frame of the video light, and every page and picture checked for a path of this
# computer or a real name while it is captured (web/scripts/capture-guard.mjs). Look at the contact sheets and the
# pictures before you commit them.
set -euo pipefail
# the checkout's physical path, as realpath gives the folders below, also when it is opened through a symlink
cd -P "$(dirname "$0")/.."

PORT=${CAPTURE_PORT:-8797}
DATA=${CAPTURE_DATA:-$(mktemp -d)/ordnung-capture}
OUT=$(realpath -m "${CAPTURE_OUT:-docs/assets}")
GIF_WIDTH=${CAPTURE_GIF_WIDTH:-720}
GIF_FPS=${CAPTURE_GIF_FPS:-6}
GIF_COLOURS=${CAPTURE_GIF_COLOURS:-64}
MP4_CRF=${CAPTURE_MP4_CRF:-32}
# the contact sheets of the video and the GIF, and a copy of the pictures, to look at before committing them
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

rm -rf "$DATA"
mkdir -p "$(dirname "$DATA")" "$OUT" "$REVIEW"
rm -f "$REVIEW"/video-sheet-*.png "$REVIEW"/gif-sheet-*.png "$REVIEW"/capture-error.png
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
.venv/bin/ordnung demo --serve --no-browser --reset --port "$PORT" --data-dir "$DATA" >"$DATA.log" 2>&1 &
SERVER=$!
# a run that fails leaves no recording in $OUT (a clean one removes it itself, once the MP4 is made)
trap 'status=$?; kill "$SERVER" 2>/dev/null || true; [ "$status" = 0 ] || rm -rf "$OUT/video"' EXIT
for _ in $(seq 120); do
  curl -sf "http://127.0.0.1:$PORT/api/health" >/dev/null && break
  sleep 0.5
done

(cd web && node scripts/capture.mjs --data "$DATA" --port "$PORT" --out "$OUT" "$@")

if [ -f "$OUT/video/demo.webm" ]; then
  # the whole tour as H.264 MP4, and its first part (up to the court order) as the README's GIF, both from
  # when Today is on screen, without the full page loads (e.g. between the demo and mock mode). The tour writes
  # the seconds to video/cut: start, GIF end, then pairs of from–to to leave out
  read -r START GIF_END GAPS < "$OUT/video/cut" || { START=0; GIF_END=41; GAPS=""; }
  # the gaps as a frame filter over the seconds after START, and how much of them lies before the GIF's end
  read -r KEEP BEFORE_GIF < <(awk -v s="$START" -v g="$GIF_END" -v gaps="$GAPS" 'BEGIN {
    n = split(gaps, t, " "); expr = ""; cut = 0
    for (i = 1; i < n; i += 2) {
      a = t[i] - s; b = t[i + 1] - s
      expr = expr (expr == "" ? "" : "+") sprintf("between(t,%.2f,%.2f)", a, b)
      if (t[i + 1] <= g) cut += t[i + 1] - t[i]
    }
    printf "%s %.2f\n", (expr == "" ? "1" : "not(" expr ")"), cut
  }')
  GIF_SECONDS=${CAPTURE_GIF_SECONDS:-$(awk -v a="$START" -v b="$GIF_END" -v c="$BEFORE_GIF" 'BEGIN { printf "%.2f", b - a - c }')}
  ffmpeg -v error -y -ss "$START" -i "$OUT/video/demo.webm" -vf "fps=25,select='$KEEP',setpts=N/(25*TB)" \
    -c:v libx264 -pix_fmt yuv420p -crf "$MP4_CRF" -preset slow -movflags +faststart "$OUT/demo.mp4"
  rm -rf "$OUT/video"
  # every frame light, two a second (the mean brightness of each, 0 black to 255 white, as tests/test_media_budget.py
  # measures the pictures; ffmpeg gives a video's luma from 16 black to 235 white, mapped here): the tour never shows
  # the dark theme
  DARK=$(ffmpeg -v error -i "$OUT/demo.mp4" -vf "fps=2,signalstats,metadata=mode=print:key=lavfi.signalstats.YAVG:file=-" -f null - |
    awk -v min=150 '/pts_time:/ { t = substr($0, index($0, "pts_time:") + 9) + 0 }
      /lavfi.signalstats.YAVG=/ { y = (substr($0, index($0, "=") + 1) - 16) * 255 / 219
        if (y < min && !dark) { printf "A frame of demo.mp4 is dark (mean brightness %.0f at %.1f s): the tour must stay in the light theme.\n", y, t; dark = 1 } }')
  if [ -n "$DARK" ]; then
    echo "$DARK" >&2
    exit 1
  fi
  # contact sheets: the video a frame a second, twelve to a sheet
  ffmpeg -v error -y -i "$OUT/demo.mp4" -vf "fps=1,scale=480:-1,tile=4x3" "$REVIEW/video-sheet-%02d.png"
  # the GIF from the MP4: the recording's VP8 noise would make it half as large again, for no visible gain
  ffmpeg -v error -y -t "$GIF_SECONDS" -i "$OUT/demo.mp4" -vf \
    "fps=$GIF_FPS,scale=$GIF_WIDTH:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=$GIF_COLOURS:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle" \
    "$OUT/demo.gif"
  # the GIF's sheets at its own size, a frame a second, nine to a sheet: its colours as README shows them
  ffmpeg -v error -y -i "$OUT/demo.gif" -vf "fps=1,tile=3x3" "$REVIEW/gif-sheet-%02d.png"
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
