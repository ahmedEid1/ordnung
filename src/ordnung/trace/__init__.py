"""How a letter was read: a trace of every step of each reading.

* :mod:`ordnung.trace.spans` — the tracer (explicit, no global state, no-op when off) and its policy
  for keys, ids and time.
* :mod:`ordnung.trace.facts` — what each kind of step records, and that it never holds letter text.
* :mod:`ordnung.trace.runs` — one trace per reading, how many are kept, the demo's recorded timing.
* :mod:`ordnung.trace.view` — the trace as the web app and ``ordnung trace`` show it.
* :mod:`ordnung.trace.compare` — what a later reading decided differently.
* :mod:`ordnung.trace.otel` — OpenTelemetry (OTLP JSON) with the GenAI semantic conventions.

Submodules are imported where they are used: the pipeline and the model layer import only
``spans`` and ``facts``.
"""
