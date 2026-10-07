import { Link, createFileRoute, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { toast } from "sonner";

import { AuthLayout, Field, inputClass, primaryBtn } from "@/components/auth-layout";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";

export const Route = createFileRoute("/auth/login")({
  head: () => ({
    meta: [
      { title: "Log in — Haman Health" },
      { name: "description", content: "Sign in to Haman Health to see your night summaries and wellness trends." },
      { property: "og:title", content: "Log in — Haman Health" },
      { property: "og:description", content: "Sign in to Haman Health to see your night summaries and wellness trends." },
    ],
  }),
  component: LoginPage,
});

function LoginPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const { refresh } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const res = await api.auth.login(email, password);
      if (res.requires2fa) {
        navigate({ to: "/auth/two-factor", search: { challenge: res.challengeId ?? "" } });
        return;
      }
      await refresh();
      const consent = await api.consent.get();
      navigate({ to: consent.acceptedAt ? "/" : "/auth/consent" });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not log in");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthLayout title={t("welcome_back")} subtitle={t("tagline")}>
      <form onSubmit={submit} className="space-y-4">
        <Field label={t("email")}>
          <input className={inputClass} type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" />
        </Field>
        <Field label={t("password")}>
          <input className={inputClass} type="password" required autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" />
        </Field>
        <div className="flex justify-end">
          <Link to="/auth/forgot" className="text-sm text-primary hover:underline">
            {t("forgot")}
          </Link>
        </div>
        <button className={primaryBtn} disabled={busy}>
          {busy ? t("loading") : t("login")}
        </button>
      </form>
      <p className="mt-5 text-center text-sm text-muted-foreground">
        New here?{" "}
        <Link to="/auth/register" className="font-medium text-primary hover:underline">
          {t("register")}
        </Link>
      </p>
    </AuthLayout>
  );
}
