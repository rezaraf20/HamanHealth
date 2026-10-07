import { Link } from "@tanstack/react-router";
import { ArrowDownRight, ArrowUpRight, Minus, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import type { ChangeCard as ChangeCardT, Range } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

export function PageHeader({
  eyebrow,
  title,
  action,
  className,
}: {
  eyebrow?: string | undefined;
  title: string;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex items-end justify-between gap-4 px-5 pt-6 pb-4 md:px-8 md:pt-10", className)}>
      <div className="min-w-0">
        {eyebrow && <p className="text-sm text-muted-foreground">{eyebrow}</p>}
        <h1 className="mt-0.5 text-2xl font-semibold tracking-tight md:text-3xl">{title}</h1>
      </div>
      {action}
    </div>
  );
}

export function SectionTitle({ title, to, children }: { title: string; to?: string; children?: ReactNode }) {
  const { t } = useI18n();
  return (
    <div className="mb-3 flex items-center justify-between">
      <h2 className="text-base font-semibold">{title}</h2>
      {to && (
        <Link to={to} className="text-sm text-muted-foreground hover:text-primary">
          {t("see_all")}
        </Link>
      )}
      {children}
    </div>
  );
}

export function StatCard({
  label,
  value,
  unit,
  icon: Icon,
  children,
  className,
}: {
  label: string;
  value: string | number;
  unit?: string;
  icon?: LucideIcon;
  children?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("card-soft p-4", className)}>
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium">{label}</p>
        {Icon && (
          <span className="grid size-9 place-items-center rounded-full bg-primary-soft text-primary">
            <Icon className="size-4" strokeWidth={2} />
          </span>
        )}
      </div>
      <p className="mt-3 text-2xl font-semibold tracking-tight">
        {value} {unit && <span className="text-sm font-normal text-muted-foreground">{unit}</span>}
      </p>
      {children}
    </div>
  );
}

export function RangeTabs({ value, onChange }: { value: Range; onChange: (r: Range) => void }) {
  const { t } = useI18n();
  const opts: { v: Range; label: string }[] = [
    { v: 7, label: t("range_7") },
    { v: 30, label: t("range_30") },
    { v: 90, label: t("range_90") },
  ];
  return (
    <div className="inline-flex rounded-full border bg-card p-1 shadow-card">
      {opts.map((o) => (
        <button
          key={o.v}
          onClick={() => onChange(o.v)}
          className={cn(
            "whitespace-nowrap rounded-full px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors",
            value === o.v && "bg-primary text-primary-foreground",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** Neutral trend card. Deliberately no urgency colors. */
export function ChangeNoticedCard({ card }: { card: ChangeCardT }) {
  const { t } = useI18n();
  const Icon = card.direction === "up" ? ArrowUpRight : card.direction === "down" ? ArrowDownRight : Minus;
  return (
    <div className="card-soft p-4">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 grid size-9 shrink-0 place-items-center rounded-full bg-muted text-foreground">
          <Icon className="size-4" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <p className="text-sm font-semibold">{card.title}</p>
            <span className="rounded-full bg-secondary px-2 py-0.5 text-[11px] font-medium text-secondary-foreground">
              {card.deltaLabel}
            </span>
          </div>
          <p className="mt-1 text-sm text-muted-foreground">{card.description}</p>
          <p className="mt-2 text-[11px] text-muted-foreground">
            {card.since} · {t("trend_only")}
          </p>
        </div>
      </div>
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-2xl bg-muted", className)} />;
}

export function Disclaimer() {
  const { t } = useI18n();
  return <p className="px-5 pt-6 text-center text-[11px] text-muted-foreground md:px-8">{t("notDiagnostic")}</p>;
}
