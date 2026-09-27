import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router";
import { useState, type ReactElement } from "react";
import userEvent from "@testing-library/user-event";
import type { Draft } from "@/api/types";
import { makeTestQueryClient } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import { assertNoRawEnumsInElement } from "@/lib/copy";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import LetterPage from "@/pages/LetterPage";
import DocumentPage from "@/pages/DocumentPage";
import ProofFilePage from "@/pages/ProofFilePage";
import { closeLabel } from "@/features/waiting/model";
import { TrackingField } from "./TrackingField";
import { startDay } from "./AddProofDialog";
import { hasPicture, nachweisFileName, proofKindsFor, startWith, suggestedKind, takesTrackingNumber, waitingTitle } from "./proof";

function renderLetter(route: string, extra?: ReactElement) {
  const client = makeTestQueryClient();
  const router = createMemoryRouter(
    [
      {
        path: "/letters/:id",
        element: (
          <>
            <LetterPage />
            <Toaster />
            {extra}
          </>
        ),
      },
      { path: "*", element: <p>elsewhere</p> },
    ],
    { initialEntries: [route] },
  );
  return {
    router,
    ...render(
      <QueryClientProvider client={client}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    ),
  };
}

beforeEach(() => {
  vi.stubGlobal("scrollTo", () => {});
});
afterEach(() => {
  vi.unstubAllGlobals();
  act(() => __clearToasts());
});

// ------------------------------------------------------------------------------------------------
// Helpers
// ------------------------------------------------------------------------------------------------

describe("proof helpers", () => {
  it("offers the kinds that fit the way it was sent first, then every other kind", () => {
    const post = proofKindsFor("registered_letter");
    expect(post.slice(0, 3)).toEqual(["posting_receipt", "delivery_record", "return_receipt"]);
    expect(new Set(post).size).toBe(post.length);
    expect(post).toContain("other");
    expect(proofKindsFor("fax")[0]).toBe("fax_report");
    expect(proofKindsFor(null)[0]).toBe("posting_receipt");
  });

  it("suggests the next fitting kind the letter doesn't have yet", () => {
    expect(suggestedKind("registered_letter", [])).toBe("posting_receipt");
    expect(suggestedKind("registered_letter", ["posting_receipt"])).toBe("delivery_record");
    expect(suggestedKind("online_button", ["cancel_confirmation"])).toBe("other");
    expect(suggestedKind("letter", [])).toBe("other");
  });

  it("asks for a tracking number only for registered letters — a plain letter has none", () => {
    expect(takesTrackingNumber("registered_letter")).toBe(true);
    expect(takesTrackingNumber("letter")).toBe(false);
    expect(takesTrackingNumber("email")).toBe(false);
    expect(takesTrackingNumber(null)).toBe(false);
  });

  it("names the Nachweis like the server does: its subject and the sending day", () => {
    const d = { subject: "Kündigung: FW/4711 „Flex“", sent_at: "2026-09-22T12:00:00Z", created_at: "2026-09-20T10:00:00Z" } as Pick<Draft, "subject" | "sent_at" | "created_at">;
    expect(nachweisFileName(d)).toBe("Nachweis Kündigung FW 4711 „Flex“ 2026-09-22.pdf"); // tests/test_api_proof.py: same rule
    expect(nachweisFileName({ ...d, subject: "", sent_at: null })).toBe("Nachweis Schreiben 2026-09-20.pdf");
  });

  it("starts a proof of the sending on the sending day, a delivery on no day", () => {
    expect(startDay("posting_receipt", "2026-09-10")).toBe("2026-09-10");
    expect(startDay("fax_report", "2026-09-10")).toBe("2026-09-10");
    expect(startDay("delivery_record", "2026-09-10")).toBe("");
    expect(startDay("other", "2026-09-10")).toBe("");
    expect(startDay("posting_receipt", null)).toBe("");
  });

  it("shows a picture only for photos and PDFs, and says what to add first", () => {
    expect(hasPicture({ mime: "image/jpeg" })).toBe(true);
    expect(hasPicture({ mime: "application/pdf" })).toBe(true);
    expect(hasPicture({ mime: "text/plain" })).toBe(false);
    expect(hasPicture({ mime: "message/rfc822" })).toBe(false);
    expect(startWith("registered_letter")).toBe("a photo of your posting receipt");
    expect(startWith("letter")).toBeNull();
  });

  it("closes a letter with the letter that came, or with an answer that came another way", () => {
    expect(closeLabel({ status: "answered", answered_by: { type: "document", id: "doc_1" } })).toBe("It's the answer — close this");
    expect(closeLabel({ status: "overdue", answered_by: null })).toBe("I got an answer — close this");
    expect(closeLabel({ status: "waiting", answered_by: null })).toBe("I got an answer — close this");
  });

  it("titles what a letter waits for by its status", () => {
    const title = "A written confirmation of the end date";
    expect(waitingTitle({ status: "waiting", title })).toBe("Waiting for a written confirmation of the end date");
    expect(waitingTitle({ status: "overdue", title })).toBe("Still waiting for a written confirmation of the end date");
    expect(waitingTitle({ status: "answered", title })).toBe("Did their letter bring a written confirmation of the end date?");
  });
});

