import { Link } from "@tanstack/react-router";
import { ArrowLeft } from "lucide-react";
import type { ReactNode } from "react";

export function AccountSection({ title, description, children }: { title: string; description?: string; children: ReactNode }) {
  return (
    <div className="space-y-4">
      <Link to="/account" className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-primary md:hidden">
        <ArrowLeft className="size-4" /> Account
      </Link>
      <div>
        <h2 className="text-xl font-semibold tracking-tight">{title}</h2>
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      </div>
      {children}
    </div>
  );
}

export function Row({ title, hint, children }: { title: string; hint?: string; children?: ReactNode }) {
  return (
    <div className="flex items-center gap-3 py-3.5">
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">{title}</p>
        {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
      </div>
      {children}
    </div>
  );
}

export const btnPrimary =
  "inline-flex h-11 items-center justify-center rounded-full bg-primary px-5 text-sm font-semibold text-primary-foreground hover:brightness-110 disabled:opacity-50";
export const btnOutline =
  "inline-flex h-11 items-center justify-center rounded-full border bg-card px-5 text-sm font-medium hover:bg-muted disabled:opacity-50";
export const btnDanger =
  "inline-flex h-11 items-center justify-center rounded-full border border-destructive/40 px-5 text-sm font-medium text-destructive hover:bg-destructive/10 disabled:opacity-50";
export const input = "h-11 w-full rounded-2xl border bg-background px-4 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-ring/30";
