import { Link, createFileRoute, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { toast } from "sonner";
import { z } from "zod";

import { AuthLayout, primaryBtn } from "@/components/auth-layout";
import { InputOTP, InputOTPGroup, InputOTPSlot } from "@/components/ui/input-otp";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";

export const Route = createFileRoute("/auth/two-factor")({
  validateSearch: z.object({ challenge: z.string().optional() }),
  head: () => ({
    meta: [
      { title: "Two-factor code — Haman Health" },
      { name: "description", content: "Enter your two-factor authentication code to finish signing in." },
      { property: "og:title", content: "Two-factor code — Haman Health" },
      { property: "og:description", content: "Enter your two-factor authentication code to finish signing in." },
    ],
  }),
  component: TwoFactorPage,
});

function TwoFactorPage() {
  const { t } = useI18n();
  const { challenge } = Route.useSearch();
  const navigate = useNavigate();
  const { refresh } = useAuth();
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await api.auth.verify2fa(challenge ?? "", code);
      await refresh();
      const consent = await api.consent.get();
      navigate({ to: consent.acceptedAt ? "/" : "/auth/consent" });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Invalid code");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthLayout title="Enter your code" subtitle="Open your authenticator app and type the 6-digit code.">
      <form onSubmit={submit} className="space-y-6">
        <div className="flex justify-center">
          <InputOTP maxLength={6} value={code} onChange={setCode} autoFocus>
            <InputOTPGroup className="gap-2">
              {[0, 1, 2, 3, 4, 5].map((i) => (
                <InputOTPSlot key={i} index={i} className="size-12 rounded-2xl border text-lg first:rounded-l-2xl last:rounded-r-2xl" />
              ))}
            </InputOTPGroup>
          </InputOTP>
        </div>
        <button className={primaryBtn} disabled={busy || code.length < 6}>
          {busy ? t("loading") : "Verify"}
        </button>
        <Link to="/auth/login" className="block text-center text-sm text-muted-foreground hover:text-primary">
          {t("back")}
        </Link>
      </form>
    </AuthLayout>
  );
}
