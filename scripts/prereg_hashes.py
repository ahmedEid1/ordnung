"""The final run's pre-registration, by hash: what it pins, and how a checkout is checked against it (zero tokens).

It prints hashes, versions, counts and paths, never a prompt's, a letter's or a question's text.

* ``--section frozen|code|files|data|all [--final-day D] [--check FILE]`` prints the sections as JSON (the freeze
  record is ``--section all``; the pre-registration copies them into ``evals/preregistration/final-0.4.0.json``). With
  ``--check`` it compares them with that file instead and prints each difference by its path (exit 1):

  - ``frozen``: the code digest and each condition's fingerprint for ``claude-sonnet-5``
    (``evals.conditions._code_digest``, ``fingerprint``), the prompt hashes (Ordnung's prompts, each baseline's
    prompt digest, the rules tools' digest), both ``environment()``\\s (the runner's and the generator's), the
    sha256 of every request and prompts lock under ``evals/recorded/``, of ``evals/results/INDEX.json`` and of
    ``items.csv``. The rest of the pre-registration's ``frozen`` section (the path lists, ``cli_versions``, ``served_models``, the
    settings) is written by hand and not compared;
  - ``code``: the sha256 of each file of :data:`CODE_PATHS` (``null`` while it does not exist): the scorers, the
    analysis, the post-run scripts, these tools and the three frozen tests;
  - ``files``: the sha256 of every final data file (:data:`FILES_PATTERNS`);
  - ``data``: the build command for the planned day (``--final-day``, else the plug-in's ``FINAL_DAY``), the
    dataset's manifest and tree hashes (``evals.reproduce.dataset_info``), the generator's tree hash
    (:data:`GENERATOR_PATTERNS`), each final split's composition and the conventions' ids and ``disputed`` flags.

* ``--deviations FILE [--prereg FILE] [--history]`` checks the deviations file against the pre-registration's table of deviation kinds: every entry
  well formed (:data:`DEVIATION_KEYS`), with its issue comment's URL, ``created_at`` and checkpoint commit, and its
  kind's consequence the registered one; that table must also be the one the analysis applies. With ``--history``
  it also checks by the git history that each was recorded at the time (:func:`history_problems`). It prints ids
  and reasons only.
* ``--phase2 FILE [--head REV] [--path PATTERN]… --write`` writes the presenter's phase-2 record: the commit and
  the sha256 of every file of :data:`PHASE2_PATTERNS` at it, and their tree hash (the presenter's output
  ``presentation.json`` left out). Without ``--write`` it checks the checkout against FILE: a file that differs
  needs a ``code_hash_changed`` deviation whose evidence names its path (``--with-deviations FILE``).

``--root DIR`` reads another checkout (default: this one); the ``frozen`` section always describes the code that
runs it. ``tests/test_preregistration.py`` runs these checks on the pre-registration once it exists.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import importlib
import json
import re
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MODEL = "claude-sonnet-5"
PREREG = ROOT / "evals" / "preregistration" / "final-0.4.0.json"
SECTIONS = ("frozen", "code", "files", "data")
FINAL_SPLITS = ("holdout4", "newkinds")
#: The code that scores, analyses and presents the final run besides the runner (``evals/*.py`` is in the code
#: digest), and the tests that hold it: the pre-registration's ``code`` map.
CODE_PATHS = (
    "evals/analysis.py",
    "evals/stats.py",
    "evals/metrics.py",
    "evals/records.py",
    # every module of the packages that score Ask, the end-to-end replay and the stress test
    "evals/e2e/__init__.py",
    "evals/e2e/__main__.py",
    "evals/e2e/check.py",
    "evals/e2e/harness.py",
    "evals/e2e/metrics.py",
    "evals/e2e/observe.py",
    "evals/e2e/report.py",
    "evals/ask/__init__.py",
    "evals/ask/__main__.py",
    "evals/ask/attacks.py",
    "evals/ask/heldout.py",
    "evals/ask/heldout_check.py",
    "evals/ask/household.py",
    "evals/ask/ledger.py",
    "evals/ask/metrics.py",
    "evals/ask/owner.py",
    "evals/ask/parse.py",
    "evals/ask/questions.py",
    "evals/ask/recurrence.py",
    "evals/ask/report.py",
    "evals/ask/run.py",
    "evals/ask/score.py",
    "evals/ask/strict.py",
    "evals/perturb/__init__.py",
    "evals/perturb/build.py",
    "evals/perturb/score.py",
    "evals/perturb/templates.py",
    "evals/present/final.py",
    "evals/present/final_templates.json",
    "scripts/eval_without_land.py",
    "scripts/eval_ablate_checks.py",
    "scripts/eval_perturb.py",
    "scripts/eval_power.py",
    "scripts/prereg_hashes.py",
    "scripts/prereg_calibration.py",
    "scripts/owner_label_sample.py",
    "tests/test_preregistration.py",
    "tests/test_present_final.py",
    "tests/test_final_gates.py",
)
#: The final run's data, written blind after the freeze: the pre-registration's ``files`` map.
FILES_PATTERNS = (
    "evals/dataset/manifest.json",
    "evals/dataset/VERIFICATION.md",
    "evals/dataset/holdout4/**",
    "evals/dataset/newkinds/**",
    "evals/dataset/provenance/**",
    "evals/gen/**",
    "evals/ask/heldout/**",
    "evals/perturb/manifest.json",
)
GENERATOR_PATTERNS = ("evals/gen/**", "evals/generate.py", "evals/verify_labels.py")
#: The presenter as phase 2 builds it before any recording: its code, its docs templates and the report page's test.
PHASE2_PATTERNS = ("evals/present/**", "docs/templates/**", "web/e2e/eval-report.spec.ts")
#: What the presenter writes from the results (not its code): it changes with the results by design.
PHASE2_EXCLUDE = ("evals/present/presentation.json",)
PHASE2_SCHEMA = "ordnung-prereg-phase2/1"
#: The pre-registration's fields, at the top and in the sections code reads.
REQUIRED = (
    "schema",
    "id",
    "model",
    "registered",
    "frozen",
    "code",
    "files",
    "data",
    "blind_writing",
    "runs",
    "budget",
    "recording_day_rule",
    "contingency",
    "error_rules",
    "deviation_kinds",
    "deviations_file",
    "sealing",
    "analysis",
    "label_and_scorer_errors",
    "runner_defect",
    "sentences",
    "owner_checks",
    "power",
    "calibration",
    "pledge",
)
REQUIRED_IN = {
    "registered": ("freeze_sha", "freeze_pr", "commit_a", "planned_day", "valid_until"),
    "frozen": (
        "identical_paths",
        "allowed_after_freeze",
        "allowed_while_recording",
        "allowed_at_publish",
        "code_digest",
        "fingerprints",
        "prompt_hashes",
        "environment",
        "cli_versions",
        "served_models",
        "settings",
        "locks",
        "index_sha256",
    ),
    "data": ("build_command", "manifest_sha256", "tree_sha256", "splits", "conventions"),
    # final_templates.json as registered: the README's slots and the page's (evals.present.final.BLOCKS)
    "sentences": ("readme_block", "page_block"),
}
#: Files the pre-registration names by path and sha256 besides its ``files`` map.
NAMED_FILES = ("power", "calibration")
#: The pledge, word for word as it is registered.
PLEDGE = (
    "This result is published in the README, on the report page and in docs/evals.md, whatever it is. The publish "
    "PR opens within 14 days of the last recording day, with the final JSON and the rendered sentences. Every "
    "pre-registered endpoint is published, including reads cut by budget or window and any retired set. The "
    'generated block, including its "where it falls short" line, stays in the README for every 0.4.x release. No '
    "later split replaces it as 0.4.0's headline, and no fix informed by it is reported as held-out."
)
#: A deviation's keys as it is recorded at the time; ``applies_to`` (what the analysis applies it to) may be added.
DEVIATION_KEYS = (
    "id",
    "kind",
    "at",
    "step",
    "what",
    "evidence",
    "consequence",
    "issue_comment_url",
    "created_at",
    "checkpoint_sha",
)
OPTIONAL_DEVIATION_KEYS = ("applies_to",)
COMMENT_URL = re.compile(r"https://github\.com/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+/issues/\d+#issuecomment-\d+")
COMMIT = re.compile(r"[0-9a-f]{40}")
#: Any model identifier (the repository's model-id search, spelled in parts so that search does not find this line);
#: the pinned one is taken out before the search.
MODEL_ID = re.compile(
    "|".join(("op" + "us", "hai" + "ku", r"sonnet-[0-9]", r"claude-[a-z]+-[0-9]")), re.IGNORECASE
)
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --------------------------------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------------------------------


def _match_parts(parts: Sequence[str], pattern: Sequence[str]) -> bool:
    if not pattern:
        return not parts
    if pattern[0] == "**":
        return any(_match_parts(parts[i:], pattern[1:]) for i in range(len(parts) + 1))
    return bool(parts) and fnmatch.fnmatchcase(parts[0], pattern[0]) and _match_parts(parts[1:], pattern[1:])


def matches(path: str, pattern: str) -> bool:
    """Whether a repository path matches a glob: ``*`` within one folder name, ``**`` across folders."""
    return _match_parts(path.split("/"), pattern.split("/"))


def _hidden(rel: str) -> bool:
    """A hidden file or folder, or Python's cache: never part of what is hashed."""
    parts = rel.split("/")
    return rel.endswith(".pyc") or any(part.startswith(".") or part == "__pycache__" for part in parts)


