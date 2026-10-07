import { Link, useNavigate, useRouterState } from "@tanstack/react-router";
import { Activity, CalendarClock, FileText, Home, LayoutGrid, LogOut, Moon, User, type LucideIcon } from "lucide-react";
import { useEffect, type ReactNode } from "react";

import { useAuth } from "@/lib/auth";
import { useI18n, type MessageKey } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { Logo } from "./logo";
import { SupportChat } from "./support-chat";

type NavItem = { to: string; icon: LucideIcon; label: MessageKey; mobile?: boolean };

const NAV: NavItem[] = [
  { to: "/", icon: Home, label: "nav_home", mobile: true },
  { to: "/dashboard", icon: LayoutGrid, label: "nav_dashboard" },
  { to: "/trends", icon: Activity, label: "nav_trends", mobile: true },
  { to: "/timeline", icon: CalendarClock, label: "nav_timeline", mobile: true },
  { to: "/records", icon: FileText, label: "nav_records" },
  { to: "/session", icon: Moon, label: "nav_session" },
  { to: "/account", icon: User, label: "nav_profile", mobile: true },
];

export function useRequireAuth() {
  const { ready, user } = useAuth();
  const navigate = useNavigate();
  useEffect(() => {
    if (ready && !user) navigate({ to: "/auth/login" });
  }, [ready, user, navigate]);
  return { ready, user };
}

export function AppShell({
  children,
  title,
  hideChrome,
  night,
}: {
  children: ReactNode;
  title?: string;
  hideChrome?: boolean;
  night?: boolean;
}) {
  const { t } = useI18n();
  const { user, signOut } = useAuth();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const { ready } = useRequireAuth();

  if (!ready || !user) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <div className="size-10 animate-breathe rounded-full orb" />
      </div>
    );
  }

  const isActive = (to: string) => (to === "/" ? pathname === "/" : pathname.startsWith(to));

  return (
    <div className={cn("min-h-screen bg-background text-foreground", night && "dark")}>
      <div className="mx-auto flex w-full max-w-7xl">
        {!hideChrome && (
          <aside className="sticky top-0 hidden h-screen w-64 shrink-0 flex-col border-r border-sidebar-border bg-sidebar px-4 py-6 md:flex">
            <Link to="/" className="mb-8 flex items-center px-2" aria-label={t("appName")}>
              <Logo variant={night ? "white" : "dark"} className="h-9" />
            </Link>
            <nav className="flex flex-1 flex-col gap-1">
              {NAV.map((item) => (
                <Link
                  key={item.to}
                  to={item.to}
                  className={cn(
                    "flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium text-sidebar-foreground/80 transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
                    isActive(item.to) && "bg-sidebar-accent text-sidebar-accent-foreground",
                  )}
                >
                  <item.icon className="size-[18px]" strokeWidth={1.8} />
                  {t(item.label)}
                </Link>
              ))}
            </nav>
            <div className="mt-4 flex items-center gap-3 rounded-2xl border border-sidebar-border p-3">
              <div className="grid size-9 shrink-0 place-items-center rounded-full bg-primary-soft text-xs font-semibold text-primary">
                {user.avatarInitials}
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{user.name}</p>
                <p className="truncate text-xs text-muted-foreground">{user.email}</p>
              </div>
              <button
                onClick={() => void signOut()}
                aria-label={t("logout")}
                className="rounded-lg p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
              >
                <LogOut className="size-4" />
              </button>
            </div>
          </aside>
        )}

        <main className={cn("min-w-0 flex-1", !hideChrome && "pb-safe md:pb-10")}>
          {title && !hideChrome && (
            <header className="sticky top-0 z-20 flex h-14 items-center border-b border-border/60 bg-background/80 px-4 backdrop-blur md:hidden">
              <h1 className="text-base font-semibold">{title}</h1>
            </header>
          )}
          {children}
        </main>
      </div>

      {!hideChrome && (
        <nav className="fixed inset-x-0 bottom-0 z-30 border-t border-border bg-card/90 backdrop-blur md:hidden">
          <div className="mx-auto grid max-w-md grid-cols-4 px-2 pb-[env(safe-area-inset-bottom)]">
            {NAV.filter((n) => n.mobile).map((item) => (
              <Link
                key={item.to}
                to={item.to}
                className={cn(
                  "flex flex-col items-center gap-1 py-2.5 text-[11px] font-medium text-muted-foreground",
                  isActive(item.to) && "text-primary",
                )}
              >
                <span className={cn("grid size-9 place-items-center rounded-full", isActive(item.to) && "bg-primary-soft")}>
                  <item.icon className="size-5" strokeWidth={isActive(item.to) ? 2.2 : 1.8} />
                </span>
                {t(item.label)}
              </Link>
            ))}
          </div>
        </nav>
      )}

      <SupportChat />
    </div>
  );
}
