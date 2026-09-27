/**
 * Top 3 this week (UI audit round 1, today-a): the Pay panel's transfer details and its always
 * visible actions, one urgency scale for the pill and the card edge, verbs that say where they go,
 * the reason's "Read more", and where focus goes when a card leaves (paid) or comes back (Undo).
 * jsdom has no layout; e2e/today-layout.spec.ts checks the real one.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import { formatIban } from "@/lib/format";
import { renderWithProviders } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import { item } from "@/mocks/data/helpers";
import { receiptForItem } from "./receipt";
import { TodayView } from "./TodayView";
import { actionTone, amountForTransfer, verbFor, verbLabel } from "./TopThree";

beforeEach(() => {
  vi.stubGlobal("scrollTo", () => {});
});
afterEach(() => {
  vi.unstubAllGlobals();
  act(() => __clearToasts());
});

/** Today on the in-memory mock API (call `useMockApi()` first). */
async function renderToday() {
  const user = userEvent.setup();
  renderWithProviders(
    <>
      <TodayView />
      <Toaster />
    </>,
  );
  const top = await screen.findByRole("region", { name: "Top 3 this week" });
  await within(top).findAllByRole("article");
  return { user, top };
}

describe("verbs and labels", () => {
  it("names the button's target and never says the verb twice", () => {
    expect(verbLabel("Pay", "Pay TechMarkt reminder")).toBe("Pay: TechMarkt reminder");
    expect(verbLabel("Pay", "Rundfunkbeitrag Q4")).toBe("Pay: Rundfunkbeitrag Q4");
    expect(verbLabel("Check", "Pay the parking fine")).toBe("Check: Pay the parking fine");
    expect(verbLabel("Draft letter", "Cancel phone contract")).toBe("Draft letter: Cancel phone contract");
    expect(verbFor({ verb: "open", docId: "doc_1", contractId: null }).label).toBe("Open letter");
    expect(verbFor({ verb: "open", docId: null, contractId: "ctr_1" }).label).toBe("Open contract");
    expect(verbFor({ verb: "open", docId: null, contractId: null }).label).toBe("Open in Timeline");
    expect(verbFor({ verb: "pay", docId: "doc_1", contractId: null }).label).toBe("Pay");
  });

  it("the date receipt says 'Transfer by' for money you send, 'Send by' for a letter", () => {
    const transfer = item({ id: "itm_t", kind: "payment", title: "Pay the fee", amount: 30, due_date: "2026-10-02", send_by: "2026-09-30" });
    const letter = item({ id: "itm_l", kind: "deadline", title: "Object", due_date: "2026-10-14", send_by: "2026-10-08" });
    expect(receiptForItem(transfer).sendByLabel).toBe("Transfer by");
    expect(receiptForItem(letter).sendByLabel).toBe("Send by");
  });

  it("copies an amount the way a German banking app takes it", () => {
    expect(amountForTransfer(94.99)).toBe("94,99");
    expect(amountForTransfer(1234.5)).toBe("1234,50");
    expect(amountForTransfer(30)).toBe("30,00");
  });
});

describe("one urgency scale for the pill and the card's edge", () => {
  it("colours the edge like the countdown (a direct debit never turns red)", () => {
    const today = "2026-09-28";
    expect(actionTone({ actionDate: "2026-09-29", dateRole: "transfer_by" }, today).level).toBe("danger");
    expect(actionTone({ actionDate: "2026-09-29", dateRole: "collected" }, today).level).toBe("warn");
    expect(actionTone({ actionDate: "2026-10-01", dateRole: "pay_by" }, today).level).toBe("warn");
    expect(actionTone({ actionDate: "2026-10-01", dateRole: "on" }, today).level).toBe("warn");
    expect(actionTone({ actionDate: "2026-10-20", dateRole: "send_by" }, today).level).toBe("ink");
  });

  it("every card's edge matches its pill, and the pill starts with a capital", async () => {
    useMockApi();
    const { top } = await renderToday();
    const STRIPE = { danger: "bg-danger", warn: "bg-warn", ink: "bg-line-strong", muted: "bg-line" } as const;
    const levels: string[] = [];
    for (const card of within(top).getAllByRole("article")) {
      const pill = card.querySelector("time")!;
      const level = pill.dataset.urgency as keyof typeof STRIPE;
      levels.push(level);
      expect(card.dataset.urgency).toBe(level);
      expect(card.querySelector("[data-part=stripe]")!.classList).toContain(STRIPE[level]);
      expect(pill.textContent).toMatch(/^[A-Z]/);
    }
    expect(levels).toContain("danger");
    // the first card leads with an accent edge (a shadow alone vanishes in dark mode)
    expect(within(top).getAllByRole("article")[0]!.className).toMatch(/border-accent/);
  });

  it("puts the rank in the corner, clear of the date pill", async () => {
    useMockApi();
    const { top } = await renderToday();
    within(top)
      .getAllByRole("article")
      .forEach((card, i) => {
        const rank = card.querySelector("[data-part=rank]")!;
        expect(rank).toHaveTextContent(String(i + 1));
        expect(rank.className).toMatch(/\babsolute\b/);
        expect(rank.className).toMatch(/\btext-faint\b/);
      });
  });
});

