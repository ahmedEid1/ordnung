"""Simulated phone photos of a printed letter (Pillow only, deterministic for a given seed).

Pipeline: render page 1 with pypdfium2 (≈ 140 dpi) → off-white paper + fold creases → slight
rotation and perspective onto a table surface → soft shadow → uneven light + vignette → warm white
balance → mild blur + phone sharpening → luminance noise → baseline JPEG, quality 82, no EXIF.
"""

from __future__ import annotations

import io
import math
import random

import pypdfium2 as pdfium
from PIL import Image, ImageChops, ImageDraw, ImageFilter

Point = tuple[float, float]


def render_page(pdf_bytes: bytes, index: int = 0, dpi: float = 140.0) -> Image.Image:
    document = pdfium.PdfDocument(pdf_bytes)
    try:
        return document[index].render(scale=dpi / 72.0).to_pil().convert("RGB")
    finally:
        document.close()


def _solve(matrix: list[list[float]], rhs: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting (8 × 8)."""
    n = len(rhs)
    rows = [[*matrix[i], rhs[i]] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(rows[r][col]))
        rows[col], rows[pivot] = rows[pivot], rows[col]
        lead = rows[col][col]
        rows[col] = [v / lead for v in rows[col]]
        for r in range(n):
            if r != col and rows[r][col]:
                factor = rows[r][col]
                rows[r] = [a - factor * b for a, b in zip(rows[r], rows[col], strict=True)]
    return [rows[i][n] for i in range(n)]


def _perspective(dst: list[Point], src: list[Point]) -> tuple[float, ...]:
    """Coefficients for ``Image.transform(PERSPECTIVE)`` mapping output quad ``dst`` → input ``src``."""
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


def _noise(size: tuple[int, int], rng: random.Random, amplitude: float, blur: float) -> Image.Image:
    width, height = size
    noise = Image.frombytes("L", size, rng.randbytes(width * height))
    noise = noise.point(_lut(lambda v: 128 + (v - 128) * amplitude / 128))
    return noise.filter(ImageFilter.GaussianBlur(blur)) if blur else noise


def _low_freq(
    size: tuple[int, int], rng: random.Random, lo: int, hi: int, grid: tuple[int, int]
) -> Image.Image:
    small = Image.new("L", grid)
    small.putdata([rng.randint(lo, hi) for _ in range(grid[0] * grid[1])])
    return small.resize(size, Image.Resampling.BICUBIC)


def _surface(size: tuple[int, int], rng: random.Random) -> Image.Image:
    kind = rng.choice(("wood", "desk", "dark"))
    width, height = size
    if kind == "wood":
        base = Image.new("RGB", size, (148, 104, 66))
        draw = ImageDraw.Draw(base)
        for _ in range(140):
            y0 = rng.uniform(-40, height + 40)
            amp = rng.uniform(3, 16)
            freq = rng.uniform(0.002, 0.005)
            phase = rng.uniform(0, math.tau)
            shade = rng.randint(-30, 20)
            color = (148 + shade, 104 + round(shade * 0.75), 66 + round(shade * 0.5))
            pts = [(x, y0 + amp * math.sin(x * freq + phase)) for x in range(-40, width + 80, 40)]
            draw.line(pts, fill=color, width=rng.randint(1, 4))
        base = base.filter(ImageFilter.GaussianBlur(2.0))
    elif kind == "desk":
        base = Image.new("RGB", size, (205, 203, 197))
    else:
        base = Image.new("RGB", size, (60, 63, 70))
    grain = _noise(size, rng, 10, 0.8)
    base = ImageChops.add(base, Image.merge("RGB", (grain, grain, grain)), scale=1.0, offset=-128)
    light_map = _low_freq(size, rng, 205, 255, (5, 4))
    return ImageChops.multiply(base, Image.merge("RGB", (light_map, light_map, light_map)))


def _paper(page: Image.Image, rng: random.Random) -> Image.Image:
    width, height = page.size
    tinted = ImageChops.multiply(page, Image.new("RGB", page.size, (253, 251, 245)))
    crease = Image.new("L", page.size, 255)
    draw = ImageDraw.Draw(crease)
    for index in (1, 2):
        y = round(height * index / 3) + rng.randint(-6, 6)
        draw.line([(0, y - 2), (width, y - 2 + rng.randint(-3, 3))], fill=226, width=3)
        draw.line([(0, y + 3), (width, y + 3)], fill=248, width=4)
    crease = crease.filter(ImageFilter.GaussianBlur(2.4))
    return ImageChops.multiply(tinted, Image.merge("RGB", (crease, crease, crease)))


def phone_photo(
    pdf_bytes: bytes, seed: int, *, canvas: tuple[int, int] = (1275, 1700), quality: int = 82
) -> bytes:
    """JPEG bytes of a simulated phone photo of page 1 of ``pdf_bytes``."""
    rng = random.Random(seed)
    page = _paper(render_page(pdf_bytes), rng)
    width, height = canvas
    item_w, item_h = page.size
    scale = min(0.90 * height / item_h, 0.93 * width / item_w)
    half_w, half_h = item_w * scale / 2, item_h * scale / 2
    theta = math.radians(rng.choice((-1, 1)) * rng.uniform(0.8, 3.2))
    tilt = rng.uniform(0.015, 0.045)
    cx = width / 2 + rng.uniform(-0.015, 0.015) * width
    cy = height / 2 + rng.uniform(-0.012, 0.012) * height
    quad: list[Point] = []
    for i, (px, py) in enumerate(
        [(-half_w, -half_h), (half_w, -half_h), (half_w, half_h), (-half_w, half_h)]
    ):
        top = i < 2
        px *= (1 - tilt) if top else (1 + tilt * 0.3)
        py *= (1 - tilt * 0.4) if top else 1.0
        px += rng.uniform(-0.005, 0.005) * half_w * 2
        py += rng.uniform(-0.005, 0.005) * half_h * 2
        quad.append(
            (
                cx + px * math.cos(theta) - py * math.sin(theta),
                cy + px * math.sin(theta) + py * math.cos(theta),
            )
        )
    coeffs = _perspective(quad, [(0, 0), (item_w, 0), (item_w, item_h), (0, item_h)])
    warped = page.transform(canvas, Image.Transform.PERSPECTIVE, coeffs, Image.Resampling.BICUBIC)
    mask = Image.new("L", page.size, 255).transform(
        canvas, Image.Transform.PERSPECTIVE, coeffs, Image.Resampling.BILINEAR
    )
    mask = mask.filter(ImageFilter.GaussianBlur(0.8))

    background = _surface(canvas, rng)
    dark = ImageChops.multiply(background, Image.new("RGB", canvas, (50, 46, 42)))
    cast = Image.new("L", canvas, 0)
    cast.paste(mask, (12, 18))
    cast = cast.filter(ImageFilter.GaussianBlur(20)).point(_lut(lambda v: v * 0.5))
    background = Image.composite(dark, background, cast)
    photo = Image.composite(warped, background, mask)

    light = _low_freq(canvas, rng, 222, 255, (3, 4))
    vignette = Image.new("L", (48, 64))
    vignette.putdata(
        [
            round(255 * (1 - 0.22 * (((x - 23.5) / 24) ** 2 + ((y - 31.5) / 32) ** 2)))
            for y in range(64)
            for x in range(48)
        ]
    )
    lighting = ImageChops.multiply(light, vignette.resize(canvas, Image.Resampling.BICUBIC))
    photo = ImageChops.multiply(photo, Image.merge("RGB", (lighting, lighting, lighting)))
    red, green, blue = photo.split()
    photo = Image.merge(
        "RGB",
        (
            red.point(_lut(lambda v: v * 1.03 + 4)),
            green.point(_lut(lambda v: v + 1)),
            blue.point(_lut(lambda v: v * 0.93)),
        ),
    )
    photo = photo.filter(ImageFilter.GaussianBlur(0.55)).filter(
        ImageFilter.UnsharpMask(radius=1.6, percent=60, threshold=2)
    )
    grain = _noise((width // 2, height // 2), rng, 7, 0).resize(canvas, Image.Resampling.BILINEAR)
    photo = ImageChops.add(photo, Image.merge("RGB", (grain, grain, grain)), scale=1.0, offset=-128)
    buffer = io.BytesIO()
    photo.save(buffer, "JPEG", quality=quality, optimize=False, progressive=False, subsampling=2)
    return buffer.getvalue()
