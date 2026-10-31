// CalloutLayer — renders visible callout cards in a stacked panel.
// Does NOT use absolute positioning over the code — cards stack vertically
// in a sidebar column next to the CodeView, so they never overlap code text.

import { useMemo } from 'react';
import type { RefObject } from 'react';
import type { V2Event } from '../types';
import type { CodeViewHandle } from './CodeView';
import { CalloutCard } from './CalloutCard';

const CALLOUT_KINDS = new Set<V2Event['kind']>([
  'hypothesis.formed',
  'symbol.located',
  'probe.reproduced',
  'bug.confirmed',
]);

type CalloutEvent = Extract<
  V2Event,
  | { kind: 'hypothesis.formed' }
  | { kind: 'symbol.located' }
  | { kind: 'probe.reproduced' }
  | { kind: 'bug.confirmed' }
>;

interface CalloutLayerProps {
  events: V2Event[];
  currentIndex: number;
  // kept for API compat; not used in this layout approach
  codeViewRef: RefObject<CodeViewHandle | null>;
  containerRef: RefObject<HTMLDivElement | null>;
  reducedMotion: boolean;
}

export function CalloutLayer({
  events,
  currentIndex,
  reducedMotion,
}: CalloutLayerProps) {
  const visibleCalloutEvents = useMemo(
    () =>
      events
        .slice(0, currentIndex + 1)
        .filter((e): e is CalloutEvent => CALLOUT_KINDS.has(e.kind)),
    [events, currentIndex],
  );

  if (visibleCalloutEvents.length === 0) {
    return (
      <div className="h-full flex items-start justify-center pt-8">
        <p className="text-xs text-slate-600 italic">Analysis in progress…</p>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto p-3 space-y-2">
      {visibleCalloutEvents.map((event, idx) => (
        <CalloutCard
          key={`${event.kind}-${idx}`}
          event={event}
          topPx={0}          // not used in the new stacked layout
          reducedMotion={reducedMotion}
        />
      ))}
    </div>
  );
}
