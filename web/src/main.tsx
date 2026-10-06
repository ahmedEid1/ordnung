import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./styles/index.css";
import { initTheme } from "@/app/theme";
import { reloadOnStaleChunks } from "@/app/staleChunks";
import { mockMode } from "@/mocks/mode";
import { copyWithoutGlue } from "@/lib/glue";

async function boot() {
  initTheme();
  reloadOnStaleChunks();
  // on-screen glue (non-breaking spaces and hyphens) never ends up in copied text
  document.addEventListener("copy", copyWithoutGlue);
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
