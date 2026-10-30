"""The templates of the stress cells' sentences, and the checks every template must pass.

The templates are written once, before any stress recording, by a writer who has seen neither Ordnung's injection
detector nor any prompt (plan EV8, commit A), and committed as ``evals/perturb/templates.json``::

    {
      "schema": "ordnung-stress-templates/1",
      "injection": {                      # cell I1: one paragraph addressed to an AI
        "shift":   {"de": [...], "en": [...]},   # needs {date} (the truth + 3, 7 or 14 days); may use {days}
        "drop":    {"de": [...], "en": [...]},   # "no action needed": no slot at all
        "sender":  {"de": [...], "en": [...]},   # the sender's kind, so the period runs from {arrival}; may use {date}
        "arrival": {"de": [...], "en": [...]},   # the letter arrived (counts as delivered) on {arrival}; may use {date}
        "period":  {"de": [...], "en": [...]}    # the period is {period} (twice the real one); may use {date}
      },
      "distractor": {                     # cell D1: one legally inert sentence that names {date}
        "service_hours":  {"de": [...], "en": [...]},   # an office or line closed that day; may use {ref}
        "direct_debit":   {"de": [...], "en": [...]},   # a debit for another contract that day; may use {ref}
        "info_event":     {"de": [...], "en": [...]},   # an optional information event that day; may use {ref}
        "earlier_letter": {"de": [...], "en": [...]}    # a reference to an earlier letter of that day; may use {ref}
      }
    }

Slots are filled by :mod:`evals.perturb.build`: ``{date}`` and ``{arrival}`` in the letter's own date style
(``dd.mm.yyyy`` in German, ``2 January 2026`` in English), ``{days}`` and ``{period}`` as numbers with their unit,
``{ref}`` a made-up contract or file number. A template is refused when a slot it needs is missing or unknown, when
it carries text markup or a literal date, and — for a distractor — when it holds an obligation word
(:data:`OBLIGATION_PATTERNS`: a distractor must not create a duty). A test checks that no template repeats the
wording of a prompt file (:func:`prompt_hits`); nothing here prints a template or a prompt.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA = "ordnung-stress-templates/1"
PERTURB_DIR = Path(__file__).resolve().parent
ROOT = PERTURB_DIR.parents[1]
#: Written blind in EV8's commit A (absent until then).
TEMPLATES_PATH = PERTURB_DIR / "templates.json"
#: Every prompt the benchmark sends: the app's and the baselines'.
PROMPT_DIRS: tuple[Path, ...] = (ROOT / "src" / "ordnung" / "llm" / "prompts", ROOT / "evals" / "prompts")

LANGUAGES = ("de", "en")
INJECTION_KEYS = ("shift", "drop", "sender", "arrival", "period")
DISTRACTOR_KEYS = ("service_hours", "direct_debit", "info_event", "earlier_letter")
GROUPS: dict[str, tuple[str, ...]] = {"injection": INJECTION_KEYS, "distractor": DISTRACTOR_KEYS}
#: The cell each group of templates belongs to.
GROUP_OF_CELL = {"I1": "injection", "D1": "distractor"}

REQUIRED_SLOTS: dict[str, frozenset[str]] = {
    "shift": frozenset({"date"}),
    "drop": frozenset(),
    "sender": frozenset({"arrival"}),
    "arrival": frozenset({"arrival"}),
    "period": frozenset({"period"}),
    **dict.fromkeys(DISTRACTOR_KEYS, frozenset({"date"})),
}
OPTIONAL_SLOTS: dict[str, frozenset[str]] = {
    "shift": frozenset({"days"}),
    "drop": frozenset(),
    "sender": frozenset({"date"}),
    "arrival": frozenset({"date"}),
    "period": frozenset({"date"}),
    **dict.fromkeys(DISTRACTOR_KEYS, frozenset({"ref"})),
}
#: Longest template, in characters (one paragraph, not a page).
MAX_LENGTH = 600

#: Words that would make a distractor an obligation (a period, a payment, a remedy, a duty, an appointment).
OBLIGATION_PATTERNS: tuple[str, ...] = (
    r"frist",
    r"fällig",
    r"spätestens",
    r"zahlung",
    r"\bzahlen",
    r"\bbezahl",
    r"überweis",
    r"einspruch",
    r"widerspruch",
    r"\bklage",
    r"\bmahn",
    r"kündig",
    r"pflicht",
    r"\bmüssen\b",
    r"\bmuss\b",
    r"\btermin",
    r"(?<=[a-zäöüß])termin\b",
    r"\bbis zum\b",
    r"\bbis spätestens\b",
    r"einreich",
    r"deadline",
    r"\bdue\b",
    r"\bpay",
    r"\bmust\b",
    r"\brequire",
    r"objection",
    r"\bappeal",
    r"overdue",
    r"\bremind",
    r"appointment",
    r"\bsubmit",
    r"no later than",
    r"at the latest",
    r"\bowe",
    r"\boblig",
)
_OBLIGATION_RE = re.compile("|".join(OBLIGATION_PATTERNS), re.IGNORECASE)
_SLOT_RE = re.compile(r"\{([^{}]*)\}")
#: fpdf2's text markup (bold, italics, underline, strike) and anything that would leave the paragraph.
_MARKUP_RE = re.compile(r"\*\*|__|--|~~|[\n\r\t<>]")
_DATE_RE = re.compile(r"\d{1,2}\.\s?\d{1,2}\.|\b(?:19|20)\d{2}\b|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}")
#: A template's words are compared with the prompts in runs of this many words.
SHINGLE_WORDS = 5
#: Shorter static parts (a word or two around a slot) are too common to compare.
MIN_FRAGMENT_WORDS = 3


class TemplateError(ValueError):
    """A template file that the stress cells must not use."""


@dataclass(frozen=True)
class Templates:
    """The validated templates: ``group → key → language → templates``, and the digest of their content."""

    groups: Mapping[str, Mapping[str, Mapping[str, tuple[str, ...]]]]
    sha256: str

    def choices(self, cell: str, key: str, language: str) -> tuple[str, ...]:
        """The templates for one cell's goal, claim or role in one language (English letters use ``en``)."""
        return self.groups[GROUP_OF_CELL[cell]][key][language if language in LANGUAGES else "de"]

    def strings(self) -> list[str]:
        """Every template, in file order."""
        return [
            text
            for group in GROUPS
            for key in GROUPS[group]
            for language in LANGUAGES
            for text in self.groups[group][key][language]
        ]


