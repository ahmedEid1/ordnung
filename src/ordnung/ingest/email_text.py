"""E-mail and HTML text: an e-mail's heading and body, and the text a reader sees in an HTML part."""

from __future__ import annotations

import bisect
import email
import email.parser
import email.policy
import itertools
import math
import re
import sys
import unicodedata
from collections import Counter
from collections.abc import Iterator
from email.message import EmailMessage, MIMEPart
from html.parser import HTMLParser
from typing import Any, NamedTuple

from PIL import ImageColor

from ordnung.ingest.amounts import amount_matches
from ordnung.ingest.normalize import fold_punctuation
from ordnung.money.iban import MAX_LENGTH, MIN_LENGTH, inspect_iban

EMAIL_HEADING_CHARS = 200


def email_heading(data: bytes) -> str | None:
    """“Subject · Sender” of an e-mail from its headers alone (no model, no body parsed), e.g. “Ihre
    Rechnung September · Muster Telecom” — what a letter nobody read yet is called. Control and
    formatting characters are dropped and the result is at most :data:`EMAIL_HEADING_CHARS` long;
    ``None`` without a subject or sender."""
    try:
        headers = email.parser.BytesHeaderParser(policy=email.policy.default).parsebytes(data)
        subject = _heading_text(str(headers.get("Subject") or ""))
        sender = _sender_name(headers.get("From"))
    except (ValueError, LookupError, TypeError, AttributeError, IndexError):  # a malformed header
        return None
    heading = " · ".join(part for part in (subject, sender) if part)
    if len(heading) > EMAIL_HEADING_CHARS:
        heading = heading[: EMAIL_HEADING_CHARS - 1].rstrip() + "…"
    return heading or None


def _heading_text(value: str) -> str:
    return " ".join("".join(ch if ch.isprintable() else " " for ch in value).split())


def _sender_name(header: Any) -> str:
    addresses = getattr(header, "addresses", ())
    if not addresses:
        return _heading_text(str(header or ""))
    first = addresses[0]
    return _heading_text(first.display_name or first.addr_spec or "")


def _email_body(message: EmailMessage) -> tuple[str, str]:
    """The text/plain body, or the visible text of the HTML body when there is no plain part or the
    plain part is empty (mail clients show the HTML part then, so its sender never notices).

    Mail programs show the HTML part of an e-mail that has both, so a plain part could name another
    IBAN or amount than the person read: a line of the plain part with an IBAN or amount that the HTML
    part doesn't show is left out of the text and reported as hidden (:func:`_unshown_lines`), a scam
    sign, never text a value is grounded in."""
    part = message.get_body(preferencelist=("plain", "html"))
    if part is None:
        return "", ""
    content = _part_text(part)
    html = message.get_body(preferencelist=("html",))
    if part.get_content_type() == "text/plain" and not content.strip():
        if html is None:
            return content, ""
        part, content = html, _part_text(html)
    if part.get_content_type() == "text/html":
        return html_to_text(content)
    if html is None:
        return content, ""
    shown, _ = html_to_text(_part_text(html))
    return _unshown_lines(content, shown)


#: Words as the GiroCode gate reads a printed IBAN: runs of letters and digits, whatever stands between.
_WORDS = re.compile(r"[^\W_]+")


def _unshown_lines(plain: str, shown: str) -> tuple[str, str]:
    """``plain`` without the lines that name an IBAN or amount ``shown`` (the HTML part's visible text)
    doesn't, and those lines apart (as hidden text).

    Both are found with what grounds a value on the text: an IBAN is any valid IBAN that a run of whole
    words spells (dashes, tabs, line breaks or anything else between its groups, as the GiroCode gate
    joins them), and counts as shown when the HTML part's letters and digits hold it; an amount is what
    :func:`~ordnung.ingest.amounts.amount_matches` reads (``1.200 EUR``, ``99,- €`` included), and counts
    as shown only as the same amount. A value spread over lines takes all of them out. What is left is
    checked again, since taking a line out can join the lines around it into a new value."""
    seen = "".join(_WORDS.findall(fold_punctuation(shown).upper()))
    seen_amounts = {match.value for match in amount_matches(shown)}
    lines = [fold_punctuation(line) for line in plain.splitlines(keepends=True)]
    originals = plain.splitlines(keepends=True)
    kept = list(range(len(lines)))
    unshown: set[int] = set()
    while True:
        text = "".join(lines[index] for index in kept)
        starts = list(itertools.accumulate((len(lines[index]) for index in kept), initial=0))
        spans = [(start, end) for iban, start, end in _ibans(text) if iban not in seen]
        spans += [(m.start, m.end) for m in amount_matches(text) if m.value not in seen_amounts]
        out = {
            kept[position]
            for start, end in spans
            for position in range(bisect.bisect_right(starts, start) - 1, bisect.bisect_left(starts, end))
        }
        if not out:
            break
        unshown |= out
        kept = [index for index in kept if index not in out]
    return "".join(originals[index] for index in kept), "".join(
        originals[index] for index in sorted(unshown)
    ).strip()


