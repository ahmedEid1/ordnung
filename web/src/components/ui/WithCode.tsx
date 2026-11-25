import { Fragment } from "react";
import { cn } from "@/lib/utils";

/** How a command reads inside a sentence. */
export const inlineCode = "rounded bg-surface-2 px-1 py-px font-mono text-[12px] text-ink";

/**
 * A message from the server with its `commands` (in backticks, as the command line prints them) set as code:
 * never literal backticks. Used by Settings → Claude connection's checks and a letter's failure card.
 */
export function WithCode({ text }: { text: string }) {
  return (
    <>
      {text.split(/`([^`]+)`/).map((part, i) =>
        i % 2 ? (
          <code key={i} className={cn(inlineCode, "whitespace-nowrap")}>
            {part}
          </code>
        ) : (
          <Fragment key={i}>{part}</Fragment>
        ),
      )}
    </>
  );
}
