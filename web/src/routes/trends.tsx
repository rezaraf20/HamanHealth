import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { AppShell } from "@/components/app-shell";
import { CoughBars, MetricArea, MetricLine } from "@/components/charts";
import { ChangeNoticedCard, Disclaimer, PageHeader, RangeTabs, Skeleton } from "@/components/haman-ui";
import { api, type DailyPoint, type Range } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/trends")({
  head: () => ({
    meta: [
      { title: "Trends — Haman Health" },
      { name: "description", content: "Notice how coughs, sleep, weight and activity change over time. Trends only, no triage." },
      { property: "og:title", content: "Trends — Haman Health" },
      { property: "og:description", content: "Notice how coughs, sleep, weight and activity change over time. Trends only, no triage." },
    ],
  }),
  component: TrendsPage,
});

type Metric = { key: keyof DailyPoint; label: string; unit: string; kind: "bar" | "line" | "area"; color: string };

const METRICS: Metric[] = [
  { key: "coughs", label: "Coughs", unit: "per night", kind: "bar", color: "var(--primary)" },
  { key: "sleepHours", label: "Sleep", unit: "hours", kind: "area", color: "var(--primary)" },
  { key: "weight", label: "Weight", unit: "kg", kind: "line", color: "var(--chart-2)" },
  { key: "steps", label: "Activity", unit: "steps", kind: "area", color: "var(--chart-3)" },
];

function TrendsPage() {
  const { t } = useI18n();
  const [range, setRange] = useState<Range>(30);
  const [metric, setMetric] = useState<Metric>(METRICS[0]!);
  const { data } = useQuery({ queryKey: ["dashboard", range], queryFn: () => api.dashboard.get(range) });

  const half = data ? Math.floor(data.points.length / 2) : 0;
  const avg = (pts: DailyPoint[]) => (pts.length ? pts.reduce((a, p) => a + (p[metric.key] as number), 0) / pts.length : 0);
  const first = data ? avg(data.points.slice(0, half)) : 0;
  const second = data ? avg(data.points.slice(half)) : 0;
  const delta = second - first;
  const fmt = (n: number) => (metric.key === "steps" ? Math.round(n).toLocaleString() : n.toFixed(1));

  return (
    <AppShell title={t("nav_trends")}>
      <PageHeader eyebrow="Over time" title={t("nav_trends")} action={<RangeTabs value={range} onChange={setRange} />} />

      <div className="space-y-5 px-5 md:px-8">
        <div className="flex gap-2 overflow-x-auto pb-1 [-ms-overflow-style:none] [scrollbar-width:none]">
          {METRICS.map((m) => (
            <button
              key={m.key}
              onClick={() => setMetric(m)}
              className={cn(
                "pill shrink-0 px-4 py-2 text-sm font-medium transition",
                metric.key === m.key ? "border-primary bg-primary text-primary-foreground" : "text-foreground hover:bg-muted",
              )}
            >
              {m.label}
            </button>
          ))}
        </div>

        {!data ? (
          <Skeleton className="h-80" />
        ) : (
          <section className="card-soft p-5">
            <div className="mb-4 flex items-end justify-between">
              <div>
                <p className="text-sm text-muted-foreground">
                  {metric.label} · {metric.unit}
                </p>
                <p className="text-3xl font-semibold tracking-tight">{fmt(second)}</p>
                <p className="text-xs text-muted-foreground">recent half of the period</p>
              </div>
              <div className="text-right">
                <p className="text-sm font-medium">
                  {delta > 0 ? "+" : ""}
                  {fmt(delta)}
                </p>
                <p className="text-xs text-muted-foreground">vs. earlier half</p>
              </div>
            </div>
            {metric.kind === "bar" && <CoughBars data={data.points} height={240} />}
            {metric.kind === "line" && <MetricLine data={data.points} dataKey={metric.key} label={metric.unit} color={metric.color} height={240} />}
            {metric.kind === "area" && <MetricArea data={data.points} dataKey={metric.key} label={metric.unit} color={metric.color} height={240} />}
            <p className="mt-3 text-[11px] text-muted-foreground">{t("trend_only")}</p>
          </section>
        )}

        <section>
          <h2 className="mb-3 text-base font-semibold">{t("change_noticed")}</h2>
          <div className="grid gap-3 md:grid-cols-2">{data?.changes.map((c) => <ChangeNoticedCard key={c.id} card={c} />)}</div>
        </section>
      </div>
      <Disclaimer />
    </AppShell>
  );
}