def _ibans(text: str) -> Iterator[tuple[str, int, int]]:
    """Every valid IBAN that a run of whole words of ``text`` spells, with where the run starts and
    ends."""
    words = list(_WORDS.finditer(text))  # spans in ``text``: an upper-case letter can be longer
    for first, word in enumerate(words):
        if not word.group()[:1].isascii() or not word.group()[:1].isalpha():
            continue
        joined = ""
        for last in range(first, len(words)):
            joined += words[last].group().upper()
            if len(joined) > MAX_LENGTH:
                break
            if len(joined) >= 4 and not (joined[:2].isalpha() and joined[2:4].isdecimal()):
                break
            if len(joined) >= MIN_LENGTH and inspect_iban(joined).valid:
                yield joined, word.start(), words[last].end()


#: The labels that name ISO-8859-1. Browsers and mail programs read text so labelled as Windows-1252 (WHATWG
#: Encoding), as Windows mail programs write it: "…" and "€" are 0x85 and 0x80, which ISO-8859-1 reads as control
#: characters.
_LATIN_1_LABELS = frozenset({"iso-8859-1", "iso8859-1", "iso_8859-1", "latin-1", "latin1", "l1", "cp819"})
#: Windows-1252's characters for 0x80-0x9F; the five bytes it leaves out keep their ISO-8859-1 meaning.
_C1_AS_WINDOWS_1252 = {
    code: char for code in range(0x80, 0xA0) if (char := bytes([code]).decode("cp1252", errors="ignore"))
}


def _part_text(part: MIMEPart) -> str:
    if (part.get_content_charset() or "").lower() in _LATIN_1_LABELS:
        payload = part.get_payload(decode=True)
        if isinstance(payload, bytes):
            return payload.decode("latin-1").translate(_C1_AS_WINDOWS_1252)
    try:
        return str(part.get_content())
    except (LookupError, UnicodeError):  # unknown or wrong charset
        payload = part.get_payload(decode=True)
        return payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else ""


# -- HTML → text -------------------------------------------------------------------------------------

