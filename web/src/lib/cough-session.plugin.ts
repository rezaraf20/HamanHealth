/**
 * The contract between this web app and the native Android layer.
 *
 * In the Android app this web app runs inside a Capacitor WebView. The native side
 * registers a plugin named "CoughSession" that implements exactly this interface; it
 * owns the microphone, the on-device detector and the background upload to the platform.
 * The web side owns the screens and the login.
 *
 * Any change here is a change to both sides. The native task is specified in
 * backend/docs/ANDROID_APP_TASK.md.
 */
import { registerPlugin, type PluginListenerHandle } from "@capacitor/core";

export type NativeSensitivity = "low" | "medium" | "high";

export type NativeSessionStatus = {
  state: "idle" | "running" | "stopping";
  /** The phone's own id for the running session (not the server's). */
  sessionId?: string;
  /** ISO 8601 UTC. */
  startedAt?: string;
  autoStopAt?: string;
  /** Coughs detected so far in the running session. */
  eventCount: number;
};

export type NativeSessionSummary = {
  sessionId: string;
  startedAt: string;
  endedAt: string;
  totalCoughs: number;
  /** Coughs per local clock hour, "YYYY-MM-DDTHH:00", in time order. */
  hourly: { hour: string; count: number }[];
};

export type NativeDetectedEvent = {
  sessionId: string;
  type: "cough" | "sneeze" | "snore";
  /** ISO 8601 UTC, event start. */
  timestamp: string;
  /** Peak model score, 0-1. */
  confidence: number;
};

export type NativeSyncStatus = {
  /** False until setAuth has been called with valid tokens. */
  signedIn: boolean;
  /** Finished nights not yet fully uploaded (night or its clips). */
  pendingNights: number;
  /** ISO 8601 UTC of the last successful upload, if any. */
  lastSyncedAt?: string;
  /** Human-readable reason the last attempt failed; absent when it succeeded. */
  lastError?: string;
};

export interface CoughSessionPlugin {
  /** True when the detector can run on this device (model loaded, microphone present). */
  isAvailable(): Promise<{ available: boolean }>;

  /** Asks for the microphone (and, on Android 13+, notification) permission if needed. */
  requestPermissions(): Promise<{ microphone: "granted" | "denied" }>;

  /** Starts the foreground monitoring service. Rejects if a session is already running. */
  start(options: { sensitivity: NativeSensitivity; autoStopAt?: string }): Promise<{ sessionId: string }>;

  /** Stops the running session, finishes writing it, and queues its upload. */
  stop(): Promise<NativeSessionSummary>;

  getStatus(): Promise<NativeSessionStatus>;

  /** Finished sessions that started within [from, to), newest first. ISO 8601 UTC. */
  listSessions(options: { from: string; to: string }): Promise<{ sessions: NativeSessionSummary[] }>;

  /**
   * Hands the native layer the login it uploads with. Called on app start, after every
   * sign-in and after every token refresh. baseUrl includes the /api prefix,
   * e.g. "https://api.hamanhealth.com/api". Queues upload of everything pending.
   */
  setAuth(options: { baseUrl: string; access: string; refresh: string }): Promise<void>;

  /** Sign-out: forget the tokens and stop uploading. Local nights are kept. */
  clearAuth(): Promise<void>;

  /** Tries to upload pending nights now; resolves when the attempt has finished. */
  syncNow(): Promise<NativeSyncStatus>;

  getSyncStatus(): Promise<NativeSyncStatus>;

  /** Fired for each cough, sneeze or snore while a session is running. */
  addListener(eventName: "detectedEvent", listener: (event: NativeDetectedEvent) => void): Promise<PluginListenerHandle>;

  /** Fired whenever an upload attempt finishes or the pending count changes. */
  addListener(eventName: "syncStatus", listener: (status: NativeSyncStatus) => void): Promise<PluginListenerHandle>;
}

export const PLUGIN_NAME = "CoughSession";

export const CoughSessionNative = registerPlugin<CoughSessionPlugin>(PLUGIN_NAME);
