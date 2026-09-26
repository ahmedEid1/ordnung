/**
 * Shows browser notifications while Ordnung is open (mounted once by the app shell): on load, when
 * the day changes and when Ideas change. Only when the person turned them on in this browser and the
 * browser allows them; never in the zero-install online demo. Each to-do or Idea at most once a day
 * (remembered in localStorage, shared by every tab).
 */
import { useCallback, useEffect, useRef, useSyncExternalStore } from "react";
import { useNavigate, type NavigateFunction } from "react-router";
import { api } from "@/api/endpoints";
import { useHealth } from "@/api/hooks";
import { useServerEvent } from "@/api/sse";
import { isStaticDemo } from "@/mocks/mode";
import {
  batchForDisplay,
  notYetShown,
  notifyPermission,
  planNotifications,
  readNotifyEnabled,
  recordSent,
  writeNotifyEnabled,
  type NotifyPermission,
  type PlannedNotification,
} from "./notify";

// ------------------------------------------------------------------------------------------------
// Preference + permission as a tiny store (the Settings switch and the app shell stay in sync)
// ------------------------------------------------------------------------------------------------

export interface NotifyState {
  enabled: boolean;
  permission: NotifyPermission;
  /** The online demo never notifies. */
  available: boolean;
}

const listeners = new Set<() => void>();
let snapshot: NotifyState | null = null;

function computeState(): NotifyState {
  const permission = notifyPermission();
  return { enabled: readNotifyEnabled() && permission === "granted", permission, available: !isStaticDemo() && permission !== "unsupported" };
}

function getSnapshot(): NotifyState {
  const next = computeState();
  if (!snapshot || snapshot.enabled !== next.enabled || snapshot.permission !== next.permission || snapshot.available !== next.available) snapshot = next;
  return snapshot;
}

function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  const onStorage = (e: StorageEvent) => {
    if (e.key === null || e.key.startsWith("ordnung.notify")) fn();
  };
  window.addEventListener("storage", onStorage);
  window.addEventListener("focus", fn); // permission may have changed in the browser's site settings
  return () => {
    listeners.delete(fn);
    window.removeEventListener("storage", onStorage);
    window.removeEventListener("focus", fn);
  };
}

function changed() {
  listeners.forEach((fn) => fn());
}

/** The browser-notification preference of this browser (reactive). */
export function useNotifyState(): NotifyState {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

/**
 * Turn notifications on (asks the browser for permission when it hasn't been asked yet) or off.
 * Resolves to the resulting state; `permission: "denied"` means the browser blocked them.
 */
export async function setBrowserNotifications(on: boolean): Promise<NotifyState> {
  if (!on) {
    writeNotifyEnabled(false);
    changed();
    return computeState();
  }
  if (isStaticDemo() || notifyPermission() === "unsupported") return computeState();
  let permission = notifyPermission();
  if (permission === "default") {
    try {
      permission = (await window.Notification.requestPermission()) as NotifyPermission;
    } catch {
      permission = notifyPermission();
    }
  }
  writeNotifyEnabled(permission === "granted");
  changed();
  return computeState();
}

/** Show one notification; clicking it brings Ordnung to the front on the right page. */
export function showNotification(n: Pick<PlannedNotification, "key" | "title" | "body" | "href">, navigate?: NavigateFunction): boolean {
  try {
    const note = new window.Notification(n.title, { body: n.body, tag: `ordnung:${n.key}`, icon: "/favicon.svg" });
    note.onclick = () => {
      window.focus();
      navigate?.(n.href);
      note.close();
    };
    return true;
  } catch {
    return false; // e.g. mobile browsers that only notify from a service worker
  }
}

// ------------------------------------------------------------------------------------------------
// The app-shell hook
// ------------------------------------------------------------------------------------------------

export function useBrowserNotifications(): void {
  const health = useHealth();
  const today = health.data?.today ?? null;
  const { enabled } = useNotifyState();
  const navigate = useNavigate();
  const running = useRef(false);

  const check = useCallback(async () => {
    if (!today || !enabled || running.current || isStaticDemo() || notifyPermission() !== "granted") return;
    running.current = true;
    try {
      const [items, ideas] = await Promise.all([api.items({ status: "open" }), api.suggestions({ status: "new" })]);
      const pending = notYetShown(planNotifications(items, ideas, today), today);
      if (!pending.length) return;
      // remember first: another tab checking at the same moment then skips them
      recordSent(
        pending.map((n) => n.key),
        today,
      );
      for (const n of batchForDisplay(pending)) showNotification(n, navigate);
    } catch {
      /* a failed check is retried on the next event — never bother the person about it */
    } finally {
      running.current = false;
    }
  }, [today, enabled, navigate]);

  // on load, when the app's today moves on and when notifications are turned on
  useEffect(() => {
    void check();
  }, [check]);
  useServerEvent("day.changed", () => void check());
  useServerEvent("suggestions.updated", () => void check());
}
