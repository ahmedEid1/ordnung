import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import { useReducedMotion } from "motion/react";
import { Lock, MessagesSquare, SquarePen } from "lucide-react";
import { useHealth } from "@/api/hooks";
import { isStaticDemo } from "@/mocks/mode";
import { Page } from "@/components/shell/Page";
import { Button } from "@/components/ui/Button";
import { Skeleton, SkeletonText, LoadingLabel } from "@/components/ui/Skeleton";
import { AskComposer } from "@/features/ask/AskComposer";
import { AskTurnView } from "@/features/ask/AskTurnView";
import { SuggestedQuestions } from "@/features/ask/SuggestedQuestions";
import { isSuggestedQuestion } from "@/features/ask/suggestions";
import { useAskThread } from "@/features/ask/useAskThread";
import { useRefResolver } from "@/features/ask/refs";

/** `/ask` — questions about your letters, answered with a visible tool trace and cited sources. */
export default function AskPage() {
  const thread = useAskThread();
  const { resolve, titleOf } = useRefResolver();
  const [params, setParams] = useSearchParams();
  const [draft, setDraft] = useState(() => params.get("q") ?? "");
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const reduce = useReducedMotion();
  const health = useHealth();
  const replayDemo = isStaticDemo() || health.data?.backend === "replay";

  // `?q=` (e.g. "Ask about them" in the People drawer) pre-fills the question once
  useEffect(() => {
    if (!params.get("q")) return;
    inputRef.current?.focus();
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete("q");
        return next;
      },
      { replace: true },
    );
  }, [params, setParams]);

  const send = (q: string) => {
    void thread.ask(q);
    setDraft("");
    // a chip that started the question disappears — keep keyboard focus in the question box
    // (not on touch screens, where focusing would pop up the keyboard)
    if (window.matchMedia?.("(pointer: fine)").matches) inputRef.current?.focus({ preventScroll: true });
  };

  const last = thread.turns[thread.turns.length - 1];
  const lastKey = last?.key;
  const lastLen = last?.answer.text.length ?? 0;

  // a new question scrolls into view at the top
  useEffect(() => {
    if (!lastKey) return;
    const el = document.querySelector<HTMLElement>(`[data-turn="${lastKey}"]`);
    el?.scrollIntoView?.({ block: "start", behavior: reduce ? "auto" : "smooth" });
  }, [lastKey, reduce]);

  // while it streams, keep the growing answer visible — but never scroll the question away
  useEffect(() => {
    if (!thread.streaming || !lastKey) return;
    const el = document.querySelector<HTMLElement>(`[data-turn="${lastKey}"]`);
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const composerSpace = window.innerWidth < 768 ? 190 : 130;
    const overflow = rect.bottom - (window.innerHeight - composerSpace);
    const room = rect.top - 72;
    if (overflow > 0 && room > 0) window.scrollBy({ top: Math.min(overflow, room) });
  }, [lastLen, thread.streaming, lastKey]);

  // stored conversation: start at its end
  const hadHistory = thread.past.length > 0;
  useEffect(() => {
    if (hadHistory) window.scrollTo({ top: document.documentElement.scrollHeight });
  }, [hadHistory]);

  const empty = !thread.all.length && !thread.loadingHistory;
  const asked = thread.all.map((t) => t.question);
  const announce = last
    ? last.answer.status === "streaming"
      ? "Looking through your records…"
      : last.answer.status === "done"
        ? "Answer ready."
        : last.answer.status === "error"
          ? "The answer could not be completed."
          : "Stopped."
    : "";

  return (
    <Page title="Ask" width="narrow" className="flex min-h-[calc(100dvh-3.5rem)] flex-col pb-0 md:pb-0">
      <p className="sr-only" aria-live="polite" role="status">
        {announce}
      </p>

      {empty ? (
        <section aria-labelledby="ask-title" className="flex flex-1 flex-col justify-center pb-6 pt-4 sm:pt-10">
          <div className="text-center">
            <span className="mx-auto mb-5 grid size-12 place-items-center rounded-2xl bg-accent-soft text-accent">
              <MessagesSquare className="size-6" aria-hidden />
            </span>
            <h1 id="ask-title" className="display text-[30px] font-semibold leading-tight text-ink sm:text-[38px]">
              Ask about your letters
            </h1>
            <p className="mx-auto mt-2.5 max-w-md text-[15px] leading-relaxed text-muted">
              Plain-English answers from your own records. Every answer shows what it looked at and links to the letter it comes from.
            </p>
          </div>
          <SuggestedQuestions className="mt-8" onPick={send} />
          <p className="mx-auto mt-6 flex max-w-lg items-start justify-center gap-2 text-center text-[12.5px] leading-5 text-muted">
            <Lock className="mt-0.5 size-3.5 shrink-0" aria-hidden />
            <span>
              Claude searches your records with read-only tools. Only the letters it opens are sent to Anthropic, through your own Claude account.
            </span>
          </p>
        </section>
      ) : (
        <div className="flex-1">
          <div className="mb-6 flex items-center gap-3">
            <h1 className="display min-w-0 flex-1 truncate text-[22px] font-semibold text-ink">Ask about your letters</h1>
            <Button size="sm" variant="ghost" icon={SquarePen} onClick={thread.newChat} disabled={thread.loadingHistory}>
              New chat
            </Button>
          </div>

          {thread.loadingHistory ? (
            <div aria-busy="true" className="space-y-8">
              <LoadingLabel>Loading your conversation…</LoadingLabel>
              {[0, 1].map((i) => (
                <div key={i} className="space-y-4">
                  <Skeleton className="ml-auto h-10 w-2/3 rounded-2xl" />
                  <div className="flex gap-3">
                    <Skeleton className="size-7 rounded-lg" />
                    <SkeletonText lines={3} className="flex-1" />
                  </div>
                </div>
              ))}
            </div>
          ) : null}

          <div className="space-y-10">
            {thread.all.map((turn) => (
              <AskTurnView
                key={turn.key}
                turn={turn}
                resolve={resolve}
                titleOf={titleOf}
                onRetry={thread.turns.includes(turn) ? () => thread.retry(turn.key) : undefined}
                demoNote={isStaticDemo() && !isSuggestedQuestion(turn.question)}
              />
            ))}
          </div>

          {!thread.streaming && !thread.loadingHistory ? (
            <div className="mt-10">
              <SuggestedQuestions variant="row" exclude={asked} onPick={send} />
            </div>
          ) : null}
        </div>
      )}

      {/* on phones the demo tour's bar sits above the tab bar: the composer stays above both */}
      <div className="sticky bottom-[calc(4rem+env(safe-area-inset-bottom)+var(--ordnung-toast-lift,0px))] z-10 -mx-4 mt-6 bg-linear-to-t from-canvas from-70% to-transparent px-4 pb-3 pt-6 sm:-mx-6 sm:px-6 md:bottom-0 md:pb-5 lg:-mx-10 lg:px-10">
        <AskComposer value={draft} onChange={setDraft} onSubmit={send} onStop={thread.stop} streaming={thread.streaming} textareaRef={inputRef} />
        <p id="ask-hint" className="mt-2 text-center text-[12px] leading-5 text-muted">
          {replayDemo ? "Demo: suggested questions replay recorded answers. " : null}
          Answers can be wrong — check the source. Not legal advice.
        </p>
      </div>
    </Page>
  );
}
