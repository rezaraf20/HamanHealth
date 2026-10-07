import { Link, Outlet, createFileRoute, useRouterState } from "@tanstack/react-router";
import { Bell, ChevronRight, Globe, LogOut, Shield, Smartphone, UserRound, Lock, type LucideIcon } from "lucide-react";

import { AppShell } from "@/components/app-shell";
import { Disclaimer, PageHeader } from "@/components/haman-ui";
import { useAuth } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/account")({
  component: AccountLayout,
});

const ACCOUNT_SECTIONS: { to: string; label: string; hint: string; icon: LucideIcon }[] = [
  { to: "/account", label: "Profile", hint: "Name and email", icon: UserRound },
  { to: "/account/security", label: "Security", hint: "Password, 2FA, sessions", icon: Lock },
  { to: "/account/privacy", label: "Privacy", hint: "Consent, export, delete", icon: Shield },
  { to: "/account/notifications", label: "Notifications", hint: "Reminders and summaries", icon: Bell },
  { to: "/account/language", label: "Language", hint: "English · Nederlands", icon: Globe },
  { to: "/account/devices", label: "Connected devices", hint: "Phone, scale, tracker", icon: Smartphone },
];

function AccountLayout() {
  const { t } = useI18n();
  const { user, signOut } = useAuth();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const isIndex = pathname === "/account" || pathname === "/account/";

  return (
    <AppShell title={t("nav_profile")}>
      <PageHeader eyebrow={user?.email} title={user?.name ?? t("nav_account")} className={cn(!isIndex && "hidden md:flex")} />
      <div className="px-5 md:px-8">
        <div className="md:grid md:grid-cols-[260px_minmax(0,1fr)] md:gap-6">
          <nav className={cn("space-y-1", !isIndex && "hidden md:block")}>
            {ACCOUNT_SECTIONS.map((s) => {
              const active = s.to === "/account" ? isIndex : pathname.startsWith(s.to);
              return (
                <Link
                  key={s.to}
                  to={s.to}
                  className={cn(
                    "card-soft flex items-center gap-3 p-3.5 transition hover:bg-muted/50 md:rounded-xl md:border-0 md:shadow-none",
                    active && "md:bg-primary-soft md:text-primary",
                  )}
                >
                  <span className={cn("grid size-9 shrink-0 place-items-center rounded-full bg-primary-soft text-primary", active && "md:bg-primary md:text-primary-foreground")}>
                    <s.icon className="size-4" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium">{s.label}</p>
                    <p className="truncate text-xs text-muted-foreground md:hidden">{s.hint}</p>
                  </div>
                  <ChevronRight className="size-4 text-muted-foreground md:hidden" />
                </Link>
              );
            })}
            <button onClick={() => void signOut()} className="card-soft flex w-full items-center gap-3 p-3.5 text-left hover:bg-muted/50 md:rounded-xl md:border-0 md:shadow-none">
              <span className="grid size-9 shrink-0 place-items-center rounded-full bg-muted text-foreground">
                <LogOut className="size-4" />
              </span>
              <p className="text-sm font-medium">{t("logout")}</p>
            </button>
          </nav>
          <div className={cn(isIndex && "hidden md:block")}>
            <Outlet />
          </div>
        </div>
      </div>
      <Disclaimer />
    </AppShell>
  );
}
