/**
 * Haman Health — single typed API client.
 *
 * Every network call in the app goes through this module. It talks to an external
 * FastAPI backend at VITE_API_BASE_URL using JWT (access + refresh) auth.
 * While the backend is not available, USE_MOCKS returns local mock data.
 *
 * Privacy invariant: raw audio is never stored or uploaded. Only cough events
 * (timestamp, count, session_id) are sent.
 */
import * as mocks from "./mocks";

export const API_BASE_URL: string = (import.meta.env['VITE_API_BASE_URL'] as string | undefined) ?? "";
export const USE_MOCKS: boolean = (import.meta.env['VITE_USE_MOCKS'] as string | undefined) !== "false" || !API_BASE_URL;

// ---------- Types ----------

export type Tokens = { access: string; refresh: string };

export type User = {
  id: string;
  name: string;
  email: string;
  locale: "en" | "nl";
  twoFactorEnabled: boolean;
  createdAt: string;
  avatarInitials: string;
};

export type ConsentState = {
  coughTracking: boolean;
  healthTrends: boolean;
  recordsProcessing: boolean;
  productAnalytics: boolean;
  acceptedAt: string | null;
};

export type SessionStatus = "idle" | "active" | "completed";

export type NightSession = {
  id: string;
  startedAt: string;
  endedAt: string | null;
  status: SessionStatus;
  sensitivity: "low" | "medium" | "high";
  quietHours: { from: string; to: string };
  coughCount: number;
};

/** Only this shape ever leaves the device. Never audio. */
export type CoughEvent = { session_id: string; timestamp: string; count: number };

export type NightSummary = {
  date: string;
  coughs: number;
  coughsPrevAvg: number;
  sleepHours: number;
  restfulness: number; // 0..100
  hourly: { hour: string; coughs: number }[];
  note: string;
};

export type Range = 7 | 30 | 90;

export type DailyPoint = {
  date: string;
  coughs: number;
  weight: number;
  steps: number;
  sleepHours: number;
  medsTaken: number;
  medsPlanned: number;
};

export type ChangeCard = {
  id: string;
  metric: "coughs" | "weight" | "activity" | "sleep" | "medications";
  title: string;
  description: string;
  direction: "up" | "down" | "steady";
  deltaLabel: string;
  since: string;
};

export type Medication = {
  id: string;
  name: string;
  dose: string;
  schedule: string;
  adherence: number; // 0..1
};

export type DashboardData = {
  range: Range;
  points: DailyPoint[];
  changes: ChangeCard[];
  medications: Medication[];
  averages: { coughs: number; weight: number; steps: number; sleepHours: number; adherence: number };
};

export type TimelineKind = "session" | "record" | "medication" | "weight" | "note" | "device";

export type TimelineEvent = {
  id: string;
  kind: TimelineKind;
  at: string;
  title: string;
  detail: string;
};

export type RecordType = "lab" | "letter" | "prescription" | "imaging" | "other";

export type HealthRecord = {
  id: string;
  title: string;
  type: RecordType;
  date: string;
  fileName: string;
  mime: string;
  sizeKb: number;
  status: "processing" | "ready";
};

export type ExtractedField = { label: string; value: string; confidence: number };

export type RecordDetail = HealthRecord & {
  extracted: ExtractedField[];
  pages: number;
};

export type ActiveLoginSession = {
  id: string;
  device: string;
  location: string;
  lastActive: string;
  current: boolean;
};

export type NotificationPrefs = {
  morningSummary: boolean;
  sessionReminder: boolean;
  medicationReminder: boolean;
  weeklyTrends: boolean;
  productUpdates: boolean;
};

export type Device = { id: string; name: string; kind: string; status: "connected" | "available" };

export type SupportMessage = { role: "user" | "assistant"; content: string };

// ---------- Token storage ----------

const TOKEN_KEY = "haman.tokens";

export function getTokens(): Tokens | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(TOKEN_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as Tokens;
  } catch {
    return null;
  }
}

export function setTokens(tokens: Tokens | null) {
  if (typeof window === "undefined") return;
  if (tokens) window.localStorage.setItem(TOKEN_KEY, JSON.stringify(tokens));
  else window.localStorage.removeItem(TOKEN_KEY);
}

// ---------- HTTP core ----------

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

let refreshing: Promise<Tokens | null> | null = null;

async function refreshTokens(): Promise<Tokens | null> {
  const current = getTokens();
  if (!current) return null;
  if (!refreshing) {
    refreshing = fetch(`${API_BASE_URL}/auth/refresh`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ refresh: current.refresh }),
    })
      .then(async (r) => {
        if (!r.ok) throw new ApiError(r.status, "Refresh failed");
        const next = (await r.json()) as Tokens;
        setTokens(next);
        return next;
      })
      .catch(() => {
        setTokens(null);
        return null;
      })
      .finally(() => {
        refreshing = null;
      });
  }
  return refreshing;
}

