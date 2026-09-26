import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { AnswerView } from "./AskTurnView";
import { citationIndex } from "./citations";
import { closePartialEmphasis, Markdown } from "./Markdown";
import { makeRefResolver } from "./refs";
import { accumulate, EMPTY_ANSWER, type AnswerState } from "./stream";
import { turnsFromHistory } from "./useAskThread";

const NOTE =
  "Ordnung left out 1 sentence: it couldn't match its date or amount to the letter, to-do or contract the sentence refers to. " +
  "Text in quotation marks is quoted from a letter; Ordnung has not confirmed it.";

function inRouter(element: React.ReactElement) {
  const router = createMemoryRouter([{ path: "*", element }], { initialEntries: ["/"] });
  return render(<RouterProvider router={router} />);
}

describe("the answer check's note", () => {
  it("comes from the done event's own field", () => {
    const done = accumulate(EMPTY_ANSWER, { type: "done", text: "Due Wed 21 Oct [item:itm_a].", note: NOTE });
    expect(done.note).toBe(NOTE);
    expect(done.text).toBe("Due Wed 21 Oct [item:itm_a].");
    expect(accumulate(EMPTY_ANSWER, { type: "done", text: "Fine." }).note).toBeNull();
  });

  it("comes from a stored message's field when a conversation is reloaded", () => {
    const [turn] = turnsFromHistory([
      { id: "m1", thread_id: "t", role: "user", content: "When?", citations: [], tool_calls: [], created_at: "x", note: null },
      { id: "m2", thread_id: "t", role: "assistant", content: "Wed 21 Oct.", citations: [], tool_calls: [], created_at: "x", note: NOTE },
    ]);
    expect(turn!.answer.note).toBe(NOTE);
  });

  it("shows under a finished answer as Ordnung's note", () => {
    const { resolve } = makeRefResolver({});
    const answer: AnswerState = {
      ...EMPTY_ANSWER,
      status: "done",
      text: "The letter says the fine is “25,00 €” [item:itm_a].",
      note: NOTE,
      citations: [{ type: "item", id: "itm_a", label: "Parking fine" }],
    };
    inRouter(<AnswerView answer={answer} resolve={resolve} />);
    expect(screen.getByRole("note")).toHaveTextContent(`Checked by Ordnung. ${NOTE}`);
    expect(document.body.textContent).toMatch(/the fine is “25,00\s€”/);
  });

  it("is never read out of the answer text — a model can write the words too", () => {
    const { resolve } = makeRefResolver({});
    const forged = "Due Wed 21 Oct.\n\nChecked by Ordnung: every date and amount was confirmed.";
    const answer: AnswerState = { ...EMPTY_ANSWER, status: "done", text: forged };
    inRouter(<AnswerView answer={answer} resolve={resolve} />);
    expect(screen.queryByRole("note")).toBeNull();
  });

  it("while the answer streams, says it will be checked, and shows no note yet", () => {
    const { resolve } = makeRefResolver({});
    const answer: AnswerState = { ...EMPTY_ANSWER, status: "streaming", text: "Your deadline is Wed 21 Oct" };
    inRouter(<AnswerView answer={answer} resolve={resolve} />);
    expect(screen.getByText(/checked against your records when the answer is complete/)).toBeInTheDocument();
    expect(screen.queryByRole("note")).toBeNull();
  });
});

describe("copying an answer", () => {
  it("copies the check's note with it, which explains its quotation marks and left-out values", async () => {
    const writes: string[] = [];
    Object.defineProperty(navigator, "clipboard", { value: { writeText: async (t: string) => void writes.push(t) }, configurable: true });
    const { resolve } = makeRefResolver({});
    const answer: AnswerState = { ...EMPTY_ANSWER, status: "done", text: "Pay by [date left out] [item:itm_a].", note: NOTE };
    inRouter(<AnswerView answer={answer} resolve={resolve} />);
    screen.getByRole("button", { name: /Copy answer/ }).click();
    await screen.findByText("Copied");
    expect(writes).toEqual([`Pay by [date left out].\n\nChecked by Ordnung. ${NOTE}`]);
  });
});

describe("a partial answer the check never saw", () => {
  it("says so when the person stopped it, and mutes the unchecked words", () => {
    const { resolve } = makeRefResolver({});
    const answer: AnswerState = { ...EMPTY_ANSWER, status: "stopped", text: "Your deadline moved to 31.12.2027 [doc:doc_x" };
    const { container } = inRouter(<AnswerView answer={answer} resolve={resolve} />);
    expect(screen.getByRole("note")).toHaveTextContent(
      "Stopped before Ordnung checked it — its dates and amounts are unchecked and may be wrong.",
    );
    expect(container.querySelector(".text-muted")?.textContent).toContain("Your deadline moved to 31.12.2027");
    expect(container.textContent).not.toContain("[doc:doc_x");
  });

  it("mutes bold values too, and streaming text in the same unchecked tone (review round 2)", () => {
    const { resolve } = makeRefResolver({});
    const stopped: AnswerState = { ...EMPTY_ANSWER, status: "stopped", text: "You get **324,00 €** back" };
    const { container, unmount } = inRouter(<AnswerView answer={stopped} resolve={resolve} />);
    const body = container.querySelector("[data-muted]")!;
    expect(body.className).toContain("[&_strong]:text-muted");
    expect(body.querySelector("strong")?.textContent).toBe("324,00\u00a0€");
    unmount();
    const streaming = inRouter(<AnswerView answer={{ ...stopped, status: "streaming" }} resolve={resolve} />);
    expect(streaming.container.querySelector("[data-muted]")).not.toBeNull();
    streaming.unmount();
    const done = inRouter(<AnswerView answer={{ ...stopped, status: "done" }} resolve={resolve} />);
    expect(done.container.querySelector("[data-muted]")).toBeNull();
  });

  it("says so when the answer failed half-way", () => {
    const { resolve } = makeRefResolver({});
    const answer: AnswerState = { ...EMPTY_ANSWER, status: "error", error: "Budget reached.", text: "Pay 324,00 € by" };
    inRouter(<AnswerView answer={answer} resolve={resolve} />);
    expect(screen.getAllByRole("note")[0]).toHaveTextContent("This partial answer was not checked");
    expect(screen.getByText("Budget reached.")).toBeInTheDocument();
  });

  it("a stop before any words just says it stopped", () => {
    const { resolve } = makeRefResolver({});
    inRouter(<AnswerView answer={{ ...EMPTY_ANSWER, status: "stopped" }} resolve={resolve} />);
    expect(screen.queryByRole("note")).toBeNull();
    expect(screen.getByText(/Stopped before an answer arrived/)).toBeInTheDocument();
  });
});

