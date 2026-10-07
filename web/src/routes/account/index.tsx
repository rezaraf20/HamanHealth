import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { AccountSection, btnPrimary, input } from "@/components/account-ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export const Route = createFileRoute("/account/")({
  head: () => ({
    meta: [
      { title: "Profile — Haman Health" },
      { name: "description", content: "Manage your Haman Health profile, security, privacy and preferences." },
      { property: "og:title", content: "Profile — Haman Health" },
      { property: "og:description", content: "Manage your Haman Health profile, security, privacy and preferences." },
    ],
  }),
  component: ProfilePage,
});

function ProfilePage() {
  const { user, setUser } = useAuth();
  const [name, setName] = useState(user?.name ?? "");
  const [busy, setBusy] = useState(false);
  useEffect(() => setName(user?.name ?? ""), [user?.name]);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setUser(await api.account.updateProfile({ name }));
    setBusy(false);
    toast.success("Profile saved");
  }

  return (
    <AccountSection title="Profile" description="How you appear in the app.">
      <form onSubmit={save} className="card-soft space-y-4 p-5">
        <div className="flex items-center gap-4">
          <div className="grid size-16 place-items-center rounded-full bg-primary-soft text-lg font-semibold text-primary">{user?.avatarInitials}</div>
          <div>
            <p className="text-sm font-medium">{user?.name}</p>
            <p className="text-xs text-muted-foreground">Member since {user && new Date(user.createdAt).toLocaleDateString()}</p>
          </div>
        </div>
        <label className="block">
          <span className="mb-1.5 block text-sm font-medium">Full name</span>
          <input className={input} value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label className="block">
          <span className="mb-1.5 block text-sm font-medium">Email</span>
          <input className={input} value={user?.email ?? ""} disabled />
          <span className="mt-1 block text-xs text-muted-foreground">Contact support to change your email address.</span>
        </label>
        <button className={btnPrimary} disabled={busy || name.trim().length < 2}>
          Save changes
        </button>
      </form>
    </AccountSection>
  );
}
