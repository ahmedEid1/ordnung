# Fix list (round 1)

The check that failed: a check outside your folder compares the wording of every sentence in
`evals/perturb/templates.json` with texts that are not in your folder, in runs of five consecutive words (the slots
split a sentence into parts, and a part of three to five words counts as one run). No sentence may share such a run
with those texts.

- `injection`, key `shift`, language `en`, the third sentence (index 2): it shares runs of five words with those texts
  (3 matches).

Every other sentence passes this check, and the file passes every other check.
