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
  | { kind: "hypothesis.formed"; text: string }
  | { kind: "symbol.located"; symbol: string; file: string; line: number }
  | { kind: "chain.resolved"; chain: ChainLink[] }
  | { kind: "probe.running"; flags: string[] }
  | { kind: "probe.reproduced"; error: string }
  | { kind: "bug.confirmed"; fix_location: string; failure_mode: string }
  | { kind: "fix.proposed"; diff: string }
  | { kind: "fix.verified"; passed: boolean; output: string }
  | { kind: "investigation.complete"; result: "verified" | "rejected" | "unverified" };
