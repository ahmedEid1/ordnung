"""Simulated phone photos of paper documents (Pillow only, fully deterministic).

Pipeline: render the PDF page with pypdfium2 (~150 dpi) → paper effects (tint, fold creases) → place
it on a procedurally generated table surface with rotation and perspective → soft drop shadow →
uneven lighting and vignette → warm white balance → slight softness + phone-style sharpening →
luminance noise → JPEG (quality 82, no EXIF). All randomness comes from ``random.Random(seed)``.
"""

from __future__ import annotations

import io
import math
import random
from collections.abc import Sequence
from typing import Literal

import pypdfium2 as pdfium
from PIL import Image, ImageChops, ImageDraw, ImageFilter

Surface = Literal["wood", "desk", "dark", "linen"]
Point = tuple[float, float]


def render_page(pdf_bytes: bytes, index: int = 0, dpi: float = 150.0) -> Image.Image:
    """Rasterise one PDF page to an RGB image."""
    document = pdfium.PdfDocument(pdf_bytes)
    try:
        bitmap = document[index].render(scale=dpi / 72.0)
        return bitmap.to_pil().convert("RGB")
    finally:
        document.close()


def to_jpeg(image: Image.Image, quality: int = 82) -> bytes:
    """Encode as a baseline JPEG without metadata (byte-stable for a given Pillow build)."""
    buffer = io.BytesIO()
    image.convert("RGB").save(
        buffer, "JPEG", quality=quality, optimize=False, progressive=False, subsampling=2
    )
    return buffer.getvalue()


# --------------------------------------------------------------------------------------------------
# geometry
# --------------------------------------------------------------------------------------------------


