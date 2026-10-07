import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { AccountSection, Row, btnDanger, btnOutline } from "@/components/account-ui";
import { Switch } from "@/components/ui/switch";
import { api, type ConsentState } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { CONSENT_ITEMS } from "@/lib/consent";
import { useI18n } from "@/lib/i18n";

export const Route = createFileRoute("/account/privacy")({
  head: () => ({
    meta: [
      { title: "Privacy — Haman Health" },
      { name: "description", content: "Manage consent, export your data or delete your account." },
      { property: "og:title", content: "Privacy — Haman Health" },
      { property: "og:description", content: "Manage consent, export your data or delete your account." },
    ],
  }),
  component: PrivacyPage,
});

function PrivacyPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const { setUser } = useAuth();
  const [consent, setConsent] = useState<ConsentState | null>(null);
  const [exporting, setExporting] = useState(false);
  const [confirmText, setConfirmText] = useState("");

  useEffect(() => {
    void api.consent.get().then(setConsent);
  }, []);

  async function update(key: keyof ConsentState, v: boolean) {
    if (!consent) return;
    const next = await api.consent.update({ ...consent, [key]: v });
    setConsent(next);
    toast.success("Consent updated");
  }

  async function exportData() {
    setExporting(true);
    const { url } = await api.account.exportData();
    setExporting(false);
    const a = document.createElement("a");
    a.href = url;
    a.download = "haman-health-export.json";
    a.click();
    toast.success("Your export has started downloading");
  }

  async function deleteAccount() {
    await api.account.deleteAccount();
    setUser(null);
    toast.success("Your account has been deleted");
    navigate({ to: "/auth/login" });
  }

  return (
    <AccountSection title="Privacy" description="You decide what the app may process.">
      <div className="card-soft px-5">
        {CONSENT_ITEMS.map((item) => (
          <Row key={item.key} title={item.title} hint={item.body}>
            <Switch checked={!!consent?.[item.key]} disabled={!consent || item.required} onCheckedChange={(v) => void update(item.key, v)} />
          </Row>
        ))}
        <p className="pb-4 text-xs text-muted-foreground">{t("privacy_note")}</p>
      </div>

      <div className="card-soft px-5">
        <Row title="Export my data" hint="Download everything we hold about you as a file.">
          <button onClick={() => void exportData()} disabled={exporting} className={btnOutline}>
            {exporting ? "Preparing…" : "Export"}
          </button>
        </Row>
      </div>

      <div className="card-soft space-y-3 p-5">
        <p className="text-sm font-semibold">Delete account</p>
        <p className="text-xs text-muted-foreground">
          This permanently removes your profile, sessions, trends and records. Type <span className="font-medium text-foreground">DELETE</span> to confirm.
        </p>
        <input
          value={confirmText}
          onChange={(e) => setConfirmText(e.target.value)}
          placeholder="DELETE"
          className="h-11 w-full rounded-2xl border bg-background px-4 text-sm outline-none focus:border-destructive"
        />
        <button onClick={() => void deleteAccount()} disabled={confirmText !== "DELETE"} className={btnDanger}>
          Delete my account
        </button>
      </div>
    </AccountSection>
  );
}
