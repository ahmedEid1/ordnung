import { useState } from "react";
import { FlaskConical } from "lucide-react";
import { isStaticDemo, mockMode } from "@/mocks/mode";
import { cn } from "@/lib/utils";
import { SHELL_GUTTERS, shellWidth } from "./layout";
import { usePageMeta } from "./page-meta";

/**
 * `?mock=1` / `?mock=full` on a served app switch this tab to the browser-only sample data (remembered for
 * the tab): a different sample life from the recorded demo, with no sign of it before (walkthrough of phase 2:
 * "To pay €1,237.65" instead of the recorded demo's €681.34). Says so, with the way back (`?mock=0`, a full
 * reload: mock mode is chosen when the app starts). Never in the hosted static demo, which is only that.
 */
export function MockBanner() {
  const [shown] = useState(() => !isStaticDemo() && mockMode() !== "off");
  const { width } = usePageMeta();
  if (!shown) return null;
  return (
    <div role="status" className="border-b border-line bg-surface-2 py-2 text-base">
      <div className={cn("mx-auto flex w-full items-start gap-2.5", SHELL_GUTTERS, shellWidth(width))}>
        <FlaskConical className="mt-0.5 size-4 shrink-0 text-muted" aria-hidden />
        <p className="min-w-0 text-[13.5px] leading-5 text-ink/90">
          <span className="font-semibold">Browser-only sample data</span> — not the recorded demo, and nothing is saved.{" "}
          <a href="?mock=0" className="inline-flex min-h-6 items-center font-semibold text-accent underline-offset-2 hover:underline">
            Back to the recorded demo
          </a>
        </p>
      </div>
    </div>
  );
}
