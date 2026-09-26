"""The data page of Sam Rivera's (fictional) Republic of Examplia passport, drawn with Pillow.

It carries a visible ``SPECIMEN`` overprint like real specimen passports, a stylised silhouette instead
of a face, and a machine-readable zone with correct ICAO 9303 check digits.
"""

from __future__ import annotations

import math
import random

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from samplelife.ids import mrz_check_digit
from samplelife.letter import FONT_DIR, scribble_strokes

PX_PER_MM = 12
PAGE_W_MM, PAGE_H_MM = 125, 88
COVER = (92, 22, 40)

SURNAME = "RIVERA"
GIVEN = "SAM"
NUMBER = "X1234567"
STATE = "EXA"
BIRTH = "000314"
EXPIRY = "270210"
SEX = "M"


def _font(size_mm: float, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    return ImageFont.truetype(str(FONT_DIR / name), round(size_mm * PX_PER_MM))


def mm(value: float) -> int:
    """Millimetres → pixels on the drawing canvas."""
    return round(value * PX_PER_MM)


def mrz_lines() -> tuple[str, str]:
    """The two 44-character TD3 machine-readable-zone lines."""
    line1 = f"P<{STATE}{SURNAME}<<{GIVEN}".ljust(44, "<")
    number = NUMBER.ljust(9, "<")
    personal = "<" * 14
    parts = [
        number + mrz_check_digit(number),
        STATE,
        BIRTH + mrz_check_digit(BIRTH),
        SEX,
        EXPIRY + mrz_check_digit(EXPIRY),
        personal + "<",
    ]
    body = "".join(parts)
    composite = body[0:10] + body[13:20] + body[21:43]
    line2 = body + mrz_check_digit(composite)
    if len(line1) != 44 or len(line2) != 44:
        raise AssertionError("MRZ lines must be 44 characters")
    return line1, line2


def _guilloche(draw: ImageDraw.ImageDraw, width: int, height: int, rng: random.Random) -> None:
    colors = [(176, 204, 214), (206, 186, 214), (190, 214, 190)]
    for index in range(46):
        color = colors[index % 3]
        base = rng.uniform(-0.1, 1.1) * height
        amp = rng.uniform(0.04, 0.12) * height
        wave = rng.uniform(0.6, 1.6)
        phase = rng.uniform(0, math.tau)
        points = [
            (x, base + amp * math.sin(x / width * math.tau * wave + phase)) for x in range(0, width + 12, 12)
        ]
        draw.line(points, fill=color, width=2)
    cx, cy = int(width * 0.7), int(height * 0.45)
    for radius in range(mm(4), mm(22), mm(1.1)):
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=(200, 214, 222), width=2)


def _silhouette(page: Image.Image, box: tuple[int, int, int, int], *, alpha: int = 255) -> None:
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    layer = Image.new("RGBA", (w, h), (214, 226, 234, alpha))
    draw = ImageDraw.Draw(layer)
    draw.ellipse((int(0.08 * w), int(0.72 * h), int(0.92 * w), int(1.45 * h)), fill=(58, 68, 92, alpha))
    draw.rectangle((int(0.4 * w), int(0.55 * h), int(0.6 * w), int(0.8 * h)), fill=(196, 172, 150, alpha))
    draw.ellipse((int(0.26 * w), int(0.16 * h), int(0.74 * w), int(0.7 * h)), fill=(204, 180, 158, alpha))
    draw.chord((int(0.24 * w), int(0.1 * h), int(0.76 * w), int(0.5 * h)), 180, 360, fill=(62, 46, 38, alpha))
    page.alpha_composite(layer, (x0, y0))


