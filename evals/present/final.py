"""The pre-registered sentences about the final run, for the README and docs/evals.md; standard library only.

Every sentence the README's generated block and the final-run section of ``docs/evals.md`` say about the final run
is a template of ``evals/present/final_templates.json`` (the pre-registration copies it as its ``sentences``
section). This module picks one template code per decision by the fixed rules below and fills its placeholders; it
computes no statistic and writes no word of its own, so what either page can say was settled before any final result
existed.

The templates file orders the slots twice (:func:`sentences` takes ``block``, ``"page"`` or ``"readme"``).
``page_block`` lists every slot: the final section of ``docs/evals.md``, between :data:`PAGE_BEGIN` and
:data:`PAGE_END`, says all of them. ``readme_block`` lists the slots the README says, in the same order: a
subsequence of ``page_block``, so each README sentence is a page sentence, word for word. The README holds a slot for
its role, fixed before any result, never for what it says on a given result, so each of its slots is there whatever
its code:

* the accuracy family of the one confirmatory decision (``evals.analysis.CONFIRMATORY``): the headline with Ordnung
  against the model alone (``head``, which ends with the number of deviations recorded at the time and the file that
  lists them), and the family's two other comparisons, against the model with the rules pasted in (``rules_text``)
  and the agent's non-inferiority (``agent``);
* the safety endpoint, every condition's late or missed dates (``harm``), and the harm comparisons the analysis
  decides, against the model alone and against the model with the rules pasted in (``f2.llm_only``,
  ``f2.llm_rules_text``; harm against the agent is described, not tested, and stays on the page);
* the stability decision (``stability``);
* where Ordnung falls short: what its "please check" flag caught of its wrong dates (``flags``), the real
  obligations the end-to-end run set aside as scams and the scam letters whose demands still reached the calendar
  (``e2e``);
* "Ask: new questions on the demo household" (``ask``), with its sentence for runs not recorded, and its scope: it
  holds out only its questions (``limitations.ask_scope``);
* the caveats that bear on every number: the deadlines whose label rests on a disputed reading the engine's
  documentation shares (``limitations.s_conv``), the slots the letter or the law leaves open, which the deadlines
  counted leave out (``limitations.ambiguous``), and who wrote the letters, so that every condition's absolute
  accuracy may be higher than on real mail (``limitations.absolute``).

Everything else is on the page only: harm against the agent, the new kinds, the stress test, the limitation on reads
recorded within days, the owner's checks and the provenance. The page holds every sentence, decided or not, and the
README's link says so.

:func:`readme_block` lays the README's sentences out, the one layout phase 2 writes between the README's markers:
one paragraph of the head, the accuracy family, harm, the tested harm comparisons and stability, wrapped at
:data:`README_WIDTH` as today's headline; a blank line, the chart, a blank line, as today's block; one line per item
of the templates' ``readme_layout`` (where Ordnung falls short, under its lead; Ask with its scope; each caveat),
each ending in ``<br>`` as today's; and the link. Its budget is fixed with it: at most :data:`README_BLOCK_MAX_LINES`
lines, and every line but the chart's at most :data:`README_LINE_MAX` characters, both taken from the longest block
the templates can give (``tests/test_present_final.py``).

The rules:

* a comparison the analysis decided (``clear``, ``baseline_ahead``; for harm ``fewer``, ``more``) prints its
  interval and its Holm p; one it did not decide says "no clear difference", with the comparison's pre-registered
  power, only when its interval includes 0, and otherwise "a difference … not confirmed by the pre-registered test";
* the agent comparison prints the non-inferiority bound (the inverted sign-flip test) and the error counts; harm
  against the agent is described (its difference and interval), never decided;
* stability is not compared when fewer than ``rules.stability_min_discordant`` deadlines changed for only one of
  Ordnung and the model alone, and is not measured with one read;
* the label slots the letter or the law leaves open between two or more dates are counted, deadlines, offered dates
  and contract dates apart, with what counts for them (``labels.ambiguous_slots`` of the final analysis);
* a slot that has nothing to say says nothing: the limitation on reads recorded within days needs two reads or more;
* a decision its interval or its counts contradict, a decision code without a template and a named result that is
  missing are refused (:class:`FinalSentenceError`), never written around. A result that was not recorded (the new
  kinds, Ask, the stress test) has its own sentence, which points to the deviations file; an Ask run left
  out, or a stress test not completed, only when a ``budget_cut`` or ``window_closed`` deviation names it
  (``applies_to.split`` :data:`ASK_SPLIT` with the run's ``repeat``, or :data:`STRESS_SPLIT`).

Placeholders are filled only from the final analysis (``evals.analysis --prereg``), the pre-registration and the
results files it names, passed as ``sources``:

* ``power``: ``evals/preregistration/power-0.4.0.json``, ``comparisons.<family>.<pair>.power`` per comparison;
* ``ask``: the Ask set's final file (``evals.ask.heldout.final_payload``), ``r1`` (``summarise_strict`` of the first
  run) and ``consistency`` (``evals.ask.metrics.consistency`` of every run); ``None`` when it was not recorded;
* ``stress``: the stress results file (``evals.perturb.score.stress_results``); ``None`` when it was not recorded;
* ``e2e``: the end-to-end replay of the final letters (``evals.e2e``);
* ``owner_labels`` (``status``, ``checked``, ``agree``, ``source``) and ``owner_kappa`` (``status``, ``answers``,
  ``kappa``): the owner's checks, ``pending`` until done;
* ``deviations``: ``evals/preregistration/deviations-0.4.0.json``, the list of deviations recorded at the time.

:func:`published` finds them in a checkout; :func:`readme_problems` holds the README's block to the README's
sentences as :func:`readme_block` lays them out, and :func:`page_problems` the final section of ``docs/evals.md`` to
the page's.
"""

