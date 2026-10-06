/**
 * Audit (UI audit round 2, proof of sending):
 *
 * - The proof file page was titled by the raw file name, its breadcrumb read "Your letter" ("Back to
 *   Your letter" on phones), and the file's full name was cut short with only a tooltip (R2-proof-2).
 * - A failed load showed the server's raw message instead of the app's one failed-load card (R2-proof-3).
 * - The proof's note was a one-line field: a 200-character note was edited through a slit (R2-proof-4).
 * - The page sat in a centred column while its breadcrumb started at the page's edge (R2-proof-5).
 * - An "other" proof with a note still said "Shows: What it shows — describe it in the note" (R2-proof-6).
 * - Removing a proof from its page asked more vaguely than on the letter (R2-proof-7).
 * - A missing file wasn't marked on its field, and Escape didn't leave a tracking-number change (R2-proof-8).
 * - Privacy statements said "AI" (the app says "Claude"), "Waiting for" used the Deadline hourglass,
 *   and the page's title had its own size instead of the detail pages' one (R2-proof-9).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router";
import userEvent from "@testing-library/user-event";
import { makeTestQueryClient } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import { PageMetaProvider, usePageMeta } from "@/components/shell/page-meta";
import LetterPage from "@/pages/LetterPage";
import ProofFilePage from "@/pages/ProofFilePage";
import { plainText } from "@/lib/glue";
import { NOTED_DOES_NOT_SHOW, NOTED_SHOWS } from "@/mocks/proof";
import { proofPageTitle } from "./ProofFileView";

beforeEach(() => {
  vi.stubGlobal("scrollTo", () => {});
});
afterEach(() => {
  vi.unstubAllGlobals();
  act(() => __clearToasts());
});

const classOf = (el: Element | null | undefined) => el?.getAttribute("class") ?? "";

/** What the top bar would show: the page's title and its breadcrumb parent. */
function MetaProbe() {
  const { title, parent } = usePageMeta();
  return (
    <output data-testid="meta">
      {title} | {parent ? `${parent.label} → ${parent.to}` : "no parent"}
    </output>
  );
}

