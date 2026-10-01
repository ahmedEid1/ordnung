/**
 * The to-do Ordnung files itself when Claude's reading of a letter came back incomplete (`check:reading`,
 * `src/ordnung/ingest/gaps.py`): its "Please check" card says where its date came from — or, without one, why
 * there is none and how to give it one — instead of "doesn't match the sentence it came from" or "Couldn't find
 * this — please check". The letter's warning about the incomplete reading is no scam sign, and it goes once the
 * to-do no longer needs checking.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { makeTestQueryClient, renderWithProviders } from "@/test/render";
import { qk } from "@/api/hooks";
import { DocumentWarnings, READING_CHECK_SLOT } from "./Warnings";
import { ItemsList } from "./ItemsList";
import { germanRuns } from "./fact-text";
import { makeDetail, makeDoc, makeItem, makeSuggestion } from "./fixtures";

function client() {
  const qc = makeTestQueryClient();
  qc.setQueryData(qk.rules, []);
  return qc;
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } })));
});
afterEach(() => {
  vi.unstubAllGlobals();
});

const NOTICE = "Gegen diesen Gebührenbescheid können Sie binnen eines Monats nach seiner Bekanntgabe Widerspruch einlegen.";

/** The letter's warnings for an incomplete reading (`gap_warning` in `src/ordnung/ingest/gaps.py`). */
const GAP_DATED =
  "This letter explains how to object, but Claude's reading left out the deadline to object. Ordnung added the deadline from the letter's own instructions on how to object (Rechtsbehelfsbelehrung) — please check it against the letter before you rely on it.";
const GAP_BLANK =
  "Claude's reading of this letter came back almost blank: the sender, the letter's date and its to-dos were all left out. Please read the letter yourself; if it asks you to do something by a date, give the to-do “Read this letter yourself” that date.";

const dated = makeItem({
  id: "itm_check",
  kind: "deadline",
  title: "Deadline to object (Widerspruch)",
  due_date: "2026-12-09",
  slot_key: READING_CHECK_SLOT,
  grounding: "verified",
  evidence: [{ doc_id: "doc_1", page: 1, quote: NOTICE, grounding: "verified", value_consistent: false, score: 100, boxes: [] }],
});

const undatedDeadline = { ...dated, id: "itm_nodate", due_date: null };

const placeholder = makeItem({
  id: "itm_read",
  kind: "task",
  title: "Read this letter yourself",
  due_date: null,
  slot_key: READING_CHECK_SLOT,
  grounding: "unverified",
  evidence: [{ doc_id: "doc_1", page: null, quote: "", grounding: "unverified", value_consistent: false, score: 0, boxes: [] }],
});

const scam = makeSuggestion({ id: "sug_scam", kind: "scam", title: "Possible scam", refs: [{ type: "document", id: "doc_1" }] });

describe("the to-do Ordnung adds, round 2 (UX review 2)", () => {
  it("marks the remedy in parentheses German (R2UX-8)", () => {
    const runs = germanRuns("Deadline for a court action (Klage)");
    expect(runs.filter((r) => r.german).map((r) => r.text)).toEqual(["Klage"]);
    expect(germanRuns("Deadline to object (Widerspruch)").some((r) => r.german && r.text === "Widerspruch")).toBe(true);
  });

  it("shows no “couldn't find” chip on “Read this letter yourself”: it quotes nothing (R2UX-9)", () => {
    const done = { ...placeholder, status: "done" as const };
    renderWithProviders(<ItemsList items={[done]} docId="doc_1" />, { client: client() });
    expect(screen.getByText("Added by Ordnung")).toBeInTheDocument();
    expect(screen.queryByText("Please check")).toBeNull();
  });
});

