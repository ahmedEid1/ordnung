"""The final run's charts (standard library only), drawn with :mod:`evals.present.charts`'s primitives from
``presentation.json``'s ``final`` alone.

``final`` is the headline chart once the final run is published (the README's, the summary's and the page's): per
condition, the mean over the reads of the exact dates right and of the late or missed ones, each with its
letter-cluster bootstrap interval, and each read alone as a hollow ring. Every title, heading, column, tooltip,
description and caption is a view template (:mod:`evals.present.views`) filled with values; the description, which is
also the README picture's alt text, names every condition and value, and the table twin holds the same numbers. The
rows follow the page's one order (``presentation.json``'s ``order``, the final run's mean accuracy).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from evals.present import charts, fmt, palette, views
from evals.present.charts import Panel, Row

Parts = tuple[list[str], list[list[str]], str]


def _final(doc: Mapping[str, Any]) -> Mapping[str, Any]:
    shown: Mapping[str, Any] = doc["final"]
    return shown


def _view(doc: Mapping[str, Any], key: str, **values: object) -> views.Filled:
    return views.fill(_final(doc)["views"], key, **values)


def _level(doc: Mapping[str, Any]) -> str:
    return f"{float(_final(doc)['settings']['level']) * 100:g}"


def _each(rates: Sequence[Mapping[str, Any]]) -> str:
    return " · ".join(fmt.num(rate["value"]) for rate in rates)


# --------------------------------------------------------------------------------------------------
# The final run: exact dates and harm, the mean over the reads and each read
# --------------------------------------------------------------------------------------------------


def _hero_parts(doc: Mapping[str, Any]) -> Parts:
    shown, level = _final(doc), _level(doc)
    header: list[str] = [
        _view(doc, "chart.final.col.condition"),
        _view(doc, "chart.final.col.exact"),
        _view(doc, "chart.final.col.exact_ci", level=level),
        _view(doc, "chart.final.col.exact_reads"),
        _view(doc, "chart.final.col.harm"),
        _view(doc, "chart.final.col.harm_ci", level=level),
        _view(doc, "chart.final.col.harm_reads"),
    ]
    rows: list[list[str]] = []
    said: list[str] = []
    for condition in doc["order"]:
        summary = shown["conditions"][condition]
        exact, harm = summary["mean_accuracy"], summary["mean_harmful"]
        cells = [
            palette.LABELS[condition],
            fmt.pct(exact["value"]),
            fmt.ci(exact["ci"]),
            _each(summary["exact_per_read"]),
            fmt.pct(harm["value"]),
            fmt.ci(harm["ci"]),
            _each(summary["harmful_per_read"]),
        ]
        rows.append(cells)
        said.append(
            _view(
                doc,
                "chart.final.row",
                condition=cells[0],
                exact=cells[1],
                exact_ci=cells[2],
                exact_reads=cells[3],
                harm=cells[4],
                harm_ci=cells[5],
                harm_reads=cells[6],
            )
        )
    description: str = _view(
        doc,
        "chart.final.description",
        items=shown["items"],
        reads=shown["reads"],
        level=level,
        rows=". ".join(said),
    )
    return header, rows, description


def _rings(
    doc: Mapping[str, Any], condition: str, rates: Sequence[Mapping[str, Any]]
) -> list[tuple[float, str]]:
    reads = _final(doc)["reads_used"]
    return [
        (
            float(rate["value"]),
            _view(
                doc,
                "chart.final.tip.read",
                condition=palette.LABELS[condition],
                read=read,
                value=fmt.pct(rate["value"]),
            ),
        )
        for read, rate in zip(reads, rates, strict=True)
        if rate["value"] is not None
    ]


def _hero(doc: Mapping[str, Any], theme: str, narrow: bool, ident: str) -> str:
    shown, level = _final(doc), _level(doc)
    _, _, description = _hero_parts(doc)
    exact_rows: list[Row] = []
    harm_rows: list[Row] = []
    lowest, highest = 1.0, 0.0
    for condition in doc["order"]:
        summary = shown["conditions"][condition]
        label = palette.LABELS[condition]
        exact, harm = summary["mean_accuracy"], summary["mean_harmful"]
        exact_rings = _rings(doc, condition, summary["exact_per_read"])
        harm_rings = _rings(doc, condition, summary["harmful_per_read"])
        lowest = min([lowest, exact["ci"][0], *(value for value, _ in exact_rings)])
        highest = max([highest, harm["ci"][1], *(value for value, _ in harm_rings)])
        for rows, mean, rings, tip in (
            (exact_rows, exact, exact_rings, "chart.final.tip.exact"),
            (harm_rows, harm, harm_rings, "chart.final.tip.harm"),
        ):
            rows.append(
                Row(
                    condition,
                    mean["value"],
                    (mean["ci"][0], mean["ci"][1]),
                    fmt.pct(mean["value"]),
                    _view(
                        doc,
                        tip,
                        condition=label,
                        value=fmt.pct(mean["value"]),
                        level=level,
                        ci=fmt.ci(mean["ci"]),
                    ),
                    rings,
                )
            )
    panels = [
        Panel(
            _view(doc, "chart.final.exact"),
            min(charts._floor(lowest, 0.1), 0.9),
            1.0,
            charts._percent,
            exact_rows,
        ),
        Panel(
            _view(doc, "chart.final.harm"),
            0.0,
            max(charts._ceil(highest, 0.05), 0.05),
            charts._percent,
            harm_rows,
        ),
    ]
    subtitle = _view(
        doc,
        "chart.final.subtitle",
        items=shown["items"],
        letters=shown["letters"],
        reads=shown["reads"],
        split=shown["split"],
        model=shown["model"],
        level=level,
        method=shown["conditions"]["ordnung"]["mean_accuracy"]["method"],
    )
    return charts._dot_chart(
        ident,
        theme,
        narrow,
        _view(doc, "chart.final.title"),
        subtitle,
        description,
        panels,
        _view(doc, "chart.final.footnote"),
    )


def _hero_caption(doc: Mapping[str, Any]) -> str:
    conditions = _final(doc)["conditions"]

    def mean(condition: str, key: str) -> str:
        return fmt.pct(conditions[condition][key]["value"])

    return _view(
        doc,
        "chart.final.caption",
        ordnung_exact=mean("ordnung", "mean_accuracy"),
        ordnung_harm=mean("ordnung", "mean_harmful"),
        alone_exact=mean("llm_only", "mean_accuracy"),
        alone_harm=mean("llm_only", "mean_harmful"),
        agent_exact=mean("llm_rules_tool", "mean_accuracy"),
        agent_harm=mean("llm_rules_tool", "mean_harmful"),
    )


#: Each chart: how it is drawn, its parts (header, rows, description), its title's view and its caption.
_CHARTS: dict[
    str,
    tuple[
        Callable[[Mapping[str, Any], str, bool, str], str],
        Callable[[Mapping[str, Any]], Parts],
        str,
        Callable[[Mapping[str, Any]], str],
    ],
] = {
    "final": (_hero, _hero_parts, "chart.final.title", _hero_caption),
}


def names(doc: Mapping[str, Any]) -> tuple[str, ...]:
    """The final run's charts, in the order the report shows them."""
    return tuple(_CHARTS)


def committed(doc: Mapping[str, Any]) -> tuple[str, ...]:
    """The final run's charts committed as ``docs/assets/eval-<name>-{light,dark}.svg``."""
    return names(doc)


def svg(name: str, doc: Mapping[str, Any], theme: str = "light", *, narrow: bool = False) -> str:
    return _CHARTS[name][0](doc, theme, narrow, f"{name}-{theme}-{'n' if narrow else 'w'}")


def table(name: str, doc: Mapping[str, Any]) -> tuple[list[str], list[list[str]]]:
    header, rows, _ = _CHARTS[name][1](doc)
    return header, rows


def description(name: str, doc: Mapping[str, Any]) -> str:
    return _CHARTS[name][1](doc)[2]


def title(name: str, doc: Mapping[str, Any]) -> str:
    return _view(doc, _CHARTS[name][2])


def caption(name: str, doc: Mapping[str, Any]) -> str:
    """The chart's "What this shows", a view template filled with values only."""
    return _CHARTS[name][3](doc)
