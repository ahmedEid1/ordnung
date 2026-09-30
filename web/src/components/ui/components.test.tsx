import { describe, expect, it } from "vitest";
import { useState } from "react";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/render";
import { assertNoRawEnumsInElement } from "@/lib/copy";
import { ITEM_KINDS, DOCUMENT_KINDS } from "@/api/types";
import { Countdown } from "./Countdown";
import { GroundingBadge } from "./GroundingBadge";
import { KindBadge } from "./KindBadge";
import { StatusPill } from "./StatusPill";
import { Money } from "./Money";
import { Stepper } from "./Stepper";
import { Dialog } from "./Dialog";
import { TabPanel, Tabs } from "./Tabs";
import { Glossary } from "./Glossary";
import { Button, buttonVariants } from "./Button";
import { Checkbox, Field, Input, Select, Switch } from "./Field";
import { SegmentedControl } from "./SegmentedControl";
import { CountBadge } from "./Badge";
import { LetterText } from "./LetterText";
import { EmptyState } from "./EmptyState";
import { Toaster, toast, __clearToasts } from "./Toast";
import { PIPELINE_STEPS } from "@/lib/copy";

const plain = (s: string | null | undefined) => (s ?? "").replace(/\u00a0/g, " ");

describe("dates & money", () => {
  it("counts down against the app's today (demo date), not the browser clock", () => {
    const { container } = renderWithProviders(
      <div>
        <Countdown date="2026-10-08" prefix="send by" />
        <Countdown date="2026-09-26" />
        <Countdown date="2026-09-29" variant="pill" />
      </div>,
    );
    const [sendBy] = container.querySelectorAll("time");
    expect(plain(sendBy!.textContent)).toBe("send by Thu 8 Oct · in 10 days");
    expect(screen.getByText("2 days overdue")).toHaveClass("text-danger-ink");
    expect(screen.getByText("tomorrow").closest("time")).toHaveAttribute("datetime", "2026-09-29");
  });

  it("wraps between its parts instead of overflowing (only the pill stays on one line)", () => {
    const { container } = renderWithProviders(
      <div>
        <Countdown date="2026-10-08" prefix="send by" />
        <Countdown date="2026-10-08" prefix="send by" variant="pill" />
      </div>,
    );
    const [text, pill] = container.querySelectorAll("time");
    expect(text).not.toHaveClass("whitespace-nowrap");
    // "send by" · "Thu 8 Oct ·" · "in 10 days": each whole, breakable between them
    const parts = [...text!.children].map((el) => [plain(el.textContent), el.classList.contains("whitespace-nowrap")]);
    expect(parts).toEqual([
      ["send by", true],
      ["Thu 8 Oct ·", true],
      ["in 10 days", true],
    ]);
    expect(plain(text!.textContent)).toBe("send by Thu 8 Oct · in 10 days");
    expect(pill).toHaveClass("whitespace-nowrap", "inline-flex", "gap-x-1");
  });

  it("colours by the one urgency scale; appointments and direct debits never turn red", () => {
    const { container } = renderWithProviders(
      <div>
        <Countdown date="2026-09-29" />
        <Countdown date="2026-10-03" />
        <Countdown date="2026-10-08" />
        <Countdown date="2026-12-01" />
        <Countdown date="2026-09-28" mode="event" />
        <Countdown date="2026-09-29" cap="warn" />
        <Countdown date="2026-12-01" inkLater />
      </div>,
    );
    const levels = [...container.querySelectorAll("time")].map((t) => t.dataset.urgency);
    expect(levels).toEqual(["danger", "warn", "ink", "muted", "warn", "warn", "ink"]);
    expect(container.querySelectorAll("time")[1]).toHaveClass("text-warn-ink");
  });

  it("formats money with the interval as its own part that may wrap below the amount", () => {
    const { container } = renderWithProviders(<Money amount={34.99} interval="monthly" />);
    expect(plain(container.textContent)).toBe("€34.99/month");
    const money = container.firstElementChild!;
    expect(money).not.toHaveClass("whitespace-nowrap");
    expect(money.children[0]).toHaveClass("whitespace-nowrap");
    expect(money.children[0]!.textContent).toBe("€34.99");
    expect(money.querySelector("wbr")).not.toBeNull();
    const suffix = money.querySelector("[data-part=interval]")!;
    expect(suffix).toHaveTextContent("/month");
    expect(suffix).toHaveClass("ml-0.5", "whitespace-nowrap", "text-muted");
  });

  it("sizes the interval for a display amount, and has no suffix for one-off costs", () => {
    const { container } = renderWithProviders(
      <div>
        <Money amount={59.9} interval="yearly" intervalClassName="font-sans text-sm" />
        <Money amount={12} interval="once" />
      </div>,
    );
    expect(container.querySelector("[data-part=interval]")).toHaveClass("font-sans", "text-sm");
    expect(container.querySelectorAll("[data-part=interval]")).toHaveLength(1);
  });
});