async function request<T>(path: string, init: RequestInit & { retry?: boolean } = {}): Promise<T> {
  const tokens = getTokens();
  const headers = new Headers(init.headers);
  if (!(init.body instanceof FormData)) headers.set("content-type", "application/json");
  if (tokens) headers.set("authorization", `Bearer ${tokens.access}`);

  const res = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });

  if (res.status === 401 && init.retry !== false) {
    const next = await refreshTokens();
    if (next) return request<T>(path, { ...init, retry: false });
  }
  if (!res.ok) {
    let message = res.statusText;
    try {
      const body = (await res.json()) as { detail?: string; message?: string };
      message = body.detail ?? body.message ?? message;
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, message);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const json = (body: unknown) => JSON.stringify(body);

// ---------- API surface ----------

export const api = {
  auth: {
    login: (email: string, password: string) =>
      USE_MOCKS
        ? mocks.login(email)
        : request<{ requires2fa: boolean; challengeId?: string; tokens?: Tokens }>("/auth/login", {
            method: "POST",
            body: json({ email, password }),
          }),
    verify2fa: (challengeId: string, code: string) =>
      USE_MOCKS
        ? mocks.verify2fa(code)
        : request<Tokens>("/auth/2fa/verify", { method: "POST", body: json({ challengeId, code }) }),
    register: (name: string, email: string, password: string) =>
      USE_MOCKS
        ? mocks.register(name, email)
        : request<Tokens>("/auth/register", { method: "POST", body: json({ name, email, password }) }),
    forgotPassword: (email: string) =>
      USE_MOCKS ? mocks.ok() : request<void>("/auth/forgot-password", { method: "POST", body: json({ email }) }),
    logout: async () => {
      if (!USE_MOCKS) await request<void>("/auth/logout", { method: "POST" }).catch(() => undefined);
      setTokens(null);
      mocks.reset();
    },
    me: () => (USE_MOCKS ? mocks.me() : request<User>("/auth/me")),
  },
  consent: {
    get: () => (USE_MOCKS ? mocks.getConsent() : request<ConsentState>("/consent")),
    update: (state: Partial<ConsentState>) =>
      USE_MOCKS ? mocks.updateConsent(state) : request<ConsentState>("/consent", { method: "PUT", body: json(state) }),
  },
  sessions: {
    current: () => (USE_MOCKS ? mocks.currentSession() : request<NightSession | null>("/sessions/current")),
    start: (opts: Pick<NightSession, "sensitivity" | "quietHours">) =>
      USE_MOCKS ? mocks.startSession(opts) : request<NightSession>("/sessions", { method: "POST", body: json(opts) }),
    /** Sends cough events only — never audio. */
    pushEvents: (events: CoughEvent[]) =>
      USE_MOCKS
        ? mocks.pushEvents(events)
        : request<void>("/sessions/events", { method: "POST", body: json({ events }) }),
    end: (id: string) =>
      USE_MOCKS ? mocks.endSession(id) : request<NightSession>(`/sessions/${id}/end`, { method: "POST" }),
    lastSummary: () => (USE_MOCKS ? mocks.lastSummary() : request<NightSummary>("/sessions/last/summary")),
  },
  dashboard: {
    get: (range: Range) => (USE_MOCKS ? mocks.dashboard(range) : request<DashboardData>(`/dashboard?range=${range}`)),
  },
  timeline: {
    list: (kinds?: TimelineKind[]) =>
      USE_MOCKS
        ? mocks.timeline(kinds)
        : request<TimelineEvent[]>(`/timeline${kinds?.length ? `?kinds=${kinds.join(",")}` : ""}`),
  },
  records: {
    list: () => (USE_MOCKS ? mocks.records() : request<HealthRecord[]>("/records")),
    get: (id: string) => (USE_MOCKS ? mocks.record(id) : request<RecordDetail>(`/records/${id}`)),
    upload: (file: File, type: RecordType) => {
      if (USE_MOCKS) return mocks.uploadRecord(file, type);
      const form = new FormData();
      form.append("file", file);
      form.append("type", type);
      return request<HealthRecord>("/records", { method: "POST", body: form });
    },
    remove: (id: string) => (USE_MOCKS ? mocks.removeRecord(id) : request<void>(`/records/${id}`, { method: "DELETE" })),
  },
  account: {
    updateProfile: (patch: Partial<Pick<User, "name" | "locale">>) =>
      USE_MOCKS ? mocks.updateProfile(patch) : request<User>("/account/profile", { method: "PATCH", body: json(patch) }),
    changePassword: (current: string, next: string) =>
      USE_MOCKS
        ? mocks.ok()
        : request<void>("/account/password", { method: "POST", body: json({ current, next }) }),
    setTwoFactor: (enabled: boolean) =>
      USE_MOCKS ? mocks.setTwoFactor(enabled) : request<User>("/account/2fa", { method: "POST", body: json({ enabled }) }),
    loginSessions: () => (USE_MOCKS ? mocks.loginSessions() : request<ActiveLoginSession[]>("/account/sessions")),
    revokeSession: (id: string) =>
      USE_MOCKS ? mocks.revokeSession(id) : request<void>(`/account/sessions/${id}`, { method: "DELETE" }),
    notifications: () => (USE_MOCKS ? mocks.notifications() : request<NotificationPrefs>("/account/notifications")),
    updateNotifications: (prefs: NotificationPrefs) =>
      USE_MOCKS
        ? mocks.updateNotifications(prefs)
        : request<NotificationPrefs>("/account/notifications", { method: "PUT", body: json(prefs) }),
    devices: () => (USE_MOCKS ? mocks.devices() : request<Device[]>("/account/devices")),
    exportData: () => (USE_MOCKS ? mocks.exportData() : request<{ url: string }>("/account/export", { method: "POST" })),
    deleteAccount: async () => {
      if (USE_MOCKS) return mocks.deleteAccount();
      await request<void>("/account", { method: "DELETE" });
      setTokens(null);
    },
  },
  support: {
    chat: (messages: SupportMessage[]) =>
      USE_MOCKS
        ? mocks.supportChat(messages)
        : request<{ reply: string }>("/support/chat", { method: "POST", body: json({ messages }) }),
  },
};

export type Api = typeof api;