// ------------------------------------------------------------------------------------------------
// The tracking field
// ------------------------------------------------------------------------------------------------

function Controlled({ initial = "" }: { initial?: string }) {
  const [value, setValue] = useState(initial);
  return <TrackingField value={value} onChange={setValue} />;
}

describe("TrackingField", () => {
  it("confirms a correct check digit as it is typed", async () => {
    const user = userEvent.setup();
    render(<Controlled />);
    const input = screen.getByLabelText("Tracking number");
    expect(screen.getByText(/As printed on your posting receipt/)).toBeInTheDocument();
    await user.type(input, "rt123456785de");
    expect(screen.getByText(/Check digit correct/)).toBeInTheDocument();
    expect(screen.getByText("RT 123 456 785 DE")).toBeInTheDocument();
    expect(input).not.toHaveAttribute("aria-invalid", "true");
  });

  it("names a wrong check digit once the number is complete — not while typing", async () => {
    const user = userEvent.setup();
    render(<Controlled />);
    const input = screen.getByLabelText("Tracking number");
    await user.type(input, "RT 123 456");
    expect(screen.queryByText(/check digit/)).not.toBeInTheDocument();
    await user.type(input, " 784 DE");
    expect(screen.getByText(/The last digit doesn't match the others/)).toBeInTheDocument();
    expect(input).toHaveAttribute("aria-invalid", "true");
  });

  it("says a short number is wrong when the field is left", async () => {
    const user = userEvent.setup();
    render(
      <>
        <Controlled />
        <button type="button">elsewhere</button>
      </>,
    );
    await user.type(screen.getByLabelText("Tracking number"), "RT1234DE");
    expect(screen.queryByText(/this one has 4 digits/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "elsewhere" }));
    expect(screen.getByText(/this one has 4 digits/)).toBeInTheDocument();
  });

  it("keeps twelve-digit numbers with a note that they can't be checked", async () => {
    const user = userEvent.setup();
    render(<Controlled />);
    await user.type(screen.getByLabelText("Tracking number"), "1234 5678 9012");
    expect(screen.getByText(/can't check this kind of number/)).toBeInTheDocument();
    expect(screen.getByLabelText("Tracking number")).not.toHaveAttribute("aria-invalid", "true");
  });
});

// ------------------------------------------------------------------------------------------------
// Mark as sent with a tracking number
// ------------------------------------------------------------------------------------------------

describe("Mark as sent by Einschreiben", () => {
  it("won't mark it sent with a mistyped number, and sends a correct one along", async () => {
    const { calls } = useMockApi();
    const user = userEvent.setup();
    renderLetter("/letters/drf_phone");
    await user.click(await screen.findByRole("button", { name: "Mark as sent" }));
    const dialog = await screen.findByRole("dialog", { name: "Mark as sent" });
    expect(within(dialog).queryByLabelText(/Tracking number/)).not.toBeInTheDocument();
    await user.click(within(dialog).getByRole("radio", { name: /Einwurf-Einschreiben/ }));
    const field = within(dialog).getByLabelText(/Tracking number/);
    await user.type(field, "RT 123 456 784 DE");
    // the button says why instead of sitting disabled: the mistake is named and the field focused
    await user.click(within(dialog).getByRole("button", { name: "Mark as sent" }));
    expect(within(dialog).getByText(/The last digit doesn't match the others/)).toBeInTheDocument();
    expect(field).toHaveFocus();
    expect(calls.some((c) => c.path === "/drafts/drf_phone/sent")).toBe(false);
    await user.clear(field);
    await user.type(field, "RT 123 456 785 DE");
    await user.click(within(dialog).getByRole("button", { name: "Mark as sent" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/drafts/drf_phone/sent")).toBe(true));
    expect(calls.find((c) => c.path === "/drafts/drf_phone/sent")?.body).toEqual({ channel: "registered_letter", date: "2026-09-28", tracking_number: "RT 123 456 785 DE" });
    // the sent letter now shows its proof, with the number saved
    const proof = await screen.findByRole("region", { name: "Proof of sending" });
    expect(await within(proof).findByText("RT 123 456 785 DE")).toBeInTheDocument();
  });
});

// ------------------------------------------------------------------------------------------------
// Proof of sending on a sent letter
// ------------------------------------------------------------------------------------------------

describe("Proof of sending", () => {
  it("shows the tracking number, the proof and what it doesn't show, what's missing, the timeline and the caveat", async () => {
    useMockApi();
    const { container } = renderLetter("/letters/drf_gym");
    const proof = await screen.findByRole("region", { name: "Proof of sending" });
    expect(await within(proof).findByText("RT 123 456 785 DE")).toBeInTheDocument();
    expect(within(proof).getByText("Check digit correct")).toBeInTheDocument();
    // the sent banner doesn't repeat the reminder the proof card gives
    expect(screen.getByText("Keep your proof of sending with it below.")).toBeInTheDocument();
    expect(screen.queryByText(/We'll remind you to check for a reply/)).not.toBeInTheDocument();
    // what it waits for
    expect(within(proof).getByText("Waiting for a written confirmation of the end date")).toBeInTheDocument();
    // the posting receipt, honestly described
    const list = within(proof).getByRole("region", { name: /Your proof/ });
    expect(within(list).getByText("Posting receipt (Einlieferungsbeleg)")).toBeInTheDocument();
    expect(within(list).getByText(/Whether it arrived, or what was in the envelope/)).toBeInTheDocument();
    expect(within(list).getByText("Einlieferungsbeleg_FitWell.jpg")).toBeInTheDocument();
    // what would make it stronger: the delivery record, with the BAG decision
    const missing = within(proof).getByRole("region", { name: "What would make it stronger" });
    expect(within(missing).getByText(/Auslieferungsbeleg/)).toBeInTheDocument();
    expect(within(missing).getByText(/BAG 2 AZR 68\/24/)).toBeInTheDocument();
    // the timeline
    const timeline = within(proof).getByRole("region", { name: "Timeline" });
    expect(within(timeline).getByText(/Sent by registered letter/)).toBeInTheDocument();
    // the server groups it with no-break spaces: it never breaks inside the number
    expect(within(timeline).getByText("Tracking number RT 123 456 785 DE").textContent).toBe("Tracking number RT\u00a0123\u00a0456\u00a0785\u00a0DE");
    // never claims it is enough — only the caveat says who decides that
    const caveat = within(proof).getByText(/Whether a proof is enough is for a court to decide/);
    expect(proof).not.toHaveTextContent(/legally (sufficient|valid)|court-proof|guaranteed/i);
    expect((proof.textContent ?? "").replace(caveat.textContent ?? "", "")).not.toMatch(/\benough\b/i);
    // the Nachweis, named like the server names it
    const nachweis = within(proof).getByRole("link", { name: /Download Nachweis/ });
    expect(nachweis.getAttribute("download")).toMatch(/^Nachweis Kündigung meiner Mitgliedschaft .* 2026-09-22\.pdf$/);
    assertNoRawEnumsInElement(container);
  });

  it("adds a proof file privately and lists it", async () => {
    const { calls, srv } = useMockApi();
    const user = userEvent.setup();
    renderLetter("/letters/drf_gym");
    const proof = await screen.findByRole("region", { name: "Proof of sending" });
    await user.click(await within(proof).findByRole("button", { name: "Add proof" }));
    const dialog = await screen.findByRole("dialog", { name: "Add proof" });
    expect(within(dialog).getByText(/never sent to AI/)).toBeInTheDocument();
    // the next fitting kind is suggested (the receipt is already there)
    expect(within(dialog).getByRole("combobox", { name: "What is it?" })).toHaveValue("delivery_record");
    expect(within(dialog).getByText(/Deutsche Post's record of the day it was delivered/)).toBeInTheDocument(); // the kind's hint
    // no file yet: the button says so (and focuses the file field) instead of sitting disabled
    await user.click(within(dialog).getByRole("button", { name: "Add proof" }));
    expect(within(dialog).getByText("Choose the photo or PDF of the proof.")).toBeInTheDocument();
    expect(within(dialog).getByLabelText("File")).toHaveFocus();
    expect(calls.some((c) => c.path === "/drafts/drf_gym/proofs")).toBe(false);
    await user.upload(within(dialog).getByLabelText("File"), new File(["%PDF-1.4"], "Auslieferungsbeleg.pdf", { type: "application/pdf" }));
    await user.type(within(dialog).getByLabelText(/Delivered on/), "2026-09-24");
    await user.click(within(dialog).getByRole("button", { name: "Add proof" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/drafts/drf_gym/proofs")).toBe(true));
    const form = calls.find((c) => c.path === "/drafts/drf_gym/proofs")?.body as FormData;
    expect(form.get("kind")).toBe("delivery_record");
    expect(form.get("on_date")).toBe("2026-09-24");
    expect(await screen.findByText("Proof added")).toBeInTheDocument();
    expect(await within(proof).findByText("Delivery record (Auslieferungsbeleg)")).toBeInTheDocument();
    expect(within(proof).getByRole("region", { name: "Timeline" })).toHaveTextContent(/Delivered — delivery record/);
    // stored as a private, outgoing proof file — never in the letters list
    const added = srv.db.state.documents.find((d) => d.filename === "Auslieferungsbeleg.pdf");
    expect(added).toMatchObject({ direction: "outgoing", source: "proof", ai_private: true });
  });

  it("removes a proof after asking", async () => {
    const { calls } = useMockApi();
    const user = userEvent.setup();
    renderLetter("/letters/drf_gym");
    const proof = await screen.findByRole("region", { name: "Proof of sending" });
    await user.click(await within(proof).findByRole("button", { name: "Actions for Posting receipt (Einlieferungsbeleg)" }));
    await user.click(await screen.findByRole("menuitem", { name: "Remove this proof" }));
    const dialog = await screen.findByRole("dialog", { name: "Remove this proof?" });
    expect(within(dialog).getByText(/deleted from Ordnung for good/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE" && c.path === "/drafts/drf_gym/proofs/prf_gym_receipt")).toBe(true));
    // never "a photo is enough": what to start with
    expect(await within(proof).findByText("Nothing added yet — start with a photo of your posting receipt.")).toBeInTheDocument();
    // its row and the menu that opened the dialog are gone: focus lands on the list's heading, not <body>
    await waitFor(() => expect(within(proof).getByRole("heading", { name: /^Your proof/ })).toHaveFocus());
  });

  it("saves, refuses and removes the tracking number", async () => {
    const { calls } = useMockApi();
    const user = userEvent.setup();
    renderLetter("/letters/drf_gym");
    const proof = await screen.findByRole("region", { name: "Proof of sending" });
    await user.click(await within(proof).findByRole("button", { name: "Remove" }));
    await waitFor(() => expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ tracking_number: null }));
    const field = await within(proof).findByLabelText("Tracking number");
    await waitFor(() => expect(field).toHaveFocus()); // not <body>
    // removed by mistake: Undo puts it back
    await user.click(await screen.findByRole("button", { name: "Undo" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "PUT").at(-1)?.body).toEqual({ tracking_number: "RT123456785DE" }));
    await waitFor(() => expect(within(proof).getByRole("button", { name: "Change" })).toHaveFocus());
    await user.click(within(proof).getByRole("button", { name: "Remove" }));
    const again = await within(proof).findByLabelText("Tracking number");
    const puts = calls.filter((c) => c.method === "PUT").length;
    await user.type(again, "RT 000 000 001 DE");
    await user.click(within(proof).getByRole("button", { name: "Save number" }));
    expect(within(proof).getByText(/The last digit doesn't match the others/)).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "PUT").length).toBe(puts);
    const field2 = within(proof).getByLabelText("Tracking number");
    await user.clear(field2);
    await user.type(field2, "rt 123 456 785 de");
    await user.click(within(proof).getByRole("button", { name: "Save number" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "PUT").at(-1)?.body).toEqual({ tracking_number: "rt 123 456 785 de" }));
    expect(await within(proof).findByText("RT 123 456 785 DE")).toBeInTheDocument();
    expect(await screen.findByText("Tracking number saved")).toBeInTheDocument();
  });

  it("closes the letter when it was answered another way — with Undo", async () => {
    const { calls } = useMockApi();
    const user = userEvent.setup();
    renderLetter("/letters/drf_gym");
    const proof = await screen.findByRole("region", { name: "Proof of sending" });
    await user.click(await within(proof).findByRole("button", { name: "I got an answer — close this" }));
    await waitFor(() => expect(calls.find((c) => c.method === "POST" && c.path === "/drafts/drf_gym/answered")?.body).toEqual({ doc_id: null }));
    expect(await within(proof).findByText(/You said it was answered on/)).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "Undo" }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE" && c.path === "/drafts/drf_gym/answered")).toBe(true));
    expect(await within(proof).findByRole("button", { name: "I got an answer — close this" })).toBeInTheDocument();
  });

  it("lists a proof without a day apart — never on the day it was added", async () => {
    const { srv } = useMockApi();
    srv.db.state.proofs[0]!.on_date = null;
    renderLetter("/letters/drf_gym");
    const proof = await screen.findByRole("region", { name: "Proof of sending" });
    const timeline = await within(proof).findByRole("region", { name: "Timeline" });
    expect(within(timeline).getByRole("heading", { name: "No day given" })).toBeInTheDocument();
    expect(within(timeline).getByText(/not placed on the timeline/)).toBeInTheDocument();
    expect(within(timeline).getAllByRole("listitem").filter((li) => /Posting receipt/.test(li.textContent ?? "")).length).toBe(1);
  });

  it("says when a receipt's day and the sending day disagree, and offers to correct the sending day", async () => {
    const { srv } = useMockApi();
    srv.db.state.proofs[0]!.on_date = "2026-09-24";
    const user = userEvent.setup();
    renderLetter("/letters/drf_gym");
    const proof = await screen.findByRole("region", { name: "Proof of sending" });
    expect(await within(proof).findByText("These days don't match")).toBeInTheDocument();
    expect(within(proof).getByText(/says Thu 24 Sep 2026, but the letter is marked as sent on Tue 22 Sep 2026/)).toBeInTheDocument();
    await user.click(within(proof).getByRole("button", { name: "Change the sending day" }));
    const dialog = await screen.findByRole("dialog", { name: "Change how or when you sent it" });
    expect(within(dialog).getByLabelText("When?")).toHaveValue("2026-09-22");
    expect(within(dialog).getByLabelText(/Tracking number/)).toHaveValue("RT 123 456 785 DE");
  });

  it("names the proof files when a sent letter is deleted, and can keep them", async () => {
    const { srv } = useMockApi();
    const user = userEvent.setup();
    renderLetter("/letters/drf_gym");
    await screen.findByRole("region", { name: "Proof of sending" });
    await user.click(screen.getByRole("button", { name: "More actions" }));
    await user.click(await screen.findByRole("menuitem", { name: "Delete this letter" }));
    const dialog = await screen.findByRole("dialog", { name: "Delete this letter?" });
    expect(dialog).not.toHaveTextContent(/not affected/);
    expect(within(dialog).getByText(/Its proof file — posting receipt — is deleted for good too/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole("checkbox", { name: /Keep the proof files/ }));
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(srv.db.state.drafts.some((d) => d.id === "drf_gym")).toBe(false));
    expect(srv.db.state.documents.find((d) => d.id === "doc_gym_receipt")).toMatchObject({ source: "upload", ai_private: true });
  });

  it("isn't shown on a letter that hasn't been sent", async () => {
    useMockApi();
    renderLetter("/letters/drf_phone");
    expect(await screen.findByRole("heading", { level: 1 })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Proof of sending" })).not.toBeInTheDocument();
  });
});

// ------------------------------------------------------------------------------------------------
// A proof file's own page
// ------------------------------------------------------------------------------------------------

describe("A proof file", () => {
  function renderAt(route: string) {
    const client = makeTestQueryClient();
    const router = createMemoryRouter(
      [
        { path: "/documents/:id", element: <DocumentPage /> },
        { path: "/letters/:id/proofs/:docId", element: <ProofFilePage /> },
        { path: "/letters/:id", element: <p>the letter</p> },
      ],
      { initialEntries: [route] },
    );
    render(
      <QueryClientProvider client={client}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );
    return router;
  }

  it("opens under its letter — never as an Inbox letter — and says what it is", async () => {
    useMockApi();
    const router = renderAt("/documents/doc_gym_receipt");
    // the Inbox's letter viewer hands it on to its letter's proof page
    await waitFor(() => expect(router.state.location.pathname).toBe("/letters/drf_gym/proofs/doc_gym_receipt"));
    expect(await screen.findByRole("heading", { level: 1, name: "Posting receipt (Einlieferungsbeleg)" })).toBeInTheDocument();
    expect(screen.getByText(/For your letter/)).toHaveTextContent("Kündigung meiner Mitgliedschaft");
    expect(screen.getByText(/Kept private — never sent to AI/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Back to the letter/ })).toHaveAttribute("href", "/letters/drf_gym");
    // none of the letter viewer's parts: no kind to change, no "what you need to do"
    expect(screen.queryByText(/What you need to do/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Change/ })).not.toBeInTheDocument();
  });

  it("removes it as a proof, after asking, and goes back to the letter", async () => {
    const { calls } = useMockApi();
    const user = userEvent.setup();
    const router = renderAt("/letters/drf_gym/proofs/doc_gym_receipt");
    await user.click(await screen.findByRole("button", { name: "Remove this proof" }));
    const dialog = await screen.findByRole("dialog", { name: "Remove this proof?" });
    await user.click(within(dialog).getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE" && c.path === "/drafts/drf_gym/proofs/prf_gym_receipt")).toBe(true));
    await waitFor(() => expect(router.state.location.pathname).toBe("/letters/drf_gym"));
  });
});
