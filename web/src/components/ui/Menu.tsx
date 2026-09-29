import { useRef, useState, type KeyboardEvent, type ReactElement, type ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { Popover } from "./Popover";
import type { Placement } from "./internal";

export interface MenuItem {
  label: string;
  icon?: LucideIcon;
  onSelect: () => void;
  /** Destructive styling. */
  danger?: boolean;
  disabled?: boolean;
  /** Short hint on the right (e.g. a keyboard shortcut). */
  hint?: string;
}

export interface MenuProps {
  /** Trigger element (usually an IconButton with an Ellipsis icon). */
  children: ReactElement;
  items: (MenuItem | "separator")[];
  placement?: Placement;
  /** Accessible name of the menu. */
  label?: string;
  /** Title of the phone sheet: what the menu acts on (e.g. the to-do's title). Default: `label`. */
  heading?: ReactNode;
}

/**
 * Dropdown action menu (a bottom sheet on phones). Focus goes to the first item; ↑/↓/Home/End move
 * between items (one Tab stop: a roving tabindex), Enter/Space select, Escape closes and returns
 * to the trigger, Tab closes and moves on from the trigger.
 *
 * @example <Menu items={[{label: "Reprocess", icon: RotateCw, onSelect}]}><IconButton icon={Ellipsis} label="More" /></Menu>
 */
export function Menu({ children, items, placement = "bottom-end", label = "Actions", heading }: MenuProps) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const listRef = useRef<HTMLDivElement | null>(null);
  const firstEnabled = Math.max(
    0,
    items.findIndex((item) => item !== "separator" && !item.disabled),
  );

  const onOpenChange = (v: boolean) => {
    if (v) setActive(firstEnabled);
    setOpen(v);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const buttons = Array.from(listRef.current?.querySelectorAll<HTMLButtonElement>("[role=menuitem]:not([disabled])") ?? []);
    const i = buttons.indexOf(document.activeElement as HTMLButtonElement);
    let next = -1;
    if (e.key === "ArrowDown") next = (i + 1) % buttons.length;
    else if (e.key === "ArrowUp") next = (i - 1 + buttons.length) % buttons.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = buttons.length - 1;
    if (next >= 0) {
      e.preventDefault();
      buttons[next]?.focus();
    }
  };

  return (
    <Popover
      open={open}
      onOpenChange={onOpenChange}
      placement={placement}
      role="menu"
      label={label}
      title={heading ?? label}
      autoFocus="first"
      className="w-56 p-1.5"
      content={(close) => (
        <div ref={listRef} onKeyDown={onKeyDown} className="flex flex-col in-sheet:-mx-2.5">
          {items.map((item, i) =>
            item === "separator" ? (
              <div key={`sep-${i}`} role="separator" className="my-1 h-px bg-line" />
            ) : (
              <button
                key={item.label}
                type="button"
                role="menuitem"
                tabIndex={i === active ? 0 : -1}
                disabled={item.disabled}
                onFocus={() => setActive(i)}
                onClick={() => {
                  close();
                  item.onSelect();
                }}
                className={cn(
                  "flex min-h-11 w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left text-base transition-colors md:min-h-9",
                  // the focused item: a tinted row and an inset accent ring (≥ 3:1 in both themes)
                  "outline-none hover:bg-surface-2 focus-visible:bg-accent-soft focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent disabled:opacity-50",
                  item.danger ? "text-danger-ink" : "text-ink",
                )}
              >
                {item.icon ? <item.icon className={cn("size-4 shrink-0", item.danger ? "" : "text-muted")} aria-hidden /> : null}
                <span className="min-w-0 flex-1 truncate">{item.label}</span>
                {item.hint ? <span className="shrink-0 text-xs text-muted">{item.hint}</span> : null}
              </button>
            ),
          )}
        </div>
      )}
    >
      {children}
    </Popover>
  );
}