from __future__ import annotations

import fnmatch
import json
import math
import re
import string
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any, NamedTuple

from evals.present import BEGIN, END, PresentError

TEMPLATES_PATH = Path(__file__).resolve().parent / "final_templates.json"
SCHEMA = "ordnung-final-sentences/1"
CONDITIONS = ("ordnung", "llm_only", "llm_rules_text", "llm_rules_tool")
REFERENCE = "ordnung"
BASELINES = tuple(condition for condition in CONDITIONS if condition != REFERENCE)
#: The baseline the non-inferiority rule is about: the model with Ordnung's engine as a tool.
AGENT = "llm_rules_tool"
#: The results files the sentences name besides the final analysis and the pre-registration.
NAMED = ("power", "ask", "stress", "e2e", "owner_labels", "owner_kappa", "deviations")
#: What a deviation names (its ``applies_to.split``) for a run of the Ask set (with its ``repeat``) and for the stress
#: test; the kinds that say a step was not run or not completed; the Ask runs the pre-registration plans
#: (``evals.ask.heldout.REGISTERED_READS``).
ASK_SPLIT, STRESS_SPLIT = "ask-heldout", "stress"
NOT_RUN_KINDS = ("budget_cut", "window_closed")
ASK_REGISTERED_RUNS = 3
#: Where a placeholder's value comes from (``context``: the slot's comparison).
SOURCES = ("final", "prereg", "templates", "context", *NAMED)
#: The two ordered slot lists of the templates file, by the block each one fills.
BLOCKS = {"readme": "readme_block", "page": "page_block"}
#: The README block's budget, registered with the templates before any result: its paragraph is wrapped at
#: ``README_WIDTH`` characters (the width of today's headline), the block takes at most ``README_BLOCK_MAX_LINES``
#: lines between the markers, and every line but the chart's at most ``README_LINE_MAX`` characters. Both limits are
#: the longest block the templates can give (``tests/test_present_final.py`` builds it).
README_WIDTH = 116
README_BLOCK_MAX_LINES = 26
README_LINE_MAX = 412
#: docs/evals.md's final section lies between these two lines (the README's block between ``BEGIN`` and ``END``).
PAGE_BEGIN = "<!-- evals:final:begin: the pre-registered sentences, in page_block order; do not edit -->"
PAGE_END = "<!-- evals:final:end -->"
#: The slots a block may list: ``f2`` once per baseline, as ``f2.<baseline>``, and ``limitations`` once per part, as
#: ``limitations.<part>``.
SLOTS = (
    "head",
    "rules_text",
    "agent",
    "harm",
    "f2",
    "stability",
    "flags",
    "newkinds",
    "ask",
    "stress",
    "e2e",
    "limitations",
    "owner",
    "provenance",
)
#: The parts of the limitations: the disputed readings, the slots left open, who wrote the letters with what that
#: does to absolute accuracy, the Ask set's scope, and reads recorded within days.
LIMITATIONS = ("s_conv", "ambiguous", "absolute", "ask_scope", "reads")
#: Every slot, as ``page_block`` must list it (in any order of its own).
ALL_SLOTS = tuple(
    name
    for slot in SLOTS
    for name in (
        [f"f2.{b}" for b in BASELINES]
        if slot == "f2"
        else [f"limitations.{part}" for part in LIMITATIONS]
        if slot == "limitations"
        else [slot]
    )
)
#: Every template code the rules can pick; the templates file holds exactly these.
CODES = (
    "head.intro",
    "head.intro.k2",
    "head.intro.k1",
    "head.clear",
    "head.baseline_ahead",
    "head.no_clear_difference",
    "head.not_confirmed",
    "head.deviations",
    "rules_text.clear",
    "rules_text.baseline_ahead",
    "rules_text.no_clear_difference",
    "rules_text.not_confirmed",
    "agent.non_inferior",
    "agent.agent_higher",
    "agent.cannot_tell",
    "harm.none",
    "harm.some",
    "f2.fewer",
    "f2.more",
    "f2.no_clear_difference",
    "f2.not_confirmed",
    "f2.descriptive",
    "stability.more_stable",
    "stability.not_shown",
    "stability.too_few",
    "stability.not_run",
    "flags.some",
    "flags.none_wrong",
    "newkinds.done",
    "newkinds.not_recorded",
    "ask.runs",
    "ask.one_run",
    "ask.not_recorded",
    "stress.done",
    "stress.incomplete",
    "e2e.set_aside",
    "e2e.none_set_aside",
    "e2e.scam_in_calendar",
    "e2e.no_scam_in_calendar",
    "limitations.s_conv",
    "limitations.s_conv_same",
    "limitations.s_conv_none",
    "limitations.ambiguous",
    "limitations.ambiguous_none",
    "limitations.writer",
    "limitations.absolute",
    "limitations.ask_scope",
    "limitations.reads",
    "owner.pending",
    "owner.labels_done",
    "owner.kappa_done",
    "owner.done",
    "provenance.none",
    "provenance.one",
    "provenance.some",
)
FORMATS = ("int", "pct", "pct_whole", "percent_number", "ci", "points", "p", "kappa", "hash", "text")
MINUS = "−"
DASH = "–"
_PLACEHOLDER = re.compile(r"\{[^{}]*\}")


class FinalSentenceError(PresentError):
    """The final analysis, a named result or the templates do not fit the pre-registered sentences."""


class Sentence(NamedTuple):
    """One rendered sentence: the slot it fills, its template code and its text (Markdown)."""

    slot: str
    code: str
    text: str


# --------------------------------------------------------------------------------------------------
# The templates
# --------------------------------------------------------------------------------------------------