def matching(root: Path, patterns: Iterable[str], exclude: Iterable[str] = ()) -> list[str]:
    """The files under ``root`` matching any pattern (hidden files and Python caches left out), sorted."""
    patterns, exclude = list(patterns), list(exclude)
    found = set()
    for pattern in patterns:
        head = pattern.split("*", 1)[0].rsplit("/", 1)[0] if "*" in pattern else pattern
        base = root / head
        candidates = [base] if base.is_file() else (base.rglob("*") if base.is_dir() else [])
        for path in candidates:
            rel = path.relative_to(root).as_posix()
            if path.is_file() and not _hidden(rel) and matches(rel, pattern):
                found.add(rel)
    return sorted(rel for rel in found if not any(matches(rel, pattern) for pattern in exclude))


def tree_sha256(files: Mapping[str, str]) -> str:
    """sha256 over each path and its sha256, in path order."""
    digest = hashlib.sha256()
    for path in sorted(files):
        digest.update(f"{path}\0{files[path]}\n".encode())
    return digest.hexdigest()


# --------------------------------------------------------------------------------------------------
# The sections
# --------------------------------------------------------------------------------------------------


def frozen_section(root: Path = ROOT) -> dict[str, Any]:
    """What the code freeze pins: digests, fingerprints, prompt hashes, environments, locks and the index."""
    from evals import conditions, generate
    from evals.records import CONDITIONS

    baselines = [c for c in CONDITIONS if c != "ordnung"]
    locks = {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted((root / "evals" / "recorded").rglob("*.lock.json"))
    }
    results = root / "evals" / "results"
    return {
        "model": MODEL,
        "code_digest": conditions._code_digest("ordnung"),
        "fingerprints": {c: conditions.fingerprint(c, MODEL) for c in CONDITIONS},
        "prompt_hashes": {
            "ordnung": {name: list(pair) for name, pair in conditions.ordnung_prompt_hashes().items()},
            "baselines": {c: conditions.baseline_prompt_digest(c) for c in baselines},
            "tools": conditions.tool_definitions_digest(),
        },
        "environment": {"evals": conditions.environment(), "generator": generate.environment()},
        "locks": locks,
        "index_sha256": sha256_file(results / "INDEX.json"),
        "items_sha256": sha256_file(results / "items.csv"),
    }


