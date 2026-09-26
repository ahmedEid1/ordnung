import { useRef, useState, type KeyboardEvent, type ReactElement } from "react";
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
  label?: string;
}

/**
 * Dropdown action menu with arrow-key navigation (↑/↓/Home/End), Enter/Space to select,
 * Escape to close.
 *
 * @example <Menu items={[{label: "Reprocess", icon: RotateCw, onSelect}]}><IconButton icon={Ellipsis} label="More" /></Menu>
 */
export function Menu({ children, items, placement = "bottom-end", label = "Actions" }: MenuProps) {
  const [open, setOpen] = useState(false);
  const listRef = useRef<HTMLDivElement | null>(null);

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
      onOpenChange={setOpen}
      placement={placement}
      role="menu"
      label={label}
      className="w-56 p-1.5"
      content={(close) => (
        <div ref={listRef} onKeyDown={onKeyDown} className="flex flex-col">
          {items.map((item, i) =>
            item === "separator" ? (
              <div key={`sep-${i}`} role="separator" className="my-1 h-px bg-line" />
            ) : (
              <button
                key={item.label}
                type="button"
                role="menuitem"
                disabled={item.disabled}
                onClick={() => {
                  close();
                  item.onSelect();
                }}
                className={cn(
                  "flex h-9 w-full items-center gap-2.5 rounded-lg px-2.5 text-left text-base outline-none transition-colors",
                  "hover:bg-surface-2 focus-visible:bg-surface-2 focus-visible:outline-none disabled:opacity-50",
                  item.danger ? "text-danger-ink" : "text-ink",
                )}
              >
                {item.icon ? <item.icon className={cn("size-4 shrink-0", item.danger ? "" : "text-muted")} aria-hidden /> : null}
                <span className="flex-1 truncate">{item.label}</span>
                {item.hint ? <span className="text-xs text-muted">{item.hint}</span> : null}
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
