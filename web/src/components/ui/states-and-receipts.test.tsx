import { afterEach, describe, expect, it, vi } from "vitest";
import { useState } from "react";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/render";
import { ApiError } from "@/api/client";
import { PIPELINE_STEPS } from "@/lib/copy";
import { Card, CardHeader } from "./Card";
import { DateLeaf } from "./DateLeaf";
import { ADVICE_LINKS, Disclaimer } from "./Disclaimer";
import { EmptyState } from "./EmptyState";
import { Glossary } from "./Glossary";
import { KindBadge, KindIcon, resolveKind } from "./KindBadge";
import { LoadError, technicalDetails } from "./LoadError";
import { PartyChip } from "./PartyChip";
import { Receipt, ReceiptPopover, ReceiptTrigger } from "./Receipt";
import { Stepper, chooseStepLabels, labelsFit } from "./Stepper";
import { ListChecks } from "lucide-react";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("EmptyState", () => {
  it("is an h2 under the page's h1 by default, and an h1 when it replaces the page", () => {
    const { unmount } = renderWithProviders(<EmptyState title="No letters yet" />);
    expect(screen.getByRole("heading", { level: 2, name: "No letters yet" })).toBeInTheDocument();
    unmount();
    renderWithProviders(<EmptyState headingLevel={1} illustration="search" title="This page doesn't exist" />);
    expect(screen.getByRole("heading", { level: 1, name: "This page doesn't exist" })).toBeInTheDocument();
  });

  it("draws its own badge for letters and contracts (not the all-clear check)", () => {
    const { container } = renderWithProviders(
      <>
        <EmptyState illustration="clear" title="All clear" />
        <EmptyState illustration="letter" title="No letters yet" />
        <EmptyState illustration="contract" title="No contracts yet" />
      </>,
    );
    const badges = Array.from(container.querySelectorAll("[data-badge]"));
    expect(badges.map((b) => b.getAttribute("data-badge"))).toEqual(["clear", "letter", "contract"]);
    const glyph = (i: number) => badges[i]!.innerHTML.replace(/<circle[^>]*>/, "");
    expect(glyph(1)).not.toEqual(glyph(0));
    expect(glyph(2)).not.toEqual(glyph(0));
  });

  it("gives an error a solid card (not the dashed drop-zone look) and centres its content", () => {
    renderWithProviders(
      <>
        <EmptyState illustration="error" title="Couldn't load your day" />
        <EmptyState title="Nothing here" />
      </>,
    );
    const error = screen.getByRole("heading", { name: "Couldn't load your day" }).parentElement!;
    const empty = screen.getByRole("heading", { name: "Nothing here" }).parentElement!;
    expect(error).toHaveAttribute("data-variant", "error");
    expect(error.className).toContain("card");
    expect(error.className).not.toContain("border-dashed");
    expect(empty.className).toContain("border-dashed");
    for (const box of [error, empty]) expect(box.className).toMatch(/\bjustify-center\b/);
  });
});

describe("LoadError", () => {
  it("is an alert: the error art, 'Couldn't load …', a calm sentence and Try again", async () => {
    const user = userEvent.setup();
    const retry = vi.fn();
    renderWithProviders(<LoadError what="your letters" error={new ApiError(500, "Internal error")} onRetry={retry} />);
    const alert = screen.getByRole("alert");
    expect(within(alert).getByRole("heading", { level: 2, name: "Couldn't load your letters" })).toBeInTheDocument();
    expect(alert).toHaveTextContent("Your letters are safe — Ordnung didn't answer. Is it still running?");
    // the raw server message is not the sentence: it waits behind "Technical details"
    const details = within(alert).getByText("Technical details").closest("details")!;
    expect(details).not.toHaveAttribute("open");
    expect(within(details).getByText("HTTP 500 · Internal error")).toBeInTheDocument();
    await user.click(within(alert).getByRole("button", { name: "Try again" }));
    expect(retry).toHaveBeenCalledOnce();
  });

  it("stays mounted while retrying, with a busy button", async () => {
    const user = userEvent.setup();
    function Page() {
      const [retrying, setRetrying] = useState(false);
      return <LoadError what="your day" headingLevel={1} onRetry={() => setRetrying(true)} retrying={retrying} />;
    }
    renderWithProviders(<Page />);
    const alert = screen.getByRole("alert");
    await user.click(within(alert).getByRole("button", { name: "Try again" }));
    expect(screen.getByRole("alert")).toBe(alert);
    expect(within(alert).getByRole("button", { name: /Try again/ })).toHaveAttribute("aria-busy", "true");
    expect(within(alert).getByRole("heading", { level: 1, name: "Couldn't load your day" })).toBeInTheDocument();
  });

  it("describes errors for the disclosure", () => {
    expect(technicalDetails(new ApiError(404, "Not found"))).toBe("HTTP 404 · Not found");
    expect(technicalDetails(new Error("Failed to fetch"))).toBe("Failed to fetch");
    expect(technicalDetails(undefined)).toBeNull();
  });
});