_BLOCK_TAGS = frozenset(
    {
        "address", "article", "aside", "blockquote", "br", "caption", "center", "dd", "details", "dialog",
        "dir", "div", "dl", "dt", "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3",
        "h4", "h5", "h6", "header", "hgroup", "hr", "li", "main", "menu", "nav", "ol", "p", "pre", "search",
        "section", "summary", "table", "ul",
    }
)  # fmt: skip
_BREAKS = dict.fromkeys(_BLOCK_TAGS, "\n") | {"td": "\t", "th": "\t"}  # and a <tr> starts a line
_REMOVED_TAGS = frozenset({"head", "script", "style", "template", "noscript"})
_HEAD_TAGS = frozenset({"base", "link", "meta", "noscript", "script", "style", "template", "title"})
_VOID_TAGS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
)
#: Optional end tags (point 6). The elements whose end tag may be left out, in groups: a start tag
#: ends the nearest open element of each group it names (in this order), with all opened in it …
_P, _CELL, _ROW, _ROWS, _ITEM, _TERM, _OPTION, _CAPTION = range(8)
_GROUPS = {
    "p": _P, "td": _CELL, "th": _CELL, "tr": _ROW, "thead": _ROWS, "tbody": _ROWS, "tfoot": _ROWS,
    "li": _ITEM, "dt": _TERM, "dd": _TERM, "option": _OPTION, "caption": _CAPTION,
}  # fmt: skip
_ENDS: dict[str, tuple[int, ...]] = dict.fromkeys(_BLOCK_TAGS - {"br", "caption"}, (_P,)) | {
    "td": (_CAPTION, _CELL), "th": (_CAPTION, _CELL), "tr": (_CAPTION, _ROW, _CELL),
    "thead": (_CAPTION, _ROWS, _ROW, _CELL), "tbody": (_CAPTION, _ROWS, _ROW, _CELL),
    "tfoot": (_CAPTION, _ROWS, _ROW, _CELL), "caption": (_CAPTION,), "col": (_CAPTION,),
    "colgroup": (_CAPTION,), "li": (_ITEM, _P), "dt": (_TERM, _P), "dd": (_TERM, _P), "option": (_OPTION,),
}  # fmt: skip
#: … unless an element opened after it keeps it out of reach: a table has its own caption, rows and
#: cells, a cell its own paragraphs and lists, a list its own items (in a scope, -1: none in reach)
_ALL_GROUPS = frozenset(range(8))
_SCOPES: dict[str, frozenset[int]] = {
    **dict.fromkeys(_REMOVED_TAGS | {"table"}, _ALL_GROUPS),
    **dict.fromkeys(("td", "th", "caption"), frozenset({_P, _ITEM, _TERM, _OPTION})),
    **dict.fromkeys(("button", "object"), frozenset({_P})),
    **dict.fromkeys(("ul", "ol"), frozenset({_ITEM})),
    "dl": frozenset({_TERM}),
    "select": frozenset({_OPTION}),
}
_NO_SCOPE = (-1,) * len(_ALL_GROUPS)
MIN_TEXT_CONTRAST = 1.2  # WCAG contrast ratio; below it text is (nearly) the colour of its background
OFFSCREEN_PX = -1000.0  # an absolutely positioned box this far left or up is off the screen
_SPACES = str.maketrans("\t\n\r\f\v", "     ")  # in the output, "\n" ends a line and "\t" a table cell
_GRAPHEME_JOINER = "\u034f"  # &#847;, in preview-text spacers: no glyph, though not a format character
RGB = tuple[float, float, float]
RGBA = tuple[float, float, float, float]
_CSS_COMMENT_OR_STRING_RE = re.compile(r"""/\*.*?(?:\*/|\Z)|"[^"\n]*"?|'[^'\n]*'?""", re.DOTALL)
_CSS_TOKEN_RE = re.compile(r"""[{};]|"[^"\n]*"?|'[^'\n]*'?""")  # a string is one token: "a;b{"
_AT_RULE_RE = re.compile(r"@([\w-]*)(.*)", re.DOTALL)  # @media only screen and (max-width: 480px)
_SCREEN_MEDIA_RE = re.compile(r"(?:(?:only\s+)?(?:all|screen))?")
_SIMPLE_SELECTOR_RE = re.compile(r"(?:[a-z][a-z0-9-]*)?\.[\w-]+|#[\w-]+|[a-z][a-z0-9-]*")  # .x #x p p.x
_SELECTOR_ARGUMENTS_RE = re.compile(r"\[[^\][]*\]|\([^()]*\)")  # [type="x"], :not(.a); "[[" is scanned once
_NAME_RE = re.compile(r"^[a-z][\w-]*|[.#][\w-]+")  # the type, classes and id of a compound selector
_CSS_ESCAPE_RE = re.compile(r"\\(?:([0-9a-f]{1,6})\s?|(.))")  # \: → ":", \31 0 → "10" (a space ends hex)
_MARKED_ESCAPE_RE = re.compile(r"U([0-9A-F]+)U")  # an escaped character while _subject reads a selector
_LENGTH_RE = re.compile(r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?)([a-z%]*)")  # one way to split "99…9"
_RGB_RE = re.compile(r"rgba?\(([^()]*)\)")  # rgb(0, 112, 192), rgba(0,0,0,.5), rgb(0 112 192 / 50%)
_BACKGROUND_WORD_RE = re.compile(r"[a-z-]+\([^()]*\)|#?[\w-]+")  # rgb(0, 0, 0), url(x.png), #fff, red
_IMPORTANT_RE = re.compile(r"!\s*important\s*$")  # "!important", "! important", "!/**/important"
#: font sizes relative to the parent's (point 4): never larger than it, and any other
_NO_LARGER_SIZES = frozenset({"inherit", "unset", "smaller"})
_RELATIVE_SIZES = frozenset({"larger", "revert", "revert-layer"})
_RELATIVE_UNITS = frozenset({"%", "em", "ex", "ch"})
#: an inline ``display`` that makes an element a block, or a table cell, breaks the line (point 7)
_DISPLAY_BREAKS = dict.fromkeys(
    ("block", "flex", "grid", "flow-root", "list-item", "table", "table-caption", "table-row"), "\n"
) | {"table-cell": "\t"}


def _strip_css_comments(css: str) -> str:
    return _CSS_COMMENT_OR_STRING_RE.sub(lambda found: " " if found[0].startswith("/*") else found[0], css)


def _declarations(style: str) -> dict[str, str]:
    """``color: Red; FONT-SIZE: 1px ! important`` → ``{"color": "red", "font-size": "1px"}`` (CSS allows
    spaces and comments after the "!"). A shorthand counts where it stands among them: ``font`` sets
    the font size too (:func:`_shorthand_size`), and ``background`` resets a ``background-color`` or
    ``background-image`` written before it (one written after it is kept next to it)."""
    declarations: dict[str, str] = {}
    for name, _, value in (part.partition(":") for part in _strip_css_comments(style).split(";")):
        name, value = name.strip().lower(), _IMPORTANT_RE.sub("", value.lower()).strip()
        if name == "background":
            declarations.pop("background-color", None)
            declarations.pop("background-image", None)
        declarations[name] = value
        if name == "font":
            declarations["font-size"] = _shorthand_size(value)
    return declarations


def _shorthand_size(font: str) -> str:
    """The size in a ``font`` shorthand: the word before the optional ``/line-height``, else the last
    number (before the family): ``bold 15px/20px Arial`` → ``15px``; ``""`` if there is none
    (``caption``), which is not tiny."""
    if font in ("inherit", "unset", "revert", "revert-layer"):  # the size too
        return font
    before, slash, _ = font.partition("/")
    words = before.split()
    if slash:
        return words[-1] if words else ""
    return next((word for word in reversed(words) if not math.isnan(_length(word)[0])), "")


def _length(value: str | None) -> tuple[float, str]:
    """``"-9999px"`` → ``(-9999.0, "px")``; the number is NaN for anything but a number and a unit."""
    found = _LENGTH_RE.fullmatch((value or "").strip())
    return (float(found[1]), found[2]) if found else (math.nan, "")


