# The briefs as run, against their templates

Each blind session's brief is its template in `brief-templates/` with the placeholders filled: `{D0}` = 2026-11-24, `{L}` = 2026-12-01 and, for the four A1 batches, `{N}` (the batch's letters) and `{BATCH}`. This file lists every session, the brief it ran with (its sha256 is the `prompt_sha256` in that session's `writer-run.meta` under `evals/dataset/provenance/<session>/`), its template and the lines in which the brief differs from the filled template. Fix rounds that ran with the same brief name it again.

Checked for this commit: no brief holds a letter's text, a label, a label date, a question's text or a model identifier; the only dates in them are D0 and L.

| session | role | brief as run | sha256 | template | lines added / removed |
|---|---|---|---|---|---|
| w1a | W1a: wrote holdout4 | `briefs/w1a.md` | `139f9d79f706cf3e…` | `brief-templates/w1a.md` | 0 / 0 |
| w1b | W1b: wrote newkinds | `briefs/w1b.md` | `52d4d4e66eef2c44…` | `brief-templates/w1b.md` | 0 / 0 |
| w1c | W1c: wrote the stress templates | `briefs/w1c.md` | `25377a3087a9c923…` | `brief-templates/w1c.md` | 0 / 0 |
| w1c-fix1 | W1c's fix round 1 | `briefs/w1c-fix1.md` | `3018580da260b00d…` | `brief-templates/w1c.md` | 11 / 0 |
| a1-1 | A1 batch b1: convention-free audit | `briefs/a1-1.md` | `cb783a6d7657a567…` | `brief-templates/a1.md` | 0 / 0 |
| a1-2 | A1 batch b2: convention-free audit | `briefs/a1-2.md` | `85e7cbd2641ecd17…` | `brief-templates/a1.md` | 0 / 0 |
| a1-3 | A1 batch b3: convention-free audit | `briefs/a1-3.md` | `fddb00bd8c4cb957…` | `brief-templates/a1.md` | 0 / 0 |
| a1-4 | A1 batch b4: convention-free audit | `briefs/a1-4.md` | `b93ba6926fe14e4d…` | `brief-templates/a1.md` | 0 / 0 |
| a1c | A1c: the conventions applied to A1's sealed facts | `briefs/a1c.md` | `893d65628a5bead2…` | `brief-templates/a1c.md` | 0 / 0 |
| a1p | A1′: adjudication of the audit's disagreements | `briefs/a1p.md` | `9b08c3065e8e1328…` | `brief-templates/a1p.md` | 0 / 0 |
| w1fix | W1-fix round 1 | `briefs/w1fix.md` | `0c3d1ca8751193cf…` | `brief-templates/w1fix.md` | 0 / 0 |
| w1fix2 | W1-fix round 2, the writer's last | `briefs/w1fix.md` | `0c3d1ca8751193cf…` | `brief-templates/w1fix.md` | 0 / 0 |
| w2 | W2: wrote the held-out Ask set | `briefs/w2.md` | `a97c1937f57074c6…` | `brief-templates/w2.md` | 0 / 0 |
| w2-fix | W2-fix round 1 | `briefs/w2-fix.md` | `4a13f2941e5f9247…` | `brief-templates/w2fix.md` | 0 / 0 |
| w2-fix2 | W2-fix round 2, the writer's last | `briefs/w2-fix2.md` | `4a13f2941e5f9247…` | `brief-templates/w2fix.md` | 0 / 0 |
| w2v | W2v: blind gold check | `briefs/w2v.md` | `7bf869c2b02bffbe…` | `brief-templates/w2v.md` | 0 / 0 |
| w2a | W2a: adjudication of W2v's disagreements | `briefs/w2a.md` | `9f5eb8e9a3e6c1ef…` | `brief-templates/w2a.md` | 0 / 0 |

Every brief is its filled template line for line, except `w1c-fix1.md`, which adds a section for the fix round (the template has none: W1c's fix round was not planned when the templates were written). The added lines, as run:

### w1c-fix1

```diff
--- brief-templates/w1c.md (placeholders filled)
+++ briefs/w1c-fix1.md
@@ -63,0 +64,11 @@
+
+## Fix round
+
+This is a fix round of the same task. Your folder also holds your earlier `evals/perturb/templates.json`, and
+`/work/fix-list.md` names the sentence that failed a check outside your folder, and why.
+
+- Rewrite only the sentence that the fix list names, in new words of your own: same group, key and language, the same
+  slots and the same purpose. Keep every other sentence, and the rest of the file, exactly as it is.
+- Write `writer-notes-templates.md` for the rewritten sentence only: what it does and which slots it uses.
+- Then run the check under "Checks, and when to stop", read the rewritten sentence once more against the rules above,
+  print the number of sentences per key and language and the digest the check prints, and stop.
```

Full sha256s of the briefs and the templates are in `final-0.4.0.json`, `blind_writing.sessions[].brief`.
