import type { User } from "@/lib/api";
import { cn } from "@/lib/utils";

/** The user's profile photo, or their initials when none is set. Pass the size and text size via className. */
export function UserAvatar({
  user,
  className,
}: {
  user: Pick<User, "avatarInitials" | "avatarUrl"> | null | undefined;
  className?: string;
}) {
  return (
    <span className={cn("grid shrink-0 place-items-center overflow-hidden rounded-full bg-primary-soft font-semibold text-primary", className)}>
      {user?.avatarUrl ? <img src={user.avatarUrl} alt="" className="size-full object-cover" /> : user?.avatarInitials}
    </span>
  );
}
