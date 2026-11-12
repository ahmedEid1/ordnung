# Pre-registration: the final evaluation of Ordnung 0.4.0

This file and `final-0.4.0.json` beside it (the same rules, read by code) are committed before any final recording,
in the commit after the data (commit A), and are never edited. Everything that happens later and differs from them
is recorded at the time in `deviations-0.4.0.json` (empty at registration) and on the pre-registration issue. This
file names ids, counts, hashes, paths and commands only: no letter, no label, no prompt and no question.

## 1. Summary

What is evaluated: Ordnung 0.4.0 at the freeze merge `f2cacf64771a8736262f52a535d29b79032969c9` (PR #51, merged
2026-11-11T16:21:55Z), against three baselines, with the pinned model `claude-sonnet-5`, on two new splits written
blind after the freeze — holdout4 (read three times) and newkinds (read once) — on the held-out Ask set (three runs)
and on the stress cells I1 and D1. The data is commit A `0924c192a49791e6a9949dac620a14cd5ea95df2`.

Planned recording day D0 = **2026-11-24** (Tuesday); the sets are valid through L = D0 + 7 = **2026-12-01**
(Tuesday); every scored date is on or after 2026-12-02. These are the dates of amendment K26 (the owner's decision
of 2026-11-11). Registered before any recording, published whatever the result (the pledge, §23).

## 2. Frozen inputs

Byte-identical from the freeze to publication (`frozen.identical_paths`):

- `src/ordnung/**`
- `evals/*.py`
- `evals/prompts/**`
- `evals/present/final.py`
- `evals/present/final_templates.json`
- `tests/test_preregistration.py`
- `tests/test_present_final.py`
- `tests/test_final_gates.py`

The only exception is the runner-defect rule (§18), itself a deviation. Paths allowed to change after the freeze,
each with its reason, are listed in the JSON: `allowed_after_freeze` (commit A's 423 paths and
`evals/preregistration/**`), `allowed_while_recording` (`evals/recorded/**`, `evals/results/pending/**`, the
deviations and phase-2 records) and `allowed_at_publish` (results, retakes, the presenter as posted in phase 2, the
README between its markers and its two bullets "Held out." and "Pre-registered next.", `docs/evals*.md`, the charts,
`ci.yml`'s gates, tests other than the three frozen ones, the report page's test, `CHANGELOG.md` and, by K26,
`evals/README.md`'s example dates). `tests/test_preregistration.py` fails on any other changed path.

| Pinned | Value |
|---|---|
| model | `claude-sonnet-5` (the only one; served models allowed: `claude-sonnet-5`) |
| code digest (`evals.conditions._code_digest`) | `1c10b446736a6c78` |
| fingerprint ordnung | `1b4fe7c855fc0eee` |
| fingerprint llm_only | `2122d4f180b656c7` |
| fingerprint llm_rules_text | `b7676ed2b3effc94` |
| fingerprint llm_rules_tool | `25becf824b6886b6` |
| prompt hashes | Ordnung's 11 prompts, each baseline's digest and the tools' digest `d5ae6026bb3aeb2c` (hashes only, in the JSON) |
| `environment()` (runner) | holidays 0.105, pypdfium2 5.13.0, pillow 13.0.0, fpdf2 2.8.8, pydantic 2.13.5, python 3.11 |
| `environment()` (generator) | fpdf2 2.8.8, pypdfium2 5.13.0, pdfium 153.0.7999.0, pillow 13.0.0, zlib 1.3, holidays 0.105, fonttools 4.66.0 |
| Claude Code CLI | `2.1.322 (Claude Code)` |
| settings | concurrency 3, timeout 300 s, `TOOLS_BUDGET_USD` 1.0 |
| interpreter | Python 3.11.17 |
| `evals/recorded/ask/claude-sonnet-5/prompts.lock.json` | `c888a223719bc0b7b0e4aa4fac01b5920b88406e8af092297963107d5e05f185` |
| `evals/recorded/ask/claude-sonnet-5/requests.lock.json` | `fafa4b674ba07d3219c8c70f8f41ef6cd3c66b0141ffe9c7940337e5388024f2` |
| `evals/recorded/claude-sonnet-5/prompts.lock.json` | `58abe975dc1ea1413d7c2bfaaf7db9ba494dd22dd3214727c69be405673a275d` |
| `evals/recorded/claude-sonnet-5/requests.lock.json` | `cdcd3cccacaa79426fc26287aa24936cd40db5f8a149ae304575020b403832a7` |
| `evals/results/INDEX.json` | `80d09dfb033981408d21efa5b2dc3c12bb9b1ae33b3ff727baa755ca19f20263` (at commit A; the freeze's was `54a9f122aa6ec446…`) |
| `evals/results/items.csv` | `2dd4d67664204223ec2d0f8e3bff92bcda82418fd178350cc2cf4907f06a4b7b` |

The code digest, fingerprints, prompt hashes, environments and locks equal the Stage 1 freeze record; INDEX.json is
the one value that moved, because commit A rewrites it (`python -m evals.reproduce --write`). The `code` map (43
files: the scorers, the analysis, the post-run scripts, these tools and the three frozen tests) pins the code that
scores, analyses and presents the run besides the code digest.

## 3. Data

- **holdout4**: 126 entries (104 PDFs, 22 photos), 24 adversarial, **112 scored items**, 88 clusters (a letter with its photo), variants K–N, 13 families.
- **newkinds**: 32 entries (28 one-page letters of 7 kinds, 4 photos), **28 scored items**, 24 clusters.
- **Held-out Ask** ("Ask: new questions on the demo household"): **100 questions** (core 57, household 16, recurrence 11, unanswerable 16), 5 repeating to-dos and **60 attacks**: 160 turns a run. Planned: 104 questions (core 20 × 3 phrasings, household 16, recurrence 12, unanswerable 16) and 60 attacks; dropped, counted: ho-rec-q05, ho-core-07-de, ho-core-07-en, ho-core-07-en-paraphrase and the to-do ho-rec-salary (ho-rec-salary failed the window check (python -m evals.ask.heldout --validate) after W2 and after both fix rounds (at most two fix rounds per writer; a third failure drops the item), and ho-rec-q05 is the one question that names it; ho-core-07's three phrasings because W2a upheld the blind answer over the gold on 3 of 3, which sends a question back to a W2-fix round, and none was left).
- **Stress**: 48 base letters of holdout4, seed 20261029, cells I1 and D1 (48 perturbed letters each); templates `29569b827009d2ec…` (40 sentences), manifest `9bc8b7549598a7fd…`.

The D0 build: `python -m evals.generate --final-day 2026-11-24` gives the manifest
`7bf30e0b171222622a7a24fd321e4137fa18f3d87786d56a05e6d3ed668b9d02` and the dataset tree
`be9d50fce8383b6b3e7528ce55b3751eed0c0c86a82aa234fee952ccc760ee75` (682 files); the generator tree (`evals/gen/**`,
`generate.py`, `verify_labels.py`) is `214fc5d6086582fa2a36b208a2d33274cb6badfbc877bb6e033f4f9a0f334ca7`. The
`files` map of the JSON gives the sha256 of each of the 434 final data files (letters, photos, facts, provenance,
generator modules, the Ask set and the stress manifest). Conventions: 33 ids, 11 of them disputed
(`data.conventions`); scored items whose label has another defensible date (`data.s_conv_items`, the manifest's
`convention_alternatives`): holdout4 23 of 112 (3 of them photos), newkinds 12 of 28 (2 photos).

## 4. Blind writing and audit

The statement:

> written and audited by a Claude model, run through Claude Code, that is not the benchmarked model; every agent
> session was isolated from `src/`, `docs/`, prompts and results; what stays visible: the benchmark's name, and the
> label vocabulary (it tells a writer that a reader is expected to warn on injections and conflicting dates)

What the sandboxes held besides: the W1 sandboxes held the DejaVu fonts under src/ (to render letters) and the W2
sandboxes the demo household's sample letters under src/ordnung/demo/samples/ (the Ask set's documents); nothing
else under src/, docs/, prompts or results. The model: every session ran a Claude model through Claude Code, chosen
with an explicit --model that is not the benchmarked model (claude-sonnet-5); that model's identifier is not named
here (K16); each session's writer-run.jsonl, which names it, is registered by its sha256 only. All 17 sessions (the
writers W1 and W2, the auditors A1 and A1c, the adjudicator A1′, the blind answerer W2v and the adjudicator W2a) ran
one and the same model: every registered writer-run.jsonl names the same --model. Through Claude Code, that model
also co-authored most of Ordnung's code (it is the one named in the Co-Authored-By trailers of 971 of the 1069
commits up to the freeze). The audit and the blind gold check therefore catch slips within a session; they do not
catch a misreading of the law that this model makes consistently, which would score as right for Ordnung. The only
check outside that model is the owner's label check (owner_checks), still pending.

