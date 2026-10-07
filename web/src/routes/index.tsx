import { Link, createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { Activity, Bell, Footprints, Moon, Pill, Scale, Wind } from "lucide-react";

import { AppShell } from "@/components/app-shell";
import { HourlyBars } from "@/components/charts";
import { ChangeNoticedCard, Disclaimer, SectionTitle, Skeleton, StatCard } from "@/components/haman-ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Haman Health — Morning summary" },
      { name: "description", content: "Your night at a glance: cough events, sleep and gentle wellness trends. Not a diagnostic tool." },
      { property: "og:title", content: "Haman Health — Morning summary" },
      { property: "og:description", content: "Your night at a glance: cough events, sleep and gentle wellness trends. Not a diagnostic tool." },
    ],
  }),
  component: HomePage,
});

const QUICK = [
  { to: "/session", icon: Moon, label: "Start night session" },
  { to: "/trends", icon: Activity, label: "View trends" },
  { to: "/records", icon: Pill, label: "Add a record" },
] as const;

function HomePage() {
  const { t } = useI18n();
  const { user } = useAuth();
  const summary = useQuery({ queryKey: ["summary", "last"], queryFn: api.sessions.lastSummary });
  const dash = useQuery({ queryKey: ["dashboard", 7], queryFn: () => api.dashboard.get(7) });
  const session = useQuery({ queryKey: ["session", "current"], queryFn: api.sessions.current });
  const hour = new Date().getHours();
  const greeting = hour < 12 ? t("good_morning") : hour < 18 ? t("welcome_back") : t("good_evening");

  return (
    <AppShell>
      <div className="bg-sky-wash">
        <div className="flex items-start justify-between px-5 pt-8 md:px-8 md:pt-10">
          <div>
            <p className="text-sm text-muted-foreground">
              {greeting}, {user?.name.split(" ")[0]} 👋
            </p>
            <h1 className="mt-1 text-2xl font-semibold tracking-tight md:text-3xl">How was your night?</h1>
          </div>
          <div className="flex items-center gap-2">
            <button aria-label="Notifications" className="pill grid size-10 place-items-center text-foreground">
              <Bell className="size-4" />
            </button>
            <Link to="/account" className="grid size-10 place-items-center rounded-full bg-primary-soft text-xs font-semibold text-primary">
              {user?.avatarInitials}
            </Link>
          </div>
        </div>

        {session.data?.status === "active" && (
          <div className="px-5 pt-5 md:px-8">
            <Link to="/session/active" className="card-soft flex items-center gap-3 p-4">
              <span className="size-3 animate-pulse rounded-full bg-primary" />
              <span className="text-sm font-medium">Night session is running</span>
              <span className="ml-auto text-sm text-muted-foreground">Open →</span>
            </Link>
          </div>
        )}

        {/* Last night hero */}
        <div className="px-5 pt-5 md:px-8">
          {summary.isLoading ? (
            <Skeleton className="h-64" />
          ) : summary.data ? (
            <div className="card-soft overflow-hidden p-5">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium">{t("last_night")}</p>
                  <p className="text-xs text-muted-foreground">
                    {new Date(summary.data.date).toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" })}
                  </p>
                </div>
                <span className="grid size-10 place-items-center rounded-full bg-primary-soft text-primary">
                  <Wind className="size-5" />
                </span>
              </div>
              <div className="mt-4 flex items-end gap-6">
                <div>
                  <p className="text-4xl font-semibold tracking-tight">
                    {summary.data.coughs} <span className="text-base font-normal text-muted-foreground">{t("coughs")}</span>
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">7-night average: {summary.data.coughsPrevAvg}</p>
                </div>
                <div className="ml-auto text-right">
                  <p className="text-2xl font-semibold tracking-tight">
                    {summary.data.sleepHours}
                    <span className="text-sm font-normal text-muted-foreground"> {t("hours")}</span>
                  </p>
                  <p className="text-xs text-muted-foreground">in bed</p>
                </div>
              </div>
              <div className="mt-4 rounded-2xl bg-muted/60 p-3">
                <HourlyBars data={summary.data.hourly} />
              </div>
              <p className="mt-3 text-sm text-muted-foreground">{summary.data.note}</p>
            </div>
          ) : null}
        </div>
      </div>

      {/* Quick actions */}
      <div className="flex flex-wrap gap-2 px-5 pt-5 md:px-8">
        {QUICK.map((q) => (
          <Link key={q.to} to={q.to} className="pill inline-flex items-center gap-2 px-4 py-2.5 text-sm font-medium hover:bg-muted">
            <q.icon className="size-4 text-primary" />
            {q.label}
          </Link>
        ))}
      </div>

      {/* Today's numbers */}
      <div className="px-5 pt-7 md:px-8">
        <SectionTitle title="This week" to="/dashboard" />
        {dash.isLoading || !dash.data ? (
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-28" />
            ))}
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <StatCard label={t("sleep")} value={dash.data.averages.sleepHours} unit="h / night" icon={Moon} />
            <StatCard label={t("weight")} value={dash.data.averages.weight} unit="kg" icon={Scale} />
            <StatCard label={t("activity")} value={dash.data.averages.steps.toLocaleString()} unit={t("steps")} icon={Footprints} />
            <StatCard label={t("medications")} value={`${Math.round(dash.data.averages.adherence * 100)}%`} unit="taken" icon={Pill} />
          </div>
        )}
      </div>

      {/* Change noticed */}
      <div className="px-5 pt-7 md:px-8">
        <SectionTitle title={t("change_noticed")} to="/trends" />
        <div className="grid gap-3 md:grid-cols-2">
          {dash.data?.changes.slice(0, 2).map((c) => <ChangeNoticedCard key={c.id} card={c} />)}
        </div>
      </div>

      <Disclaimer />
    </AppShell>
  );
}
