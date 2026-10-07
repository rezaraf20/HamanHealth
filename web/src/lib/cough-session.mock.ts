/**
 * Web mock of the cough session bridge.
 *
 * Simulates random cough detections every few seconds. It never touches the
 * microphone and never records or uploads audio.
 */
import type { CoughEvent, CoughSessionBridge, Sensitivity, SessionStatus, SessionSummary } from "./cough-session";

const STORE_KEY = "haman.coughSessions";

type StoredSession = SessionSummary;

function loadStore(): StoredSession[] {
  if (typeof window === "undefined") return [];
  try {
    return JSON.parse(window.localStorage.getItem(STORE_KEY) ?? "[]") as StoredSession[];
  } catch {
    return [];
  }
}

function saveStore(sessions: StoredSession[]) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(STORE_KEY, JSON.stringify(sessions.slice(-200)));
}

function hourKey(iso: string) {
  return `${iso.slice(0, 13)}:00`;
}

function summarize(sessionId: string, startedAt: string, endedAt: string, events: CoughEvent[]): SessionSummary {
  const buckets = new Map<string, number>();
  let total = 0;
  for (const e of events) {
    total += e.count;
    buckets.set(hourKey(e.timestamp), (buckets.get(hourKey(e.timestamp)) ?? 0) + e.count);
  }
  return {
    sessionId,
    startedAt,
    endedAt,
    totalCoughs: total,
    hourly: [...buckets.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([hour, count]) => ({ hour, count })),
  };
}

export function createMockCoughSession(): CoughSessionBridge {
  let status: SessionStatus & { sensitivity?: Sensitivity } = { state: "idle", eventCount: 0 };
  let events: CoughEvent[] = [];
  let timer: ReturnType<typeof setInterval> | undefined;
  const listeners = new Set<(e: CoughEvent) => void>();

  function stopTimer() {
    if (timer) clearInterval(timer);
    timer = undefined;
  }

  function emit(e: CoughEvent) {
    events.push(e);
    status = { ...status, eventCount: status.eventCount + e.count };
    listeners.forEach((cb) => cb(e));
  }

  function tick() {
    if (status.state !== "running" || !status.sessionId) return;
    if (status.autoStopAt && Date.now() >= new Date(status.autoStopAt).getTime()) return;
    // Roughly 45% of ticks produce a detection.
    const rate = status.sensitivity === "high" ? 0.6 : status.sensitivity === "low" ? 0.3 : 0.45;
    if (Math.random() > rate) return;
    emit({
      sessionId: status.sessionId,
      timestamp: new Date().toISOString(),
      count: 1,
      confidence: Math.round((0.62 + Math.random() * 0.36) * 100) / 100,
    });
  }

  return {
    async isAvailable() {
      return true;
    },
    async requestPermissions() {
      // No microphone is used in the web version.
      return "granted";
    },
    async start(opts) {
      stopTimer();
      const sessionId = `web-${Date.now().toString(36)}`;
      events = [];
      status = {
        state: "running",
        sessionId,
        startedAt: new Date().toISOString(),
        ...(opts.autoStopAt ? { autoStopAt: opts.autoStopAt } : {}),
        sensitivity: opts.sensitivity ?? "medium",
        eventCount: 0,
      };
      timer = setInterval(tick, 4000);
      return { sessionId };
    },
    async stop() {
      const sessionId = status.sessionId ?? `web-${Date.now().toString(36)}`;
      const startedAt = status.startedAt ?? new Date().toISOString();
      status = { ...status, state: "stopping" };
      stopTimer();
      const summary = summarize(sessionId, startedAt, new Date().toISOString(), events);
      saveStore([...loadStore(), summary]);
      events = [];
      status = { state: "idle", eventCount: 0 };
      return summary;
    },
    async getStatus() {
      const { sensitivity: _s, ...publicStatus } = status;
      return publicStatus;
    },
    onCoughEvent(cb) {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    async listSessions(from, to) {
      const a = new Date(from).getTime();
      const b = new Date(to).getTime();
      return loadStore().filter((s) => {
        const t = new Date(s.startedAt).getTime();
        return t >= a && t <= b;
      });
    },
  };
}
