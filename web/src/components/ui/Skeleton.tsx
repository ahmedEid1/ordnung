import { cn } from "@/lib/utils";

/** Loading placeholder block. Size it with classes (`h-4 w-32`). */
export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn("animate-pulse rounded-md bg-surface-3/80 motion-reduce:animate-none", className)} />;
}

/** A few lines of placeholder text (last line shorter). */
export function SkeletonText({ lines = 3, className }: { lines?: number; className?: string }) {
  return (
    <div className={cn("space-y-2", className)} aria-hidden>
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} className={cn("h-3.5", i === lines - 1 ? "w-2/3" : "w-full")} />
      ))}
    </div>
  );
}

/** Card-shaped placeholder with an icon, title and text lines. */
export function SkeletonCard({ className, lines = 2 }: { className?: string; lines?: number }) {
  return (
    <div className={cn("card p-4 sm:p-5", className)} aria-hidden>
      <div className="flex items-center gap-3">
        <Skeleton className="size-9 rounded-lg" />
        <div className="flex-1 space-y-2">
          <Skeleton className="h-4 w-1/2" />
          <Skeleton className="h-3 w-1/3" />
        </div>
      </div>
      {lines > 0 ? <SkeletonText lines={lines} className="mt-4" /> : null}
    </div>
  );
}

/** Screen-reader-only loading announcement to pair with skeletons. */
export function LoadingLabel({ children = "Loading…" }: { children?: string }) {
  return (
    <span role="status" className="sr-only">
      {children}
    </span>
  );
}
