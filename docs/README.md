# Ordnung's documents

Every document, by who it is for. The [README](../README.md) says what Ordnung is, how to try it and how it is
measured; start there.

## Using Ordnung

- [guide.md](guide.md): a tour of the app, how to install, run and update it, the environment variables it reads,
  and every limitation
- [privacy.md](privacy.md): what is stored where, what each feature sends, and what to do if your computer is lost
  or stolen

## Checking the AI

- [The evaluation report](https://ahmedeid1.github.io/ordnung/evals/), as a page with its charts
- [evals.md](evals.md): the same report: the letters, the baselines, the statistics, the ablations, the failures
  and the cost; [how to reproduce it](evals.md#15-reproduce) with no API key
- [evals-ask.md](evals-ask.md): the Ask benchmark: are Ask's answers right, and do they cite what they rest on
- [evals-history.md](evals-history.md): every earlier run, in the order it happened
- [evals/README.md](../evals/README.md): the benchmark code: what is measured, where each part lives, how to run it
- [evals/results/INDEX.json](../evals/results/INDEX.json): every results file with its hash, and how
  `make eval-reproduce` checks it

## How it is built

- [architecture.md](architecture.md): components, trust boundaries, data model, testing strategy
- [decisions/README.md](decisions/README.md): the design decisions, each with its status
- [SPEC.md](SPEC.md): what each module does, for someone changing it
- [deadline-rules.md](deadline-rules.md): every rule the engine applies, with its source

## Working on Ordnung

- [CONTRIBUTING.md](../CONTRIBUTING.md): setting up a checkout, which checks to run, and how changes are written
- [releasing.md](releasing.md): how a release is made, and the one-time setup for PyPI
- [SECURITY.md](../SECURITY.md): reporting a vulnerability privately
- [CHANGELOG.md](../CHANGELOG.md): what changed in each version
