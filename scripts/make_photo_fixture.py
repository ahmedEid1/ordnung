"""Draw ``web/e2e/fixtures/private-photo.jpg``: a fictional printed letter on white, for the end-to-end test of
the words Ordnung reads in a private photo with Tesseract (``web/e2e/real-app-pictures.spec.ts``, ADR 0024).

Every name, address and number in it is invented. It is drawn with Pillow and the DejaVu Sans font that ships
with Ordnung (``src/ordnung/drafts/fonts``), large and clean, so Tesseract reads its words the same way on every
computer; the spec searches for "Kellerabteil", a word with no umlaut that no other letter of the real app has.
The JPEG carries no metadata (no camera, no place, no date).

JPEG encoders differ, so the same drawing can give other bytes elsewhere: ``--check`` and
``tests/test_photo_fixture.py`` compare the pixels with what this script draws, not the bytes.

Run it from the repository root::

    python scripts/make_photo_fixture.py            # write the fixture
    python scripts/make_photo_fixture.py --check    # exit 1 if the committed photo isn't what it draws
"""

from __future__ import annotations

import argparse
import io
from collections.abc import Sequence
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "web" / "e2e" / "fixtures" / "private-photo.jpg"
FONT = ROOT / "src" / "ordnung" / "drafts" / "fonts" / "DejaVuSans.ttf"

#: The photo's size in pixels: a phone photo of a page, made smaller.
SIZE = (1200, 1600)
#: The letter's lines, top to bottom (fictional): the sender, the subject the spec searches for, the request.
LINES = (
    "Hausverwaltung Beispiel GmbH",
    "Musterweg 5, 12345 Musterstadt",
    "",
    "Ihr Kellerabteil 7",
    "",
    "Bitte räumen Sie Ihr Kellerabteil",
    "bis zum 30.11.2026.",
    "",
    "Mit freundlichen Grüßen",
    "Ihre Hausverwaltung",
)
#: JPEG quality: small enough for the repository, clean enough to read.
QUALITY = 85
#: How far the committed photo may stray from the drawing: the mean difference (0-255) of its grey pixels, and the
#: share of pixels that differ by more than a quarter of the scale (a JPEG decoder's rounding never does).
MAX_MEAN_DIFFERENCE = 2.0
MAX_FAR_PIXELS = 0.002


def draw() -> Image.Image:
    """The photo as this script draws it: black lines on white paper."""
    image = Image.new("RGB", SIZE, "white")
    pen = ImageDraw.Draw(image)
    heading = ImageFont.truetype(str(FONT), 64)
    body = ImageFont.truetype(str(FONT), 54)
    y = 140
    for row, text in enumerate(LINES):
        if text:
            pen.text((110, y), text, font=heading if row == 3 else body, fill="black")
        y += 96 if text else 60
    return image


def photo_bytes() -> bytes:
    """The fixture's bytes as this computer's Pillow encodes the drawing (no metadata)."""
    buffer = io.BytesIO()
    draw().save(buffer, "JPEG", quality=QUALITY, optimize=True)
    return buffer.getvalue()


def differs(path: Path = FIXTURE) -> str | None:
    """Why the photo at ``path`` isn't what :func:`draw` draws, or ``None`` when it is (pixels, not bytes)."""
    if not path.is_file():
        return f"{path.name} is missing"
    with Image.open(path) as committed:
        if committed.format != "JPEG":
            return f"{path.name} is a {committed.format}, not a JPEG"
        if committed.size != SIZE:
            return f"{path.name} is {committed.size[0]} × {committed.size[1]} px, not {SIZE[0]} × {SIZE[1]}"
        if committed.getexif():
            return f"{path.name} carries EXIF metadata"
        grey = committed.convert("L")
    difference = ImageChops.difference(draw().convert("L"), grey)
    histogram = difference.histogram()
    pixels = SIZE[0] * SIZE[1]
    mean = sum(value * count for value, count in enumerate(histogram)) / pixels
    far = sum(histogram[64:]) / pixels
    if mean > MAX_MEAN_DIFFERENCE or far > MAX_FAR_PIXELS:
        return f"{path.name} isn't what the script draws (mean difference {mean:.2f}, {far:.2%} of pixels far off)"
    return None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument(
        "--check", action="store_true", help="exit 1 if the committed photo isn't what it draws"
    )
    args = parser.parse_args(argv)
    shown = FIXTURE.relative_to(ROOT)
    if args.check:
        why = differs()
        if why:
            print(f"{shown} is out of date: {why}; run python scripts/make_photo_fixture.py")
            return 1
        print(f"{shown} is current")
        return 0
    data = photo_bytes()
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_bytes(data)
    print(f"wrote {shown} ({len(data)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
