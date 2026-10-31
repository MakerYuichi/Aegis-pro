export type ChainLink = {
  file: string;
  line: number;
  symbol: string;
  reason: string;
};

export type PlaybackState = 'idle' | 'playing' | 'awaiting-approval' | 'applying' | 'verified' | 'rejected' | 'paused';

export type V2Event =
  | { kind: "investigation.started"; symbol: string; file: string; line: number }
  | { kind: "file.opened"; file: string; line: number }
  | { kind: "hypothesis.formed"; text: string; line: number }
  | { kind: "symbol.located"; symbol: string; file: string; line: number }
  | { kind: "chain.resolved"; chain: ChainLink[] }
  | { kind: "probe.running"; flags: string[] }
  | { kind: "probe.reproduced"; error: string; line: number }
  | { kind: "bug.confirmed"; fix_location: string; failure_mode: string; line: number }
  | { kind: "fix.proposed"; diff: string }
  | { kind: "fix.verified"; passed: boolean; output: string }
  | { kind: "investigation.complete"; result: "verified" | "rejected" | "unverified" };

/** Per-event-kind auto-advance durations in milliseconds. */
export const EVENT_DURATIONS: Partial<Record<V2Event['kind'], number>> = {
  'investigation.started': 800,
  'file.opened': 800,
  'hypothesis.formed': 1200,
  'symbol.located': 800,
  'chain.resolved': 1000,
  'probe.running': 2500,
  'probe.reproduced': 2500,
  'bug.confirmed': 1200,
  'fix.proposed': 1500,
  'fix.verified': 3000,
  'investigation.complete': 1500,
};

export const DEFAULT_EVENT_DURATION = 1200;
