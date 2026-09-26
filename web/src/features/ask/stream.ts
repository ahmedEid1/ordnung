/**
 * Accumulating a streamed Ask answer (`POST /api/ask`, SPEC §10).
 *
 * Event order: `tool_use` (the backend adds a human label in `text`) → `tool_result` (a short
 * summary in `text`; results arrive in call order) → one `text` event while the answer is written →
 * `done` (the **checked** answer text, the check's `note`, the validated citations and the stored ids)
 * or `error`. The model's words are never shown before the check (ADR 0008): a `text` event only
 * sets `writing`, whatever it carries, so an answer that stops or fails shows none of them.
 * {@link accumulate} is a pure reducer so the whole flow is unit-testable.
 *
 * The note comes only from the `done` event's own field (or a stored message's `note`), never from
 * the answer text: a model can write "Checked by Ordnung:" too (ADR 0008).
 */
import type { StreamEvent } from "@/api/types";
import type { CitationRef } from "./citations";

export type TurnStatus = "streaming" | "done" | "error" | "stopped";

export interface ToolStep {
  /** short tool name (`search`, `list_items`…) — never shown raw */
  name: string;
  input: Record<string, unknown>;
  /** human label from the backend ("Searched your letters for "Kündigung"") */
  label: string | null;
  /** short result summary ("Found 4 to-dos & dates") */
  result: string | null;
  done: boolean;
}

export interface AnswerState {
  status: TurnStatus;
  /** the checked answer (`done`, or a stored message) — never unchecked words */
  text: string;
  /** the model is writing the answer (it is shown once Ordnung has checked it) */
  writing: boolean;
  /** what Ordnung's answer check left out or quoted (`done`), shown under the answer */
  note: string | null;
  tools: ToolStep[];
  citations: CitationRef[];
  messageId: string | null;
  threadId: string | null;
  error: string | null;
}

export const EMPTY_ANSWER: AnswerState = {
  status: "streaming",
  text: "",
  writing: false,
  note: null,
  tools: [],
  citations: [],
  messageId: null,
  threadId: null,
  error: null,
};

const TOOL_PREFIX = "mcp__ordnung__";

/** `mcp__ordnung__search` → `search`. */
export function shortToolName(raw: string | null | undefined): string {
  return (raw || "tool").replace(TOOL_PREFIX, "");
}

/** Apply one stream event. */
export function accumulate(state: AnswerState, ev: StreamEvent): AnswerState {
  switch (ev.type) {
    case "tool_use":
      return {
        ...state,
        tools: [
          ...state.tools,
          { name: shortToolName(ev.name), input: ev.input ?? {}, label: ev.text?.trim() || null, result: null, done: false },
        ],
      };
    case "tool_result": {
      const name = ev.name ? shortToolName(ev.name) : null;
      // results arrive in call order: the first open call (of that name, when given)
      let idx = state.tools.findIndex((t) => !t.done && (!name || t.name === name));
      if (idx < 0) idx = state.tools.findIndex((t) => !t.done);
      if (idx < 0) return state;
      const tools = state.tools.slice();
      tools[idx] = { ...tools[idx]!, result: ev.text?.trim() || null, done: true };
      return { ...state, tools };
    }
    case "text":
      // the words wait for the check: a text event only says the answer is being written
      return state.writing ? state : { ...state, writing: true };
    case "done":
      return {
        ...state,
        status: "done",
        writing: false,
        // only the checked answer is ever shown (unsupported values left out, sentences removed)
        text: typeof ev.text === "string" ? ev.text : "",
        note: ev.note?.trim() || null,
        tools: state.tools.map((t) => (t.done ? t : { ...t, done: true })),
        citations: (ev.citations as CitationRef[] | undefined) ?? [],
        messageId: ev.message_id ?? state.messageId,
        threadId: ev.thread_id ?? state.threadId,
      };
    case "error":
      return {
        ...state,
        status: "error",
        writing: false,
        error: ev.error || "Something went wrong.",
        tools: state.tools.map((t) => (t.done ? t : { ...t, done: true })),
      };
    default:
      return state;
  }
}

/** Fold a whole event list (tests, replays). */
export function accumulateAll(events: StreamEvent[], from: AnswerState = EMPTY_ANSWER): AnswerState {
  return events.reduce(accumulate, from);
}

/** Tool steps of a stored message (`ChatMessage.tool_calls`). */
export function toolStepsFromStored(calls: Record<string, unknown>[]): ToolStep[] {
  return calls.map((c) => ({
    name: shortToolName(typeof c.name === "string" ? c.name : null),
    input: c.input && typeof c.input === "object" ? (c.input as Record<string, unknown>) : {},
    label: typeof c.label === "string" ? c.label : null,
    result: typeof c.result === "string" ? c.result : null,
    done: true,
  }));
}
