import { Fragment, type ReactNode } from "react";
import { ChevronRight, CircleAlert, CircleCheck, FlaskConical, RotateCw, Terminal } from "lucide-react";
import { useProbeHealth } from "@/api/hooks";
import type { Health } from "@/api/types";
import { Button } from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import { CopyCommand } from "@/features/onboarding/CopyCommand";
import { CLAUDE_INSTALL_CMD, CLAUDE_LOGIN_CMD } from "@/features/onboarding/options";
import { claudeState } from "@/features/onboarding/wizard";
import { cn } from "@/lib/utils";
import { BreakablePath } from "./DataSection";
import { SectionHeading, SettingsCard } from "./SettingsCard";

/** "2.1.4 (Claude Code)" → "2.1.4" (the row is already called "Claude Code"). */
export function bareVersion(version: string | null | undefined): string | null {
  return version?.replace(/\s*\(Claude Code\)\s*$/i, "").trim() || null;
}

const code = "rounded bg-surface-2 px-1 py-px font-mono text-[12px] text-ink";

/** A message from the check with its `commands` set as code (never literal backticks). */
function WithCode({ text }: { text: string }) {
  return (
    <>
      {text.split(/`([^`]+)`/).map((part, i) =>
        i % 2 ? (
          <code key={i} className={cn(code, "whitespace-nowrap")}>
            {part}
          </code>
        ) : (
          <Fragment key={i}>{part}</Fragment>
        ),
      )}
    </>
  );
}

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

/** The install / sign-in commands, numbered. */
function FixSteps({ missing, children }: { missing: boolean; children?: ReactNode }) {
  return (
    <ol className="space-y-4">
      {missing ? (
        <li>
          <p className="mb-2 text-[14px] font-medium text-ink">1. Install Claude Code</p>
          <CopyCommand command={CLAUDE_INSTALL_CMD} label="install Claude Code" />
        </li>
      ) : null}
      <li>
        <p className="mb-2 text-[14px] font-medium text-ink">{missing ? "2." : "1."} Start it once and sign in with your Claude account</p>
        <CopyCommand command={CLAUDE_LOGIN_CMD} label="sign in" />
      </li>
      {children}
    </ol>
  );
}

/** "Claude connection": is the `claude` CLI installed and signed in — and how to fix it. */
export function ClaudeSection({ health }: { health: Health }) {
  const probe = useProbe();
  const c = health.claude;
  const state = claudeState(c);
  const replay = health.backend === "replay";
  // the demo replays recordings: a missing Claude is expected there, not a problem
  const good = state === "ready" || state === "unchecked" || replay;

  const rows: [string, ReactNode][] = [
    ["Claude Code", c.installed ? (bareVersion(c.version) ?? "Installed") : "Not found"],
    // whether you're signed in can only be checked once Claude is there
    ["Signed in", !c.installed ? null : c.ok === true ? "Yes — working" : c.ok === false ? "No" : "Not checked yet"],
    ["Found at", c.path ? <BreakablePath path={c.path} /> : null],
    ["Ordnung", `Version ${health.version}`],
  ];

  const title =
    replay && state !== "ready"
      ? "The demo runs without Claude"
      : state === "ready"
        ? "Claude is ready"
        : state === "unchecked"
          ? "Claude is installed"
          : state === "signed_out"
            ? "Claude is installed, but not signed in"
            : "Claude isn't installed";
  const body: ReactNode =
    replay && state !== "ready" ? (
      "Everything you see was read by Claude once and recorded. To read your own letters, install Ordnung and connect Claude — the steps are below."
    ) : state === "ready" ? (
      c.detail ? <WithCode text={c.detail} /> : "Signed in and working."
    ) : state === "unchecked" ? (
      "Run the check to make sure you're signed in."
    ) : state === "signed_out" ? (
      <>
        Open a terminal, run <code className={code}>claude</code> once and sign in with your Claude account. Then run the check again.
      </>
    ) : (
      "Install it once in your terminal (it needs Node.js 18 or newer), then sign in."
    );

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
            // the demo replays recordings: there is nothing to check
            replay ? undefined : (
              <>
                <span className="mr-auto min-w-0 text-[12.5px] leading-5 text-muted">
                  {state === "missing" ? "Installed it? The check finds it and tries it with one tiny test message." : "The check sends one tiny test message through your account."}
                </span>
                <Button size="sm" icon={RotateCw} onClick={() => probe.mutate()} loading={probe.isPending} className="ml-auto">
                  Run check
                </Button>
              </>
            )
          }
        >
          <div role="status" className={cn("flex items-start gap-3 rounded-xl border p-4", good ? "border-ok/30 bg-ok-soft/60" : "border-warn/30 bg-warn-soft/70")}>
            {good ? <CircleCheck className="mt-0.5 size-5 shrink-0 text-ok" aria-hidden /> : <CircleAlert className="mt-0.5 size-5 shrink-0 text-warn" aria-hidden />}
            <div className="min-w-0">
              <p className={cn("text-[15px] font-semibold", good ? "text-ok-ink" : "text-warn-ink")}>{title}</p>
              <p className="mt-0.5 text-[13.5px] leading-relaxed text-ink/80">{body}</p>
            </div>
          </div>

          {/* label above value on phones (a long path gets the whole width), side by side from sm */}
          <dl className="mt-5 divide-y divide-line text-[13.5px]">
            {rows.map(([k, v]) =>
              v ? (
                <div key={k} className="flex flex-col gap-0.5 py-2.5 sm:flex-row sm:gap-4">
                  <dt className="shrink-0 text-muted sm:w-32">{k}</dt>
                  <dd className="min-w-0 font-medium text-ink [overflow-wrap:anywhere]">{v}</dd>
                </div>
              ) : null,
            )}
          </dl>
        </SettingsCard>

        {(state === "missing" || state === "signed_out") && replay ? (
          <details className="card group overflow-clip">
            <summary className="flex min-h-11 cursor-pointer list-none items-center gap-2 px-4 py-3 text-[14px] font-medium text-ink transition-colors hover:bg-surface-2/60 sm:px-5 [&::-webkit-details-marker]:hidden">
              <ChevronRight className="size-4 shrink-0 text-muted transition-transform group-open:rotate-90" aria-hidden />
              Connect Claude for your own letters
            </summary>
            <div className="border-t border-line px-4 pb-4 pt-3 sm:px-5 sm:pb-5">
              <FixSteps missing={state === "missing"} />
            </div>
          </details>
        ) : state === "missing" || state === "signed_out" ? (
          <SettingsCard title="How to fix it" id="set-claude-fix" description="Open a terminal (Terminal on a Mac, PowerShell on Windows) and run:">
            <FixSteps missing={state === "missing"}>
              <li className="text-[13.5px] text-muted">Then come back here and press “Run check”.</li>
            </FixSteps>
          </SettingsCard>
        ) : null}

        <p className="flex items-start gap-2 px-1 text-[12.5px] leading-5 text-muted">
          <Terminal className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          <span>
            Also available in a terminal: <code className={cn(code, "whitespace-nowrap")}>ordnung doctor --probe</code>. Without Claude you can still store letters, search them and add
            your own dates.
          </span>
        </p>
      </div>
    </section>
  );
}
