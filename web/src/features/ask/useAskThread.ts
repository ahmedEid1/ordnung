/**
 * One Ask conversation: the stored history of the thread (`GET /api/chat/{thread}`) plus the
 * turns asked in this session, each accumulated from the answer stream (`POST /api/ask`).
 *
 * The thread id is remembered in localStorage, so the conversation is still there after a
 * reload. History is loaded once per thread; new turns live locally (no refetch → no flicker,
 * no duplicates). "New chat" forgets the thread.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, ApiError, qk, useChat } from "@/api";
import type { ChatMessage } from "@/api/types";
import { accumulate, EMPTY_ANSWER, toolStepsFromStored, type AnswerState } from "./stream";
import type { CitationRef } from "./citations";

export const THREAD_STORAGE_KEY = "ordnung.ask.thread";

export interface AskTurn {
  key: string;
  question: string;
  answer: AnswerState;
}

function readThread(): string | null {
  try {
    return localStorage.getItem(THREAD_STORAGE_KEY);
  } catch {
    return null;
  }
}

function writeThread(id: string | null) {
  try {
    if (id) localStorage.setItem(THREAD_STORAGE_KEY, id);
    else localStorage.removeItem(THREAD_STORAGE_KEY);
  } catch {
    /* storage unavailable: the thread just isn't remembered */
  }
}

/** Turn stored messages into question/answer turns (exported for tests). */
export function turnsFromHistory(messages: ChatMessage[]): AskTurn[] {
  const turns: AskTurn[] = [];
  let pending: string | null = null;
  for (const m of messages) {
    if (m.role === "user") {
      if (pending !== null) turns.push({ key: `h-${turns.length}`, question: pending, answer: { ...EMPTY_ANSWER, status: "error", error: "No answer was saved for this question." } });
      pending = m.content;
      continue;
    }
    turns.push({
      key: m.id,
      question: pending ?? "",
      answer: {
        status: "done",
        text: m.content,
        writing: false,
        note: m.note ?? null,
        noteLabel: m.note_label ?? null,
        // answers stored before the claim-level check (ADR 0008) are not shown as checked
        checked: Boolean(m.checked),
        tools: toolStepsFromStored(m.tool_calls ?? []),
        citations: (m.citations ?? []) as CitationRef[],
        messageId: m.id,
        threadId: m.thread_id,
        error: null,
      },
    });
    pending = null;
  }
  return turns;
}

let seq = 0;

export function useAskThread() {
  const qc = useQueryClient();
  const [threadId, setThreadId] = useState<string | null>(readThread);
  const threadRef = useRef(threadId);
  // history is loaded for the thread we started with; later turns are kept locally
  const [historyThread, setHistoryThread] = useState<string | null>(threadId);
  const history = useChat(historyThread);
  const [turns, setTurns] = useState<AskTurn[]>([]);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  const setThread = useCallback((id: string | null) => {
    threadRef.current = id;
    setThreadId(id);
    writeThread(id);
  }, []);

  const update = useCallback((key: string, fn: (a: AnswerState) => AnswerState) => {
    setTurns((ts) => ts.map((t) => (t.key === key ? { ...t, answer: fn(t.answer) } : t)));
  }, []);

  const ask = useCallback(
    async (question: string) => {
      const q = question.trim();
      if (!q) return;
      abortRef.current?.abort();
      const ctrl = new AbortController();
      abortRef.current = ctrl;
      const key = `t${Date.now().toString(36)}${++seq}`;
      setTurns((ts) => [
        ...ts.map((t) => (t.answer.status === "streaming" ? { ...t, answer: { ...t.answer, status: "stopped" as const, writing: false } } : t)),
        { key, question: q, answer: { ...EMPTY_ANSWER } },
      ]);
      try {
        for await (const ev of api.ask({ question: q, thread_id: threadRef.current }, ctrl.signal)) {
          if (ctrl.signal.aborted) return;
          if (ev.thread_id && ev.thread_id !== threadRef.current) setThread(ev.thread_id);
          update(key, (s) => accumulate(s, ev));
          if (ev.type === "done" && ev.thread_id) {
            // stale for the next visit, without refetching (and duplicating) this session's turns
            void qc.invalidateQueries({ queryKey: qk.chat(ev.thread_id), refetchType: "none" });
          }
        }
        update(key, (s) => (s.status === "streaming" ? { ...s, status: "done" } : s));
      } catch (err) {
        if (ctrl.signal.aborted) return;
        const message = err instanceof ApiError ? err.message : "The answer was interrupted. Please try again.";
        update(key, (s) => ({ ...s, status: "error", error: message, tools: s.tools.map((t) => ({ ...t, done: true })) }));
      } finally {
        if (abortRef.current === ctrl) abortRef.current = null;
      }
    },
    [qc, setThread, update],
  );

  const stop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setTurns((ts) =>
      ts.map((t) =>
        t.answer.status === "streaming"
          ? { ...t, answer: { ...t.answer, status: "stopped", writing: false, tools: t.answer.tools.map((s) => ({ ...s, done: true })) } }
          : t,
      ),
    );
  }, []);

  /** Ask the question of a failed turn again (the failed turn is replaced). */
  const retry = useCallback(
    (key: string) => {
      const turn = turns.find((t) => t.key === key);
      if (!turn) return;
      setTurns((ts) => ts.filter((t) => t.key !== key));
      void ask(turn.question);
    },
    [ask, turns],
  );

  const newChat = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setTurns([]);
    setHistoryThread(null);
    setThread(null);
  }, [setThread]);

  const past = useMemo(() => {
    const local = new Set(turns.map((t) => t.answer.messageId).filter(Boolean));
    return turnsFromHistory(history.data ?? []).filter((t) => !local.has(t.answer.messageId));
  }, [history.data, turns]);

  const streaming = turns.some((t) => t.answer.status === "streaming");

  return {
    threadId,
    past,
    turns,
    all: [...past, ...turns],
    loadingHistory: Boolean(historyThread) && history.isPending,
    historyError: history.isError,
    streaming,
    ask,
    stop,
    retry,
    newChat,
  };
}
