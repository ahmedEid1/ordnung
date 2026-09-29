/**
 * Audit (UI audit round 2, letters): the Letters page, the New-letter composer and the letter page.
 *
 * - The composer on a phone left under half its sheet for the choices: a pinned three-line
 *   description and a footer with the reason line over two stacked buttons.
 * - Its contract picker counted down in red to the "send by" of contracts that can be cancelled any
 *   month, and broke references at their hyphens ("TM- / 2026-0048213").
 * - The same deadline read "send by" here and "Send by" on Contracts, This week and Today.
 * - An empty Letters page led with a "Waiting for" button to another empty page; with letters, its
 *   whole count turned red when one of four was overdue.
 * - The deposit letter's link to Settings opened a new tab without saying so on screen.
 * - Section labels, the letter's title and the Waiting-for icon differed from the rest of the app.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router";
import { render } from "@testing-library/react";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import { makeTestQueryClient, renderWithProviders } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import LetterPage from "@/pages/LetterPage";
import LettersPage from "@/pages/LettersPage";
import { NB_HYPHEN } from "@/lib/glue";
import { CONTRACTS } from "@/mocks/data/contracts";
import { isRollingContract } from "@/features/contracts/model";
import { cancellableContracts } from "./logic";

beforeEach(() => {
  vi.stubGlobal("scrollTo", () => {});
});
afterEach(() => {
  vi.unstubAllGlobals();
  act(() => __clearToasts());
});

/** An install with nothing in it yet: every list is empty. */
function stubEmptyInstall() {
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    const path = new URL(String(input instanceof Request ? input.url : input), "http://localhost").pathname;
    const body = /\/profile$/.test(path) ? {} : [];
    return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
  });
}

const classOf = (el: Element | null | undefined) => el?.getAttribute("class") ?? "";

describe("composer on a phone (R2-letters-1)", () => {
  it("pins only the title: the description scrolls with the form, and screen readers hear it once", async () => {
    useMockApi();
    renderWithProviders(<LettersPage />, { route: "/letters?kind=payment_plan&doc=doc_tm_dunning" });
    const dialog = await screen.findByRole("dialog", { name: "New letter" });
    expect(dialog).toHaveAccessibleDescription(/The legal sentences come from fixed templates/);
    const header = document.getElementById(dialog.getAttribute("aria-describedby")!)!;
    expect(classOf(header.firstElementChild)).toMatch(/(^| )max-sm:sr-only( |$)/);
    const copy = dialog.querySelector("[data-composer-about]")!;
    expect(copy).toHaveTextContent(/The legal sentences come from fixed templates/);
    expect(copy).toHaveAttribute("aria-hidden", "true");
    expect(classOf(copy)).toMatch(/(^| )sm:hidden( |$)/);
  });

  it("puts Cancel and 'Write the letter' side by side, 44 px tall, under a reason of at most two lines", async () => {
    useMockApi();
    renderWithProviders(<LettersPage />, { route: "/letters?kind=payment_plan&doc=doc_tm_dunning" });
    const dialog = await screen.findByRole("dialog", { name: "New letter" });
    const write = await within(dialog).findByRole("button", { name: /Write the letter/ });
    const cancel = within(dialog).getByRole("button", { name: "Cancel" });
    const actions = dialog.querySelector("[data-composer-actions]")!;
    expect(actions).toContainElement(write);
    expect(actions).toContainElement(cancel);
    // a row on phones (Cancel as wide as its word), the footer's own row from 640 px
    expect(classOf(actions)).toMatch(/grid-cols-\[auto_minmax\(0,1fr\)\]/);
    expect(classOf(actions)).toMatch(/(^| )sm:contents( |$)/);
    for (const b of [cancel, write]) expect(classOf(b)).toMatch(/(^| )max-sm:h-11( |$)/);
    // the reason is whole in the page (and for the disabled button); on a phone two lines at most
    await waitFor(() => expect(write).toHaveAccessibleDescription("Still needed: the monthly instalment and the day of the first instalment."));
    const why = dialog.querySelector("#cmp-why")!;
    expect(classOf(why)).toMatch(/(^| )max-sm:line-clamp-2( |$)/);
    expect(why).toHaveAttribute("title", "Still needed: the monthly instalment and the day of the first instalment.");
  });
});

