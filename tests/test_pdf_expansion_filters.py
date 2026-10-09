"""The decompression-bomb check's own decoders (``ordnung.ingest.expansion``): LZW (either ``/EarlyChange``),
RunLength, and the ASCII85 and ASCIIHex data in front of them. Each must count what PDFium decodes (checked
byte for byte through PDFium's own image decoding, and against pdfminer's decoders), and stop once a limit is
passed; a bomb behind each filter, alone or chained, is rejected, and a letter written with them passes.

The streams are built here: a small LZW encoder (codes of 9 to 12 bits, the table cleared when it fills) and
a RunLength encoder.
"""

from __future__ import annotations

import base64
import binascii
import random
import zlib
from collections.abc import Iterator

import pypdfium2 as pdfium
import pytest
from pdfminer.ascii85 import ascii85decode
from pdfminer.lzw import lzwdecode
from pdfminer.runlength import rldecode

from ordnung.ingest import expansion
from ordnung.ingest.text import PDFIUM_LOCK

CLEAR, END = 256, 257
#: The encoder clears the table before it holds 4094 entries (the decoders' table stops at 4096).
CLEAR_AT = 4094
#: The bytes one table's worth of codes writes for a run of zero bytes: runs of 1, 2, … 3837 zeros.
ZERO_TABLE = sum(range(1, CLEAR_AT - 258 + 2))
LIMIT = 2 * 1024 * 1024


# --------------------------------------------------------------------------------------------------
# Writing the streams
# --------------------------------------------------------------------------------------------------


def _lzw_packed(codes: list[int], early_change: int = 1) -> bytes:
    """``codes`` as LZW data: each code as wide as a decoder reads it (PDF 7.4.4.2)."""
    out = bytearray()
    value = bits = 0
    size, width, previous = 258, 9, False
    for code in codes:
        value, bits = (value << width) | code, bits + width
        while bits >= 8:
            bits -= 8
            out.append((value >> bits) & 0xFF)
        value &= (1 << bits) - 1
        if code == CLEAR:
            size, width, previous = 258, 9, False
            continue
        if code == END:
            break
        if previous and size < 4096:
            size += 1
        previous = True
        if size + early_change >= 1 << width and width < 12:
            width += 1
    if bits:
        out.append((value << (8 - bits)) & 0xFF)
    return bytes(out)


def _lzw_codes(data: bytes) -> list[int]:
    codes = [CLEAR]
    table = {bytes([value]): value for value in range(256)}
    word = b""
    for value in data:
        longer = word + bytes([value])
        if longer in table:
            word = longer
            continue
        codes.append(table[word])
        if len(table) + 2 < CLEAR_AT:
            table[longer] = len(table) + 2
        else:
            codes.append(CLEAR)
            table = {bytes([value]): value for value in range(256)}
        word = bytes([value])
    if word:
        codes.append(table[word])
    return [*codes, END]


def _lzw(data: bytes, early_change: int = 1) -> bytes:
    return _lzw_packed(_lzw_codes(data), early_change)


def _zero_bomb(tables: int, early_change: int = 1) -> bytes:
    """The LZW codes an encoder writes for ``tables`` × :data:`ZERO_TABLE` zero bytes (each code is the one
    being defined: the KwKwK case), without encoding them: about 5.4 KB per table."""
    codes: list[int] = []
    for _ in range(tables):
        codes += [CLEAR, 0, *range(258, CLEAR_AT)]
    return _lzw_packed([*codes, END], early_change)


def _run_length(data: bytes) -> bytes:
    """RunLength data (PDF 7.4.5): runs of 2–128 equal bytes, literals of 1–128 bytes, then 128."""
    out = bytearray()
    at = 0
    while at < len(data):
        run = 1
        while at + run < len(data) and run < 128 and data[at + run] == data[at]:
            run += 1
        if run > 1:
            out += bytes([257 - run, data[at]])
            at += run
            continue
        start = at
        while at < len(data) and at - start < 128 and (at + 1 == len(data) or data[at + 1] != data[at]):
            at += 1
        out += bytes([at - start - 1]) + data[start:at]
    return bytes(out) + b"\x80"


