/**
 * Overlays (Popover, Menu, Tooltip, Dialog, Drawer): placement, keyboard, modality, focus return
 * and the classes that carry their layout. jsdom has no layout, so element visibility and the
 * viewport width are stubbed; the Playwright suite checks the real layout (e2e/layout.spec.ts).
 */
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { useRef, useState } from "react";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/render";
import { Button } from "./Button";
import { Dialog } from "./Dialog";
import { Drawer } from "./Drawer";
import { Menu } from "./Menu";
import { Popover } from "./Popover";
import { Tooltip } from "./Tooltip";
import { computePosition, type Insets } from "./internal";

// ------------------------------------------------------------------------------------------------
// jsdom stubs: a viewport width for media queries, and "every element is rendered" (offsetParent)
// ------------------------------------------------------------------------------------------------

const original = {
  matchMedia: window.matchMedia,
  innerWidth: window.innerWidth,
  innerHeight: window.innerHeight,
  offsetParent: Object.getOwnPropertyDescriptor(HTMLElement.prototype, "offsetParent"),
};

/** Media-query listeners (`useMediaQuery` subscribes); `setViewport` notifies them like a resize. */
const mediaListeners = new Set<() => void>();

function setViewport(width: number, height = 800): void {
  Object.defineProperty(window, "innerWidth", { configurable: true, value: width });
  Object.defineProperty(window, "innerHeight", { configurable: true, value: height });
  window.matchMedia = (query: string) => {
    const min = /min-width:\s*(\d+)px/.exec(query);
    return {
      matches: min ? width >= Number(min[1]) : false,
      media: query,
      onchange: null,
      addEventListener: (_: string, cb: () => void) => mediaListeners.add(cb),
      removeEventListener: (_: string, cb: () => void) => mediaListeners.delete(cb),
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    } as unknown as MediaQueryList;
  };
  act(() => mediaListeners.forEach((cb) => cb()));
}

beforeAll(() => {
  Object.defineProperty(HTMLElement.prototype, "offsetParent", {
    configurable: true,
    get(this: HTMLElement) {
      return this.parentElement;
    },
  });
});
afterAll(() => {
  if (original.offsetParent) Object.defineProperty(HTMLElement.prototype, "offsetParent", original.offsetParent);
});
afterEach(() => {
  window.matchMedia = original.matchMedia;
  Object.defineProperty(window, "innerWidth", { configurable: true, value: original.innerWidth });
  Object.defineProperty(window, "innerHeight", { configurable: true, value: original.innerHeight });
  document.getElementById("root")?.remove();
  document.body.style.overflow = "";
});

/** Render inside a `#root`, like the app (modals make it inert). */
function renderInRoot(ui: React.ReactElement) {
  const root = document.createElement("div");
  root.id = "root";
  document.body.appendChild(root);
  return renderWithProviders(ui, { container: root });
}

const sleep = (ms: number) => act(() => new Promise<void>((r) => setTimeout(r, ms)));

// ------------------------------------------------------------------------------------------------
// Placement
// ------------------------------------------------------------------------------------------------