describe("Button", () => {
  it("gives a link button a 24 px target", () => {
    renderWithProviders(<Button variant="link">Why this date?</Button>);
    expect(screen.getByRole("button", { name: "Why this date?" })).toHaveClass("min-h-6", "inline-flex", "items-center");
  });

  it("turns a disabled button neutral (not a faded primary), but keeps a busy one's colour", () => {
    renderWithProviders(
      <div>
        <Button variant="primary" disabled>
          Write the letter
        </Button>
        <Button variant="primary" loading>
          Saving
        </Button>
      </div>,
    );
    const disabled = screen.getByRole("button", { name: "Write the letter" });
    expect(disabled).toBeDisabled();
    expect(disabled).toHaveClass("inactive:bg-surface-3", "inactive:text-faint", "inactive:shadow-none");
    expect(disabled.className).not.toMatch(/opacity-50/);
    const busy = screen.getByRole("button", { name: "Saving" });
    expect(busy).toHaveAttribute("aria-busy", "true");
    expect(busy).toBeDisabled();
  });

  it("fills a hovered danger button opaquely in dark mode: its text contrast never depends on the parent", () => {
    const hover = buttonVariants({ variant: "danger" }).split(" ").filter((c) => c.startsWith("dark:hover:bg-"));
    expect(hover).toEqual(["dark:hover:bg-danger-soft-hover"]);
  });

  it("lets a caller shrink a button: its text label can end in an ellipsis", () => {
    renderWithProviders(<Button className="min-w-0 flex-1">Ask about them</Button>);
    const button = screen.getByRole("button", { name: "Ask about them" });
    expect(button).toHaveClass("min-w-0", "flex-1");
    expect(button).not.toHaveClass("shrink-0");
    expect(screen.getByText("Ask about them")).toHaveClass("min-w-0", "truncate");
    // links styled as buttons keep the same look
    expect(buttonVariants({ variant: "link" })).toContain("min-h-6");
  });
});

describe("Field controls", () => {
  it("have a visible edge, readable placeholders and selects that end long choices in an ellipsis", () => {
    renderWithProviders(
      <div>
        <Field label="Your name">
          <Input placeholder="Sam Rivera" />
        </Field>
        <Field label="State">
          <Select defaultValue="nw">
            <option value="nw">Nordrhein-Westfalen (North Rhine-Westphalia)</option>
          </Select>
        </Field>
      </div>,
    );
    const input = screen.getByLabelText("Your name");
    expect(input).toHaveClass("border-control-border", "placeholder:text-muted");
    expect(input.className).not.toMatch(/placeholder:text-muted\/70|border-line-strong/);
    expect(screen.getByLabelText("State")).toHaveClass("truncate", "border-control-border");
  });
});

describe("CountBadge", () => {
  it("is 12 px, visible on surface-2 when neutral, and 11 px as a compact solid bubble", () => {
    const { container } = renderWithProviders(
      <div>
        <CountBadge count={3} />
        <CountBadge count={2} tone="warn" label="2 letters to check" />
        <CountBadge count={2} tone="warn" variant="solid" size="compact" />
        <CountBadge count={0} />
        <CountBadge count={120} />
      </div>,
    );
    const [neutral, warn, bubble, big] = [...container.querySelectorAll("span")];
    expect(neutral).toHaveClass("text-xs", "bg-surface-3", "text-muted");
    expect(warn).toHaveClass("bg-warn-soft", "text-warn-ink");
    expect(screen.getByLabelText("2 letters to check")).toBe(warn);
    expect(bubble).toHaveClass("text-2xs", "h-4", "bg-warn", "text-white");
    expect(big).toHaveTextContent("99+");
    expect(container.querySelectorAll("span")).toHaveLength(4);
  });
});

