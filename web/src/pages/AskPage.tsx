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
  // the answer's words only come once checked (ADR 0008): while it is worked on, the trace's steps and the
  // "Writing the answer" line are what grows (review round 2: they grew behind the composer on phones)
  const lastSteps = last?.answer.tools.length ?? 0;
  const lastWriting = last?.answer.writing ?? false;
  const lastStatus = last?.answer.status;

  // the sticky composer covers the bottom of the screen: its height is published (--ask-composer-h) so that
  // whatever gets focus or is scrolled to stops clear of it, as of the tab bar (WCAG 2.4.11, review round 2)
  const composerRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const el = composerRef.current;
    const root = document.documentElement;
    if (!el) return;
    const publish = () => root.style.setProperty("--ask-composer-h", `${Math.ceil(el.getBoundingClientRect().height)}px`);
    publish();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(publish);
    observer?.observe(el);
    return () => {
      observer?.disconnect();
      root.style.removeProperty("--ask-composer-h");
    };
  }, []);

  // a new question scrolls into view at the top
  useEffect(() => {
    if (!lastKey) return;
    const el = document.querySelector<HTMLElement>(`[data-turn="${lastKey}"]`);
    el?.scrollIntoView?.({ block: "start", behavior: reduce ? "auto" : "smooth" });
  }, [lastKey, reduce]);

  // while it is worked on — and when it arrives — keep the growing turn visible above the composer (and, on
  // phones, the tab bar), but never scroll the question away
  useEffect(() => {
    if (!lastKey || (!thread.streaming && lastStatus !== "done")) return;
    const el = document.querySelector<HTMLElement>(`[data-turn="${lastKey}"]`);
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const composer = composerRef.current?.getBoundingClientRect();
    const covered = composer ? window.innerHeight - composer.top : window.innerWidth < 768 ? 190 : 130;
    const overflow = rect.bottom - (window.innerHeight - covered);
    const room = rect.top - 72;
    if (overflow > 0 && room > 0) window.scrollBy({ top: Math.min(overflow, room) });
  }, [lastLen, lastSteps, lastWriting, lastStatus, thread.streaming, lastKey]);

  // stored conversation: start at its end
  const hadHistory = thread.past.length > 0;
  useEffect(() => {
    if (hadHistory) window.scrollTo({ top: document.documentElement.scrollHeight });
  }, [hadHistory]);

  const empty = !thread.all.length && !thread.loadingHistory;
  const asked = thread.all.map((t) => t.question);
  const announce = last
    ? last.answer.status === "streaming"
      ? last.answer.writing
        ? "Writing the answer — it appears once Ordnung has checked it."
        : "Looking through your records…"
      : last.answer.status === "done"
        ? "Answer ready."
        : last.answer.status === "error"
          ? "The answer could not be completed."
          : "Stopped."
    : "";

  return (
    <Page title="Ask" width="narrow" className="flex flex-1 flex-col pb-0 md:pb-0">
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
            {/* on the narrowest phones the title needs the room: the button keeps its icon and name */}
            <Button size="sm" variant="ghost" icon={SquarePen} onClick={thread.newChat} disabled={thread.loadingHistory} title="New chat">
              <span className="max-[359px]:sr-only">New chat</span>
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
      {/* opaque down to the screen's edge (under the see-through tab bar too), so the answer never
          shows around the tour's bar or through the tab bar */}
      <div ref={composerRef} data-ask-composer className="sticky bottom-[calc(4rem+env(safe-area-inset-bottom))] z-10 -mx-4 mt-6 bg-linear-to-t from-canvas from-80% to-transparent px-4 pb-[calc(0.75rem+var(--ordnung-toast-lift,0px))] pt-6 after:pointer-events-none after:absolute after:inset-x-0 after:top-full after:h-[calc(4rem+env(safe-area-inset-bottom))] after:bg-canvas sm:-mx-6 sm:px-6 md:bottom-0 md:pb-[calc(1.25rem+var(--ordnung-toast-lift,0px))] md:after:hidden lg:-mx-10 lg:px-10">
        <AskComposer value={draft} onChange={setDraft} onSubmit={send} onStop={thread.stop} streaming={thread.streaming} textareaRef={inputRef} />
        <p id="ask-hint" className="mt-2 text-center text-[12px] leading-5 text-muted">
          {replayDemo ? "Demo: suggested questions replay recorded answers. " : null}
          Answers can be wrong — check the source. Not legal advice.
        </p>
      </div>
    </Page>
  );
}