def code_section(root: Path = ROOT) -> dict[str, str | None]:
    """The sha256 of each file of :data:`CODE_PATHS` (``None`` while it does not exist)."""
    return {path: sha256_file(root / path) if (root / path).is_file() else None for path in CODE_PATHS}


def files_section(root: Path = ROOT) -> dict[str, str]:
    """The sha256 of every final data file."""
    return {rel: sha256_file(root / rel) for rel in matching(root, FILES_PATTERNS)}


def _plugin_day(root: Path) -> str | None:
    """The plug-in's ``FINAL_DAY`` (``evals/gen/final.py``), when this checkout has one."""
    if root.resolve() != ROOT.resolve() or not (root / "evals" / "gen" / "final.py").is_file():
        return None
    day = getattr(importlib.import_module("evals.gen.final"), "FINAL_DAY", None)
    if day is None:
        return None
    return day.isoformat() if hasattr(day, "isoformat") else str(day)


def _composition(entries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    families: dict[str, int] = {}
    for entry in entries:
        families[str(entry["family"])] = families.get(str(entry["family"]), 0) + 1
    return {
        "entries": len(entries),
        "pdfs": sum(1 for e in entries if not e.get("photo")),
        "photos": sum(1 for e in entries if e.get("photo")),
        "adversarial": sum(1 for e in entries if e.get("family") == "adversarial"),
        "scored_items": sum(
            1
            for e in entries
            for item in (e.get("truth") or {}).get("items") or []
            if isinstance(item.get("expected_due"), str) and _DAY.match(item["expected_due"])
        ),
        "families": dict(sorted(families.items())),
        "kinds": sorted({str((e.get("truth") or {}).get("kind")) for e in entries}),
        "variants": sorted({str(e.get("variant")) for e in entries}),
    }


def data_section(root: Path = ROOT, final_day: str | None = None) -> dict[str, Any]:
    """The build of the planned day and the final splits it holds."""
    from evals import reproduce

    dataset = root / "evals" / "dataset"
    manifest = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))
    day = final_day or _plugin_day(root)
    entries = manifest.get("entries") or []
    generator = {rel: sha256_file(root / rel) for rel in matching(root, GENERATOR_PATTERNS)}
    data: dict[str, Any] = {
        "build_command": f"python -m evals.generate --final-day {day}" if day else None,
        "final_day": day,
        **reproduce.dataset_info(dataset),
        "generator_tree_sha256": tree_sha256(generator),
        "splits": {
            split: _composition([e for e in entries if e.get("split") == split])
            for split in FINAL_SPLITS
            if any(e.get("split") == split for e in entries)
        },
        "conventions": [
            {"id": c.get("id"), "disputed": c.get("disputed")}
            if isinstance(c, Mapping)
            else {"id": None, "disputed": None}
            for c in manifest.get("conventions") or []
        ],
    }
    heldout = root / "evals" / "ask" / "heldout"
    counts = {}
    for name, key in (("questions", "questions.json"), ("attacks", "attacks.json")):
        if (heldout / key).is_file():
            counts[name] = len(json.loads((heldout / key).read_text(encoding="utf-8")).get(name) or [])
    if counts:
        data["ask_heldout"] = counts
    return data