describe("computePosition", () => {
  const page: Insets = { top: 72, right: 8, bottom: 24, left: 8 }; // under the top bar, as pageInsets() reads it
  const rect = (top: number, left = 300, width = 70, height = 32) =>
    ({ top, bottom: top + height, left, right: left + width, width, height, x: left, y: top, toJSON: () => ({}) }) as DOMRect;
  const panel = { width: 352, height: 434 };

  beforeEach(() => setViewport(1280, 800));

  it("opens on the preferred side when it fits, starting below its trigger", () => {
    const pos = computePosition(rect(100), panel, "bottom-start", { insets: page });
    expect(pos).toMatchObject({ side: "bottom", placement: "bottom-start", top: 138, left: 300 });
    expect(pos.maxHeight).toBe(800 - 24 - 132 - 6);
  });

  it("flips above when only that side fits, hanging from the trigger (never over it or the top bar)", () => {
    const pos = computePosition(rect(600), panel, "bottom-start", { insets: page });
    expect(pos.side).toBe("top");
    expect(pos.top).toBeUndefined();
    expect(pos.bottom).toBe(800 - 600 + 6); // its bottom edge 6 px above the trigger, whatever its height
    expect(pos.maxHeight).toBe(600 - 6 - 72); // stops below the top bar
  });

  it("takes the side where scrolling the page makes it fit over one where it would be cut", () => {
    const tall = { width: 384, height: 617 };
    // 490 px above, 182 px below; scrolling can move the trigger 496 px up
    expect(computePosition(rect(568, 556, 130, 20), tall, "bottom-start", { insets: page }).side).toBe("top");
    expect(computePosition(rect(568, 556, 130, 20), tall, "bottom-start", { insets: page, scroll: { up: 0, down: 496 } }).side).toBe("bottom");
  });

  it("keeps the side it opened on when the content grows", () => {
    const pos = computePosition(rect(500), { width: 352, height: 700 }, "bottom-start", { insets: page, side: "bottom" });
    expect(pos.side).toBe("bottom");
    expect(pos.top).toBe(538);
    expect(pos.maxHeight).toBe(800 - 24 - 532 - 6);
  });

  it("a side placement without room beside the trigger goes below it instead of covering it", () => {
    setViewport(390, 844);
    const tip = { width: 288, height: 40 };
    const badge = rect(12, 210, 32, 32);
    const pos = computePosition(badge, tip, "right");
    expect(pos.side).toBe("bottom");
    expect(pos.top).toBe(50);
    expect(computePosition(rect(12, 20, 32, 32), tip, "right").side).toBe("right");
  });

  it("keeps the panel inside the viewport horizontally", () => {
    expect(computePosition(rect(100, 1200), panel, "bottom-start", { insets: page }).left).toBe(1280 - 8 - 352);
    expect(computePosition(rect(100, 2), panel, "bottom-end", { insets: page }).left).toBe(8);
  });
});

// ------------------------------------------------------------------------------------------------
// Popover — floating panel (tablets and up)
// ------------------------------------------------------------------------------------------------

function PayPopover() {
  return (
    <>
      <Button>Before</Button>
      <Popover label="Pay the reminder" title="Pay" content={(close) => (
        <div>
          <p className="in-sheet:hidden">Pay</p>
          <button type="button">Copy IBAN</button>
          <button type="button" onClick={close}>
            Mark as paid
          </button>
        </div>
      )}>
        <Button>Pay</Button>
      </Popover>
      <Button>Next</Button>
    </>
  );
}

