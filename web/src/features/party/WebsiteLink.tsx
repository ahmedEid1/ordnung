import { ExternalLink } from "lucide-react";
import { cn } from "@/lib/utils";

/** How many of the address's last characters stay on one line with the new-tab icon. */
const TAIL = 4;

/**
 * A website from their letters, opening in a new tab. A long address wraps where it must
 * ("www.rundfunkbeitrag-musterstadt.example"); the new-tab icon follows its last characters on the
 * last line — never alone on a line of its own, and never at the far edge of a wrapped box (the link
 * is text, not a flex row). At least 24 px tall (WCAG 2.5.8).
 */
export function WebsiteLink({ href, website, className }: { href: string; website: string; className?: string }) {
  const text = website.replace(/^https?:\/\//, "");
  const chars = Array.from(text);
  const head = chars.slice(0, -TAIL).join("");
  const tail = chars.slice(-TAIL).join("");
  return (
    <a href={href} target="_blank" rel="noreferrer noopener" className={cn("block min-h-6 min-w-0 py-0.5 [overflow-wrap:anywhere]", className)}>
      {head}
      <span className="whitespace-nowrap">
        {tail}
        <ExternalLink className="ml-1 inline size-3 align-[-1px]" aria-hidden />
      </span>
      <span className="sr-only">(opens in a new tab)</span>
    </a>
  );
}