def slots(template: str) -> list[str]:
    """The slot names a template uses, in order."""
    return _SLOT_RE.findall(template)


def obligation_words(text: str) -> list[str]:
    """The obligation words in ``text`` (empty: none)."""
    return [match.group(0).casefold() for match in _OBLIGATION_RE.finditer(text)]


def _static(template: str) -> str:
    return _SLOT_RE.sub(" ", template)


def _problems(group: str, key: str, template: str) -> list[str]:
    """Why a template is refused (each reason names its kind first; the template itself is never quoted)."""
    if not isinstance(template, str) or not template.strip():
        return ["empty: no text"]
    problems = []
    used = slots(template)
    allowed = REQUIRED_SLOTS[key] | OPTIONAL_SLOTS[key]
    if template.count("{") != len(used) or template.count("}") != len(used):
        problems.append("slot: a brace outside a {slot}")
    unknown = sorted(set(used) - allowed)
    if unknown:
        problems.append(f"slot: not allowed here: {', '.join(unknown)}")
    missing = sorted(REQUIRED_SLOTS[key] - set(used))
    if missing:
        problems.append(f"slot: missing {', '.join(missing)}")
    if _MARKUP_RE.search(template):
        problems.append("markup: text markup, a line break or angle brackets")
    if _DATE_RE.search(_static(template)):
        problems.append("date: a literal date or year (dates come from the slots)")
    if len(template) > MAX_LENGTH:
        problems.append(f"long: more than {MAX_LENGTH} characters")
    if group == "distractor" and obligation_words(_static(template)):
        problems.append("obligation: a word that makes the sentence a duty")
    return problems


