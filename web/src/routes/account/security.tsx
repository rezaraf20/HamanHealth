import { createFileRoute } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { AccountSection, Row, btnOutline, btnPrimary, input } from "@/components/account-ui";
import { Switch } from "@/components/ui/switch";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export const Route = createFileRoute("/account/security")({
  head: () => ({
    meta: [
      { title: "Security — Haman Health" },
      { name: "description", content: "Change your password, manage two-factor authentication and active sessions." },
      { property: "og:title", content: "Security — Haman Health" },
      { property: "og:description", content: "Change your password, manage two-factor authentication and active sessions." },
    ],
  }),
  component: SecurityPage,
});

function SecurityPage() {
  const { user, setUser } = useAuth();
  const qc = useQueryClient();
  const sessions = useQuery({ queryKey: ["login-sessions"], queryFn: api.account.loginSessions });
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [busy, setBusy] = useState(false);

  async function changePassword(e: React.FormEvent) {
    e.preventDefault();
    if (next.length < 8) {
      toast.error("Use at least 8 characters.");
      return;
    }
    setBusy(true);
    await api.account.changePassword(current, next);
    setBusy(false);
    setCurrent("");
    setNext("");
    toast.success("Password updated");
  }

  async function toggle2fa(v: boolean) {
    setUser(await api.account.setTwoFactor(v));
    toast.success(v ? "Two-factor authentication enabled" : "Two-factor authentication disabled");
  }

  async function revoke(id: string) {
    await api.account.revokeSession(id);
    await qc.invalidateQueries({ queryKey: ["login-sessions"] });
    toast.success("Device signed out");
  }

  return (
    <AccountSection title="Security" description="Keep your account protected.">
      <form onSubmit={changePassword} className="card-soft space-y-3 p-5">
        <p className="text-sm font-semibold">Change password</p>
        <input className={input} type="password" placeholder="Current password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required />
        <input className={input} type="password" placeholder="New password (min. 8 characters)" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} required />
        <button className={btnPrimary} disabled={busy}>
          Update password
        </button>
      </form>

      <div className="card-soft px-5">
        <Row title="Two-factor authentication" hint="Ask for a code from your authenticator app at sign-in.">
          <Switch checked={!!user?.twoFactorEnabled} onCheckedChange={(v) => void toggle2fa(v)} />
        </Row>
      </div>

      <div className="card-soft p-5">
        <p className="text-sm font-semibold">Active sessions</p>
        <ul className="mt-2 divide-y">
          {sessions.data?.map((s) => (
            <li key={s.id}>
              <Row title={`${s.device}${s.current ? " · this device" : ""}`} hint={`${s.location} · ${new Date(s.lastActive).toLocaleString()}`}>
                {!s.current && (
                  <button onClick={() => void revoke(s.id)} className={`${btnOutline} h-9 px-3 text-xs`}>
                    Sign out
                  </button>
                )}
              </Row>
            </li>
          ))}
        </ul>
      </div>
    </AccountSection>
  );
}
