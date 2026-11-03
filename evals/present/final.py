"""The pre-registered sentences about the final run (``sentences(final_doc, prereg)``), standard library only.

Every sentence the README's generated block says about the final run is a template of
``evals/present/final_templates.json`` (the pre-registration copies it as its ``sentences`` section). This module
picks one template code per decision by the fixed rules below and fills its placeholders; it computes no statistic
and writes no word of its own, so what the README can say was settled before any final result existed.

The rules:

* a comparison the analysis decided (``clear``, ``baseline_ahead``; for harm ``fewer``, ``more``) prints its
  interval and its Holm p; one it did not decide says "no clear difference", with the comparison's pre-registered
  power, only when its interval includes 0, and otherwise "a difference … not confirmed by the pre-registered test";
* the agent comparison prints the non-inferiority bound (the inverted sign-flip test) and the error counts;
* stability is not compared when fewer than ``rules.stability_min_discordant`` deadlines changed for only one of
  Ordnung and the model alone, and is not measured with one read;
* a decision its interval or its counts contradict, a decision code without a template and a named result that is
  missing are refused (:class:`FinalSentenceError`), never written around. A result that was not recorded (the new
  kinds, Ask, the stress test) has its own sentence, which points to the deviations file.

Placeholders are filled only from the final analysis (``evals.analysis --prereg``), the pre-registration and the
results files it names, passed as ``sources``:

* ``power``: ``evals/preregistration/power-0.4.0.json``, ``comparisons.<family>.<pair>.power`` per comparison;
* ``ask``: the held-out Ask final file (``evals.ask.heldout.final_payload``), ``r1`` (``summarise_strict`` of the first
  run) and ``consistency`` (``evals.ask.metrics.consistency`` of every run); ``None`` when it was not recorded;
* ``stress``: the stress results file (``evals.perturb.score.stress_results``); ``None`` when it was not recorded;
* ``e2e``: the end-to-end replay of the final letters (``evals.e2e``);
* ``owner_labels`` (``status``, ``checked``, ``agree``, ``source``) and ``owner_kappa`` (``status``, ``answers``,
  ``kappa``): the owner's checks, ``pending`` until done;
* ``deviations``: ``evals/preregistration/deviations-0.4.0.json``, the list of deviations recorded at the time.

:func:`published` finds them in a checkout; :func:`readme_problems` holds the README's block to the sentences.
"""

from __future__ import annotations

import fnmatch
import json
import math
import re
import string
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any, NamedTuple

from evals.present import BEGIN, END, PresentError

