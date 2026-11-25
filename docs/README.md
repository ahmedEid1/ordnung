# Ordnung's documents

Every document, by who it is for and the question it answers. The [README](../README.md) says what Ordnung is, how
to try it and how it is measured; start there.

**In one minute**

- **To install, run and update Ordnung,** and to know its limits: the [guide](guide.md).
- **To know what leaves your computer:** [privacy.md](privacy.md).
- **To check how a date is worked out, rule by rule:** [deadline-rules.md](deadline-rules.md).
- **To see how often its dates are right:** the [evaluation report](https://ahmedeid1.github.io/ordnung/evals/)
  ([evals.md](evals.md) on GitHub).
- **To change the code:** [CONTRIBUTING.md](../CONTRIBUTING.md), then [architecture.md](architecture.md).
- **To report a vulnerability:** [SECURITY.md](../SECURITY.md), privately.

## Using Ordnung

- [guide.md](guide.md): how do I install, run and update it, what does it do, which environment variables does it
  read, and what are all its limitations?
- [privacy.md](privacy.md): what is stored where, what does each feature send, and what do I do if my computer is lost
  or stolen?

## Checking the AI

- [The evaluation report](https://ahmedeid1.github.io/ordnung/evals/): how often are its deadlines right? The report
  as a page, with its charts.
- [evals.md](evals.md): the same report: the letters, the baselines, the statistics, the ablations, the failures and
  the cost, and [how to reproduce it](evals.md#15-reproduce) with no API key.
- [evals-ask.md](evals-ask.md): the Ask benchmark: are Ask's answers right, and do they cite what they rest on?
- [evals-history.md](evals-history.md): what did every earlier run measure? Each in the order it happened.
- [The pre-registration of the final run](../evals/preregistration/final-0.4.0.md): what does 0.4.0's final run
  measure, and how is it analysed? Registered with its sha256 on
  [issue #54](https://github.com/ahmedEid1/ordnung/issues/54) before any final recording.
- [evals/README.md](../evals/README.md): the benchmark code: what is measured, where each part lives, and how do I run
  it?
- [evals/results/INDEX.json](../evals/results/INDEX.json): which results files are there? Each with its hash, and how
  `make eval-reproduce` checks it.

## How it is built

- [architecture.md](architecture.md): what are the components, the trust boundaries, the data model and the testing
  strategy?
- [decisions/README.md](decisions/README.md): why is it built this way? The design decisions, each with its status.
- [SPEC.md](SPEC.md): what does each module do? For someone changing it.
- [deadline-rules.md](deadline-rules.md): which rule does the engine apply, and what is its source? Every rule.

## Working on Ordnung

- [CONTRIBUTING.md](../CONTRIBUTING.md): how do I set up a checkout, which checks do I run, and how are changes
  written?
- [releasing.md](releasing.md): how is a release made, and what is the one-time setup for PyPI?
- [SECURITY.md](../SECURITY.md): how do I report a vulnerability privately?
- [CHANGELOG.md](../CHANGELOG.md): what changed in each version?
