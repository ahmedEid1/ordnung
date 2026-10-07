/**
 * What only the computer does (deleting, downloading files and PDFs, held-letter decisions, settings): shown on
 * the computer, left out on a paired phone — where the API refuses it anyway (403 `computer_only`), so a phone
 * never offers a button that can only fail.
 */
import type { ReactNode } from "react";
import { Laptop } from "lucide-react";
import { usePhoneCompanion } from "./client";
import { cn } from "@/lib/utils";

export interface ComputerOnlyProps {
  /** What is left out on a phone, for whoever reads the code ("Delete this letter"). */
  what: string;
  /** What a phone shows instead (nothing by default). */
  fallback?: ReactNode;
  children: ReactNode;
}

/** `children` on the computer; `fallback` (or nothing) on a phone. */
export function ComputerOnly({ fallback = null, children }: ComputerOnlyProps) {
  return <>{usePhoneCompanion() ? fallback : children}</>;
}

/** Where something is done instead, on a phone: a quiet line with a laptop ("Delete or download it on your computer."). */
export function OnYourComputer({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <p data-on-computer="" className={cn("flex items-start gap-1.5 text-[12.5px] leading-5 text-muted", className)}>
      <Laptop className="mt-[3px] size-3.5 shrink-0" aria-hidden />
      <span className="min-w-0">{children}</span>
    </p>
  );
}
