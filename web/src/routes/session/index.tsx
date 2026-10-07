import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Mic, Moon, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { AppShell } from "@/components/app-shell";
import { primaryBtn } from "@/components/auth-layout";
import { Disclaimer, PageHeader } from "@/components/haman-ui";
import { coughSession } from "@/lib/cough-session";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/session/")({
  head: () => ({
    meta: [
      { title: "Night session — Haman Health" },
      { name: "description", content: "Set up tonight's cough tracking session. Detection runs on your device; no audio leaves it." },
      { property: "og:title", content: "Night session — Haman Health" },
      { property: "og:description", content: "Set up tonight's cough tracking session. Detection runs on your device; no audio leaves it." },
    ],
  }),
  component: SessionSetupPage,
});

const SENS = ["low", "medium", "high"] as const;
type Sensitivity = (typeof SENS)[number];

/** Next occurrence of an HH:MM wall-clock time, as an ISO timestamp. */
function nextTimeIso(hhmm: string): string {
  const parts = hhmm.split(":");
  const h = Number(parts[0] ?? 7);
  const m = Number(parts[1] ?? 0);
  const at = new Date();
  at.setSeconds(0, 0);
  at.setHours(h, m);
  if (at.getTime() <= Date.now()) at.setDate(at.getDate() + 1);
  return at.toISOString();
}

function SessionSetupPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [sensitivity, setSensitivity] = useState<Sensitivity>("medium");
  const [from, setFrom] = useState("22:30");
  const [to, setTo] = useState("07:00");
  const [busy, setBusy] = useState(false);
  const status = useQuery({ queryKey: ["cough-session", "status"], queryFn: () => coughSession.getStatus() });

  async function start() {
    setBusy(true);
    try {
      if (!(await coughSession.isAvailable())) throw new Error("Cough detection is not available on this device");
      const permission = await coughSession.requestPermissions();
      if (permission !== "granted") throw new Error("Permission is needed to track coughs tonight");
      await coughSession.start({ autoStopAt: nextTimeIso(to), sensitivity });
      await qc.invalidateQueries({ queryKey: ["cough-session"] });
      navigate({ to: "/session/active" });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not start session");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AppShell title={t("nav_session")}>
      <PageHeader eyebrow="Tonight" title={t("session_setup")} />
      <div className="space-y-4 px-5 md:px-8 md:max-w-2xl">
        {status.data?.state === "running" && (
          <button onClick={() => navigate({ to: "/session/active" })} className="card-soft flex w-full items-center gap-3 p-4 text-left">
            <span className="size-3 animate-pulse rounded-full bg-primary" />
            <span className="text-sm font-medium">A session is already running — open it</span>
          </button>
        )}

        <section className="card-soft p-5">
          <div className="mb-4 flex items-center gap-3">
            <span className="grid size-10 place-items-center rounded-full bg-primary-soft text-primary">
              <Mic className="size-5" />
            </span>
            <div>
              <p className="text-sm font-semibold">Detection sensitivity</p>
              <p className="text-xs text-muted-foreground">Higher picks up softer coughs but may count more noise.</p>
            </div>
          </div>
          <div className="grid grid-cols-3 gap-2">
            {SENS.map((s) => (
              <button
                key={s}
                onClick={() => setSensitivity(s)}
                className={cn(
                  "rounded-2xl border py-3 text-sm font-medium capitalize transition",
                  sensitivity === s ? "border-primary bg-primary-soft text-primary" : "bg-background hover:bg-muted",
                )}
              >
                {s}
              </button>
            ))}
          </div>
        </section>

        <section className="card-soft p-5">
          <div className="mb-4 flex items-center gap-3">
            <span className="grid size-10 place-items-center rounded-full bg-primary-soft text-primary">
              <Moon className="size-5" />
            </span>
            <div>
              <p className="text-sm font-semibold">Quiet hours</p>
              <p className="text-xs text-muted-foreground">The session ends automatically at the end time.</p>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <label className="text-xs text-muted-foreground">
              From
              <input type="time" value={from} onChange={(e) => setFrom(e.target.value)} className="mt-1 h-12 w-full rounded-2xl border bg-background px-3 text-base text-foreground" />
            </label>
            <label className="text-xs text-muted-foreground">
              To
              <input type="time" value={to} onChange={(e) => setTo(e.target.value)} className="mt-1 h-12 w-full rounded-2xl border bg-background px-3 text-base text-foreground" />
            </label>
          </div>
        </section>

        <section className="flex items-start gap-3 rounded-[var(--radius)] bg-primary-soft p-4 text-primary">
          <ShieldCheck className="mt-0.5 size-5 shrink-0" />
          <p className="text-sm leading-relaxed">{t("privacy_note")}</p>
        </section>

        <button onClick={start} className={primaryBtn} disabled={busy}>
          {busy ? t("loading") : t("start_session")}
        </button>
      </div>
      <Disclaimer />
    </AppShell>
  );
}
