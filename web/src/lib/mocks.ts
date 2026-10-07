/**
 * Local mock backend used while USE_MOCKS is on. Deterministic, in-memory,
 * with a small delay to mimic network latency.
 */
import type {
  ActiveLoginSession,
  ChangeCard,
  ConsentState,
  CoughEvent,
  DailyPoint,
  DashboardData,
  Device,
  HealthRecord,
  Medication,
  NightSession,
  NightSummary,
  NotificationPrefs,
  Range,
  RecordDetail,
  RecordType,
  SupportMessage,
  TimelineEvent,
  TimelineKind,
  Tokens,
  User,
} from "./api";
import { setTokens } from "./api";

const wait = (ms = 350) => new Promise((r) => setTimeout(r, ms));

// seeded pseudo-random for stable charts
function seeded(seed: number) {
  let s = seed;
  return () => {
    s = (s * 9301 + 49297) % 233280;
    return s / 233280;
  };
}

const fmtDate = (d: Date) => d.toISOString().slice(0, 10);
const daysAgo = (n: number) => {
  const d = new Date();
  d.setHours(8, 0, 0, 0);
  d.setDate(d.getDate() - n);
  return d;
};

const tokens = (): Tokens => ({ access: `mock-access-${Date.now()}`, refresh: `mock-refresh-${Date.now()}` });

let user: User = {
  id: "u_1",
  name: "Alex Morgan",
  email: "alex@example.com",
  locale: "en",
  twoFactorEnabled: true,
  createdAt: "2026-05-02T10:00:00Z",
  avatarInitials: "AM",
};

const CONSENT_KEY = "haman.mock.consent";
function loadConsent(): ConsentState {
  if (typeof window !== "undefined") {
    const raw = window.localStorage.getItem(CONSENT_KEY);
    if (raw) return JSON.parse(raw) as ConsentState;
  }
  return { coughTracking: false, healthTrends: false, recordsProcessing: false, productAnalytics: false, acceptedAt: null };
}
let consent = loadConsent();

let session: NightSession | null = null;

// ---------- auth ----------

export async function login(email: string) {
  await wait();
  user = { ...user, email: email || user.email };
  if (user.twoFactorEnabled) return { requires2fa: true as const, challengeId: "ch_1" };
  const t = tokens();
  setTokens(t);
  return { requires2fa: false as const, tokens: t };
}

export async function verify2fa(code: string) {
  await wait();
  if (code.replace(/\D/g, "").length !== 6) throw new Error("Enter the 6-digit code from your authenticator app.");
  const t = tokens();
  setTokens(t);
  return t;
}