def load_templates(path: Path = TEMPLATES_PATH) -> dict[str, Any]:
    """The committed templates file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise FinalSentenceError(f"{path.name} is not a JSON object")
    return data


def _fields(text: str) -> list[str]:
    try:
        return [field for _, field, _, _ in string.Formatter().parse(text) if field is not None]
    except ValueError as exc:
        raise FinalSentenceError(f"a template's braces do not pair up: {exc}") from exc


def check_templates(templates: Mapping[str, Any]) -> list[str]:
    """What is wrong with a template set (empty when nothing is): its slots, codes, placeholders and rules."""
    problems: list[str] = []
    if templates.get("schema") != SCHEMA:
        problems.append(f"the schema is {templates.get('schema')!r}, not {SCHEMA!r}")
    conditions = templates.get("conditions")
    if not isinstance(conditions, Mapping) or list(conditions) != list(CONDITIONS):
        problems.append(f"conditions must name {', '.join(CONDITIONS)}, in that order")
        conditions = {c: c for c in CONDITIONS}
    elif not all(isinstance(name, str) and name for name in conditions.values()):
        problems.append("every condition needs a name")
    problems += _block_problems(templates)
    problems += _layout_problems(templates)
    rules = templates.get("rules")
    minimum = rules.get("stability_min_discordant") if isinstance(rules, Mapping) else None
    if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 1:
        problems.append("rules.stability_min_discordant must be a positive whole number")
    files = templates.get("files")
    if not isinstance(files, Mapping) or set(files) != {"prereg", "final", *NAMED}:
        problems.append(f"files must give the path of prereg, final, {', '.join(NAMED)}")
    codes = templates.get("templates")
    placeholders = templates.get("placeholders")
    if not isinstance(codes, Mapping) or not isinstance(placeholders, Mapping):
        problems.append("templates and placeholders must be objects")
        return problems
    for code in CODES:
        if code not in codes:
            problems.append(f"no template for the code {code}")
    used: set[str] = set()
    for code, template in codes.items():
        if code not in CODES:
            problems.append(f"the template {code} is one no rule picks")
        if not isinstance(template, Mapping) or not isinstance(template.get("text"), str):
            problems.append(f"{code}: a template is an object with a text")
            continue
        text = template["text"]
        if re.search(r"\d", _PLACEHOLDER.sub("", text)):
            problems.append(f"{code}: a number outside a placeholder")
        for field in _fields(text):
            used.add(field)
            if field not in placeholders:
                problems.append(f"{code}: the placeholder {{{field}}} has no source")
        compares = template.get("compares")
        if not isinstance(compares, list) or not all(c in (*CONDITIONS, "baseline") for c in compares):
            problems.append(f"{code}: compares must list conditions (or baseline)")
    for name, spec in placeholders.items():
        if name not in used:
            problems.append(f"the placeholder {name} is used by no template")
        if not isinstance(spec, Mapping):
            problems.append(f"{name}: a placeholder is an object")
            continue
        if spec.get("source") not in SOURCES:
            problems.append(f"{name}: unknown source {spec.get('source')!r}")
        if spec.get("format") not in FORMATS:
            problems.append(f"{name}: unknown format {spec.get('format')!r}")
        paths = spec.get("paths")
        if not isinstance(spec.get("path"), str) and not (
            isinstance(paths, list) and paths and all(isinstance(p, str) for p in paths)
        ):
            problems.append(f"{name}: give a path or paths")
        if spec.get("total") not in (None, "sum", "count"):
            problems.append(f"{name}: total is sum or count")
        if "each" in spec and spec.get("total") != "sum":
            problems.append(f"{name}: each needs total sum")
    return problems


def _block_problems(templates: Mapping[str, Any]) -> list[str]:
    """What is wrong with the two slot lists: a slot no rule fills, a slot named twice, a page that leaves a slot
    out, a README slot the page does not say or says in another order."""
    problems: list[str] = []
    blocks: dict[str, list[str]] = {}
    for name in BLOCKS.values():
        block = templates.get(name)
        if not isinstance(block, list) or not block:
            problems.append(f"{name} must list the slots in order")
            block = []
        for slot in block:
            if _rule(slot) is None:
                problems.append(f"{name} names an unknown slot {slot!r}, which no rule fills")
        if len(set(map(str, block))) != len(block):
            problems.append(f"{name} names a slot twice")
        blocks[name] = [str(slot) for slot in block]
    page, readme = blocks[BLOCKS["page"]], blocks[BLOCKS["readme"]]
    left_out = [slot for slot in ALL_SLOTS if slot not in page]
    if left_out:
        problems.append(f"page_block leaves out {', '.join(left_out)}: every slot is said on the page")
    not_on_page = [slot for slot in readme if slot not in page]
    if not_on_page:
        problems.append(f"readme_block names {', '.join(not_on_page)}, which page_block does not")
    else:
        rest = iter(page)
        if not all(slot in rest for slot in readme):
            problems.append("readme_block lists its slots in another order than page_block")
    return problems


def _layout_problems(templates: Mapping[str, Any]) -> list[str]:
    """What is wrong with the README block's layout: its paragraph and its lines must lay out ``readme_block``'s
    slots, each once and in its order; a line has a lead (empty or words, no number) and slots; the link is a line."""
    layout = templates.get("readme_layout")
    if not isinstance(layout, Mapping) or set(layout) != {"paragraph", "lines", "link"}:
        return ["readme_layout must give the paragraph, the lines and the link"]
    problems: list[str] = []
    paragraph, lines = layout.get("paragraph"), layout.get("lines")
    if not isinstance(paragraph, list) or not isinstance(lines, list) or not lines:
        return ["readme_layout's paragraph and lines must be lists"]
    laid: list[Any] = list(paragraph)
    for line in lines:
        if (
            not isinstance(line, Mapping)
            or set(line) != {"lead", "slots"}
            or not isinstance(line["lead"], str)
            or not isinstance(line["slots"], list)
            or not line["slots"]
        ):
            problems.append("readme_layout: a line is an object with a lead and its slots")
            continue
        if re.search(r"\d", line["lead"]):
            problems.append("readme_layout: a lead holds a number outside a placeholder")
        laid += line["slots"]
    if laid != templates.get(BLOCKS["readme"]):
        problems.append("readme_layout lays out other slots than readme_block, or in another order")
    link = layout.get("link")
    if not isinstance(link, str) or not link.strip() or "\n" in link:
        problems.append("readme_layout must give the link to the page, on one line")
    return problems


# --------------------------------------------------------------------------------------------------
# Values and their formats
# --------------------------------------------------------------------------------------------------


def _walk(doc: Any, path: str, where: str) -> Any:
    value = doc
    for part in path.split(".") if path else []:
        if isinstance(value, Mapping) and part in value:
            value = value[part]
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            raise FinalSentenceError(f"{where}: no {path}")
    return value


def _number(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise FinalSentenceError(f"{where}: {value!r} is not a number")
    return float(value)


def _whole(value: Any, where: str) -> int:
    number = _number(value, where)
    if not number.is_integer():
        raise FinalSentenceError(f"{where}: {value!r} is not a whole number")
    return int(number)


def _signed(text: str) -> str:
    return text.replace("-", MINUS)


def _formatted(value: Any, fmt: str, where: str) -> str:
    if fmt == "text":
        if not isinstance(value, str) or not value.strip():
            raise FinalSentenceError(f"{where}: {value!r} is not a text")
        return value
    if fmt == "hash":
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{12,}", value):
            raise FinalSentenceError(f"{where}: {value!r} is not a hash")
        return value[:12]
    if fmt == "ci":
        if not isinstance(value, list) or len(value) != 2:
            raise FinalSentenceError(f"{where}: {value!r} is not an interval")
        low, high = (_number(v, where) for v in value)
        return f"{low * 100:.1f}{DASH}{high * 100:.1f}"
    if fmt == "int":
        return str(_whole(value, where))
    number = _number(value, where)
    if fmt == "pct":
        return f"{number * 100:.1f} %"
    if fmt == "pct_whole":
        return f"{number * 100:.0f} %"
    if fmt == "percent_number":
        return f"{number * 100:g}"
    if fmt == "points":
        return _signed(f"{number * 100:+.1f}")
    if fmt == "p":
        return "< 0.001" if number < 0.001 else f"= {number:.3f}"
    if fmt == "kappa":
        return _signed(f"{number:.2f}")
    raise FinalSentenceError(f"{where}: unknown format {fmt!r}")


class _Inputs:
    """The documents the placeholders read, and the reads the rules make of them."""

    def __init__(self, templates: Mapping[str, Any], docs: Mapping[str, Any]) -> None:
        self.templates = templates
        self.docs = docs

    def get(self, source: str, path: str) -> Any:
        doc = self.docs.get(source)
        if doc is None:
            raise FinalSentenceError(f"the {source} results are missing")
        return _walk(doc, path, source)

    def final(self, path: str) -> Any:
        return self.get("final", path)

    def optional(self, source: str, path: str) -> Any:
        """The value at ``path``, or ``None`` when the document or the path is not there."""
        try:
            return self.get(source, path)
        except FinalSentenceError:
            return None

    def number(self, path: str) -> float:
        return _number(self.final(path), f"final {path}")

    def whole(self, path: str) -> int:
        return _whole(self.final(path), f"final {path}")

    def value(self, name: str, context: Mapping[str, str]) -> str:
        spec = self.templates["placeholders"][name]
        source = str(spec["source"])
        where = f"{{{name}}} ({source})"
        try:
            paths = [str(p).format_map(context) for p in spec.get("paths") or [spec["path"]]]
        except KeyError as exc:
            raise FinalSentenceError(f"{where}: no {exc} for this sentence") from exc
        if source == "context":
            if paths[0] not in context:
                raise FinalSentenceError(f"{where}: no {paths[0]} for this sentence")
            values = [context[paths[0]]]
        elif source == "templates":
            values = [_walk(self.templates, path, where) for path in paths]
        else:
            values = [self.get(source, path) for path in paths]
        each, total = spec.get("each"), spec.get("total")
        if each is not None:
            if not isinstance(values[0], list):
                raise FinalSentenceError(f"{where}: {paths[0]} is not a list")
            values = [_walk(item, str(each), where) for item in values[0]]
        if total == "count":
            if not isinstance(values[0], list):
                raise FinalSentenceError(f"{where}: {paths[0]} is not a list")
            value: Any = len(values[0])
        elif total == "sum":
            value = sum(_whole(v, where) for v in values)
        else:
            value = values[0]
        if value is None:
            raise FinalSentenceError(f"{where}: no value")
        return _formatted(value, str(spec["format"]), where)

    def render(self, code: str, context: Mapping[str, str]) -> str:
        text = str(self.templates["templates"][code]["text"])
        return text.format_map({field: self.value(field, context) for field in _fields(text)})


# --------------------------------------------------------------------------------------------------
# The rules: which code each slot says
# --------------------------------------------------------------------------------------------------


def _pair(baseline: str) -> str:
    return f"{REFERENCE}-vs-{baseline}"


def _context(inputs: _Inputs, family: str, baseline: str) -> dict[str, str]:
    return {
        "family": family,
        "pair": _pair(baseline),
        "baseline_key": baseline,
        "baseline": str(inputs.templates["conditions"][baseline]),
    }


def _decided(
    inputs: _Inputs, prefix: str, family: str, baseline: str, decision: str, higher: str, lower: str
) -> str:
    """A comparison of F1 or F2 by its decision code, checked against the interval and Holm p it prints:
    ``higher`` (Ordnung's rate above the baseline's) and ``lower`` need Holm p below alpha and the interval on that
    side of 0; anything undecided is "no clear difference" when the interval includes 0, else "not confirmed"."""
    row = f"primary.families.{family}.{_pair(baseline)}"
    lo, hi = inputs.number(f"{row}.bootstrap.lo"), inputs.number(f"{row}.bootstrap.hi")
    holm, alpha = inputs.number(f"{row}.holm"), inputs.number("meta.settings.alpha")
    names = {higher: (lo > 0, "above"), lower: (hi < 0, "below")}
    if decision in names:
        side_ok, side = names[decision]
        if not (side_ok and holm < alpha):
            raise FinalSentenceError(
                f"{prefix} against {baseline}: {decision} needs Holm p below {alpha:g} and an interval {side} 0"
            )
        return f"{prefix}.{decision}"
    if decision not in ("no_clear_difference", "level_within_noise"):
        raise FinalSentenceError(f"{prefix} against {baseline}: no template for the decision {decision!r}")
    if holm < alpha and (lo > 0 or hi < 0):
        raise FinalSentenceError(f"{prefix} against {baseline}: {decision} with a decided test and interval")
    return f"{prefix}.no_clear_difference" if lo <= 0 <= hi else f"{prefix}.not_confirmed"


def _head(inputs: _Inputs) -> Iterator[tuple[str, dict[str, str]]]:
    reads = inputs.whole("primary.reads")
    yield {1: "head.intro.k1", 2: "head.intro.k2"}.get(reads, "head.intro"), {}
    decision = str(inputs.final("primary.decisions.beats_llm_only"))
    code = _decided(inputs, "head", "F1_accuracy", "llm_only", decision, "clear", "baseline_ahead")
    yield code, _context(inputs, "F1_accuracy", "llm_only")
    # "pre-registered" comes with the deviations recorded at the time, whatever their number, and where they are
    if not isinstance(inputs.docs.get("deviations"), list):
        raise FinalSentenceError("the deviations file is missing or is not a list")
    yield "head.deviations", {}


def _rules_text(inputs: _Inputs) -> Iterator[tuple[str, dict[str, str]]]:
    decision = str(inputs.final("primary.decisions.vs_llm_rules_text"))
    code = _decided(
        inputs, "rules_text", "F1_accuracy", "llm_rules_text", decision, "clear", "baseline_ahead"
    )
    yield code, _context(inputs, "F1_accuracy", "llm_rules_text")


def _agent(inputs: _Inputs) -> Iterator[tuple[str, dict[str, str]]]:
    decision = str(inputs.final(f"primary.decisions.vs_{AGENT}"))
    block = f"primary.noninferiority.{_pair(AGENT)}"
    lo, hi = inputs.number(f"{block}.bound.lo"), inputs.number(f"{block}.bound.hi")
    margin = inputs.number("meta.settings.noninferiority_margin")
    recorded = inputs.optional("final", f"{block}.decision")
    if recorded is not None and recorded != decision:
        raise FinalSentenceError(
            f"the agent: the decision {decision!r} differs from the bound's {recorded!r}"
        )
    fits = {
        "agent_higher": hi < 0,
        "non_inferior": lo > -margin and hi >= 0,
        "cannot_tell": lo <= -margin and hi >= 0,
    }
    if decision not in fits:
        raise FinalSentenceError(f"the agent: no template for the decision {decision!r}")
    if not fits[decision]:
        raise FinalSentenceError(f"the agent: {decision} contradicts the bound it prints")
    yield f"agent.{decision}", _context(inputs, "F1_accuracy", AGENT)


def _harm(inputs: _Inputs) -> Iterator[tuple[str, dict[str, str]]]:
    dates = inputs.whole("primary.decisions.harmful.dates")
    none = inputs.final("primary.decisions.harmful.none")
    per_read = inputs.final(f"primary.conditions.{REFERENCE}.harmful_per_read")
    if not isinstance(per_read, list):
        raise FinalSentenceError("final: harmful_per_read is not a list")
    counted = sum(
        _whole(_walk(row, "k", "final harmful_per_read"), "final harmful_per_read") for row in per_read
    )
    if counted != dates or none is not (dates == 0):
        raise FinalSentenceError("Ordnung's late or missed dates differ between the decision and the reads")
    yield ("harm.none" if dates == 0 else "harm.some"), {}


def _f2(inputs: _Inputs, baseline: str) -> Iterator[tuple[str, dict[str, str]]]:
    if baseline == AGENT:
        # harm against the agent is described, not tested (the pre-registration sets no margin for harm)
        if inputs.optional("final", f"primary.decisions.f2_vs_{baseline}") is not None:
            raise FinalSentenceError(
                "harm against the agent is described, not tested: the analysis decided it"
            )
        yield "f2.descriptive", _context(inputs, "F2_harm", baseline)
        return
    decision = str(inputs.final(f"primary.decisions.f2_vs_{baseline}"))
    # harm: Ordnung's rate above the baseline's is more late or missed dates
    code = _decided(inputs, "f2", "F2_harm", baseline, decision, "more", "fewer")
    yield code, _context(inputs, "F2_harm", baseline)


def _stability(inputs: _Inputs) -> Iterator[tuple[str, dict[str, str]]]:
    reads = inputs.whole("primary.reads")
    family = inputs.optional("final", "primary.families.F3_stability")
    decision = inputs.optional("final", "primary.decisions.more_stable_than_llm_only")
    if reads < 2 or family is None:
        if decision is not None:
            raise FinalSentenceError("stability: a decision without the reads to compare")
        yield "stability.not_run", {}
        return
    row = f"primary.families.F3_stability.{_pair('llm_only')}"
    b, c = inputs.whole(f"{row}.b"), inputs.whole(f"{row}.c")
    decided = inputs.number(f"{row}.holm") < inputs.number("meta.settings.alpha") and b < c
    if decision is not decided:
        raise FinalSentenceError(f"stability: the decision {decision!r} contradicts the test it prints")
    minimum = int(inputs.templates["rules"]["stability_min_discordant"])
    if b + c < minimum:
        yield "stability.too_few", {}
    else:
        yield ("stability.more_stable" if decided else "stability.not_shown"), {}


def _flags(inputs: _Inputs) -> Iterator[tuple[str, dict[str, str]]]:
    caught = inputs.whole("primary.decisions.flags_caught.caught")
    wrong = inputs.whole("primary.decisions.flags_caught.wrong")
    if not 0 <= caught <= wrong:
        raise FinalSentenceError(f"the flags caught {caught} of {wrong} wrong dates")
    yield ("flags.some" if wrong else "flags.none_wrong"), {}


def _newkinds(inputs: _Inputs) -> Iterator[tuple[str, dict[str, str]]]:
    inputs.final("secondary.newkinds")  # refused when the analysis has no block for the new kinds
    recorded = inputs.optional("final", "secondary.newkinds.not_recorded") is None
    yield ("newkinds.done" if recorded else "newkinds.not_recorded"), {}


def _not_run(inputs: _Inputs, split: str, repeat: int | None = None) -> bool:
    """Whether a deviation recorded at the time says this step was not run or not completed (``budget_cut``,
    ``window_closed``, naming it in ``applies_to``)."""
    deviations = inputs.docs.get("deviations")
    if not isinstance(deviations, list):
        raise FinalSentenceError("the deviations file is missing or is not a list")
    for deviation in deviations:
        applies = deviation.get("applies_to") if isinstance(deviation, Mapping) else None
        if (
            isinstance(applies, Mapping)
            and deviation.get("kind") in NOT_RUN_KINDS
            and applies.get("split") == split
            and (repeat is None or applies.get("repeat") == repeat)
        ):
            return True
    return False


def _ask(inputs: _Inputs) -> Iterator[tuple[str, dict[str, str]]]:
    runs = 0
    if inputs.docs.get("ask") is not None:
        runs = _whole(inputs.get("ask", "consistency.runs"), "ask consistency.runs")
        if runs < 1:
            raise FinalSentenceError("ask: no run")
    missing = [
        run for run in range(runs + 1, ASK_REGISTERED_RUNS + 1) if not _not_run(inputs, ASK_SPLIT, run)
    ]
    if missing:
        # every pre-registered endpoint is published: a run is left out only when a deviation says why
        raise FinalSentenceError(
            f"ask: run(s) {', '.join(map(str, missing))} of {ASK_REGISTERED_RUNS} are not in the file of runs and no "
            "budget_cut or window_closed deviation names them"
        )
    if runs == 0:
        yield "ask.not_recorded", {}
        return
    yield ("ask.runs" if runs > 1 else "ask.one_run"), {}


def _stress(inputs: _Inputs) -> Iterator[tuple[str, dict[str, str]]]:
    done = inputs.optional("stress", "endpoints") is not None
    if not done and not _not_run(inputs, STRESS_SPLIT):
        raise FinalSentenceError(
            "stress: the test is not completed and no budget_cut or window_closed deviation names it"
        )
    yield ("stress.done" if done else "stress.incomplete"), {}


def _e2e(inputs: _Inputs) -> Iterator[tuple[str, dict[str, str]]]:
    set_aside = _whole(
        inputs.get("e2e", "metrics.all.scam.set_aside_obligations"), "e2e set_aside_obligations"
    )
    yield ("e2e.set_aside" if set_aside else "e2e.none_set_aside"), {}
    scams = _whole(inputs.get("e2e", "metrics.all.scam.scam_letters"), "e2e scam_letters")
    in_calendar = inputs.get("e2e", "metrics.all.scam.in_the_calendar")
    if not isinstance(in_calendar, list) or len(in_calendar) > scams:
        raise FinalSentenceError(
            f"e2e: the scam letters in the calendar are not a list of at most {scams} scam letters"
        )
    yield ("e2e.scam_in_calendar" if in_calendar else "e2e.no_scam_in_calendar"), {}


def _s_conv(inputs: _Inputs) -> Iterator[tuple[str, dict[str, str]]]:
    if inputs.optional("final", "sensitivities.s_conv") is None:
        raise FinalSentenceError("the final analysis has no s_conv sensitivity analysis")
    tagged = inputs.whole("sensitivities.s_conv.tagged_items")
    changed = inputs.whole("sensitivities.s_conv.items_changed")
    if tagged == 0:
        yield "limitations.s_conv_none", {}
    else:
        yield ("limitations.s_conv" if changed else "limitations.s_conv_same"), {}


def _left_open(inputs: _Inputs) -> Iterator[tuple[str, dict[str, str]]]:
    if inputs.optional("final", "labels.ambiguous_slots") is None:
        raise FinalSentenceError(
            "the final analysis does not count the label slots left open (labels.ambiguous_slots)"
        )
    left_open = sum(
        inputs.whole(f"labels.ambiguous_slots.{kind}") for kind in ("deadline", "offered", "contract")
    )
    yield ("limitations.ambiguous" if left_open else "limitations.ambiguous_none"), {}


def _absolute(inputs: _Inputs) -> Iterator[tuple[str, dict[str, str]]]:
    # the caveat refers back to the writer ("a model of that family"), so the two are said together
    yield "limitations.writer", {}
    yield "limitations.absolute", {}


def _ask_scope(inputs: _Inputs) -> Iterator[tuple[str, dict[str, str]]]:
    yield "limitations.ask_scope", {}


def _reads(inputs: _Inputs) -> Iterator[tuple[str, dict[str, str]]]:
    if inputs.whole("primary.reads") > 1:
        yield "limitations.reads", {}


def _status(inputs: _Inputs, source: str) -> bool:
    status = "pending" if inputs.docs.get(source) is None else inputs.optional(source, "status")
    if status not in ("pending", "done"):
        raise FinalSentenceError(f"{source}: the status is {status!r}, not pending or done")
    return status == "done"


def _owner(inputs: _Inputs) -> Iterator[tuple[str, dict[str, str]]]:
    labels, kappa = _status(inputs, "owner_labels"), _status(inputs, "owner_kappa")
    yield (
        {
            (False, False): "owner.pending",
            (True, False): "owner.labels_done",
            (False, True): "owner.kappa_done",
            (True, True): "owner.done",
        }[(labels, kappa)],
        {},
    )


def _provenance(inputs: _Inputs) -> Iterator[tuple[str, dict[str, str]]]:
    deviations = inputs.docs.get("deviations")
    if not isinstance(deviations, list):
        raise FinalSentenceError("the deviations file is missing or is not a list")
    yield {0: "provenance.none", 1: "provenance.one"}.get(len(deviations), "provenance.some"), {}


_Rule = Callable[[_Inputs], Iterator[tuple[str, dict[str, str]]]]
_RULES: dict[str, _Rule] = {
    "head": _head,
    "rules_text": _rules_text,
    "agent": _agent,
    "harm": _harm,
    "stability": _stability,
    "flags": _flags,
    "newkinds": _newkinds,
    "ask": _ask,
    "stress": _stress,
    "e2e": _e2e,
    "owner": _owner,
    "provenance": _provenance,
}
_LIMITATION_RULES: dict[str, _Rule] = {
    "s_conv": _s_conv,
    "ambiguous": _left_open,
    "absolute": _absolute,
    "ask_scope": _ask_scope,
    "reads": _reads,
}


def _rule(slot: object) -> _Rule | None:
    """The rule that picks a slot's codes, or ``None`` for a name that is no slot."""
    if not isinstance(slot, str):
        return None
    family, dot, part = slot.partition(".")
    if family == "f2" and dot:
        return (lambda inputs: _f2(inputs, part)) if part in BASELINES else None
    if family == "limitations" and dot:
        return _LIMITATION_RULES.get(part)
    return None if dot else _RULES.get(slot)


