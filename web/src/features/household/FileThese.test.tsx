/**
 * *File these N* on the Inbox's view of one person: the letters addressed to them and not filed yet, listed in a
 * card with one button that files exactly those, a toast that says how many, and an Undo that puts each letter back
 * as it was (not answered). Nothing is filed without the press.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Household, HouseholdFiling, Party } from "@/api/types";
import { renderWithProviders } from "@/test/render";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import { makeRow } from "@/features/document/fixtures";
import { FileThese } from "./FileThese";

const ALEX = "hhm_alex00000001";
const HOUSEHOLD: Household = {
  members: [{ id: ALEX, name: "Alex Rivera", signs: true, letters: 0 }],
  filed: {},
  mine: [],
  suggested: { doc_a: ALEX, doc_b: ALEX, doc_c: ALEX },
  version: "0123456789abcdef",
};
const LETTERS = [
  makeRow({ id: "doc_a", title: "Dentist appointment reminder", party_id: "pty_dentist", received_date: "2026-09-25" }),
  makeRow({ id: "doc_b", title: "Library: overdue books", party_id: null, received_date: "2026-09-26" }),
];
const PARTIES = new Map<string, Party>([["pty_dentist", { id: "pty_dentist", name: "Zahnarztpraxis Dr. Muster" } as Party]]);

let filings: HouseholdFiling["letters"][];
let failNext: boolean;

beforeEach(() => {
  filings = [];
  failNext = false;
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    if (url.pathname === "/api/household" && init?.method === "PATCH") {
      if (failNext) {
        failNext = false;
        return new Response(JSON.stringify({ detail: "This letter is in the trash." }), { status: 404, headers: { "Content-Type": "application/json" } });
      }
      const letters = (JSON.parse(String(init.body)) as HouseholdFiling).letters;
      filings.push(letters);
      return new Response(JSON.stringify(HOUSEHOLD), { headers: { "Content-Type": "application/json" } });
    }
    return new Response(JSON.stringify({ detail: "Not here" }), { status: 404, headers: { "Content-Type": "application/json" } });
  });
});
afterEach(() => {
  vi.unstubAllGlobals();
  act(() => __clearToasts());
});

function renderCard(letters = LETTERS, onFiled = vi.fn()) {
  renderWithProviders(
    <>
      <FileThese member={HOUSEHOLD.members[0]!} letters={letters} household={HOUSEHOLD} parties={PARTIES} onFiled={onFiled} />
      <Toaster />
    </>,
  );
  return onFiled;
}

describe("File these N", () => {
  it("names the person, says why the letters are there and lists them with their sender and arrival", () => {
    renderCard();
    const card = screen.getByRole("region", { name: "Addressed to Alex Rivera, not filed yet, 2 letters" });
    expect(within(card).getByRole("heading", { level: 2 })).toHaveTextContent("Addressed to Alex Rivera, not filed yet · 2");
    expect(within(card).getByText("Ordnung read Alex Rivera's name on these letters. They count as yours until you file them.")).toBeInTheDocument();
    const list = within(card).getByRole("list", { name: "Letters addressed to Alex Rivera" });
    expect(
      within(list)
        .getAllByRole("link")
        .map((a) => [a.textContent, a.getAttribute("href")]),
    ).toEqual([
      ["Dentist appointment reminder", "/documents/doc_a"],
      ["Library: overdue books", "/documents/doc_b"],
    ]);
    expect(within(list).getByText(/Zahnarztpraxis Dr\. Muster/)).toBeInTheDocument();
    expect(within(card).getByRole("button", { name: "File these 2 for Alex Rivera" })).toBeInTheDocument();
  });

  it("says “File it” for one letter, and is not there without letters", () => {
    renderCard(LETTERS.slice(0, 1));
    expect(screen.getByRole("button", { name: "File it for Alex Rivera" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Addressed to Alex Rivera, not filed yet, 1 letter" })).toBeInTheDocument();
  });

  it("renders nothing when no letter is listed", () => {
    renderCard([]);
    expect(screen.queryByRole("region", { name: /Addressed to/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /^File / })).toBeNull();
  });

  it("files exactly the listed letters on the press, and Undo puts each back as it was", async () => {
    const onFiled = renderCard();
    expect(filings).toEqual([]); // nothing is filed by itself
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "File these 2 for Alex Rivera" }));
    await waitFor(() => expect(filings).toEqual([{ doc_a: ALEX, doc_b: ALEX }]));
    const toastItem = (await screen.findByText("Filed 2 letters for Alex Rivera")).closest("li")!;
    expect(onFiled).toHaveBeenCalledTimes(1);
    await user.click(within(toastItem).getByRole("button", { name: "Undo" }));
    // back to not answered: null for each, as before the press (doc_c, not listed, is never sent)
    await waitFor(() => expect(filings).toEqual([{ doc_a: ALEX, doc_b: ALEX }, { doc_a: null, doc_b: null }]));
  });

  it("says “Filed 1 letter” for one", async () => {
    renderCard(LETTERS.slice(1));
    await userEvent.setup().click(screen.getByRole("button", { name: "File it for Alex Rivera" }));
    expect(await screen.findByText("Filed 1 letter for Alex Rivera")).toBeInTheDocument();
    expect(filings).toEqual([{ doc_b: ALEX }]);
  });

  it("keeps focus on the button while it files, and keeps the card when filing fails", async () => {
    failNext = true;
    const onFiled = renderCard();
    const button = screen.getByRole("button", { name: "File these 2 for Alex Rivera" });
    await userEvent.setup().click(button);
    await waitFor(() => expect(button).not.toHaveAttribute("aria-busy"));
    expect(button).toHaveFocus();
    expect(onFiled).not.toHaveBeenCalled();
    expect(screen.queryByText(/^Filed /)).toBeNull();
  });
});
