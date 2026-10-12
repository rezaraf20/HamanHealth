/**
 * Cough session bridge for the Android app: every call goes to the native "CoughSession"
 * plugin (see cough-session.plugin.ts), which runs the real detector.
 */
import { API_BASE_URL, onTokensChanged } from "./api";
import type { CoughEvent, CoughSessionBridge } from "./cough-session";
import { CoughSessionNative, type NativeSyncStatus } from "./cough-session.plugin";

export function createCapacitorCoughSession(): CoughSessionBridge {
  // The native layer uploads in the background, also when this web view is closed, so
  // it needs its own copy of the login. Keep it in step with ours.
  onTokensChanged((tokens) => {
    const done = tokens
      ? CoughSessionNative.setAuth({ baseUrl: API_BASE_URL, access: tokens.access, refresh: tokens.refresh })
      : CoughSessionNative.clearAuth();
    done.catch((err: unknown) => console.error("CoughSession auth sync failed", err));
  });

  return {
    isAvailable: async () => (await CoughSessionNative.isAvailable()).available,

    requestPermissions: async () => (await CoughSessionNative.requestPermissions()).microphone,

    start: (opts) =>
      CoughSessionNative.start({
        sensitivity: opts.sensitivity ?? "medium",
        ...(opts.autoStopAt ? { autoStopAt: opts.autoStopAt } : {}),
      }),

    async stop() {
      const summary = await CoughSessionNative.stop();
      // Best effort: the native layer retries by itself if this attempt fails.
      await CoughSessionNative.syncNow().catch(() => undefined);
      return summary;
    },

    getStatus: () => CoughSessionNative.getStatus(),

    onCoughEvent(cb: (e: CoughEvent) => void) {
      const handle = CoughSessionNative.addListener("detectedEvent", (e) => {
        if (e.type === "cough") cb({ sessionId: e.sessionId, timestamp: e.timestamp, count: 1, confidence: e.confidence });
      });
      return () => void handle.then((h) => h.remove());
    },

    listSessions: async (from, to) => (await CoughSessionNative.listSessions({ from, to })).sessions,
  };
}

/** Calls back whenever the native layer finishes an upload attempt. Returns unsubscribe. */
export function onNativeSyncStatus(cb: (status: NativeSyncStatus) => void): () => void {
  const handle = CoughSessionNative.addListener("syncStatus", cb);
  return () => void handle.then((h) => h.remove());
}
