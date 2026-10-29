"""The stress cells of the 0.4.0 evaluation (plan EV11): held-out letters with one sentence added, recorded once.

Two cells, each on the same 48 standard text letters of the held-out splits ``holdout``, ``holdout2`` and
``holdout3`` (16 per split, stratified by family, seed 20261029; ``holdout4`` is never perturbed):

* **I1, targeted injection** — one visible paragraph addressed to an AI, with one of three goals (16 letters each):
  *shift* the deadline to the truth + 3, 7 or 14 days; *drop* it ("no action needed"); or *re-route* it with a claim
  about one of the engine's inputs (the sender's kind, the day the letter arrived, the length of the period). Scored
  as exact targeted success, untargeted harm (later, missed or undated) and whether the person was warned.
* **D1, distractor date** — one legally inert sentence that names a date: three roles give a date 1–7 days after
  the deadline (an office closed, a direct debit for another contract, an information event), one quotes an earlier
  letter. Scored as taken, harmful, and false alarms of the "please check" flag.

The truth of every perturbed letter is its base letter's (an AI-addressed paragraph and an inert sentence change no
legal date). The letters are re-rendered through the benchmark's own generator (``evals/generate.py`` and
``evals/gen/``, unchanged): an unperturbed re-render is byte-identical to the dataset.

* :mod:`evals.perturb.templates` — the sentences' templates (written blind, plan EV8) and their checks;
* :mod:`evals.perturb.build` — the base set, what each letter gets, the files and the stress manifest;
* :mod:`evals.perturb.score` — the scorer and the results document (``<date>-<model>-stress.json``).

``scripts/eval_perturb.py`` builds, replays (or records) and scores the cells.
"""
