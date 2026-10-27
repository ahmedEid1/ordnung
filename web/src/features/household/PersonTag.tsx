import { User } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { cn } from "@/lib/utils";

/**
 * Whose letter it is, when it is filed for someone in the household: "For Alex Rivera" with a person icon, one
 * look on the Inbox's rows and Today's cards. A long name is cut, the whole of it in `title`.
 */
export function PersonTag({ name, className }: { name: string; className?: string }) {
  const text = `For ${name}`;
  return (
    <Badge tone="neutral" icon={User} title={text} className={cn("min-w-0", className)} data-person-tag>
      {text}
    </Badge>
  );
}
