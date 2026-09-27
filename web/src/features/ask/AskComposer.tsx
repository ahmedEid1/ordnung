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
  /** Enter was pressed while an answer is still being written (nothing is sent: say why). */
  onBusy?: () => void;
  textareaRef?: Ref<HTMLTextAreaElement>;
  className?: string;
}

const MAX_ROWS_PX = 180;

/**
 * The question box: grows with its text (at most 180 px, less on a short phone screen), Enter sends
 * (Shift+Enter for a new line), and its button turns into Stop while an answer streams.
 *
 * Send and Stop are one button that changes its role, so keyboard focus stays on it when an answer
 * starts or ends (UI audit round 1: two buttons swapped places and focus fell back to the page). It is
 * never `disabled` for the same reason: with nothing typed it only says so (`aria-disabled`).
 */
export function AskComposer({ value, onChange, onSubmit, onStop, streaming, onBusy, textareaRef, className }: AskComposerProps) {
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
    const q = value.trim();
    if (streaming) {
      if (q) onBusy?.();
      return;
    }
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
        // a long question leaves a short phone screen room for the answer above it (UI audit round 1)
        className="max-h-[min(180px,25dvh)] min-h-[40px] flex-1 resize-none bg-transparent py-2 text-[15px] leading-6 text-ink outline-none placeholder:text-muted scrollbar-thin"
      />
      <button
        type={streaming ? "button" : "submit"}
        onClick={streaming ? onStop : undefined}
        aria-disabled={canSend || streaming ? undefined : true}
        aria-label={streaming ? "Stop the answer" : "Ask"}
        title={streaming ? "Stop" : "Ask (Enter)"}
        data-ask-button={streaming ? "stop" : "send"}
        className={cn(
          "grid size-10 shrink-0 place-items-center rounded-xl transition-[background-color,border-color,opacity] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
          streaming
            ? "border border-line-strong bg-surface-2 text-ink hover:bg-surface-3"
            : canSend
              ? "bg-accent text-on-accent shadow-[inset_0_1px_0_rgb(255_255_255/0.14),0_1px_2px_rgb(0_0_0/0.14)] hover:bg-accent-strong"
              : "cursor-default bg-surface-3 text-faint",
        )}
      >
        {streaming ? <Square className="size-3.5 fill-current" aria-hidden /> : <ArrowUp className="size-[18px]" aria-hidden />}
      </button>
    </form>
  );
}
