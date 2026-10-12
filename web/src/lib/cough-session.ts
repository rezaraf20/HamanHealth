/**
 * Cough session bridge — the ONLY interface night-session screens may use.
 *
 * Detection runs in the Haman Health phone app, not in the browser: the web app has no
 * microphone access, so here the bridge reports itself unavailable and night sessions
 * cannot be started. A native (Capacitor) implementation can be registered later
 * without touching any UI code. Demo mode (USE_MOCKS) keeps its simulated session.
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

import { createMockCoughSession } from "./cough-session.mock";
import { USE_MOCKS } from "./api";

type BridgeFactory = () => CoughSessionBridge;

const nativeFactories: Record<string, BridgeFactory | undefined> = {
  // e.g. capacitor: () => createCapacitorCoughSession(),
};

function isNative(): boolean {
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

/** Single shared instance chosen by the factory. */
export const coughSession: CoughSessionBridge = createCoughSession();