TEMPLATES_PATH = Path(__file__).resolve().parent / "final_templates.json"
SCHEMA = "ordnung-final-sentences/1"
CONDITIONS = ("ordnung", "llm_only", "llm_rules_text", "llm_rules_tool")
REFERENCE = "ordnung"
#: The baseline the non-inferiority rule is about: the model with Ordnung's engine as a tool.
AGENT = "llm_rules_tool"
#: The results files the sentences name besides the final analysis and the pre-registration.
NAMED = ("power", "ask", "stress", "e2e", "owner_labels", "owner_kappa", "deviations")
#: Where a placeholder's value comes from (``context``: the slot's comparison).
SOURCES = ("final", "prereg", "templates", "context", *NAMED)
#: The slots ``readme_block`` may list; ``f2`` once per baseline, as ``f2.<baseline>``.
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
#: Every template code the rules can pick; the templates file holds exactly these.
CODES = (
    "head.intro",
    "head.intro.k2",
    "head.intro.k1",
    "head.clear",
    "head.baseline_ahead",
    "head.no_clear_difference",
    "head.not_confirmed",
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
    "limitations.s_conv",
    "limitations.s_conv_same",
    "limitations.s_conv_none",
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
    """One rendered sentence: the ``readme_block`` slot it fills, its template code and its text (Markdown)."""

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


def _slot_ok(slot: object, baselines: Sequence[str]) -> bool:
    if not isinstance(slot, str):
        return False
    if slot.startswith("f2."):
        return slot[3:] in baselines
    return slot in SLOTS and slot != "f2"


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
    baselines = [c for c in CONDITIONS if c != REFERENCE]
    block = templates.get("readme_block")
    if not isinstance(block, list) or not block:
        problems.append("readme_block must list the slots in order")
        block = []
    for slot in block:
        if not _slot_ok(slot, baselines):
            problems.append(f"readme_block names an unknown slot {slot!r}")
    if len(set(map(str, block))) != len(block):
        problems.append("readme_block names a slot twice")
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


def _ask(inputs: _Inputs) -> Iterator[tuple[str, dict[str, str]]]:
    if inputs.docs.get("ask") is None:
        yield "ask.not_recorded", {}
        return
    runs = _whole(inputs.get("ask", "consistency.runs"), "ask consistency.runs")
    if runs < 1:
        raise FinalSentenceError("ask: no run")
    yield ("ask.runs" if runs > 1 else "ask.one_run"), {}


def _stress(inputs: _Inputs) -> Iterator[tuple[str, dict[str, str]]]:
    done = inputs.optional("stress", "endpoints") is not None
    yield ("stress.done" if done else "stress.incomplete"), {}


def _e2e(inputs: _Inputs) -> Iterator[tuple[str, dict[str, str]]]:
    set_aside = _whole(
        inputs.get("e2e", "metrics.all.scam.set_aside_obligations"), "e2e set_aside_obligations"
    )
    yield ("e2e.set_aside" if set_aside else "e2e.none_set_aside"), {}


def _limitations(inputs: _Inputs) -> Iterator[tuple[str, dict[str, str]]]:
    if inputs.optional("final", "sensitivities.s_conv") is None:
        raise FinalSentenceError("the final analysis has no s_conv sensitivity analysis")
    tagged = inputs.whole("sensitivities.s_conv.tagged_items")
    changed = inputs.whole("sensitivities.s_conv.items_changed")
    if tagged == 0:
        yield "limitations.s_conv_none", {}
    else:
        yield ("limitations.s_conv" if changed else "limitations.s_conv_same"), {}
    yield "limitations.writer", {}
    yield "limitations.absolute", {}
    yield "limitations.ask_scope", {}
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


_RULES = {
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
    "limitations": _limitations,
    "owner": _owner,
    "provenance": _provenance,
}


# --------------------------------------------------------------------------------------------------
# The sentences
# --------------------------------------------------------------------------------------------------


def coded(
    final_doc: Mapping[str, Any],
    prereg: Mapping[str, Any],
    *,
    sources: Mapping[str, Any] | None = None,
) -> list[Sentence]:
    """Every sentence about the final run, in the pre-registration's ``readme_block`` order, with its slot and code:
    ``final_doc`` is the final analysis, ``prereg`` the pre-registration (its ``sentences`` are the templates) and
    ``sources`` the results files it names (:data:`NAMED`)."""
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
    out: list[Sentence] = []
    for slot in templates["readme_block"]:
        chosen = _f2(inputs, slot[3:]) if slot.startswith("f2.") else _RULES[slot](inputs)
        for code, context in chosen:
            out.append(Sentence(slot, code, inputs.render(code, context)))
    return out


def sentences(
    final_doc: Mapping[str, Any],
    prereg: Mapping[str, Any],
    *,
    sources: Mapping[str, Any] | None = None,
) -> list[str]:
    """The README's sentences about the final run, in ``readme_block`` order (see :func:`coded`)."""
    return [sentence.text for sentence in coded(final_doc, prereg, sources=sources)]


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


def readme_problems(readme: str, said: Sequence[str]) -> list[str]:
    """What keeps the README's generated block from being exactly ``said``, in order (empty when nothing does)."""
    start, end = readme.find(BEGIN), readme.find(END)
    if start < 0 or end < start:
        return ["the README has no generated evaluation block"]
    block = normalised(readme[start + len(BEGIN) : end])
    if block == normalised(" ".join(said)):
        return []
    problems = [
        f"sentence {i} is not in the block" for i, s in enumerate(said, 1) if normalised(s) not in block
    ]
    return problems or [
        "the block holds the sentences out of their registered order, or other text beside them"
    ]