def _tiny(font_size: str | None) -> bool:
    """Whether a font size is 0 or at most 1px/1pt."""
    size, unit = _length(font_size)
    return size == 0 or (unit in ("px", "pt") and 0 <= size <= 1)


def _font_size(value: str, parent_tiny: bool, parent_zero: bool) -> tuple[bool, bool]:
    """``(tiny, zero)``: whether an element's font size set to ``value`` is at most 1px/1pt, and
    whether it is 0 (point 4). A size of its own counts (``14px``, ``1rem``, ``small``); one relative
    to the parent's is 0 in a 0, and tiny in a tiny one when it is no larger (``100%``, ``1em``,
    ``smaller``, ``inherit``)."""
    size, unit = _length(value)
    if size == 0:
        return True, True
    if value in _NO_LARGER_SIZES or (unit == "%" and size <= 100) or (unit == "em" and size <= 1):
        return parent_tiny, parent_zero
    if unit in _RELATIVE_UNITS or value in _RELATIVE_SIZES:
        return parent_zero, parent_zero
    return _tiny(value), False


def _hides(style: dict[str, str]) -> bool:
    """Whether declarations hide an element with all it holds: ``display:none``, ``opacity:0``, a zero
    height with ``overflow:hidden``, an absolute position far off to the left or top."""
    opacity, unit = _length(style.get("opacity"))
    heights = (_length(style.get("height"))[0], _length(style.get("max-height"))[0])
    offsets = (_length(style.get("left")), _length(style.get("top")))
    return (
        style.get("display") == "none"
        or (opacity <= 0 and unit in ("", "%"))
        or (style.get("overflow") == "hidden" and 0 in heights)
        or (
            style.get("position") in ("absolute", "fixed")
            and any(u == "px" and n <= OFFSCREEN_PX for n, u in offsets)
        )
    )


def _color(value: str, *, legacy: bool = False) -> RGBA | None:
    """A CSS colour (a name, ``#hex``, ``rgb()``/``rgba()``, ``hsl()``, ``transparent``) as RGBA 0..1;
    ``None`` if it can't be read. ``legacy``: an HTML attribute, whose hex digits may lack the "#"."""
    value = value.strip().lower()
    if legacy and re.fullmatch(r"[0-9a-f]{3}|[0-9a-f]{6}", value):
        value = "#" + value
    if value == "transparent":
        return (0.0, 0.0, 0.0, 0.0)
    if (function := _RGB_RE.fullmatch(value)) is not None:
        parts = [_length(part) for part in re.split(r"[\s,/]+", function[1].strip())]
        if len(parts) not in (3, 4) or any(math.isnan(n) or u not in ("", "%") for n, u in parts):
            return None
        red, green, blue = (min(max(n * (2.55 if u == "%" else 1) / 255, 0.0), 1.0) for n, u in parts[:3])
        alpha = parts[3][0] / (100 if parts[3][1] == "%" else 1) if len(parts) == 4 else 1.0
        return red, green, blue, min(max(alpha, 0.0), 1.0)
    if value in ImageColor.colormap or value.startswith(("#", "hsl(")):
        try:
            red_byte, green_byte, blue_byte, *alpha_byte = ImageColor.getrgb(value)
        except ValueError:
            return None
        return red_byte / 255, green_byte / 255, blue_byte / 255, alpha_byte[0] / 255 if alpha_byte else 1.0
    return None


def _background(style: dict[str, str], values: dict[str, str]) -> tuple[bool, RGBA | None]:
    """Whether an element sets a background inline, and its colour (``None``: an image, or unread). A
    ``background-color`` next to the ``background`` shorthand was written after it (:func:`_declarations`):
    its colour counts, but an image in the shorthand still covers it."""
    if style.get("background-image", "none") != "none" or "background" in values:  # <td background=…>
        return True, None
    given = [value for name in ("background", "background-color") if (value := style.get(name)) is not None]
    if not given:
        return "bgcolor" in values, _color(values.get("bgcolor", ""), legacy=True)
    words = [_BACKGROUND_WORD_RE.findall(value) for value in given]  # none repeat scroll 0% 0% rgb(192, 0, 0)
    if any(word.endswith(")") and not word.startswith(("rgb", "hsl")) for word in itertools.chain(*words)):
        return True, None  # url(), linear-gradient(), var() …
    colors = [color for word in words[-1] if (color := _color(word)) is not None]
    return True, colors[0] if len(colors) == 1 else None


def _painted(color: RGBA | None, below: RGB | None) -> RGB | None:
    """What a (semi-transparent) colour looks like on what is below it; ``None`` if that's unknown."""
    if color is None or (below is None and color[3] < 1):
        return None
    if below is None or color[3] == 1:
        return color[:3]
    red, green, blue = (color[3] * c + (1 - color[3]) * b for c, b in zip(color[:3], below, strict=False))
    return red, green, blue


