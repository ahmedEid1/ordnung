/**
 * The servers the audit runs against, started and stopped by the audit itself:
 *
 * - demo:   `ordnung demo --serve --no-browser --reset --port P --data-dir D` (Sam Rivera's sample life)
 * - fresh:  `ordnung serve --no-browser --port P --data-dir D` on an emptied folder (first run)
 * - static: the zero-install demo (`VITE_STATIC_DEMO=1 vite build --outDir D`) under `vite preview`
 *
 * With `reuse` nothing is started: the server already running on the port is used (demo/fresh
 * read their session token from `<data>/server.json`).
 */
import { spawn } from "node:child_process";
import { closeSync, existsSync, mkdirSync, openSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { sourceHash } from "../source-hash.mjs";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export function ordnungBin(webDir) {
  if (process.env.ORDNUNG_BIN) return process.env.ORDNUNG_BIN;
  const venv = resolve(webDir, "..", ".venv", "bin", "ordnung");
  return existsSync(venv) ? venv : "ordnung";
}

async function waitFor(url, { timeout = 90_000, proc } = {}) {
  const until = Date.now() + timeout;
  let last;
  while (Date.now() < until) {
    if (proc && proc.exitCode !== null) throw new Error(`the server exited (code ${proc.exitCode}) before ${url} answered`);
    try {
      const res = await fetch(url);
      if (res.ok) return;
      last = `HTTP ${res.status}`;
    } catch (err) {
      last = err.message;
    }
    await sleep(150);
  }
  throw new Error(`${url} did not answer within ${timeout / 1000}s (${last})`);
}

async function portFree(port) {
  try {
    await fetch(`http://127.0.0.1:${port}/`, { signal: AbortSignal.timeout(800) });
    return false;
  } catch {
    return true;
  }
}

async function stopProc(proc) {
  if (!proc || proc.exitCode !== null) return;
  proc.kill("SIGTERM");
  for (let i = 0; i < 50 && proc.exitCode === null; i += 1) await sleep(100);
  if (proc.exitCode === null) proc.kill("SIGKILL");
  for (let i = 0; i < 20 && proc.exitCode === null; i += 1) await sleep(100);
}

/**
 * A server for one target. `start()` / `stop()` / `restart({ dataDir })`; `token()` reads the
 * current session token (demo/fresh restarts write a new one).
 */
export class AuditServer {
  constructor({ target, port, dataDir, webDir, reuse = false, log = console.log, logDir }) {
    this.target = target;
    this.port = port;
    this.dataDir = resolve(dataDir);
    this.webDir = webDir;
    this.reuse = reuse;
    this.log = log;
    this.logDir = logDir ?? this.dataDir;
    this.base = `http://127.0.0.1:${port}`;
    this.proc = null;
    this.pids = [];
  }

  token() {
    if (this.target === "static") return null;
    try {
      return JSON.parse(readFileSync(join(this.dataDir, "server.json"), "utf8")).token ?? null;
    } catch {
      return null;
    }
  }

  async start() {
    if (this.reuse) {
      await waitFor(this.target === "static" ? `${this.base}/` : `${this.base}/api/health`, { timeout: 10_000 });
      this.log(`  reusing the server on ${this.base}`);
      return;
    }
    if (!(await portFree(this.port))) throw new Error(`port ${this.port} is already in use — stop that server or pass --reuse`);
    mkdirSync(this.logDir, { recursive: true });
    if (this.target === "static") return this.#startStatic();
    const bin = ordnungBin(this.webDir);
    let args;
    if (this.target === "demo") {
      args = ["demo", "--serve", "--no-browser", "--reset", "--port", String(this.port), "--data-dir", this.dataDir];
    } else {
      rmSync(this.dataDir, { recursive: true, force: true });
      mkdirSync(this.dataDir, { recursive: true });
      args = ["serve", "--no-browser", "--port", String(this.port), "--data-dir", this.dataDir];
    }
    const logFile = join(this.logDir, `${this.target}-server.log`);
    const fd = openSync(logFile, "a");
    this.proc = spawn(bin, args, { stdio: ["ignore", fd, fd], env: { ...process.env, NO_COLOR: "1", COLUMNS: "200" } });
    closeSync(fd);
    this.pids.push(this.proc.pid);
    this.log(`  started ${this.target} server (pid ${this.proc.pid}) on ${this.base}, data ${this.dataDir}`);
    await waitFor(`${this.base}/api/health`, { proc: this.proc });
    for (let i = 0; i < 50 && !this.token(); i += 1) await sleep(100);
    if (!this.token()) throw new Error(`no session token in ${this.dataDir}/server.json`);
  }

  async #startStatic() {
    const outDir = this.dataDir;
    if (outDir === resolve(this.webDir, "..", "src", "ordnung", "web", "dist")) throw new Error("never build the static demo into src/ordnung/web/dist — pass another --data folder");
    // rebuild unless the folder already holds a static build of exactly these sources
    let built = null;
    try {
      built = JSON.parse(readFileSync(join(outDir, "build-info.json"), "utf8")).sourceHash;
    } catch {
      /* no build yet */
    }
    const stale = !existsSync(join(outDir, "index.html")) || built !== sourceHash(this.webDir) || !existsSync(join(outDir, ".static-demo"));
    if (stale) {
      this.log(`  building the static demo into ${outDir} …`);
      await run(process.execPath, [join(this.webDir, "node_modules", "vite", "bin", "vite.js"), "build", "--outDir", outDir, "--emptyOutDir", "--logLevel", "warn"], {
        cwd: this.webDir,
        env: { ...process.env, VITE_STATIC_DEMO: "1" },
        logFile: join(this.logDir, "static-build.log"),
      });
      writeFileSync(join(outDir, ".static-demo"), "built with VITE_STATIC_DEMO=1 by the UI audit\n");
    }
    const logFile = join(this.logDir, "static-server.log");
    const fd = openSync(logFile, "a");
    this.proc = spawn(
      process.execPath,
      [join(this.webDir, "node_modules", "vite", "bin", "vite.js"), "preview", "--outDir", outDir, "--port", String(this.port), "--strictPort", "--host", "127.0.0.1"],
      { cwd: this.webDir, stdio: ["ignore", fd, fd], env: { ...process.env, VITE_STATIC_DEMO: "1" } },
    );
    closeSync(fd);
    this.pids.push(this.proc.pid);
    this.log(`  started static preview (pid ${this.proc.pid}) on ${this.base}`);
    await waitFor(`${this.base}/`, { proc: this.proc });
  }

  /** Stop and start again (demo: `--reset`, optionally on another data folder). */
  async restart({ dataDir } = {}) {
    if (this.reuse) throw new Error("can't restart a reused server");
    await this.stop();
    if (dataDir) this.dataDir = resolve(dataDir);
    await this.start();
  }

  async stop() {
    if (this.reuse || !this.proc) return;
    const pid = this.proc.pid;
    await stopProc(this.proc);
    this.log(`  stopped ${this.target} server (pid ${pid})`);
    this.proc = null;
    for (let i = 0; i < 30 && !(await portFree(this.port)); i += 1) await sleep(100);
  }
}