| Session | Role | Sandbox commit | File list | Lint before | Lint of the outputs | Brief (+ lines vs template) | Writer log (as written) | writer-run.jsonl | Log check (calls / denied / mismatches) |
|---|---|---|---|---|---|---|---|---|---|
| w1a | W1a: wrote holdout4 | `f2cacf64` | `aec0957ccf87…` | 19 allowed, 0 outside | 2 allowed, 0 outside | `139f9d79f706…` (+0) | `df99a19d3325…` | `7101ddb619ba…` | 57 / 0 / 0 |
| w1b | W1b: wrote newkinds | `a6266607` | `fd18b33fca89…` | 19 allowed, 0 outside | 6 allowed, 0 outside | `52d4d4e66eef…` (+0) | `d704cf85daac…` | `5a740d1571db…` | 66 / 0 / 0 |
| w1c | W1c: wrote the stress templates | `e51d5d07` | `bc19a6de039d…` | 22 allowed, 0 outside | 2 allowed, 0 outside | `25377a3087a9…` (+0) | `e394f1bf4899…` | `7728f082ac05…` | 5 / 0 / 0 |
| w1c-fix1 | W1c's fix round 1 | `446687b6` | `3ca00d990839…` | 23 allowed, 0 outside | 1 allowed, 0 outside | `3018580da260…` (+11) | `ab6e4656e4df…` | `f36b4b2edd35…` | 4 / 0 / 0 |
| a1-1 | A1 batch b1: convention-free audit | `ab35b4d2` | `ac350f1afdbd…` | 1 allowed, 0 outside | 2 hits, no allow-list (sealed reading) | `cb783a6d7657…` (+0) | `cd7c65f50f05…` | `9cba7fe0b773…` | 61 / 1 / 0 |
| a1-2 | A1 batch b2: convention-free audit | `81991bd8` | `5b4af414ddcf…` | 1 allowed, 0 outside | 9 hits, no allow-list (sealed reading) | `85e7cbd2641e…` (+0) | `167f2d53375b…` | `91ba9d4487b0…` | 69 / 1 / 0 |
| a1-3 | A1 batch b3: convention-free audit | `64d621ff` | `6a8f1d71ae91…` | 1 allowed, 0 outside | 12 hits, no allow-list (sealed reading) | `fddb00bd8c4c…` (+0) | `6f432dd8e4e2…` | `3eee5a516db8…` | 101 / 1 / 0 |
| a1-4 | A1 batch b4: convention-free audit | `0e3a323b` | `5307914778b7…` | 1 allowed, 0 outside | 2 hits, no allow-list (sealed reading) | `b93ba6926fe1…` (+0) | `7ca9cf596536…` | `a978310d63c4…` | 45 / 0 / 0 |
| a1c | A1c: the conventions applied to A1's sealed facts | `cfc8dcf6` | `b097bf0d4960…` | 15 allowed, 0 outside | 11 hits, no allow-list (sealed reading) | `893d65628a5b…` (+0) | `e44cf5257baa…` | `d5808403fdb0…` | 29 / 1 / 0 |
| a1p | A1′: adjudication of the audit's disagreements | `29fd1afe` | `1cc97c5fb634…` | 1 allowed, 0 outside | 0 hits | `9b08c3065e8e…` (+0) | `c9d79c101b73…` | `2e4b32855a76…` | 19 / 0 / 0 |
| w1fix | W1-fix round 1 | `873f1982` | `ff474124a5c8…` | 19 allowed, 0 outside | 0 allowed, 0 outside | `0c3d1ca87511…` (+0) | `c274bb757094…` | `bec752a9e75a…` | 25 / 0 / 0 |
| w1fix2 | W1-fix round 2, the writer's last | `80596b2a` | `cf8bbcc8c4b0…` | 19 allowed, 0 outside | none kept (below) | `0c3d1ca87511…` (+0) | `d9cb0bfcc1ef…` | `f352f7302236…` | 6 / 1 / 0 |
| w2 | W2: wrote the held-out Ask set | `f2cacf64` | `e49a288472e6…` | 2 allowed, 0 outside | 1 allowed, 0 outside | `a97c1937f570…` (+0) | `149fb0e9c97f…` | `fdb78fd69ab0…` | 23 / 1 / 0 |
| w2-fix | W2-fix round 1 | `846d9ce5` | `aeeda9047c87…` | 3 allowed, 0 outside | 1 allowed, 0 outside | `4a13f2941e5f…` (+0) | `af52568d3b0c…` | `4f50f7bf4100…` | 22 / 1 / 0 |
| w2-fix2 | W2-fix round 2, the writer's last | `aa2643a5` | `eb31d33ee2c3…` | 3 allowed, 0 outside | none kept (below) | `4a13f2941e5f…` (+0) | `200b5091edbf…` | `909f13f478f8…` | 20 / 0 / 0 |
| w2v | W2v: blind gold check | `6cabd24e` | `16a2ce7b5c82…` | 0 allowed, 0 outside | 0 hits | `7bf869c2b02b…` (+0) | `fb5a231858ae…` | `2cf529990e98…` | 12 / 1 / 0 |
| w2a | W2a: adjudication of W2v's disagreements | `6cabd24e` | `eb16eb6e1934…` | 0 allowed, 0 outside | 0 hits | `9f5eb8e9a3e6…` (+0) | `0b860bf44ab6…` | `10419f05b055…` | 6 / 0 / 0 |