describe("LetterText", () => {
  it("writes money the app's way in English text and keeps units together", () => {
    const { container } = renderWithProviders(<LetterText text="Pay 94.99 EUR by 2026-10-14 (§ 286 BGB)." />);
    expect(plain(container.textContent)).toBe("Pay €94.99 by Wed 14 Oct (§ 286 BGB).");
    expect(container.textContent).toContain("Wed\u00a014\u00a0Oct");
    expect(container.textContent).toContain("§\u00a0286");
  });

  it("quotes German text as written, only gluing its units", () => {
    renderWithProviders(<LetterText text="Geht der Betrag von 184,30 € nicht bis zum 14. Oktober 2026 ein, wird die Forderung (§ 56 Abs. 3) fällig." />);
    const quote = document.querySelector("q[lang=de]")!;
    expect(plain(quote.textContent)).toContain("184,30 € nicht bis zum 14. Oktober 2026");
    expect(quote.textContent).toContain("184,30\u00a0€");
    expect(quote.textContent).toContain("§\u00a056 Abs.\u00a03");
  });
});

describe("copy-mapped components never show raw enum values", () => {
  it("renders labels for every kind and status", () => {
    const { container } = renderWithProviders(
      <div>
        {ITEM_KINDS.map((k) => (
          <KindBadge key={k} kind={k} />
        ))}
        {DOCUMENT_KINDS.map((k) => (
          <KindBadge key={k} docKind={k} />
        ))}
        <StatusPill of="document" status="needs_review" />
        <StatusPill of="item" status="missed" />
        <GroundingBadge grounding="verified" page={2} />
        <GroundingBadge grounding="model_read" />
        <GroundingBadge grounding="unverified" />
      </div>,
    );
    expect(screen.getByText("Please check")).toBeInTheDocument();
    expect(screen.getByText("Found in the letter · p.2")).toBeInTheDocument();
    expect(screen.getByText("Read by AI from the photo")).toBeInTheDocument();
    expect(screen.getByText("Couldn't find this — please check")).toBeInTheDocument();
    expect(screen.getByText("Tax assessment")).toBeInTheDocument();
    expect(() => assertNoRawEnumsInElement(container)).not.toThrow();
  });

  it("the DOM guard catches a leaked value", () => {
    const { container } = renderWithProviders(
      <div>
        <span>needs_review</span>
      </div>,
    );
    expect(() => assertNoRawEnumsInElement(container)).toThrow(/needs_review/);
  });
});

describe("Stepper", () => {
  it("marks done / current steps accessibly", () => {
    renderWithProviders(<Stepper steps={PIPELINE_STEPS} current={2} live label="Reading IMG_2044.jpg" />);
    const list = screen.getByRole("list", { name: "Reading IMG_2044.jpg" });
    expect(list).toBeInTheDocument();
    expect(screen.getByLabelText("Reading: done")).toBeInTheDocument();
    expect(screen.getByLabelText("Checking: in progress")).toHaveAttribute("aria-current", "step");
    expect(screen.getByLabelText("Filing: not started")).toBeInTheDocument();
    expect(screen.getByText("Checking, step 3 of 5.")).toBeInTheDocument();
  });
});

describe("Dialog", () => {
  function Harness() {
    const [open, setOpen] = useState(false);
    return (
      <>
        <Button onClick={() => setOpen(true)}>Open</Button>
        <Dialog open={open} onClose={() => setOpen(false)} title="Are these pages of one letter?" footer={<Button>Combine</Button>}>
          <p>Body</p>
        </Dialog>
      </>
    );
  }

  it("opens as a labelled modal and closes on Escape, restoring focus", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Harness />);
    const trigger = screen.getByRole("button", { name: "Open" });
    await user.click(trigger);
    const dialog = await screen.findByRole("dialog", { name: "Are these pages of one letter?" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    await waitFor(() => expect(dialog).toHaveFocus());
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(trigger).toHaveFocus();
  });
});

describe("Switch and Checkbox", () => {
  it("wrap their descriptions without a one-word last line", () => {
    renderWithProviders(
      <>
        <Switch checked={false} onCheckedChange={() => {}} label="Reminders" description="We remind you seven days before a deadline and again on the day." />
        <Checkbox label="Keep private" description="Nothing about this letter is sent to Claude." />
      </>,
    );
    expect(screen.getByText(/seven days before/)).toHaveClass("text-pretty");
    expect(screen.getByText(/Nothing about this letter/)).toHaveClass("text-pretty");
  });
});

