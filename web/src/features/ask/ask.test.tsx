import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import type { ChatMessage, StreamEvent } from "@/api/types";
import { citationIndex, numberCitations, parseCitations, stripAllMarkers, stripInvalid, stripPartialMarker, type CitationRef } from "./citations";
import { inlineText, isInternalHref, parseInline, parseMarkdown } from "./markdown";
import { Markdown } from "./Markdown";
import { accumulate, accumulateAll, EMPTY_ANSWER } from "./stream";
import { fallbackToolLabel, toolLabel } from "./tools";
import { makeRefResolver } from "./refs";
import { turnsFromHistory } from "./useAskThread";

const valid = citationIndex([
  { type: "document", id: "doc_phone" },
  { type: "item", id: "itm_phone_cancel" },
]);

function renderMd(text: string, citations: ReadonlyMap<string, CitationRef> | null = valid, streaming = false) {
  const router = createMemoryRouter(
    [
      {
        path: "*",
        element: (
          <Markdown
            text={text}
            citations={citations}
            streaming={streaming}
            renderCitation={(ref, key) => (
              <span key={key} data-cite={ref.id}>
                [{ref.type}]
              </span>
            )}
          />
        ),
      },
    ],
    { initialEntries: ["/"] },
  );
  return render(<RouterProvider router={router} />);
}

// ------------------------------------------------------------------------------------------------
// Citations
// ------------------------------------------------------------------------------------------------

describe("citation markers", () => {
  it("parses single, grouped and spelled-out markers in reading order", () => {
    const refs = parseCitations("A [doc:doc_a]. B [document:doc_b, item:itm_c]; C [contract:ctr_d][party:pty_e].");
    expect(refs).toEqual([
      { type: "document", id: "doc_a" },
      { type: "document", id: "doc_b" },
      { type: "item", id: "itm_c" },
      { type: "contract", id: "ctr_d" },
      { type: "party", id: "pty_e" },
    ]);
  });

  it("ignores markers whose id prefix does not fit the type", () => {
    expect(parseCitations("x [doc:itm_a] y [item:doc_b]")).toEqual([]);
  });

  it("keeps only validated ids and removes the others with the space before them", () => {
    const text = "Send by Thu 8 Oct [item:itm_phone_cancel] [doc:doc_fake]. Letter [doc:doc_phone, item:itm_nope].";
    expect(stripInvalid(text, valid)).toBe("Send by Thu 8 Oct [item:itm_phone_cancel]. Letter [doc:doc_phone].");
    expect(stripAllMarkers(text)).toBe("Send by Thu 8 Oct. Letter.");
  });

  it("numbers validated sources by first appearance; uncited validated ones come last", () => {
    const idx = citationIndex([
      { type: "document", id: "doc_phone" },
      { type: "item", id: "itm_phone_cancel" },
      { type: "party", id: "pty_x" },
    ]);
    const n = numberCitations("A [item:itm_phone_cancel] B [doc:doc_nope] C [doc:doc_phone] D [item:itm_phone_cancel]", idx);
    expect([...n.entries()]).toEqual([
      ["itm_phone_cancel", 1],
      ["doc_phone", 2],
      ["pty_x", 3],
    ]);
  });

  it("a validated id with the wrong type is not a valid citation", () => {
    const idx = citationIndex([{ type: "document", id: "itm_phone_cancel" }]);
    expect(stripInvalid("x [item:itm_phone_cancel]", idx)).toBe("x");
  });

  it("hides a half-received marker at the end of a streaming answer", () => {
    expect(stripPartialMarker("Send it by Thu 8 Oct [ite")).toBe("Send it by Thu 8 Oct");
    expect(stripPartialMarker("Send it by Thu 8 Oct [item:itm_pho")).toBe("Send it by Thu 8 Oct");
    expect(stripPartialMarker("Done [doc:doc_a].")).toBe("Done [doc:doc_a].");
    expect(stripPartialMarker("See [Open the letter")).toBe("See [Open the letter");
  });
});

// ------------------------------------------------------------------------------------------------
// Markdown safety
// ------------------------------------------------------------------------------------------------

