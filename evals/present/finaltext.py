"""The final run's parts of docs/evals.md and the report page (standard library only), from ``presentation.json``'s
``final`` alone.

Each part is either a registered sentence (``final.sentences``, coded by :mod:`evals.present.final`'s rules) or a view
template (``final.views``, :mod:`evals.present.views`) filled with values; nothing here is worded in code. With a final
run the report's header names the final analysis, the evaluation card says how the final run was pre-registered, read
and analysed, the summary is the README's registered paragraph with the final run's chart, and section 6.1 is every
registered page sentence, in its order, between :data:`evals.present.final.PAGE_BEGIN` and
:data:`~evals.present.final.PAGE_END`. :mod:`evals.present.text` calls these only when ``doc["final"]`` is set.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from evals.present import PAGES_URL, fmt, views
from evals.present.final import PAGE_BEGIN, PAGE_END
from evals.present.text import Block, Chart, Marker, Paragraph, Subheading

#: The evaluation card's rows with a final run, in order: the ones every card has (``text``'s) and the final run's.
CARD = (
    "task",
    "model",
    "data",
    "primary",
    "safety",
    "protocol",
    "prereg",
    "reads",
    "intervals",
    "replay",
    "sources",
    "newest",
)
#: The anchors the card links to (the report's sections 3 and 7) and the final run's subsection.
DATA_ANCHOR, STATISTICS_ANCHOR = "#3-data-and-labels", "#7-statistics"
FINAL_SUBSECTION = "6.1"
#: The final analysis's inputs that are the final run's reads (the earlier splits pooled with them are not).
FINAL_INPUTS = ("primary", "secondary", "left_out")


def _final(doc: Mapping[str, Any]) -> Mapping[str, Any]:
    shown: Mapping[str, Any] = doc["final"]
    return shown


def view(doc: Mapping[str, Any], key: str, **values: object) -> views.Filled:
    """The view template ``key`` of ``doc``'s final run, filled."""
    return views.fill(_final(doc)["views"], key, **values)


def lede(doc: Mapping[str, Any]) -> str:
    """The report's header with a final run: it names the final analysis as the headline."""
    return view(doc, "report.lede", source=_final(doc)["source"]["file"], pages=PAGES_URL)


def card_rows(doc: Mapping[str, Any], common: Mapping[str, Sequence[str]]) -> list[list[str]]:
    """The evaluation card of the final run: ``common`` (the rows every card has) and the final run's own."""
    shown = _final(doc)
    reads = [row for row in shown["inputs"] if row["role"] in FINAL_INPUTS]
    registered = shown["prereg"]["registered"]
    if reads:
        newest = max(reads, key=lambda row: str(row["date"]))
        sources = view(
            doc,
            "card.sources",
            source=shown["source"]["file"],
            inputs=fmt.join([f"`{row['file']}`" for row in reads]),
        )
        recorded = view(
            doc, "card.newest", split=newest["split"], date=newest["date"], commit=newest["commit"]
        )
    else:
        sources = view(doc, "card.sources.alone", source=shown["source"]["file"])
        recorded = view(doc, "card.newest.alone", date=shown["date"])
    own = {
        "data": view(
            doc,
            "card.data",
            letters=shown["letters"],
            split=shown["split"],
            items=shown["items"],
            clusters=shown["clusters"],
        ),
        "protocol": view(doc, "card.protocol", anchor=DATA_ANCHOR),
        "prereg": view(
            doc,
            "card.prereg",
            file=shown["prereg"]["file"],
            hash=shown["prereg"]["sha256"][:12],
            freeze=str(registered["freeze_sha"])[:12],
            pr=registered["freeze_pr"],
        ),
        "reads": view(doc, "card.reads", used=len(shown["reads_used"]), registered=shown["reads_registered"]),
        "intervals": view(doc, "card.intervals", anchor=STATISTICS_ANCHOR),
        "sources": sources,
        "newest": recorded,
    }
    return [
        list(common[key]) if key in common else [view(doc, f"card.{key}.label"), own[key]] for key in CARD
    ]


def summary(doc: Mapping[str, Any]) -> list[Block]:
    """Section 1 with a final run: the README's registered paragraph (its sentences, laid out as the registered
    ``readme_layout`` lays out the paragraph) and the final run's chart."""
    shown = _final(doc)
    paragraph = shown["layout"]["readme_layout"]["paragraph"]
    said = shown["sentences"]["readme"]
    texts = [sentence["text"] for slot in paragraph for sentence in said if sentence["slot"] == slot]
    return [Paragraph(" ".join(texts)), Chart("final")]


def final_run(doc: Mapping[str, Any]) -> list[Block]:
    """Subsection 6.1 with a final run: its lead, then every registered page sentence in ``page_block`` order between
    the page's markers, one paragraph per slot, and nothing else between them."""
    blocks: list[Block] = [
        Subheading(view(doc, "results.final.heading", number=FINAL_SUBSECTION)),
        Paragraph(view(doc, "results.final.lead")),
        Marker(PAGE_BEGIN),
    ]
    slots: list[tuple[str, list[str]]] = []
    for sentence in _final(doc)["sentences"]["page"]:
        if slots and slots[-1][0] == sentence["slot"]:
            slots[-1][1].append(sentence["text"])
        else:
            slots.append((sentence["slot"], [sentence["text"]]))
    blocks += [Paragraph(" ".join(texts)) for _, texts in slots]
    blocks.append(Marker(PAGE_END))
    return blocks


def kind(doc: Mapping[str, Any], name: str) -> str:
    """What a results file of the final run is, on the history page (``ask-final``, ``stress``)."""
    return view(doc, f"history.kind.{name}")
