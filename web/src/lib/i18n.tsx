import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export type Locale = "en" | "nl";

const en = {
  appName: "Haman Health",
  tagline: "Gentle night tracking for how you feel over time",
  notDiagnostic: "Haman Health is a wellness companion, not a diagnostic tool.",
  nav_home: "Home",
  nav_dashboard: "Dashboard",
  nav_trends: "Trends",
  nav_timeline: "Timeline",
  nav_records: "Records",
  nav_session: "Night session",
  nav_profile: "Profile",
  nav_account: "Account",
  good_morning: "Good morning",
  good_evening: "Good evening",
  welcome_back: "Welcome back",
  last_night: "Last night",
  coughs: "coughs",
  cough_events: "Cough events",
  sleep: "Sleep",
  weight: "Weight",
  activity: "Activity",
  medications: "Medications",
  steps: "steps",
  hours: "h",
  see_all: "See all",
  start_session: "Start night session",
  end_session: "End session",
  session_setup: "Night session setup",
  session_active: "Session active",
  change_noticed: "Change noticed",
  no_change: "No notable change",
  trend_only: "Trend only — not a medical assessment.",
  range_7: "7 days",
  range_30: "30 days",
  range_90: "90 days",
  login: "Log in",
  register: "Create account",
  forgot: "Forgot password?",
  email: "Email",
  password: "Password",
  continue: "Continue",
  back: "Back",
  save: "Save",
  cancel: "Cancel",
  loading: "Loading…",
  support_title: "Haman support",
  support_hint: "I can help with using the app — sessions, records, settings and privacy.",
  support_placeholder: "Ask about the app…",
  privacy_note: "We never record or upload audio. Only cough events (time and count) leave your device.",
  language: "Language",
  logout: "Log out",
};

export type MessageKey = keyof typeof en;

const nl: Record<MessageKey, string> = {
  appName: "Haman Health",
  tagline: "Zachte nachtmonitoring van hoe je je door de tijd heen voelt",
  notDiagnostic: "Haman Health is een welzijnshulpmiddel, geen diagnostisch instrument.",
  nav_home: "Home",
  nav_dashboard: "Dashboard",
  nav_trends: "Trends",
  nav_timeline: "Tijdlijn",
  nav_records: "Documenten",
  nav_session: "Nachtsessie",
  nav_profile: "Profiel",
  nav_account: "Account",
  good_morning: "Goedemorgen",
  good_evening: "Goedenavond",
  welcome_back: "Welkom terug",
  last_night: "Afgelopen nacht",
  coughs: "hoestjes",
  cough_events: "Hoestmomenten",
  sleep: "Slaap",
  weight: "Gewicht",
  activity: "Activiteit",
  medications: "Medicatie",
  steps: "stappen",
  hours: "u",
  see_all: "Alles",
  start_session: "Nachtsessie starten",
  end_session: "Sessie beëindigen",
  session_setup: "Nachtsessie instellen",
  session_active: "Sessie actief",
  change_noticed: "Verandering opgemerkt",
  no_change: "Geen opvallende verandering",
  trend_only: "Alleen een trend — geen medische beoordeling.",
  range_7: "7 dagen",
  range_30: "30 dagen",
  range_90: "90 dagen",
  login: "Inloggen",
  register: "Account aanmaken",
  forgot: "Wachtwoord vergeten?",
  email: "E-mail",
  password: "Wachtwoord",
  continue: "Doorgaan",
  back: "Terug",
  save: "Opslaan",
  cancel: "Annuleren",
  loading: "Laden…",
  support_title: "Haman-ondersteuning",
  support_hint: "Ik help je met de app — sessies, documenten, instellingen en privacy.",
  support_placeholder: "Vraag iets over de app…",
  privacy_note: "We nemen nooit audio op en uploaden die ook niet. Alleen hoestmomenten (tijd en aantal) verlaten je apparaat.",
  language: "Taal",
  logout: "Uitloggen",
};

const dictionaries: Record<Locale, Record<MessageKey, string>> = { en, nl };

const STORAGE_KEY = "haman.locale";

type I18nContextValue = {
  locale: Locale;
  setLocale: (l: Locale) => void;
  t: (key: MessageKey) => string;
};

const I18nContext = createContext<I18nContextValue>({
  locale: "en",
  setLocale: () => {},
  t: (k) => en[k],
});

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>("en");

  useEffect(() => {
    const stored = window.localStorage.getItem(STORAGE_KEY) as Locale | null;
    if (stored === "en" || stored === "nl") setLocaleState(stored);
  }, []);

  const setLocale = useCallback((l: Locale) => {
    setLocaleState(l);
    window.localStorage.setItem(STORAGE_KEY, l);
  }, []);

  const value = useMemo<I18nContextValue>(
    () => ({ locale, setLocale, t: (key) => dictionaries[locale][key] ?? en[key] }),
    [locale, setLocale],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  return useContext(I18nContext);
}