export async function register(name: string, email: string) {
  await wait();
  const initials = name
    .split(" ")
    .map((p) => p[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
  user = { ...user, name, email, avatarInitials: initials || "HH", twoFactorEnabled: false };
  consent = { coughTracking: false, healthTrends: false, recordsProcessing: false, productAnalytics: false, acceptedAt: null };
  if (typeof window !== "undefined") window.localStorage.removeItem(CONSENT_KEY);
  const t = tokens();
  setTokens(t);
  return t;
}

export async function ok() {
  await wait();
}

export async function me() {
  await wait(150);
  return user;
}

export function reset() {
  session = null;
}

// ---------- consent ----------

export async function getConsent() {
  await wait(150);
  consent = loadConsent();
  return consent;
}

export async function updateConsent(patch: Partial<ConsentState>) {
  await wait();
  consent = { ...consent, ...patch };
  if (typeof window !== "undefined") window.localStorage.setItem(CONSENT_KEY, JSON.stringify(consent));
  return consent;
}

// ---------- sessions ----------

export async function currentSession() {
  await wait(150);
  return session;
}

export async function startSession(opts: Pick<NightSession, "sensitivity" | "quietHours">) {
  await wait();
  session = { id: `s_${Date.now()}`, startedAt: new Date().toISOString(), endedAt: null, status: "active", coughCount: 0, ...opts };
  return session;
}

export async function pushEvents(events: CoughEvent[]) {
  await wait(80);
  if (session) session.coughCount += events.reduce((a, e) => a + e.count, 0);
}

export async function endSession(id: string) {
  await wait();
  if (session && session.id === id) session = { ...session, endedAt: new Date().toISOString(), status: "completed" };
  const ended = session;
  session = null;
  return ended!;
}

export async function lastSummary(): Promise<NightSummary> {
  await wait();
  const rnd = seeded(7);
  const hourly = ["22", "23", "00", "01", "02", "03", "04", "05", "06"].map((h) => ({
    hour: `${h}:00`,
    coughs: Math.round(rnd() * 4 + (h === "02" || h === "03" ? 3 : 0)),
  }));
  const coughs = hourly.reduce((a, b) => a + b.coughs, 0);
  return {
    date: fmtDate(daysAgo(0)),
    coughs,
    coughsPrevAvg: 21,
    sleepHours: 7.2,
    restfulness: 78,
    hourly,
    note: "Most cough events clustered between 2:00 and 3:30. Your 7-night average is similar.",
  };
}

// ---------- dashboard ----------

function buildPoints(range: Range): DailyPoint[] {
  const rnd = seeded(range * 13);
  const points: DailyPoint[] = [];
  for (let i = range - 1; i >= 0; i--) {
    const trend = Math.sin(i / 9) * 4;
    points.push({
      date: fmtDate(daysAgo(i)),
      coughs: Math.max(0, Math.round(18 + trend + rnd() * 10 - 3)),
      weight: Number((72.4 + Math.sin(i / 20) * 0.6 + rnd() * 0.4 - 0.2).toFixed(1)),
      steps: Math.round(5200 + rnd() * 4500 + (i % 7 < 2 ? 1500 : 0)),
      sleepHours: Number((6.6 + rnd() * 1.6).toFixed(1)),
      medsTaken: rnd() > 0.15 ? 2 : 1,
      medsPlanned: 2,
    });
  }
  return points;
}

const medications: Medication[] = [
  { id: "m1", name: "Salbutamol", dose: "100 µg", schedule: "As needed", adherence: 0.92 },
  { id: "m2", name: "Vitamin D3", dose: "1000 IU", schedule: "Every morning", adherence: 0.86 },
];

export async function dashboard(range: Range): Promise<DashboardData> {
  await wait();
  const points = buildPoints(range);
  const avg = (k: keyof DailyPoint) => points.reduce((a, p) => a + (p[k] as number), 0) / points.length;
  const adherence = points.reduce((a, p) => a + p.medsTaken, 0) / points.reduce((a, p) => a + p.medsPlanned, 0);
  const changes: ChangeCard[] = [
    {
      id: "c1",
      metric: "coughs",
      title: "Night coughs slightly higher this week",
      description: "Average of 23 per night versus 19 the week before. Clusters tend to appear after 2:00.",
      direction: "up",
      deltaLabel: "+4 / night",
      since: "vs. previous 7 nights",
    },
    {
      id: "c2",
      metric: "sleep",
      title: "Sleep duration steady",
      description: "You averaged 7.1 hours in bed; no notable change from the previous period.",
      direction: "steady",
      deltaLabel: "±0.1 h",
      since: `over ${range} days`,
    },
    {
      id: "c3",
      metric: "weight",
      title: "Weight within a narrow band",
      description: "Readings stayed between 72.0 and 73.1 kg.",
      direction: "steady",
      deltaLabel: "−0.2 kg",
      since: `over ${range} days`,
    },
    {
      id: "c4",
      metric: "activity",
      title: "More active on weekends",
      description: "Weekend step counts were ~1,500 higher than weekdays.",
      direction: "up",
      deltaLabel: "+1.5k steps",
      since: "weekends",
    },
  ];
  return {
    range,
    points,
    changes,
    medications,
    averages: {
      coughs: Math.round(avg("coughs")),
      weight: Number(avg("weight").toFixed(1)),
      steps: Math.round(avg("steps")),
      sleepHours: Number(avg("sleepHours").toFixed(1)),
      adherence,
    },
  };
}

// ---------- timeline ----------

const timelineAll: TimelineEvent[] = [
  { id: "t1", kind: "session", at: daysAgo(0).toISOString(), title: "Night session completed", detail: "23 cough events · 7.2 h in bed" },
  { id: "t2", kind: "medication", at: daysAgo(0).toISOString(), title: "Vitamin D3 taken", detail: "Morning dose logged" },
  { id: "t3", kind: "weight", at: daysAgo(1).toISOString(), title: "Weight logged", detail: "72.6 kg" },
  { id: "t4", kind: "session", at: daysAgo(1).toISOString(), title: "Night session completed", detail: "19 cough events · 6.9 h in bed" },
  { id: "t5", kind: "record", at: daysAgo(3).toISOString(), title: "Lab results uploaded", detail: "Blood panel — extracted 8 fields" },
  { id: "t6", kind: "note", at: daysAgo(4).toISOString(), title: "Note added", detail: "Slept with window open; pollen was high." },
  { id: "t7", kind: "device", at: daysAgo(6).toISOString(), title: "Device paired", detail: "Phone microphone (on-device only)" },
  { id: "t8", kind: "record", at: daysAgo(9).toISOString(), title: "GP letter uploaded", detail: "Referral letter — 5 fields extracted" },
  { id: "t9", kind: "session", at: daysAgo(12).toISOString(), title: "Night session completed", detail: "27 cough events · 7.5 h in bed" },
  { id: "t10", kind: "medication", at: daysAgo(14).toISOString(), title: "Medication added", detail: "Salbutamol 100 µg, as needed" },
];

export async function timeline(kinds?: TimelineKind[]) {
  await wait();
  return kinds?.length ? timelineAll.filter((e) => kinds.includes(e.kind)) : timelineAll;
}

// ---------- records ----------

let recordsList: HealthRecord[] = [
  { id: "r1", title: "Blood panel — spring check", type: "lab", date: fmtDate(daysAgo(3)), fileName: "lab-results.pdf", mime: "application/pdf", sizeKb: 412, status: "ready" },
  { id: "r2", title: "Referral letter", type: "letter", date: fmtDate(daysAgo(9)), fileName: "gp-letter.pdf", mime: "application/pdf", sizeKb: 188, status: "ready" },
  { id: "r3", title: "Prescription photo", type: "prescription", date: fmtDate(daysAgo(20)), fileName: "IMG_2231.jpg", mime: "image/jpeg", sizeKb: 1520, status: "ready" },
];

const extractedByType: Record<RecordType, RecordDetail["extracted"]> = {
  lab: [
    { label: "Document date", value: "2026-09-14", confidence: 0.98 },
    { label: "Issuer", value: "Central Lab Services", confidence: 0.93 },
    { label: "Haemoglobin", value: "14.1 g/dL", confidence: 0.91 },
    { label: "Ferritin", value: "58 µg/L", confidence: 0.9 },
    { label: "Vitamin D (25-OH)", value: "61 nmol/L", confidence: 0.88 },
    { label: "CRP", value: "2 mg/L", confidence: 0.9 },
    { label: "Reference ranges", value: "Included in document", confidence: 0.8 },
    { label: "Ordering clinician", value: "Dr. J. de Vries", confidence: 0.86 },
  ],
  letter: [
    { label: "Document date", value: "2026-09-08", confidence: 0.97 },
    { label: "From", value: "Huisartsenpraktijk Noord", confidence: 0.92 },
    { label: "To", value: "Pulmonology outpatient clinic", confidence: 0.9 },
    { label: "Subject", value: "Referral", confidence: 0.85 },
    { label: "Mentioned medication", value: "Salbutamol", confidence: 0.83 },
  ],
  prescription: [
    { label: "Medication", value: "Salbutamol 100 µg", confidence: 0.9 },
    { label: "Instructions", value: "As needed, max 8 puffs/day", confidence: 0.82 },
    { label: "Prescriber", value: "Dr. J. de Vries", confidence: 0.87 },
  ],
  imaging: [{ label: "Document date", value: "—", confidence: 0.5 }],
  other: [{ label: "Document date", value: "—", confidence: 0.5 }],
};

export async function records() {
  await wait();
  return recordsList;
}

export async function record(id: string): Promise<RecordDetail> {
  await wait();
  const r = recordsList.find((x) => x.id === id);
  if (!r) throw new Error("Record not found");
  return { ...r, extracted: extractedByType[r.type], pages: r.mime === "application/pdf" ? 2 : 1 };
}

export async function uploadRecord(file: File, type: RecordType) {
  await wait(700);
  const rec: HealthRecord = {
    id: `r_${Date.now()}`,
    title: file.name.replace(/\.[^.]+$/, "").replace(/[-_]/g, " "),
    type,
    date: fmtDate(new Date()),
    fileName: file.name,
    mime: file.type || "application/octet-stream",
    sizeKb: Math.max(1, Math.round(file.size / 1024)),
    status: "ready",
  };
  recordsList = [rec, ...recordsList];
  return rec;
}

export async function removeRecord(id: string) {
  await wait();
  recordsList = recordsList.filter((r) => r.id !== id);
}

// ---------- account ----------

export async function updateProfile(patch: Partial<Pick<User, "name" | "locale">>) {
  await wait();
  user = { ...user, ...patch };
  return user;
}

export async function setTwoFactor(enabled: boolean) {
  await wait();
  user = { ...user, twoFactorEnabled: enabled };
  return user;
}

let loginSessionsList: ActiveLoginSession[] = [
  { id: "ls1", device: "iPhone 15 · Safari", location: "Amsterdam, NL", lastActive: new Date().toISOString(), current: true },
  { id: "ls2", device: "MacBook Pro · Chrome", location: "Amsterdam, NL", lastActive: daysAgo(1).toISOString(), current: false },
  { id: "ls3", device: "iPad · Safari", location: "Utrecht, NL", lastActive: daysAgo(6).toISOString(), current: false },
];

export async function loginSessions() {
  await wait();
  return loginSessionsList;
}

export async function revokeSession(id: string) {
  await wait();
  loginSessionsList = loginSessionsList.filter((s) => s.id !== id);
}

let prefs: NotificationPrefs = {
  morningSummary: true,
  sessionReminder: true,
  medicationReminder: false,
  weeklyTrends: true,
  productUpdates: false,
};

export async function notifications() {
  await wait(150);
  return prefs;
}

export async function updateNotifications(next: NotificationPrefs) {
  await wait();
  prefs = next;
  return prefs;
}

export async function devices(): Promise<Device[]> {
  await wait();
  return [
    { id: "d1", name: "This phone", kind: "On-device cough detection", status: "connected" },
    { id: "d2", name: "Smart scale", kind: "Weight", status: "available" },
    { id: "d3", name: "Activity tracker", kind: "Steps & sleep", status: "available" },
  ];
}

export async function exportData() {
  await wait(900);
  const blob = new Blob([JSON.stringify({ user, consent, exportedAt: new Date().toISOString() }, null, 2)], {
    type: "application/json",
  });
  return { url: URL.createObjectURL(blob) };
}

export async function deleteAccount() {
  await wait(600);
  setTokens(null);
  if (typeof window !== "undefined") window.localStorage.removeItem(CONSENT_KEY);
}

// ---------- support ----------

const MEDICAL = /\b(diagnos|symptom|disease|infection|asthma|copd|cancer|pneumonia|covid|fever|pain|treat|dose|dosage|should i take|is it serious|bronchitis|blood|medicine advice|what do i have)\b/i;

export async function supportChat(messages: SupportMessage[]) {
  await wait(600);
  const last = messages.filter((m) => m.role === "user").at(-1)?.content ?? "";
  if (MEDICAL.test(last)) {
    return {
      reply:
        "I can't give medical advice — Haman Health is a wellness companion, not a diagnostic tool. If you're worried about symptoms, please contact your GP or local health service. I'm happy to help with using the app, though.",
    };
  }
  const l = last.toLowerCase();
  if (l.includes("session") || l.includes("night"))
    return {
      reply:
        "To start a night session, open Night session from the menu, choose a sensitivity and quiet hours, then tap Start. Detection runs on your device; only cough events (time and count) are sent — never audio. End the session in the morning to see your summary.",
    };
  if (l.includes("record") || l.includes("upload") || l.includes("pdf"))
    return {
      reply:
        "Go to Records and tap Upload. PDFs and images are accepted. After processing, the detail view shows the extracted information (dates, values, issuer). It's a transcription of the document, not an interpretation.",
    };
  if (l.includes("delete") || l.includes("export") || l.includes("privacy") || l.includes("consent"))
    return {
      reply:
        "Privacy options live in Account → Privacy. You can change each consent, export your data as a file, or delete your account permanently.",
    };
  if (l.includes("2fa") || l.includes("password") || l.includes("security"))
    return {
      reply: "Under Account → Security you can change your password, turn two-factor authentication on or off, and sign out other devices.",
    };
  if (l.includes("language") || l.includes("dutch") || l.includes("nederlands"))
    return { reply: "You can switch between English and Nederlands under Account → Language." };
  return {
    reply:
      "I can help with sessions, the dashboard and trends, records, notifications, security and privacy settings. What would you like to do in the app?",
  };
}