def sections(names: Sequence[str], root: Path = ROOT, final_day: str | None = None) -> dict[str, Any]:
    """The named sections of :data:`SECTIONS`, computed for ``root``."""
    out: dict[str, Any] = {}
    for name in names:
        if name == "frozen":
            out[name] = frozen_section(root)
        elif name == "code":
            out[name] = code_section(root)
        elif name == "files":
            out[name] = files_section(root)
        elif name == "data":
            out[name] = data_section(root, final_day)
        else:
            raise ValueError(f"no section {name!r} (there are {', '.join(SECTIONS)})")
    return out


def _diff(ours: Any, theirs: Any, path: str, exhaustive: bool) -> list[str]:
    if isinstance(ours, Mapping) and isinstance(theirs, Mapping):
        out = []
        for key, value in ours.items():
            if key not in theirs:
                out.append(f"{path}.{key}: not in the pre-registration")
            else:
                out += _diff(value, theirs[key], f"{path}.{key}", True)
        if exhaustive:
            out += [
                f"{path}.{key}: in the pre-registration, not in this checkout"
                for key in theirs
                if key not in ours
            ]
        return out
    return [] if ours == theirs else [f"{path}: differs"]


def mismatches(computed: Mapping[str, Any], prereg: Mapping[str, Any]) -> list[str]:
    """Every computed value the pre-registration does not hold, by path. The ``code`` and ``files`` maps must match
    path for path; in ``frozen`` and ``data`` the fields written by hand are left alone."""
    out = []
    for section, values in computed.items():
        if section not in prereg:
            out.append(f"{section}: not in the pre-registration")
        else:
            out += _diff(values, prereg[section], section, section in ("code", "files"))
    return sorted(out)


# --------------------------------------------------------------------------------------------------
# The deviations file
# --------------------------------------------------------------------------------------------------


def kinds_table(raw: Any) -> dict[str, str]:
    """The pre-registration's ``deviation_kinds``: ``{kind: consequence}``, ``{kind: {"consequence": …}}`` or a list of
    ``{"kind", "consequence"}``; ``ValueError`` unless every consequence is a text."""
    if isinstance(raw, Mapping):
        rows: list[tuple[Any, Any]] = [
            (kind, value.get("consequence") if isinstance(value, Mapping) else value)
            for kind, value in raw.items()
        ]
    elif isinstance(raw, list):
        rows = [
            (row.get("kind"), row.get("consequence")) if isinstance(row, Mapping) else (None, None)
            for row in raw
        ]
    else:
        raise ValueError("the pre-registration has no table of deviation kinds")
    table = {}
    for kind, consequence in rows:
        if not isinstance(kind, str) or not isinstance(consequence, str) or not consequence:
            raise ValueError(f"the deviation kind {kind!r} has no consequence as a text")
        table[kind] = consequence
    return table


def _moment(value: Any) -> bool:
    try:
        datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return False
    return value is not None