describe("Tabs", () => {
  function Harness() {
    const [v, setV] = useState("all");
    return (
      <Tabs
        label="Filter letters"
        value={v}
        onChange={setV}
        items={[
          { value: "all", label: "All" },
          { value: "check", label: "Please check", count: 2 },
          { value: "private", label: "Private" },
        ]}
      />
    );
  }

  it("points aria-controls only at the panel that exists", () => {
    function WithPanels() {
      const [v, setV] = useState("all");
      return (
        <>
          <Tabs id="t" label="Filter letters" value={v} onChange={setV} items={[{ value: "all", label: "All" }, { value: "check", label: "Please check" }]} />
          <TabPanel id="t" value="all" current={v}>
            All letters
          </TabPanel>
          <TabPanel id="t" value="check" current={v}>
            To check
          </TabPanel>
        </>
      );
    }
    const { unmount } = renderWithProviders(<WithPanels />);
    expect(screen.getByRole("tab", { name: "All" })).toHaveAttribute("aria-controls", "t-panel-all");
    expect(screen.getByRole("tab", { name: "Please check" })).not.toHaveAttribute("aria-controls");
    expect(document.getElementById("t-panel-all")).toHaveAttribute("role", "tabpanel");
    // the panel's focus ring isn't switched off
    expect(screen.getByRole("tabpanel")).not.toHaveClass("outline-none");
    unmount();

    // no id → no panels → no aria-controls at all
    renderWithProviders(<Tabs label="Range" variant="pill" value="a" onChange={() => {}} items={[{ value: "a", label: "A" }, { value: "b", label: "B" }]} />);
    for (const tab of screen.getAllByRole("tab")) expect(tab).not.toHaveAttribute("aria-controls");
  });

  it("pill tabs: 36 px tall with the track, focus ring inside the tab, zero counts optional, fill on phones", () => {
    const { container } = renderWithProviders(
      <Tabs
        label="Show contracts"
        variant="pill"
        fill
        hideZero
        value="active"
        onChange={() => {}}
        className="self-start"
        items={[
          { value: "active", label: "Active", count: 9 },
          { value: "ended", label: "Ended", count: 0 },
        ]}
      />,
    );
    const track = container.firstElementChild!;
    expect(track).toHaveClass("rounded-xl", "bg-surface-2", "p-1", "w-fit", "max-w-full", "max-sm:w-full", "self-start");
    const list = screen.getByRole("tablist", { name: "Show contracts" });
    expect(list).toHaveClass("overflow-x-auto");
    const [active, ended] = screen.getAllByRole("tab");
    expect(active).toHaveClass("h-7", "focus-visible:-outline-offset-2", "max-sm:flex-auto");
    expect(active).toHaveTextContent("Active9");
    expect(ended).toHaveTextContent(/^Ended$/);
  });

  it("shows zero counts by default, on a background that stands out from the track", () => {
    renderWithProviders(
      <Tabs label="Filter letters" variant="pill" value="all" onChange={() => {}} items={[{ value: "all", label: "All", count: 3 }, { value: "private", label: "Private", count: 0 }]} />,
    );
    const zero = within(screen.getByRole("tab", { name: /Private/ })).getByText("0");
    expect(zero).toHaveClass("bg-surface-3");
  });

  it("moves selection with arrow keys (roving focus)", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Harness />);
    const all = screen.getByRole("tab", { name: "All" });
    expect(all).toHaveAttribute("aria-selected", "true");
    all.focus();
    await user.keyboard("{ArrowRight}");
    const check = screen.getByRole("tab", { name: /Please check/ });
    expect(check).toHaveAttribute("aria-selected", "true");
    expect(check).toHaveFocus();
    await user.keyboard("{End}");
    expect(screen.getByRole("tab", { name: "Private" })).toHaveAttribute("aria-selected", "true");
  });
});

describe("pill Tabs and SegmentedControl", () => {
  it("share one track, thumb and item shape", async () => {
    const { SEGMENT_THUMB, SEGMENT_TRACK } = await import("./segment");
    const { container } = renderWithProviders(
      <>
        <Tabs label="Show letters" variant="pill" value="a" onChange={() => {}} items={[{ value: "a", label: "All" }, { value: "b", label: "Open" }]} />
        <SegmentedControl label="View" value="a" onChange={() => {}} options={[{ value: "a", label: "Lanes" }, { value: "b", label: "List" }]} />
      </>,
    );
    const track = container.firstElementChild!;
    const group = screen.getByRole("radiogroup", { name: "View" });
    for (const cls of SEGMENT_TRACK.split(" ")) {
      expect(track).toHaveClass(cls);
      expect(group).toHaveClass(cls);
    }
    const tabThumb = screen.getByRole("tab", { name: "All" }).querySelector("span[aria-hidden]")!;
    const segThumb = screen.getByRole("radio", { name: "Lanes" }).querySelector("span[aria-hidden]")!;
    for (const cls of SEGMENT_THUMB.split(" ")) {
      expect(tabThumb).toHaveClass(cls);
      expect(segThumb).toHaveClass(cls);
    }
    expect(screen.getByRole("tab", { name: "All" })).toHaveClass("h-7", "rounded-lg");
    expect(screen.getByRole("radio", { name: "Lanes" })).toHaveClass("h-7", "rounded-lg", "focus-visible:-outline-offset-2");
  });
});

