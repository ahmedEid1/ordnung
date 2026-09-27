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
import { TrackingField } from "./TrackingField";
import { nachweisFileName, proofKindsFor, suggestedKind, takesTrackingNumber, waitingTitle } from "./proof";

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

  it("asks for a tracking number only for letters by post", () => {
    expect(takesTrackingNumber("registered_letter")).toBe(true);
    expect(takesTrackingNumber("letter")).toBe(true);
    expect(takesTrackingNumber("email")).toBe(false);
    expect(takesTrackingNumber(null)).toBe(false);
  });

  it("names the Nachweis after the recipient and the sending day", () => {
    const d = { kind: "cancellation", recipient_block: "FitWell Studios GmbH\nMitgliederservice", sent_at: "2026-09-22T12:00:00Z", created_at: "2026-09-20T10:00:00Z" } as Pick<
      Draft,
      "kind" | "recipient_block" | "sent_at" | "created_at"
    >;
    expect(nachweisFileName(d)).toBe("nachweis-FitWell-Studios-GmbH-2026-09-22.pdf");
    expect(nachweisFileName({ ...d, recipient_block: "Bürgeramt Süd", sent_at: null })).toBe("nachweis-Burgeramt-Sud-2026-09-20.pdf");
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
    expect(within(dialog).getByRole("button", { name: "Mark as sent" })).toBeDisabled();
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
    expect(within(timeline).getByText("Tracking number RT 123 456 785 DE")).toBeInTheDocument();
    // never claims it is enough
    expect(within(proof).getByText(/Whether a proof is enough is for a court to decide/)).toBeInTheDocument();
    expect(proof).not.toHaveTextContent(/legally (sufficient|valid)|court-proof|guaranteed/i);
    // the Nachweis
    const nachweis = within(proof).getByRole("link", { name: /Download Nachweis/ });
    expect(nachweis).toHaveAttribute("download", "nachweis-FitWell-Studios-2026-09-22.pdf");
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
    expect(within(dialog).getByRole("button", { name: "Add proof" })).toBeDisabled();
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
    expect(await within(proof).findByText(/Nothing added yet/)).toBeInTheDocument();
  });

  it("saves, refuses and removes the tracking number", async () => {
    const { calls } = useMockApi();
    const user = userEvent.setup();
    renderLetter("/letters/drf_gym");
    const proof = await screen.findByRole("region", { name: "Proof of sending" });
    await user.click(await within(proof).findByRole("button", { name: "Remove" }));
    await waitFor(() => expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ tracking_number: null }));
    const field = await within(proof).findByLabelText("Tracking number");
    await user.type(field, "RT 000 000 001 DE");
    expect(within(proof).getByRole("button", { name: "Save number" })).toBeDisabled();
    await user.clear(field);
    await user.type(field, "rt 123 456 785 de");
    await user.click(within(proof).getByRole("button", { name: "Save number" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "PUT").at(-1)?.body).toEqual({ tracking_number: "rt 123 456 785 de" }));
    expect(await within(proof).findByText("RT 123 456 785 DE")).toBeInTheDocument();
    expect(await screen.findByText("Tracking number saved")).toBeInTheDocument();
  });

  it("isn't shown on a letter that hasn't been sent", async () => {
    useMockApi();
    renderLetter("/letters/drf_phone");
    expect(await screen.findByRole("heading", { level: 1 })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Proof of sending" })).not.toBeInTheDocument();
  });
});