describe("Popover (floating)", () => {
  it("moves focus to the panel itself, not to a control that may be scrolled out of view", async () => {
    setViewport(1280);
    const user = userEvent.setup();
    renderInRoot(<PayPopover />);
    await user.click(screen.getByRole("button", { name: "Pay" }));
    const panel = await screen.findByRole("dialog", { name: "Pay the reminder" });
    await waitFor(() => expect(panel).toHaveFocus());
    expect(panel).not.toHaveAttribute("aria-modal");
    expect(panel.className).toMatch(/scroll-shadow/);
  });

  it("Tab past the last control closes it and continues after the trigger", async () => {
    setViewport(1280);
    const user = userEvent.setup();
    renderInRoot(<PayPopover />);
    await user.click(screen.getByRole("button", { name: "Pay" }));
    const panel = await screen.findByRole("dialog", { name: "Pay the reminder" });
    await waitFor(() => expect(panel).toHaveFocus());
    await user.tab();
    expect(screen.getByRole("button", { name: "Copy IBAN" })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("button", { name: "Mark as paid" })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("button", { name: "Next" })).toHaveFocus();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("Shift+Tab before the first control closes it and returns to the trigger", async () => {
    setViewport(1280);
    const user = userEvent.setup();
    renderInRoot(<PayPopover />);
    const trigger = screen.getByRole("button", { name: "Pay" });
    await user.click(trigger);
    const panel = await screen.findByRole("dialog", { name: "Pay the reminder" });
    await waitFor(() => expect(panel).toHaveFocus());
    await user.tab({ shift: true });
    expect(trigger).toHaveFocus();
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  it("closes when focus leaves for the page, and gives focus back to the trigger when an action closes it", async () => {
    setViewport(1280);
    const user = userEvent.setup();
    renderInRoot(<PayPopover />);
    const trigger = screen.getByRole("button", { name: "Pay" });
    await user.click(trigger);
    const panel = await screen.findByRole("dialog", { name: "Pay the reminder" });
    await waitFor(() => expect(panel).toHaveFocus());
    act(() => screen.getByRole("button", { name: "Before" }).focus());
    expect(trigger).toHaveAttribute("aria-expanded", "false");

    await user.click(trigger);
    await user.click(await screen.findByRole("button", { name: "Mark as paid" }));
    expect(trigger).toHaveFocus();
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  it("keeps its form while open: resizing to a phone doesn't swap the panel for a sheet under you", async () => {
    setViewport(1280);
    const user = userEvent.setup();
    renderInRoot(<PayPopover />);
    await user.click(screen.getByRole("button", { name: "Pay" }));
    const panel = await screen.findByRole("dialog", { name: "Pay the reminder" });
    setViewport(390);
    expect(screen.getByRole("dialog", { name: "Pay the reminder" })).toBe(panel);
    expect(panel).not.toHaveAttribute("data-sheet");
  });

  it("Escape closes it and returns focus to the trigger", async () => {
    setViewport(1280);
    const user = userEvent.setup();
    renderInRoot(<PayPopover />);
    const trigger = screen.getByRole("button", { name: "Pay" });
    await user.click(trigger);
    await screen.findByRole("dialog", { name: "Pay the reminder" });
    await user.keyboard("{Escape}");
    expect(trigger).toHaveFocus();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});

// ------------------------------------------------------------------------------------------------
// Popover — bottom sheet (phones)
// ------------------------------------------------------------------------------------------------

describe("Popover (phone sheet)", () => {
  it("is a real modal: title, 44 px Close, scrim, inert page, scroll lock, Tab trapped, focus back to the trigger", async () => {
    setViewport(390);
    const user = userEvent.setup();
    renderInRoot(<PayPopover />);
    const trigger = screen.getByRole("button", { name: "Pay" });
    await user.click(trigger);
    const sheet = await screen.findByRole("dialog", { name: "Pay the reminder" });
    expect(sheet).toHaveAttribute("aria-modal", "true");
    expect(sheet).toHaveAttribute("data-sheet");
    expect(within(sheet).getByRole("heading", { level: 2, name: "Pay" })).toBeInTheDocument();
    const close = within(sheet).getByRole("button", { name: "Close" });
    expect(close.className).toMatch(/\bsize-11\b/);
    expect(document.querySelector(".bg-scrim")).not.toBeNull();
    // no decorative grab handle that promises swipe-to-close
    expect(sheet.querySelector(".rounded-full.bg-line-strong")).toBeNull();
    // the content's own "Pay" eyebrow is hidden there (the sheet title says it)
    expect(within(sheet).getByText("Pay", { selector: "p" }).className).toMatch(/in-sheet:hidden/);
    // the page behind is out of reach
    expect(document.getElementById("root")).toHaveAttribute("inert");
    expect(document.body.style.overflow).toBe("hidden");
    await waitFor(() => expect(sheet).toHaveFocus());

    await user.tab();
    expect(close).toHaveFocus();
    await user.tab();
    await user.tab();
    expect(within(sheet).getByRole("button", { name: "Mark as paid" })).toHaveFocus();
    await user.tab();
    expect(close).toHaveFocus(); // wraps around instead of walking into the page

    await user.click(close);
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(document.getElementById("root")).not.toHaveAttribute("inert");
    expect(document.body.style.overflow).toBe("");
    expect(trigger).toHaveFocus();
  });

  it("a menu sheet says what it acts on", async () => {
    setViewport(390);
    const user = userEvent.setup();
    renderInRoot(
      <Menu label="Actions for Pay TechMarkt" heading="Pay TechMarkt" items={[{ label: "Mark done", onSelect: () => {} }]}>
        <Button>More</Button>
      </Menu>,
    );
    await user.click(screen.getByRole("button", { name: "More" }));
    const sheet = await screen.findByRole("dialog", { name: "Actions for Pay TechMarkt" });
    expect(within(sheet).getByRole("heading", { name: "Pay TechMarkt" })).toBeInTheDocument();
    const menu = within(sheet).getByRole("menu", { name: "Actions for Pay TechMarkt" });
    await waitFor(() => expect(within(menu).getByRole("menuitem", { name: "Mark done" })).toHaveFocus());
  });
});

// ------------------------------------------------------------------------------------------------
// Menu
// ------------------------------------------------------------------------------------------------

function DeleteMenu() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Menu
        label="More actions"
        items={[
          { label: "Add to calendar", onSelect: () => {} },
          { label: "Change date", onSelect: () => {} },
          "separator",
          { label: "Delete", danger: true, onSelect: () => setOpen(true) },
        ]}
      >
        <Button>More actions</Button>
      </Menu>
      <Button>After</Button>
      <Dialog open={open} onClose={() => setOpen(false)} title="Delete this letter?" footer={<Button onClick={() => setOpen(false)}>Keep it</Button>} />
    </>
  );
}

describe("Menu", () => {
  it("is one Tab stop: focus on the first item, arrows move it, Tab closes and moves on", async () => {
    setViewport(1280);
    const user = userEvent.setup();
    renderInRoot(<DeleteMenu />);
    await user.click(screen.getByRole("button", { name: "More actions" }));
    const menu = await screen.findByRole("menu", { name: "More actions" });
    const items = within(menu).getAllByRole("menuitem");
    await waitFor(() => expect(items[0]).toHaveFocus());
    expect(items.map((i) => i.tabIndex)).toEqual([0, -1, -1]);
    await user.keyboard("{ArrowDown}");
    expect(items[1]).toHaveFocus();
    expect(items.map((i) => i.tabIndex)).toEqual([-1, 0, -1]);
    await user.tab();
    expect(screen.getByRole("button", { name: "After" })).toHaveFocus();
    await waitFor(() => expect(screen.queryByRole("menu")).not.toBeInTheDocument());
  });

  it("marks the focused item with a tinted row and an accent ring, not just a faint background", async () => {
    setViewport(1280);
    const user = userEvent.setup();
    renderInRoot(<DeleteMenu />);
    await user.click(screen.getByRole("button", { name: "More actions" }));
    const item = within(await screen.findByRole("menu")).getAllByRole("menuitem")[0]!;
    expect(item.className).toMatch(/focus-visible:bg-accent-soft/);
    expect(item.className).toMatch(/focus-visible:ring-2/);
    expect(item.className).toMatch(/focus-visible:ring-accent\b/);
    // 44 px rows on phones (sheet), 36 px from tablets up
    expect(item.className).toMatch(/min-h-11/);
    expect(item.className).toMatch(/md:min-h-9/);
  });

  it("a dialog opened from an item gives focus back to the menu's trigger", async () => {
    setViewport(1280);
    const user = userEvent.setup();
    renderInRoot(<DeleteMenu />);
    const trigger = screen.getByRole("button", { name: "More actions" });
    await user.click(trigger);
    await waitFor(() => expect(within(screen.getByRole("menu")).getAllByRole("menuitem")[0]).toHaveFocus());
    await user.keyboard("{End}{Enter}");
    const dialog = await screen.findByRole("dialog", { name: "Delete this letter?" });
    await waitFor(() => expect(dialog).toHaveFocus());
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(trigger).toHaveFocus();
  });
});

// ------------------------------------------------------------------------------------------------
// Tooltip
// ------------------------------------------------------------------------------------------------

describe("Tooltip", () => {
  function InDrawer() {
    const [open, setOpen] = useState(true);
    return (
      <Drawer open={open} onClose={() => setOpen(false)} title="Stadt Musterstadt">
        <Tooltip content="Deadlines with them skip the public holidays of North Rhine-Westphalia." delay={0}>
          <span tabIndex={0}>Holidays: NRW</span>
        </Tooltip>
      </Drawer>
    );
  }

  it("Escape hides the tooltip, not the drawer around it", async () => {
    setViewport(1280);
    const user = userEvent.setup();
    renderInRoot(<InDrawer />);
    const drawer = screen.getByRole("dialog", { name: "Stadt Musterstadt" });
    await waitFor(() => expect(drawer).toHaveFocus());
    fireEvent.pointerEnter(screen.getByText("Holidays: NRW"), { pointerType: "mouse" });
    expect(await screen.findByRole("tooltip")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Stadt Musterstadt" })).toBeInTheDocument();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("stays open while the pointer is on it (hoverable), and closes after it leaves", async () => {
    renderWithProviders(
      <Tooltip content="Found on page 2" delay={0}>
        <button type="button">Evidence</button>
      </Tooltip>,
    );
    const trigger = screen.getByRole("button", { name: "Evidence" });
    fireEvent.pointerEnter(trigger, { pointerType: "mouse" });
    const tip = await screen.findByRole("tooltip");
    expect(tip.className).not.toMatch(/pointer-events-none/);
    fireEvent.pointerLeave(trigger, { pointerType: "mouse" });
    fireEvent.pointerEnter(tip, { pointerType: "mouse" });
    await sleep(250);
    expect(screen.getByRole("tooltip")).toBeInTheDocument();
    fireEvent.pointerLeave(tip, { pointerType: "mouse" });
    await waitFor(() => expect(screen.queryByRole("tooltip")).not.toBeInTheDocument());
  });

  it("a tap shows it (touch has no hover); a tap elsewhere or scrolling hides it", async () => {
    renderWithProviders(
      <div>
        <Tooltip content="Simulated date">
          <span tabIndex={0}>Demo · 28 Sep</span>
        </Tooltip>
        <p>Elsewhere</p>
      </div>,
    );
    const badge = screen.getByText("Demo · 28 Sep");
    fireEvent.pointerDown(badge, { pointerType: "touch" });
    expect(await screen.findByRole("tooltip")).toHaveTextContent("Simulated date");
    fireEvent.pointerDown(screen.getByText("Elsewhere"), { pointerType: "touch" });
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();

    fireEvent.pointerDown(badge, { pointerType: "touch" });
    expect(await screen.findByRole("tooltip")).toBeInTheDocument();
    fireEvent.scroll(window);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("hides when keyboard focus moves on to another control", async () => {
    renderWithProviders(
      <div>
        <Tooltip content="Simulated date" delay={0}>
          <span tabIndex={0}>Demo · 28 Sep</span>
        </Tooltip>
        <button type="button">TechMarkt Online GmbH</button>
      </div>,
    );
    fireEvent.pointerEnter(screen.getByText("Demo · 28 Sep"), { pointerType: "mouse" });
    expect(await screen.findByRole("tooltip")).toBeInTheDocument();
    act(() => screen.getByRole("button", { name: "TechMarkt Online GmbH" }).focus());
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("a mouse click on the trigger hides it (the action matters now)", async () => {
    renderWithProviders(
      <Tooltip content="Show on the page" delay={0}>
        <button type="button">p.1</button>
      </Tooltip>,
    );
    const trigger = screen.getByRole("button", { name: "p.1" });
    fireEvent.pointerEnter(trigger, { pointerType: "mouse" });
    expect(await screen.findByRole("tooltip")).toBeInTheDocument();
    fireEvent.pointerDown(trigger, { pointerType: "mouse" });
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });
});

// ------------------------------------------------------------------------------------------------
// Dialog & Drawer
// ------------------------------------------------------------------------------------------------

describe("Dialog", () => {
  it("gives focus back to its opener even when a field inside takes focus first (autoFocus)", async () => {
    function Search() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <Button onClick={() => setOpen(true)}>Search letters</Button>
          <Dialog open={open} onClose={() => setOpen(false)} title="Search letters" align="top">
            <input aria-label="Search your letters" autoFocus />
          </Dialog>
        </>
      );
    }
    const user = userEvent.setup();
    renderInRoot(<Search />);
    const opener = screen.getByRole("button", { name: "Search letters" });
    await user.click(opener);
    await waitFor(() => expect(screen.getByRole("textbox", { name: "Search your letters" })).toHaveFocus());
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(opener).toHaveFocus();
  });

  it("never takes focus back from where it moved before its first frame (a quick keyboard user, a list keeping its place)", async () => {
    // hold the dialog's first frame, like a busy machine does
    const frames: FrameRequestCallback[] = [];
    const realRaf = window.requestAnimationFrame;
    window.requestAnimationFrame = (cb) => {
      frames.push(cb);
      return frames.length;
    };
    try {
      function Confirm() {
        const primary = useRef<HTMLButtonElement>(null);
        return (
          <Dialog open onClose={() => {}} title="Add 2 letters?" initialFocus={primary} footer={<Button ref={primary}>Add letters</Button>}>
            <Button>Remove c.pdf</Button>
          </Dialog>
        );
      }
      renderInRoot(<Confirm />);
      const dialog = await screen.findByRole("dialog", { name: "Add 2 letters?" });
      const moved = within(dialog).getByRole("button", { name: "Remove c.pdf" });
      act(() => moved.focus());
      act(() => frames.splice(0).forEach((cb) => cb(performance.now())));
      expect(moved).toHaveFocus();
    } finally {
      window.requestAnimationFrame = realRaf;
    }
  });

  it("still moves focus to its initial element when nothing moved it first", async () => {
    const frames: FrameRequestCallback[] = [];
    const realRaf = window.requestAnimationFrame;
    window.requestAnimationFrame = (cb) => {
      frames.push(cb);
      return frames.length;
    };
    try {
      function Confirm() {
        const primary = useRef<HTMLButtonElement>(null);
        return <Dialog open onClose={() => {}} title="Add 2 letters?" initialFocus={primary} footer={<Button ref={primary}>Add letters</Button>} />;
      }
      renderInRoot(<Confirm />);
      const dialog = await screen.findByRole("dialog", { name: "Add 2 letters?" });
      act(() => frames.splice(0).forEach((cb) => cb(performance.now())));
      expect(within(dialog).getByRole("button", { name: "Add letters" })).toHaveFocus();
    } finally {
      window.requestAnimationFrame = realRaf;
    }
  });

  it("falls back to the page's main when the opener is gone", async () => {
    function Recap() {
      const [read, setRead] = useState(false);
      const [open, setOpen] = useState(false);
      return (
        <main tabIndex={-1}>
          {!read ? (
            <Button
              onClick={() => {
                setRead(true);
                setOpen(true);
              }}
            >
              Read all
            </Button>
          ) : null}
          <Dialog open={open} onClose={() => setOpen(false)} title="3 letters read" footer={<Button onClick={() => setOpen(false)}>Done</Button>} />
        </main>
      );
    }
    const user = userEvent.setup();
    renderInRoot(<Recap />);
    await user.click(screen.getByRole("button", { name: "Read all" }));
    await screen.findByRole("dialog", { name: "3 letters read" });
    await user.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByRole("main")).toHaveFocus();
  });

  it("lays out its parts: scrim, room under a body-less header, focused fields clear of the footer, safe-area footer", async () => {
    const { rerender } = renderInRoot(<Dialog open onClose={() => {}} title="Discard your changes?" description="You changed something." footer={<Button>Discard</Button>} />);
    const dialog = await screen.findByRole("dialog", { name: "Discard your changes?" });
    expect(document.querySelector(".bg-scrim.backdrop-blur-\\[2px\\]")).not.toBeNull();
    const header = within(dialog).getByRole("heading", { name: "Discard your changes?" }).parentElement!.parentElement!;
    expect(header.className).toMatch(/pb-5 sm:pb-6/);
    const footer = within(dialog).getByRole("button", { name: "Discard" }).parentElement!;
    expect(footer.className).toMatch(/pb-\[calc\(1rem\+env\(safe-area-inset-bottom\)\)\]/);
    expect(within(dialog).getByRole("button", { name: "Close" }).className).toMatch(/\bsize-11\b.*sm:size-8|sm:size-8.*\bsize-11\b/);

    rerender(
      <Dialog open onClose={() => {}} title="Your wishes" footer={<Button>Write</Button>}>
        <textarea aria-label="Your wishes" />
      </Dialog>,
    );
    const body = screen.getByRole("textbox", { name: "Your wishes" }).parentElement!;
    expect(body.className).toMatch(/scroll-py-6/);
    expect(body.className).toMatch(/overscroll-contain/);
    let revealed = false;
    Element.prototype.scrollIntoView = function () {
      revealed = true;
    };
    fireEvent.focus(screen.getByRole("textbox", { name: "Your wishes" }));
    expect(revealed).toBe(true);
  });
});

describe("Drawer", () => {
  function Party({ size }: { size?: "md" | "lg" }) {
    return (
      <Drawer open onClose={() => {}} title="Stadt Musterstadt – Ordnungsamt (Bußgeldstelle)" eyebrow="People & organisations" size={size} headerExtra={<span>Authority</span>}>
        <p>1 letter</p>
      </Drawer>
    );
  }

  it("on phones: full width without a stray border, only the title pinned (chips scroll with the body)", async () => {
    setViewport(390);
    renderInRoot(<Party />);
    const drawer = await screen.findByRole("dialog", { name: /Ordnungsamt/ });
    expect(drawer.className).toMatch(/sm:border-l/);
    expect(drawer.className).not.toMatch(/(^|\s)border-l(\s|$)/);
    expect(within(drawer).getByRole("banner").textContent).not.toContain("Authority");
    expect(screen.getByText("Authority").closest(".overflow-y-auto")).not.toBeNull();
    expect(document.querySelector(".bg-scrim")).not.toBeNull();
  });

  it("from tablets up: header extras in the header, the Dialog's title size, and a wider `lg`", async () => {
    setViewport(1920);
    renderInRoot(<Party size="lg" />);
    const drawer = await screen.findByRole("dialog", { name: /Ordnungsamt/ });
    expect(within(drawer).getByRole("banner")).toHaveTextContent("Authority");
    expect(within(drawer).getByRole("heading", { level: 2 }).className).toMatch(/text-title/);
    expect(drawer.className).toMatch(/lg:max-w-lg/);
    expect(drawer.className).toMatch(/2xl:max-w-xl/);
  });
});
