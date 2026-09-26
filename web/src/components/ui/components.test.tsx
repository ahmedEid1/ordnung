import { describe, expect, it } from "vitest";
import { useState } from "react";
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
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
import { Tabs } from "./Tabs";
import { Glossary } from "./Glossary";
import { Button } from "./Button";
import { Checkbox, Switch } from "./Field";
import { EmptyState } from "./EmptyState";
import { Toaster, toast, __clearToasts } from "./Toast";
import { PIPELINE_STEPS } from "@/lib/copy";

describe("dates & money", () => {
  it("counts down against the app's today (demo date), not the browser clock", () => {
    renderWithProviders(
      <div>
        <Countdown date="2026-10-08" prefix="send by" />
        <Countdown date="2026-09-26" />
        <Countdown date="2026-09-29" variant="pill" />
      </div>,
    );
    expect(screen.getByText(/send by Thu 8 Oct/)).toBeInTheDocument();
    expect(screen.getByText(/in 10 days/)).toBeInTheDocument();
    expect(screen.getByText("2 days overdue")).toHaveClass("text-danger-ink");
    expect(screen.getByText("tomorrow").closest("time")).toHaveAttribute("datetime", "2026-09-29");
  });

  it("formats money with the interval", () => {
    const { container } = renderWithProviders(<Money amount={34.99} interval="monthly" />);
    expect(container.textContent?.replace(/\u00a0/g, " ")).toBe("€34.99/month");
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

describe("Glossary, EmptyState, Toast", () => {
  it("shows the German term with its translation and explains it on focus", async () => {
    renderWithProviders(<Glossary term="Einspruch" />);
    const term = screen.getByText("Einspruch (objection)");
    expect(term).toHaveAttribute("lang", "de");
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
