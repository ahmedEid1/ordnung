"""The report page (``python -m evals.present --site DIR``): one static HTML file, no script, standard library only.

It is built from ``presentation.json`` alone, so the Pages job needs no install and never imports ``ordnung``:
``index.html`` with every chart inline (a wide and a narrow layout, switched by a 600 px media query, coloured by
CSS variables for light and dark), a table and a CSV behind every chart, ``data.json`` (``presentation.json`` as it
is) and the README's charts (``eval-*-{light,dark}.svg``), which PyPI's copy of the README loads from here.

:func:`check_site` fails on a chart without its description or table, a link to nowhere, a picture without alt
text, a number the presenter does not render from ``presentation.json``, or a sentence of a benchmark letter (named
by its hash, never printed).
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections.abc import Mapping, Sequence
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from evals.present import PAGES_URL, REPO_URL, ROOT, charts, fmt, palette, text

TITLE = "Ordnung evaluation"
DESCRIPTION = (
    "How well Ordnung reads German letters and dates their deadlines: held-out results against three baselines on "
    "the same model, with intervals, safety, failures and cost."
)
#: Fields of the dataset manifest that never hold a letter's words (ids, files, hashes, codes).
_NOT_TEXT = frozenset(
    {"id", "file", "sha256", "source_id", "family", "split", "media_type", "photo", "variant"}
)


def _tokens(theme: Mapping[str, str]) -> str:
    return "".join(f"--{role.replace('_', '-')}:{value};" for role, value in theme.items())


CSS = (
    f":root{{color-scheme:light;{_tokens(palette.LIGHT)}}}"
    f'@media (prefers-color-scheme: dark){{:root:not([data-theme="light"]){{color-scheme:dark;'
    f"{_tokens(palette.DARK)}}}}}"
    f':root[data-theme="dark"]{{color-scheme:dark;{_tokens(palette.DARK)}}}'
    """
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--surface);color:var(--text);font:16px/1.55 Inter,-apple-system,'Segoe UI',Helvetica,Arial,sans-serif}
main{max-width:820px;margin:0 auto;padding:24px 16px 64px}
a{color:var(--link)}
h1{font-size:30px;line-height:1.2;margin:12px 0 6px}
h2{font-size:22px;line-height:1.3;margin:44px 0 10px}
h3{font-size:18px;margin:28px 0 8px}
p,li{overflow-wrap:anywhere}
.top{font-size:15px;margin:0}
.top a{display:inline-block;min-height:24px;padding:2px 0}
.lede{color:var(--text2);font-size:17px;margin:0 0 20px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin:16px 0 24px;padding:0;list-style:none}
.tile{border:1px solid var(--grid);border-radius:8px;padding:12px 14px}
.tile .v{display:block;font-size:30px;font-weight:600;line-height:1.15}
.tile .l{display:block;color:var(--text2);font-size:15px}
figure{margin:20px 0}
figcaption{color:var(--text2);font-size:15px;margin-top:8px}
svg{display:block;max-width:100%;height:auto}
.narrow{display:none}
@media (max-width:600px){.wide{display:none}.narrow{display:block}}
details{margin-top:8px}
summary{cursor:pointer;color:var(--link);min-height:24px}
.tablewrap{overflow-x:auto;margin:8px 0}
table{border-collapse:collapse;font-size:14px;font-variant-numeric:tabular-nums}
caption{text-align:left;color:var(--text2);font-size:14px;padding:0 0 4px}
th,td{border-bottom:1px solid var(--grid);padding:5px 10px;text-align:left;vertical-align:top}
thead th{border-bottom:1px solid var(--axis)}
code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.9em;overflow-wrap:anywhere}
pre{margin:0;border:1px solid var(--grid);border-radius:6px;padding:10px 12px;font-size:14px;width:max-content;min-width:100%}
pre code{overflow-wrap:normal}
nav.toc{font-size:15px;border:1px solid var(--grid);border-radius:8px;padding:8px 14px;margin:24px 0}
nav.toc ul{columns:2;margin:4px 0;padding:0;list-style:none}
nav.toc li a{display:inline-block;min-height:24px;padding:2px 0}
@media (max-width:600px){nav.toc ul{columns:1}}
footer{color:var(--text2);font-size:14px;margin-top:48px;border-top:1px solid var(--grid);padding-top:12px}
"""
)


# --------------------------------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------------------------------


def inline(value: str) -> str:
    """The report's inline markup as HTML: code, links (``repo:`` to GitHub), bold and italic."""
    parts = value.split("`")
    out = []
    for i, part in enumerate(parts):
        if i % 2:
            out.append(f"<code>{escape(part)}</code>")
            continue
        html = escape(part, quote=False)

        def link(match: re.Match[str]) -> str:
            target = match.group(2)
            href = text.site_link(target) if target.startswith("repo:") else target
            return f'<a href="{escape(href)}">{match.group(1)}</a>'

        html = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, html)
        html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)
        html = re.sub(r"(?<![\w*])\*([^*]+?)\*(?![\w*])", r"<em>\1</em>", html)
        out.append(html)
    return "".join(out)