describe("the to-do Ordnung adds for an incomplete reading", () => {
  it("is the backend's slot, spelled out", () => {
    // `CHECK_SLOT` in src/ordnung/ingest/gaps.py — a rename there must be a rename here
    expect(READING_CHECK_SLOT).toBe("check:reading");
  });

  it("says a dated one was worked out from the letter's instructions on how to object", () => {
    const doc = makeDoc({ status: "needs_review" });
    renderWithProviders(<DocumentWarnings detail={makeDetail({ document: doc, items: [dated] })} />, { client: client() });
    expect(screen.getByText("Deadline to object", { exact: false })).toBeInTheDocument();
    expect(
      screen.getByText("Ordnung worked this date out from the letter's own instructions on how to object, because Claude's reading left it out."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/doesn't match the sentence it came from/)).toBeNull();
    expect(screen.getByRole("button", { name: "Correct" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Change date" })).toBeInTheDocument();
  });

  it("marks the German term in its title for screen readers", () => {
    renderWithProviders(<DocumentWarnings detail={makeDetail({ document: makeDoc({ status: "needs_review" }), items: [dated] })} />, {
      client: client(),
    });
    const term = screen.getByText("Widerspruch", { selector: "span" });
    expect(term).toHaveAttribute("lang", "de");
  });

  it("asks for the date when it found the instructions but couldn't work it out", () => {
    renderWithProviders(<DocumentWarnings detail={makeDetail({ document: makeDoc({ status: "needs_review" }), items: [undatedDeadline] })} />, {
      client: client(),
    });
    expect(
      screen.getByText("Ordnung found the letter's instructions on how to object but couldn't work out the date from them — enter the deadline with “Set a date”."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Set a date" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Change date" })).toBeNull();
  });

  it("asks the person to read the letter when the reading came back almost blank", () => {
    const doc = makeDoc({ status: "needs_review" });
    renderWithProviders(<DocumentWarnings detail={makeDetail({ document: doc, items: [placeholder] })} />, { client: client() });
    expect(screen.getByText("Read this letter yourself", { exact: false })).toBeInTheDocument();
    expect(
      screen.getByText(
        "Claude's reading of this letter came back almost blank. Read the letter yourself; if it asks you to do something by a date, give this to-do that date with “Set a date”.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Couldn't find this/)).toBeNull();
    // reading it is the whole task: "Correct" would confirm a to-do that has nothing to confirm
    expect(screen.getByRole("button", { name: "I've read it — nothing to do" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Correct" })).toBeNull();
    expect(screen.getByRole("button", { name: "Set a date" })).toBeInTheDocument();
  });

  it("says the scam warning first on a letter with scam signs", () => {
    const detail = makeDetail({ document: makeDoc({ status: "needs_review", warnings: [GAP_DATED] }), items: [dated], suggestions: [scam] });
    renderWithProviders(<DocumentWarnings detail={detail} />, { client: client() });
    expect(screen.getByText(/This letter shows signs of a scam/)).toBeInTheDocument();
    expect(screen.queryByText(/worked this date out/)).toBeNull();
    expect(screen.getByRole("button", { name: "Not a real to-do" })).toBeInTheDocument();
  });

  it("never lists the incomplete reading as a scam sign", () => {
    // no `scam_signs` from the API: the banner lists the letter's warnings
    const detail = makeDetail({
      document: makeDoc({ status: "needs_review", warnings: [GAP_DATED, "The payee's name differs from the sender."] }),
      items: [dated],
      suggestions: [scam],
      scam_signs: [],
    });
    renderWithProviders(<DocumentWarnings detail={detail} />, { client: client() });
    const banner = screen.getByRole("alert");
    expect(banner).toHaveTextContent("The payee's name differs from the sender.");
    expect(banner).not.toHaveTextContent("Claude's reading");
    expect(banner).toHaveTextContent("The warning sign");
  });

  it("says the letter's warning only while the to-do still needs checking", () => {
    const warned = makeDoc({ status: "needs_review", warnings: [GAP_BLANK] });
    const { unmount } = renderWithProviders(<DocumentWarnings detail={makeDetail({ document: warned, items: [placeholder] })} />, {
      client: client(),
    });
    expect(screen.getByText(/the sender, the letter's date and its to-dos were all left out/)).toBeInTheDocument();
    unmount();

    // the person gave it a date of their own: the warning is out of date
    const dealt = { ...placeholder, grounding: "user" as const, due_date: "2026-12-01" };
    renderWithProviders(<DocumentWarnings detail={makeDetail({ document: makeDoc({ status: "processed", warnings: [GAP_BLANK, "Another note."] }), items: [dealt] })} />, {
      client: client(),
    });
    expect(screen.queryByText(/the sender, the letter's date and its to-dos were all left out/)).toBeNull();
    expect(screen.getByText("Another note.")).toBeInTheDocument();
  });

  it("leaves every other to-do's card as it was", () => {
    const other = { ...dated, id: "itm_other", slot_key: "a".repeat(40), title: "Pay the fee" };
    renderWithProviders(<DocumentWarnings detail={makeDetail({ document: makeDoc({ status: "needs_review" }), items: [other] })} />, { client: client() });
    expect(screen.getByText("The date or amount doesn't match the sentence it came from.")).toBeInTheDocument();
    expect(screen.getByText("Pay the fee", { exact: false })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Correct" })).toBeInTheDocument();
  });
});
