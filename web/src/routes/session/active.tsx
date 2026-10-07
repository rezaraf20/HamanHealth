import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useQueryClient } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { AppShell } from "@/components/app-shell";
import { Logo } from "@/components/logo";
import { coughSession, type CoughEvent, type SessionStatus } from "@/lib/cough-session";
import { useI18n } from "@/lib/i18n";

export const Route = createFileRoute("/session/active")({
  head: () => ({
    meta: [
      { title: "Session active — Haman Health" },
      { name: "description", content: "Your night session is running. Only cough counts are recorded — never audio." },
      { property: "og:title", content: "Session active — Haman Health" },
      { property: "og:description", content: "Your night session is running. Only cough counts are recorded — never audio." },
    ],
  }),
  component: ActiveSessionPage,
});

function useElapsed(startedAt?: string) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  if (!startedAt) return "00:00:00";
  const s = Math.max(0, Math.floor((now - new Date(startedAt).getTime()) / 1000));
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(Math.floor(s / 3600))}:${p(Math.floor((s % 3600) / 60))}:${p(s % 60)}`;
}

function ActiveSessionPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [status, setStatus] = useState<SessionStatus | null>(null);
  const [recent, setRecent] = useState<CoughEvent[]>([]);
  const elapsed = useElapsed(status?.startedAt);

  // Status + live cough events come only from the cough session bridge.
  useEffect(() => {
    let cancelled = false;
    void coughSession.getStatus().then((s) => {
      if (cancelled) return;
      setStatus(s);
      if (s.state === "idle") navigate({ to: "/session" });
    });
    const off = coughSession.onCoughEvent((e) => {
      setStatus((prev) => (prev ? { ...prev, eventCount: prev.eventCount + e.count } : prev));
      setRecent((r) => [e, ...r].slice(0, 5));
    });
    return () => {
      cancelled = true;
      off();
    };
  }, [navigate]);

  async function end() {
    const summary = await coughSession.stop();
    await qc.invalidateQueries({ queryKey: ["cough-session"] });
    await qc.invalidateQueries({ queryKey: ["session"] });
    toast.success(`Session saved — ${summary.totalCoughs} cough events. Your morning summary is ready.`);
    navigate({ to: "/" });
  }

  return (
    <AppShell night hideChrome>
      <div className="mx-auto flex min-h-screen w-full max-w-md flex-col px-6 pt-12 pb-10 text-foreground">
        <div className="flex items-center justify-between">
          <span className="inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-medium">
            <span className="size-2 animate-pulse rounded-full bg-accent" />
            {t("session_active")}
          </span>
          <span className="font-mono text-sm tabular-nums text-muted-foreground">{elapsed}</span>
        </div>

        <div className="flex flex-1 flex-col items-center justify-center text-center">
          <Logo variant="white" className="mb-6 h-7 opacity-80" />
          <div className="mb-8 size-40 animate-breathe rounded-full orb opacity-90" />
          <p className="text-6xl font-semibold tracking-tight tabular-nums">{status?.eventCount ?? 0}</p>
          <p className="mt-1 mb-8 text-sm text-muted-foreground">{t("cough_events")}</p>
          <h1 className="text-2xl font-semibold tracking-tight">Sleep well</h1>
          <p className="mt-2 max-w-xs text-sm text-muted-foreground">
            Listening on-device for coughs. Keep the phone nearby; the screen can stay off.
          </p>

          {recent.length > 0 && (
            <div className="mt-8 w-full space-y-1.5 text-left">
              {recent.map((e) => (
                <div key={e.timestamp} className="flex items-center justify-between rounded-2xl bg-card px-4 py-2.5 text-sm">
                  <span className="text-muted-foreground">Cough event</span>
                  <span className="tabular-nums">{new Date(e.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="space-y-3">
          <div className="flex items-start gap-3 rounded-[var(--radius)] bg-card p-4 text-sm text-muted-foreground">
            <ShieldCheck className="mt-0.5 size-4 shrink-0 text-accent" />
            <p>Only the time and count of each cough is stored. Audio is never recorded or uploaded.</p>
          </div>
          <button onClick={end} className="inline-flex h-12 w-full items-center justify-center rounded-full bg-primary text-sm font-semibold text-primary-foreground">
            {t("end_session")}
          </button>
        </div>
      </div>
    </AppShell>
  );
}
