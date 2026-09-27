import { Fragment, type ReactNode } from "react";
import { Check, Copy } from "lucide-react";
import { cn } from "@/lib/utils";
import { useClipboard } from "@/features/today/clipboard";

/**
 * A terminal command with a copy button ("Copied" is announced to screen readers). A long command
 * wraps instead of scrolling out of sight: at spaces, after a "/" of a package name, and only as
 * a last resort inside a word — the whole command is always visible (and copied exactly). `display`
 * shows the command with its own line-break opportunities (the button still copies `command`).
 */
export function CopyCommand({ command, label, className, display }: { command: string; label?: string; className?: string; display?: ReactNode }) {
  const { copy, copied } = useClipboard();
  const done = copied === command;
  const parts = command.split(/(?<=\/)/);
  return (
    <div className={cn("flex items-start gap-2 rounded-xl border border-line bg-[#1d1b16] py-1.5 pl-3.5 pr-1.5 text-[#f2efe7] dark:bg-canvas", className)}>
      <span aria-hidden className="select-none py-1.5 font-mono text-[13px] leading-5 text-[#9a937f]">
        $
      </span>
      <code className="min-w-0 flex-1 whitespace-pre-wrap py-1.5 font-mono text-[13px] leading-5 [overflow-wrap:anywhere]">
        {display ??
          parts.map((p, i) => (
            <Fragment key={i}>
              {i > 0 ? <wbr /> : null}
              {p}
            </Fragment>
          ))}
      </code>
      <button
        type="button"
        onClick={() => void copy(command)}
        aria-label={done ? `Copied: ${command}` : `Copy command${label ? ` to ${label}` : ""}: ${command}`}
        className={cn(
          "inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg px-2.5 text-[12.5px] font-medium transition-colors",
          done ? "bg-[#15302d] text-[#7fd6cc]" : "text-[#d8d3c7] hover:bg-white/10 hover:text-white",
        )}
      >
        {done ? <Check className="size-3.5" aria-hidden /> : <Copy className="size-3.5" aria-hidden />}
        <span aria-hidden>{done ? "Copied" : "Copy"}</span>
      </button>
      <span className="sr-only" aria-live="polite">
        {done ? "Copied to the clipboard" : ""}
      </span>
    </div>
  );
}
