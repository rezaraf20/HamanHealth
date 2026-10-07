import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { AccountSection, Row } from "@/components/account-ui";
import { Switch } from "@/components/ui/switch";
import { api, type NotificationPrefs } from "@/lib/api";

export const Route = createFileRoute("/account/notifications")({
  head: () => ({
    meta: [
      { title: "Notifications — Haman Health" },
      { name: "description", content: "Choose which reminders and summaries Haman Health sends you." },
      { property: "og:title", content: "Notifications — Haman Health" },
      { property: "og:description", content: "Choose which reminders and summaries Haman Health sends you." },
    ],
  }),
  component: NotificationsPage,
});

const ITEMS: { key: keyof NotificationPrefs; title: string; hint: string }[] = [
  { key: "morningSummary", title: "Morning summary", hint: "A short recap after each night session." },
  { key: "sessionReminder", title: "Session reminder", hint: "A nudge at your usual bedtime to start tracking." },
  { key: "medicationReminder", title: "Medication reminder", hint: "Reminders for scheduled medication you've added." },
  { key: "weeklyTrends", title: "Weekly trends", hint: "One message a week with what changed." },
  { key: "productUpdates", title: "Product updates", hint: "Occasional news about new features." },
];

function NotificationsPage() {
  const [prefs, setPrefs] = useState<NotificationPrefs | null>(null);
  useEffect(() => {
    void api.account.notifications().then(setPrefs);
  }, []);

  async function toggle(key: keyof NotificationPrefs, v: boolean) {
    if (!prefs) return;
    const next = { ...prefs, [key]: v };
    setPrefs(next);
    await api.account.updateNotifications(next);
    toast.success("Saved");
  }

  return (
    <AccountSection title="Notifications" description="Only what you find useful.">
      <div className="card-soft divide-y px-5">
        {ITEMS.map((i) => (
          <Row key={i.key} title={i.title} hint={i.hint}>
            <Switch checked={!!prefs?.[i.key]} disabled={!prefs} onCheckedChange={(v) => void toggle(i.key, v)} />
          </Row>
        ))}
      </div>
    </AccountSection>
  );
}