# --------------------------------------------------------------------------------------------------
# The sentences
# --------------------------------------------------------------------------------------------------


def coded(
    final_doc: Mapping[str, Any],
    prereg: Mapping[str, Any],
    *,
    block: str,
    sources: Mapping[str, Any] | None = None,
) -> list[Sentence]:
    """The sentences one block says about the final run, in its order, with their slot and code: ``block`` is
    ``"page"`` (every slot, ``page_block``) or ``"readme"`` (``readme_block``); ``final_doc`` is the final analysis,
    ``prereg`` the pre-registration (its ``sentences`` are the templates) and ``sources`` the results files it names
    (:data:`NAMED`). The page is rendered either way, so the README refuses what the page refuses, and the README's
    sentences are the page's, word for word."""
    if block not in BLOCKS:
        raise FinalSentenceError(f"no block {block!r}: {' or '.join(BLOCKS)}")
    templates = prereg.get("sentences")
    if not isinstance(templates, Mapping):
        raise FinalSentenceError("the pre-registration holds no sentences")
    problems = check_templates(templates)
    if problems:
        raise FinalSentenceError("the pre-registered sentences are malformed: " + "; ".join(problems))
    named = dict(sources or {})
    unknown = sorted(set(named) - set(NAMED))
    if unknown:
        raise FinalSentenceError(f"no sentence reads {', '.join(unknown)}")
    for name, doc in named.items():
        kind = list if name == "deviations" else Mapping
        if doc is not None and not isinstance(doc, kind):
            raise FinalSentenceError(
                f"the {name} results are not a JSON {'list' if kind is list else 'object'}"
            )
    docs = {"final": final_doc, "prereg": prereg, **{name: named.get(name) for name in NAMED}}
    inputs = _Inputs(templates, docs)
    page: list[Sentence] = []
    for slot in templates[BLOCKS["page"]]:
        rule = _rule(slot)
        if rule is None:  # check_templates refused it above; never reached
            raise FinalSentenceError(f"no rule fills the slot {slot!r}")
        for code, context in rule(inputs):
            page.append(Sentence(slot, code, inputs.render(code, context)))
    if block == "page":
        return page
    said = set(templates[BLOCKS[block]])
    return [sentence for sentence in page if sentence.slot in said]


