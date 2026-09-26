/**
 * Incremental Server-Sent Events parser (used for the streamed `POST /api/ask` response, which
 * EventSource cannot consume because it is a POST).
 *
 * Handles chunk boundaries anywhere (even inside a line or a multi-byte character), `\n`, `\r\n`
 * and `\r` line endings, multi-line `data:` fields, `event:`/`id:` fields and `:` comments
 * (keep-alive pings).
 */
import type { StreamEvent } from "./types";

export interface SseMessage {
  event: string;
  data: string;
  id?: string;
}

/** Stateful line-oriented parser. Feed text chunks, get complete messages back. */
export class SseParser {
  private buffer = "";
  private event = "";
  private data: string[] = [];
  private id: string | undefined;

  /** Feed a decoded text chunk; returns the messages completed by it. */
  push(chunk: string): SseMessage[] {
    this.buffer += chunk;
    const out: SseMessage[] = [];
    // split on any line terminator; keep the trailing partial line in the buffer
    for (;;) {
      const m = /\r\n|\n|\r/.exec(this.buffer);
      if (!m) break;
      // a lone "\r" at the very end may be the first half of "\r\n" — wait for more input
      if (m[0] === "\r" && m.index === this.buffer.length - 1) break;
      const line = this.buffer.slice(0, m.index);
      this.buffer = this.buffer.slice(m.index + m[0].length);
      const msg = this.line(line);
      if (msg) out.push(msg);
    }
    return out;
  }

  /** Flush at end of stream (a final message without a trailing blank line still counts). */
  end(): SseMessage[] {
    const out: SseMessage[] = [];
    if (this.buffer) {
      const msg = this.line(this.buffer);
      this.buffer = "";
      if (msg) out.push(msg);
    }
    const last = this.dispatch();
    if (last) out.push(last);
    return out;
  }

  private line(line: string): SseMessage | null {
    if (line === "") return this.dispatch();
    if (line.startsWith(":")) return null; // comment / keep-alive
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    switch (field) {
      case "event":
        this.event = value;
        break;
      case "data":
        this.data.push(value);
        break;
      case "id":
        this.id = value;
        break;
      default:
        break; // "retry" and unknown fields are ignored
    }
    return null;
  }

  private dispatch(): SseMessage | null {
    if (this.data.length === 0 && !this.event) return null;
    const msg: SseMessage = { event: this.event || "message", data: this.data.join("\n") };
    if (this.id !== undefined) msg.id = this.id;
    this.event = "";
    this.data = [];
    return msg;
  }
}

const STREAM_TYPES = new Set<StreamEvent["type"]>(["text", "tool_use", "tool_result", "done", "error"]);

/**
 * Convert one SSE message into a {@link StreamEvent}. The event type comes from the `event:` field
 * or, for plain `message` events, from a `type` property in the JSON data. Non-JSON `text` data is
 * treated as a raw text delta. Returns null for unknown / keep-alive messages.
 */
export function toStreamEvent(msg: SseMessage): StreamEvent | null {
  let payload: Record<string, unknown> | null = null;
  if (msg.data) {
    try {
      const parsed: unknown = JSON.parse(msg.data);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) payload = parsed as Record<string, unknown>;
      else if (typeof parsed === "string") payload = { text: parsed };
    } catch {
      payload = { text: msg.data };
    }
  }
  const declared = msg.event !== "message" ? msg.event : typeof payload?.type === "string" ? payload.type : "";
  if (!STREAM_TYPES.has(declared as StreamEvent["type"])) return null;
  const type = declared as StreamEvent["type"];
  const ev: StreamEvent = { ...(payload ?? {}), type } as StreamEvent;
  if (type === "error" && !ev.error) ev.error = typeof payload?.message === "string" ? payload.message : ev.text ?? "Something went wrong.";
  return ev;
}

/** Read a streamed response body and yield parsed SSE messages. */
export async function* readSse(body: ReadableStream<Uint8Array>, signal?: AbortSignal): AsyncGenerator<SseMessage> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  const parser = new SseParser();
  try {
    for (;;) {
      if (signal?.aborted) break;
      const { value, done } = await reader.read();
      if (done) break;
      for (const msg of parser.push(decoder.decode(value, { stream: true }))) yield msg;
    }
    for (const msg of parser.push(decoder.decode())) yield msg;
    for (const msg of parser.end()) yield msg;
  } finally {
    try {
      await reader.cancel();
    } catch {
      /* already closed */
    }
    reader.releaseLock?.();
  }
}

/** Read a streamed Ask response body and yield {@link StreamEvent}s. */
export async function* readStreamEvents(
  body: ReadableStream<Uint8Array>,
  signal?: AbortSignal,
): AsyncGenerator<StreamEvent> {
  for await (const msg of readSse(body, signal)) {
    const ev = toStreamEvent(msg);
    if (ev) yield ev;
  }
}