def data_page(seed: int = 1017) -> Image.Image:
    """Render the passport data page (RGB, 12 px/mm)."""
    rng = random.Random(seed)
    width, height = mm(PAGE_W_MM), mm(PAGE_H_MM)
    page = Image.new("RGBA", (width, height), (238, 242, 236, 255))
    draw = ImageDraw.Draw(page)
    _guilloche(draw, width, height, rng)
    draw.rectangle((0, mm(66), width, height), fill=(246, 246, 240, 255))

    dark = (40, 44, 60)
    grey = (96, 104, 120)
    draw.text((mm(6), mm(4)), "REPUBLIC OF EXAMPLIA", font=_font(3.0, True), fill=dark)
    draw.text((mm(6), mm(7.6)), "RÉPUBLIQUE D'EXAMPLIE", font=_font(2.2), fill=grey)
    draw.text((mm(96), mm(4)), "PASSPORT", font=_font(3.0, True), fill=dark)
    draw.text((mm(96), mm(7.6)), "PASSEPORT", font=_font(2.2), fill=grey)

    _silhouette(page, (mm(6), mm(14), mm(38), mm(56)))
    _silhouette(page, (mm(104), mm(40), mm(119), mm(59)), alpha=70)

    label_font, value_font = _font(1.75), _font(2.9, True)

    def field(x: float, y: float, label: str, value: str) -> None:
        draw.text((mm(x), mm(y)), label, font=label_font, fill=grey)
        draw.text((mm(x), mm(y + 2.2)), value, font=value_font, fill=dark)

    field(42, 12, "Type / Type", "P")
    field(56, 12, "Code / Code", STATE)
    field(78, 12, "Passport No. / N° du passeport", NUMBER)
    field(42, 18.6, "Surname / Nom", SURNAME)
    field(42, 25.2, "Given names / Prénoms", GIVEN)
    field(42, 31.8, "Nationality / Nationalité", "EXAMPLIAN")
    field(92, 31.8, "Sex / Sexe", SEX)
    field(42, 38.4, "Date of birth / Date de naissance", "14 MAR / MARS 2000")
    field(42, 45.0, "Place of birth / Lieu de naissance", "EXAMPLIA CITY")
    field(42, 51.6, "Date of issue / Date de délivrance", "11 FEB / FÉV 2017")
    field(84, 51.6, "Authority / Autorité", "MINISTRY OF INTERIOR")
    field(42, 58.2, "Date of expiry / Date d'expiration", "10 FEB / FÉV 2027")
    draw.text((mm(6), mm(57.5)), "Holder's signature", font=label_font, fill=grey)
    for stroke in scribble_strokes(mm(8), mm(59.5), mm(26), mm(4.5), seed="sam:passport"):
        draw.line(stroke, fill=(30, 50, 120), width=3, joint="curve")

    mono = _font(3.3)
    cell = (width - mm(12)) / 44
    for row, line in enumerate(mrz_lines()):
        for col, char in enumerate(line):
            x = mm(6) + col * cell + (cell - mono.getlength(char)) / 2
            draw.text((x, mm(70.5 + row * 6.2)), char, font=mono, fill=(20, 20, 24))

    overlay = Image.new("RGBA", page.size, (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    odraw.text((mm(22), mm(26)), "SPECIMEN", font=_font(16, True), fill=(200, 30, 40, 96))
    overlay = overlay.rotate(18, resample=Image.Resampling.BICUBIC, center=(width // 2, height // 2))
    page.alpha_composite(overlay)
    return page.convert("RGB")


def booklet(seed: int = 1017) -> Image.Image:
    """The open passport: upper (observations) page, data page and the cover edge around them."""
    page = data_page(seed)
    width, height = page.size
    border = mm(2.6)
    gutter = mm(1.2)
    total = Image.new("RGB", (width + 2 * border, 2 * height + gutter + 2 * border), COVER)
    upper = Image.new("RGB", (width, height), (240, 238, 228))
    udraw = ImageDraw.Draw(upper)
    rng = random.Random(seed + 1)
    _guilloche(udraw, width, height, rng)
    udraw.text((mm(6), mm(6)), "OBSERVATIONS / OBSERVATIONS", font=_font(2.6, True), fill=(90, 96, 110))
    for row in range(8):
        y = mm(16 + row * 8.2)
        udraw.line([(mm(6), y), (width - mm(6), y)], fill=(170, 176, 186), width=2)
    udraw.text((mm(40), mm(78)), "3", font=_font(2.4), fill=(90, 96, 110))
    total.paste(upper, (border, border))
    total.paste(page, (border, border + height + gutter))
    shade = Image.new("L", total.size, 255)
    sdraw = ImageDraw.Draw(shade)
    middle = border + height + gutter // 2
    for offset in range(mm(5)):
        value = 170 + round(85 * offset / mm(5))
        sdraw.line([(0, middle - offset), (total.width, middle - offset)], fill=value)
        sdraw.line([(0, middle + offset), (total.width, middle + offset)], fill=value)
    shade = shade.filter(ImageFilter.GaussianBlur(3))
    return Image.composite(total, Image.new("RGB", total.size, (0, 0, 0)), shade)
