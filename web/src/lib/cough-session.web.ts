/**
 * Web implementation of CoughSessionBridge.
 *
 * Unlike the mock, this actually persists data to the backend via the REST API.
 * It is used whenever the app runs in a browser (non-native environment).
 *
 * Detection is still simulated on web (no microphone access); only the
 * persistence layer is real. A native Capacitor build will replace this
 * with real on-device ML inference.
 *
 * Privacy invariant: no microphone access, raw audio is never recorded or
 * uploaded. Only cough event timestamps and counts leave the device.
 */
import type { CoughEvent, CoughSessionBridge, Sensitivity, SessionStatus, SessionSummary } from "./cough-session";
import { api } from "./api";

function hourKey(iso: string) {
  return `${iso.slice(0, 13)}:00`;
}

export function createWebCoughSession(): CoughSessionBridge {
  let status: SessionStatus & { sensitivity?: Sensitivity } = { state: "idle", eventCount: 0 };
  // backend session id (numeric string from the API)
  let backendSessionId: string | null = null;
  let events: CoughEvent[] = [];
  let pendingEvents: CoughEvent[] = [];
  let flushTimer: ReturnType<typeof setInterval> | undefined;
  let detectionTimer: ReturnType<typeof setInterval> | undefined;
  const listeners = new Set<(e: CoughEvent) => void>();

  function stopTimers() {
    if (flushTimer) clearInterval(flushTimer);
    if (detectionTimer) clearInterval(detectionTimer);
    flushTimer = undefined;
    detectionTimer = undefined;
  }

  function emit(e: CoughEvent) {
    events.push(e);
    pendingEvents.push(e);
    status = { ...status, eventCount: status.eventCount + e.count };
    listeners.forEach((cb) => cb(e));
  }

  /** Flush pending events to the backend. Fire-and-forget; errors are swallowed
   *  so a transient network hiccup doesn't crash the session UI. */
  async function flush() {
    if (!backendSessionId || pendingEvents.length === 0) return;
    const batch = pendingEvents.splice(0);
    try {
      await api.sessions.pushEvents(
        batch.map((e) => ({ session_id: backendSessionId!, timestamp: e.timestamp, count: e.count })),
      );
    } catch {
      // Put events back so the next flush retries them
      pendingEvents.unshift(...batch);
    }
  }

  /** Simulated on-device detection tick (web-only). */
  function tick() {
    if (status.state !== "running" || !status.sessionId) return;
    if (status.autoStopAt && Date.now() >= new Date(status.autoStopAt).getTime()) return;
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
      return "granted";
    },

    async start(opts) {
      stopTimers();

      // Create session on backend
      const session = await api.sessions.start({
        sensitivity: opts.sensitivity ?? "medium",
        quietHours: { from: "23:00", to: "07:00" },
      });

      backendSessionId = session.id;
      events = [];
      pendingEvents = [];
      status = {
        state: "running",
        sessionId: session.id,
        startedAt: session.startedAt,
        ...(opts.autoStopAt ? { autoStopAt: opts.autoStopAt } : {}),
        sensitivity: opts.sensitivity ?? "medium",
        eventCount: session.coughCount ?? 0,
      };

      // Flush events to backend every 30 s
      flushTimer = setInterval(() => { void flush(); }, 30_000);
      // Simulate detections every 4 s
      detectionTimer = setInterval(tick, 4000);

      return { sessionId: session.id };
    },

    async stop() {
      stopTimers();
      status = { ...status, state: "stopping" };

      // Flush any remaining events before ending
      await flush();

      const sessionId = backendSessionId ?? status.sessionId ?? `web-${Date.now().toString(36)}`;
      const startedAt = status.startedAt ?? new Date().toISOString();
      const endedAt = new Date().toISOString();

      // End session on backend
      if (backendSessionId) {
        try {
          await api.sessions.end(backendSessionId);
        } catch {
          // Best-effort; session data is already saved
        }
      }

      // Build summary from local events
      const buckets = new Map<string, number>();
      let total = 0;
      for (const e of events) {
        total += e.count;
        buckets.set(hourKey(e.timestamp), (buckets.get(hourKey(e.timestamp)) ?? 0) + e.count);
      }
      const summary: SessionSummary = {
        sessionId,
        startedAt,
        endedAt,
        totalCoughs: total,
        hourly: [...buckets.entries()]
          .sort(([a], [b]) => a.localeCompare(b))
          .map(([hour, count]) => ({ hour, count })),
      };

      events = [];
      pendingEvents = [];
      backendSessionId = null;
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

    async listSessions() {
      // Not used in the web UI currently
      return [];
    },
  };
}