function renderAt(route: string) {
  const router = createMemoryRouter(
    [
      {
        path: "/letters/:id/proofs/:docId",
        element: (
          <PageMetaProvider>
            <ProofFilePage />
            <MetaProbe />
            <Toaster />
          </PageMetaProvider>
        ),
      },
      {
        path: "/letters/:id",
        element: (
          <>
            <LetterPage />
            <Toaster />
          </>
        ),
      },
    ],
    { initialEntries: [route] },
  );
  render(
    <QueryClientProvider client={makeTestQueryClient()}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

const PROOF_PAGE = "/letters/drf_gym/proofs/doc_gym_receipt";

describe("the proof file page (R2-proof-2, R2-proof-5, R2-proof-9)", () => {
  it("is named by its kind under 'Letter' — never by the file's name — and shows the whole file name", async () => {
    const { srv } = useMockApi();
    const long = "IMG_20260910_Einlieferungsbeleg_Einwurf-Einschreiben_FunkNetz_Kundenkuendigung_FN-88213407.jpg";
    srv.db.state.documents.find((d) => d.id === "doc_gym_receipt")!.filename = long;
    renderAt(PROOF_PAGE);
    await screen.findByRole("heading", { level: 1, name: "Posting receipt (Einlieferungsbeleg)" });
    // "Back to Letter" on phones, like "Back to Inbox"
    expect(screen.getByTestId("meta")).toHaveTextContent("Proof: Posting receipt | Letter → /letters/drf_gym");
    expect(proofPageTitle("other")).toBe("Proof: Other proof");
    // the one place the name can be read whole: it wraps (no tooltip-only name on touch screens)
    const name = screen.getByTitle(long);
    expect(plainText(name.textContent ?? "")).toBe(long);
    expect(classOf(name)).not.toMatch(/(^| )truncate( |$)/);
    expect(classOf(name)).toMatch(/\[overflow-wrap:anywhere\]/);
    // it breaks after its underscores, as between words — mid-word only when a part is wider than the line
    expect(name.querySelectorAll("wbr")).toHaveLength(long.split("_").length - 1);
  });

  it("starts under the breadcrumb (no centred column), titled at the detail pages' size, and says 'Claude'", async () => {
    useMockApi();
    renderAt(PROOF_PAGE);
    const h1 = await screen.findByRole("heading", { level: 1, name: "Posting receipt (Einlieferungsbeleg)" });
    expect(classOf(h1)).toMatch(/(^| )text-detail(-long)?( |$)/);
    expect(classOf(h1)).not.toMatch(/text-\[\d+px\]/);
    // on phones the title has the whole width, as on the letter page ("(Einlieferungsbeleg)" never breaks at 320 px)
    const icon = classOf(h1.closest("header")!.querySelector("[aria-hidden]")).split(" ");
    expect(icon).toEqual(expect.arrayContaining(["hidden", "sm:grid"]));
    const column = h1.closest("header")!.parentElement!;
    expect(classOf(column)).toMatch(/(^| )max-w-3xl( |$)/);
    expect(classOf(column)).not.toMatch(/(^| )mx-auto( |$)/);
    expect(screen.getByText("Kept private — never sent to Claude.")).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent(/\bto AI\b/);
  });

  it("opens with a skeleton in the same column", () => {
    useMockApi();
    renderAt(PROOF_PAGE);
    const busy = document.querySelector("[aria-busy='true']")!;
    expect(busy).toHaveTextContent("Opening the proof…");
    // its heading is a stand-in: focus waits for the proof's own (Layout's PageAnnouncer)
    expect(within(busy as HTMLElement).getByRole("heading", { level: 1, name: "Proof" })).toHaveAttribute("data-loading");
    expect(classOf(busy)).toMatch(/(^| )max-w-3xl( |$)/);
    expect(classOf(busy)).not.toMatch(/(^| )mx-auto( |$)/);
  });
});

describe("a proof that can't be loaded (R2-proof-3)", () => {
  it("says so like every other page: the calm sentence, Try again, technical details — and the way back", async () => {
    useMockApi();
    const mocked = globalThis.fetch;
    let failing = true;
    vi.stubGlobal("fetch", (input: RequestInfo | URL, init?: RequestInit) =>
      failing && String(input).includes("/documents/doc_gym_receipt")
        ? Promise.resolve(new Response(JSON.stringify({ detail: "Something went wrong (UI audit)" }), { status: 500, headers: { "Content-Type": "application/json" } }))
        : mocked(input, init),
    );
    const user = userEvent.setup();
    renderAt(PROOF_PAGE);
    const alert = await screen.findByRole("alert", {}, { timeout: 5000 });
    expect(within(alert).getByRole("heading", { level: 1, name: "Couldn't open this proof" })).toBeInTheDocument();
    expect(alert).toHaveTextContent("Your letters are safe — Ordnung ran into a problem while loading this page.");
    // the server's words only under "Technical details", never as the sentence
    expect(within(alert).getByText("Technical details")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to the letter" })).toHaveAttribute("href", "/letters/drf_gym");
    failing = false;
    await user.click(within(alert).getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Posting receipt (Einlieferungsbeleg)" })).toBeInTheDocument();
  });
});

describe("removing a proof from its page (R2-proof-7)", () => {
  it("asks like the letter's proof card does: which proof, which file, for good — and offers to download it first", async () => {
    useMockApi();
    const user = userEvent.setup();
    renderAt(PROOF_PAGE);
    await user.click(await screen.findByRole("button", { name: "Remove this proof" }));
    const dialog = await screen.findByRole("dialog", { name: "Remove the posting receipt (Einlieferungsbeleg)?" });
    expect(dialog).toHaveAccessibleDescription("“Einlieferungsbeleg_FitWell.jpg” is deleted from Ordnung for good — this can't be undone.");
    expect(within(dialog).getByRole("link", { name: "download it first" })).toHaveAttribute("download", "Einlieferungsbeleg_FitWell.jpg");
    await user.click(within(dialog).getByRole("button", { name: "Keep it" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});

async function openLetter() {
  renderAt("/letters/drf_gym");
  return screen.findByRole("region", { name: "Proof of sending" });
}

describe("the Add proof dialog (R2-proof-4, R2-proof-8, R2-proof-9)", () => {
  it("edits the note in a few lines — a long note is read whole — and counts down near its limit", async () => {
    const { srv } = useMockApi();
    const note = "Postfiliale im Hauptbahnhof, Schalter 3 — die Mitarbeiterin hat den Umschlag gewogen und frankiert. Zeugin: meine Nachbarin Frau Kowalczyk-Hernández";
    srv.db.state.proofs[0]!.note = note;
    const user = userEvent.setup();
    const proof = await openLetter();
    await user.click(await within(proof).findByRole("button", { name: "Actions for Posting receipt (Einlieferungsbeleg)" }));
    await user.click(await screen.findByRole("menuitem", { name: "Change kind or day" }));
    const dialog = await screen.findByRole("dialog", { name: "Change this proof" });
    const field = within(dialog).getByLabelText(/^Note/);
    expect(field.tagName).toBe("TEXTAREA");
    expect(field).toHaveValue(note);
    expect(field).toHaveAttribute("rows", "2");
    // two lines when empty, growing with the note (up to about eight lines)
    expect(classOf(field).split(" ")).toEqual(expect.arrayContaining(["min-h-16", "max-h-48", "[field-sizing:content]"]));
    expect(within(dialog).queryByText(/characters? left/)).not.toBeInTheDocument();
    await user.clear(field);
    await user.click(field);
    await user.paste("x".repeat(450));
    expect(field).toHaveAccessibleDescription("50 characters left");
    await user.paste("x".repeat(53));
    expect(field).toHaveAttribute("aria-invalid", "true");
    expect(field).toHaveAccessibleDescription("Keep it under 500 characters — 3 too many.");
  });

  it("marks a missing file on its field (a red edge, and a red ring while focused) and says 'Claude'", async () => {
    useMockApi();
    const user = userEvent.setup();
    const proof = await openLetter();
    await user.click(await within(proof).findByRole("button", { name: "Add proof" }));
    const dialog = await screen.findByRole("dialog", { name: "Add proof" });
    expect(within(dialog).getByText("Kept on this computer with the letter, and never sent to Claude.")).toBeInTheDocument();
    const file = within(dialog).getByLabelText("File");
    expect(file).not.toHaveAttribute("aria-invalid");
    await user.click(within(dialog).getByRole("button", { name: "Add proof" }));
    expect(file).toHaveFocus();
    expect(file).toHaveAttribute("aria-invalid", "true");
    for (const cls of ["aria-invalid:file:border-danger", "aria-invalid:focus:outline-danger", "aria-invalid:focus:outline-2"]) expect(classOf(file).split(" ")).toContain(cls);
  });

  it("thanks with 'kept private, never sent to Claude' when a proof is added", async () => {
    useMockApi();
    const user = userEvent.setup();
    const proof = await openLetter();
    await user.click(await within(proof).findByRole("button", { name: "Add proof" }));
    const dialog = await screen.findByRole("dialog", { name: "Add proof" });
    await user.upload(within(dialog).getByLabelText("File"), new File(["%PDF-1.4"], "Auslieferungsbeleg.pdf", { type: "application/pdf" }));
    await user.click(within(dialog).getByRole("button", { name: "Add proof" }));
    expect(await screen.findByText("Delivery record (Auslieferungsbeleg) — kept private, never sent to Claude.")).toBeInTheDocument();
  });
});

describe("the proof card (R2-proof-6, R2-proof-8, R2-proof-9)", () => {
  it("says an 'other' proof shows what its note says — the request for a note only while there is none", async () => {
    const { srv } = useMockApi();
    const other = srv.db.state.proofs[0]!;
    other.kind = "other";
    other.note = "Kopie des Briefes mit Unterschrift, eingescannt, bevor er in den Umschlag kam";
    const proof = await openLetter();
    const list = await within(proof).findByRole("region", { name: /Your proof/ });
    await within(list).findByText("Other proof");
    expect(list).toHaveTextContent(`Shows: ${NOTED_SHOWS}`);
    expect(list).toHaveTextContent(`Doesn't show: ${NOTED_DOES_NOT_SHOW}`);
    expect(list).not.toHaveTextContent(/describe it in the note|say what it shows/);
  });

  it("asks for a note on an 'other' proof without one", async () => {
    const { srv } = useMockApi();
    const other = srv.db.state.proofs[0]!;
    other.kind = "other";
    other.note = null;
    const proof = await openLetter();
    const list = await within(proof).findByRole("region", { name: /Your proof/ });
    expect(await within(list).findByText("What it shows — describe it in the note.")).toBeInTheDocument();
  });

  it("leaves a tracking-number change with Escape, like Cancel, and returns to 'Change'", async () => {
    const { calls } = useMockApi();
    const user = userEvent.setup();
    const proof = await openLetter();
    await user.click(await within(proof).findByRole("button", { name: /^Change$/ }));
    const field = within(proof).getByRole("textbox", { name: "Tracking number" });
    await waitFor(() => expect(field).toHaveFocus());
    await user.type(field, "{Backspace}{Backspace}");
    await user.keyboard("{Escape}");
    const change = await within(proof).findByRole("button", { name: /^Change$/ });
    await waitFor(() => expect(change).toHaveFocus());
    expect(within(proof).getByText("RT 123 456 785 DE")).toBeInTheDocument();
    expect(calls.some((c) => c.method !== "GET" && c.path.includes("/tracking"))).toBe(false);
  });

  it("marks what the letter waits for with the Waiting-for icon — the hourglass is for deadlines", async () => {
    useMockApi();
    const proof = await openLetter();
    const title = await within(proof).findByText("Waiting for a written confirmation of the end date");
    const box = title.closest("#proof-waiting")!;
    expect(classOf(box.querySelector("svg"))).toMatch(/lucide-mail-question-mark/);
    expect(box.querySelector("svg.lucide-hourglass")).toBeNull();
  });
});
