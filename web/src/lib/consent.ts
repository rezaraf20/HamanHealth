import type { ConsentState } from "./api";

export const CONSENT_ITEMS: { key: keyof Omit<ConsentState, "acceptedAt">; title: string; body: string; required?: boolean }[] = [
  {
    key: "coughTracking",
    title: "Night cough events",
    body: "Detect coughs, sneezes and snoring on your phone during the night and send when each one happened.",
    required: true,
  },
  {
    key: "audioClips",
    title: "Short audio clips",
    body: "Also send a 2.5-second clip of each detected cough or sneeze, so you can listen back. Clips are encrypted and deleted after 90 days. A whole night is never recorded.",
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
