import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** Keyboard key hint: <Kbd>⌘</Kbd><Kbd>K</Kbd>. */
export function Kbd({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <kbd
      className={cn(
        "inline-grid h-5 min-w-5 place-items-center rounded-[5px] border border-line-strong/80 bg-surface px-1 font-sans text-[11px] font-medium leading-none text-muted shadow-[0_1px_0_var(--color-line-strong)]",
        className,
      )}
    >
      {children}
    </kbd>
  );
}