def sentences(
    final_doc: Mapping[str, Any],
    prereg: Mapping[str, Any],
    *,
    block: str,
    sources: Mapping[str, Any] | None = None,
) -> list[str]:
    """The sentences one block says about the final run, ``"readme"`` or ``"page"``, in its order (see
    :func:`coded`)."""
    return [sentence.text for sentence in coded(final_doc, prereg, block=block, sources=sources)]


# --------------------------------------------------------------------------------------------------
# The published files and the README
# --------------------------------------------------------------------------------------------------


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FinalSentenceError(f"{path.name}: not a readable JSON file ({exc})") from exc


def _one(paths: Sequence[Path], what: str) -> Path | None:
    if len(paths) > 1:
        raise FinalSentenceError(f"more than one {what} file: {', '.join(p.name for p in paths)}")
    return paths[0] if paths else None


def _matches(root: Path, pattern: str) -> list[Path]:
    folder = root / Path(pattern).parent
    return sorted(p for p in folder.glob("*.json") if fnmatch.fnmatch(p.name, Path(pattern).name))


def _meta(doc: Any) -> Mapping[str, Any]:
    meta = doc.get("meta") if isinstance(doc, Mapping) else None
    return meta if isinstance(meta, Mapping) else {}


def published(root: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None:
    """The final analysis, the pre-registration and the named results files of a checkout, where the templates'
    ``files`` put them (``None`` until the final analysis is in ``evals/results/``; a named file that is not there is
    ``None``, and the end-to-end file is the one that holds the final split)."""
    files = load_templates()["files"]
    finals = [path for path in _matches(root, files["final"]) if _meta(_load(path)).get("kind") == "final"]
    found = _one(finals, "final analysis")
    if found is None:
        return None
    final_doc = _load(found)
    prereg_path = root / files["prereg"]
    if not prereg_path.is_file():
        raise FinalSentenceError(f"the final analysis is published without {files['prereg']}")
    named: dict[str, Any] = {}
    for name in ("power", "owner_labels", "owner_kappa", "deviations"):
        path = root / files[name]
        named[name] = _load(path) if path.is_file() else None
    split = (final_doc.get("primary") or {}).get("split")
    candidates = {
        "ask": _matches(root, files["ask"]),
        "stress": _matches(root, files["stress"]),
        "e2e": [p for p in _matches(root, files["e2e"]) if split in (_meta(_load(p)).get("splits") or [])],
    }
    for name, paths in candidates.items():
        chosen = _one(paths, name)
        named[name] = _load(chosen) if chosen else None
    return final_doc, _load(prereg_path), named


def normalised(text: str) -> str:
    """The text with every run of white space made one space (the presenter may wrap lines)."""
    return " ".join(text.split())


def _fill(value: str, width: int) -> list[str]:
    """``value`` in lines of at most ``width`` characters, broken at spaces only and never before a ``%`` (the
    presenter's rule for today's headline, kept here so that the registered layout does not move with it)."""
    words: list[str] = []
    for word in value.split():
        if word.startswith("%") and words:
            words[-1] += " " + word
        else:
            words.append(word)
    lines: list[str] = []
    line = ""
    for word in words:
        if line and len(line) + 1 + len(word) > width:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}" if line else word
    return [*lines, line]


