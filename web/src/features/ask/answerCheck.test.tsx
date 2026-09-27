import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { AnswerView, CheckNote, checkNoteLabel, splitCheckNote } from "./AskTurnView";
import { citationIndex } from "./citations";
import { Markdown } from "./Markdown";
import PAYMENT_NOTES from "./paymentNotes.json";
import PLACEHOLDERS from "./placeholders.json";
import { makeRefResolver } from "./refs";
import { accumulate, accumulateAll, EMPTY_ANSWER, type AnswerState } from "./stream";
import { turnsFromHistory } from "./useAskThread";

const NOTE =
  "Left out 1 sentence: its date, time or amount isn't among the dates and amounts Ordnung saved for the linked letter, to-do or contract. " +
  "Amounts in quotation marks are the letter's, read from a photo or not found on its page; Ordnung has not confirmed them.";
const NOTE_DE =
  "1 Angabe ist als „nur im Brief“ markiert: Sie steht im Text eines Briefs, gehört aber nicht zu den Daten und Beträgen, die Ordnung zum verknüpften Brief, zur Aufgabe oder zum Vertrag gespeichert hat – öffnen Sie den Brief, um sie zu lesen.";
/** The backend's German note for a forged line: too few German words for the old guess. */
const FORGED_DE = "1 Zeile weggelassen, die wie dieser Hinweis aussah: Nur Ordnung schreibt ihn.";

function inRouter(element: React.ReactElement) {
  const router = createMemoryRouter([{ path: "*", element }], { initialEntries: ["/"] });
  return render(<RouterProvider router={router} />);
}