def _entry_problems(entry: Mapping[str, Any], kinds: Mapping[str, str]) -> list[str]:
    problems = [
        f"unknown key {key}" for key in sorted(set(entry) - {*DEVIATION_KEYS, *OPTIONAL_DEVIATION_KEYS})
    ]
    kind = entry.get("kind")
    if kind not in kinds:
        problems.append(f"kind {kind!r} is not in the pre-registration's table")
    elif entry.get("consequence") != kinds[str(kind)]:
        problems.append(f"its consequence is not the registered one for {kind}")
    if not isinstance(entry.get("step"), str) or not entry["step"]:
        problems.append("no step")
    if not _moment(entry.get("at")):
        problems.append("no time it happened (at)")
    if not isinstance(entry.get("what"), str) or not entry["what"]:
        problems.append("no what")
    evidence = entry.get("evidence")
    if not isinstance(evidence, list) or not evidence or not all(isinstance(e, str) and e for e in evidence):
        problems.append("no evidence")
    if not COMMENT_URL.fullmatch(str(entry.get("issue_comment_url") or "")):
        problems.append("no comment on the pre-registration issue (issue_comment_url)")
    if not _moment(entry.get("created_at")):
        problems.append("no time it was recorded (created_at)")
    if not COMMIT.fullmatch(str(entry.get("checkpoint_sha") or "")):
        problems.append("no checkpoint commit that pushed it (checkpoint_sha)")
    if "applies_to" in entry and not isinstance(entry["applies_to"], Mapping):
        problems.append("applies_to is not an object")
    text = re.sub(re.escape(MODEL), "", json.dumps(entry, ensure_ascii=False), flags=re.IGNORECASE)
    if MODEL_ID.search(text):
        problems.append(f"names a model other than {MODEL}")
    return problems


def deviation_problems(entries: Any, kinds: Mapping[str, str]) -> list[str]:
    """Why the deviations file does not hold deviations recorded at the time (empty: it does), by id and reason."""
    if not isinstance(entries, list):
        return ["the deviations file is not a JSON list"]
    out: list[str] = []
    seen: set[str] = set()
    for position, entry in enumerate(entries, start=1):
        ident = entry.get("id") if isinstance(entry, Mapping) else None
        if not isinstance(entry, Mapping) or not isinstance(ident, str) or not ident:
            out.append(f"#{position}: not an entry with an id")
            continue
        if ident in seen:
            out.append(f"{ident}: in the file twice")
            continue
        seen.add(ident)
        out += [f"{ident}: {problem}" for problem in _entry_problems(entry, kinds)]
    return out


#: Where the deviations are recorded at the time (``deviate.py`` appends, the next checkpoint commits and pushes).
DEVIATIONS_PATH = "evals/preregistration/deviations-0.4.0.json"
#: Written once after the freeze, never edited: the pre-registration and the posted phase-2 record.
WRITE_ONCE = (
    "evals/preregistration/final-0.4.0.json",
    "evals/preregistration/final-0.4.0.md",
    "evals/preregistration/phase2-0.4.0.json",
)
#: The kinds that may be recorded after the results are published: a label error found by the blind review of
#: discordant items (or an owner's finding sent through it), and a scorer bug fixed after the publish PR.
AFTER_PUBLICATION = ("label_error", "scorer_bug")
#: What publishes the final run's results: a final read's results file out of ``pending/``, or a final analysis.
PUBLISHED = (
    ":(glob)evals/results/*holdout4*.json",
    ":(glob)evals/results/*newkinds*.json",
    ":(glob)evals/results/*-final.json",
)


def _run_git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=False)


def _commits(root: Path, since: str | None, *paths: str, added: bool = False) -> list[str]:
    """The commits (oldest first) of HEAD's history since ``since`` that changed (``added``: added) these paths."""
    span = f"{since}..HEAD" if since else "HEAD"
    filters = ["--diff-filter=A"] if added else []
    done = _run_git(root, "log", "--format=%H", "--reverse", *filters, span, "--", *paths)
    return done.stdout.decode().split() if done.returncode == 0 else []


def _at_commit(root: Path, sha: str, path: str) -> Any:
    done = _run_git(root, "show", f"{sha}:{path}")
    if done.returncode != 0:
        return None
    try:
        return json.loads(done.stdout.decode("utf-8"))
    except ValueError:
        return None


def _without_sha(entry: Any) -> Any:
    return (
        {key: value for key, value in entry.items() if key != "checkpoint_sha"}
        if isinstance(entry, Mapping)
        else entry
    )


