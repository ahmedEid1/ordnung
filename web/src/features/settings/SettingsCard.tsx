import type { ReactNode } from "react";
import { Check, Save } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/utils";
import { useReportDirty } from "./dirty";

/** A titled block inside a settings section. */
export function SettingsCard({
  title,
  description,
  children,
  footer,
  className,
  id,
}: {
  title?: ReactNode;
  description?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  className?: string;
  id?: string;
}) {
  return (
    <section aria-labelledby={title && id ? id : undefined} className={cn("card overflow-hidden", className)}>
      <div className="p-5 sm:p-6">
        {title ? (
          <div className="mb-5">
            <h3 id={id} className="text-[15px] font-semibold text-ink">
              {title}
            </h3>
            {description ? <p className="mt-1 text-[13.5px] leading-relaxed text-muted">{description}</p> : null}
          </div>
        ) : null}
        {children}
      </div>
      {footer ? <div className="flex flex-wrap items-center justify-end gap-3 border-t border-line bg-surface-2/40 px-5 py-3 sm:px-6">{footer}</div> : null}
    </section>
  );
}

/** Save row for a form card: "Unsaved changes" hint + Discard + Save. Reports unsaved edits to the page. */
export function SaveBar({
  dirty,
  saving,
  onSave,
  onDiscard,
  label = "Save changes",
  invalid = false,
}: {
  dirty: boolean;
  saving?: boolean;
  onSave: () => void;
  onDiscard?: () => void;
  label?: string;
  /** a field has an error: saving waits until it is fixed */
  invalid?: boolean;
}) {
  useReportDirty(dirty);
  return (
    <>
      <span className={cn("mr-auto text-[12.5px]", dirty ? "text-warn-ink" : "text-muted")} role="status">
        {dirty ? (invalid ? "Fix the field marked above to save" : "Unsaved changes") : "All changes saved"}
      </span>
      {dirty && onDiscard ? (
        <Button variant="ghost" size="sm" onClick={onDiscard} disabled={saving}>
          Discard
        </Button>
      ) : null}
      <Button variant={dirty ? "primary" : "secondary"} size="sm" icon={dirty ? Save : Check} onClick={onSave} disabled={!dirty || invalid} loading={saving}>
        {dirty ? label : "Saved"}
      </Button>
    </>
  );
}

/** Heading of a settings section (the right-hand pane). */
export function SectionHeading({ title, description, id }: { title: string; description?: ReactNode; id: string }) {
  return (
    <header className="mb-5">
      <h2 id={id} className="display text-[24px] font-semibold leading-tight text-ink">
        {title}
      </h2>
      {description ? <p className="mt-1.5 max-w-2xl text-[14px] leading-relaxed text-muted">{description}</p> : null}
    </header>
  );
}
