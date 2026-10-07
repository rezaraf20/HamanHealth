import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { AuthLayout, primaryBtn } from "@/components/auth-layout";
import { Switch } from "@/components/ui/switch";
import { api, type ConsentState } from "@/lib/api";
import { CONSENT_ITEMS } from "@/lib/consent";
import { useI18n } from "@/lib/i18n";

export const Route = createFileRoute("/auth/consent")({
  head: () => ({
    meta: [
      { title: "Your consent — Haman Health" },
      { name: "description", content: "Choose what Haman Health may process. Audio is never stored or uploaded." },
      { property: "og:title", content: "Your consent — Haman Health" },
      { property: "og:description", content: "Choose what Haman Health may process. Audio is never stored or uploaded." },
    ],
  }),
  component: ConsentPage,
});



function ConsentPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [state, setState] = useState<ConsentState | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void api.consent.get().then(setState);
  }, []);

  async function accept() {
    if (!state?.coughTracking) {
      toast.error("Night cough events are needed for the app to work.");
      return;
    }
    setBusy(true);
    await api.consent.update({ ...state, acceptedAt: new Date().toISOString() });
    setBusy(false);
    navigate({ to: "/onboarding" });
  }

  return (
    <AuthLayout title="Before we begin" subtitle="You stay in control of what the app may do. Change this anytime under Account → Privacy.">
      <div className="space-y-3">
        {CONSENT_ITEMS.map((item) => (
          <div key={item.key} className="flex items-start gap-3 rounded-2xl border p-3.5">
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium">
                {item.title} {item.required && <span className="text-xs text-muted-foreground">(required)</span>}
              </p>
              <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">{item.body}</p>
            </div>
            <Switch checked={!!state?.[item.key]} onCheckedChange={(v) => state && setState({ ...state, [item.key]: v })} disabled={!state} />
          </div>
        ))}
        <p className="rounded-2xl bg-primary-soft px-3.5 py-3 text-xs leading-relaxed text-primary">{t("privacy_note")}</p>
        <button onClick={accept} className={primaryBtn} disabled={busy || !state}>
          {busy ? t("loading") : "Agree and continue"}
        </button>
      </div>
    </AuthLayout>
  );
}