describe("Stepper", () => {
  it("fits labels by their widths: neighbours never touch, the outer ones stay inside", () => {
    expect(labelsFit(80, [48, 85, 55])).toBe(true);
    // at 320 px "Understanding" ran into "Checking"
    expect(labelsFit(50, [48, 85, 55])).toBe(false);
    expect(labelsFit(40, [48])).toBe(false);
    expect(chooseStepLabels(500, [48, 85, 55, 95, 35], [48, 85, 55, 33, 35])).toBe("full");
    expect(chooseStepLabels(400, [48, 85, 55, 95, 35], [48, 85, 55, 33, 35])).toBe("short");
    expect(chooseStepLabels(250, [48, 85, 55, 95, 35], [48, 85, 55, 33, 35])).toBeNull();
  });

  it("draws one continuous track under the dots, with 12 px labels", () => {
    const { container } = renderWithProviders(<Stepper steps={PIPELINE_STEPS} current={2} />);
    expect(screen.getAllByTestId("stepper-track")).toHaveLength(1);
    const labels = container.querySelectorAll("[data-step-label]");
    expect(labels).toHaveLength(5);
    expect(screen.getByRole("list").className).toMatch(/\btext-xs\b/);
    for (const l of labels) expect(l.className).toContain("whitespace-nowrap");
  });

  /** Lay the stepper out `width` px wide with labels ~6.5 px per character. */
  function layout(width: number) {
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockImplementation(function (this: HTMLElement) {
      return this.tagName === "OL" ? width : 0;
    });
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
      return new DOMRect(0, 0, (this.textContent ?? "").length * 6.5, 16);
    });
  }

  it("switches to the one-line current step when the labels don't fit its own width", async () => {
    layout(250);
    const { container } = renderWithProviders(<Stepper steps={PIPELINE_STEPS} current={2} />);
    await waitFor(() => expect(container.querySelectorAll("[data-step-label]")).toHaveLength(0));
    expect(screen.getByText(/Checking/)).toHaveTextContent("Checking · step 3 of 5");
  });

  it("uses the short labels where they fit, and nothing with fallback none", async () => {
    // 390 px: "Checking" and "Computing dates" would touch, "Checking" and "Dates" don't
    layout(390);
    const { container, unmount } = renderWithProviders(<Stepper steps={PIPELINE_STEPS} current={1} />);
    await waitFor(() => expect(Array.from(container.querySelectorAll("[data-step-label]")).map((l) => l.textContent)).toEqual(["Reading", "Understanding", "Checking", "Dates", "Filing"]));
    unmount();
    layout(200);
    const narrow = renderWithProviders(<Stepper steps={PIPELINE_STEPS} current={1} size="sm" fallback="none" />);
    await waitFor(() => expect(narrow.container.querySelectorAll("[data-step-label]")).toHaveLength(0));
    expect(screen.queryByText(/step 2 of 5/)).not.toBeInTheDocument();
  });
});