def _letter() -> bytes:
    """A page of text (made-up words, the same every run)."""
    rng = random.Random(3)
    words = [b"Frist", b"Bescheid", b"Widerspruch", b"Monat", b"Zahlung", b"bis", b"zum", b"Euro", b"12,50"]
    lines = [b" ".join(rng.choice(words) for _ in range(8)) for _ in range(60)]
    return b"\n".join(
        b"BT /F1 9 Tf 20 %d Td (%s) Tj ET" % (780 - 12 * n, line) for n, line in enumerate(lines)
    )


def _mixed(size: int) -> bytes:
    """Text-like bytes, then random ones: every code width, and a cleared table, in one stream."""
    rng = random.Random(7)
    return bytes(rng.choice(b"abcdefgh \n0123") for _ in range(size // 2)) + rng.randbytes(size - size // 2)


# --------------------------------------------------------------------------------------------------
# Reading them: the guard, PDFium
# --------------------------------------------------------------------------------------------------


def _decoded(stage: expansion._Stage, data: bytes, piece: int | None = None) -> bytes:
    """What ``stage`` decodes from ``data``, fed whole or in pieces of ``piece`` bytes."""
    pieces = [data] if piece is None else [data[at : at + piece] for at in range(0, len(data), piece)]
    return b"".join(chunk for part in pieces for chunk in stage.feed(part))


_HEADER = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
_PAGES = b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
_TRAILER = b"\nendstream\nendobj\ntrailer\n<< /Root 1 0 R /Size 6 >>\n%%EOF\n"


_IMAGE_PAGE = (
    b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 800] /Contents 4 0 R "
    b"/Resources << /XObject << /Im1 5 0 R >> >> >>\nendobj\n"
)
_TEXT_PAGE = (
    b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 800] /Contents 4 0 R "
    b"/Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n"
    b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"
)


def _image_pdf(filters: bytes, data: bytes, width: int, height: int = 1, parameters: bytes = b"") -> bytes:
    """A page that shows one grey image whose data is ``data`` through ``filters``."""
    content = b"q %d 0 0 %d 0 0 cm /Im1 Do Q" % (width, height)
    page_content = b"4 0 obj\n<< /Length %d >>\nstream\n%s\nendstream\nendobj\n" % (len(content), content)
    image = b"5 0 obj\n<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceGray " % (
        width,
        height,
    )
    image += b"/BitsPerComponent 8 /Length %d /Filter %s %s >>\nstream\n" % (len(data), filters, parameters)
    return _HEADER + _PAGES + _IMAGE_PAGE + page_content + image + data + _TRAILER


def _pdfium_decodes(filters: bytes, data: bytes, parameters: bytes = b"") -> bytes:
    """What PDFium decodes from ``data`` through ``filters`` (its image data API applies every filter but
    the image codecs)."""
    with PDFIUM_LOCK:
        pdf = pdfium.PdfDocument(_image_pdf(filters, data, max(1, len(data)), 1, parameters))
        try:
            (image,) = [item for item in pdf[0].get_objects() if isinstance(item, pdfium.PdfImage)]
            return bytes(image.get_data(decode_simple=True))
        finally:
            pdf.close()


def _page(filters: bytes, data: bytes, parameters: bytes = b"") -> bytes:
    """A one-page letter whose page content is ``data`` through ``filters``, in Helvetica."""
    content = b"4 0 obj\n<< /Length %d /Filter %s %s >>\nstream\n" % (len(data), filters, parameters)
    return _HEADER + _PAGES + _TEXT_PAGE + content + data + _TRAILER


def _pdfium_text(pdf: bytes) -> str:
    with PDFIUM_LOCK:
        document = pdfium.PdfDocument(pdf)
        try:
            return document[0].get_textpage().get_text_range()
        finally:
            document.close()


