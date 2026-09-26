import { CircleAlert, CircleCheck, FlaskConical, RotateCw, Terminal } from "lucide-react";
import { useProbeHealth } from "@/api/hooks";
import type { Health } from "@/api/types";
import { Button } from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import { CopyCommand } from "@/features/onboarding/CopyCommand";
import { CLAUDE_INSTALL_CMD, CLAUDE_LOGIN_CMD } from "@/features/onboarding/options";
import { claudeState } from "@/features/onboarding/wizard";
import { cn } from "@/lib/utils";
import { SectionHeading, SettingsCard } from "./SettingsCard";

/** "Run check": `GET /api/health?probe=1` — the doctor's checks plus one tiny live call to Claude. */
function useProbe() {
  const probe = useProbeHealth();
  const mutate = () =>
    probe.mutate(undefined, {
      onSuccess: (h) => {
        const failed = h.checks.find((c) => c.id.startsWith("claude") && c.status === "fail");
        if (h.claude.ok && !failed) toast.success("Claude answered", { description: "Reading letters and Ask are ready." });
        else toast.warn("Claude didn't answer", { description: failed?.fix ?? failed?.detail ?? h.claude.detail ?? "See the steps below." });
      },
    });
  return { mutate, isPending: probe.isPending };
}

/** "Claude connection": is the `claude` CLI installed and signed in — and how to fix it. */
export function ClaudeSection({ health }: { health: Health }) {
  const probe = useProbe();
  const c = health.claude;
  const state = claudeState(c);
  const replay = health.backend === "replay";
  // the demo replays recordings: a missing Claude is expected there, not a problem
  const good = state === "ready" || state === "unchecked" || replay;

  const rows: [string, string | null][] = [
    ["Claude Code", c.installed ? (c.version ?? "Installed") : "Not found"],
    ["Signed in", c.ok === true ? "Yes — working" : c.ok === false ? "No" : "Not checked yet"],
    ["Found at", c.path],
    ["Ordnung", `Version ${health.version}`],
  ];

  return (
    <section aria-labelledby="set-claude">
      <SectionHeading
        id="set-claude"
        title="Claude connection"
        description="Ordnung reads letters with the Claude app on this computer, signed in with your own Claude account. No API key, no extra account."
      />
      <div className="space-y-5">
        {replay && state === "ready" ? (
          <div className="flex items-start gap-3 rounded-xl border border-accent/20 bg-accent-soft/60 px-4 py-3 text-[13.5px] leading-relaxed text-ink/90">
            <FlaskConical className="mt-0.5 size-4 shrink-0 text-accent" aria-hidden />
            <p>
              <strong className="font-semibold text-ink">Demo mode.</strong> Answers and letters are replayed from recordings — nothing is sent to Claude right now.
            </p>
          </div>
        ) : null}

        <SettingsCard
          footer={
            <>
              <span className="mr-auto text-[12.5px] text-muted">The check sends one tiny test message through your account.</span>
              <Button size="sm" icon={RotateCw} onClick={() => probe.mutate()} loading={probe.isPending}>
                Run check
              </Button>
            </>
          }
        >
          <div role="status" className={cn("flex items-start gap-3 rounded-xl border p-4", good ? "border-ok/30 bg-ok-soft/60" : "border-warn/30 bg-warn-soft/70")}>
            {good ? <CircleCheck className="mt-0.5 size-5 shrink-0 text-ok" aria-hidden /> : <CircleAlert className="mt-0.5 size-5 shrink-0 text-warn" aria-hidden />}
            <div className="min-w-0">
              <p className={cn("text-[15px] font-semibold", good ? "text-ok-ink" : "text-warn-ink")}>
                {replay && state !== "ready"
                  ? "The demo runs without Claude"
                  : state === "ready"
                  ? "Claude is ready"
                  : state === "unchecked"
                    ? "Claude is installed"
                    : state === "signed_out"
                      ? "Claude is installed, but not signed in"
                      : "Claude isn't installed"}
              </p>
              <p className="mt-0.5 text-[13.5px] leading-relaxed text-ink/80">
                {replay && state !== "ready"
                  ? "Everything you see was read by Claude once and recorded. To read your own letters, install Ordnung and connect Claude — the steps are below."
                  : state === "ready"
                  ? c.detail ?? "Signed in and working."
                  : state === "unchecked"
                    ? "Run the check to make sure you're signed in."
                    : state === "signed_out"
                      ? c.detail ?? "Sign in once in your terminal, then run the check again."
                      : "Install it once in your terminal (it needs Node.js 18 or newer), then sign in."}
              </p>
            </div>
          </div>

          <dl className="mt-5 divide-y divide-line text-[13.5px]">
            {rows.map(([k, v]) =>
              v ? (
                <div key={k} className="flex gap-4 py-2.5">
                  <dt className="w-32 shrink-0 text-muted">{k}</dt>
                  <dd className="min-w-0 break-all font-medium text-ink">{v}</dd>
                </div>
              ) : null,
            )}
          </dl>
        </SettingsCard>

        {(state === "missing" || state === "signed_out") && replay ? (
          <details className="group rounded-xl border border-line bg-surface px-4 py-3">
            <summary className="cursor-pointer text-[14px] font-medium text-ink marker:text-muted">Connect Claude for your own letters</summary>
            <ol className="mt-3 space-y-4">
              {state === "missing" ? (
                <li>
                  <p className="mb-2 text-[14px] font-medium text-ink">1. Install Claude Code</p>
                  <CopyCommand command={CLAUDE_INSTALL_CMD} label="install Claude Code" />
                </li>
              ) : null}
              <li>
                <p className="mb-2 text-[14px] font-medium text-ink">{state === "missing" ? "2." : "1."} Start it once and sign in with your Claude account</p>
                <CopyCommand command={CLAUDE_LOGIN_CMD} label="sign in" />
              </li>
            </ol>
          </details>
        ) : state === "missing" || state === "signed_out" ? (
          <SettingsCard title="How to fix it" id="set-claude-fix" description="Open a terminal (Terminal on a Mac, PowerShell on Windows) and run:">
            <ol className="space-y-4">
              {state === "missing" ? (
                <li>
                  <p className="mb-2 text-[14px] font-medium text-ink">1. Install Claude Code</p>
                  <CopyCommand command={CLAUDE_INSTALL_CMD} label="install Claude Code" />
                </li>
              ) : null}
              <li>
                <p className="mb-2 text-[14px] font-medium text-ink">{state === "missing" ? "2." : "1."} Start it once and sign in with your Claude account</p>
                <CopyCommand command={CLAUDE_LOGIN_CMD} label="sign in" />
              </li>
              <li className="text-[13.5px] text-muted">Then come back here and press “Run check”.</li>
            </ol>
          </SettingsCard>
        ) : null}

        <p className="flex items-start gap-2 px-1 text-[12.5px] leading-5 text-muted">
          <Terminal className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          <span>
            Also available in a terminal: <code className="rounded bg-surface-2 px-1 py-px font-mono text-[12px] text-ink">ordnung doctor --probe</code>. Without Claude you can still store letters,
            search them and add your own dates.
          </span>
        </p>
      </div>
    </section>
  );
}
