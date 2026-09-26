import { describe, expect, it } from "vitest";
import { SseParser, readStreamEvents, toStreamEvent } from "./sse-parser";
import { reduceAsk, type AskState } from "./hooks";
import type { StreamEvent } from "./types";

function streamOf(chunks: (string | Uint8Array)[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const c of chunks) controller.enqueue(typeof c === "string" ? enc.encode(c) : c);
      controller.close();
    },
  });
}

async function collect(gen: AsyncGenerator<StreamEvent>): Promise<StreamEvent[]> {
  const out: StreamEvent[] = [];
  for await (const ev of gen) out.push(ev);
  return out;
}

describe("SseParser", () => {
  it("parses events split across arbitrary chunk boundaries", () => {
    const p = new SseParser();
    const msgs = [
      ...p.push("event: tool_use\nda"),
      ...p.push('ta: {"name":"search","input":{"query":"Kündigung"}}\n'),
      ...p.push("\nevent: text\ndata: {\"text\":\"Hel"),
      ...p.push('lo"}\n\n'),
    ];
    expect(msgs).toEqual([
      { event: "tool_use", data: '{"name":"search","input":{"query":"Kündigung"}}' },
      { event: "text", data: '{"text":"Hello"}' },
    ]);
  });

  it("handles CRLF, CR, comments, ids and multi-line data", () => {
    const p = new SseParser();
    // a trailing lone "\r" could be half of "\r\n", so the last message completes on end()
    const msgs = [...p.push(": keep-alive\r\nid: 7\r\nevent: text\r\ndata: line one\r\ndata: line two\r\n\r\ndata: plain\r\r"), ...p.end()];
    expect(msgs).toEqual([
      { event: "text", data: "line one\nline two", id: "7" },
      { event: "message", data: "plain", id: "7" },
    ]);
  });

  it("waits when a chunk ends in the middle of a CRLF", () => {
    const p = new SseParser();
    expect(p.push("event: done\r")).toEqual([]);
    expect(p.push("\ndata: {}\r\n\r\n")).toEqual([{ event: "done", data: "{}" }]);
  });

  it("flushes a final message without a trailing blank line", () => {
    const p = new SseParser();
    p.push("event: done\ndata: {\"message_id\":\"msg_1\"}");
    expect(p.end()).toEqual([{ event: "done", data: '{"message_id":"msg_1"}' }]);
  });
});

describe("toStreamEvent", () => {
  it("takes the type from the event name or the JSON body", () => {
    expect(toStreamEvent({ event: "text", data: '{"text":"Hi"}' })).toEqual({ type: "text", text: "Hi" });
    expect(toStreamEvent({ event: "message", data: '{"type":"tool_result","name":"search","text":"1 letter"}' })).toEqual({
      type: "tool_result",
      name: "search",
      text: "1 letter",
    });
    expect(toStreamEvent({ event: "text", data: "raw words" })).toEqual({ type: "text", text: "raw words" });
    expect(toStreamEvent({ event: "error", data: '{"message":"Budget exceeded"}' })).toMatchObject({ type: "error", error: "Budget exceeded" });
    expect(toStreamEvent({ event: "ping", data: "" })).toBeNull();
  });
});

describe("readStreamEvents", () => {
  it("decodes multi-byte characters split between chunks", async () => {
    const bytes = new TextEncoder().encode('event: text\ndata: {"text":"Kündigung €"}\n\n');
    const cut = bytes.indexOf(0xc3) + 1; // split inside "ü"
    const events = await collect(readStreamEvents(streamOf([bytes.slice(0, cut), bytes.slice(cut)])));
    expect(events).toEqual([{ type: "text", text: "Kündigung €" }]);
  });

  it("replays a recorded Ask answer into state with tool trace and citations", async () => {
    const body = streamOf([
      ": connected\n\n",
      'event: tool_use\ndata: {"name":"list_items","input":{"from":"2026-09-28"}}\n\n',
      'event: tool_result\ndata: {"name":"list_items","text":"Found 4 to-dos & dates"}\n\n',
      'event: text\ndata: {"text":"Pay the parking fine "}\n\n',
      'event: text\ndata: {"text":"[item:itm_parking]."}\n\n',
      'event: done\ndata: {"message_id":"msg_2","thread_id":"thr_1","citations":[{"type":"item","id":"itm_parking"}]}\n\n',
    ]);
    const events = await collect(readStreamEvents(body));
    expect(events.map((e) => e.type)).toEqual(["tool_use", "tool_result", "text", "text", "done"]);

    const initial: AskState = {
      status: "streaming",
      question: "What now?",
      text: "",
      toolCalls: [],
      citations: [],
      messageId: null,
      threadId: null,
      error: null,
      events: [],
    };
    const final = events.reduce(reduceAsk, initial);
    expect(final.status).toBe("done");
    expect(final.text).toBe("Pay the parking fine [item:itm_parking].");
    expect(final.toolCalls).toEqual([{ name: "list_items", input: { from: "2026-09-28" }, result: "Found 4 to-dos & dates" }]);
    expect(final.citations).toEqual([{ type: "item", id: "itm_parking" }]);
    expect(final.threadId).toBe("thr_1");
    expect(final.messageId).toBe("msg_2");
  });
});