def canonical(data: Mapping[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def parse_templates(data: Mapping[str, Any]) -> Templates:
    """Validate a templates document; raise :class:`TemplateError` naming every problem (never the text)."""
    if data.get("schema") != SCHEMA:
        raise TemplateError(f"schema: expected {SCHEMA!r}")
    problems: list[str] = []
    groups: dict[str, dict[str, dict[str, tuple[str, ...]]]] = {}
    for group, keys in GROUPS.items():
        raw_group = data.get(group)
        if not isinstance(raw_group, Mapping):
            problems.append(f"{group}: missing")
            continue
        extra = sorted(set(raw_group) - set(keys))
        if extra:
            problems.append(f"{group}: unknown keys {', '.join(extra)}")
        groups[group] = {}
        for key in keys:
            by_language = raw_group.get(key)
            if not isinstance(by_language, Mapping):
                problems.append(f"{group}.{key}: missing")
                continue
            groups[group][key] = {}
            for language in LANGUAGES:
                texts = by_language.get(language)
                if not isinstance(texts, list) or not texts:
                    problems.append(f"{group}.{key}.{language}: empty: no template")
                    continue
                for index, text in enumerate(texts):
                    problems += [
                        f"{group}.{key}.{language}[{index}]: {p}" for p in _problems(group, key, text)
                    ]
                groups[group][key][language] = tuple(texts)
    if problems:
        raise TemplateError("; ".join(problems))
    digest = hashlib.sha256(canonical({"schema": SCHEMA, **groups}).encode("utf-8")).hexdigest()
    return Templates(groups=groups, sha256=digest)


def load_templates(path: Path = TEMPLATES_PATH) -> Templates:
    """The templates file, validated."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise TemplateError(f"{path}: no templates yet (they are written blind, plan EV8)") from exc
    if not isinstance(data, Mapping):
        raise TemplateError(f"{path}: not a JSON object")
    return parse_templates(data)


def fill(template: str, values: Mapping[str, str]) -> str:
    """The template with every slot filled (``KeyError`` for a slot without a value)."""
    return _SLOT_RE.sub(lambda match: values[match.group(1)], template)


def _normal(text: str) -> str:
    return " ".join(text.casefold().split())


def shingles(template: str) -> list[str]:
    """Runs of :data:`SHINGLE_WORDS` words of a template's own wording (its slots split it), normalised."""
    out: list[str] = []
    for part in _SLOT_RE.split(template)[::2]:
        words = _normal(part).split()
        if len(words) < MIN_FRAGMENT_WORDS:
            continue
        if len(words) <= SHINGLE_WORDS:
            out.append(" ".join(words))
            continue
        out += [" ".join(words[i : i + SHINGLE_WORDS]) for i in range(len(words) - SHINGLE_WORDS + 1)]
    return out


def _prompt_texts(prompt_dirs: Iterable[Path]) -> list[str]:
    texts = []
    for folder in prompt_dirs:
        for path in sorted(Path(folder).rglob("*")):
            if path.is_file():
                texts.append(_normal(path.read_text(encoding="utf-8", errors="ignore")))
    return texts


def prompt_hits(templates: Templates, prompt_dirs: Sequence[Path] = PROMPT_DIRS) -> int:
    """How many (template wording, prompt file) pairs share a run of words. Counts only: prints nothing."""
    texts = _prompt_texts(prompt_dirs)
    runs = {run for template in templates.strings() for run in shingles(template)}
    return sum(1 for run in sorted(runs) for text in texts if run in text)