def _solve(matrix: list[list[float]], rhs: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting (8 × 8 is all we need)."""
    size = len(rhs)
    rows = [[*matrix[i], rhs[i]] for i in range(size)]
    for col in range(size):
        pivot = max(range(col, size), key=lambda r: abs(rows[r][col]))
        rows[col], rows[pivot] = rows[pivot], rows[col]
        lead = rows[col][col]
        if abs(lead) < 1e-12:
            raise ValueError("degenerate perspective quad")
        rows[col] = [v / lead for v in rows[col]]
        for r in range(size):
            if r != col and rows[r][col]:
                factor = rows[r][col]
                rows[r] = [a - factor * b for a, b in zip(rows[r], rows[col], strict=True)]
    return [rows[i][size] for i in range(size)]


def perspective_coeffs(dst: Sequence[Point], src: Sequence[Point]) -> tuple[float, ...]:
    """Coefficients for ``Image.transform(PERSPECTIVE)`` mapping output quad ``dst`` → input quad ``src``."""
    matrix: list[list[float]] = []
    rhs: list[float] = []
    for (x, y), (u, v) in zip(dst, src, strict=True):
        matrix.append([x, y, 1, 0, 0, 0, -x * u, -y * u])
        rhs.append(u)
        matrix.append([0, 0, 0, x, y, 1, -x * v, -y * v])
        rhs.append(v)
    return tuple(_solve(matrix, rhs))


def _lut(fn: object) -> list[int]:
    assert callable(fn)
    return [max(0, min(255, round(fn(i)))) for i in range(256)]


# --------------------------------------------------------------------------------------------------
# surfaces
# --------------------------------------------------------------------------------------------------


def _low_freq(
    size: tuple[int, int], rng: random.Random, lo: int, hi: int, grid: tuple[int, int] = (5, 4)
) -> Image.Image:
    small = Image.new("L", grid)
    small.putdata([rng.randint(lo, hi) for _ in range(grid[0] * grid[1])])
    return small.resize(size, Image.Resampling.BICUBIC)


def _speckle(size: tuple[int, int], rng: random.Random, amplitude: float, blur: float) -> Image.Image:
    width, height = size
    noise = Image.frombytes("L", size, rng.randbytes(width * height))
    noise = noise.point(_lut(lambda v: 128 + (v - 128) * amplitude / 128))
    return noise.filter(ImageFilter.GaussianBlur(blur)) if blur else noise


def make_surface(kind: Surface, size: tuple[int, int], rng: random.Random) -> Image.Image:
    """A procedurally generated table top."""
    width, height = size
    if kind == "wood":
        base = Image.new("RGB", size, (151, 104, 64))
        draw = ImageDraw.Draw(base)
        for _ in range(170):
            y0 = rng.uniform(-40, height + 40)
            amp = rng.uniform(3, 18)
            freq = rng.uniform(0.0015, 0.005)
            phase = rng.uniform(0, math.tau)
            tone = rng.randint(-34, 22)
            color = (151 + tone, 104 + round(tone * 0.75), 64 + round(tone * 0.5))
            points = [(x, y0 + amp * math.sin(x * freq + phase)) for x in range(-40, width + 80, 40)]
            draw.line(points, fill=color, width=rng.randint(1, 5))
        plank = rng.randint(520, 640)
        for y in range(rng.randint(80, 300), height, plank):
            draw.line([(0, y), (width, y + rng.randint(-6, 6))], fill=(78, 50, 30), width=3)
        base = base.filter(ImageFilter.GaussianBlur(2.2))
        grain = _speckle(size, rng, 10, 0.8)
    elif kind == "desk":
        base = Image.new("RGB", size, (208, 205, 198))
        grain = _speckle(size, rng, 9, 0.9)
    elif kind == "dark":
        base = Image.new("RGB", size, (58, 61, 68))
        grain = _speckle(size, rng, 12, 0.7)
    else:  # linen
        base = Image.new("RGB", size, (222, 213, 194))
        draw = ImageDraw.Draw(base)
        for x in range(0, width, 4):
            draw.line([(x, 0), (x, height)], fill=(212 + rng.randint(-5, 5), 202, 182), width=1)
        for y in range(0, height, 4):
            draw.line([(0, y), (width, y)], fill=(214, 205 + rng.randint(-5, 5), 185), width=1)
        base = base.filter(ImageFilter.GaussianBlur(0.7))
        grain = _speckle(size, rng, 8, 0.6)
    base = ImageChops.add(base, Image.merge("RGB", (grain, grain, grain)), scale=1.0, offset=-128)
    shade = _low_freq(size, rng, 200, 255)
    return ImageChops.multiply(base, Image.merge("RGB", (shade, shade, shade)))


# --------------------------------------------------------------------------------------------------
# paper and camera effects
# --------------------------------------------------------------------------------------------------


def paper_effects(page: Image.Image, rng: random.Random, *, folds: int = 2) -> Image.Image:
    """Off-white paper and soft crease shading where a letter was folded into thirds."""
    width, height = page.size
    tinted = ImageChops.multiply(page, Image.new("RGB", page.size, (254, 253, 249)))
    if not folds:
        return tinted
    crease = Image.new("L", page.size, 255)
    draw = ImageDraw.Draw(crease)
    for index in range(1, folds + 1):
        y = round(height * index / (folds + 1)) + rng.randint(-6, 6)
        draw.line([(0, y - 2), (width, y - 2 + rng.randint(-3, 3))], fill=228, width=3)
        draw.line([(0, y + 3), (width, y + 3)], fill=248, width=4)
    crease = crease.filter(ImageFilter.GaussianBlur(2.5))
    return ImageChops.multiply(tinted, Image.merge("RGB", (crease, crease, crease)))


def phone_photo(
    item: Image.Image,
    *,
    seed: int,
    surface: Surface = "wood",
    canvas: tuple[int, int] = (1500, 2000),
    fill: float = 0.88,
    angle: float | None = None,
    tilt: float = 0.035,
    shadow: float = 0.55,
    light: tuple[int, int] = (230, 255),
    noise: float = 7.0,
) -> Image.Image:
    """Photograph ``item`` (a page, card or booklet image) lying on a table."""
    rng = random.Random(seed)
    width, height = canvas
    item_w, item_h = item.size
    scale = min(fill * height / item_h, 0.94 * width / item_w)
    half_w, half_h = item_w * scale / 2, item_h * scale / 2
    theta = math.radians(angle if angle is not None else rng.choice((-1, 1)) * rng.uniform(1.2, 3.6))
    center_x = width / 2 + rng.uniform(-0.015, 0.015) * width
    center_y = height / 2 + rng.uniform(-0.012, 0.012) * height
    corners = [(-half_w, -half_h), (half_w, -half_h), (half_w, half_h), (-half_w, half_h)]
    quad: list[Point] = []
    for index, (px, py) in enumerate(corners):
        top = index < 2
        px *= (1 - tilt) if top else (1 + tilt * 0.35)
        py *= (1 - tilt * 0.4) if top else 1.0
        px += rng.uniform(-0.006, 0.006) * half_w * 2
        py += rng.uniform(-0.006, 0.006) * half_h * 2
        rx = px * math.cos(theta) - py * math.sin(theta)
        ry = px * math.sin(theta) + py * math.cos(theta)
        quad.append((center_x + rx, center_y + ry))
    coeffs = perspective_coeffs(quad, [(0, 0), (item_w, 0), (item_w, item_h), (0, item_h)])

    warped = item.convert("RGB").transform(
        canvas, Image.Transform.PERSPECTIVE, coeffs, Image.Resampling.BICUBIC
    )
    mask = Image.new("L", item.size, 255).transform(
        canvas, Image.Transform.PERSPECTIVE, coeffs, Image.Resampling.BILINEAR
    )
    mask = mask.filter(ImageFilter.GaussianBlur(0.8))

    background = make_surface(surface, canvas, rng)
    dark = ImageChops.multiply(background, Image.new("RGB", canvas, (48, 44, 40)))
    for radius, offset, strength in ((22, (14, 20), shadow), (3, (2, 3), shadow * 0.6)):
        cast = Image.new("L", canvas, 0)
        cast.paste(mask, offset)
        cast = cast.filter(ImageFilter.GaussianBlur(radius)).point(_lut(lambda v, s=strength: v * s))
        background = Image.composite(dark, background, cast)
    photo = Image.composite(warped, background, mask)

    illumination = _low_freq(canvas, rng, light[0], light[1], grid=(3, 4))
    vignette = Image.new("L", (48, 64))
    vignette.putdata(
        [
            round(255 * (1 - 0.24 * (((x - 23.5) / 24) ** 2 + ((y - 31.5) / 32) ** 2)))
            for y in range(64)
            for x in range(48)
        ]
    )
    vignette = vignette.resize(canvas, Image.Resampling.BICUBIC)
    lighting = ImageChops.multiply(illumination, vignette)
    photo = ImageChops.multiply(photo, Image.merge("RGB", (lighting, lighting, lighting)))

    red, green, blue = photo.split()
    photo = Image.merge(
        "RGB",
        (
            red.point(_lut(lambda v: v * 1.025 + 3)),
            green.point(_lut(lambda v: v * 1.0 + 1)),
            blue.point(_lut(lambda v: v * 0.945 + 2)),
        ),
    )
    photo = photo.filter(ImageFilter.GaussianBlur(0.5)).filter(
        ImageFilter.UnsharpMask(radius=1.6, percent=60, threshold=2)
    )
    grain = _speckle((width // 2, height // 2), rng, noise, 0).resize(canvas, Image.Resampling.BILINEAR)
    return ImageChops.add(photo, Image.merge("RGB", (grain, grain, grain)), scale=1.0, offset=-128)


def photo_of_pdf_page(
    pdf_bytes: bytes,
    index: int,
    *,
    seed: int,
    surface: Surface = "wood",
    folds: int = 2,
    dpi: float = 150.0,
    canvas: tuple[int, int] = (1500, 2000),
    fill: float = 0.88,
    angle: float | None = None,
    tilt: float = 0.035,
) -> bytes:
    """Render page ``index`` of a PDF and return it as a simulated phone photo (JPEG bytes)."""
    rng = random.Random(seed ^ 0x5EED)
    page = paper_effects(render_page(pdf_bytes, index, dpi), rng, folds=folds)
    photo = phone_photo(page, seed=seed, surface=surface, canvas=canvas, fill=fill, angle=angle, tilt=tilt)
    return to_jpeg(photo)
