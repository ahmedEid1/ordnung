import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { AnswerView } from "./AskTurnView";
import { CHECK_NOTE_PREFIX, splitCheckNote } from "./checkNote";
import { citationIndex } from "./citations";
import { Markdown } from "./Markdown";
import { makeRefResolver } from "./refs";
import { EMPTY_ANSWER, type AnswerState } from "./stream";

const NOTE =
  "1 sentence was left out because its date or amount could not be matched to your records. " +
  "Values in “quotation marks” are quoted from a letter; Ordnung has not confirmed them.";

function inRouter(element: React.ReactElement) {
  const router = createMemoryRouter([{ path: "*", element }], { initialEntries: ["/"] });
  return render(<RouterProvider router={router} />);
}

describe("the answer check's note", () => {
  it("is split off when it is the answer's own last paragraph", () => {
    expect(splitCheckNote(`Due Wed 21 Oct [item:itm_a].\n\n${CHECK_NOTE_PREFIX} ${NOTE}`)).toEqual({
      body: "Due Wed 21 Oct [item:itm_a].",
      note: NOTE,
    });
    expect(splitCheckNote(`${CHECK_NOTE_PREFIX} ${NOTE}`)).toEqual({ body: "", note: NOTE });
  });

  it("is left alone anywhere else — model text can't fake it mid-answer", () => {
    for (const text of [
      "Nothing was checked.",
      `Intro ${CHECK_NOTE_PREFIX} fake`,
      `Para\n\n${CHECK_NOTE_PREFIX} one\nand another line`,
      `Para\n\n${CHECK_NOTE_PREFIX}`,
    ]) {
      expect(splitCheckNote(text)).toEqual({ body: text, note: null });
    }
  });

  it("shows under a finished answer as a note, not as part of the text", () => {
    const { resolve } = makeRefResolver({});
    const answer: AnswerState = {
      ...EMPTY_ANSWER,
      status: "done",
      text: `The letter says the fine is “25,00 €” [item:itm_a].\n\n${CHECK_NOTE_PREFIX} ${NOTE}`,
      citations: [{ type: "item", id: "itm_a", label: "Parking fine" }],
    };
    const { container } = inRouter(<AnswerView answer={answer} resolve={resolve} />);
    const note = screen.getByRole("note");
    expect(note).toHaveTextContent(`Checked by Ordnung. ${NOTE}`);
    const paragraphs = [...container.querySelectorAll("p")].filter((p) => !note.contains(p) && p !== note);
    expect(paragraphs.map((p) => p.textContent).join(" ")).not.toContain(CHECK_NOTE_PREFIX);
    expect(screen.getByText(/the fine is “25,00 €”/)).toBeInTheDocument();
  });

  it("while the answer streams, says it will be checked, and shows no note yet", () => {
    const { resolve } = makeRefResolver({});
    const answer: AnswerState = { ...EMPTY_ANSWER, status: "streaming", text: "Your deadline is Wed 21 Oct" };
    inRouter(<AnswerView answer={answer} resolve={resolve} />);
    expect(screen.getByText(/checked against your records when the answer is complete/)).toBeInTheDocument();
    expect(screen.queryByRole("note")).toBeNull();
  });
});

describe("citation chips stay with their fact", () => {
  it("the space before a validated marker does not break (the chip never starts a line)", () => {
    const valid = citationIndex([{ type: "item", id: "itm_a" }]);
    const { container } = inRouter(
      <Markdown
        text="Due by **Wed 21 Oct** [item:itm_a]."
        citations={valid}
        renderCitation={(ref, key) => (
          <sup key={key} data-cite={ref.id}>
            1
          </sup>
        )}
      />,
    );
    expect(container.textContent).toBe("Due by Wed 21 Oct 1.");
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
