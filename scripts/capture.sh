#!/usr/bin/env bash
# README screenshots and the demo video, captured from a fresh demo (`make capture`).
# Needs the Python venv, the web app's node_modules and ffmpeg. PW_CHROMIUM_PATH selects a Chromium.
# The court payment order comes from the app's mock mode (see web/scripts/capture.mjs).
# Pairing a phone and Your computers come from the real app (see web/e2e/readme-pictures.spec.ts).
set -euo pipefail
cd "$(dirname "$0")/.."

PORT=${CAPTURE_PORT:-8797}
DATA=${CAPTURE_DATA:-$(mktemp -d)/ordnung-capture}
OUT=$(realpath -m "${CAPTURE_OUT:-docs/assets}")
GIF_WIDTH=${CAPTURE_GIF_WIDTH:-820}
GIF_FPS=${CAPTURE_GIF_FPS:-8}

rm -rf "$DATA"
mkdir -p "$(dirname "$DATA")" "$OUT"
.venv/bin/ordnung demo --serve --no-browser --reset --port "$PORT" --data-dir "$DATA" >"$DATA.log" 2>&1 &
SERVER=$!
trap 'kill "$SERVER" 2>/dev/null || true' EXIT
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
    -c:v libx264 -pix_fmt yuv420p -crf 30 -preset slow -movflags +faststart "$OUT/demo.mp4"
  # the GIF from the MP4: the recording's VP8 noise would make it half as large again, for no visible gain
  ffmpeg -v error -y -t "$GIF_SECONDS" -i "$OUT/demo.mp4" -vf \
    "fps=$GIF_FPS,scale=$GIF_WIDTH:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=96:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle" \
    "$OUT/demo.gif"
  rm -rf "$OUT/video"
fi
# Phone access and hand-off sync, which the demo never offers: two pictures from the real app, on the e2e suite's
# own servers, started here (never a running Ordnung) on ports 8807-8810 with throwaway data folders in a new
# temporary folder (web/e2e/readme-pictures.spec.ts). CAPTURE_REAL=0 leaves them out; CAPTURE_REAL_PORT moves them.
if [ "${CAPTURE_REAL:-1}" != 0 ]; then
  (cd web && env -u ORDNUNG_E2E_REUSE ORDNUNG_CAPTURE_OUT="$OUT" ORDNUNG_E2E_DATA="$(mktemp -d)/ordnung" \
    ORDNUNG_E2E_PORT="${CAPTURE_REAL_PORT:-$((PORT + 10))}" npx playwright test --project pictures)
fi
ls -la "$OUT"
