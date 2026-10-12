import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { AccountSection, btnOutline, btnPrimary, input } from "@/components/account-ui";
import { UserAvatar } from "@/components/user-avatar";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fileToAvatarDataUrl } from "@/lib/avatar";
import { cn } from "@/lib/utils";

export function ProfilePage() {
  const { user, setUser } = useAuth();
  const [name, setName] = useState(user?.name ?? "");
  const [busy, setBusy] = useState(false);
  const [photoBusy, setPhotoBusy] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  useEffect(() => setName(user?.name ?? ""), [user?.name]);

  async function changePhoto(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = ""; // so picking the same file again still fires onChange
    if (!file) return;
    setPhotoBusy(true);
    try {
      setUser(await api.account.setAvatar(await fileToAvatarDataUrl(file)));
      toast.success("Profile photo updated");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not update your photo");
    } finally {
      setPhotoBusy(false);
    }
  }

  async function removePhoto() {
    setPhotoBusy(true);
    try {
      setUser(await api.account.removeAvatar());
      toast.success("Profile photo removed");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not remove your photo");
    } finally {
      setPhotoBusy(false);
    }
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      setUser(await api.account.updateProfile({ name }));
      toast.success("Profile saved");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not save your profile");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AccountSection title="Profile" description="How you appear in the app.">
      <form onSubmit={save} className="card-soft space-y-4 p-5">
        <div className="flex items-center gap-4">
          <UserAvatar user={user} className="size-16 text-lg" />
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">{user?.name}</p>
            <p className="text-xs text-muted-foreground">Member since {user && new Date(user.createdAt).toLocaleDateString()}</p>
            <div className="mt-2 flex flex-wrap gap-2">
              <input ref={fileInput} type="file" accept="image/*" className="hidden" onChange={changePhoto} />
              <button type="button" className={cn(btnOutline, "h-9 px-4")} disabled={photoBusy} onClick={() => fileInput.current?.click()}>
                {user?.avatarUrl ? "Change photo" : "Add photo"}
              </button>
              {user?.avatarUrl && (
                <button type="button" className={cn(btnOutline, "h-9 px-4")} disabled={photoBusy} onClick={() => void removePhoto()}>
                  Remove
                </button>
              )}
            </div>
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