def _table(header: Sequence[str], rows: Sequence[Sequence[str]], caption: str) -> str:
    head = "".join(f'<th scope="col">{inline(h)}</th>' for h in header)
    body = "".join(
        "<tr>"
        + "".join(
            f'<th scope="row">{inline(cell)}</th>' if i == 0 else f"<td>{inline(cell)}</td>"
            for i, cell in enumerate(row)
        )
        + "</tr>"
        for row in rows
    )
    return (
        f'<div class="tablewrap" tabindex="0" role="region" aria-label="{escape(caption)}"><table>'
        f"<caption>{escape(caption)}</caption><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"
    )


def csv_text(header: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue()


def caption(name: str, doc: Mapping[str, Any]) -> str:
    """The chart's one-line "What this shows", generated from the numbers."""
    conditions = doc["headline"]["conditions"]
    o, alone, agent = (conditions[c] for c in ("ordnung", "llm_only", "llm_rules_tool"))
    if name == "held-out":
        return (
            f"Ordnung dates {fmt.pct(o['exact']['value'])} exactly right with {o['harmful']['k']} harmful dates; the "
            f"model alone {fmt.pct(alone['exact']['value'])} with {alone['harmful']['k']}; the agent given the engine "
            f"as a tool {fmt.pct(agent['exact']['value'])} with {agent['harmful']['k']}."
        )
    if name == "timeline":
        return (
            "The dev split was tuned on and the test split iterated on; each held-out split was written before any "
            "recording on it and recorded once."
        )
    if name == "differences":
        parts = []
        for baseline in (c for c in doc["order"] if c != "ordnung"):
            pair = doc["headline"]["paired"]["accuracy"][f"ordnung-vs-{baseline}"]
            parts.append(f"against {palette.LABELS[baseline]}, {text.verdict(pair)}")
        return "Exact dates, one read: " + "; ".join(parts) + "."
    if name == "risk-coverage":
        flags = doc["headline"]["flags"]
        return (
            f"Holding back flagged dates would not make Ordnung's shown dates safer: “Please check” caught "
            f"{flags['caught']} of its {flags['wrong']} wrong dates."
            if flags["caught"] == 0
            else f"“Please check” caught {flags['caught']} of Ordnung's {flags['wrong']} wrong dates."
        )
    costs = {c: conditions[c]["cost"] for c in doc["order"]}
    dearest = max(costs, key=lambda c: costs[c]["usd_per_letter"])
    return (
        f"{palette.LABELS[dearest]} is the dearest per letter ({fmt.usd(costs[dearest]['usd_per_letter'])}); each "
        "condition's cost per right date is in the table."
    )


def _figure(name: str, doc: Mapping[str, Any]) -> str:
    header, rows = charts.table(name, doc)
    return (
        f'<figure id="{name}"><div class="wide">{charts.svg(name, doc, "css")}</div>'
        f'<div class="narrow">{charts.svg(name, doc, "css", narrow=True)}</div>'
        f"<figcaption>What this shows: {escape(caption(name, doc))}</figcaption>"
        f"<details><summary>Show the numbers as a table</summary>"
        f"{_table(header, rows, charts.title(name) + ' (table)')}"
        f'<p><a href="{name}.csv" download>Download the numbers (CSV)</a></p></details></figure>'
    )


def _blocks(blocks: Sequence[text.Block], doc: Mapping[str, Any]) -> str:
    out = []
    for block in blocks:
        if isinstance(block, text.Paragraph):
            out.append(f"<p>{inline(block.text)}</p>")
        elif isinstance(block, text.Bullets):
            out.append("<ul>" + "".join(f"<li>{inline(item)}</li>" for item in block.items) + "</ul>")
        elif isinstance(block, text.Table):
            out.append(_table(block.header, block.rows, block.caption))
        elif isinstance(block, text.Chart):
            out.append(_figure(block.name, doc))
        elif isinstance(block, text.Code):
            out.append(
                '<div class="tablewrap" tabindex="0" role="region" aria-label="Commands">'
                "<pre><code>" + escape("\n".join(block.lines)) + "</code></pre></div>"
            )
        else:
            out.append(f"<h3>{inline(block.text)}</h3>")
    return "".join(out)


def page(doc: Mapping[str, Any], *, commit: str | None = None) -> str:
    """``index.html`` of the report page."""
    conditions = doc["headline"]["conditions"]
    o, alone = conditions["ordnung"], conditions["llm_only"]
    sections = text.sections(doc)
    tiles = (
        '<ul class="tiles" aria-label="The headline">'
        f'<li class="tile"><span class="v">{fmt.pct(o["exact"]["value"])}</span><span class="l">deadlines dated '
        f"exactly right by Ordnung ({fmt.of(o['exact'])}, held out)</span></li>"
        f'<li class="tile"><span class="v">{fmt.of(o["harmful"])}</span><span class="l">late or missed with '
        f"Ordnung, against {alone['harmful']['k']} for the model alone</span></li>"
        f'<li class="tile"><span class="v">{fmt.pct(alone["exact"]["value"])}</span><span class="l">the same model '
        f"doing the date arithmetic itself ({fmt.of(alone['exact'])})</span></li></ul>"
    )
    toc = "".join(f'<li><a href="#{s.anchor}">{escape(s.title)}</a></li>' for s in sections)
    body = "".join(
        f'<section id="{s.anchor}" aria-labelledby="{s.anchor}-h"><h2 id="{s.anchor}-h">{escape(s.title)}</h2>'
        f"{_blocks(s.blocks, doc)}</section>"
        for s in sections
    )
    built = f", commit <code>{escape(commit)}</code>" if commit else ""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{TITLE}</title>
<meta name="description" content="{escape(DESCRIPTION)}">
<style>{CSS}</style>
</head>
<body>
<main>
<p class="top"><a href="../">Online demo</a> · <a href="{REPO_URL}">Source</a> · <a href="{REPO_URL}/blob/main/docs/evals.md">This report on GitHub</a></p>
<h1>{TITLE}</h1>
<p class="lede">The model reads the letter; tested code computes the deadline. Does that beat the same model doing the date arithmetic itself? Measured on synthetic letters nothing was tuned on, against three baselines that use the same model.</p>
{tiles}
<nav class="toc" aria-label="Report sections"><ul>{toc}</ul></nav>
{body}
<footer><p>Built by <code>python -m evals.present --site</code> from <a href="data.json">presentation.json</a>{built}, never by hand. Every number replays from the recorded answers with no model call: <a href="#15-reproduce">Reproduce</a>. This page: <a href="{PAGES_URL}">{PAGES_URL}</a>.</p></footer>
</main>
</body>
</html>
"""


def dumps(doc: Mapping[str, Any]) -> str:
    """``presentation.json``'s text (as :func:`evals.present.model.dumps` writes it)."""
    return json.dumps(doc, ensure_ascii=False, indent=1) + "\n"


def build_site(doc: Mapping[str, Any], out: Path, *, commit: str | None = None) -> list[Path]:
    """Write the report page into ``out``; returns the files written."""
    out.mkdir(parents=True, exist_ok=True)
    files = {"index.html": page(doc, commit=commit), "data.json": dumps(doc)}
    for name in charts.NAMES:
        header, rows = charts.table(name, doc)
        files[f"{name}.csv"] = csv_text(header, rows)
    for name in charts.COMMITTED:
        for theme in ("light", "dark"):
            files[f"eval-{name}-{theme}.svg"] = charts.svg(name, doc, theme)
    written = []
    for name, content in files.items():
        path = out / name
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return written


# --------------------------------------------------------------------------------------------------
# Checking a built page
# --------------------------------------------------------------------------------------------------


class _Page(HTMLParser):
    """What the check needs from a page: ids, in-page links, pictures, figures and the visible text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: set[str] = set()
        self.links: list[str] = []
        self.images: list[dict[str, str | None]] = []
        self.figures: dict[str, dict[str, Any]] = {}
        self._figure: str | None = None
        self._in: list[str] = []
        self.text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.add(str(values["id"]))
        if tag == "a" and values.get("href"):
            self.links.append(str(values["href"]))
        if tag == "img":
            self.images.append(values)
        if tag == "figure":
            self._figure = str(values.get("id") or "")
            self.figures[self._figure] = {
                "svg": 0,
                "titles": 0,
                "descs": 0,
                "tables": 0,
                "csv": [],
                "empty": 0,
            }
        elif self._figure is not None:
            figure = self.figures[self._figure]
            if tag == "svg" and values.get("role") == "img" and values.get("aria-labelledby"):
                figure["svg"] += 1
            if tag == "title" and values.get("id"):
                figure["titles"] += 1
            if tag == "desc" and values.get("id"):
                figure["descs"] += 1
            if tag == "table":
                figure["tables"] += 1
            if tag == "a" and str(values.get("href", "")).endswith(".csv"):
                figure["csv"].append(values["href"])
        self._in.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag == "figure":
            self._figure = None
        if self._in and self._in[-1] == tag:
            self._in.pop()

    def handle_data(self, data: str) -> None:
        if self._in and self._in[-1] == "desc" and self._figure is not None and not data.strip():
            self.figures[self._figure]["empty"] += 1
        if not (self._in and self._in[-1] in ("style", "title", "desc")):
            self.text.append(data)


_PERCENT = re.compile(r"\d+(?:\.\d+)? %")
_OF = re.compile(r"\b\d+ of \d+\b")


def _numbers(html: str) -> set[str]:
    parsed = _Page()
    parsed.feed(html)
    words = " ".join(" ".join(parsed.text).split())
    return set(_PERCENT.findall(words)) | set(_OF.findall(words))


def dataset_sentences(manifest: Path | None = None) -> tuple[str, ...]:
    """The benchmark letters' sentences (label quotes, key and hidden phrases): what no page may hold."""
    path = manifest or ROOT / "evals" / "dataset" / "manifest.json"
    if not path.is_file():
        return ()
    data = json.loads(path.read_text(encoding="utf-8"))
    found: set[str] = set()

    def walk(value: Any, key: str = "") -> None:
        if isinstance(value, dict):
            for name, inner in value.items():
                if name not in _NOT_TEXT:
                    walk(inner, name)
        elif isinstance(value, list):
            for inner in value:
                walk(inner, key)
        elif isinstance(value, str) and len(value) >= 24 and value.count(" ") >= 3:
            found.add(value)

    for entry in data.get("entries", []):
        walk(entry)
    return tuple(sorted(found))


def check_site(out: Path, doc: Mapping[str, Any], *, forbidden: Sequence[str] = ()) -> list[str]:
    """What is wrong with the page built in ``out``; empty when nothing is."""
    problems: list[str] = []
    index = out / "index.html"
    if not index.is_file():
        return [f"{index} is missing"]
    html = index.read_text(encoding="utf-8")
    parsed = _Page()
    parsed.feed(html)
    for href in parsed.links:
        if href.startswith("#") and href[1:] not in parsed.ids:
            problems.append(f"a link to {href} goes nowhere on the page")
    for image in parsed.images:
        if not image.get("alt"):
            problems.append(f"a picture without alt text: {image.get('src')}")
    for name in charts.NAMES:
        figure = parsed.figures.get(name)
        if figure is None:
            problems.append(f"the chart {name} is missing")
            continue
        if figure["svg"] < 1 or figure["titles"] < figure["svg"] or figure["descs"] < figure["svg"]:
            problems.append(f"the chart {name} lacks its <title> or <desc>")
        if figure["empty"]:
            problems.append(f"the chart {name} has an empty <desc>")
        if figure["tables"] < 1:
            problems.append(f"the chart {name} has no table")
        if f"{name}.csv" not in figure["csv"] or not (out / f"{name}.csv").is_file():
            problems.append(f"the chart {name} has no CSV beside it")
    for name in charts.COMMITTED:
        for theme in ("light", "dark"):
            if not (out / f"eval-{name}-{theme}.svg").is_file():
                problems.append(f"eval-{name}-{theme}.svg is missing (the README's charts on PyPI load it)")
    rendered = _numbers(page(doc))
    for number in sorted(_numbers(html) - rendered):
        problems.append(f"{number}: a number the presenter does not render from presentation.json")
    for sentence in forbidden:
        if sentence in html:
            digest = hashlib.sha256(sentence.encode("utf-8")).hexdigest()[:12]
            problems.append(f"the page holds a sentence of a benchmark letter (sha256 {digest}…)")
    return problems
