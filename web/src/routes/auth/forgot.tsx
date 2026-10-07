import { Link, createFileRoute } from "@tanstack/react-router";
import { useState } from "react";

import { AuthLayout, Field, inputClass, primaryBtn } from "@/components/auth-layout";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

export const Route = createFileRoute("/auth/forgot")({
  head: () => ({
    meta: [
      { title: "Reset password — Haman Health" },
      { name: "description", content: "Request a password reset link for your Haman Health account." },
      { property: "og:title", content: "Reset password — Haman Health" },
      { property: "og:description", content: "Request a password reset link for your Haman Health account." },
    ],
  }),
  component: ForgotPage,
});

function ForgotPage() {
  const { t } = useI18n();
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    await api.auth.forgotPassword(email).catch(() => undefined);
    setBusy(false);
    setSent(true);
  }

  return (
    <AuthLayout title="Reset your password" subtitle="We'll email you a link to choose a new one.">
      {sent ? (
        <div className="space-y-4 text-center">
          <p className="text-sm">If an account exists for <span className="font-medium">{email}</span>, a reset link is on its way.</p>
          <Link to="/auth/login" className={primaryBtn}>
            {t("back")}
          </Link>
        </div>
      ) : (
        <form onSubmit={submit} className="space-y-4">
          <Field label={t("email")}>
            <input className={inputClass} type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" />
          </Field>
          <button className={primaryBtn} disabled={busy}>
            {busy ? t("loading") : "Send reset link"}
          </button>
          <Link to="/auth/login" className="block text-center text-sm text-muted-foreground hover:text-primary">
            {t("back")}
          </Link>
        </form>
      )}
    </AuthLayout>
  );
}
