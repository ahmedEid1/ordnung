"""A reading as OpenTelemetry JSON (OTLP/JSON), for any OpenTelemetry viewer (``ordnung trace --otel``).

Written policy:

* **Format.** One ``resourceSpans`` entry (``service.name`` ``ordnung``) with one scope
  (``ordnung.trace``) holding every step of the reading, encoded as the OTLP/JSON protocol encodes
  it: trace and span ids as hex (16 and 8 bytes, derived from Ordnung's ids by SHA-256, so the same
  reading always exports the same ids), times as nanoseconds since the Unix epoch in decimal strings,
  64-bit integers as decimal strings, every attribute as a typed ``AnyValue``.
* **Model calls** follow the OpenTelemetry semantic conventions for generative AI: span kind
  ``CLIENT``, name ``"{gen_ai.operation.name} {gen_ai.request.model}"`` (``chat sonnet``) and the
  attributes ``gen_ai.operation.name``, ``gen_ai.provider.name`` (and the older ``gen_ai.system``),
  ``gen_ai.request.model``, ``gen_ai.response.model``, ``gen_ai.usage.input_tokens``,
  ``gen_ai.usage.output_tokens`` and ``error.type`` for a failed call. What the conventions do not
  name is under ``ordnung.*`` (purpose, prompt and version, cost, cache use, outcome, repair link).
* **No text.** Like the stored spans, the export holds no letter text — and no labels either: a step
  names the record it points to by id (``ordnung.ref.type``/``ordnung.ref.id``), never by its title,
  so the file can be loaded into a viewer or shared to debug a reading without sharing the letter.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from ordnung import __version__
from ordnung.models import DocumentTrace, TraceSpan

SCOPE = "ordnung.trace"
SCOPE_VERSION = "1"
SPAN_KIND_INTERNAL = 1
SPAN_KIND_CLIENT = 3
STATUS_UNSET = 0
STATUS_ERROR = 2
GEN_AI_PROVIDER = "anthropic"
GEN_AI_OPERATION = "chat"
#: A model step's facts that the ``gen_ai.*`` and ``ordnung.llm.*`` attributes carry instead.
_GEN_AI_KEYS = frozenset(
    {
        "call_id",
        "purpose",
        "prompt",
        "prompt_version",
        "request_model",
        "served_model",
        "cache_hit",
        "outcome",
        "repair_of",
    }
)


def hex_id(value: str, size: int) -> str:
    """``size`` bytes of SHA-256(``value``) as lower-case hex (an OTLP trace or span id)."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[: size * 2]


def any_value(value: Any) -> dict[str, Any] | None:
    """A JSON value as an OTLP ``AnyValue`` (``None`` for a null, which OTLP leaves out)."""
    if value is None:
        return None
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, str):
        return {"stringValue": value}
    if isinstance(value, list | tuple):
        return {"arrayValue": {"values": [v for v in map(any_value, value) if v is not None]}}
    if isinstance(value, dict):
        return {"kvlistValue": {"values": attributes(value)}}
    return {"stringValue": str(value)}


def attributes(values: dict[str, Any]) -> list[dict[str, Any]]:
    """``{key: value}`` as OTLP key-values, nulls left out, keys sorted."""
    pairs = ((key, any_value(values[key])) for key in sorted(values))
    return [{"key": key, "value": value} for key, value in pairs if value is not None]


def _nanos(moment: str) -> int:
    parsed = datetime.fromisoformat(moment.replace("Z", "+00:00"))
    return int(parsed.timestamp()) * 1_000_000_000 + parsed.microsecond * 1000


