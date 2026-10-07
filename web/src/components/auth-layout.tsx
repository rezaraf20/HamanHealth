import type { ReactNode } from "react";

import { Logo } from "@/components/logo";
import { useI18n } from "@/lib/i18n";

export function AuthLayout({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  const { t } = useI18n();
  return (
    <div className="min-h-screen bg-background bg-sky-wash">
      <div className="mx-auto flex min-h-screen w-full max-w-md flex-col px-6 pt-16 pb-10">
        <div className="mb-8 flex flex-col items-center text-center">
          <Logo className="mb-6 h-12" />
          <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
          {subtitle && <p className="mt-2 text-sm text-muted-foreground">{subtitle}</p>}
        </div>
        <div className="card-soft p-5">{children}</div>
        <p className="mt-auto pt-8 text-center text-[11px] text-muted-foreground">{t("notDiagnostic")}</p>
      </div>
    </div>
  );
}

export function Field({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-medium">{label}</span>
      {children}
    </label>
  );
}

export const inputClass =
  "h-12 w-full rounded-2xl border bg-background px-4 text-sm outline-none transition focus:border-primary focus:ring-2 focus:ring-ring/30";

export const primaryBtn =
  "inline-flex h-12 w-full items-center justify-center rounded-full bg-primary text-sm font-semibold text-primary-foreground transition hover:brightness-110 disabled:opacity-50";

export const ghostBtn =
  "inline-flex h-12 w-full items-center justify-center rounded-full border bg-card text-sm font-medium text-foreground transition hover:bg-muted";