describe("PartyChip", () => {
  it("keeps the name and lets the kind give way, with the full name in its tooltip and a 24 px target", () => {
    renderWithProviders(<PartyChip id="pty_abh" name="Ausländerbehörde Musterstadt" kind="immigration_office" showKind />);
    const chip = screen.getByRole("button", { name: /Ausländerbehörde Musterstadt — open details/ });
    expect(chip).toHaveAttribute("title", "Ausländerbehörde Musterstadt · Immigration office");
    expect(chip.className).toMatch(/\bmin-h-6\b/);
    expect(chip.className).toContain("transition-[color,background-color,border-color]");
    expect(chip.className).not.toMatch(/\btransition-colors\b/);
    const name = within(chip).getByText("Ausländerbehörde Musterstadt");
    const kind = within(chip).getByText(/Immigration office/);
    expect(name.className).toMatch(/\bmin-w-0\b.*\btruncate\b/);
    expect(kind.className).toMatch(/shrink-\[999\]/);
    expect(kind.className).toMatch(/\btruncate\b/);
  });
});

describe("Glossary", () => {
  it("marks only the German word as German", () => {
    renderWithProviders(<Glossary term="Einspruch" />);
    const german = screen.getByText("Einspruch");
    expect(german).toHaveAttribute("lang", "de");
    expect(german.parentElement).toHaveTextContent("Einspruch (objection)");
    expect(german.parentElement).not.toHaveAttribute("lang");
  });

  it("has a plain variant for labels: no tab stop, no tooltip trigger", () => {
    renderWithProviders(
      <label>
        <input type="radio" name="kind" /> <Glossary term="Kündigung" translate={false} plain />
      </label>,
    );
    const term = screen.getByText("Kündigung");
    expect(term).toHaveAttribute("lang", "de");
    expect(term.closest("[tabindex]")).toBeNull();
  });
});

describe("CardHeader", () => {
  it("centres a lone title on its icon; with a description the icon aligns with the first line", () => {
    renderWithProviders(
      <Card>
        <CardHeader title="Checks" icon={ListChecks} data-testid="lone" />
        <CardHeader title="How to send it" description="By Einschreiben" icon={ListChecks} data-testid="described" />
      </Card>,
    );
    expect(screen.getByTestId("lone").className).toMatch(/\bitems-center\b/);
    expect(screen.getByTestId("lone").firstElementChild!.className).not.toContain("mt-0.5");
    expect(screen.getByTestId("described").className).toMatch(/\bitems-start\b/);
  });
});

