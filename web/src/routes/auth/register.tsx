import { Link, createFileRoute, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { toast } from "sonner";

import { AuthLayout, Field, inputClass, primaryBtn } from "@/components/auth-layout";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";

export const Route = createFileRoute("/auth/register")({
  head: () => ({
    meta: [
      { title: "Create account — Haman Health" },
      { name: "description", content: "Create your Haman Health account for gentle night tracking and trends." },
      { property: "og:title", content: "Create account — Haman Health" },
      { property: "og:description", content: "Create your Haman Health account for gentle night tracking and trends." },
    ],
  }),
  component: RegisterPage,
});

function RegisterPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const { refresh } = useAuth();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (password.length < 8) {
      toast.error("Use at least 8 characters.");
      return;
    }
    setBusy(true);
    try {
      await api.auth.register(name, email, password);
      await refresh();
      navigate({ to: "/auth/consent" });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not create account");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthLayout title={t("register")} subtitle="A calm place to notice how your nights change.">
      <form onSubmit={submit} className="space-y-4">
        <Field label="Full name">
          <input className={inputClass} required value={name} onChange={(e) => setName(e.target.value)} placeholder="Alex Morgan" />
        </Field>
        <Field label={t("email")}>
          <input className={inputClass} type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" />
        </Field>
        <Field label={t("password")}>
          <input className={inputClass} type="password" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} placeholder="At least 8 characters" />
        </Field>
        <button className={primaryBtn} disabled={busy}>
          {busy ? t("loading") : t("continue")}
        </button>
      </form>
      <p className="mt-5 text-center text-sm text-muted-foreground">
        Already have an account?{" "}
        <Link to="/auth/login" className="font-medium text-primary hover:underline">
          {t("login")}
        </Link>
      </p>
    </AuthLayout>
  );
}