def history_problems(
    root: Path,
    entries: Any,
    *,
    freeze: str | None = None,
    path: str = DEVIATIONS_PATH,
    issue: str | None = None,
) -> list[str]:
    """Why the deviations file's entries were not recorded at the time, by the repository's history (empty: they
    were). For each entry: its checkpoint is a commit of HEAD's history, that commit holds the entry as it is now
    (its own sha aside, filled in by the next commit), the entry was written no later than that commit, and that
    commit comes before the results were published (a label error or a scorer bug excepted); each entry is a comment
    on one issue, ``issue`` when the pre-registration names it. Over its history the file only grew: no entry was
    changed or removed."""
    if not isinstance(entries, list):
        return ["the deviations file is not a JSON list"]
    out: list[str] = []
    published = _commits(root, freeze, *PUBLISHED, added=True)
    first_published = published[0] if published else None
    issues: set[str] = set()
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        ident = str(entry.get("id"))
        url = str(entry.get("issue_comment_url") or "")
        issues.add(url.split("#", 1)[0])
        sha = str(entry.get("checkpoint_sha") or "")
        if not COMMIT.fullmatch(sha) or _run_git(root, "cat-file", "-e", f"{sha}^{{commit}}").returncode != 0:
            out.append(f"{ident}: its checkpoint {sha or '(none)'} is not a commit of this repository")
            continue
        if _run_git(root, "merge-base", "--is-ancestor", sha, "HEAD").returncode != 0:
            out.append(f"{ident}: its checkpoint {sha} is not in HEAD's history")
            continue
        held = _at_commit(root, sha, path)
        there = [e for e in held or [] if isinstance(e, Mapping) and e.get("id") == entry.get("id")]
        if not there or _without_sha(there[0]) != _without_sha(entry):
            out.append(f"{ident}: not what its checkpoint holds")
        when = _run_git(root, "show", "-s", "--format=%cI", sha).stdout.decode().strip()
        try:
            written = datetime.fromisoformat(str(entry.get("created_at")).replace("Z", "+00:00"))
            if written > datetime.fromisoformat(when):
                out.append(f"{ident}: written after its checkpoint commit")
        except ValueError:
            out.append(f"{ident}: no time it was recorded (created_at)")
        if (
            first_published is not None
            and entry.get("kind") not in AFTER_PUBLICATION
            and _run_git(root, "merge-base", "--is-ancestor", first_published, sha).returncode == 0
        ):
            out.append(f"{ident}: its checkpoint comes after the results were published")
    if len(issues) > 1:
        out.append("the deviations are comments on more than one issue")
    if issue is not None and issues and issues != {issue.rstrip("/")}:
        out.append("a deviation is not a comment on the registered issue")
    versions = [_at_commit(root, sha, path) for sha in _commits(root, freeze, path)]
    for before, after in zip(versions, [*versions[1:], entries], strict=True):
        if not isinstance(before, list) or not isinstance(after, list):
            continue
        kept = len(after) >= len(before) and all(
            _without_sha(old) == _without_sha(new)
            and (
                not isinstance(old, Mapping)
                or not old.get("checkpoint_sha")
                or old.get("checkpoint_sha") == new.get("checkpoint_sha")
            )
            for old, new in zip(before, after, strict=False)
        )
        if not kept:
            out.append(f"{path} is append-only: an entry was changed or removed")
            break
    return out


def write_once_problems(root: Path, freeze: str, paths: Sequence[str] = WRITE_ONCE) -> list[str]:
    """Each of ``paths`` that more than one commit changed since the freeze: the pre-registration and the posted
    phase-2 record are written once and never edited."""
    out = []
    for path in paths:
        count = len(_commits(root, freeze, path))
        if count > 1:
            out.append(f"{path}: changed by {count} commits since the freeze; it is written once")
    return out


def analysis_table_problems(kinds: Mapping[str, str]) -> list[str]:
    """The pre-registration's table against the one the analysis applies (``evals.analysis.DEVIATION_CONSEQUENCES``, where it has one)."""
    from evals import analysis

    applied = getattr(analysis, "DEVIATION_CONSEQUENCES", None)
    if applied is None:
        return []
    differing = sorted(k for k in set(applied) | set(kinds) if applied.get(k) != kinds.get(k))
    return (
        [
            f"the pre-registration's table of deviation kinds differs from the analysis' in {', '.join(differing)}"
        ]
        if differing
        else []
    )


# --------------------------------------------------------------------------------------------------
# The phase-2 tree
# --------------------------------------------------------------------------------------------------


def _git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=True).stdout


