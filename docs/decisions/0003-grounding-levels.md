# ADR 0003 — Three honest grounding levels instead of "verified"

**Status:** accepted · **Date:** 2026-09-25

## Context
"Verified" is easy to over-claim. A fuzzy quote match says nothing about whether the extracted value
is right (`15.09.2026` vs `16.09.2026` still scores ~98), and for photos the only text available is
the model's own transcription, so checking a quote against it is circular.

## Decision
Every fact carries `Evidence` with a grounding level:
- **verified** — the quote was located in the PDF text layer (fuzzy ≥ 90) *and* every digit token
  of the quote appears verbatim on that page; boxes are computed from word coordinates → yellow
  highlight on the page image. UI: "Found in the letter · p. 2".
- **model_read** — located only in the AI transcription of a photo/scan. UI: "Read by AI from the
  photo".
- **unverified** — not found. UI: "Couldn't find this — please check".
- **user** — the person confirmed it.

Additionally `spec_consistency` parses numbers, number words, units and dates from the quote and
checks them against the `DateSpec` and amounts. Any dated item that is unverified or inconsistent
puts the letter into **Please check**.

## Consequences
The UI never says "verified"; the eval reports a *false-grounded rate*; photos are presented
honestly without depending on OCR.