function run(cmd, args, { cwd, env, logFile }) {
  return new Promise((resolvePromise, reject) => {
    const fd = logFile ? openSync(logFile, "a") : "inherit";
    const p = spawn(cmd, args, { cwd, env, stdio: ["ignore", fd, fd] });
    if (typeof fd === "number") closeSync(fd);
    p.on("exit", (code) => (code === 0 ? resolvePromise() : reject(new Error(`${cmd} ${args.join(" ")} exited with ${code}${logFile ? ` (see ${logFile})` : ""}`))));
    p.on("error", reject);
  });
}

/** Helpers for the API of a running demo/fresh server (outside any page). */
export function apiClient(server) {
  const headers = () => ({ Authorization: `Bearer ${server.token()}`, ...{ "X-Ordnung-Client": "web" } });
  const call = async (method, path, body) => {
    const res = await fetch(`${server.base}${path}`, {
      method,
      headers: { ...headers(), ...(body !== undefined ? { "Content-Type": "application/json" } : {}) },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) throw new Error(`${method} ${path} → ${res.status} ${await res.text().catch(() => "")}`);
    const type = res.headers.get("content-type") ?? "";
    return type.includes("json") ? res.json() : res.text();
  };
  return {
    get: (p) => call("GET", p),
    post: (p, b) => call("POST", p, b ?? {}),
    patch: (p, b) => call("PATCH", p, b),
    put: (p, b) => call("PUT", p, b),
    raw: async (p) => {
      const res = await fetch(`${server.base}${p}`, { headers: headers() });
      if (!res.ok) throw new Error(`GET ${p} → ${res.status}`);
      return Buffer.from(await res.arrayBuffer());
    },
  };
}
