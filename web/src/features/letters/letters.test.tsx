import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router";
import type { ReactElement } from "react";
import userEvent from "@testing-library/user-event";
import type { Document, Draft, SendGuidance } from "@/api/types";
import { makeTestQueryClient, renderWithProviders } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import { assertNoRawEnumsInElement } from "@/lib/copy";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import LettersPage from "@/pages/LettersPage";
import LetterPage from "@/pages/LetterPage";
import {
  changedFields,
  draftTitle,
  findPlaceholders,
  followUpDate,
  objectionCheck,
  parsePrefill,
  pdfFileName,
  rankChannels,
  sendChoices,
  sentVia,
  sortChecks,
  versioned,
} from "./logic";
import { SendGuidancePanel, instantPhrase, notEnoughPhrase } from "./SendGuidancePanel";
import { STATUTORY_OBJECTIONS } from "@/mocks/data/highStakes";

/** Render `ui` at `route` under a real `:id` route pattern (so useParams works). */
function renderAt(ui: ReactElement, pattern: string, route: string) {
  const client = makeTestQueryClient();
  const router = createMemoryRouter(
    [
      { path: pattern, element: ui },
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

const doc = (remedy: Document["remedy"], area: Document["area"] = "tax") => ({ remedy, area });

beforeEach(() => {
  vi.stubGlobal("scrollTo", () => {});
});
afterEach(() => {
  vi.unstubAllGlobals();
  act(() => __clearToasts());
});

// ------------------------------------------------------------------------------------------------
// Logic
// ------------------------------------------------------------------------------------------------

describe("composer pre-fill from the URL", () => {
  it("opens with kind + contract / doc / recipient", () => {
    expect(parsePrefill(new URLSearchParams("kind=cancellation&contract=ctr_phone"))).toEqual({ kind: "cancellation", contractId: "ctr_phone", docId: null, partyId: null });
    expect(parsePrefill(new URLSearchParams("kind=objection&doc=doc_tax"))).toMatchObject({ kind: "objection", docId: "doc_tax" });
    expect(parsePrefill(new URLSearchParams("to=pty_x"))).toMatchObject({ kind: "general_reply", partyId: "pty_x" });
    expect(parsePrefill(new URLSearchParams("contract=ctr_x"))).toMatchObject({ kind: "cancellation" });
    expect(parsePrefill(new URLSearchParams("new=1"))).toMatchObject({ kind: null });
  });

  it("stays closed without composer parameters and ignores unknown kinds", () => {
    expect(parsePrefill(new URLSearchParams(""))).toBeNull();
    expect(parsePrefill(new URLSearchParams("party=pty_x"))).toBeNull();
    expect(parsePrefill(new URLSearchParams("kind=lawsuit"))).toBeNull();
  });
});

describe("objections only where the letter allows them (SPEC §21)", () => {
  it("allows Einspruch and Widerspruch", () => {
    const e = objectionCheck(doc({ type: "einspruch", addressee: "Finanzamt", period_text: null, form_text: null, quote: null }));
    expect(e).toMatchObject({ ok: true, term: "Einspruch" });
    expect(objectionCheck(doc({ type: "widerspruch", addressee: null, period_text: null, form_text: null, quote: null }))).toMatchObject({ ok: true, term: "Widerspruch" });
  });

  it("explains why not, with advice, for missing / court / none / unclear", () => {
    const missing = objectionCheck(doc(null));
    expect(missing).toMatchObject({ ok: false, reason: "missing" });
    if (!missing.ok) {
      expect(missing.body).toMatch(/Rechtsbehelfsbelehrung/);
      expect(missing.advice[0]!.label).toMatch(/Lohnsteuerhilfe/);
    }
    expect(objectionCheck(doc({ type: "klage", addressee: null, period_text: null, form_text: null, quote: null }))).toMatchObject({ ok: false, reason: "klage" });
    expect(objectionCheck(doc({ type: "none", addressee: null, period_text: null, form_text: null, quote: null }, "home"))).toMatchObject({ ok: false, reason: "none" });
    const unclear = objectionCheck(doc({ type: "unclear", addressee: null, period_text: null, form_text: null, quote: null }, "residence"));
    expect(unclear).toMatchObject({ ok: false, reason: "unclear" });
    if (!unclear.ok) expect(unclear.advice[0]!.label).toMatch(/Studierendenwerk/);
    expect(objectionCheck(null)).toMatchObject({ ok: false, reason: "missing" });
  });
});

describe("draft helpers", () => {
  const draft = { kind: "cancellation", recipient_block: "FunkNetz Mobil GmbH\nPostfach 10 20 30", created_at: "2026-09-27T18:10:00Z" } as Draft;

  it("titles, file names and the 21-day follow-up", () => {
    expect(draftTitle(draft)).toBe("Cancellation to FunkNetz Mobil GmbH");
    expect(draftTitle({ ...draft, kind: "objection" }, "Finanzamt Musterstadt")).toBe("Objection to Finanzamt Musterstadt");
    expect(draftTitle({ ...draft, kind: "general_reply", recipient_block: "" })).toBe("Reply letter");
    expect(pdfFileName(draft)).toBe("Kuendigung-FunkNetz-Mobil-GmbH-2026-09-27.pdf");
    expect(followUpDate("2026-09-28")).toBe("2026-10-19");
    expect(followUpDate("2026-09-15T17:00:00Z")).toBe("2026-10-06");
  });

  it("versions API URLs but never data: URLs (demo mode)", () => {
    expect(versioned("/api/drafts/drf_x/pdf", "2026-09-28T10:00:00Z")).toBe("/api/drafts/drf_x/pdf?v=2026-09-28T10%3A00%3A00Z");
    expect(versioned("data:image/svg+xml,abc", "v1")).toBe("data:image/svg+xml,abc");
  });

  it("patches only what changed and spots placeholders", () => {
    const base = { subject: "A", body: "B", sender_block: "S", recipient_block: "R", place_date: "P" };
    expect(changedFields(base, { ...base, body: "B2" })).toEqual({ body: "B2" });
    expect(changedFields(base, base)).toEqual({});
    expect(findPlaceholders("Ich habe dazu folgende Frage: … und [Datum] XXX")).toEqual(["…", "[Datum]", "XXX"]);
    expect(findPlaceholders("Mit freundlichen Grüßen")).toEqual([]);
  });

  it("describes how a letter was sent in words", () => {
    expect(sentVia("registered_letter")).toBe("by Einschreiben");
    expect(sentVia("online_button")).toBe("with the online cancel button");
    expect(sentVia(null)).toBe("");
  });
});

describe("sending", () => {
  const guidance: SendGuidance = {
    send_by: "2026-10-08",
    must_arrive_by: "2026-10-14",
    form: "written_form",
    form_note: null,
    channels: [
      { channel: "email", label: "Email", allowed: false, recommended: false, note: null, citation: null },
      { channel: "letter", label: "Letter", allowed: true, recommended: false, note: null, citation: null },
      { channel: "registered_letter", label: "Einwurf-Einschreiben", allowed: true, recommended: true, note: null, citation: "§ 568 BGB" },
    ],
    tips: [],
  };

  it("says only what the letter's own ways allow: a court takes a fax and online, never an email", () => {
    const court: SendGuidance = { ...STATUTORY_OBJECTIONS.court_payment_order!.guidance, send_by: "2026-10-01", must_arrive_by: "2026-10-07" };
    expect(instantPhrase(court.channels)).toBe("online or by fax");
    expect(notEnoughPhrase(court.channels)).toBe("An email is not enough.");
    renderWithProviders(<SendGuidancePanel guidance={court} />);
    expect(screen.getByText(/online or by fax you have until then/)).toBeInTheDocument();
    expect(screen.queryByText(/fax is not enough/)).toBeNull();
    expect(screen.getByText(/An email is not enough\./)).toBeInTheDocument();
    // a tenancy notice on paper: neither an email nor a fax
    expect(notEnoughPhrase([...guidance.channels, { channel: "fax", label: "Fax", allowed: false, recommended: false, note: null, citation: null }])).toBe(
      "An email or a fax is not enough.",
    );
    expect(instantPhrase(guidance.channels)).toBeNull();
  });

  it("ranks recommended first and not-allowed last", () => {
    expect(rankChannels(guidance.channels).map((c) => c.channel)).toEqual(["registered_letter", "letter", "email"]);
  });

  it("offers the guidance's ways first; for signed paper, email stays not allowed", () => {
    const choices = sendChoices(guidance);
    expect(choices[0]).toMatchObject({ channel: "registered_letter", recommended: true, allowed: true });
    expect(choices.find((c) => c.channel === "email")).toMatchObject({ allowed: false });
    expect(choices.find((c) => c.channel === "fax")).toMatchObject({ allowed: false });
    expect(choices.find((c) => c.channel === "in_person")).toMatchObject({ allowed: true });
  });

  it("shows failed checks first", () => {
    const checks = [
      { id: "a", label: "A", ok: true, detail: null },
      { id: "b", label: "B", ok: false, detail: "fix" },
    ];
    expect(sortChecks(checks).map((c) => c.id)).toEqual(["b", "a"]);
  });
});

// ------------------------------------------------------------------------------------------------
// Pages (against the in-memory mock API)
// ------------------------------------------------------------------------------------------------

describe("Letters page", () => {
  it("lists letters in progress and sent, with human copy only", async () => {
    useMockApi();
    const { container } = renderWithProviders(<LettersPage />, { route: "/letters" });
    const inProgress = await screen.findByRole("region", { name: /In progress/ });
    expect(within(inProgress).getByText("Cancellation to FunkNetz Mobil GmbH")).toBeInTheDocument();
    expect(within(inProgress).getAllByText("Draft").length).toBeGreaterThan(0);
    const sent = screen.getByRole("region", { name: /Sent/ });
    expect(within(sent).getByText("Reply to Wohnbau Musterstadt eG")).toBeInTheDocument();
    expect(within(sent).getByText(/by email/)).toBeInTheDocument();
    expect(screen.getAllByText(/Not legal advice/).length).toBeGreaterThan(0);
    assertNoRawEnumsInElement(container);
  });

  it("blocks an objection when the letter has no instructions on how to object — and offers a reply instead", async () => {
    useMockApi({ full: true });
    const user = userEvent.setup();
    renderWithProviders(<LettersPage />, { route: "/letters?kind=objection&doc=doc_parking" });
    const dialog = await screen.findByRole("dialog", { name: "New letter" });
    expect(await within(dialog).findByText("This letter doesn't explain how to object")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: /Write the letter/ })).toBeDisabled();
    await user.click(within(dialog).getByRole("button", { name: "Reply to this letter instead" }));
    expect(within(dialog).getByRole("radio", { name: /Reply to a letter/ })).toBeChecked();
    expect(within(dialog).getByRole("button", { name: /Write the letter/ })).toBeEnabled();
  });

  it("drafts an objection against the tax assessment and opens it", async () => {
    const { calls } = useMockApi({ full: true });
    const user = userEvent.setup();
    const { router } = renderWithProviders(<LettersPage />, { route: "/letters?kind=objection&doc=doc_tax" });
    const dialog = await screen.findByRole("dialog", { name: "New letter" });
    expect(await within(dialog).findByText("Einspruch possible")).toBeInTheDocument();
    expect(dialog).toHaveTextContent(/To\s*FM\s*Finanzamt Musterstadt\s*Steuerring 10, 12345 Musterstadt/);
    await user.type(within(dialog).getByLabelText(/Your wishes/), "Laptop is for work");
    await user.click(within(dialog).getByRole("button", { name: /Write the letter/ }));
    await waitFor(() => expect(router.state.location.pathname).toMatch(/^\/letters\/drf_/));
    const post = calls.find((c) => c.method === "POST" && c.path === "/drafts");
    expect(post?.body).toMatchObject({ kind: "objection", doc_id: "doc_tax", party_id: "pty_finanzamt", instructions: "Laptop is for work", language: "de" });
  });

  it("asks to suspend enforcement only when ticked — never from the wishes", async () => {
    const { calls } = useMockApi({ full: true });
    const user = userEvent.setup();
    renderWithProviders(<LettersPage />, { route: "/letters?kind=objection&doc=doc_tax" });
    const dialog = await screen.findByRole("dialog", { name: "New letter" });
    const box = await within(dialog).findByRole("checkbox", { name: /Also ask to suspend enforcement/ });
    expect(box).not.toBeChecked();
    await user.type(within(dialog).getByLabelText(/Your wishes/), "I don't want to suspend enforcement");
    await user.click(box);
    await user.click(within(dialog).getByRole("button", { name: /Write the letter/ }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/drafts")).toBe(true));
    const post = calls.find((c) => c.method === "POST" && c.path === "/drafts");
    expect(post?.body).toMatchObject({ kind: "objection", doc_id: "doc_tax", suspend_enforcement: true });
  });

  it("pre-fills a cancellation from a contract", async () => {
    useMockApi();
    renderWithProviders(<LettersPage />, { route: "/letters?kind=cancellation&contract=ctr_phone" });
    const dialog = await screen.findByRole("dialog", { name: "New letter" });
    expect(within(dialog).getByRole("radio", { name: /Cancel a contract/ })).toBeChecked();
    expect(await within(dialog).findByRole("radio", { name: /FunkNetz Allnet L/ })).toBeChecked();
    expect(within(dialog).getByRole("button", { name: /Write the letter/ })).toBeEnabled();
  });
});

describe("Letter editor", () => {
  it("shows the German letter, its English meaning, checks and how to send it", async () => {
    useMockApi();
    const user = userEvent.setup();
    const { container } = renderAt(<LetterPage />, "/letters/:id", "/letters/drf_phone");
    expect(await screen.findByRole("heading", { level: 1, name: "Cancellation to FunkNetz Mobil GmbH" })).toBeInTheDocument();
    expect((screen.getByLabelText("Letter text (German)") as HTMLTextAreaElement).value).toContain("hiermit kündige ich meinen Mobilfunkvertrag");
    // phones: a toggle switches to the translation
    await user.click(screen.getByRole("radio", { name: "In English" }));
    expect(screen.getByText(/I hereby cancel my mobile contract/)).toBeInTheDocument();
    expect(screen.getByText(/For your understanding only/)).toBeInTheDocument();
    // checks
    expect(screen.getByText("All 8 checks passed")).toBeInTheDocument();
    // how to send it
    const send = screen.getByRole("region", { name: "How to send it" });
    expect(within(send).getByText("Send it by")).toBeInTheDocument();
    expect(within(send).getByText("Thu 8 Oct")).toBeInTheDocument();
    expect(within(send).getByText("Cancel button in „Mein FunkNetz“")).toBeInTheDocument();
    expect(within(send).getByText("§ 312k BGB")).toBeInTheDocument();
    expect(screen.getAllByText(/Not legal advice/).length).toBeGreaterThan(0);
    assertNoRawEnumsInElement(container);
  });

  it("saves only the edited fields", async () => {
    const { calls } = useMockApi();
    const user = userEvent.setup();
    renderAt(<LetterPage />, "/letters/:id", "/letters/drf_phone");
    const body = await screen.findByLabelText("Letter text (German)");
    expect(screen.getByRole("button", { name: /Saved/ })).toBeDisabled();
    await user.type(body, " Danke.");
    expect(screen.getByText(/Unsaved changes/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^Save$/ }));
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
    const patch = calls.find((c) => c.method === "PATCH")!;
    expect(patch.path).toBe("/drafts/drf_phone");
    expect(Object.keys(patch.body as object)).toEqual(["body"]);
    await waitFor(() => expect(screen.getByRole("button", { name: /Saved/ })).toBeDisabled());
  });

  it("marks a letter as sent and promises the follow-up reminder", async () => {
    const { calls } = useMockApi();
    const user = userEvent.setup();
    renderAt(
      <>
        <LetterPage />
        <Toaster />
      </>,
      "/letters/:id",
      "/letters/drf_phone",
    );
    await user.click(await screen.findByRole("button", { name: "Mark as sent" }));
    const dialog = await screen.findByRole("dialog", { name: "Mark as sent" });
    expect(within(dialog).getByRole("radio", { name: /Cancel button in „Mein FunkNetz“/ })).toBeChecked();
    await user.click(within(dialog).getByRole("radio", { name: /Einwurf-Einschreiben/ }));
    expect(within(dialog).getByText(/We'll remind you to check for a reply on Mon 19 Oct/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Mark as sent" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/drafts/drf_phone/sent")).toBe(true));
    expect(calls.find((c) => c.path === "/drafts/drf_phone/sent")?.body).toEqual({ channel: "registered_letter", date: "2026-09-28" });
    expect(await screen.findByText("We'll remind you to check for a reply on Mon 19 Oct")).toBeInTheDocument();
    expect(await screen.findByText(/Sent by Einschreiben on Mon 28 Sep/)).toBeInTheDocument();
  });

  it("shows a friendly not-found state", async () => {
    useMockApi();
    renderAt(<LetterPage />, "/letters/:id", "/letters/drf_nope");
    expect(await screen.findByText("This letter isn't here (anymore)")).toBeInTheDocument();
  });
});