def _contrast(first: RGB, second: RGB) -> float:
    """WCAG contrast ratio of two colours (1 = identical, 21 = black on white)."""

    def luminance(rgb: RGB) -> float:
        red, green, blue = (c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb)
        return 0.2126 * red + 0.7152 * green + 0.0722 * blue

    light, dark = sorted((luminance(first), luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def _screen_media(query_list: str) -> bool:
    """Whether a media query list names the media types all/screen only (``only screen``, ``all``)."""
    return all(_SCREEN_MEDIA_RE.fullmatch(query.strip()) for query in query_list.lower().split(","))


def _css_rules(css: str, *, on_screen: bool) -> Iterator[tuple[str, str, bool]]:
    """``(selectors, declarations, on screens)`` of each style rule of a style sheet, nested ones too
    (without recursion). A rule's declarations are the text directly in its block, around the rules
    nested in it (so each character is read once). An at-rule nested in a style rule (CSS Nesting:
    ``.x { @media (…) { display: block } }``) is a rule of the same selectors, never on screens. *On
    screens*: at the top level of an on-screen sheet, or inside ``@media`` blocks of the media types
    all/screen only."""
    css = _strip_css_comments(css).replace("<!--", " ").replace("-->", " ")
    #: the open blocks: a rule's selectors (None: an at-rule outside style rules), the text directly
    #: in its body so far, and whether the rules in it are on screens
    blocks: list[tuple[str | None, list[str], bool]] = []
    statement = 0  # where the current at-rule, list of selectors or declaration starts
    body = 0  # where the text directly in the innermost open block continues
    for token in _CSS_TOKEN_RE.finditer(css):
        position = token.start()
        if token[0] == "{":
            prelude, screen = css[statement:position].strip(), blocks[-1][2] if blocks else on_screen
            if blocks:
                blocks[-1][1].append(css[body:statement])  # up to the prelude of the nested block
            if (at_rule := _AT_RULE_RE.match(prelude.lower())) is not None:
                screen = screen and at_rule[1] == "media" and _screen_media(at_rule[2])
                blocks.append((blocks[-1][0] if blocks else None, [], screen))  # in a rule: its selectors
            else:
                blocks.append((prelude, [], False))
            body = position + 1
        elif token[0] == "}" and blocks:
            selectors, texts, _ = blocks.pop()
            if selectors is not None:
                texts.append(css[body:position])
                yield selectors, ";".join(texts), blocks[-1][2] if blocks else on_screen
            body = position + 1
        if token[0] in "{};":
            statement = position + 1


def _subject(selector: str) -> set[str]:
    """The lower-case names of the elements a selector styles: ``.a > p.note:hover`` → ``{"p",
    ".note"}``, ``.sm\\:block`` → ``{".sm:block"}`` (an escaped character is part of the name);
    ``{"*"}`` (any element) for ``*``, ``[class=x]``, ``:root`` …"""
    # while the selector is taken apart, an escaped character is "U<code point>U", name characters
    # that a lower-case selector has nowhere else
    plain = _CSS_ESCAPE_RE.sub(_marked_escape, selector.strip().lower())
    plain = _SELECTOR_ARGUMENTS_RE.sub(lambda found: found[0][0], plain)  # [x] → [
    compound = re.split(r"[\s>+~]+", plain)[-1]
    names = {_MARKED_ESCAPE_RE.sub(_unmarked_escape, name) for name in _NAME_RE.findall(compound)}
    return names or ({"*"} if compound[:1] in ("*", "[", ":", "&") else set())


def _marked_escape(found: re.Match[str]) -> str:
    code = int(found[1], 16) if found[1] else ord(found[2])
    return f"U{code if 0 < code <= sys.maxunicode else 0xFFFD:X}U"  # CSS reads \0 as U+FFFD


def _unmarked_escape(found: re.Match[str]) -> str:
    return chr(int(found[1], 16)).lower()


class _StyleSheet:
    """What the ``<style>`` blocks of an e-mail say, as far as the policy asks (point 5)."""

    def __init__(self) -> None:
        #: the context-free declarations of the hiding simple rules on screens, by selector (".x", "#x",
        #: "p", "p.x"; class names and ids are case-sensitive)
        self.hiding: dict[str, dict[str, str]] = {}
        #: the names (".x", "#x", "p" in lower case; "*": any) of elements some rule may show (display
        #: other than none, visibility:visible, a font size above 1px), colour or give a background
        self.showing: set[str] = set()
        self.coloring: set[str] = set()
        self.backgrounding: set[str] = set()

    def add(self, css: str, *, on_screen: bool) -> None:
        for selectors, body, rule_on_screen in _css_rules(css, on_screen=on_screen):
            declarations = _declarations(body)
            context_free: dict[str, str] = {
                name: declarations[name]
                for name in ("display", "visibility", "opacity", "font-size")
                if name in declarations
            }
            hides = _hides(context_free) or context_free.get("visibility") == "hidden"
            hides = hides or _tiny(context_free.get("font-size"))
            # a display other than none shows whatever else the rule sets (a fade-in starts at
            # opacity:0); a font size only where the rule doesn't also take the element away
            shows = (
                context_free.get("display", "none") != "none"
                or context_free.get("visibility") == "visible"
                or (
                    "font-size" in context_free
                    and not _tiny(context_free["font-size"])
                    and context_free.get("display") != "none"
                    and context_free.get("visibility") != "hidden"
                )
            )
            for selector in selectors.split(","):
                if hides and rule_on_screen and _SIMPLE_SELECTOR_RE.fullmatch(selector.strip()):
                    self.hiding.setdefault(selector.strip(), {}).update(context_free)
                subject = _subject(selector)
                if shows:
                    self.showing |= subject
                if "color" in declarations:
                    self.coloring |= subject
                if any(name.startswith("background") for name in declarations):
                    self.backgrounding |= subject


class _Box(NamedTuple):
    """An open element, and how the text in it looks."""

    tag: str
    removed: bool = False  # in <head>, <script>, <style>, <template> or <noscript>
    hides: bool = False  # the text in it is hidden (by one of the next three, or by its colours)
    hidden: bool = False  # display:none, opacity:0 … on it or further out: nothing inside shows
    invisible: bool = False  # visibility:hidden in effect
    tiny: bool = False  # a font size of at most 1px in effect
    zero: bool = False  # a font size of 0 in effect (a relative size in it is 0 too)
    color: RGBA | None = None  # the text colour given inline (None: not given, or a rule may set it)
    background: RGB | None = None  # the background colour given inline (the same)
    breaks: str = ""  # the line break or cell break its inline display makes ("\n", "\t")


_ROOT = _Box("")


class _Reader(HTMLParser):
    """Reads an HTML e-mail in two steps: :meth:`feed` records its tags and texts and collects its style
    sheets (they apply to the elements before them too); :meth:`read` then walks the recorded tags."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._events: list[tuple[str, str, list[tuple[str, str | None]]]] = []  # start/end: tag; text
        self._sheets: list[tuple[list[str], bool]] = []  # the text of each <style>, and if it's on screens
        self._text: list[str] = []  # the text since the last tag
        self._style: list[str] | None = None  # the text of the open <style>
        self._sheet = _StyleSheet()
        self._out: tuple[list[str], list[str]] = ([], [])  # visible and hidden text
        #: until the first visible text, hidden text is the preview text (point 4): written as visible
        self._leading = True
        self._previewed = False  # preview text with a glyph was written
        self._stack: list[_Box] = []
        self._open: Counter[str] = Counter()  # the tags of the open elements
        #: for each open element, where in the stack the nearest open element of each group is that a
        #: start tag in it may end (see _ENDS): kept per level, so no start tag walks the stack
        self._scopes: list[tuple[int, ...]] = []
        #: the box of an element by tag, attributes and parent: the same element in the same place (a
        #: newsletter's repeated blocks, a deep stack of <div>s) is worked out once
        self._boxes: dict[tuple[str, tuple[tuple[str, str | None], ...], _Box], _Box] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._text:
            self._flush()
        self._events.append(("start", tag, attrs))
        if tag == "style":
            self._style = []
            self._sheets.append((self._style, _screen_media(dict(attrs).get("media") or "")))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in _VOID_TAGS:  # <br/> is one line break
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if self._text:
            self._flush()
        self._events.append(("end", tag, []))
        if tag == "style":
            self._style = None

    def handle_data(self, data: str) -> None:
        (self._text if self._style is None else self._style).append(data)

    def _flush(self) -> None:
        self._events.append(("text", "".join(self._text), []))
        self._text = []

    def read(self) -> tuple[str, str]:
        """``(visible text, hidden text)`` of what was fed."""
        self.close()
        if self._text:
            self._flush()
        for texts, on_screen in self._sheets:
            self._sheet.add("".join(texts), on_screen=on_screen)
        for kind, value, attrs in self._events:
            if kind == "start":
                self._start(value, attrs)
            elif kind == "end":
                self._end(value)
            else:
                self._write(value)
        return _tidy_lines("".join(self._out[0])), _tidy_lines("".join(self._out[1]))

    def _start(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._open["head"] and tag not in _HEAD_TAGS:  # <body> (or body content) ends an open <head>
            self._end("head")
        for group in _ENDS.get(tag, ()):  # <td> ends the open cell of its row, <p> an open <p> …
            if self._scopes and (index := self._scopes[-1][group]) >= 0:
                self._end(self._stack[index].tag)
        key = (tag, tuple(attrs), self._stack[-1] if self._stack else _ROOT)
        if key not in self._boxes:
            self._boxes[key] = self._box(*key)
        box = self._boxes[key]
        self._break(_BREAKS.get(tag, "\n" if tag == "tr" else "") or box.breaks)
        if tag not in _VOID_TAGS:
            self._scopes.append(self._scope(tag))
            self._stack.append(box)
            self._open[tag] += 1

    def _scope(self, tag: str) -> tuple[int, ...]:
        """The scope of the elements in a new ``tag`` element: its parent's, with the groups it keeps out
        of reach emptied and its own group's entry the element itself."""
        scope = self._scopes[-1] if self._scopes else _NO_SCOPE
        hides, own = _SCOPES.get(tag, frozenset()), _GROUPS.get(tag)
        if not hides and own is None:
            return scope
        return tuple(
            len(self._stack) if group == own else -1 if group in hides else index
            for group, index in enumerate(scope)
        )

    def _end(self, tag: str) -> None:
        """Closes the nearest open element of the tag and all opened in it; a stray end tag is ignored
        (counting the open tags keeps both linear)."""
        separator = _BREAKS.get(tag, "")
        if self._open[tag]:
            while (box := self._stack.pop()).tag != tag:
                self._open[box.tag] -= 1
            self._open[tag] -= 1
            del self._scopes[len(self._stack) :]
            separator = separator or box.breaks
        self._break(separator)

    def _write(self, text: str) -> None:
        if self._stack and self._stack[-1].tag == "head" and not text.isspace():  # text ends <head>
            self._end("head")
        box = self._stack[-1] if self._stack else _ROOT
        if box.removed:
            return
        text = text.translate(_SPACES)
        if self._leading:  # no visible text yet: hidden text is the preview text, a paragraph of its own
            if box.hides:
                self._previewed = self._previewed or _has_glyph(text)
                self._out[0].append(text)
                return
            if _has_glyph(text):
                self._leading = False
                if self._previewed:
                    self._out[0].append("\n\n")
        self._out[box.hides].append(text)

    def _break(self, separator: str) -> None:
        self._out[0].append(separator)
        self._out[1].append(separator)

    def _box(self, tag: str, attrs: tuple[tuple[str, str | None], ...], parent: _Box) -> _Box:
        if parent.removed or tag in _REMOVED_TAGS:
            return _Box(tag, removed=True)
        values: dict[str, str] = {}
        for name, value in attrs:
            values.setdefault(name, value or "")  # of a repeated attribute, browsers keep the first
        classes, identifier = values.get("class", "").split(), values.get("id", "")
        style: dict[str, str] = {}
        for key in (tag, f"#{identifier}", *(f".{c}" for c in classes), *(f"{tag}.{c}" for c in classes)):
            style.update(self._sheet.hiding.get(key, {}))
        inline = _declarations(values.get("style", ""))
        style.update(inline)  # the style attribute wins over the rules (!important is not considered)
        names = {"*", tag, f"#{identifier.lower()}", *(f".{name.lower()}" for name in classes)}
        uncertain = not names.isdisjoint(self._sheet.showing)  # its own styles don't hide it
        hidden = parent.hidden or (not uncertain and ("hidden" in values or _hides(style)))
        visibility = "visible" if uncertain else style.get("visibility")
        invisible = visibility == "hidden" or (parent.invisible and visibility != "visible")
        if "font-size" in style:  # also set by the font shorthand (_declarations)
            tiny, zero = _font_size(style["font-size"], parent.tiny, parent.zero)
        elif tag == "font" and "size" in values:  # <font size="1"> is 10px: a size, and never a tiny one
            tiny = zero = False
        else:
            tiny, zero = parent.tiny, parent.zero
        tiny, zero = tiny and not uncertain, zero and not uncertain
        color = parent.color
        if not names.isdisjoint(self._sheet.coloring):
            color = None
        elif "color" in inline or (tag == "font" and "color" in values):
            color = _color(inline["color"]) if "color" in inline else _color(values["color"], legacy=True)
        elif tag == "a" and "href" in values:  # a link has the mail client's link colour
            color = None
        background = parent.background
        sets_background, paint = _background(inline, values)
        if not names.isdisjoint(self._sheet.backgrounding):
            background = None
        elif sets_background and (paint is None or paint[3] > 0):  # transparent: the parent's shows
            background = _painted(paint, background)
        faint = False
        if (text_color := _painted(color, background)) is not None and background is not None:
            faint = _contrast(text_color, background) < MIN_TEXT_CONTRAST
        hides = hidden or invisible or tiny or faint
        breaks = _DISPLAY_BREAKS.get(inline.get("display", ""), "")
        return _Box(tag, False, hides, hidden, invisible, tiny, zero, color, background, breaks)


def html_to_text(markup: str) -> tuple[str, str]:
    """``(visible text, hidden text)`` of an HTML e-mail, following this policy (and nothing else;
    cases outside it are accepted limitations):

    1. The visible text is what the model reads. The hidden text is text Ordnung is *certain* no
       reader sees in any mail client; it is reported as hidden text (a scam sign) and never sent to
       the model.
    2. Never drop on uncertainty: when in doubt, text is visible. Other layers defend against
       injected instructions (untrusted wrapping, a tool-less extraction model, injection-phrase
       detection on the visible text, dates computed by code, grounding against the page).
    3. Removed, and not hidden text: ``<head>``, ``<script>``, ``<style>``, ``<template>``,
       ``<noscript>`` and comments, Outlook's conditional comments included (``<!--[if mso]>…
       <![endif]-->`` is an Outlook-only copy of content that other clients show from elsewhere).
    4. Certainly hidden, decided from the inline ``style`` and the ``hidden`` attribute of the
       element or an ancestor: ``display:none``; ``visibility:hidden`` (unless a descendant sets
       ``visibility:visible`` inline); ``opacity:0``; a font size of 0 or at most 1px/1pt (the
       nearest one set counts: a column sized inside a ``font-size:0`` wrapper is visible; the
       ``font`` shorthand sets one too, and ``<font size>`` one that is never tiny; a size relative
       to the parent's — ``%``, ``em``, ``ex``, ``ch``, ``smaller``, ``larger``, ``inherit`` — is 0
       in a 0, and tiny in a tiny one when it is no larger: ``100%``, ``1em``, ``smaller``);
       ``height:0`` or ``max-height:0`` together with ``overflow:hidden``;
       ``position:absolute``/``fixed`` with ``left`` or ``top`` at -1000px or less; a text
       colour and a background colour both given inline with a contrast ratio below 1.2. The text
       colour is the element's or an ancestor's (``<font color>`` too; a link has the client's
       link colour), the background the one of the nearest element that sets one (``bgcolor``
       too; an image or a colour that can't be read is unknown; of its declarations the later one
       counts: a ``background`` shorthand resets a ``background-color`` before it). ``mso-hide:all``
       is *not* hidden: it hides only in Outlook, every other client shows it. Hidden text before
       the first visible text is *not* hidden text either: it is the preview text (preheader) that
       every mail client shows in the inbox list next to the subject, so it is visible text, a
       paragraph of its own (the model reads it like the subject).
    5. ``<style>`` rules hide only when they are at the top level or inside ``@media`` blocks of the
       media types all/screen only (in a ``<style>`` whose ``media`` is unset or all/screen), have
       a simple selector (``.class``, ``#id``, ``tag``, ``tag.class``; comma lists allowed), and
       only by ``display:none``, ``visibility:hidden``, ``opacity:0`` or a font size of 0 or at
       most 1px/1pt. But a class, id or tag that any *other* rule may show — in any at-rule block
       (one nested in a style rule too) or style sheet (``media="print"`` too), with any selector
       (an escaped name such as Tailwind's ``.sm\\:block`` too) — by a display other than none or
       ``visibility:visible`` (whatever else the rule sets: a fade-in starts at ``opacity:0``), or by
       another font size in a rule without ``display:none`` or ``visibility:hidden``, is uncertain:
       its elements are not hidden, by rules or inline styles (the phone copy of a responsive e-mail
       and a dark-mode copy stay visible). A rule that may give an element a colour or a
       background makes that colour unknown (a stylesheet-coloured cell is visible). A rule whose
       last compound names no type, class or id (``*``, ``[class=x]``) may concern any element.
    6. Robust: linear time in the size of the e-mail, no recursion on the nesting depth, tolerant of
       broken HTML (``html.parser``): an end tag closes the nearest open element of its name and all
       opened in it, a stray end tag is ignored, void elements hold nothing. Left-out end tags are
       implied where every browser implies them, so a missing one can't remove or hide a letter:
       ``</head>`` at ``<body>`` or other body content; a caption at the next caption, row, cell,
       row group or column of its table; a cell at the next cell, row or row group of its table, a
       row at the next row or row group; a list item (``li``, ``dt``/``dd``, ``option``) at the next
       one of its list; a ``<p>`` at a block (``<table>`` too) outside the cells, captions and
       buttons opened in it. (HTML's other implied end tags are not.)
    7. Block elements and ``<br>`` break lines, as does an inline ``display`` that makes an element a
       block (``block``, ``flex``, ``grid``, ``list-item``, ``table``, ``table-row`` …); a table row
       is a line with its cells (``display:table-cell`` too) three spaces apart; whitespace is
       collapsed and entities are decoded. Characters without a glyph (format characters such as
       ``&zwnj;`` and ``&shy;``, and U+034F) are dropped: a preview-text spacer made of them is no
       hidden text.
    """
    reader = _Reader()
    reader.feed(markup)
    return reader.read()


def _tidy_lines(text: str) -> str:
    """A run of breaks becomes one line break or one blank line, cells are three spaces apart, and runs
    of spaces one space (:func:`_words`). (A run starts at a line break, so no text is scanned twice.)"""
    text = re.sub(r"\n[\n\t ]*", lambda run: "\n\n" if run[0].count("\n") > 1 else "\n", text)
    lines = (
        "   ".join(cell for part in line.split("\t") if (cell := _words(part))) for line in text.split("\n")
    )
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _words(text: str) -> str:
    """``text`` with runs of spaces as one space and without the characters that have no glyph: format
    characters (Unicode category Cf: zero-width spaces and joiners, the soft hyphen, the BOM, direction
    marks …) and the combining grapheme joiner U+034F."""
    words = " ".join(text.split())
    if words.isprintable() and _GRAPHEME_JOINER not in words:  # no format character (most text)
        return words
    kept = (char for char in words if char != _GRAPHEME_JOINER and unicodedata.category(char) != "Cf")
    return " ".join("".join(kept).split())


def _has_glyph(text: str) -> bool:
    """Whether ``text`` has a character a reader sees (not whitespace, and not one :func:`_words`
    drops)."""
    return any(
        not char.isspace() and char != _GRAPHEME_JOINER and unicodedata.category(char) != "Cf"
        for char in text
    )
