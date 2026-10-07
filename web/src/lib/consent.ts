import type { ConsentState } from "./api";

export const CONSENT_ITEMS: { key: keyof Omit<ConsentState, "acceptedAt">; title: string; body: string; required?: boolean }[] = [
  {
    key: "coughTracking",
    title: "Night cough events",
    body: "Detect coughs on your device during a session. Only the time and count are sent — never audio.",
    required: true,
  },
  {
    key: "healthTrends",
    title: "Wellness trends",
    body: "Combine cough events with weight, activity, sleep and medication logs to show changes over time.",
  },
  {
    key: "recordsProcessing",
    title: "Records processing",
    body: "Extract text fields (dates, values, issuer) from documents you upload. No medical interpretation.",
  },
  {
    key: "productAnalytics",
    title: "Anonymous product analytics",
    body: "Help us improve the app with anonymised usage statistics.",
  },
];
