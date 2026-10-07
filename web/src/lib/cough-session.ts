/**
 * Cough session bridge — the ONLY interface night-session screens may use.
 *
 * On the web a mock implementation simulates detections; a native (Capacitor)
 * implementation can be registered later without touching any UI code.
 *
 * Privacy invariant: no microphone access on the web, and raw audio is never
 * recorded or uploaded anywhere. Only cough events leave the device.
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
  return createMockCoughSession();
}

/** Single shared instance chosen by the factory. */
export const coughSession: CoughSessionBridge = createCoughSession();
