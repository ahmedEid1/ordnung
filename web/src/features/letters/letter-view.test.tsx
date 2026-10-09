/**
 * The letter page after the UI audit (round 1, "letters-a"): the print preview as an image, the
 * ways to send ranked in words, a way that doesn't count said as a warning, the Mark-as-sent
 * dialog's dates and ways, a sent letter that reads as sent, status actions with Undo, the notes
 * without a second disclaimer and a load error you can leave.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router";
import userEvent from "@testing-library/user-event";
import type { Draft, SendGuidance } from "@/api/types";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import { makeTestQueryClient, renderWithProviders } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import LetterPage from "@/pages/LetterPage";
import { phoneGuidance } from "@/mocks/data/drafts";
import { PdfPreview } from "./PdfPreview";
import { SendGuidancePanel } from "./SendGuidancePanel";
import { channelCounts, checksSummary, notesToShow, pdfFileName, plainText, sendChoices } from "./logic";

function renderLetter(id: string) {
  const router = createMemoryRouter(
    [
      { path: "/letters/:id", element: <LetterPage /> },
      { path: "*", element: <p>elsewhere</p> },
    ],
    { initialEntries: [`/letters/${id}`] },
  );
  return {
    router,
    ...render(
      <QueryClientProvider client={makeTestQueryClient()}>
        <RouterProvider router={router} />
        <Toaster />
      </QueryClientProvider>,
    ),
  };
}

/** A signed-paper letter: email doesn't count. */
function writtenForm(): SendGuidance {
  const g = phoneGuidance();
  return { ...g, form: "written_form", channels: g.channels.map((c) => (c.channel === "email" ? { ...c, allowed: false, recommended: false } : c)) };
}

beforeEach(() => {
  vi.stubGlobal("scrollTo", () => {});
});
afterEach(() => {
  vi.unstubAllGlobals();
  act(() => __clearToasts());
});