def phase2_record(
    root: Path = ROOT, head: str = "HEAD", patterns: Sequence[str] = PHASE2_PATTERNS
) -> dict[str, Any]:
    """The presenter at a commit: the commit, the sha256 of each of its files matching ``patterns`` (but
    :data:`PHASE2_EXCLUDE`), and their tree hash."""
    sha = _git(root, "rev-parse", "--verify", f"{head}^{{commit}}").decode().strip()
    names = [
        name for name in _git(root, "ls-tree", "-r", "-z", "--name-only", sha).decode().split("\0") if name
    ]
    files = {
        name: hashlib.sha256(_git(root, "cat-file", "blob", f"{sha}:{name}")).hexdigest()
        for name in sorted(names)
        if any(matches(name, p) for p in patterns)
        and not any(matches(name, p) for p in PHASE2_EXCLUDE)
        and not _hidden(name)
    }
    return {
        "schema": PHASE2_SCHEMA,
        "head": sha,
        "patterns": list(patterns),
        "exclude": list(PHASE2_EXCLUDE),
        "files": files,
        "tree_sha256": tree_sha256(files),
    }


def _names(deviation: Mapping[str, Any], path: str) -> bool:
    evidence = deviation.get("evidence") or []
    return any(isinstance(e, str) and (e == path or e.startswith(f"{path} ")) for e in evidence)


def phase2_problems(record: Mapping[str, Any], root: Path, deviations: Any) -> list[str]:
    """Each presenter file of the checkout that is not the posted phase-2 tree's, unless a ``code_hash_changed``
    deviation names its path in its evidence."""
    posted = dict(record.get("files") or {})
    now = {
        rel: sha256_file(root / rel)
        for rel in matching(
            root, record.get("patterns") or PHASE2_PATTERNS, record.get("exclude") or PHASE2_EXCLUDE
        )
    }
    changes = [d for d in deviations or [] if isinstance(d, Mapping) and d.get("kind") == "code_hash_changed"]
    out = []
    for path in sorted(posted.keys() | now.keys()):
        if posted.get(path) == now.get(path):
            continue
        if path not in now:
            what = "removed since the posted phase-2 tree"
        elif path not in posted:
            what = "not in the posted phase-2 tree"
        else:
            what = "differs from the posted phase-2 tree"
        if not any(_names(d, path) for d in changes):
            out.append(f"{path}: {what}, and no code_hash_changed deviation names it")
    return out


# --------------------------------------------------------------------------------------------------
# The pre-registration itself
# --------------------------------------------------------------------------------------------------


def required_problems(prereg: Mapping[str, Any]) -> list[str]:
    """Each required field the pre-registration lacks."""
    out = [f"{key}: missing" for key in REQUIRED if key not in prereg]
    for section, keys in REQUIRED_IN.items():
        values = prereg.get(section)
        if isinstance(values, Mapping):
            out += [f"{section}.{key}: missing" for key in keys if key not in values]
    return out


def files_problems(prereg: Mapping[str, Any], root: Path = ROOT) -> list[str]:
    """Each file of the ``files`` map, and each named file (:data:`NAMED_FILES`), that is not byte for byte the
    registered one."""
    out = []
    for path, sha in sorted((prereg.get("files") or {}).items()):
        file = root / path
        if not file.is_file():
            out.append(f"{path}: missing")
        elif sha256_file(file) != sha:
            out.append(f"{path}: differs from the pre-registration (sha256)")
    for name in NAMED_FILES:
        named = prereg.get(name) or {}
        file = root / str(named.get("file"))
        if not file.is_file():
            out.append(f"{name}: {named.get('file')} missing")
        elif sha256_file(file) != named.get("sha256"):
            out.append(f"{name}: {named.get('file')} differs from the pre-registration (sha256)")
    return out


def _words(text: str) -> str:
    """Text with Markdown quote marks dropped and every run of white space one space."""
    return " ".join(" ".join(re.sub(r"^\s*>\s?", "", line) for line in text.splitlines()).split())


def verbatim_problems(prereg: Mapping[str, Any], md: str) -> list[str]:
    """The pledge must be :data:`PLEDGE`, and it and every section's ``text`` (the rules) word for word in the .md."""
    out = []
    pledge = prereg.get("pledge")
    if pledge != PLEDGE:
        out.append("pledge: not the registered pledge")
    flat = _words(md)
    texts = [("pledge", pledge)] + [
        (f"{key}.text", value["text"])
        for key, value in sorted(prereg.items())
        if isinstance(value, Mapping) and isinstance(value.get("text"), str)
    ]
    for label, text in texts:
        if not isinstance(text, str) or _words(text) not in flat:
            out.append(f"{label}: not word for word in the .md")
    return out