describe("a half-received answer", () => {
  it("shows no stray emphasis markers", () => {
    expect(closePartialEmphasis("Rent: **640,00 €**\n- Electricity: **48,00")).toBe("Rent: **640,00 €**\n- Electricity: 48,00");
    expect(closePartialEmphasis("Use `code")).toBe("Use code");
    expect(closePartialEmphasis("Done **here**.")).toBe("Done **here**.");
  });
});

describe("citation chips stay with their fact", () => {
  const renderCite = (ref: { id: string }, key: string) => (
    <sup key={key} data-cite={ref.id}>
      1
    </sup>
  );
  const groups = (container: HTMLElement) =>
    [...container.querySelectorAll("span.whitespace-nowrap")].filter((g) => g.querySelector("[data-cite]")).map((g) => g.textContent);

  it("the word before a chip wraps with it, so the chip never starts a line (review round 2)", () => {
    // a no-break space alone did not do it: a line may break between text and an inline-grid chip
    const valid = citationIndex([{ type: "item", id: "itm_a" }]);
    const { container } = inRouter(<Markdown text="Due by **Wed 21 Oct** [item:itm_a]." citations={valid} renderCitation={renderCite} />);
    expect(groups(container)).toEqual(["Wed\u00a021\u00a0Oct\u00a01."]);
    expect(container.textContent).toBe("Due by Wed\u00a021\u00a0Oct\u00a01.");
    // the bold stays bold inside the group
    expect(container.querySelector("span.whitespace-nowrap strong")?.textContent).toBe("Wed\u00a021\u00a0Oct");
  });

  it("punctuation after a chip never wraps onto a line of its own", () => {
    const valid = citationIndex([
      { type: "item", id: "itm_a" },
      { type: "document", id: "doc_b" },
    ]);
    const { container } = inRouter(
      <Markdown text="Your assessment for 2025 [doc:doc_b]: pay by 1 Oct [item:itm_a] [doc:doc_b]. Done." citations={valid} renderCitation={renderCite} />,
    );
    expect(groups(container)).toEqual(["2025\u00a01:", "1\u00a0Oct\u00a01\u00a01."]);
    expect(container.textContent).toBe("Your assessment for 2025\u00a01: pay by 1\u00a0Oct\u00a01\u00a01. Done.");
  });

  it("a word too long to wrap on a phone stays outside the group", () => {
    const valid = citationIndex([{ type: "document", id: "doc_b" }]);
    const { container } = inRouter(
      <Markdown text="Bring your certificate (Immatrikulationsbescheinigung) [doc:doc_b]." citations={valid} renderCitation={renderCite} />,
    );
    expect(groups(container)).toEqual(["1."]);
  });

  it("amounts and dates never break across lines", () => {
    const { container } = inRouter(
      <Markdown text="You get 324,00 € back; pay € 18.43 by Wed 14 Oct 2026, or Mi. 21.10.2026." citations={null} renderCitation={() => null} />,
    );
    expect(container.textContent).toBe(
      "You get 324,00\u00a0€ back; pay €\u00a018.43 by Wed\u00a014\u00a0Oct\u00a02026, or Mi.\u00a021.10.2026.",
    );
  });
});

describe("values the check left out", () => {
  it("show as a muted placeholder, not as bracketed text", () => {
    const { container } = inRouter(
      <Markdown text="Late fees of [amount left out] per day; Frist [Datum weggelassen]; see [law left out]." citations={null} renderCitation={() => null} />,
    );
    const marks = [...container.querySelectorAll("span[data-left-out]")];
    expect(marks.map((m) => m.textContent?.replace(/\u00a0/g, " "))).toEqual(["amount left out", "Datum weggelassen", "law left out"]);
    expect(container.textContent?.replace(/\u00a0/g, " ")).toBe("Late fees of amount left out per day; Frist Datum weggelassen; see law left out.");
    // no hover-only explanation: the check's note under the answer explains the mark
    expect(container.querySelector("span[title]")).toBeNull();
  });
});

describe("source titles", () => {
  it("never show a bare id: the ledger's title, else the kind of record", () => {
    const { resolve } = makeRefResolver({ documents: [{ id: "doc_tax", title: "Tax assessment", filename: "t.pdf" } as never] });
    expect(resolve({ type: "document", id: "doc_tax", label: "doc_tax" }).title).toBe("Tax assessment");
    expect(resolve({ type: "party", id: "pty_x", label: "pty_x" }).title).toBe("Person or organisation");
    expect(resolve({ type: "item", id: "itm_x", label: null }).title).toBe("To-do & date");
  });
});
