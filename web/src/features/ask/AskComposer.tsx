import { useLayoutEffect, useRef, type FormEvent, type KeyboardEvent, type Ref } from "react";
import { ArrowUp, Square } from "lucide-react";
import { cn } from "@/lib/utils";
import { mergeRefs } from "@/components/ui/internal";
import { useIsTabletUp } from "@/lib/hooks";

export interface AskComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: (question: string) => void;
  onStop: () => void;
  streaming: boolean;
  textareaRef?: Ref<HTMLTextAreaElement>;
  className?: string;
}

const MAX_ROWS_PX = 180;

/**
 * The question box: grows with its text, Enter sends (Shift+Enter for a new line), and turns
 * into a Stop button while an answer streams.
 */
export function AskComposer({ value, onChange, onSubmit, onStop, streaming, textareaRef, className }: AskComposerProps) {
  const local = useRef<HTMLTextAreaElement | null>(null);
  const wide = useIsTabletUp();

  useLayoutEffect(() => {
    const el = local.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, MAX_ROWS_PX)}px`;
  }, [value]);

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    if (streaming) return;
    const q = value.trim();
    if (q) onSubmit(q);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  };

  const canSend = Boolean(value.trim()) && !streaming;

  return (
    <form
      onSubmit={submit}
      className={cn(
        "flex items-end gap-2 rounded-2xl border border-line-strong/80 bg-surface p-2 pl-4 shadow-[var(--shadow-pop)] transition-[border-color,box-shadow]",
        "focus-within:border-accent/60 focus-within:ring-3 focus-within:ring-accent/15",
        className,
      )}
    >
      <label htmlFor="ask-input" className="sr-only">
        Your question
      </label>
      <textarea
        id="ask-input"
        ref={mergeRefs(local, textareaRef)}
        rows={1}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={onKeyDown}
        placeholder={wide ? "Ask about your letters, dates, money or contracts…" : "Ask about your letters…"}
        aria-describedby="ask-hint"
        className="max-h-[180px] min-h-[40px] flex-1 resize-none bg-transparent py-2 text-[15px] leading-6 text-ink outline-none placeholder:text-muted/80 scrollbar-thin"
      />
      {streaming ? (
        <button
          type="button"
          onClick={onStop}
          className="grid size-10 shrink-0 place-items-center rounded-xl border border-line-strong bg-surface-2 text-ink transition-colors hover:bg-surface-3 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          aria-label="Stop the answer"
          title="Stop"
        >
          <Square className="size-3.5 fill-current" aria-hidden />
        </button>
      ) : (
        <button
          type="submit"
          disabled={!canSend}
          className="grid size-10 shrink-0 place-items-center rounded-xl bg-accent text-on-accent shadow-[inset_0_1px_0_rgb(255_255_255/0.14),0_1px_2px_rgb(0_0_0/0.14)] transition-[background-color,opacity] hover:bg-accent-strong disabled:bg-surface-3 disabled:text-faint disabled:shadow-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          aria-label="Ask"
          title="Ask (Enter)"
        >
          <ArrowUp className="size-[18px]" aria-hidden />
        </button>
      )}
    </form>
  );
}
