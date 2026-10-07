import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { FileText, Moon, Pill, Scale, Smartphone, StickyNote, type LucideIcon } from "lucide-react";
import { useState } from "react";

import { AppShell } from "@/components/app-shell";
import { Disclaimer, PageHeader, Skeleton } from "@/components/haman-ui";
import { api, type TimelineKind } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/timeline")({
  head: () => ({
    meta: [
      { title: "Health timeline — Haman Health" },
      { name: "description", content: "Sessions, records, medication, weight and notes in one filterable timeline." },
      { property: "og:title", content: "Health timeline — Haman Health" },
      { property: "og:description", content: "Sessions, records, medication, weight and notes in one filterable timeline." },
    ],
  }),
  component: TimelinePage,
});

const KINDS: { kind: TimelineKind; label: string; icon: LucideIcon }[] = [
  { kind: "session", label: "Sessions", icon: Moon },
  { kind: "record", label: "Records", icon: FileText },
  { kind: "medication", label: "Medication", icon: Pill },
  { kind: "weight", label: "Weight", icon: Scale },
  { kind: "note", label: "Notes", icon: StickyNote },
  { kind: "device", label: "Devices", icon: Smartphone },
];

function TimelinePage() {
  const { t } = useI18n();
  const [active, setActive] = useState<TimelineKind[]>([]);
  const { data } = useQuery({ queryKey: ["timeline", active], queryFn: () => api.timeline.list(active) });

  const toggle = (k: TimelineKind) => setActive((a) => (a.includes(k) ? a.filter((x) => x !== k) : [...a, k]));

  const groups = (data ?? []).reduce<Record<string, typeof data>>((acc, e) => {
    const day = new Date(e.at).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
    (acc[day] ||= []).push(e);
    return acc;
  }, {});

  return (
    <AppShell title={t("nav_timeline")}>
      <PageHeader eyebrow="Everything, in order" title={t("nav_timeline")} />
      <div className="px-5 md:px-8">
        <div className="flex gap-2 overflow-x-auto pb-1 [scrollbar-width:none]">
          <button
            onClick={() => setActive([])}
            className={cn("pill shrink-0 px-4 py-2 text-sm font-medium", active.length === 0 ? "border-primary bg-primary text-primary-foreground" : "hover:bg-muted")}
          >
            All
          </button>
          {KINDS.map((k) => (
            <button
              key={k.kind}
              onClick={() => toggle(k.kind)}
              className={cn(
                "pill inline-flex shrink-0 items-center gap-1.5 px-4 py-2 text-sm font-medium",
                active.includes(k.kind) ? "border-primary bg-primary text-primary-foreground" : "hover:bg-muted",
              )}
            >
              <k.icon className="size-4" />
              {k.label}
            </button>
          ))}
        </div>

        <div className="mt-6 space-y-8 md:max-w-2xl">
          {!data && <Skeleton className="h-64" />}
          {data && data.length === 0 && <p className="text-sm text-muted-foreground">Nothing here for this filter yet.</p>}
          {Object.entries(groups).map(([day, events]) => (
            <div key={day}>
              <p className="mb-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">{day}</p>
              <ol className="relative space-y-3 border-l border-border pl-6">
                {events!.map((e) => {
                  const Icon = KINDS.find((k) => k.kind === e.kind)?.icon ?? StickyNote;
                  return (
                    <li key={e.id} className="relative">
                      <span className="absolute -left-[37px] top-3 grid size-6 place-items-center rounded-full border bg-card text-primary">
                        <Icon className="size-3" />
                      </span>
                      <div className="card-soft p-4">
                        <div className="flex items-center justify-between gap-3">
                          <p className="text-sm font-medium">{e.title}</p>
                          <span className="shrink-0 text-xs text-muted-foreground">
                            {new Date(e.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                          </span>
                        </div>
                        <p className="mt-1 text-sm text-muted-foreground">{e.detail}</p>
                      </div>
                    </li>
                  );
                })}
              </ol>
            </div>
          ))}
        </div>
      </div>
      <Disclaimer />
    </AppShell>
  );
}
