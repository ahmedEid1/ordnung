#!/usr/bin/env bash
# README screenshots and the demo video, captured from a fresh demo (`make capture`).
# Needs the Python venv, the web app's node_modules and ffmpeg. PW_CHROMIUM_PATH selects a Chromium.
set -euo pipefail
cd "$(dirname "$0")/.."

PORT=${CAPTURE_PORT:-8797}
DATA=${CAPTURE_DATA:-$(mktemp -d)/ordnung-capture}
OUT=$(realpath -m "${CAPTURE_OUT:-docs/assets}")
GIF_SECONDS=${CAPTURE_GIF_SECONDS:-38}
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
  # the full tour as H.264 MP4, and the first part as a GIF for the README
  ffmpeg -v error -y -i "$OUT/video/demo.webm" -c:v libx264 -pix_fmt yuv420p -crf 27 -preset slow \
    -movflags +faststart "$OUT/demo.mp4"
  ffmpeg -v error -y -t "$GIF_SECONDS" -i "$OUT/video/demo.webm" -vf \
    "fps=$GIF_FPS,scale=$GIF_WIDTH:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=96:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle" \
    "$OUT/demo.gif"
  rm -rf "$OUT/video"
fi
ls -la "$OUT"
