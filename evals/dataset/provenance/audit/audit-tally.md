# Blind audit tally (runbook-final §2.4 step 4), published before any adjudication

Counts only: no date, no letter text, no label, no entry id. Written by the W1-chain orchestrator from
`audit_compare.py`'s output, before A1′ was built or run.

## Inputs

- Compared at: 2026-11-11T21:00:11Z (after the A1c seal line at 2026-11-11T20:57:32Z)
- Seal: $F/audit-seal.txt, 5 lines (derived-b1..b4 sealed 2026-11-11T20:39:58Z; derived-conv appended 20:57:32Z), sha256 bc2865cc7fde6ad7fb178bb0220419876df990dd5cf24c948405fdf63b2f603c
- Map: $F/audit-map.json sha256 151e14cc8da9491471b2d66eed4d586bf661ee7800a421ccbb9898f52cffec59 (= audit-map.sha256); 158 letters, batches b1 40, b2 40, b3 39, b4 39
- Labels: $F/data-wt evals/dataset/manifest.json at wip e92fe560 (blob 309f573bf613b984f395280124e0f5bfa3defc61; dataset unchanged since e51d5d07)
- Tool: $F/tools/audit_compare.py sha256 4c68eaf53f5b17040971f50725aebcc1e34e125ac9b9040ce7f6f0287fdd1ecb (self-test == 0 failed); rc 0
- Readings: A1-1..4 (221 slots: dated 152, ambiguous 27, undatable 42) and A1c (221 slots: dated 183, ambiguous 14, undatable 24; changed 32)
- `audit-compare.json` sha256 819daa16c4c904eb26a8a43d6db1185c3b06e8cdfc532304464aa46aefc4f388; its seal_sha256 bc2865cc7fde6ad7fb178bb0220419876df990dd5cf24c948405fdf63b2f603c, map_sha256 151e14cc8da9491471b2d66eed4d586bf661ee7800a421ccbb9898f52cffec59

## (a) A1 (convention-free, sealed) vs the labels

| split/slot | agree | agree_candidate | disagree | not_derivable | total |
|---|---|---|---|---|---|
| holdout4/cancel_by | 3 | 1 | 0 | 0 | 4 |
| holdout4/i0 | 71 | 7 | 1 | 33 | 112 |
| holdout4/i1 | 4 | 0 | 0 | 0 | 4 |
| holdout4/o0 | 11 | 0 | 0 | 7 | 18 |
| holdout4/term_end | 4 | 0 | 0 | 0 | 4 |
| newkinds/i0 | 19 | 5 | 0 | 4 | 28 |
| newkinds/o0 | 2 | 1 | 0 | 5 | 8 |
| **holdout4 (all slots)** | 93 | 8 | 1 | 40 | 142 |
| **newkinds (all slots)** | 21 | 6 | 0 | 9 | 36 |
| **both splits** | 114 | 14 | 1 | 49 | 178 |

## (b) A1c (A1 with the conventions applied, sealed) vs the labels

| split/slot | agree | agree_candidate | disagree | not_derivable | total |
|---|---|---|---|---|---|
| holdout4/cancel_by | 4 | 0 | 0 | 0 | 4 |
| holdout4/i0 | 97 | 0 | 0 | 15 | 112 |
| holdout4/i1 | 4 | 0 | 0 | 0 | 4 |
| holdout4/o0 | 11 | 0 | 0 | 7 | 18 |
| holdout4/term_end | 4 | 0 | 0 | 0 | 4 |
| newkinds/i0 | 23 | 1 | 0 | 4 | 28 |
| newkinds/o0 | 3 | 0 | 0 | 5 | 8 |
| **holdout4 (all slots)** | 120 | 0 | 0 | 22 | 142 |
| **newkinds (all slots)** | 26 | 1 | 0 | 9 | 36 |
| **both splits** | 146 | 1 | 0 | 31 | 178 |

Categories (audit_compare.py): agree = the same date, the same candidate set, or both undated; agree_candidate =
candidate sets that overlap but differ; disagree = no overlap; not_derivable = the label has a date and the reading
has none (undatable, or no matched slot).

## (a)'s non-agreements, split by (b)

| split | convention (A1c agrees) | reading or arithmetic (A1c still differs) | total |
|---|---|---|---|
| holdout4 | 27 | 22 | 49 |
| newkinds | 5 | 10 | 15 |
| **both splits** | 32 | 32 | 64 |

## Procedure start (L2), (a) A1 vs the labels

