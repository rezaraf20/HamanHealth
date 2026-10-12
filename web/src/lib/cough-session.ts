/**
 * Cough session bridge — the ONLY interface night-session screens may use.
 *
 * Inside the Android app (a Capacitor web view) the bridge talks to the native detector.
 * In a plain browser there is no detector and no microphone access, so the bridge
 * reports itself unavailable and night sessions cannot be started. Demo mode
 * (USE_MOCKS) keeps its simulated session.
 */

export type CoughEvent = {
  sessionId: string;
  timestamp: string;
  count: number;
  confidence: number;
};

export type SessionStatus = {
  state: "idle" | "running" | "stopping";
  sessionId?: string;
  startedAt?: string;
  autoStopAt?: string;
  eventCount: number;
};

export type SessionSummary = {
  sessionId: string;
  startedAt: string;
  endedAt: string;
  totalCoughs: number;
  hourly: { hour: string; count: number }[];
};

export type Sensitivity = "low" | "medium" | "high";

export type StartOptions = {
  autoStopAt?: string;
  /** Maps to the detection threshold in the native inference module. */
  sensitivity?: Sensitivity;
};

export interface CoughSessionBridge {
  isAvailable(): Promise<boolean>;
  requestPermissions(): Promise<"granted" | "denied">;
  start(opts: StartOptions): Promise<{ sessionId: string }>;
  stop(): Promise<SessionSummary>;
  getStatus(): Promise<SessionStatus>;
  onCoughEvent(cb: (e: CoughEvent) => void): () => void;
  listSessions(from: string, to: string): Promise<SessionSummary[]>;
}

import { createCapacitorCoughSession } from "./cough-session.capacitor";
import { createMockCoughSession } from "./cough-session.mock";
import { USE_MOCKS } from "./api";

type BridgeFactory = () => CoughSessionBridge;

const nativeFactories: Record<string, BridgeFactory | undefined> = {
  capacitor: () => createCapacitorCoughSession(),
};

export function isNative(): boolean {
  if (typeof window === "undefined") return false;
  const cap = (window as unknown as { Capacitor?: { isNativePlatform?: () => boolean } }).Capacitor;
  return Boolean(cap?.isNativePlatform?.());
}

function createCoughSession(): CoughSessionBridge {
  if (isNative()) {
    const factory = nativeFactories['capacitor'];
    if (factory) return factory();
  }
  // Connected to the real backend: never invent detections. Nights come from the phone app.
  if (!USE_MOCKS) return createUnavailableCoughSession();
  return createMockCoughSession();
}

function createUnavailableCoughSession(): CoughSessionBridge {
  const unavailable = () => Promise.reject(new Error("Night sessions run in the Haman Health app on your phone"));
  return {
    isAvailable: async () => false,
    requestPermissions: async () => "denied",
    start: unavailable,
    stop: unavailable,
    getStatus: async () => ({ state: "idle", eventCount: 0 }),
    onCoughEvent: () => () => {},
    listSessions: async () => [],
  };
}

let chosen: CoughSessionBridge | null = null;

function bridge(): CoughSessionBridge {
  if (chosen) return chosen;
  const b = createCoughSession();
  // Inside the Android app the native bridge can appear a moment after this module
  // loads. Until it has, keep checking rather than settling on "unavailable".
  if (USE_MOCKS || isNative()) chosen = b;
  return b;
}

/** Single shared instance; the implementation is picked on first use. */
export const coughSession: CoughSessionBridge = {
  isAvailable: () => bridge().isAvailable(),
  requestPermissions: () => bridge().requestPermissions(),
  start: (opts) => bridge().start(opts),
  stop: () => bridge().stop(),
  getStatus: () => bridge().getStatus(),
  onCoughEvent: (cb) => bridge().onCoughEvent(cb),
  listSessions: (from, to) => bridge().listSessions(from, to),
};

/**
 * Call at app start. Inside the Android app this connects the native layer right away,
 * so it gets the login and can upload even if the user never opens the session screen.
 * In a browser it does nothing.
 */
export function connectNativeLayer(): void {
  if (isNative()) bridge();
}
