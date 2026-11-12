# Held-out Ask: the blind gold check (M3), the agreement tally as it came out

Runbook-final §2.4 step 7. Published here before any adjudication or fix. Counts and ids only.

- Set: data-wt-ask 6cabd24e57e5c1ed806b07131cffae6fc78227c8 (eval-data-ask-0.4.0, local), questions.json
  714057b5976b42c94199935fb2a096e9c942aab850620162da104195703117b9: 103 questions (after the §2.3 drop of 1).
- Blind questions: `heldout_check --strip-gold` -> questions-blind.json
  5f3da83523a39e5fe4a2ae83bad2f02bc55ef392572ac966c683be825c68f81c (103 questions, 5 repeating to-dos, 0 gold keys).
- Blind answerer: session W2v (13), profile w2v, ended 2026-11-11T17:30:45Z; answers.json
  fae13bc5f5c6f2456243758bcc5957887312c815e8edc82bdab2db6148c28dda (103 replies, 16 of them unanswerable), sealed in
  $F/ask-seal.txt before the comparison.
- Comparison: `python -m evals.ask.heldout_check --blind-compare answers.json --today 2026-11-24` (D0), rc 0;
  blind-compare.json 0e9955a5f882545601f3997172976ae3d9380285d40d222a88851c2dd64077a6. The same with --today
  2026-12-01 (L) gives the same counts and ids.

| Category | Agree | Disagree | No reply |
|---|---|---|---|
| contract | 15 | 0 | 0 |
| cross_letter | 9 | 0 | 0 |
| deadline | 12 | 3 | 0 |
| household | 16 | 0 | 0 |
| payment | 21 | 0 | 0 |
| recurrence | 11 | 0 | 0 |
| unanswerable | 16 | 0 | 0 |
| **Total** | **100** | **3** | **0** |

**W2's gold and the blind answerer agree on 100 of 103 questions.** The 3 disagreements are the three phrasings of
one core question: ho-core-07-de, ho-core-07-en, ho-core-07-en-paraphrase. No reply is missing and none is unknown.

Next (fixed before this tally): the 3 disagreements go to W2a as X/Y (W2's gold vs W2v's reply). Gold right -> keep;
W2v right -> W2-fix; ambiguous -> the question is dropped (counted). The rulings are added below, after this
section, without changing it.

## After the tally: W2a's rulings and their consequences (added 2026-11-11, the section above unchanged)

- W2a (session 14, profile adjudicate-ask, ended 2026-11-11T17:41:51Z): 3 cases, X/Y drawn per case (seed 20261029),
  both sides in the reply shape with the same keys; key $F/adjudication-ask-key.json, sha256
  6e93f1b375cfbdfb4ea094b2ea83b2642fa33c0f7a38456362e1b8bde70cfe7b; rulings adjudication-ask.json sha256
  0f1dfa2a93b5b8d2b4745230cf5d2c15358ac143567688d6b5a00c587ce6ed8d.
- Verdicts: X_right 2, Y_right 1, both_wrong 0, ambiguous 0. Mapped through the key: **W2v's reply upheld on 3 of 3**
  (ho-core-07-de, ho-core-07-en, ho-core-07-en-paraphrase); W2's gold upheld on 0.
- Consequence (§2.4 step 7, w2a.md): "W2v right" sends the question back to its writer. The W2 writer has already
  used both of its fix rounds (§2.3: "at most two fix rounds per writer; a third failure drops the item, and B states
  the final counts"), so no W2-fix round is open and the 3 questions are **dropped** (counted), not corrected.
- Final held-out Ask set after this: **100 questions** (core 57, household 16, recurrence 11, unanswerable 16), 5
  repeating to-dos, 60 attacks. Dropped in all: 4 questions and 1 to-do (ho-rec-q05 and ho-rec-salary after the
  third §2.3 failure; ho-core-07-de/-en/-en-paraphrase after the blind check).