def _is_picture(line: str) -> bool:
    return "\n" not in line and line.startswith("<picture>") and line.endswith("</picture>")


def readme_block(said: Sequence[Sentence], templates: Mapping[str, Any], picture: str) -> list[str]:
    """The README's generated block, between :data:`~evals.present.BEGIN` and :data:`~evals.present.END`, line by
    line, as phase 2 writes it: ``said`` is the README's sentences (:func:`coded` with ``block="readme"``),
    ``templates`` the registered templates (their ``readme_layout``) and ``picture`` the chart, one ``<picture>``
    line. The paragraph's sentences wrapped at :data:`README_WIDTH`; a blank line, the chart, a blank line; one line
    per item of the layout, its lead and its slots' sentences, ending in ``<br>``; the link."""
    if not _is_picture(picture):
        raise FinalSentenceError("the README's chart is one <picture> line")
    layout = templates["readme_layout"]
    slots = [sentence.slot for sentence in said]
    runs = [slot for i, slot in enumerate(slots) if i == 0 or slots[i - 1] != slot]
    if runs != list(templates[BLOCKS["readme"]]):
        raise FinalSentenceError("these are not the README's sentences, slot by slot in readme_block order")
    texts: dict[str, list[str]] = {}
    for sentence in said:
        texts.setdefault(sentence.slot, []).append(sentence.text)
    paragraph = " ".join(text for slot in layout["paragraph"] for text in texts[slot])
    lines = [*_fill(paragraph, README_WIDTH), "", picture, ""]
    for item in layout["lines"]:
        said_here = [text for slot in item["slots"] for text in texts[slot]]
        lines.append(" ".join([item["lead"], *said_here] if item["lead"] else said_here) + "<br>")
    return [*lines, layout["link"]]