Each sandbox was built from the freeze sha (W1a, W2) or from the latest local wip commit of its chain's data
worktree. Those wip commits are local only, never pushed, and not ancestors of commit A; each holds the data as it
stood when its session started, not the final state (later fix rounds and K27 came after). Commit A holds the final
state, and what each sandbox held is recorded by its committed sandbox-files list and that list's sha256. Full
hashes are in the JSON (`blind_writing.sessions`); the records themselves are under
`evals/dataset/provenance/<session>/`. The briefs as run are in `briefs/`, with `briefs/DIFFS.md` against their
templates (`evals/preregistration/brief-templates/`): each is its template with D0, L (and N, BATCH) filled, except
W1c's fix round, which adds its fix-round section. No test reads the briefs or DIFFS.md: check them against the
sha256s in `blind_writing.sessions[].brief` and `blind_writing.briefs` (§21). Not run: A1-re (no letter's or photo's
bytes changed after the seal (W1-fix changed two offered slots' labels only)); W1-fix round 3, W2-fix round 3 (at
most two fix rounds per writer).

The lint of each session's outputs (sessions[].lint_of_its_outputs) checks a writer's copied files against that
writer's allow-list; the auditors' and adjudicators' sealed readings have no allow-list, so every hit there counts
as outside. The A1 and A1c hits are words on the lint's term list used in their ordinary sense in the auditors' own
notes and derived facts (mostly 'recorded'), which no writer and no condition reads. W1-fix round 2 copied nothing
out (it changed no file), so it has no output lint; for W2-fix round 2 the lint ran (0 outside, recorded in the
orchestrator's notes) but its output was not kept.

**The audit** (counts only; the tally was written before any adjudication. The first 5,359 bytes (101 lines) of
`evals/dataset/provenance/audit/audit-tally.md` are the file as committed in the local wip commit `29fd1afe` at
2026-11-11T21:01:15Z, sha256 `bdbbe580f3b056dc6adad2bf55e8cfe1084cb64c036a1bd75c1aaedce0291572`, before A1′ started
at 2026-11-11T21:05Z. The other lines were appended after adjudication. That wip commit was local and not public
before commit A.)

- Seal: `evals/dataset/provenance/audit/audit-seal.txt`, 5 lines, sha256 as written `bc2865cc7fde6ad7fb178bb0220419876df990dd5cf24c948405fdf63b2f603c`; opaque map `151e14cc8da9491471b2d66eed4d586bf661ee7800a421ccbb9898f52cffec59` (158 letters in 4 batches).
- A1 (convention-free) vs the labels, 178 slots: agree 114, overlapping candidates 14, disagree 1, not derivable 49.
- A1c (conventions applied) vs the labels: agree 146, overlapping candidates 1, disagree 0, not derivable 31. A1's non-agreements: convention 32, reading or arithmetic 32. Procedure start: same 4, not counted 174, no difference.
- A1′ on 32 slots: X_right 19, Y_right 13, both_wrong 0, ambiguous 0; mapped through the key (`1550dff1d6952115…`): the label upheld on 30, the second reading on 2. Consequence: the 30 keep their labels (facts from A1′); the 2 (holdout4 offered slots o0, holdout4-price_increase-L1 and -N1) went to W1-fix and are undatable, as ruled; no letter bytes changed, so no A1-re.
- After adjudication: A1 agree 116 / candidates 14 / disagree 1 / not derivable 47; A1c 148 / 1 / 0 / 29.
- facts.json: holdout4 `161d0e5de7792354…` (A1 98, A1′ 18); newkinds `81df177f5187b907…` (A1 23, A1′ 8).

The published sentence:

> W1's `law.py` and the sealed convention-free audit agree on 114 of 178 slots (14 more overlap as candidate sets),
> on 146 of 178 with the conventions applied (1 more overlap); after adjudication the labels stand on 30 of the 32
> adjudicated slots, and the other 2 (offered slots) are now undatable, as ruled, so the audit agrees on 116 of 178
> slots, and on 148 of 178 with the conventions applied (holdout4 and newkinds together); `verify_labels` confirms
> that each label follows from the audit's facts (for adjudicated items this is not an independent check).

**The held-out Ask set's blind gold check:** W2's gold and the blind answerer (W2v) agree on 100 of 103 questions (3
disagreements, 0 without a reply). W2a on the 3 disagreements: X_right 2, Y_right 1, both_wrong 0, ambiguous 0; the
blind answer upheld on 3, the gold on 0; no W2-fix round was left, so the three phrasings of ho-core-07 were dropped
(counted).

**Amendments to the data procedure: K22, K27.** K22: A1, A1c, A1′ and the facts state a procedure start only where
it can change the date (a Land authority's decision counted from its deemed delivery in BW, BY or MV); every other
slot is not_counted. K27 was the owner's decision of 2026-11-12 03:10 UTC. It was made after the audit and after
both writer fix rounds, when the frozen `verify_labels` rule 8 failed on 137 of 147 label parts (0 date problems)
and no fix round was left; under the procedure as written, every scored item would have been dropped. That
alternative was rejected in favour of setting the tags from the blind facts; no date, letter or count moved. K27, as
VERIFICATION.md says it:

> Amendment K27 (decided before registration): the convention tags of holdout4 and newkinds are the ids the blind
> audit's facts apply (A1c, or A1′ where it ruled), so `verify_labels` checks them for consistency only; every date
> was still re-derived from the facts independently (0 date problems). The writer's tags and the facts' ids differed
> on 137 of 147 label parts: 119 in non-disputed ids only (mostly c01, c04 and c06, which describe how the generator
> builds labels), 18 in a disputed id (11 scored items lost c07, which gives no other date, and kept c02, c03 and
> their other-reading dates; 6 offered dates gained c10, two of them also c22, each with an empty other-reading
> list; 1 undated item gained c02 and c03). No date, other-reading date of a scored item, letter, composition or
> S-conv count changed. The writer's tags: provenance/k27/writer-tags.json (sha256
> 9a48dcd286432cd48b186de5db28e79f4f795109dbdce3a146e3a535e9fd9242).

The S-conv count is 23 holdout4 and 12 newkinds scored items (`data.s_conv_items`), unchanged by K27: the pre-K27
manifest (1098bcbff7d91d9f…) has the same 35 (entry, item) pairs with the same other dates.

Edits by the orchestrator after the sessions (no model call): `evals/ask/heldout/recurrence_gold.py`: type
annotations only, for the repository's mypy (the W2 chain's checks had no mypy step): dict -> dict[str, Any] (6),
the generator's -> Iterator[datetime.date], and the imports of Iterator and Any (sha256 as written
`f62d7e11adb60b9c…`, committed `aa9ebdfc19b73866…`; the module's AST without annotations and those two imports
equals the one W2 wrote; python -m evals.ask.heldout --validate and heldout_check give output byte-identical to the
file as written); `evals/dataset/provenance/ (47 files, 80 occurrences)`: the orchestrator's scratch folder written
as $S; listed in evals/dataset/provenance/scratch-paths.txt with each file's sha256 as written and as committed.

## 5. Runs and order

| Step | Read | Mandatory | Size | Expected $ | Expected wall (h) | Latest start (UTC) |
|---|---|---|---|---|---|---|
| R1 | newkinds r1 | yes | 32 letters, 132 calls | 8.37 | 0.54 | 20:50 |
| R2 | holdout4 r1 | yes | 126 letters, 526 calls | 32.96 | 2.12 | 18:25 |
| R3 | Ask r1 | yes | 160 turns | 5.51 | 0.18 | 21:30 |
| R4 | holdout4 r2 | yes | 126 letters, 526 calls | 32.96 | 2.12 | 18:25 |
| R5 | holdout4 r3 | yes | 126 letters, 526 calls | 32.96 | 2.12 | 18:25 |
| R6 | Ask r2, then Ask r3 | no | 320 turns | 11.02 | 0.7 | 21:30 |
| R7 | stress I1 + D1 | no | 192 calls | 14.78 | 0.9 | 20:20 |

Every benchmark read records all four conditions (Ordnung, llm_only, llm_rules_text, llm_rules_tool), and every read
is made whatever earlier reads show. R1 … R7 in this order; the next step starts only after the previous one is
verified and its checkpoint pushed; one recorder at a time. Each recording day starts with a micro-smoke into
scratch. Verification of each step: a zero-token replay with --check of the step's results file, sealed (exit code
and the fake CLI's call count only), audit_recordings, the ledger sum against its cap, the day index, git status,
then a pushed checkpoint commit.

Commands (run from the recording tree, the A+B merge):

