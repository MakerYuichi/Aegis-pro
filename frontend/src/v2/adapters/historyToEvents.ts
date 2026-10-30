// TODO: use this when live streaming is available; for now the demo replays demo-investigation.json.
import type { V2Event } from '../types';

export function historyToEvents(
  investigationHistory: unknown[],
  incident: { file_path: string; line_number: number; symbol?: string }
): V2Event[] {
  const events: V2Event[] = [];
  const symbol = incident.symbol ?? '__doc__';
  events.push({ kind: 'investigation.started', symbol, file: incident.file_path, line: incident.line_number });
  for (const entry of investigationHistory) {
    const e = entry as Record<string, unknown>;
    if (e['type'] === 'read_file') {
      events.push({ kind: 'file.opened', file: String(e['file'] ?? incident.file_path), line: incident.line_number });
    } else if (e['type'] === 'probe') {
      const flags = Array.isArray(e['flags']) ? e['flags'].map(String) : [];
      events.push({ kind: 'probe.running', flags });
      if (e['reproduced']) {
        events.push({ kind: 'probe.reproduced', error: String(e['error'] ?? 'Unknown error') });
      }
    } else if (e['status'] === 'confirmed') {
      events.push({ kind: 'bug.confirmed', fix_location: incident.file_path, failure_mode: String(e['failure_mode'] ?? '') });
      events.push({ kind: 'investigation.complete', result: 'verified' });
    }
  }
  return events;
}