| split/slot | same | label_only | audit_only | differs | no_facts | not_counted | total |
|---|---|---|---|---|---|---|---|
| holdout4/cancel_by | 0 | 0 | 0 | 0 | 0 | 4 | 4 |
| holdout4/i0 | 4 | 0 | 0 | 0 | 0 | 108 | 112 |
| holdout4/i1 | 0 | 0 | 0 | 0 | 0 | 4 | 4 |
| holdout4/o0 | 0 | 0 | 0 | 0 | 0 | 18 | 18 |
| holdout4/term_end | 0 | 0 | 0 | 0 | 0 | 4 | 4 |
| newkinds/i0 | 0 | 0 | 0 | 0 | 0 | 28 | 28 |
| newkinds/o0 | 0 | 0 | 0 | 0 | 0 | 8 | 8 |
| **holdout4 (all slots)** | 4 | 0 | 0 | 0 | 0 | 138 | 142 |
| **newkinds (all slots)** | 0 | 0 | 0 | 0 | 0 | 36 | 36 |
| **both splits** | 4 | 0 | 0 | 0 | 0 | 174 | 178 |

## Procedure start (L2), (b) A1c vs the labels

| split/slot | same | label_only | audit_only | differs | no_facts | not_counted | total |
|---|---|---|---|---|---|---|---|
| holdout4/cancel_by | 0 | 0 | 0 | 0 | 0 | 4 | 4 |
| holdout4/i0 | 4 | 0 | 0 | 0 | 0 | 108 | 112 |
| holdout4/i1 | 0 | 0 | 0 | 0 | 0 | 4 | 4 |
| holdout4/o0 | 0 | 0 | 0 | 0 | 0 | 18 | 18 |
| holdout4/term_end | 0 | 0 | 0 | 0 | 0 | 4 | 4 |
| newkinds/i0 | 0 | 0 | 0 | 0 | 0 | 28 | 28 |
| newkinds/o0 | 0 | 0 | 0 | 0 | 0 | 8 | 8 |
| **holdout4 (all slots)** | 4 | 0 | 0 | 0 | 0 | 138 | 142 |
| **newkinds (all slots)** | 0 | 0 | 0 | 0 | 0 | 36 | 36 |
| **both splits** | 4 | 0 | 0 | 0 | 0 | 174 | 178 |

same = absent on both sides, or the same day; not_counted = a slot whose date no start can change (K22: anything but
a Land VwVfG deemed-delivery item of a BW, BY or MV authority), not compared; no_facts = a reading without facts.

## Other counts

- Audit slots with no label slot (`extra`, counted per letter only): holdout4 52, newkinds 28.
- Slots for A1′ (every label slot where A1c is not `agree`, plus start-only cases): 32; by split holdout4 22, newkinds 10; by (b) category agree_candidate 1, not_derivable 31; read from PDF 26, photo (JPEG) 6; for the procedure start alone 0.
- Disagreement lists in audit-compare.json: (a) 64, (b) 32.

## The sentence's numbers (§2.4 step 6), before adjudication

W1's `law.py` and the sealed convention-free audit agree on 114 of 178 slots (14 more
overlap as candidate sets), on 146 of 178 with the conventions applied (1 more overlap).
After adjudication the labels stand on … (A1′ has not run).

## After adjudication (§2.4 steps 5–6; appended 2026-11-11 by the W1-chain orchestrator; the tally above is unchanged)

Counts only.
- A1′ (adjudication of the 32 slots above; key sha256 1550dff1…): the label's side upheld on 30, the second reading's
  side on 2, both wrong 0, ambiguous 0. By split: holdout4 22 ruled (label upheld 20, second reading 2), newkinds 10
  ruled (label upheld 10). 0 procedure-start cases.
- Consequences (fixed in EVP-12): the 30 keep their labels (facts from A1′); the 2 (holdout4, both an offered slot
  `o0` of a PDF letter with no photo) went to W1-fix and are now undatable, as ruled; no letter or photo bytes changed,
  so no A1-re.
- The comparison run again after W1-fix (audit-compare-2.json 4de97995…), over the same 178 label slots:
  (a) A1 vs the labels: agree 116, agree_candidate 14, disagree 1, not_derivable 47;
  (b) A1c vs the labels: agree 148, agree_candidate 1, disagree 0, not_derivable 29;
  (a)'s non-agreements: convention 32, reading or arithmetic 30; procedure start (a) and (b): same 4, not_counted 174.
  The 30 slots still at odds under (b) are exactly the 30 the adjudication upheld for the label.
- facts.json (scripts.build_final_facts as §2.4 step 6 gives it; rc 0, --check rc 0): holdout4 facts A1 98, A1p 18;
  newkinds A1 23, A1p 8; rulings applied 26 (the 6 photo cases merged with their letters' rulings).
- `evals.verify_labels` with these facts: 137 problems, all of one kind (rule 8: the conventions a slot's facts apply
  are not the label's convention tags; dates themselves raise no problem). OPEN: see provenance.md, "verify_labels
  rule 8"; the facts files are kept in scratch until this is resolved.
