import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./styles/index.css";
import { initTheme } from "@/app/theme";
import { mockMode } from "@/mocks/mode";

/**
 * A tab left open across an upgrade asks for page chunks the new build no longer has (404): load
 * the new build instead of showing an error — once a minute at most, so a real outage can't loop.
 */
function reloadOnStaleChunks() {
  window.addEventListener("vite:preloadError", () => {
    try {
      const last = Number(sessionStorage.getItem("ordnung:stale-reload") ?? 0);
      if (Date.now() - last < 60_000) return;
      sessionStorage.setItem("ordnung:stale-reload", String(Date.now()));
    } catch {
      return; // no storage: keep the error screen (it has a Reload button)
    }
    window.location.reload();
  });
}

async function boot() {
  initTheme();
  reloadOnStaleChunks();
  // Mock mode (?mock=1, ?mock=full) or the zero-install static demo build: serve /api from memory.
  const mode = mockMode();
  if (mode !== "off") {
    const { installMocks } = await import("@/mocks/install");
    installMocks({ full: mode === "full" });
  }
  const { default: App } = await import("./App");
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}

void boot();