describe("print preview", () => {
  it("is an image of the letter (no PDF frame), the PDF a link away; the last picture stays until the new one loads", () => {
    const { container, rerender } = render(<PdfPreview src="/api/drafts/drf_x/preview.png?v=1" pdfHref="/api/drafts/drf_x/pdf?v=1" version="1" />);
    expect(container.querySelector("iframe")).toBeNull();
    const loader = container.querySelector<HTMLImageElement>("img[hidden]")!;
    expect(loader.getAttribute("src")).toBe("/api/drafts/drf_x/preview.png?v=1");
    fireEvent.load(loader);
    expect(screen.getByRole("img", { name: "Preview of the printable letter" })).toHaveAttribute("src", "/api/drafts/drf_x/preview.png?v=1");
    expect(screen.getByRole("link", { name: /Open the PDF/ })).toHaveAttribute("href", "/api/drafts/drf_x/pdf?v=1");

    // after a save: the old picture stays (dimmed) while the new one loads
    rerender(<PdfPreview src="/api/drafts/drf_x/preview.png?v=2" pdfHref="/api/drafts/drf_x/pdf?v=2" version="2" />);
    expect(screen.getByRole("img", { name: "Preview of the printable letter" })).toHaveAttribute("src", "/api/drafts/drf_x/preview.png?v=1");
    fireEvent.error(container.querySelector<HTMLImageElement>("img[hidden]")!);
    expect(screen.getByText(/The preview couldn't be drawn\. Open the PDF to see the letter\./)).toBeInTheDocument();
  });

  it("the static demo's picture has no PDF to open", () => {
    renderWithProviders(<PdfPreview src="data:image/svg+xml,<svg/>" pdfHref="data:image/svg+xml,<svg/>" version="1" />);
    expect(screen.queryByRole("link", { name: /Open the PDF/ })).toBeNull();
  });
});

describe("how to send it", () => {
  it("ranks the ways with a plain number (no count-like badge) and prints citations at 12 px", () => {
    const { container } = renderWithProviders(<SendGuidancePanel guidance={writtenForm()} />);
    const rows = container.querySelectorAll("ol > li");
    expect(rows[0]).toHaveTextContent(/^1\.\s*Cancel button in „Mein FunkNetz“/);
    expect(rows[1]).toHaveTextContent(/^2\.\s*Einwurf-Einschreiben/);
    // the way that doesn't count: no number, struck, a neutral "Not enough" badge
    expect(rows[2]).toHaveTextContent(/^Email to kuendigung@funknetz\.example\s*Not enough for this letter/);
    expect(container.querySelector(".text-\\[10px\\], .text-\\[11\\.5px\\]")).toBeNull();
    expect(screen.getByText("§ 312k BGB").className).toMatch(/text-\[12px\]/);
  });
});

describe("marking as sent", () => {
  it("a way that doesn't count is a warning, not a success — and says what to do", async () => {
    const { srv, calls } = useMockApi();
    srv.db.state.drafts.find((d) => d.id === "drf_phone")!.send_guidance = writtenForm();
    const user = userEvent.setup();
    renderLetter("drf_phone");
    await user.click(await screen.findByRole("button", { name: "Mark as sent" }));
    const dialog = await screen.findByRole("dialog", { name: "Mark as sent" });
    await user.click(within(dialog).getByRole("radio", { name: /Email to kuendigung/ }));
    expect(within(dialog).getByText(/also post a signed copy by Thu 8 Oct/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Mark as sent" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/drafts/drf_phone/sent")).toBe(true));

    const toast = (await screen.findByText("Marked as sent — this way may not count")).closest("li")!;
    expect(toast).toHaveTextContent(/also post a signed copy by Thu 8 Oct, ideally by Einschreiben, and keep the receipt/);
    expect(screen.queryByText(/^We'll remind you to check for a reply on/)).toBeNull(); // no success toast
    expect(await screen.findByText(/Sent by email on Mon 28 Sep — that may not count/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Change how it was sent" })).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "How it was sent" })).getByText(/May not count for this letter/)).toBeInTheDocument();
  });

  it("the dialog: the letter's own ways, others behind “Another way”; a day from drafting to today, shown as a weekday", async () => {
    useMockApi();
    const user = userEvent.setup();
    renderLetter("drf_phone");
    await user.click(await screen.findByRole("button", { name: "Mark as sent" }));
    const dialog = await screen.findByRole("dialog", { name: "Mark as sent" });
    expect(within(dialog).getAllByRole("radio").map((r) => r.closest("label")!.textContent)).toEqual([
      "Cancel button in „Mein FunkNetz“Recommended",
      "Email to kuendigung@funknetz.example",
      "Einwurf-Einschreiben",
    ]);
    expect(within(dialog).queryByText("Cancel button on their website")).toBeNull();
    await user.click(within(dialog).getByRole("button", { name: "Another way" }));
    expect(within(dialog).getByRole("radio", { name: /Letter by post/ })).toBeInTheDocument();

    const day = within(dialog).getByLabelText("When?");
    expect(day).toHaveAttribute("min", "2026-09-27"); // the day it was drafted
    expect(day).toHaveAttribute("max", "2026-09-28");
    expect(dialog.querySelector("[data-chosen-day]")).toHaveTextContent("Mon 28 Sep");
    fireEvent.change(day, { target: { value: "2026-01-01" } });
    expect(day).toHaveAttribute("aria-invalid", "true");
    expect(within(dialog).getByText("Choose a day from Sun 27 Sep, when you drafted it, to today.")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Mark as sent" })).toBeDisabled();
  });
});

describe("a sent letter", () => {
  it("reads as sent: plain text, 'How it was sent' folded, h2 cards, a delete that doesn't pretend to unsend", async () => {
    useMockApi();
    const user = userEvent.setup();
    renderLetter("drf_wohnbau");
    await screen.findByRole("heading", { level: 1, name: /Reply to Wohnbau/ });
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.getAllByText(/vielen Dank für die Betriebskostenabrechnung/).length).toBeGreaterThan(0);
    const how = screen.getByRole("region", { name: "How it was sent" });
    expect(within(how).getByRole("heading", { level: 2, name: "How it was sent" })).toBeInTheDocument();
    expect(within(how).getByText(/Counts for this letter/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Checks" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "More actions" }));
    expect(screen.getByRole("menuitem", { name: "Change how or when you sent it" })).toBeInTheDocument();
    await user.click(screen.getByRole("menuitem", { name: "Delete this letter" }));
    const dialog = await screen.findByRole("dialog", { name: "Delete this sent letter?" });
    expect(dialog).toHaveTextContent(/It doesn't unsend anything/);
  });

  it("“Change how or when you sent it” starts from how and when it went", async () => {
    useMockApi();
    const user = userEvent.setup();
    renderLetter("drf_wohnbau");
    await user.click(await screen.findByRole("button", { name: "More actions" }));
    await user.click(screen.getByRole("menuitem", { name: "Change how or when you sent it" }));
    const dialog = await screen.findByRole("dialog", { name: "Change how or when you sent it" });
    expect(within(dialog).getByRole("radio", { name: /Email to vermietung/ })).toBeChecked();
    expect(within(dialog).getByLabelText("When?")).toHaveValue("2026-09-15");
  });
});

describe("a letter in someone else's name", () => {
  it("labels its sender block “From”, not “From (you)”", async () => {
    const { srv } = useMockApi();
    srv.db.applyTrayDocument("doc_tax");
    const res = await srv.handle("POST", "/drafts", new URLSearchParams(), { kind: "objection", doc_id: "doc_tax", sender_name: "Alex Rivera" });
    const draft = (await res.json()) as Draft;
    const user = userEvent.setup();
    renderLetter(draft.id);
    await user.click(await screen.findByRole("button", { name: "Edit sender, recipient & date" }));
    expect(screen.getByRole("textbox", { name: "From" })).toHaveValue(draft.sender_block);
    expect(screen.queryByText("From (you)")).toBeNull();
    const notes = screen.getByText("This letter goes out in the name of Alex Rivera, so Alex Rivera signs it.");
    expect(notes.closest("li")).not.toBeNull();
  });

  it("keeps “From (you)” for a letter in your own name", async () => {
    useMockApi();
    const user = userEvent.setup();
    renderLetter("drf_phone");
    await user.click(await screen.findByRole("button", { name: "Edit sender, recipient & date" }));
    expect(screen.getByRole<HTMLTextAreaElement>("textbox", { name: "From (you)" }).value).toMatch(/^Sam Rivera\n/);
  });
});

describe("status actions", () => {
  it("“Mark as ready to send” says so, with Undo", async () => {
    const { calls } = useMockApi();
    const user = userEvent.setup();
    renderLetter("drf_phone");
    await user.click(await screen.findByRole("button", { name: "More actions" }));
    await user.click(screen.getByRole("menuitem", { name: "Mark as ready to send" }));
    const toast = (await screen.findByText("Marked as ready to send")).closest("li")!;
    expect(calls.filter((c) => c.method === "PATCH").map((c) => c.body)).toEqual([{ status: "final" }]);
    await user.click(within(toast).getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "PATCH").map((c) => c.body)).toEqual([{ status: "final" }, { status: "draft" }]));
  });

  it("leaving with changes: Discard is a quiet danger button, not a second filled one", async () => {
    useMockApi();
    const user = userEvent.setup();
    const { router } = renderLetter("drf_phone");
    await user.type(await screen.findByLabelText("Letter text (German)"), " Danke.");
    act(() => void router.navigate("/letters"));
    const dialog = await screen.findByRole("dialog", { name: "Leave without saving?" });
    const discard = within(dialog).getByRole("button", { name: "Discard changes" });
    expect(discard.className).toMatch(/text-danger-ink/);
    expect(discard.className).not.toMatch(/bg-danger(\s|$)/);
  });
});

describe("letter logic", () => {
  it("drops the disclaimer from the notes (the page shows its own), keeps the rest", () => {
    expect(notesToShow(["The demo uses fixed sentences.", "Based on the law as of 25 September 2026. Not legal advice. Not reviewed by a lawyer."])).toEqual([
      "The demo uses fixed sentences.",
    ]);
  });

  it("names a Widerspruch's PDF after it", () => {
    const base = { kind: "objection", recipient_block: "Muster BKK\nPostfach 1", created_at: "2026-09-28T08:00:00Z" } as Draft;
    expect(pdfFileName({ ...base, subject: "Widerspruch gegen den Bescheid vom 10.09.2026" })).toBe("Widerspruch-Muster-BKK-2026-09-28.pdf");
    expect(pdfFileName({ ...base, subject: "Objection (Widerspruch) against the decision of 10 September 2026" })).toMatch(/^Widerspruch-/);
    expect(pdfFileName({ ...base, subject: "Einspruch gegen den Steuerbescheid" })).toMatch(/^Einspruch-/);
    expect(pdfFileName(base)).toMatch(/^Einspruch-/);
  });

  it("plain text for API messages, a checks summary, and which ways count", () => {
    expect(plainText("Run `ordnung serve` (with Claude Code signed in).")).toBe("Run “ordnung serve” (with Claude Code signed in).");
    expect(checksSummary([{ id: "a", label: "A", ok: true, detail: null }]).text).toBe("All 1 checks passed");
    expect(checksSummary([{ id: "a", label: "A", ok: false, detail: null }, { id: "b", label: "B", ok: false, detail: null }]).text).toBe("2 things need a look");
    const g = writtenForm();
    expect(channelCounts(g, "email")).toBe(false);
    expect(channelCounts(g, "registered_letter")).toBe(true);
    expect(channelCounts(g, "fax")).toBe(false); // not named, and signed paper can't be faxed as email
    expect(sendChoices(g).filter((c) => !c.other).map((c) => c.channel)).toEqual(["online_button", "registered_letter", "email"]);
    expect(sendChoices(null).every((c) => !c.other)).toBe(true);
  });
});

describe("a letter that doesn't load", () => {
  it("is the page's h1 with details folded away, a way back, and stays while retrying", async () => {
    let calls = 0;
    vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/drafts/drf_x") && ++calls > 1) return new Promise<Response>(() => {});
      if (url.includes("/api/drafts/drf_x")) return new Response(JSON.stringify({ detail: "Internal error" }), { status: 500, headers: { "Content-Type": "application/json" } });
      return new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } });
    });
    renderLetter("drf_x");
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByRole("heading", { level: 1, name: "Couldn't open this letter" })).toBeInTheDocument();
    expect(within(alert).getByText("Technical details")).toBeInTheDocument();
    expect(within(alert).queryByText(/^Internal error$/)).toBeNull(); // not as the sentence
    expect(screen.getByRole("link", { name: "Back to Letters" })).toHaveAttribute("href", "/letters");
    fireEvent.click(within(alert).getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(within(alert).getByRole("button", { name: "Try again" })).toHaveAttribute("aria-busy", "true"));
    expect(screen.getByRole("alert")).toBe(alert);
  });
});