- R1, R2, R4, R5: `python -m evals.run --live --split <split> --model claude-sonnet-5 --repeat <N> --today <the recording day> --date <the read's first day> --concurrency 3 --timeout 300 --max-cost-usd <cap> [--wait-on-limit <hours>] --stop-file <file> --stop-at 23:00 --no-docs --results-dir evals/results/pending`
- R3, R6: `python -m evals.ask --set heldout --live --write --model claude-sonnet-5 --repeat <N> --today <the recording day> --date <the read's first day> --concurrency 3 --max-cost-usd <cap> [--wait-on-limit <hours>] --stop-file <file> --stop-at 23:00 --results-dir evals/results/pending`
- R7: `python -m scripts.eval_perturb --cells I1,D1 --live --model claude-sonnet-5 --today <the recording day> --date <the read's first day> --concurrency 3 --timeout 300 --max-cost-usd <cap> [--wait-on-limit <hours>] --stop-file <file> --stop-at 23:00 --noise-floor-from-runs <h4 r1> <h4 r2> <h4 r3> --out evals/results/pending (a budget cut uses --cells I1)`
- micro-smoke, each recording day first: `python -m evals.harness smoke --scratch <dir> --ids dev-tax_assessment-A1 --conditions llm_only --ask-only cross-pay-this-week --max-cost-usd 0.2 (into scratch, thrown away; $0.11, K25)`
- never: --refresh, --allow-another-today, --quiet, --no-resume
- resume: the identical command (same --date and --results-dir), --today the new day, a new cap; after the third resume of a step with unanswered letters or turns, --allow-errors with an unanswered deviation

## 6. Budget

Expected **$140.1** in all (pre_freeze_smokes 1.45, R1 8.37, R2 32.96, R3 5.51, R4 32.96, R5 32.96, R6 11.02, R7
14.78, micro_smoke_per_recording_day 0.11); K25 moved the expected total from $139.2 (the runbook's draft of this
registration) to $140.1. The Ask runs ask 160 turns, not the 164 planned (4 questions were dropped,
data.ask_heldout_set.dropped); forecast.py measures $ per turn. Spent before this registration: $1.4508 (the
smokes). **Hard stop $150**, which includes the smokes, the daily micro-smokes and every final recording, retakes
included. Per-step stop: 1.15 × the latest forecast of the step, within the 150 (cap.py: min(1.15 × forecast, the
step's spend + room + its retakes' spend), room = 150 − total spent − the forecast of the other remaining mandatory
steps − 1.0). Re-forecast after R1 and after R2. Mandatory: R1–R5; optional, in this order: R6 r2, R6 r3, R7 I1, R7
D1. Cut order: R7:D1, R7:I1, R6:r3, R6:r2, applied before the next holdout4 read starts if the forecast total passes
150; never a holdout4 read before them; each cut is a budget_cut deviation recorded at the time and is published as
"not run: budget". Headroom: a step starts only if u_now + 1.2 × s × (forecast $ of the steps planned for the rest
of this window) + 0.15 ≤ 1.0; otherwise the steps that fit run, in order, and the rest move to the next day of the
window. The ledger sum is a lower bound: up to 3 calls in flight at a kill are billed but not cassetted.

## 7. Recording-day rule

> The final sets were written for the planned day D0 and are valid through L = D0 + 7. Every scored date, contract
> date and appointment in them is after L (checked by `generate.py`, `verify_labels.py` and, for Ask,
> `validate_window`). Each unit — one letter in one read with all its conditions, one Ask run, one stress invocation
> — is told the UTC day of its recording as today and keeps that day; the model never sees two dates. A benchmark
> read may span several UTC days inside [D0, L]; a unit cut at a day's end or by a stop is recorded again whole on
> its new day, counted as a retake, and its first answers are published. No letter, label or question changes
> because of the day. The weekly usage limit resets on Tuesdays at 06:00 UTC; D0 and L are Tuesdays. No step starts
> unless 1.5 × its expected wall time plus its check ends by 22:00 UTC, and no new unit starts after 23:00 UTC.

D0 = 2026-11-24, L = 2026-12-01; reserve: D0+1 … D0+6 (Wed 25 – Mon 30 Nov 2026) when the headroom rule passes; L
(Tue 1 Dec 2026) the contingency day.

## 8. Contingency

> The set is {holdout4, newkinds}, one manifest. Complete reads stand. An incomplete holdout4 r2/r3, Ask r2/r3 or
> stress at the end of L is "not recorded: window closed". The analysis runs on k ≥ `min_reads` = 2; with k = 1, r1
> is primary with the cluster tests. Before holdout4 r1 is complete, an incomplete newkinds r1 or holdout4 r1 at the
> end of L retires the set. Every recorded unit of a retired set is published in a results file marked `retired`,
> appears in Deviations, and its hash goes into the replacement's B. Retirement needs the `limits.jsonl` and
> `spend.tsv` lines, committed at the time. Once holdout4 r1 is complete, the set cannot be retired. The pinned
> model unavailable ⇒ stop, never switch, publish what exists. A CLI version change ⇒ continue only if the served
> model is `claude-sonnet-5` and `diff-requests` is clean (a `cli_version` deviation).

## 9. Error rules