describe("composer's contract picker (R2-letters-2, R2-letters-5)", () => {
  it("never counts down to a contract you can cancel any month; a term's send-by starts with a capital", async () => {
    const { srv } = useMockApi();
    // the demo's health insurance and rent: cancellable any month, with a "send by" that only says when it would end
    const ticket = srv.db.state.contracts.find((c) => c.id === "ctr_dticket")!;
    // a rolling contract: a must-arrive-by day each month, no term (as the rent's)
    ticket.computed = { ...ticket.computed!, cancel_by: "2026-10-10", send_by: "2026-09-28" };
    renderWithProviders(<LettersPage />, { route: "/letters?kind=cancellation&contract=ctr_dticket" });
    const dialog = await screen.findByRole("dialog", { name: "New letter" });
    const rolling = (await within(dialog).findByRole("radio", { name: /Deutschlandticket/ })).closest("label")!;
    expect(rolling.querySelector("time")).toBeNull();
    expect(rolling).not.toHaveTextContent(/send by/i);
    // a line of its own on phones, a neutral pill from 640 px
    const said = within(rolling).getAllByText("Cancel any month");
    expect(said.map(classOf)).toEqual([expect.stringMatching(/(^| )sm:hidden( |$)/), expect.stringMatching(/(^| )hidden .*sm:inline-flex/)]);
    for (const el of said) expect(classOf(el)).not.toMatch(/danger|warn/);

    const phone = (await within(dialog).findByRole("radio", { name: /FunkNetz/ })).closest("label")!;
    const dates = phone.querySelectorAll("time[data-urgency]");
    expect(dates).toHaveLength(2);
    for (const t of dates) expect(t.textContent).toMatch(/^Send by /);
  });

  it("lists the contracts whose send-by runs out first, those you can cancel any month after them", () => {
    const phone = CONTRACTS.find((c) => c.id === "ctr_phone")!;
    const ticket = CONTRACTS.find((c) => c.id === "ctr_dticket")!;
    const anyMonth = { ...ticket, computed: { ...ticket.computed!, cancel_by: "2026-10-10", send_by: "2026-09-28" } };
    expect(isRollingContract(anyMonth)).toBe(true);
    expect(isRollingContract(phone)).toBe(false);
    expect(cancellableContracts([anyMonth, phone]).map((c) => c.id)).toEqual(["ctr_phone", "ctr_dticket"]);
  });

  it("keeps a reference whole in a letter's name; its title stays plain (R2-letters-4)", async () => {
    const { srv } = useMockApi();
    const dunning = srv.db.state.documents.find((d) => d.id === "doc_tm_dunning")!;
    dunning.title = "1st Payment Reminder (Mahnung) – Invoice TM-2026-0048213";
    renderWithProviders(<LettersPage />, { route: "/letters?kind=payment_plan&doc=doc_tm_dunning" });
    const dialog = await screen.findByRole("dialog", { name: "New letter" });
    await within(dialog).findByRole("radiogroup", { name: /Which bill or decision/ });
    const name = dialog.querySelector('input[name="letter-about"]:checked')!.closest("label")!.querySelector("span[title]")!;
    expect(name).toHaveAttribute("title", "1st Payment Reminder (Mahnung) – Invoice TM-2026-0048213");
    expect(name.textContent).toBe(`1st Payment Reminder (Mahnung) – Invoice TM${NB_HYPHEN}2026${NB_HYPHEN}0048213`);
  });
});

describe("Letters list (R2-letters-5, R2-letters-8)", () => {
  it("says 'Send by' at the start of a row's date, under the app's one section label", async () => {
    useMockApi();
    renderWithProviders(<LettersPage />, { route: "/letters" });
    const open = await screen.findByRole("region", { name: /In progress/ });
    const dated = Array.from(open.querySelectorAll("[data-draft-meta] time"));
    expect(dated.length).toBeGreaterThan(0);
    for (const t of dated) expect(t.textContent).toMatch(/^Send by /);
    // SectionHeader: 13 px, the count after it, flush with the page (no inset of its own)
    const label = within(open).getByRole("heading", { level: 2 });
    expect(label).toHaveTextContent(/^In progress\s*· \d+$/);
    expect(classOf(label)).toMatch(/text-\[13px\]/);
    expect(classOf(label.parentElement?.parentElement)).not.toMatch(/(^| )px-1( |$)/);
    expect(classOf(label)).not.toMatch(/(^| )px-1( |$)/);
  });
});

