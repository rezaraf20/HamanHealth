import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { Activity, FileText, Moon, ShieldCheck } from "lucide-react";
import { useState } from "react";

import { ghostBtn, primaryBtn } from "@/components/auth-layout";
import { useRequireAuth } from "@/components/app-shell";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/onboarding")({
  head: () => ({
    meta: [
      { title: "Welcome — Haman Health" },
      { name: "description", content: "A short introduction to night sessions, trends and records in Haman Health." },
      { property: "og:title", content: "Welcome — Haman Health" },
      { property: "og:description", content: "A short introduction to night sessions, trends and records in Haman Health." },
    ],
  }),
  component: OnboardingPage,
});

const STEPS = [
  {
    icon: Moon,
    title: "Track nights, gently",
    body: "Start a session before bed. Your phone listens for coughs on-device and only keeps a count per moment — never a recording.",
  },
  {
    icon: Activity,
    title: "See what changes",
    body: "Coughs, sleep, weight, activity and medication come together as trends over 7, 30 or 90 days. No scores, no alarms.",
  },
  {
    icon: FileText,
    title: "Keep records in one place",
    body: "Upload letters, lab results or prescriptions. We extract the information written on them — we don't interpret it.",
  },
  {
    icon: ShieldCheck,
    title: "Not a diagnostic tool",
    body: "Haman Health helps you notice patterns to discuss with your GP. It never tells you what's wrong or what to take.",
  },
];

function OnboardingPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [i, setI] = useState(0);
  useRequireAuth();
  const step = STEPS[i] ?? STEPS[0]!;
  const last = i === STEPS.length - 1;

  return (
    <div className="min-h-screen bg-background bg-sky-wash">
      <div className="mx-auto flex min-h-screen w-full max-w-md flex-col px-6 pt-14 pb-10">
        <div className="flex flex-1 flex-col items-center justify-center text-center">
          <div className="relative mb-10 grid size-40 place-items-center">
            <div className="absolute inset-0 animate-breathe rounded-full orb" />
            <step.icon className="relative size-12 text-card" strokeWidth={1.6} />
          </div>
          <h1 className="text-3xl font-semibold tracking-tight">{step.title}</h1>
          <p className="mt-4 max-w-sm text-base leading-relaxed text-muted-foreground">{step.body}</p>
        </div>

        <div className="mb-6 flex justify-center gap-2">
          {STEPS.map((_, idx) => (
            <button
              key={idx}
              aria-label={`Step ${idx + 1}`}
              onClick={() => setI(idx)}
              className={cn("h-1.5 rounded-full bg-border transition-all", idx === i ? "w-8 bg-primary" : "w-2")}
            />
          ))}
        </div>
        <div className="space-y-3">
          <button className={primaryBtn} onClick={() => (last ? navigate({ to: "/" }) : setI(i + 1))}>
            {last ? "Get started" : t("continue")}
          </button>
          {!last && (
            <button className={ghostBtn} onClick={() => navigate({ to: "/" })}>
              Skip
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