def _gen_ai(span: TraceSpan) -> dict[str, Any]:
    call, attrs = span.call, span.attributes
    request_model = attrs.get("request_model") or (call.model if call else None)
    values: dict[str, Any] = {
        "gen_ai.operation.name": GEN_AI_OPERATION,
        "gen_ai.provider.name": GEN_AI_PROVIDER,
        "gen_ai.system": GEN_AI_PROVIDER,
        "gen_ai.request.model": request_model,
        "gen_ai.response.model": (call.served_model if call else None) or attrs.get("served_model"),
        "ordnung.llm.purpose": attrs.get("purpose"),
        "ordnung.llm.prompt.name": attrs.get("prompt"),
        "ordnung.llm.prompt.version": attrs.get("prompt_version"),
        "ordnung.llm.cache_hit": attrs.get("cache_hit"),
        "ordnung.llm.outcome": attrs.get("outcome"),
        "ordnung.llm.call_id": attrs.get("call_id"),
        "ordnung.llm.repair_of": attrs.get("repair_of"),
    }
    if call is not None:
        values |= {
            "gen_ai.usage.input_tokens": call.input_tokens,
            "gen_ai.usage.output_tokens": call.output_tokens,
            "ordnung.llm.cache_read_tokens": call.cache_read_tokens,
            "ordnung.llm.cache_creation_tokens": call.cache_creation_tokens,
            "ordnung.llm.cost_usd": call.cost_usd,
            "ordnung.llm.latency_ms": call.duration_ms,
            "ordnung.llm.pages_sent": call.pages_sent,
            "ordnung.llm.bytes_sent": call.bytes_sent,
        }
    if attrs.get("outcome") == "failed":
        # the backend's error (sign-in, timeout …), or an answer a repair could not make usable
        values["error.type"] = "llm_error" if call is not None and call.error else "invalid_output"
    return values


def _span(trace: DocumentTrace, span: TraceSpan, trace_hex: str, start_ns: int) -> dict[str, Any]:
    model = span.kind == "model"
    begin = start_ns + round(span.start_ms * 1_000_000)
    values: dict[str, Any] = {
        f"ordnung.{key}": value
        for key, value in span.attributes.items()
        if not (model and key in _GEN_AI_KEYS)
    }
    values |= {
        "ordnung.document.id": trace.doc_id,
        "ordnung.step.kind": span.kind,
        "ordnung.step.key": span.key,
        "ordnung.step.name": span.name,
        "ordnung.stage": span.stage,
        "ordnung.ref.type": span.ref.type if span.ref else None,
        "ordnung.ref.id": span.ref.id if span.ref else None,
    }
    if model:
        values |= _gen_ai(span)
    name = f"{GEN_AI_OPERATION} {values.get('gen_ai.request.model') or 'model'}" if model else span.name
    status: dict[str, Any] = {"code": STATUS_UNSET}
    if span.status == "error":
        status = {"code": STATUS_ERROR, "message": span.error or "error"}
    return {
        "traceId": trace_hex,
        "spanId": hex_id(span.id, 8),
        "parentSpanId": hex_id(span.parent_id, 8) if span.parent_id else "",
        "name": name,
        "kind": SPAN_KIND_CLIENT if model else SPAN_KIND_INTERNAL,
        "startTimeUnixNano": str(begin),
        "endTimeUnixNano": str(begin + round(span.duration_ms * 1_000_000)),
        "attributes": attributes(values),
        "status": status,
    }


def to_otlp(trace: DocumentTrace) -> dict[str, Any]:
    """One reading of a letter as an OTLP/JSON ``ExportTraceServiceRequest`` (see the module docstring);
    a letter without a kept reading exports no spans."""
    spans: list[dict[str, Any]] = []
    if trace.run is not None:
        trace_hex = hex_id(trace.run.trace_id, 16)
        start_ns = _nanos(trace.run.started_at)
        spans = [_span(trace, span, trace_hex, start_ns) for span in trace.spans]
    resource = {"service.name": "ordnung", "service.version": __version__}
    return {
        "resourceSpans": [
            {
                "resource": {"attributes": attributes(resource)},
                "scopeSpans": [{"scope": {"name": SCOPE, "version": SCOPE_VERSION}, "spans": spans}],
            }
        ]
    }