describe("Disclaimer", () => {
  it("offers independent advice in plain words, with 24 px link targets and the German name marked", () => {
    renderWithProviders(<Disclaimer advice={ADVICE_LINKS.rent} />);
    expect(screen.getByText(/Unsure\? Get independent advice:/)).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /Mieterverein \(tenants' association\)/ });
    expect(link.className).toMatch(/-my-0\.5/);
    expect(link.className).toMatch(/\bpy-0\.5\b/);
    expect(within(link).getByText("Mieterverein")).toHaveAttribute("lang", "de");
    expect(link).toHaveAttribute("target", "_blank");
  });
});

describe("KindBadge", () => {
  it("shows money coming in as 'Money in', not an amber payment to make", () => {
    expect(resolveKind({ kind: "payment", direction: "in" }).label).toBe("Money in");
    expect(resolveKind({ kind: "payment", direction: "in" }).tone).toBe("ok");
    expect(resolveKind({ kind: "payment", direction: "out" }).label).toBe("Payment");
    expect(resolveKind({ kind: "payment" }).label).toBe("Payment");
    renderWithProviders(
      <>
        <KindBadge kind="payment" direction="in" />
        <KindIcon kind="payment" direction="in" title="Money in" />
      </>,
    );
    expect(screen.getByText("Money in").parentElement!.className).toContain("bg-ok-soft");
    expect(screen.getByRole("img", { name: "Money in" }).className).toContain("text-ok");
  });
});

describe("DateLeaf", () => {
  it("has an 11 px weekday in every size and says the full date to screen readers", () => {
    const { container } = renderWithProviders(
      <>
        <DateLeaf date="2026-10-08" size="sm" />
        <DateLeaf date="2026-10-08" size="md" tone="danger" />
        <DateLeaf date="2026-10-08" size="lg" tone="warn" decorative />
      </>,
    );
    const leaves = container.querySelectorAll("time");
    expect(Array.from(leaves).map((l) => l.getAttribute("data-size"))).toEqual(["sm", "md", "lg"]);
    for (const leaf of leaves) {
      expect(leaf).toHaveAttribute("datetime", "2026-10-08");
      expect(leaf.firstElementChild!.className).toMatch(/\btext-2xs\b/);
    }
    expect(screen.getAllByText("Thursday 8 October")).toHaveLength(2);
    expect(leaves[2]).toHaveAttribute("aria-hidden", "true");
    expect(leaves[2]).toHaveTextContent(/Oct/);
    expect(leaves[1]!.className).toContain("bg-danger-soft");
  });
});

describe("Receipt", () => {
  it("has one trigger: help icon, soft underline, a 24 px target and its context for screen readers", () => {
    renderWithProviders(<ReceiptTrigger context="Pay TechMarkt" />);
    const trigger = screen.getByRole("button", { name: "Why this date? (Pay TechMarkt)" });
    expect(trigger.querySelector("svg")).toBeTruthy();
    expect(trigger.className).toMatch(/\bmin-h-6\b/);
    expect(trigger.className).toContain("decoration-accent/30");
  });

  it("shows date tiles, the sentence, how sure, the quote, rules on demand and the disclaimer", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <ReceiptPopover
        context="Pay TechMarkt"
        content={
          <Receipt
            context="Pay TechMarkt"
            dates={[
              { label: "Send by", date: "2026-09-29" },
              { label: "Must arrive by", date: "2026-09-30" },
              { label: "Safe date (a working day)", date: "2026-10-01" },
            ]}
            summary="The date given is Wed 30 Sep 2026."
            confidence="high"
            quote={{ text: "bis spätestens 30.09.2026" }}
            steps={[
              { label: "The date given is Wed 30 Sep 2026", date: "2026-09-30", citation: "The document's own wording" },
              { label: "Send by Tue 29 Sep", date: "2026-09-29", citation: "§ 675s Abs. 1 BGB", href: "https://www.gesetze-im-internet.de/bgb/__675s.html" },
            ]}
            holidayCalendar="Nordrhein-Westfalen"
          />
        }
      />,
    );
    await user.click(screen.getByRole("button", { name: /Why this date\?/ }));
    const pop = await screen.findByRole("dialog", { name: "Why this date? Pay TechMarkt" });
    // tiles: two per row, an odd last one spans the row
    const tiles = within(pop).getAllByRole("term").map((t) => t.parentElement!);
    expect(tiles).toHaveLength(3);
    expect(tiles[2]!.className).toContain("col-span-2");
    expect(within(pop).getByText("The date given is Wed 30 Sep 2026.")).toBeInTheDocument();
    expect(within(pop).getByText(/High confidence/)).toBeInTheDocument();
    expect(within(pop).getByText("bis spätestens 30.09.2026").closest("blockquote")).toHaveAttribute("lang", "de");
    const toggle = within(pop).getByRole("button", { name: "Show the rules" });
    expect(within(pop).getByText(/Weekends and public holidays counted/)).not.toBeVisible();
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(toggle.className).toContain("[&_svg]:rotate-180");
    // a citation with a law text is a link; one without is plain text (not accent-coloured)
    // (law references are glued with non-breaking spaces: "§ 675s" never breaks after the §)
    expect(within(pop).getByRole("link", { name: /^§\u00a0675s Abs\.\u00a01 BGB/ })).toHaveAttribute("target", "_blank");
    expect(within(pop).getByText("The document's own wording").className).toContain("text-muted");
    expect(within(pop).getByText(/Not legal advice/)).toBeInTheDocument();
  });

  it("shows a deadline the law adds in the law's words, never as what the letter says", () => {
    // review round 1: the dismissal's court-action to-do quoted Ordnung's wording of § 4 KSchG as the letter's
    renderWithProviders(
      <Receipt
        summary="Three weeks after the day you received it: Thu 15 Oct 2026."
        confidence="low"
        quote={{ text: "innerhalb von drei Wochen nach Zugang der Kündigung", source: "law", citation: "§ 4 S. 1 KSchG" }}
      />,
    );
    const caption = screen.getByText(/What the law says/);
    // review round 2: one parenthesis at most, and the law's words without the letter's yellow marker
    expect(caption).toHaveTextContent("What the law says, in short — § 4 S. 1 KSchG");
    expect(screen.queryByText(/What the letter says/)).toBeNull();
    expect(screen.getByText(/innerhalb von drei Wochen/).className).not.toMatch(/\bmarker\b/);
  });
});