describe("the Pay panel", () => {
  it("shows every transfer detail in full, in valid list markup, with actions that stay in view", async () => {
    useMockApi();
    const { top, user } = await renderToday();
    await user.click(within(top).getByRole("button", { name: "Pay: TechMarkt reminder" }));
    const panel = await screen.findByRole("dialog", { name: "Pay: TechMarkt reminder" });
    const list = (await within(panel).findAllByRole("term"))[0]!.closest("dl")!;

    // dl > div > (dt, dd, dd): the copy button sits in its own <dd> (axe definition-list / dlitem)
    for (const row of Array.from(list.children)) {
      expect(row.tagName).toBe("DIV");
      expect(Array.from(row.children).map((c) => c.tagName)).toEqual(["DT", "DD", "DD"]);
    }
    const value = (label: string) => within(list).getByText(label).nextElementSibling!;
    expect(value("IBAN")).toHaveTextContent(formatIban("DE72860555920090123456"));
    expect(value("Reference")).toHaveTextContent("RE-2026-084213");
    // identifiers wrap, they are never cut
    expect(list.querySelector(".truncate")).toBeNull();
    for (const dt of within(list).getAllByRole("term")) expect(dt.className).toContain("text-xs");

    // (user-event puts its own clipboard in place)
    await user.click(within(list).getByRole("button", { name: "Copy Amount" }));
    expect(await navigator.clipboard.readText()).toBe("94,99");
    await user.click(within(list).getByRole("button", { name: "Copy IBAN" }));
    expect(await navigator.clipboard.readText()).toBe("DE72860555920090123456");

    expect(within(panel).getByText("The IBAN's check digits are valid — that only rules out typos, not fraud.")).toBeInTheDocument();
    expect(within(panel).queryByText(/No warning does not mean/)).toBeNull();
    // the actions are a sticky footer: never scrolled out of a short panel
    const footer = within(panel).getByRole("button", { name: "Mark as paid" }).parentElement!;
    expect(footer.className).toMatch(/\bsticky\b/);
    expect(within(footer).getByRole("button", { name: "Open letter" })).toBeInTheDocument();
  });

  it("marking it paid moves focus to the card now in its place; Undo brings the card back and focuses it", async () => {
    useMockApi();
    const { top, user } = await renderToday();
    await user.click(within(top).getByRole("button", { name: "Pay: TechMarkt reminder" }));
    const panel = await screen.findByRole("dialog", { name: "Pay: TechMarkt reminder" });
    await user.click(within(panel).getByRole("button", { name: "Mark as paid" }));

    await waitFor(() => expect(within(top).queryByRole("heading", { name: "Pay TechMarkt reminder" })).toBeNull());
    await waitFor(() => expect(document.activeElement?.tagName).toBe("H3"));
    // the card that moved up into second place, not <body>
    expect(document.activeElement).toBe(within(top).getAllByRole("heading", { level: 3 })[1]);

    await user.click(await screen.findByRole("button", { name: "Undo" }));
    await waitFor(() => expect(document.activeElement).toBe(within(top).getByRole("heading", { name: "Pay TechMarkt reminder" })));
  });

  it("says it's paid and moves focus on even when the card leaves before every list is refreshed (review round 4: a slow refresh lost both)", async () => {
    useMockApi();
    // the letter's details are refreshed last: the card leaves with the refreshed Top 3, before the mark-as-paid
    // call is done — its own callbacks never ran in a card that had gone (a flaky e2e run on a busy machine)
    const answer = globalThis.fetch;
    let release = () => undefined as void;
    const held = new Promise<void>((resolve) => (release = resolve));
    let marked = false;
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if ((init?.method ?? "GET").toUpperCase() === "PATCH") marked = true;
      else if (marked && url.includes("/documents/")) await held;
      return answer(input, init);
    });
    const { top, user } = await renderToday();
    await user.click(within(top).getByRole("button", { name: "Pay: TechMarkt reminder" }));
    const panel = await screen.findByRole("dialog", { name: "Pay: TechMarkt reminder" });
    await user.click(within(panel).getByRole("button", { name: "Mark as paid" }));

    await waitFor(() => expect(within(top).queryByRole("heading", { name: "Pay TechMarkt reminder" })).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(within(top).getAllByRole("heading", { level: 3 })[1]));
    release();
    expect(await screen.findByText("Marked as paid")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Undo" })).toBeInTheDocument();
  });
});

describe("the reason", () => {
  it("offers Read more only when the text is really cut, and says whether it is open", async () => {
    const observers: (() => void)[] = [];
    vi.stubGlobal(
      "ResizeObserver",
      class {
        constructor(private cb: () => void) {}
        observe() {
          observers.push(this.cb);
          this.cb();
        }
        unobserve() {}
        disconnect() {}
      },
    );
    // the second card's reason is cut at four lines; the others fit
    const height = vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockImplementation(function (this: HTMLElement) {
      return this.closest("article")?.textContent?.includes("TechMarkt reminder") ? 120 : 40;
    });
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(80);
    try {
      useMockApi();
      const { top, user } = await renderToday();
      const cards = within(top).getAllByRole("article");
      const more = within(cards[1]!).getByRole("button", { name: "Read more" });
      expect(more).toHaveAttribute("aria-expanded", "false");
      expect(within(cards[0]!).queryByRole("button", { name: "Read more" })).toBeNull();
      const reason = document.getElementById(more.getAttribute("aria-controls")!)!;
      expect(reason.className).toContain("line-clamp-4");
      await user.click(more);
      expect(within(cards[1]!).getByRole("button", { name: "Show less" })).toHaveAttribute("aria-expanded", "true");
      expect(reason.className).not.toContain("line-clamp");
    } finally {
      height.mockRestore();
      vi.restoreAllMocks();
    }
  });
});
