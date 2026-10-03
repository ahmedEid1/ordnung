/**
 * A tab left open across an upgrade asks for page chunks the new build no longer has (404): load the new build
 * instead of showing an error — once a minute at most, so a real outage can't loop. Only while Ordnung answers: a
 * chunk that failed because Ordnung stopped keeps the app on screen, with the page's error and its "Try again" and
 * the "Can't reach Ordnung" notice, instead of the browser's "This site can't be reached" (UX audit U7).
 */
const LAST_RELOAD = "ordnung:stale-reload";
const RELOAD_GAP_MS = 60_000;

/** Reload for a new build when a page chunk failed to load, if Ordnung answers and none was done a minute ago. */
export async function reloadIfServing(reload: () => void): Promise<void> {
  try {
    if (Date.now() - Number(sessionStorage.getItem(LAST_RELOAD) ?? 0) < RELOAD_GAP_MS) return;
  } catch {
    return; // no storage: keep the error screen (it has a Reload button)
  }
  const answers = await fetch("/api/health", { cache: "no-store" }).then(
    (res) => res.ok,
    () => false,
  );
  if (!answers) return;
  try {
    sessionStorage.setItem(LAST_RELOAD, String(Date.now()));
  } catch {
    return;
  }
  reload();
}

export function reloadOnStaleChunks(): void {
  window.addEventListener("vite:preloadError", () => void reloadIfServing(() => window.location.reload()));
}
