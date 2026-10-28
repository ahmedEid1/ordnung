"""The photo the end-to-end tests keep private (``web/e2e/fixtures/private-photo.jpg``, for
``web/e2e/real-app-pictures.spec.ts`` and ADR 0024): a fictional printed letter that
``scripts/make_photo_fixture.py`` draws, committed without metadata."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "make_photo_fixture.py"
FIXTURE = ROOT / "web" / "e2e" / "fixtures" / "private-photo.jpg"


def test_the_e2e_photo_is_what_the_script_draws() -> None:
    """Pixels, not bytes: JPEG encoders differ, so the committed photo is compared with the drawing."""
    out = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)},
        check=False,
    )
    assert out.returncode == 0, out.stdout + out.stderr
    assert "is current" in out.stdout
    with Image.open(FIXTURE) as photo:
        # a photo of a page, small enough for the repository, with no camera, place or date in it
        assert (photo.format, photo.size) == ("JPEG", (1200, 1600))
        assert not photo.getexif()
        assert not {"exif", "icc_profile", "xmp", "comment"} & set(photo.info)
    assert FIXTURE.stat().st_size < 200_000


def test_the_check_refuses_a_photo_that_isnt_the_drawing(tmp_path: Path) -> None:
    sys.path.insert(0, str(SCRIPT.parent))
    try:
        import make_photo_fixture as script
    finally:
        sys.path.remove(str(SCRIPT.parent))
    assert script.differs(tmp_path / "missing.jpg") == "missing.jpg is missing"
    blank = tmp_path / "blank.jpg"
    Image.new("RGB", script.SIZE, "white").save(blank, "JPEG")
    assert "isn't what the script draws" in (script.differs(blank) or "")
    small = tmp_path / "small.jpg"
    script.draw().resize((600, 800)).save(small, "JPEG")
    assert script.differs(small) == "small.jpg is 600 × 800 px, not 1200 × 1600"
    tagged = tmp_path / "tagged.jpg"
    exif = Image.Exif()
    exif[0x010F] = "A camera"
    script.draw().save(tagged, "JPEG", quality=script.QUALITY, exif=exif.tobytes())
    assert script.differs(tagged) == "tagged.jpg carries EXIF metadata"
    # what this computer's Pillow writes passes, whatever its bytes
    fresh = tmp_path / "fresh.jpg"
    fresh.write_bytes(script.photo_bytes())
    assert script.differs(fresh) is None


def test_the_photo_has_the_word_the_spec_searches_for() -> None:
    """The spec searches for "Kellerabteil": a word with no umlaut, in no other letter of the real app."""
    sys.path.insert(0, str(SCRIPT.parent))
    try:
        import make_photo_fixture as script
    finally:
        sys.path.remove(str(SCRIPT.parent))
    assert "Ihr Kellerabteil 7" in script.LINES
    spec = (ROOT / "web" / "e2e" / "real-app-pictures.spec.ts").read_text(encoding="utf-8")
    assert 'const WORD = "Kellerabteil";' in spec
