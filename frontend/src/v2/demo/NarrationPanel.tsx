import { useEffect, useRef, useState } from 'react';
import type React from 'react';
import type { V2Event, PlaybackState } from '../types';

interface NarrationPanelProps {
  events: V2Event[];
  currentIndex: number;
  playbackState: PlaybackState;
}

function getNarration(event: V2Event): React.ReactNode | null {
  switch (event.kind) {
    case 'investigation.started':
      return <>Reading <code className="font-mono text-sm">status_codes.py</code>…</>;
    case 'file.opened':
      return 'Scanning the surrounding context.';
    case 'hypothesis.formed':
      return (
        <>
          Checking whether <code className="font-mono text-sm">__doc__</code> can be None… Under{' '}
          <code className="font-mono text-sm">-OO</code>, Python strips docstrings. That would crash here.
        </>
      );
    case 'symbol.located':
      return (
        <>
          Confirmed: <code className="font-mono text-sm">__doc__</code> at line 116.
        </>
      );
    case 'chain.resolved':
      return 'Single-file finding. The crash site is the cause.';
    case 'probe.running':
      return (
        <>
          Running the file under <code className="font-mono text-sm">python -OO</code> to see if it actually crashes.
        </>
      );
    case 'probe.reproduced':
      return (
        <>
          It crashes.{' '}
          <code className="font-mono text-sm">
            TypeError: unsupported operand type(s) for +: &apos;NoneType&apos; and &apos;str&apos;.
          </code>
        </>
      );
    case 'bug.confirmed':
      return "That's a real bug. Generating a fix.";
    case 'fix.proposed':
      return (
        <>
          Guard the concatenation with{' '}
          <code className="font-mono text-sm">(__doc__ or &apos;&apos;)</code>. Does that fix it?
        </>
      );
    case 'fix.verified':
      return 'Probe passes now. Verified.';
    case 'investigation.complete':
      return 'Done.';
    default:
      return null;
  }
}

export function NarrationPanel({ events, currentIndex, playbackState }: NarrationPanelProps) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Build narration lines from events
  const eventLines: React.ReactNode[] = [];
  events.slice(0, currentIndex + 1).forEach((event) => {
    const line = getNarration(event);
    if (line !== null) eventLines.push(line);
  });

  // State-driven extra lines (appended once, deduplicated by string key)
  const [extraLines, setExtraLines] = useState<{ key: string; node: React.ReactNode }[]>([]);

  useEffect(() => {
    if (playbackState === 'applying') {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setExtraLines((prev) => {
        const key = 'applying';
        return prev.some((x) => x.key === key) ? prev : [...prev, { key, node: 'Applying…' }];
      });
    } else if (playbackState === 'rejected') {
      setExtraLines((prev) => {
        const key = 'rejected';
        return prev.some((x) => x.key === key) ? prev : [...prev, { key, node: 'Fix dismissed.' }];
      });
    } else if (playbackState === 'idle') {
      setExtraLines([]);
    }
  }, [playbackState]);

  const allLines: React.ReactNode[] = [
    ...eventLines,
    ...extraLines.map((x) => x.node),
  ];

  const currentLineIndex = allLines.length - 1;

  useEffect(() => {
    if (bottomRef.current && containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [allLines.length]);

  return (
    <div
      ref={containerRef}
      aria-live="polite"
      aria-label="Investigation narration"
      className="bg-aegis-surface border-t border-aegis-line text-sm text-slate-300 overflow-y-auto p-3"
      style={{ height: '120px', flexShrink: 0 }}
    >
      {allLines.length === 0 && (
        <p className="text-slate-600 italic">Waiting to start…</p>
      )}
      {allLines.map((line, idx) => {
        const isCurrent = idx === currentLineIndex;
        return (
          <p
            key={idx}
            className={[
              isCurrent ? 'font-medium' : 'opacity-60',
              'motion-safe:animate-aegis-narration-in',
            ].join(' ')}
            style={{
              animationFillMode: 'forwards',
              opacity: isCurrent ? undefined : undefined,
            }}
          >
            {line}
          </p>
        );
      })}
      <div ref={bottomRef} />
    </div>
  );
}