def readme_problems(readme: str, said: Sequence[Sentence], templates: Mapping[str, Any]) -> list[str]:
    """What keeps the README's generated block from being exactly :func:`readme_block` of ``said`` (the README's
    sentences, ``block="readme"``) under ``templates`` (the registered ones), blank lines included, whatever chart its
    picture line holds (empty when nothing does)."""
    lines = readme.splitlines()
    if BEGIN not in lines or END not in lines or lines.index(END) < lines.index(BEGIN):
        return ["the README has no generated evaluation block"]
    block = lines[lines.index(BEGIN) + 1 : lines.index(END)]
    expected = readme_block(said, templates, "<picture></picture>")
    flat = normalised(" ".join(block))
    missing = [
        f"sentence {i} is not in the block"
        for i, sentence in enumerate(said, 1)
        if normalised(sentence.text) not in flat
    ]
    if missing:
        return missing
    for number, (got, want) in enumerate(zip(block, expected, strict=False), 1):
        if got != want and not (_is_picture(want) and _is_picture(got)):
            return [
                f"line {number} of the block is not laid out as readme_block lays out the registered sentences"
            ]
    if len(block) != len(expected):
        return [f"the block has {len(block)} lines, not the {len(expected)} readme_block lays out"]
    return []


def page_problems(page: str, said: Sequence[str]) -> list[str]:
    """What keeps the final section of ``docs/evals.md`` from being exactly ``said`` (the page's sentences,
    ``block="page"``), in order (empty when nothing does)."""
    return _between_problems(page, said, PAGE_BEGIN, PAGE_END, "docs/evals.md has no final-run block")


def _between_problems(text: str, said: Sequence[str], begin: str, end_marker: str, missing: str) -> list[str]:
    start, end = text.find(begin), text.find(end_marker)
    if start < 0 or end < start:
        return [missing]
    block = normalised(text[start + len(begin) : end])
    if block == normalised(" ".join(said)):
        return []
    problems = [
        f"sentence {i} is not in the block" for i, s in enumerate(said, 1) if normalised(s) not in block
    ]
    return problems or [
        "the block holds the sentences out of their registered order, or other text beside them"
    ]