@pytest.fixture
def small_limits(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Limits of 2 MB, so a bomb a few kilobytes long shows what one of gigabytes would."""
    monkeypatch.setattr(expansion, "MAX_STREAM_BYTES", LIMIT)
    monkeypatch.setattr(expansion, "MAX_CONTENT_BYTES", LIMIT)
    yield


# --------------------------------------------------------------------------------------------------
# LZW
# --------------------------------------------------------------------------------------------------


def test_lzw_decodes_what_pdfminer_and_pdfium_decode_through_every_code_width_and_a_cleared_table() -> None:
    data = _mixed(60_000)
    codes = _lzw_codes(data)
    assert CLEAR in codes[1:-1] and max(codes) >= 2048  # a cleared table, and 12-bit codes
    encoded = _lzw_packed(codes)
    assert _decoded(expansion._Lzw(), encoded) == data
    assert _decoded(expansion._Lzw(), encoded, piece=7) == data  # fed in pieces, codes span them
    assert lzwdecode(encoded) == data
    assert _pdfium_decodes(b"/LZWDecode", encoded) == data
    assert expansion.expanded_size(encoded, 0, [b"LZWDecode"]) == (len(data), len(encoded))


def test_lzw_with_early_change_0_is_read_as_pdfium_reads_it() -> None:
    """``/EarlyChange 0`` widens the codes one code later; read the other way, the data is garbage."""
    data = _mixed(20_000)
    encoded = _lzw(data, early_change=0)
    assert _decoded(expansion._Lzw(early_change=0), encoded) == data
    assert _pdfium_decodes(b"/LZWDecode", encoded, b"/DecodeParms << /EarlyChange 0 >>") == data
    assert _decoded(expansion._Lzw(early_change=1), encoded) != data


def test_an_lzw_code_not_yet_defined_repeats_the_previous_entry_as_pdfium_does() -> None:
    """A run of zeros is all KwKwK codes (each one the code being defined); a code past that one is read
    the same way by PDFium."""
    kwkwk = _lzw_packed([CLEAR, 0, 258, 259, END])
    assert (
        _decoded(expansion._Lzw(), kwkwk) == bytes(6) == lzwdecode(kwkwk) == _pdfium_decodes(b"/LZW", kwkwk)
    )
    past = _lzw_packed([CLEAR, 65, 66, 300, 67, END])
    assert _decoded(expansion._Lzw(), past) == b"ABBBC" == _pdfium_decodes(b"/LZW", past)


def test_lzw_stops_at_its_end_code_and_at_a_code_a_fresh_table_lacks() -> None:
    """Nothing after the end code counts. A first code beyond the table is damaged data: the decoder stops
    (PDFium can't decode it either and keeps the stream's bytes as they are, which don't expand)."""
    ended = expansion._Lzw()
    assert _decoded(ended, _lzw_packed([CLEAR, 65, END, 66, 67])) == b"A" and ended.finished
    damaged = expansion._Lzw()
    assert _decoded(damaged, _lzw_packed([CLEAR, 300, 65, 66, END])) == b"" and damaged.finished
    assert _decoded(expansion._Lzw(), _lzw_packed([65, 66, 258, END])) == b"ABAB"  # no clear code first


def test_an_lzw_bomb_is_counted_only_until_the_limit() -> None:
    one = _zero_bomb(1)
    assert len(one) < 6000 and len(lzwdecode(one)) == ZERO_TABLE
    bomb = _zero_bomb(30)  # 160 KB that expand to 220 MB
    assert expansion.expanded_size(bomb, 0, [b"LZWDecode"]) == (30 * ZERO_TABLE, len(bomb))
    expanded, read = expansion.expanded_size(bomb, 0, [b"LZWDecode"], limit=LIMIT)
    assert LIMIT < expanded <= LIMIT + expansion._OUT_CHUNK + 4096
    assert read <= expansion._READ_CHUNK  # it stopped in the first piece it read


def test_an_lzw_bomb_written_with_early_change_0_is_rejected(small_limits: None) -> None:
    """Read with the default ``/EarlyChange 1``, it counts 32 KB; the guard reads it both ways, whatever its
    ``/DecodeParms`` say."""
    bomb = _zero_bomb(1, early_change=0)
    assert expansion.expanded_size(bomb, 0, [b"LZWDecode"], early_change=1)[0] < LIMIT
    assert expansion.expanded_size(bomb, 0, [b"LZWDecode"], early_change=0)[0] == ZERO_TABLE
    for parameters in (b"", b"/DecodeParms << /EarlyChange 1 >>"):
        with pytest.raises(expansion.ExpansionError, match="expands to far more data"):
            expansion.check_pdf_expansion(_page(b"/LZWDecode", bomb, parameters))


# --------------------------------------------------------------------------------------------------
# RunLength
# --------------------------------------------------------------------------------------------------


def test_run_length_decodes_what_pdfminer_and_pdfium_decode_also_fed_in_pieces() -> None:
    data = _letter() + bytes(500) + b"ab" * 300 + bytes(range(256)) + b"\xff" * 129
    encoded = _run_length(data)
    assert bytes([129]) in encoded and bytes([127]) in encoded  # runs and literals of 128 bytes
    assert rldecode(encoded) == data == _pdfium_decodes(b"/RunLengthDecode", encoded)
    for piece in (None, 1, 2, 3, 129):
        stage = expansion._RunLength()
        assert _decoded(stage, encoded, piece) == data and stage.finished, piece
    after_the_end = expansion._RunLength()
    assert _decoded(after_the_end, b"\x01ab\x80\xfex") == b"ab" and after_the_end.finished


def test_a_run_length_bomb_is_counted_only_until_the_limit() -> None:
    bomb = b"\x81\x00" * 200_000  # 400 KB that expand to 25.6 MB
    assert expansion.expanded_size(bomb, 0, [b"RL"]) == (128 * 200_000, len(bomb))
    expanded, read = expansion.expanded_size(bomb, 0, [b"RL"], limit=LIMIT)
    assert LIMIT < expanded <= LIMIT + expansion._OUT_CHUNK + 128
    assert read == 3 * expansion._READ_CHUNK  # each piece read expands to 1 MB: the third passes 2 MB


# --------------------------------------------------------------------------------------------------
# ASCII85 and ASCIIHex in front of them
# --------------------------------------------------------------------------------------------------

LETTER = _letter()
A85 = base64.a85encode(LETTER, wrapcol=72)


@pytest.mark.parametrize(
    ("filters", "data"),
    [
        pytest.param(b"/ASCII85Decode", A85 + b"~>", id="ascii85"),
        pytest.param(b"/A85", base64.a85encode(bytes(64) + LETTER) + b"\n~>", id="ascii85 with z for zeros"),
        pytest.param(
            b"/A85", A85[:500] + b"v" + A85[500:] + b"~>", id="ascii85 up to a character outside it"
        ),
        pytest.param(b"/A85", A85[:500] + b"\x0c" + A85[500:] + b"~>", id="ascii85 up to a form feed"),
        pytest.param(b"/A85", A85[:500] + b"~" + A85[500:] + b"~>", id="ascii85 up to a lone tilde"),
        pytest.param(b"/A85", A85[:7] + b"z" + A85[7:] + b"~>", id="ascii85 with z inside a group"),
        pytest.param(b"/A85", b"uuuuu" + A85 + b"~>", id="ascii85 with a group above 32 bits"),
        pytest.param(b"/A85", base64.a85encode(LETTER[:-2]), id="ascii85 without its end"),
        pytest.param(b"/ASCIIHexDecode", binascii.hexlify(LETTER, b" ", 30) + b">", id="hex"),
        pytest.param(b"/AHx", binascii.hexlify(LETTER).upper() + b"g q\x0c<", id="hex past other characters"),
        pytest.param(b"/AHx", b"4142434>4445", id="hex with an odd number of digits, then its end"),
    ],
)
def test_ascii85_and_asciihex_data_is_decoded_as_pdfium_decodes_it(filters: bytes, data: bytes) -> None:
    """PDFium stops ASCII85 at the first character that can't be part of it and skips any character that
    isn't a hex digit, where Python's decoders refuse the data (so it once counted as nothing)."""
    name = filters.removeprefix(b"/")
    assert expansion._pre_decoded(data, 0, name)[0] == _pdfium_decodes(filters, data)


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(b"<~" + A85 + b"~>", id="a leading <~"),
        pytest.param(b" ~" + A85 + b"~>", id="a leading ~"),
        pytest.param(A85[:500] + b"\x0b" + A85[500:] + b"~>", id="a vertical tab"),
    ],
)
def test_ascii85_that_pdfminer_reads_further_than_pdfium_counts_what_pdfminer_reads(data: bytes) -> None:
    """PDFium stops at the ``~`` and at the vertical tab; pdfminer skips both."""
    assert expansion._pre_decoded(data, 0, b"A85")[0] == ascii85decode(data) == LETTER