describe("SegmentedControl", () => {
  it("keeps labels on one line, hugs its segments, and offers a short label on phones", () => {
    renderWithProviders(
      <SegmentedControl
        label="Zoom"
        size="sm"
        value="fit"
        onChange={() => {}}
        options={[
          { value: "fit", label: "Fit width", shortLabel: "Fit" },
          { value: "zoom", label: "150%" },
        ]}
      />,
    );
    const group = screen.getByRole("radiogroup", { name: "Zoom" });
    expect(group).toHaveClass("inline-flex", "w-fit", "max-w-full", "min-w-0");
    const fit = screen.getByRole("radio", { name: "Fit width" });
    expect(fit).toHaveClass("whitespace-nowrap", "min-w-0");
    expect(fit).toHaveAttribute("title", "Fit width");
    expect(within(fit).getByText("Fit")).toHaveClass("sm:hidden", "truncate");
    expect(within(fit).getByText("Fit width")).toHaveClass("max-sm:hidden", "truncate");
    expect(screen.getByRole("radio", { name: "150%" })).not.toHaveAttribute("title");
  });

  it("fills the row always or only on phones", () => {
    renderWithProviders(
      <>
        <SegmentedControl label="Always" fill value="a" onChange={() => {}} options={[{ value: "a", label: "A" }, { value: "b", label: "B" }]} />
        <SegmentedControl label="Phones" fill="phone" value="a" onChange={() => {}} options={[{ value: "a", label: "A" }, { value: "b", label: "B" }]} />
      </>,
    );
    const always = screen.getByRole("radiogroup", { name: "Always" });
    expect(always).toHaveClass("flex", "w-full");
    expect(always).not.toHaveClass("w-fit");
    expect(within(always).getAllByRole("radio")[0]).toHaveClass("flex-auto");
    const phones = screen.getByRole("radiogroup", { name: "Phones" });
    expect(phones).toHaveClass("w-fit", "max-sm:w-full");
    expect(within(phones).getAllByRole("radio")[0]).toHaveClass("max-sm:flex-auto");
  });
});

describe("Glossary, EmptyState, Toast", () => {
  it("shows the German term with its translation and explains it on focus", async () => {
    renderWithProviders(<Glossary term="Einspruch" />);
    // only the German word is marked German; "(objection)" is English
    expect(screen.getByText("Einspruch")).toHaveAttribute("lang", "de");
    const term = screen.getByText((_, el) => el?.getAttribute("tabindex") === "0" && el.textContent === "Einspruch (objection)");
    expect(term).not.toHaveAttribute("lang");
    act(() => {
      term.focus();
      fireEvent.focus(term);
    });
    // tooltip appears for keyboard focus (focus-visible) — jsdom may not match :focus-visible,
    // so fall back to hover (pointer events: a touch "mouseenter" must not open it)
    fireEvent.pointerEnter(term);
    expect(await screen.findByRole("tooltip")).toHaveTextContent(/formal objection/);
  });

  it("renders an empty state with a heading and action", () => {
    renderWithProviders(<EmptyState title="All clear until Friday" description="Nothing needs you." action={<Button>See timeline</Button>} />);
    expect(screen.getByRole("heading", { name: "All clear until Friday" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "See timeline" })).toBeInTheDocument();
  });

  it("shows toasts with Undo", async () => {
    __clearToasts();
    const user = userEvent.setup();
    let undone = false;
    renderWithProviders(<Toaster />);
    act(() => {
      toast({ title: "Marked as done", undo: () => void (undone = true) });
    });
    expect(await screen.findByText("Marked as done")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Undo" }));
    expect(undone).toBe(true);
    await waitFor(() => expect(screen.queryByText("Marked as done")).not.toBeInTheDocument());
  });
});
