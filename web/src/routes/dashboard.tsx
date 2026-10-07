import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { Footprints, Moon, Pill, Scale, Wind } from "lucide-react";
import { useState } from "react";

import { AppShell } from "@/components/app-shell";
import { CoughBars, MetricArea, MetricLine } from "@/components/charts";
import { ChangeNoticedCard, Disclaimer, PageHeader, RangeTabs, SectionTitle, Skeleton, StatCard } from "@/components/haman-ui";
import { api, type Range } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

export const Route = createFileRoute("/dashboard")({
  head: () => ({
    meta: [
      { title: "Dashboard — Haman Health" },
      { name: "description", content: "Coughs per night, weight, activity, sleep and medications over 7, 30 or 90 days." },
      { property: "og:title", content: "Dashboard — Haman Health" },
      { property: "og:description", content: "Coughs per night, weight, activity, sleep and medications over 7, 30 or 90 days." },
    ],
  }),
  component: DashboardPage,
});

function DashboardPage() {
  const { t } = useI18n();
  const [range, setRange] = useState<Range>(30);
  const { data, isLoading } = useQuery({ queryKey: ["dashboard", range], queryFn: () => api.dashboard.get(range) });

  return (
    <AppShell title={t("nav_dashboard")}>
      <PageHeader eyebrow="Overview" title={t("nav_dashboard")} action={<RangeTabs value={range} onChange={setRange} />} />

      {isLoading || !data ? (
        <div className="space-y-3 px-5 md:px-8">
          <Skeleton className="h-64" />
          <Skeleton className="h-40" />
        </div>
      ) : (
        <div className="space-y-6 px-5 md:px-8">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
            <StatCard label={t("cough_events")} value={data.averages.coughs} unit="/ night" icon={Wind} />
            <StatCard label={t("sleep")} value={data.averages.sleepHours} unit="h" icon={Moon} />
            <StatCard label={t("weight")} value={data.averages.weight} unit="kg" icon={Scale} />
            <StatCard label={t("activity")} value={data.averages.steps.toLocaleString()} unit={t("steps")} icon={Footprints} />
            <StatCard label={t("medications")} value={`${Math.round(data.averages.adherence * 100)}%`} unit="taken" icon={Pill} className="col-span-2 lg:col-span-1" />
          </div>

          <section className="card-soft p-5">
            <SectionTitle title="Coughs per night" />
            <CoughBars data={data.points} height={220} />
          </section>

          <div className="grid gap-4 md:grid-cols-2">
            <section className="card-soft p-5">
              <SectionTitle title={t("weight")} />
              <MetricLine data={data.points} dataKey="weight" label="kg" color="var(--chart-2)" />
            </section>
            <section className="card-soft p-5">
              <SectionTitle title={t("activity")} />
              <MetricArea data={data.points} dataKey="steps" label="steps" color="var(--chart-3)" />
            </section>
            <section className="card-soft p-5">
              <SectionTitle title={t("sleep")} />
              <MetricArea data={data.points} dataKey="sleepHours" label="hours" color="var(--primary)" />
            </section>
            <section className="card-soft p-5">
              <SectionTitle title={t("medications")} />
              <ul className="space-y-3">
                {data.medications.map((m) => (
                  <li key={m.id} className="flex items-center gap-3">
                    <span className="grid size-10 shrink-0 place-items-center rounded-full bg-primary-soft text-primary">
                      <Pill className="size-4" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium">
                        {m.name} <span className="font-normal text-muted-foreground">· {m.dose}</span>
                      </p>
                      <p className="text-xs text-muted-foreground">{m.schedule}</p>
                      <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-muted">
                        <div className="h-full rounded-full bg-primary" style={{ width: `${m.adherence * 100}%` }} />
                      </div>
                    </div>
                    <span className="text-sm tabular-nums text-muted-foreground">{Math.round(m.adherence * 100)}%</span>
                  </li>
                ))}
              </ul>
            </section>
          </div>

          <section>
            <SectionTitle title={t("change_noticed")} />
            <div className="grid gap-3 md:grid-cols-2">
              {data.changes.map((c) => (
                <ChangeNoticedCard key={c.id} card={c} />
              ))}
            </div>
          </section>
        </div>
      )}
      <Disclaimer />
    </AppShell>
  );
}