describe("safe markdown renderer", () => {
  it("renders raw HTML as literal text — no elements are injected", () => {
    const { container } = renderMd('Hello <script>alert(1)</script> <img src=x onerror="alert(2)"> <b>bold</b> <a href="javascript:alert(3)">x</a>');
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
    expect(container.querySelector("a")).toBeNull();
    expect(container.textContent).toContain("<script>alert(1)</script>");
    expect(container.querySelector("[onerror]")).toBeNull();
    expect(container.innerHTML).toContain("&lt;img src=x");
  });

  it("never renders images (remote or not) — only their alt text", () => {
    const { container } = renderMd("Look ![a tracking pixel](https://evil.example/p.gif) and ![local](/api/documents/doc_x/pages/1.jpg)");
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toBe("Look a tracking pixel and local");
  });

  it("links only to internal routes; external and script links lose their link", () => {
    const { container } = renderMd(
      "[the letter](/documents/doc_phone) · [phish](https://evil.example) · [js](javascript:alert(1)) · [proto](//evil.example/x) · [data](data:text/html,hi)",
    );
    const links = container.querySelectorAll("a");
    expect(links).toHaveLength(1);
    expect(links[0]!.getAttribute("href")).toBe("/documents/doc_phone");
    expect(container.textContent).toContain("phish");
    expect(container.textContent).not.toContain("evil.example");
    expect(isInternalHref("/timeline?month=2026-10")).toBe(true);
    expect(isInternalHref("//evil.example")).toBe(false);
    expect(isInternalHref("/\\evil.example")).toBe(false);
    expect(isInternalHref("https://evil.example")).toBe(false);
    expect(isInternalHref("javascript:alert(1)")).toBe(false);
  });

  it("supports paragraphs, lists, bold, italic and inline code", () => {
    const { container } = renderMd("Here's your week:\n\n1. **Parking fine** — pay by *Tue*\n2. Use `Kündigung`\n\n- one\n- two\n\nLast line\nsecond line");
    expect(container.querySelector("ol")!.children).toHaveLength(2);
    expect(container.querySelector("ul")!.children).toHaveLength(2);
    expect(container.querySelector("strong")!.textContent).toBe("Parking fine");
    expect(container.querySelector("em")!.textContent).toBe("Tue");
    expect(container.querySelector("code")!.textContent).toBe("Kündigung");
    expect(container.querySelectorAll("p")).toHaveLength(2);
    expect(container.querySelector("br")).not.toBeNull();
  });

  it("leaves snake_case and lone asterisks alone", () => {
    expect(inlineText(parseInline("file_name_here costs 5 * 3", null))).toBe("file_name_here costs 5 * 3");
    expect(parseInline("a_b_c", null)).toEqual([{ t: "text", v: "a_b_c" }]);
  });

  it("turns validated citation markers into chips and strips the rest", () => {
    const { container } = renderMd("Cancel by Wed 14 Oct [item:itm_phone_cancel] [doc:doc_nope]. See **the letter [doc:doc_phone]**.");
    const chips = container.querySelectorAll("[data-cite]");
    expect([...chips].map((c) => c.getAttribute("data-cite"))).toEqual(["itm_phone_cancel", "doc_phone"]);
    expect(container.textContent).not.toContain("doc_nope");
    expect(container.textContent).not.toMatch(/\[doc:|\[item:/);
  });

  it("while streaming, no marker becomes a chip and a partial marker is hidden", () => {
    const { container } = renderMd("Send by Thu 8 Oct [item:itm_phone_cancel] and [do", null, true);
    expect(container.querySelector("[data-cite]")).toBeNull();
    expect(container.textContent).toBe("Send by Thu 8 Oct and");
  });

  it("parses headings and quotes without producing heading elements from model text", () => {
    const blocks = parseMarkdown("# Big\n> quoted\n---\ntext", { citations: null });
    expect(blocks.map((b) => b.t)).toEqual(["h", "quote", "p"]);
  });
});

// ------------------------------------------------------------------------------------------------
// Stream accumulation
// ------------------------------------------------------------------------------------------------

describe("stream accumulation", () => {
  const events: StreamEvent[] = [
    { type: "tool_use", name: "mcp__ordnung__search", input: { query: "Kündigung" }, text: "Searched your letters for \"Kündigung\"" },
    { type: "tool_use", name: "list_items", input: { status: "open" } },
    { type: "tool_result", name: "search", text: "Found 1 letter" },
    { type: "text", text: "Yes. Send it by " },
    { type: "tool_result", name: "list_items", text: "Found 4 to-dos & dates" },
    { type: "text", text: "**Thu 8 Oct** [item:itm_phone_cancel] [doc:doc_x]." },
  ];

  it("builds the tool trace and the text as events arrive", () => {
    const s = accumulateAll(events);
    expect(s.status).toBe("streaming");
    expect(s.tools.map((t) => [t.name, t.done, t.result])).toEqual([
      ["search", true, "Found 1 letter"],
      ["list_items", true, "Found 4 to-dos & dates"],
    ]);
    expect(s.tools[0]!.label).toBe('Searched your letters for "Kündigung"');
    expect(s.text).toBe("Yes. Send it by **Thu 8 Oct** [item:itm_phone_cancel] [doc:doc_x].");
  });

  it("matches results to calls in call order (FIFO), by name when given", () => {
    let s = accumulate(EMPTY_ANSWER, { type: "tool_use", name: "search", input: { query: "a" } });
    s = accumulate(s, { type: "tool_use", name: "search", input: { query: "b" } });
    s = accumulate(s, { type: "tool_result", text: "first" });
    expect(s.tools.map((t) => t.result)).toEqual(["first", null]);
    s = accumulate(s, { type: "tool_result", name: "search", text: "second" });
    expect(s.tools.map((t) => t.result)).toEqual(["first", "second"]);
    // a stray result is ignored
    expect(accumulate(s, { type: "tool_result", text: "stray" })).toBe(s);
  });

  it("the done event replaces the streamed text with the checked answer and carries citations", () => {
    const s = accumulateAll([
      ...events,
      {
        type: "done",
        text: "Yes. Send it by **Thu 8 Oct** [item:itm_phone_cancel].",
        citations: [{ type: "item", id: "itm_phone_cancel", label: "Cancel phone contract" } as never],
        message_id: "msg_1",
        thread_id: "thr_1",
      },
    ]);
    expect(s.status).toBe("done");
    expect(s.text).toBe("Yes. Send it by **Thu 8 Oct** [item:itm_phone_cancel].");
    expect(s.citations).toEqual([{ type: "item", id: "itm_phone_cancel", label: "Cancel phone contract" }]);
    expect(s.messageId).toBe("msg_1");
    expect(s.threadId).toBe("thr_1");
  });

  it("keeps the streamed text when done has none, and closes open tool calls", () => {
    const s = accumulateAll([{ type: "tool_use", name: "today" }, { type: "text", text: "Hi" }, { type: "done", thread_id: "thr_2" }]);
    expect(s.text).toBe("Hi");
    expect(s.tools[0]!.done).toBe(true);
    expect(s.citations).toEqual([]);
  });

  it("errors keep what arrived so far", () => {
    const s = accumulateAll([{ type: "text", text: "Partial" }, { type: "error", error: "Claude is not signed in." }]);
    expect(s.status).toBe("error");
    expect(s.error).toBe("Claude is not signed in.");
    expect(s.text).toBe("Partial");
  });
});

// ------------------------------------------------------------------------------------------------
// Tool labels, refs, history
// ------------------------------------------------------------------------------------------------

describe("tool trace labels", () => {
  it("prefers the backend label and falls back to human wording", () => {
    expect(toolLabel({ name: "search", input: { query: "x" }, label: "From the server" })).toBe("From the server");
    expect(fallbackToolLabel("search", { query: "Kündigung" })).toBe("Searched your letters for “Kündigung”");
    expect(fallbackToolLabel("get_document", { doc_id: "doc_power" }, () => "Stadtwerke letter")).toBe("Opened “Stadtwerke letter”");
    expect(fallbackToolLabel("list_items", { status: "open" })).toBe("Listed your open to-dos & dates");
    expect(fallbackToolLabel("list_items", { from: "2026-09-28", to: "2026-10-04" })).toBe("Listed your open to-dos & dates from 28 Sep to 4 Oct");
    expect(fallbackToolLabel("mystery_tool")).toBe("Looked something up");
  });
});

describe("citation targets", () => {
  it("letters open the viewer, to-dos their letter, contracts the contracts page, people the drawer", () => {
    const { resolve } = makeRefResolver({
      items: [{ id: "itm_a", title: "Pay rent", doc_id: "doc_lease" } as never, { id: "itm_b", title: "Own to-do", doc_id: null } as never],
      documents: [{ id: "doc_lease", title: "Lease", filename: "lease.pdf" } as never],
    });
    expect(resolve({ type: "document", id: "doc_lease" })).toMatchObject({ href: "/documents/doc_lease", title: "Lease", kindLabel: "Letter" });
    expect(resolve({ type: "item", id: "itm_a" }).href).toBe("/documents/doc_lease");
    expect(resolve({ type: "item", id: "itm_b" }).href).toBe("/timeline");
    expect(resolve({ type: "contract", id: "ctr_x", label: "Phone" })).toMatchObject({ href: "/contracts?contract=ctr_x", title: "Phone" });
    expect(resolve({ type: "party", id: "pty_x" }).href).toBeNull();
  });
});

describe("stored conversation", () => {
  it("pairs stored questions with their answers, keeping trace and citations", () => {
    const msgs: ChatMessage[] = [
      { id: "m1", thread_id: "t", role: "user", content: "Q1", citations: [], tool_calls: [], created_at: "", note: null },
      {
        id: "m2",
        thread_id: "t",
        role: "assistant",
        content: "A1 [doc:doc_a]",
        citations: [{ type: "document", id: "doc_a" }],
        tool_calls: [{ name: "search", input: { query: "x" }, label: "Searched", result: "Found 1 letter" }],
        created_at: "",
        note: null,
      },
      { id: "m3", thread_id: "t", role: "user", content: "Q2", citations: [], tool_calls: [], created_at: "", note: null },
    ];
    const turns = turnsFromHistory(msgs);
    expect(turns).toHaveLength(1);
    expect(turns[0]!.question).toBe("Q1");
    expect(turns[0]!.answer.tools[0]).toMatchObject({ label: "Searched", result: "Found 1 letter", done: true });
    expect(turns[0]!.answer.citations).toEqual([{ type: "document", id: "doc_a" }]);
  });
});

describe("Markdown component", () => {
  it("is accessible text for screen readers (lists keep their structure)", () => {
    renderMd("- **Rent** 640,00 € [doc:doc_phone]");
    const list = screen.getByRole("list");
    expect(within(list).getByRole("listitem")).toHaveTextContent("Rent 640,00 € [document]");
  });
});