@pytest.mark.parametrize(
    ("filters", "data"),
    [
        pytest.param(
            [b"ASCII85Decode", b"FlateDecode"],
            base64.a85encode(zlib.compress(LETTER)) + b"~>",
            id="A85 Flate",
        ),
        pytest.param([b"A85", b"LZW"], base64.a85encode(_lzw(LETTER), wrapcol=60) + b"~>", id="A85 LZW"),
        pytest.param([b"AHx", b"RL"], binascii.hexlify(_run_length(LETTER), b"\n", 40) + b">", id="AHx RL"),
        pytest.param(
            [b"ASCIIHexDecode", b"LZWDecode", b"RunLengthDecode"],
            binascii.hexlify(_lzw(_run_length(LETTER))) + b">",
            id="AHx LZW RL",
        ),
    ],
)
def test_ascii_data_is_decoded_before_the_expanding_filters_behind_it(
    filters: list[bytes], data: bytes
) -> None:
    assert expansion.expanded_size(data + b"\nendstream", 0, filters)[0] == len(LETTER)
    chain = b"[" + b" ".join(b"/" + name for name in filters) + b"]"
    assert _pdfium_decodes(chain, data) == LETTER


# --------------------------------------------------------------------------------------------------
# Whole PDFs: bombs behind each filter and chain are rejected, letters pass
# --------------------------------------------------------------------------------------------------

