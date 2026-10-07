import { createFileRoute } from "@tanstack/react-router";
import { Check } from "lucide-react";
import { toast } from "sonner";

import { AccountSection } from "@/components/account-ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useI18n, type Locale } from "@/lib/i18n";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/account/language")({
  head: () => ({
    meta: [
      { title: "Language — Haman Health" },
      { name: "description", content: "Choose English or Nederlands for the Haman Health interface." },
      { property: "og:title", content: "Language — Haman Health" },
      { property: "og:description", content: "Choose English or Nederlands for the Haman Health interface." },
    ],
  }),
  component: LanguagePage,
});

const LOCALES: { value: Locale; label: string; native: string }[] = [
  { value: "en", label: "English", native: "English" },
  { value: "nl", label: "Dutch", native: "Nederlands" },
];

function LanguagePage() {
  const { locale, setLocale, t } = useI18n();
  const { setUser } = useAuth();

  async function choose(l: Locale) {
    setLocale(l);
    setUser(await api.account.updateProfile({ locale: l }));
    toast.success(l === "nl" ? "Taal gewijzigd" : "Language updated");
  }

  return (
    <AccountSection title={t("language")} description="Applies to the whole app.">
      <div className="card-soft divide-y px-5">
        {LOCALES.map((l) => (
          <button key={l.value} onClick={() => void choose(l.value)} className="flex w-full items-center gap-3 py-4 text-left">
            <div className="flex-1">
              <p className="text-sm font-medium">{l.native}</p>
              <p className="text-xs text-muted-foreground">{l.label}</p>
            </div>
            <span className={cn("grid size-6 place-items-center rounded-full border", locale === l.value && "border-primary bg-primary text-primary-foreground")}>
              {locale === l.value && <Check className="size-3.5" />}
            </span>
          </button>
        ))}
      </div>
    </AccountSection>
  );
}