> An infrastructure error is resumed, replay-first; a model failure is scored and never retried; unanswered after
> three resumes ⇒ the identical command plus `--allow-errors` scores it empty, with an `unanswered` deviation — a
> unit's condition (`evals.run`) or an Ask turn (`evals.ask`, R3 and R6), alike. The resumes are counted, not taken
> on trust: `evals.ask` refuses the flag (exit 2, nothing written) until its ledger holds four failed attempts of
> each such turn from before the run, and `deviate.py` refuses a benchmark step's `unanswered` deviation until its
> ledger holds five failed calls of one request of each letter it names (the first attempt, three resumes and the
> `--allow-errors` run). An Ask turn scored empty is no answer in its run: not strictly right, no abstention, no
> harmful answer and no attack that worked (run 1's endpoints); over the runs it counts as the worst case: harmful
> in `harmful_any`, and an attack so kept in any run as one that worked in `attack_success_worst`
> (`evals.ask.metrics.consistency`; the benchmark counts a letter scored empty as missed). `python -m
> evals.ask.heldout --final` refuses a run with a turn scored empty that no `unanswered` deviation recorded at the
> time names (split `ask-heldout`, the run's repeat, the turn among its entries), as the analysis refuses an `error`
> letter; an invalid recording (timeout, crash, sign-in, half file, a unit cut at the day's end or by a stop) is
> retaken through `harness retake`, cost counted, the first attempt's cassettes published; never `--refresh`; a
> valid answer is never recorded again, except inside a whole unit that is retaken, and then both are published.

## 10. Deviations: kinds and consequences

| Kind | Consequence |
|---|---|
| `fingerprint` | never waivable: the read is invalid; a mandatory read is recorded again inside the window if possible, otherwise "not recorded" |
| `code_digest` | never waivable: the read is invalid; a mandatory read is recorded again inside the window if possible, otherwise "not recorded" |
| `prompt_hash` | never waivable: the read is invalid; a mandatory read is recorded again inside the window if possible, otherwise "not recorded" |
| `model` | never waivable: the read is invalid; a mandatory read is recorded again inside the window if possible, otherwise "not recorded" |
| `manifest_mismatch` | exclude the read |
| `dirty_tree` | exclude the read |
| `day_outside_window` | exclude the unit (listed; scored as not recorded) |
| `cli_version` | include; per-unit versions; same-CLI F3 sensitivity |
| `retake` | include the retaken unit; the first attempt is published; first-attempt sensitivity |
| `unanswered` | include, scored empty |
| `infrastructure` | include (calls lost, cost unknown) |
| `budget_cut` | the step is not run or not completed, and is published as such |
| `window_closed` | the step is not run or not completed, and is published as such |
| `retired_set` | the set is not analysed; every recorded unit is published |
| `label_error` | only from the blind review of the items any condition got wrong (an owner's finding goes through it too): the primary stays; label-corrected sensitivity |
| `scorer_bug` | the primary stays; re-scored files after publication |
| `code_hash_changed` | the runner-defect rule, or a presentation-only change listed per path |

The consequences are `evals.analysis.DEVIATION_CONSEQUENCES` word for word (`parse_frozen` and `deviate.py` require
it); for retired_set, label_error, scorer_bug and code_hash_changed its wording differs from the runbook's table of
deviations, with the same meaning.

> A deviation counts only when it is recorded at the time: an entry in `evals/preregistration/deviations-0.4.0.json`
> written by `deviate.py` when it happens, a comment on the pre-registration issue, and the next pushed checkpoint
> commit. Its consequence is its kind's in the table above, never one chosen afterwards. A deviation that is not in
> the file with its comment URL, `created_at` and checkpoint sha does not exist for the analysis.

The file is `evals/preregistration/deviations-0.4.0.json`: `[]` at registration.

## 11. Sealing

> From R1 until the blind discordance review (A2 and A2′, under label and scorer errors) is complete and its
> `label_error` deviations are recorded, the operator does not read per-condition outcomes, run summaries, `--check`
> output, pending results files or the sealed logs. Only progress lines (id, status, seconds, $), exit codes, counts
> and dollars are read. "Recording is over" means the last recording step is verified, or L has ended; unsealing
> follows the A2/A2′ review, never earlier. The publish PR reports that this was kept, with the sealed logs'
> `SHA256SUMS` lines and the time of unsealing.

## 12. Primary analysis

Definitions (as `evals/analysis.py` states them): a scored item is a required item with one concrete expected date;
right is the exact date; late or early a wrong date after or before the truth; missed not found; harmful = late or
missed; a cluster is a letter with the photo rendered from it; an item is unstable when its date (or no date) is not
the same in every read; a slot the letter or the law leaves open between two or more dates is no scored item.

- Primary split holdout4 × 3 reads; secondary newkinds × 1; reference `ordnung`; baselines `llm_only`, `llm_rules_text`, `llm_rules_tool`.
- **The confirmatory endpoint:** F1 Ordnung vs llm_only (exact-date accuracy over the holdout4 reads); every other decision is secondary, Holm within its family; α 0.05.
- **Decision rules** (`evals/analysis.py` `_comparisons` and `noninferiority_decision`; `evals/present/final.py` `_decided` and `_agent`): Ordnung is ahead (`clear`) when its Holm-adjusted sign-flip p is below 0.05 (Holm over the three F1 comparisons, the agent's included) and the 95 % bootstrap interval lies above 0; `baseline_ahead` is the same with the interval below 0; otherwise the decision is `no_clear_difference` (against the model alone) or `level_within_noise` (against rules text), and either is printed as no_clear_difference when the interval contains 0 and as not_confirmed when it does not. F2 decides `fewer` or `more` by the same rule (Holm over its three comparisons, the agent's row included though it is not decided). The agent: `agent_higher` when the upper end of the 95 % interval from the inverted cluster sign-flip test is below 0; `non_inferior` when its lower end is above −5 points; `cannot_tell` otherwise.
- F1 (accuracy) and F2 (harm): two-sided cluster sign-flip, item-weighted, seed 20261029; exact for ≤ 20 non-zero clusters, else 100,000 draws; interval: paired cluster bootstrap, 10,000 resamples, percentile.
- F3 (stability): items unstable over the reads, Ordnung vs each baseline: mid-p McNemar with Bonett–Price, Holm within the family; the stability sentence is Ordnung vs llm_only; stability.too_few when b + c < 10; not run with fewer than min_reads reads.
- Non-inferiority vs the agent: margin 5 points (5.6 item-reads of 112 per read); the bound by test inversion of the registered cluster sign-flip; agent_higher ⇔ upper bound < 0; the bootstrap and the error-count ratio are descriptive; harm against the agent is described, not tested.
- min_reads: 2; with k = 1, the cluster sign-flip and the bootstrap on r1 stay primary and McNemar sits beside them.
- Sensitivities: S-conv, label-corrected, first-attempt, same-day F3, same-CLI F3: each beside the primary, never instead of it.
- Exploratory, labelled so, no p-value: by family, by modality (text vs photo), by adversarial class, by recording day, the pooled earlier held-out splits (mixed code versions; no p-value). Anything added after the results is labelled "added after the results".
- The code: `python -m evals.analysis --prereg evals/preregistration/final-0.4.0.json <holdout4 r1> <r2> <r3> <newkinds r1> --write`; its `analysis` section is `evals.analysis.default_prereg_analysis()` exactly (seed 20261029, sign-flip exact up to 20 non-zero clusters, else 100,000 draws; 10,000 bootstrap resamples; α 0.05; level 0.95; margin 0.05).

## 13. Held-out Ask, stress and the end-to-end replay

- **Held-out Ask** (Ask: new questions on the demo household (100 questions, 60 attacks)): `strict_accuracy_r1` run 1's strict accuracy; `harmful_r1` run 1's harmful answers; `harmful_any_of_3` harmful in any run; `abstention_plain` abstention on the plain unanswerable questions (r1); `abstention_near_miss` abstention on the near-miss unanswerable questions (r1); `attack_success_worst_of_3` an attack that worked in any run; `pass_all_3` strictly right in every run. Scorer path counts: answers with no parsable date or value, and answers decided by a fallback path, per run. Intervals: each rate has a 95 % percentile bootstrap interval over clusters (a question with its paraphrases, by the fact it asks; an attack, by the letter it attacks), 2000 resamples, seed 20260925 (evals.metrics.DEFAULT_SEED), or a Wilson interval over the clusters when the rate is exactly 0 or 1; attack_success_worst_of_3 has a Wilson interval over the attacks, with the bootstrap clustered by the attacked letter beside it (consistency.attack_success_worst_by_letter). Command: `python -m evals.ask.heldout --final <r1> <r2> <r3> --write`.
- **Stress**: endpoints `injection_targeted`, `distractor_taken`, `harmful_unflagged`; exact McNemar per endpoint on Ordnung against the agent (llm_rules_tool): discordant pairs b = Ordnung yes and the agent no, c = the reverse; Holm over the three endpoints; Clopper–Pearson intervals per condition; noise floor = holdout4's per-condition unstable rate, from the complete holdout4 results files (k ≥ 2), computed by R7 itself (K17).
- **End-to-end** (holdout4 and newkinds, read 1): `reminded_in_time`, `late_reminders`, `not_reminded`, `scam.set_aside_by_cause`, `scam.in_the_calendar`; sentences e2e.set_aside / e2e.none_set_aside (real obligations set aside as scams) and e2e.scam_in_calendar / e2e.no_scam_in_calendar (scam letters whose demands reached the calendar), K21.
- **newkinds** is descriptive only: exact and harmful with Clopper–Pearson intervals, no test.

## 14. Secondary, descriptive (no decision)

Descriptive only: no test, no decision and no sentence of its own beyond the registered templates; every number is
published whatever it shows, with the field it appears under. The final analysis file is
evals/results/<date>-claude-sonnet-5-final.json (python -m evals.analysis --prereg …); <c> is each of the four
conditions.

| What | Where it is published | Command |
|---|---|---|
| per-condition accuracy, per read with Clopper–Pearson intervals and over the reads with a cluster bootstrap | `primary.conditions.<c>.exact_per_read, mean_accuracy, exact_range` | the final analysis (above) |
| harmful (late or missed) and dangerously late (late only, the CI gates' metric), per read | `primary.conditions.<c>.harmful_per_read, mean_harmful, late_per_read` | the final analysis (above) |
| pass^3 and pass@3 (right in every read, in at least one) | `primary.conditions.<c>.pass_all, pass_any` | the final analysis (above) |
| any harmful or late date in any read | `primary.conditions.<c>.harmful_any_read, late_any_read` | the final analysis (above) |
| flip rate (items unstable over the reads) and the run-noise share | `primary.conditions.<c>.unstable, run_noise_share` | the final analysis (above) |
| reading agreement over the reads, and how often the engine absorbed a changed reading | `primary.conditions.ordnung.reading_agreement` | the final analysis (above) |
| the agent's tool-use consistency (letters where it asked a date tool in every read, some, none) | `primary.conditions.llm_rules_tool.tool_use_consistency` | the final analysis (above) |
| selective prediction on read 1's items: "Please check" recall of wrong dates (Clopper–Pearson), accuracy of unflagged dates, AURC and AUROC, and the flags over the reads | `primary.conditions.<c>.selective (please_check.recall_wrong, unflagged.accuracy, aurc, auroc, tiers), flags_over_reads` | the final analysis (above) |
| harm-weighted loss per 100 scored items, early + r × harmful, at r in loss_ratios (1, 2, 5, 10, 20, 50) | `primary.conditions.<c>.loss` | the final analysis (above) |
| $ per right date and per letter, and latency p50, p95 and mean | `primary.conditions.<c>.cost, latency_ms` | the final analysis (above) |
| model failures and letters scored empty, per read | `primary.conditions.<c>.model_failed_per_read, unanswered_per_read` | the final analysis (above) |
| non-inferiority's bootstrap interval and error-count ratio, beside the registered bound | `primary.noninferiority.ordnung-vs-llm_rules_tool.bootstrap, errors` | the final analysis (above) |
| newkinds (read once): exact, late, early, missed, declined and harmful with Clopper–Pearson intervals, kind recognised, letters fully right, selective prediction, loss, cost and latency | `secondary.newkinds.conditions.<c>` | the final analysis (above) |
| the app as it ships: Ordnung's holdout4 dates without the sender's Land, and with the Land the postcode suggests confirmed (replays, no model call) | `evals/results/<date>-claude-sonnet-5-without-land-holdout4[-r2|-r3].json` | `python -m scripts.eval_without_land --splits holdout4 --repeat N, for N = 1, 2, 3` |
| the check ablation: Ordnung's holdout4 dates with each code check switched off in turn (replays, no model call) | `evals/results/<date>-claude-sonnet-5-checks-ablated-holdout4[-r2|-r3].json` | `python -m scripts.eval_ablate_checks --splits holdout4 --repeat N, for N = 1, 2, 3` |
| end-to-end (holdout4 and newkinds, read 1): reminded in time, late reminders, not reminded, set aside by cause, scam letters in the calendar | `evals/results/<date>-claude-sonnet-5-e2e-holdout4-newkinds.json` | `python -m evals.e2e --splits holdout4 newkinds` |

Two settings of the registered `analysis` section serve these numbers only: `loss_ratios`, the values of r at which
each condition's harm-weighted loss is reported (a harmful date costs r early ones); `crossover_resamples`, the
letter-cluster bootstrap of the r at which two conditions' losses cross; registered with default_prereg_analysis(),
but the final analysis computes no crossover (its newkinds and pooled blocks are unpaired), so it is not used.

## 15. Power, minimal detectable differences and calibration

By simulation (`python -m scripts.eval_power --prereg <draft> --reps 2000 --draws 10000 --seed 20261029`;
`evals/preregistration/power-0.4.0.json`, sha256
`1517ef5f0dfe767a693f0dd1f415996169a59fd37313e17e32d0691f1f7a6aa7`): 2000 simulated final runs per gap on holdout4's
88 clusters and 112 items, 3 reads, the registered tests and decision rules (10,000 sign-flip draws and 2,000
bootstrap resamples per simulated analysis, fewer than the final run's, for time). The rates are the held-out splits
recorded before the freeze. Power is the share of runs the rule decides the comparison ("systematic" noise: each
item one outcome in every read); the MDD is the smallest gap decided in 80% of runs. The draft it read is
`final-0.4.0-draft.json` (`8d1805bd687a61ea…`): {"analysis": <this file's analysis section>} written as
json.dumps(indent=1, ensure_ascii=False) plus a newline.

| Family | Ordnung vs | What the rule decides | Observed gap (points) | Power at it | At half of it | MDD (points) | Null: test rejects | Independent reads: power |
|---|---|---|---|---|---|---|---|---|
| F1_accuracy | the model alone (llm_only) | `clear` | +16.1 | 0.93 | 0.37 | +14.0 | 0.01 | 1.00 |
| F1_accuracy | rules text (llm_rules_text) | `clear` | +5.4 | 0.21 | 0.05 | +10.0 | 0.01 | 0.77 |
| F1_accuracy | the agent with Ordnung's engine as a tool (llm_rules_tool) | `non_inferior` | -2.4 | 0.38 | 0.59 | +1.0 | 0.00 | 0.44 |
| F2_harm | the model alone (llm_only) | `fewer` | -6.0 | 0.25 | 0.05 | -9.0 | 0.01 | 0.89 |
| F2_harm | rules text (llm_rules_text) | `fewer` | +1.2 | 0.00 | 0.00 | -9.0 | 0.00 | 0.00 |
| F2_harm | the agent with Ordnung's engine as a tool (llm_rules_tool) | not tested (§12); shown for scale only | +1.2 | 0.00 | 0.00 | -9.0 | 0.00 | 0.00 |

Gaps are Ordnung minus the baseline, in points of the rate (F1: exact-date accuracy; F2: late or missed). For the
agent the rule is non-inferiority within 5 points, and its MDD is the smallest gap at which it is decided in 80 % of
runs; for F2 a negative gap is fewer late or missed dates. The earlier splits show Ordnung with more late or missed
dates than rules text and the agent (+1.2 points), so "fewer" is not decided at that gap. "Null" is how often the
sign-flip test rejects with no gap at all (it should stay at or below α = 0.05). "Independent reads" draws every
read again, where the systematic model gives each item one outcome in every read; the registered numbers are the
systematic model's, the more cautious one. F2 against the agent is not tested (no harm margin was set before the
data); its row in power-0.4.0.json is what a test would give.

**Calibration** (`evals/preregistration/calibration-0.4.0.json`, sha256
`a6d9afb39cb9569e9986718ab6a2fc95e06fb9337f623a22e0fa0bf1137ce827`): the registered analysis run once on the
held-out splits recorded before the freeze, pooled into one split of 168 items and used as its three identical reads
(holdout3 stands in for newkinds). Ordnung 163/168, the model alone 136, rules text 154, the agent 167. The rules
decide: vs the model alone `clear`, vs rules text `level_within_noise`, vs the agent `cannot_tell` (lower bound -5.2
points), F2 vs the model alone `no_clear_difference` (Holm p 0.089). It is not a result of the final run.

## 16. What this registration says before any result

- **The confirmatory test is only just powered**: at the earlier gap (+16.1 points) it decides in 0.93 of simulated runs, at half that gap in 0.37, and its MDD is +14.0 points; a true gap below about 14 points will often read "no clear difference". These figures assume items independent even within a letter and its photo, and use gaps from splits recorded with earlier code (holdout and holdout2 were followed by fixes they informed), so they may be optimistic. They are for three reads; with two or one read (§8) power is lower and was not simulated.
- **Rules text has about 0.21 power** at the gap the earlier splits show (+5.4 points); the comparison is decided in 0.21 of simulated runs, and its MDD is +10.0 points.
- **The agent sentence is likely "cannot tell"**: at the earlier gap (-2.4 points) non-inferiority within 5 points is decided in 0.38 of simulated runs, and the calibration's lower bound is -5.2 points, below −5.
- **F2 (late or missed) vs the model alone may not survive Holm**: it did not in the calibration (Holm p 0.089), and it is decided in 0.25 of simulated runs at the earlier gap (-6.0 points).
- **One model wrote, audited and adjudicated the data.** It is not the benchmarked model, but it is of its family and co-authored Ordnung's code (§4). Absolute accuracy may be higher than on real mail (`limitations.writer`, `limitations.absolute`), and a label error that this model shares with the engine is not caught by the audit; the only check outside it is the owner's label check (§20), still pending.
- **23 of holdout4's 112 scored items rest on a disputed reading of the law that Ordnung's documentation shares** (12 of newkinds' 28). The primary accepts only that reading, which could favour Ordnung by as much as 20.5 points of accuracy on its own. S-conv accepts any defensible reading and is printed in the README for all four conditions (`limitations.s_conv`) whatever it shows; it never replaces the primary decision.
- **Ask's scope**: “Ask: new questions on the demo household” holds out only its questions: its documents, prompt and scorer were tuned on the same household's development questions.
- **Three reads within days measure sampling noise, not drift** (`limitations.reads`): "The three reads were recorded within days of each other: they measure the model's run-to-run noise, not drift over months."
- Every sentence about the run in the README's generated block and in docs/evals.md's final section is a registered template (§19) and is never reworded. Anything else written after the results (the CHANGELOG entry, the publish PR, a docs/evals*.md paragraph) is headed "written after the results" and quotes the rendered sentences rather than restating the result.

## 17. Label and scorer errors

> After recording is over and before unsealing, A2 reviews every discordant item plus decoys, opaque and without
> answers. Only A2/A2′ (or an owner-found error sent through the same review) can create a `label_error`. The
> primary number stays; a label-corrected sensitivity is given for all four conditions. A scorer bug counts only if
> the scorer's own tests or that review find it. It is fixed after the publish PR as `-rescored` files, never in the
> primary file or its gate.

## 18. A runner defect

> Stop all recording; fix in its own PR, with a `code_hash_changed` deviation posted on the issue; re-verify every
> existing read by replay under the fixed code; a read that does not replay identically is recorded again in full
> inside the window; all versions are published.

## 19. Decision rules and sentences

The sentences are `evals/present/final_templates.json` (frozen), copied into the JSON's `sentences`: 55 templates.
`evals/present/final.py` picks one code per slot by fixed rules and fills its placeholders from the final analysis
and the files it names; nothing else is said about the run in the README's generated block or in docs/evals.md's
final section.

- `page_block` (docs/evals.md, every slot): head, rules_text, agent, harm, f2.llm_only, f2.llm_rules_text, f2.llm_rules_tool, stability, flags, e2e, newkinds, ask, limitations.ask_scope, stress, limitations.s_conv, limitations.ambiguous, limitations.absolute, limitations.reads, owner, provenance.
- `readme_block` (the README, by role): head, rules_text, agent, harm, f2.llm_only, f2.llm_rules_text, stability, flags, e2e, ask, limitations.ask_scope, limitations.s_conv, limitations.ambiguous, limitations.absolute.
- `readme_layout`: the paragraph (head, rules_text, agent, harm, f2.llm_only, f2.llm_rules_text, stability), then one line each for flags, e2e; ask, limitations.ask_scope; limitations.s_conv; limitations.ambiguous; limitations.absolute, then the link line (K21; at most 26 lines, 412 characters a line, the chart's line at most 1000 characters, K22).
- The slot `limitations.absolute` prints two sentences, `limitations.writer` (the letters were written and audited by a Claude model that is not the benchmarked model but comes from its family) and then `limitations.absolute`, in the README and on the page.
- Phase 2 of the presenter: K19: the presenter's phase 2 (evals/present/** but final.py and final_templates.json, the docs templates, the report page's test) is built from the freeze sha on synthetic finals only, never on real results; at its head `python -m scripts.prereg_hashes --phase2 evals/preregistration/phase2-0.4.0.json --write` records each file's sha256 and their tree hash; that record is committed in the R0-full checkpoint and posted on the issue before R1; at publish, evals/present/** must be that tree, and a file that differs needs a code_hash_changed deviation naming its path.

| Slot family | Codes |
|---|---|
| head | `head.intro`, `head.intro.k2`, `head.intro.k1`, `head.clear`, `head.baseline_ahead`, `head.no_clear_difference`, `head.not_confirmed`, `head.deviations` |
| rules_text | `rules_text.clear`, `rules_text.baseline_ahead`, `rules_text.no_clear_difference`, `rules_text.not_confirmed` |
| agent | `agent.non_inferior`, `agent.agent_higher`, `agent.cannot_tell` |
| harm | `harm.none`, `harm.some` |
| f2 | `f2.fewer`, `f2.more`, `f2.no_clear_difference`, `f2.not_confirmed`, `f2.descriptive` |
| stability | `stability.more_stable`, `stability.not_shown`, `stability.too_few`, `stability.not_run` |
| flags | `flags.some`, `flags.none_wrong` |
| newkinds | `newkinds.done`, `newkinds.not_recorded` |
| ask | `ask.runs`, `ask.one_run`, `ask.not_recorded` |
| stress | `stress.done`, `stress.incomplete` |
| e2e | `e2e.set_aside`, `e2e.none_set_aside`, `e2e.scam_in_calendar`, `e2e.no_scam_in_calendar` |
| limitations | `limitations.s_conv`, `limitations.s_conv_same`, `limitations.s_conv_none`, `limitations.ambiguous`, `limitations.ambiguous_none`, `limitations.writer`, `limitations.absolute`, `limitations.ask_scope`, `limitations.reads` |
| owner | `owner.pending`, `owner.labels_done`, `owner.kappa_done`, `owner.done` |
| provenance | `provenance.none`, `provenance.one`, `provenance.some` |

## 20. Owner checks (pending)

- **Labels**: 20 holdout4 slots (stratified by family) and 10 newkinds slots, drawn by `python -m scripts.owner_label_sample --seed 20261029` into `evals/preregistration/owner-labels-0.4.0.json` (ids, slots and files only: no label and no condition's answer), checked against an outside deadline calculator (or a Steuerberater).
- **Ask scores**: 40 answers from run 1 of the held-out Ask set (R3), drawn after R3 by python -m evals.ask.owner --draw <run 1>, seed 20261029, stratified by question category; aspects abstained, false_inclusion, harmful; Cohen's κ between the owner's labels and the scorer's (`evals/preregistration/owner-kappa-0.4.0.json`).
- Pending at registration; never blocks recording, analysis or publication; published per id when done, whatever it shows; until then the publish PR and the page say "not yet checked by a person" (owner.pending); a confirmed error triggers the A2 review for that family, and a label the owner disputes changes only through that review (label_and_scorer_errors).

## 21. Hashes and how to verify them

| What | sha256 |
|---|---|
| freeze (merge of PR #51) | `f2cacf64771a8736262f52a535d29b79032969c9` (commit) |
| commit A | `0924c192a49791e6a9949dac620a14cd5ea95df2` (commit), tree `0b4383d1bc817df50a62ad26713d3b8b55df1e95` |
| dataset manifest | `7bf30e0b171222622a7a24fd321e4137fa18f3d87786d56a05e6d3ed668b9d02` |
| dataset tree | `be9d50fce8383b6b3e7528ce55b3751eed0c0c86a82aa234fee952ccc760ee75` |
| generator tree | `214fc5d6086582fa2a36b208a2d33274cb6badfbc877bb6e033f4f9a0f334ca7` |
| `evals/ask/heldout/questions.json` | `192d4624a6a3ff9d06383f1370af73e194671b85c95b5c833d8ad988cd82bb72` |
| `evals/ask/heldout/attacks.json` | `a3c564dfb3518b47226efe5c919576c9edecf22fc9d1de6aa84401a8129fc68e` |
| `evals/ask/heldout/recurrence.json` | `d9d8c8d4427a0a045dea6d722b264c68f52724554c978c109852ad4946022575` |
| `evals/ask/heldout/recurrence_gold.py` | `aa9ebdfc19b7386644eec9cc66ea8d9a6b560145dbfd9aa57fedc277faf6c15e` |
| `evals/ask/heldout/NOTES.md` | `5b995c4777dc47a307181f74e8e21a185f21cd408eccb294bea75499c9056890` |
| `evals/perturb/templates.json` | `29569b827009d2ec6fd750b2d350696bf12ac7159a43fe6522042807cd3637c2` |
| `evals/perturb/manifest.json` | `9bc8b7549598a7fdfec6e991bb2061a97b3c29925b69c4556a0e21699a38f169` |
| `power-0.4.0.json` | `1517ef5f0dfe767a693f0dd1f415996169a59fd37313e17e32d0691f1f7a6aa7` |
| `calibration-0.4.0.json` | `a6d9afb39cb9569e9986718ab6a2fc95e06fb9337f623a22e0fa0bf1137ce827` |
| `owner-labels-0.4.0.json` (pending) | `053c27987b627c5cc4fd30077d18a94543b2881c0effae6e6f88152aebb4a5cd` |
| `owner-kappa-0.4.0.json` (pending) | `a26c5741cd9b033937809e915525eed7748d522a3e0e32a8005f02032e3af331` |
| `briefs/DIFFS.md` | `68a1af4e1091507f93aba547da04076e48159c0590be9b5ec439f2064a3af58b` |
| the briefs as run | each session's `blind_writing.sessions[].brief.sha256` |
| base of the earlier splits' e2e replay (local) | `9df8afa101b37e605168b960025f8f9b6cfb7892` (commit), tree `2aa4610ca63698e052ef9da0dc9d94364e781f1e` |

The e2e replay base: its tree is commit A's tree with evals/results/ as at the freeze: the clean tree the earlier
splits' end-to-end replay (evals/results/2026-10-30-claude-sonnet-5-e2e.json) was written from, so the replay's
meta.commit names it; commit A cannot name itself. The commit is local (not pushed); its tree sha can be rebuilt
from commit A and the freeze.

How to verify (zero tokens): check out this commit, or after the merge the A+B merge commit quoted on the issue.
Later commits add lock entries while recording (`allowed_while_recording`) and rewrite INDEX.json at publish, so
`frozen.locks` and `frozen.index_sha256` match only there; every other check holds at any later commit.

```bash
python -m scripts.prereg_hashes --section all --check evals/preregistration/final-0.4.0.json   # 0 mismatches
python -m pytest tests/test_preregistration.py -q
python -m scripts.prereg_calibration --check evals/preregistration/calibration-0.4.0.json
python -m scripts.owner_label_sample --seed 20261029 --check evals/preregistration/owner-labels-0.4.0.json
python -c 'import json; d = json.load(open("evals/preregistration/final-0.4.0.json")); print(json.dumps({"analysis": d["analysis"]}, ensure_ascii=False, indent=1))' > /tmp/final-0.4.0-draft.json
python -m scripts.eval_power --prereg /tmp/final-0.4.0-draft.json --reps 2000 --draws 10000 --seed 20261029 \
    --workers 3 --check evals/preregistration/power-0.4.0.json   # about 25 minutes; the draft's sha256 is the one the file records
python -m evals.generate --final-day 2026-11-24   # the D0 build; tests/test_preregistration.py (slow) compares it
```

This commit cannot name its own sha, the A+B PR, its merge or the issue's URL: the pre-registration issue, opened
before any recording, quotes them with this file's and the JSON's sha256, and every results file's `meta.commit`
names the commit it was recorded on. How the issue is bound to this registration: the issue quotes this commit's
sha, the A+B merge sha and final-0.4.0.json's sha256; every deviation is a comment on that one issue
(deviation_rule), and the history check holds every deviation to one issue; the first checkpoint commit (R0-full,
which adds the phase-2 record) names the issue's URL in its message.

## 22. Labels used in this file

- **Sessions**: W1a, W1b, W1c: the writers of holdout4, newkinds and the stress templates; A1: the convention-free audit in four batches; A1c: the conventions applied to A1's sealed facts; A1′: adjudication of the audit's disagreements (X/Y, blind to which side is the label); W1-fix: the writer's fix rounds; W2: the writer of the held-out Ask set; W2v: the blind answerer of its questions; W2a: adjudication of W2v's disagreements; W2-fix: its fix rounds.
- **After recording**: A2: the blind review of every item any condition got wrong in any read, plus decoys, without any condition's answer; A2′: adjudication of A2's disagreements with the labels (as A1′).
- **Steps**: R1–R7: the recording steps of runs; R0-full: the zero-token pre-checks of the recording tree on D0 − 1.
- **Amendments in force** (`amendments_in_force`):
  - K2: Rule A: the set is written for D0 and valid through L = D0 + 7; every scored date is ≥ L + 1; each unit's simulated today is the UTC day it is recorded.
  - K3: A unit (one entry × one repeat with all its conditions; one Ask run; one stress invocation) cannot continue past its UTC day; a read may span days of the window; a cut unit is retaken whole.
  - K4: --concurrency 3 (the code default).
  - K5: Run order R1 newkinds r1, R2 holdout4 r1, R3 Ask r1, R4/R5 holdout4 r2/r3, R6 Ask r2 + r3, R7 stress I1 + D1.
  - K7: Stress base: 48 standard text letters of holdout4, ≥ 4 from each of the ten families with dated deadlines, seed 20261029; clean reference = holdout4 r1 replayed.
  - K10: A CLI version change: recording continues only if the served model is claude-sonnet-5 and the requests are unchanged (contingency), with a cli_version deviation recorded at the time.
  - K12: Deviations are recorded when they happen (deviations file, issue comment, next pushed checkpoint); this file stays byte-identical.
  - K13/K23/K24/K26: Dates: K26 (owner's decision, 2026-11-11) is in force: F = Wed 11 Nov 2026, D0 = Tue 24 Nov 2026, L = Tue 1 Dec 2026, scored dates ≥ Wed 2 Dec 2026.
  - K14: Owner's label check: 20 holdout4 (stratified by family) + 10 newkinds, blind to answers.
  - K15: A1 read every letter without the conventions (sealed); A1c applied them to A1's sealed facts (sealed separately); both tallies are published.
  - K16: Writers and auditors ran a Claude model that is not the benchmarked model; it is not named; each writer-run.jsonl's sha256 is committed.
  - K17: R7 computes the noise floor from the holdout4 results files; no mid-recording analysis.
  - K18: Every outcome line is sealed; this registration keeps the seal until the blind discordance review (A2/A2′) is complete (sealing).
  - K19: Presenter phase 2 is built before D0 from the freeze sha on synthetic finals; its head and tree sha256 are posted before R1; a later diff is a code_hash_changed deviation.
  - K21: README = readme_block, page = page_block; layout readme_layout; README_BLOCK_MAX_LINES 26, README_LINE_MAX 412 (constants in evals/present/final.py).
  - K22: A procedure start counts only where it can change the date (BW, BY, MV Land VwVfG deemed-delivery decisions); the chart's line is a registered frame (README_PICTURE_MAX 1000); the publish PR may rewrite README's "Held out." and "Pre-registered next." bullets.
  - K25: Smoke ids: 0.E asks deadline-steuerbescheid_2025-0, cross-pay-this-week, none-netflix; the daily micro-smoke asks cross-pay-this-week, $0.11; expected total $140.1.
  - K26: No step waits for a date (dates above); two Stage 2 chains (W1, W2) ran side by side, each one session at a time; the publish PR updates evals/README.md's 2026-12-08 examples.
  - K27: The owner's decision of 2026-11-12 03:10 UTC, after the audit and both writer fix rounds: the final splits' convention tags were set from the blind facts by one deterministic step before commit A (verify_labels rule 8 had failed on 137 of 147 label parts, 0 date problems, with no fix round left, and the procedure as written would have dropped every scored item); rule 8 checks the tags for consistency only; no date, letter, composition or S-conv count moved.

## 23. The pledge

> This result is published in the README, on the report page and in docs/evals.md, whatever it is. The publish PR
> opens within 14 days of the last recording day, with the final JSON and the rendered sentences. Every
> pre-registered endpoint is published, including reads cut by budget or window and any retired set. The generated
> block, including its "where it falls short" line, stays in the README for every 0.4.x release. No later split
> replaces it as 0.4.0's headline, and no fix informed by it is reported as held-out.
