import { useEffect, useRef } from 'react';
import type { V2Event } from '../types';

interface NarrationPanelProps {
  events: V2Event[];
  currentIndex: number;
}

function getNarration(event: V2Event): string | null {
  switch (event.kind) {
    case 'investigation.started':
      return `Opening ${event.file}…`;
    case 'file.opened':
      return `Reading lines around line ${event.line}…`;
    case 'hypothesis.formed':
      return `Checking __doc__ type…`;
    case 'symbol.located':
      return `Found: ${event.symbol} at line ${event.line}`;
    case 'chain.resolved':
      return `Chain resolved: ${event.chain.length} link(s)`;
    case 'probe.running':
      return `Probing under ${event.flags.join(' ')}…`;
    case 'probe.reproduced':
      return `Reproduced: ${event.error}`;
    case 'bug.confirmed':
      return `Bug confirmed: ${event.failure_mode}`;
    case 'fix.proposed':
      return `Generating fix…`;
    case 'fix.verified':
      return event.passed ? `Fix verified.` : `Fix failed.`;
    case 'investigation.complete':
      return `Investigation complete: ${event.result}`;
    default:
      return null;
  }
}

export function NarrationPanel({ events, currentIndex }: NarrationPanelProps) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const visibleEvents = events.slice(0, currentIndex + 1);

  useEffect(() => {
    if (bottomRef.current && containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [currentIndex]);

  return (
    <div
      ref={containerRef}
      className="bg-slate-900 border-t border-slate-800 font-mono text-sm text-slate-300 overflow-y-auto p-3"
      style={{ height: '140px', flexShrink: 0 }}
    >
      <style>{`
        @keyframes aegis-narration-in {
          from { opacity: 0; transform: translateY(4px); }
          to   { opacity: 1; transform: translateY(0); }
        }
      `}</style>
      {visibleEvents.length === 0 && (
        <p className="text-slate-600 italic">Press ▶ Play to start the investigation…</p>
      )}
      {visibleEvents.map((event, idx) => {
        const line = getNarration(event);
        if (!line) return null;
        return (
          <p
            key={idx}
            style={{
              opacity: 0,
              animation: 'aegis-narration-in 0.3s ease-out forwards',
            }}
          >
            <span className="text-slate-600 mr-2 select-none">{String(idx + 1).padStart(2, '0')}</span>
            {line}
          </p>
        );
      })}
      <div ref={bottomRef} />
    </div>
  );
}
