/**
 * Mock server-sent events: an in-page emitter plus a drop-in `EventSource` replacement for
 * `/api/events`, so `api/sse.ts` works unchanged in mock / static-demo mode. Events are typed by
 * the API's `ServerEvents` schema, so the mock can only send what the real server sends.
 */
import type { ServerEventMap, ServerEventType } from "@/api/types";

type Listener = (type: string, data: unknown) => void;

const listeners = new Set<Listener>();

/** Broadcast an event to every open mock EventSource. */
export function emit<K extends ServerEventType>(type: K, data: ServerEventMap[K]): void {
  for (const l of listeners) l(type, data);
}

const NativeEventSource: typeof EventSource | undefined = typeof EventSource !== "undefined" ? EventSource : undefined;

/** Minimal EventSource for `/api/events`; other URLs fall through to the native implementation. */
export class MockEventSource extends EventTarget {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;
  readonly CONNECTING = 0;
  readonly OPEN = 1;
  readonly CLOSED = 2;

  readonly url: string;
  readonly withCredentials: boolean;
  readyState = 0;
  onopen: ((ev: Event) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  private listener: Listener;

  constructor(url: string | URL, init?: EventSourceInit) {
    super();
    this.url = String(url);
    this.withCredentials = Boolean(init?.withCredentials);
    this.listener = (type, data) => {
      if (this.readyState !== 1) return;
      const ev = new MessageEvent(type, { data: JSON.stringify(data) });
      this.dispatchEvent(ev);
      if (type === "message") this.onmessage?.(ev);
    };
    listeners.add(this.listener);
    setTimeout(() => {
      if (this.readyState === 2) return;
      this.readyState = 1;
      const ev = new Event("open");
      this.dispatchEvent(ev);
      this.onopen?.(ev);
    }, 30);
  }

  close(): void {
    this.readyState = 2;
    listeners.delete(this.listener);
  }
}

/** Replace `window.EventSource` so `/api/events` is served by the mock emitter. */
export function installMockEventSource(): void {
  if (typeof window === "undefined") return;
  const Native = NativeEventSource;
  function Patched(this: unknown, url: string | URL, init?: EventSourceInit) {
    const u = new URL(String(url), window.location.href);
    if (u.pathname === "/api/events") return new MockEventSource(url, init);
    if (!Native) throw new Error("EventSource is not supported");
    return new Native(url, init);
  }
  Object.assign(Patched, { CONNECTING: 0, OPEN: 1, CLOSED: 2 });
  (window as unknown as { EventSource: unknown }).EventSource = Patched;
}