describe("the way to Waiting for (R2-letters-3, R2-letters-6, R2-letters-8)", () => {
  it("an empty install's page has no header actions: 'Write your first letter' is the one way on", async () => {
    stubEmptyInstall();
    renderWithProviders(<LettersPage />, { route: "/letters" });
    expect(await screen.findByRole("heading", { level: 2, name: "No letters yet" })).toBeInTheDocument();
    // give the waiting list time to load (it is empty too)
    await act(async () => new Promise((r) => setTimeout(r, 20)));
    expect(screen.queryByRole("link", { name: /Waiting for/ })).toBeNull();
    expect(screen.getByRole("banner").querySelector("header > div + div")).toBeNull();
  });

  it("with nothing to wait for, there is no link to an empty page — letters or not", async () => {
    useMockApi();
    const api = globalThis.fetch;
    vi.stubGlobal("fetch", (input: RequestInfo | URL, init?: RequestInit) =>
      /\/api\/waiting$/.test(String(input)) ? Promise.resolve(new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } })) : api(input, init),
    );
    renderWithProviders(<LettersPage />, { route: "/letters" });
    await screen.findByRole("region", { name: /In progress/ });
    await act(async () => new Promise((r) => setTimeout(r, 20)));
    expect(screen.queryByRole("link", { name: /Waiting for/ })).toBeNull();
    expect(screen.getByRole("button", { name: "New letter" })).toBeInTheDocument();
  });

  it("counts what is open in neutral ink and says how many are overdue beside it, in red, with its own icon", async () => {
    useMockApi();
    renderWithProviders(<LettersPage />, { route: "/letters" });
    const link = await screen.findByRole("link", { name: /Waiting for/ });
    await waitFor(() => expect(link).toHaveAccessibleName(/^Waiting for\s*4,\s*1 overdue$/));
    const badge = within(link).getByText("4");
    expect(classOf(badge)).not.toMatch(/danger/);
    const overdue = link.querySelector("[data-overdue]")!;
    expect(overdue).toHaveTextContent("1 overdue");
    expect(classOf(overdue)).toMatch(/text-danger-ink/);
    // words where there is room (not at 320–399 px, nor beside the title before 1024 px), else the red dot on
    // the count alone (it takes no room); screen readers always hear the words
    expect(classOf(overdue)).toMatch(/max-\[399px\]:sr-only/);
    expect(classOf(overdue)).toMatch(/sm:max-lg:sr-only/);
    const dot = link.querySelector("[data-overdue-dot]")!;
    expect(dot).toHaveAttribute("aria-hidden", "true");
    expect(classOf(dot)).toMatch(/(^| )absolute( |$)/);
    expect(badge.parentElement).toContainElement(dot as HTMLElement);
    // "Waiting for" is its own meaning (a letter with a question mark), not the deadline's hourglass
    expect(link.querySelector("svg")!.getAttribute("class")).toMatch(/lucide-mail-question-mark/);
  });
});

describe("the deposit letter's link to Settings (R2-letters-7)", () => {
  it("shows that it opens a new tab: the external-link icon after the words, and says so to screen readers", async () => {
    useMockApi();
    renderWithProviders(<LettersPage />, { route: "/letters?kind=deposit_return" });
    const dialog = await screen.findByRole("dialog", { name: "New letter" });
    const link = await within(dialog).findByRole("link", { name: /Settings → Profile.*opens in a new tab/ });
    expect(link).toHaveAttribute("target", "_blank");
    const icon = link.querySelector("svg")!;
    expect(icon).toHaveAttribute("aria-hidden", "true");
    expect(icon.getAttribute("class")).toMatch(/lucide-external-link/);
    // glued to the last word: the icon never starts a line of its own
    expect(link.textContent).toMatch(/Profile \(opens in a new tab, so this letter stays as it is\)⁠$/);
  });
});

function renderLetter(id: string) {
  const router = createMemoryRouter([{ path: "/letters/:id", element: <LetterPage /> }], { initialEntries: [`/letters/${id}`] });
  return render(
    <QueryClientProvider client={makeTestQueryClient()}>
      <RouterProvider router={router} />
      <Toaster />
    </QueryClientProvider>,
  );
}

describe("the letter page (R2-letters-8)", () => {
  it("titles the letter at the detail pages' size and labels the print preview and the sending facts like the rest of the app", async () => {
    useMockApi();
    renderLetter("drf_phone");
    const title = await screen.findByRole("heading", { level: 1, name: /FunkNetz/ });
    expect(classOf(title)).toMatch(/(^| )text-detail(-long)?( |$)/);
    expect(classOf(title)).not.toMatch(/text-\[\d+px\]/);
    const preview = await screen.findByRole("heading", { level: 2, name: "Print preview" });
    expect(classOf(preview)).toMatch(/text-\[13px\]/);
    expect(classOf(preview.parentElement?.parentElement)).not.toMatch(/(^| )px-1( |$)/);
    // the labels inside the sending card: the one in-card label style
    const send = screen.getByRole("region", { name: "How to send it" });
    for (const name of ["Form", /Ways to send it/]) expect(classOf(within(send).getByRole("heading", { level: 3, name }))).toMatch(/(^| )eyebrow( |$)/);
    expect(classOf(within(send).getByText(/^(Send it by|Must arrive by)$/))).toMatch(/(^| )eyebrow( |$)/);
  });
});