ZEROS = bytes(4 * 1024 * 1024)
RUN_BOMB = b"\x81\x00" * 40_000  # 80 KB that expand to 5 MB


def _bombs() -> list[object]:
    deflated = zlib.compress(ZEROS, 9)
    return [
        pytest.param(b"/LZWDecode", _zero_bomb(1), id="LZW"),
        pytest.param(b"/RunLengthDecode", RUN_BOMB, id="RunLength"),
        pytest.param(b"[/FlateDecode /LZWDecode]", zlib.compress(_zero_bomb(1)), id="Flate LZW"),
        pytest.param(b"[/LZWDecode /FlateDecode]", _lzw(deflated), id="LZW Flate"),
        pytest.param(b"[/Fl /RL]", zlib.compress(RUN_BOMB), id="Flate RunLength"),
        pytest.param(b"[/RL /Fl]", _run_length(deflated), id="RunLength Flate"),
        pytest.param(b"[/LZW /RL]", _lzw(RUN_BOMB), id="LZW RunLength"),
        pytest.param(b"[/A85 /LZW]", base64.a85encode(_zero_bomb(1)) + b"~>", id="ASCII85 LZW"),
        pytest.param(b"[/AHx /RL]", binascii.hexlify(RUN_BOMB) + b">", id="ASCIIHex RunLength"),
        pytest.param(
            b"[/A85 /Fl]", base64.a85encode(deflated) + b"v~>", id="ASCII85 Flate, a stray character"
        ),
        pytest.param(
            b"[/AHx /Fl]", b"g" + binascii.hexlify(deflated) + b">", id="ASCIIHex Flate, a stray character"
        ),
    ]


@pytest.mark.parametrize(("filters", "data"), _bombs())
def test_a_bomb_behind_each_filter_and_chain_is_rejected(
    small_limits: None, filters: bytes, data: bytes
) -> None:
    with pytest.raises(expansion.ExpansionError, match="expands to far more data"):
        expansion.check_pdf_expansion(_page(filters, data))


@pytest.mark.parametrize(
    ("filters", "data", "parameters"),
    [
        pytest.param(b"/LZWDecode", _lzw(LETTER), b"", id="LZW"),
        pytest.param(
            b"/LZWDecode", _lzw(LETTER, 0), b"/DecodeParms << /EarlyChange 0 >>", id="LZW EarlyChange 0"
        ),
        pytest.param(b"/RunLengthDecode", _run_length(LETTER), b"", id="RunLength"),
        pytest.param(
            b"[/A85 /Fl]", base64.a85encode(zlib.compress(LETTER), wrapcol=72) + b"~>", b"", id="A85 Flate"
        ),
        pytest.param(b"[/AHx /LZW]", binascii.hexlify(_lzw(LETTER)) + b">", b"", id="AHx LZW"),
        pytest.param(b"[/Fl /RL]", zlib.compress(_run_length(LETTER)), b"", id="Flate RunLength"),
    ],
)
def test_a_letter_written_with_each_filter_and_chain_passes(
    small_limits: None, filters: bytes, data: bytes, parameters: bytes
) -> None:
    pdf = _page(filters, data, parameters)
    expansion.check_pdf_expansion(pdf)
    assert "Widerspruch" in _pdfium_text(pdf)  # PDFium reads the page as written
