/**
 * The composer's From field and your household (ADR 0023). A letter not filed for someone of the household — no
 * household, not answered, or the person's own — keeps the From field it had before the household existed, byte for
 * byte: the HTML below was recorded on the D3 base, before any composer change, and a later composer edit that
 * changes it must record it again on purpose.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Household } from "@/api/types";
import { __clearToasts } from "@/components/ui/Toast";
import LettersPage from "@/pages/LettersPage";
import { renderWithProviders } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import { ADDRESSEES } from "@/mocks/data/documents";

beforeEach(() => {
  vi.stubGlobal("scrollTo", () => {});
});
afterEach(() => {
  vi.unstubAllGlobals();
  act(() => __clearToasts());
  delete ADDRESSEES.doc_tax;
});

const ALEX = { id: "hhm_alex000000001", name: "Alex Rivera", signs: true, letters: 0 };

/** `GET /api/household` answers `household` (every other request goes to the mock API as before). */
function answerHousehold(household: Household): void {
  const api = globalThis.fetch;
  vi.stubGlobal("fetch", (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url, "http://localhost");
    if (url.pathname === "/api/household" && (init?.method ?? "GET").toUpperCase() === "GET") {
      return Promise.resolve(new Response(JSON.stringify(household), { status: 200, headers: { "Content-Type": "application/json" } }));
    }
    return api(input, init);
  });
}

/**
 * The From field's HTML, with React's generated ids numbered in the order they first appear (they count every id
 * made before in the test run, so they differ between tests while the field is the same).
 */
function signerHtml(dialog: HTMLElement): string {
  let html = (dialog.querySelector("[data-signer]") as HTMLElement).outerHTML;
  const ids = [...html.matchAll(/\sid="([^"]+)"/g)].map((m) => m[1]!);
  ids.forEach((id, i) => {
    html = html.split(id).join(`id${i + 1}`);
  });
  return html;
}

/** The composer for an objection to the tax assessment, addressed (here) to Alex Rivera; the From field as it opens. */
async function openObjection() {
  ADDRESSEES.doc_tax = "Alex Rivera";
  const user = userEvent.setup();
  renderWithProviders(<LettersPage />, { route: "/letters?kind=objection&doc=doc_tax" });
  const dialog = await screen.findByRole("dialog", { name: "New letter" });
  const from = await within(dialog).findByRole("textbox", { name: "From" });
  return { user, dialog, from };
}

describe("the From field of a letter not filed for someone of the household", () => {
  const cases: [string, Household | null][] = [
    ["no household", null],
    ["a household, the letter not answered (its addressee suggests Alex Rivera)", { members: [ALEX], filed: {}, mine: [], suggested: { doc_tax: ALEX.id }, version: "0123456789abcdef" }],
    ["a household, the letter filed as the person's own", { members: [ALEX], filed: {}, mine: ["doc_tax"], suggested: {}, version: "0123456789abcdef" }],
  ];

  it.each(cases)("is byte-identical to the base: %s", async (_name, household) => {
    useMockApi({ full: true });
    if (household) answerHousehold(household);
    const { user, dialog, from } = await openObjection();
    expect(from).toHaveValue("Sam Rivera");
    expect(signerHtml(dialog)).toMatchInlineSnapshot(`"<div class="mt-4" data-signer="true"><div class="flex flex-col gap-1.5"><label for="id1" class="text-sm font-medium text-ink">From</label><input class="w-full rounded-lg border border-control-border bg-surface px-3 text-base text-ink shadow-[inset_0_1px_1px_rgb(0_0_0/0.03)] placeholder:text-muted transition-[border-color,box-shadow] hover:border-muted focus-within:border-accent focus-within:outline-none focus-within:ring-3 focus-within:ring-accent/20 disabled:cursor-not-allowed disabled:opacity-60 aria-invalid:border-danger aria-invalid:focus-within:ring-danger/25 aria-invalid:focus-within:outline-2 aria-invalid:focus-within:outline-offset-1 aria-invalid:focus-within:outline-solid aria-invalid:focus-within:outline-danger h-9" maxlength="120" autocomplete="off" spellcheck="false" id="id1" aria-describedby="id1-hint" value="Sam Rivera"><p id="id1-hint" class="text-sm leading-5 text-muted"><span class="[overflow-wrap:anywhere]">This letter was addressed to Alex Rivera.</span></p></div><div class="mt-2 flex flex-wrap gap-2"><button type="button" class="relative inline-flex shrink-0 select-none items-center justify-center gap-2 rounded-lg font-medium transition-[background-color,border-color,color,box-shadow,transform] duration-150 ease-out active:translate-y-px disabled:pointer-events-none aria-disabled:pointer-events-none inactive:text-faint inactive:shadow-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent border border-line-strong/80 bg-surface text-ink shadow-[var(--shadow-card)] hover:border-line-strong hover:bg-surface-2 inactive:border-transparent inactive:bg-surface-3 px-3 text-[13px] [&amp;_svg]:size-3.5 h-auto min-h-8 max-w-full whitespace-normal py-1 text-left"><span class="min-w-0 whitespace-normal [overflow-wrap:anywhere]">Reply in Alex Rivera's name</span></button></div><p role="status" class="sr-only"></p></div>"`);

    await user.click(within(dialog).getByRole("button", { name: "Reply in Alex Rivera's name" }));
    expect(from).toHaveValue("Alex Rivera");
    expect(signerHtml(dialog)).toMatchInlineSnapshot(`"<div class="mt-4" data-signer="true"><div class="flex flex-col gap-1.5"><label for="id1" class="text-sm font-medium text-ink">From</label><input class="w-full rounded-lg border border-control-border bg-surface px-3 text-base text-ink shadow-[inset_0_1px_1px_rgb(0_0_0/0.03)] placeholder:text-muted transition-[border-color,box-shadow] hover:border-muted focus-within:border-accent focus-within:outline-none focus-within:ring-3 focus-within:ring-accent/20 disabled:cursor-not-allowed disabled:opacity-60 aria-invalid:border-danger aria-invalid:focus-within:ring-danger/25 aria-invalid:focus-within:outline-2 aria-invalid:focus-within:outline-offset-1 aria-invalid:focus-within:outline-solid aria-invalid:focus-within:outline-danger h-9" maxlength="120" autocomplete="off" spellcheck="false" id="id1" aria-describedby="id1-hint" value="Alex Rivera"><p id="id1-hint" class="text-sm leading-5 text-muted"><span class="[overflow-wrap:anywhere]">This letter was addressed to Alex Rivera. It goes out in the name of Alex Rivera, who signs it.</span></p></div><div class="mt-2 flex flex-wrap gap-2"><button type="button" class="relative inline-flex shrink-0 select-none items-center justify-center gap-2 whitespace-nowrap rounded-lg font-medium transition-[background-color,border-color,color,box-shadow,transform] duration-150 ease-out active:translate-y-px disabled:pointer-events-none aria-disabled:pointer-events-none inactive:text-faint inactive:shadow-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent text-muted hover:bg-surface-3/70 hover:text-ink h-8 px-3 text-[13px] [&amp;_svg]:size-3.5"><span class="min-w-0 truncate">Use my name</span></button></div><p role="status" class="sr-only">The letter now goes out in the name of Alex Rivera.</p></div>"`);
  });
});
