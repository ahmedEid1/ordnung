/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { writeFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath, URL } from "node:url";
import type { Plugin } from "vite";
// @ts-expect-error -- a plain ES module script, shared with CI's freshness check
import { sourceHash } from "./scripts/source-hash.mjs";

const API = process.env.ORDNUNG_API ?? "http://127.0.0.1:8765";
const OUT_DIR = "../src/ordnung/web/dist";

/** Record what the build was made from, so CI can tell a stale committed build (scripts/source-hash.mjs). */
function buildInfo(): Plugin {
  let outDir = OUT_DIR;
  return {
    name: "ordnung-build-info",
    apply: "build",
    configResolved(config) {
      outDir = config.build.outDir;
    },
    closeBundle() {
      const info = { sourceHash: sourceHash() as string, note: "Built from web/ by `make build-web`." };
      writeFileSync(join(outDir, "build-info.json"), JSON.stringify(info, null, 2) + "\n");
    },
  };
}

export default defineConfig({
  plugins: [react(), tailwindcss(), buildInfo()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    port: 5173,
    proxy: { "/api": { target: API, changeOrigin: false } },
  },
  build: {
    outDir: OUT_DIR,
    emptyOutDir: true,
    chunkSizeWarningLimit: 1200,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    // the composer's flows take about 1.5 s alone and timed out at the 5 s default on a busy machine (review round 2)
    testTimeout: 20_000,
  },
});