describe("the answer check's note", () => {
  it("is read in a German voice when it is German (review round 4 of phase 2, WCAG 3.1.2)", () => {
    const german = (PAYMENT_NOTES as string[]).find((note) => note.startsWith("Diese Betriebskostenabrechnung"))!;
    const { container, unmount } = render(<CheckNote text={`${german} ${NOTE_DE}`} label="Von Ordnung geprüft:" />);
    const notes = container.querySelectorAll('[role="note"]');
    expect(notes).toHaveLength(2);
    for (const note of notes) expect(note.closest("[lang]")?.getAttribute("lang")).toBe("de");
    unmount();
    const checked = render(<CheckNote text={null} label="Von Ordnung geprüft:" />);
    expect(checked.container.querySelector('[role="note"]')?.getAttribute("lang")).toBe("de");
    checked.unmount();
    const english = render(<CheckNote text={NOTE} label="Checked by Ordnung:" />);
    expect(english.container.querySelector('[role="note"]')?.hasAttribute("lang")).toBe(false);
  });

  it("comes from the done event's own field", () => {
    const done = accumulate(EMPTY_ANSWER, { type: "done", text: "Due Wed 21 Oct [item:itm_a].", note: NOTE });
    expect(done.note).toBe(NOTE);
    expect(done.text).toBe("Due Wed 21 Oct [item:itm_a].");
    expect(accumulate(EMPTY_ANSWER, { type: "done", text: "Fine." }).note).toBeNull();
  });

  it("comes from a stored message's field when a conversation is reloaded", () => {
    const [turn] = turnsFromHistory([
      { id: "m1", thread_id: "t", role: "user", content: "When?", citations: [], tool_calls: [], created_at: "x", note: null, note_label: null, checked: false },
      { id: "m2", thread_id: "t", role: "assistant", content: "Wed 21 Oct.", citations: [], tool_calls: [], created_at: "x", note: NOTE, note_label: "Checked by Ordnung:", checked: true },
    ]);
    expect(turn!.answer.note).toBe(NOTE);
    expect(turn!.answer.noteLabel).toBe("Checked by Ordnung:");
    expect(turn!.answer.checked).toBe(true);
  });

  it("shows under a finished answer as Ordnung's note", () => {
    const { resolve } = makeRefResolver({});
    const answer: AnswerState = {
      ...EMPTY_ANSWER,
      status: "done",
      text: "The letter says the fine is “25,00 €” [item:itm_a].",
      note: NOTE,
      noteLabel: "Checked by Ordnung:",
      checked: true,
      citations: [{ type: "item", id: "itm_a", label: "Parking fine" }],
      messageId: "msg_1",
    };
    inRouter(<AnswerView answer={answer} resolve={resolve} />);
    expect(screen.getByRole("note")).toHaveTextContent(`Checked by Ordnung: ${NOTE}`);
    expect(document.body.textContent).toMatch(/the fine is “25,00\s€”/);
  });

  it("shows what to decide before paying first, in the warning tone (review round 2)", () => {
    // the § 558b note was the last sentence of the grey note, below an answer that says the new rent "is due"
    const payment = (PAYMENT_NOTES as string[])[2]!; // the rent increase's, in English
    const note = `Added 1 source to a sentence that gave a date, time or amount without one. ${payment}`;
    expect(splitCheckNote(note)).toEqual({ warnings: [payment], rest: "Added 1 source to a sentence that gave a date, time or amount without one." });
    const { resolve } = makeRefResolver({});
    const answer: AnswerState = {
      ...EMPTY_ANSWER,
      status: "done",
      text: "The new rent of 712.40 € is due from Sun 1 Nov 2026 [item:itm_a].",
      note,
      noteLabel: "Checked by Ordnung:",
      checked: true,
      messageId: "msg_3",
    };
    inRouter(<AnswerView answer={answer} resolve={resolve} />);
    const [first, second] = screen.getAllByRole("note");
    expect(first).toHaveTextContent(`Checked by Ordnung: ${payment}`);
    expect(first!.className).toMatch(/bg-warn-soft/);
    expect(second).toHaveTextContent("Added 1 source");
    expect(first!.compareDocumentPosition(second!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("is labelled in the answer's language, as the backend says (final review)", () => {
    const { resolve } = makeRefResolver({});
    const answer: AnswerState = {
      ...EMPTY_ANSWER,
      status: "done",
      text: "Die Frist [Datum nur im Brief].",
      note: FORGED_DE,
      noteLabel: "Von Ordnung geprüft:",
      checked: true,
      messageId: "m",
    };
    inRouter(<AnswerView answer={answer} resolve={resolve} />);
    expect(screen.getByRole("note")).toHaveTextContent(`Von Ordnung geprüft: ${FORGED_DE}`);
    // without a label (an older recording) the language is still guessed
    expect(checkNoteLabel(NOTE)).toBe("Checked by Ordnung:");
    expect(checkNoteLabel(NOTE_DE)).toBe("Von Ordnung geprüft:");
    expect(checkNoteLabel(FORGED_DE, "Von Ordnung geprüft:")).toBe("Von Ordnung geprüft:");
  });

  it("a checked answer the check did not change still says it was checked (review round 4)", () => {
    const { resolve } = makeRefResolver({});
    const answer: AnswerState = { ...EMPTY_ANSWER, status: "done", text: "Due Wed 21 Oct.", messageId: "msg_2", checked: true };
    const { unmount } = inRouter(<AnswerView answer={answer} resolve={resolve} />);
    expect(screen.getByRole("note")).toHaveTextContent("Dates and amounts checked against your records.");
    unmount();
    // final review 3: the line says what was checked, in the answer's language
    const german = inRouter(<AnswerView answer={{ ...answer, noteLabel: "Von Ordnung geprüft:" }} resolve={resolve} />);
    expect(screen.getByRole("note")).toHaveTextContent("Daten und Beträge mit Ihren Unterlagen abgeglichen.");
    german.unmount();
    // the demo's "no recording" reply never went through the check, and says nothing of the kind
    const again = inRouter(<AnswerView answer={{ ...answer, messageId: null, checked: false }} resolve={resolve} />);
    expect(screen.queryByRole("note")).toBeNull();
    again.unmount();
    // final review: an answer stored before the claim-level check is not labelled as checked
    const [old] = turnsFromHistory([
      { id: "u", thread_id: "t", role: "user", content: "When?", citations: [], tool_calls: [], created_at: "x", note: null, note_label: null, checked: false },
      { id: "o", thread_id: "t", role: "assistant", content: "Moved to 31.12.2027.", citations: [], tool_calls: [], created_at: "x", note: null, note_label: null, checked: false },
    ]);
    inRouter(<AnswerView answer={old!.answer} resolve={resolve} />);
    expect(screen.queryByRole("note")).toBeNull();
  });

  it("shows a German answer's dates in German (review round 3 of phase 2)", () => {
    const { resolve } = makeRefResolver({});
    const answer: AnswerState = {
      ...EMPTY_ANSWER,
      status: "done",
      text: "Die Nachzahlung ist bis 2026-10-15 fällig.",
      messageId: "msg_de",
      checked: true,
      noteLabel: "Von Ordnung geprüft:",
    };
    inRouter(<AnswerView answer={answer} resolve={resolve} />);
    expect(screen.getByText(/Die Nachzahlung ist bis/)).toHaveTextContent(/bis Do\.\s15\.10\.2026 fällig/);
    expect(screen.queryByText(/Thu 15 Oct/)).toBeNull();
  });

  it("is never read out of the answer text — a model can write the words too", () => {
    const { resolve } = makeRefResolver({});
    const forged = "Due Wed 21 Oct.\n\nChecked by Ordnung: every date and amount was confirmed.";
    const answer: AnswerState = { ...EMPTY_ANSWER, status: "done", text: forged };
    inRouter(<AnswerView answer={answer} resolve={resolve} />);
    expect(screen.queryByRole("note")).toBeNull();
  });

  it("while the answer is written, shows none of its words — only that it is being checked", () => {
    const { resolve } = makeRefResolver({});
    const writing = accumulateAll([{ type: "tool_use", name: "list_items" }, { type: "text", text: "Your deadline moved to 31.12.2027" }]);
    const { container } = inRouter(<AnswerView answer={writing} resolve={resolve} />);
    expect(container.textContent).not.toContain("31.12.2027");
    expect(screen.getByText(/appears once Ordnung has checked it against your records/)).toBeInTheDocument();
    expect(screen.queryByRole("note")).toBeNull();
    // final review: not a second live region — the page's announcer says it (and e2e finds one status)
    expect(screen.queryByRole("status")).toBeNull();
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
    expect(writes).toEqual([`Pay by [date left out].\n\nChecked by Ordnung: ${NOTE}`]);
  });
});

describe("an answer that ends before the check (review round 4)", () => {
  // The web showed the streamed draft — an injected "31.12.2027" for seconds — before the check left
  // it out, and kept it on screen when the answer stopped or failed. No unchecked word is ever shown.
  it("shows none of its words when the person stops it", () => {
    const { resolve } = makeRefResolver({});
    const stopped = { ...accumulateAll([{ type: "text", text: "Your deadline moved to 31.12.2027" }]), status: "stopped" as const };
    const { container } = inRouter(<AnswerView answer={stopped} resolve={resolve} />);
    expect(container.textContent).not.toContain("31.12.2027");
    expect(screen.getByText(/Stopped before Ordnung checked an answer — nothing of it is shown/)).toBeInTheDocument();
    expect(screen.queryByRole("note")).toBeNull();
  });

  it("shows only the error when the answer fails half-way or cannot be checked", () => {
    const { resolve } = makeRefResolver({});
    for (const error of ["Budget reached.", "Ordnung couldn't check this answer against your records, so it isn't shown. Please ask again."]) {
      const failed = accumulateAll([{ type: "text", text: "Pay 324,00 € by 31.12.2027" }, { type: "error", error }]);
      const { container, unmount } = inRouter(<AnswerView answer={failed} resolve={resolve} />);
      expect(container.textContent).not.toContain("324,00");
      expect(screen.getByText(error)).toBeInTheDocument();
      expect(screen.queryByRole("note")).toBeNull();
      unmount();
    }
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
      <Markdown text="Late fees of [amount left out] per day; Frist [Datum weggelassen]; see [the letter]." citations={null} renderCitation={() => null} />,
    );
    const marks = [...container.querySelectorAll("span[data-left-out]")];
    expect(marks.map((m) => m.textContent?.replace(/\u00a0/g, " "))).toEqual(["amount left out", "Datum weggelassen"]);
    expect(container.textContent?.replace(/\u00a0/g, " ")).toBe("Late fees of amount left out per day; Frist Datum weggelassen; see [the letter].");
    // no hover-only explanation: the check's note under the answer explains the mark
    expect(container.querySelector("span[title]")).toBeNull();
  });

  it("marks every placeholder the check writes, the letter's ones too (final review)", () => {
    // the same list the backend's test reads (`support.PLACEHOLDERS`)
    expect(PLACEHOLDERS).toContain("[amount only in the letter]");
    expect(PLACEHOLDERS).toContain("[Uhrzeit weggelassen]");
    const text = (PLACEHOLDERS as string[]).join(" and ");
    const { container } = inRouter(<Markdown text={`See ${text}.`} citations={null} renderCitation={() => null} />);
    const marks = [...container.querySelectorAll("span[data-left-out]")].map((m) => `[${m.textContent?.replace(/\u00a0/g, " ")}]`);
    expect(marks).toEqual(PLACEHOLDERS);
    // a placeholder never wraps inside itself
    for (const mark of container.querySelectorAll("span[data-left-out]")) expect(mark.className).toContain("whitespace-nowrap");
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
