import { useEffect, useLayoutEffect, useState, useCallback } from 'react';
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

const MIN_CALLOUT_HEIGHT = 56;
const LINE_HEIGHT = 20;

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
  codeViewRef: RefObject<CodeViewHandle | null>;
  containerRef: RefObject<HTMLDivElement | null>;
  reducedMotion: boolean;
}

export function CalloutLayer({
  events,
  currentIndex,
  codeViewRef,
  containerRef,
  reducedMotion,
}: CalloutLayerProps) {
  const [positions, setPositions] = useState<Map<number, number>>(new Map());

  // Derive visible callout events (only the 4 kinds that have line numbers)
  const visibleCalloutEvents = events
    .slice(0, currentIndex + 1)
    .filter((e): e is CalloutEvent => CALLOUT_KINDS.has(e.kind));

  const recomputePositions = useCallback(() => {
    if (!containerRef.current) return;
    const containerRect = containerRef.current.getBoundingClientRect();
    const firstLineNum = 108; // START_LINE_NUMBER from CodeView

    const rawPositions: { idx: number; topPx: number }[] = visibleCalloutEvents.map(
      (event, idx) => {
        const lineEl = codeViewRef.current?.getLineElement(event.line);
        if (lineEl) {
          const lineRect = lineEl.getBoundingClientRect();
          // Only use measured value if the element is actually rendered
          if (lineRect.height > 0) {
            return {
              idx,
              topPx: lineRect.top - containerRect.top,
            };
          }
        }
        // Fallback: calculate from line number
        return {
          idx,
          topPx: (event.line - firstLineNum) * LINE_HEIGHT,
        };
      },
    );

    // Overlap prevention: sort by topPx, then push down overlapping callouts
    rawPositions.sort((a, b) => a.topPx - b.topPx);
    let prevBottom = -Infinity;
    for (const item of rawPositions) {
      if (item.topPx < prevBottom + 8) {
        item.topPx = prevBottom + 8;
      }
      prevBottom = item.topPx + MIN_CALLOUT_HEIGHT;
    }

    const newPositions = new Map<number, number>();
    for (const item of rawPositions) {
      newPositions.set(item.idx, item.topPx);
    }
    setPositions(newPositions);
  }, [visibleCalloutEvents, codeViewRef, containerRef]);

  // Recompute on layout (runs synchronously before paint)
  useLayoutEffect(() => {
    recomputePositions();
  }, [recomputePositions]);

  // Subscribe to scroll events on the CodeView scroll container
  useEffect(() => {
    const scrollEl = codeViewRef.current?.getScrollContainer();
    if (!scrollEl) return;

    let rafId: number;
    const handler = () => {
      cancelAnimationFrame(rafId);
      rafId = requestAnimationFrame(recomputePositions);
    };
    scrollEl.addEventListener('scroll', handler, { passive: true });
    return () => {
      scrollEl.removeEventListener('scroll', handler);
      cancelAnimationFrame(rafId);
    };
  }, [codeViewRef, recomputePositions]);

  if (visibleCalloutEvents.length === 0) return null;

  return (
    <div className="absolute inset-0 pointer-events-none overflow-hidden">
      {visibleCalloutEvents.map((event, idx) => {
        const topPx = positions.get(idx) ?? (event.line - 108) * LINE_HEIGHT;
        return (
          <CalloutCard
            key={`${event.kind}-${idx}`}
            event={event}
            topPx={topPx}
            reducedMotion={reducedMotion}
          />
        );
      })}
    </div>
  );
}
