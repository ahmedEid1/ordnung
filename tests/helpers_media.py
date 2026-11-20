"""What README's media are, read from their bytes: a GIF's size, frames, length, colours and darkest frame, an animated
WebP's size, frames, length and loop, an MP4's length and whether it starts at once, a PNG's size and brightness. Standard library and Pillow only (a runtime
dependency), so the budgets in ``tests/test_media_budget.py`` need no ffmpeg.

Brightness is the mean luma (Pillow's ``L``: 0 black, 255 white) of a whole picture or frame. A GIF's frames are
read composed, as a browser shows them: ``make capture`` writes each frame as the rectangle that changed.
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import NamedTuple

from PIL import Image, ImageSequence, ImageStat


class GifInfo(NamedTuple):
    width: int
    height: int
    frames: int
    #: the sum of the frames' delays
    seconds: float
    #: the distinct colours over every composed frame
    colours: int
    #: the lowest mean luma of a composed frame
    darkest: float


class WebpInfo(NamedTuple):
    #: the canvas, from its ``VP8X`` chunk
    width: int
    height: int
    frames: int
    #: the sum of the frames' durations
    seconds: float
    #: how many times it plays (``ANIM``): 0 is for ever
    loops: int


class Mp4Info(NamedTuple):
    #: the movie's duration from its ``mvhd`` box
    seconds: float
    #: the ``moov`` box comes before the ``mdat`` box, so a browser can start playing before the whole file is in
    faststart: bool
    #: the picture's size, from the first track that has one (its ``tkhd`` box)
    width: int
    height: int


class PngInfo(NamedTuple):
    width: int
    height: int
    mean_luma: float


def _mean_luma(image: Image.Image) -> float:
    return float(ImageStat.Stat(image.convert("L")).mean[0])


def gif_info(path: Path) -> GifInfo:
    colours: set[tuple[int, ...]] = set()
    darkest = 255.0
    frames = 0
    milliseconds = 0
    with Image.open(path) as gif:
        if gif.format != "GIF":
            raise ValueError(f"{path} is not a GIF")
        width, height = gif.size
        for frame in ImageSequence.Iterator(gif):
            rgb = frame.convert("RGB")
            found = rgb.getcolors(maxcolors=width * height)
            assert found is not None  # every pixel may have a colour of its own, and no more
            colours.update(colour for _, colour in found)
            darkest = min(darkest, _mean_luma(rgb))
            milliseconds += int(frame.info.get("duration", 0))
            frames += 1
    return GifInfo(width, height, frames, milliseconds / 1000, len(colours), darkest)


def webp_info(path: Path) -> WebpInfo:
    """An animated WebP's canvas, frames, length and loop, from its chunks (``RIFF`` ``WEBP``: ``VP8X``, ``ANIM``, then
    an ``ANMF`` per frame): no frame is decoded."""
    data = path.read_bytes()
    if data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise ValueError(f"{path} is not a WebP")
    width = height = frames = milliseconds = 0
    loops = -1
    at = 12
    while at + 8 <= len(data):
        kind, size = data[at : at + 4], struct.unpack("<I", data[at + 4 : at + 8])[0]
        body = data[at + 8 : at + 8 + size]
        if kind == b"VP8X":  # the canvas: 24-bit width and height, each less one
            width = int.from_bytes(body[4:7], "little") + 1
            height = int.from_bytes(body[7:10], "little") + 1
        elif kind == b"ANIM":  # a background colour, then the loop count
            (loops,) = struct.unpack("<H", body[4:6])
        elif kind == b"ANMF":  # x, y, width, height (24 bits each), then the frame's duration
            frames += 1
            milliseconds += int.from_bytes(body[12:15], "little")
        at += 8 + size + (size & 1)  # a chunk of odd size is padded
    if not width or loops < 0:
        raise ValueError(f"{path} is no animated WebP")
    return WebpInfo(width, height, frames, milliseconds / 1000, loops)


def _boxes(data: bytes, start: int, end: int) -> list[tuple[bytes, int, int, int]]:
    """The ISO media boxes between ``start`` and ``end``: their type, where each starts, where its body starts and
    where it ends."""
    found = []
    at = start
    while at + 8 <= end:
        size, kind = struct.unpack(">I4s", data[at : at + 8])
        body = at + 8
        if size == 1:  # a 64-bit size follows the type
            (size,) = struct.unpack(">Q", data[at + 8 : at + 16])
            body = at + 16
        elif size == 0:  # the box runs to the end
            size = end - at
        if size < body - at or at + size > end:
            raise ValueError(f"a broken {kind!r} box at byte {at}")
        found.append((kind, at, body, at + size))
        at += size
    return found


def mp4_info(path: Path) -> Mp4Info:
    data = path.read_bytes()
    # the first box of each type
    top = {kind: (at, body, end) for kind, at, body, end in reversed(_boxes(data, 0, len(data)))}
    if b"moov" not in top or b"mdat" not in top:
        raise ValueError(f"{path} has no moov or no mdat box")
    moov_at, moov_body, moov_end = top[b"moov"]
    boxes = _boxes(data, moov_body, moov_end)
    inside = {kind: body for kind, _, body, _ in boxes}
    if b"mvhd" not in inside:
        raise ValueError(f"{path} has no mvhd box")
    at = inside[b"mvhd"]
    if data[at] == 1:  # version 1: 64-bit creation and modification times, the timescale, a 64-bit duration
        timescale, duration = struct.unpack(">IQ", data[at + 20 : at + 32])
    else:  # version 0: 32-bit times
        timescale, duration = struct.unpack(">II", data[at + 12 : at + 20])
    width = height = 0
    for kind, _, body, end in boxes:
        if kind != b"trak":
            continue
        for track_kind, _, track_body, track_end in _boxes(data, body, end):
            # a track header ends with the width and the height, 16.16 fixed point
            if track_kind == b"tkhd" and not width:
                fixed = struct.unpack(">II", data[track_end - 8 : track_end])
                width, height = (value >> 16 for value in fixed)
    return Mp4Info(
        seconds=duration / timescale, faststart=moov_at < top[b"mdat"][0], width=width, height=height
    )


def png_info(path: Path) -> PngInfo:
    with Image.open(path) as png:
        if png.format != "PNG":
            raise ValueError(f"{path} is not a PNG")
        width, height = png.size
        return PngInfo(width, height, _mean_luma(png))