def changed_since(root: Path, freeze: str) -> list[str]:
    """The paths HEAD changed since the freeze commit."""
    out = _git(root, "diff", "--name-only", "-z", freeze, "HEAD").decode()
    return sorted(name for name in out.split("\0") if name)


def _patterns(values: Any) -> list[str]:
    return [str(v["path"]) if isinstance(v, Mapping) else str(v) for v in values or []]


def path_problems(changed: Iterable[str], frozen: Mapping[str, Any]) -> list[str]:
    """Each changed path that the pre-registration froze (``identical_paths``), or allows in none of its lists."""
    identical = _patterns(frozen.get("identical_paths"))
    allowed = [
        pattern
        for key in ("allowed_after_freeze", "allowed_while_recording", "allowed_at_publish")
        for pattern in _patterns(frozen.get(key))
    ]
    frozen_hits, unlisted = [], []
    for path in changed:
        if any(matches(path, p) for p in identical):
            frozen_hits.append(f"{path}: frozen since the freeze (identical_paths)")
        elif not any(matches(path, p) for p in allowed):
            unlisted.append(f"{path}: not in any list of paths allowed to change after the freeze")
    return sorted(frozen_hits) + unlisted


# --------------------------------------------------------------------------------------------------
# The command line
# --------------------------------------------------------------------------------------------------


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return DEVIATIONS_PATH


def _report(problems: Sequence[str], ok: str) -> int:
    for line in problems:
        print(line)
    print(ok if not problems else f"{len(problems)} mismatch{'es' if len(problems) != 1 else ''}")
    return 1 if problems else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.prereg_hashes", description=__doc__.split("\n\n")[0]
    )
    what = parser.add_mutually_exclusive_group(required=True)
    what.add_argument("--section", choices=(*SECTIONS, "all"), help="print a section of the pre-registration")
    what.add_argument("--deviations", type=Path, metavar="FILE", help="check a deviations file against B")
    what.add_argument(
        "--phase2", type=Path, metavar="FILE", help="the phase-2 record: check it, or --write it"
    )
    parser.add_argument("--check", type=Path, metavar="FILE", help="with --section: compare with this file")
    parser.add_argument("--final-day", help="with --section data: the planned day (default: the plug-in's)")
    parser.add_argument(
        "--prereg",
        type=Path,
        default=PREREG,
        help="with --deviations: the pre-registration (its deviation_kinds)",
    )
    parser.add_argument(
        "--history",
        action="store_true",
        help="with --deviations: also check by --root's git history that each was recorded at the time",
    )
    parser.add_argument("--head", default="HEAD", help="with --phase2 --write: the posted phase-2 commit")
    parser.add_argument(
        "--path", action="append", help="with --phase2 --write: patterns instead of the default"
    )
    parser.add_argument("--write", action="store_true", help="with --phase2: write the record")
    parser.add_argument(
        "--with-deviations", type=Path, metavar="FILE", help="with --phase2: the deviations file"
    )
    parser.add_argument("--root", type=Path, default=ROOT, help="the checkout to read (default: this one)")
    args = parser.parse_args(argv)
    try:
        if args.section is not None:
            names = SECTIONS if args.section == "all" else (args.section,)
            computed = sections(names, args.root, args.final_day)
            if args.check is None:
                print(json.dumps(computed, ensure_ascii=False, indent=1))
                return 0
            return _report(mismatches(computed, _load(args.check)), "0 mismatches")
        if args.deviations is not None:
            prereg = _load(args.prereg)
            kinds = kinds_table(prereg.get("deviation_kinds"))
            entries = _load(args.deviations)
            problems = deviation_problems(entries, kinds) + analysis_table_problems(kinds)
            if args.history:
                registered = prereg.get("registered") or {}
                problems += history_problems(
                    args.root,
                    entries,
                    freeze=registered.get("freeze_sha"),
                    path=_relative(args.deviations, args.root),
                    issue=registered.get("issue_url"),
                )
            count = len(entries) if isinstance(entries, list) else 0
            return _report(problems, f"{count} deviation(s), well formed")
        if args.write:
            record = phase2_record(args.root, args.head, args.path or PHASE2_PATTERNS)
            args.phase2.parent.mkdir(parents=True, exist_ok=True)
            args.phase2.write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")
            print(
                f"{args.phase2.name}: {len(record['files'])} files at {record['head']}, tree {record['tree_sha256']}"
            )
            return 0
        deviations = _load(args.with_deviations) if args.with_deviations else []
        found = phase2_problems(_load(args.phase2), args.root, deviations)
        return _report(found, "the presenter is the posted phase-2 tree")
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"{parser.prog}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
