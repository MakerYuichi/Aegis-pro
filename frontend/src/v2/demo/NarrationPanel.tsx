import { useEffect, useRef, useState } from 'react';
import type { V2Event, PlaybackState } from '../types';

interface NarrationPanelProps {
  events: V2Event[];
  currentIndex: number;
  playbackState: PlaybackState;
}

function getNarration(event: V2Event): string | null {
  switch (event.kind) {
    case 'investigation.started':
      return "There's a suspicious finding at status_codes.py:116. Let me open it.";
    case 'file.opened':
      return 'Reading the surrounding code...';
    case 'hypothesis.formed':
      return 'Hmm. This is a __doc__ concatenation. Under -OO, Python strips module docstrings — so __doc__ would be None here. That would crash.';
    case 'symbol.located':
      return 'Confirming: __doc__ at line 116.';
    case 'chain.resolved':
      return 'The chain is single-file. The crash site is the cause.';
    case 'probe.running':
      return 'Let me prove it. Running the file under -OO...';
    case 'probe.reproduced':
      return 'Reproduced. TypeError: NoneType + str.';
    case 'bug.confirmed':
      return "That's a real bug. Generating a fix...";
    case 'fix.proposed':
      return "Here's the fix: guard the concatenation with (__doc__ or ''). Want me to apply it?";
    case 'fix.verified':
      return 'Verified. The probe passes now.';
    case 'investigation.complete':
      return 'Done. Bug found, fixed, verified.';
    default:
      return null;
  }
}

export function NarrationPanel({ events, currentIndex, playbackState }: NarrationPanelProps) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Build lines from events
  const eventLines: string[] = [];
  events.slice(0, currentIndex + 1).forEach((event) => {
    const line = getNarration(event);
    if (line) eventLines.push(line);
  });

  // State-driven extra lines (appended once, deduplicated)
  const [extraLines, setExtraLines] = useState<string[]>([]);

  useEffect(() => {
    if (playbackState === 'awaiting-approval') {
      setExtraLines((prev) => {
        const line = 'Take your time.';
        return prev.includes(line) ? prev : [...prev, line];
      });
    } else if (playbackState === 'applying') {
      setExtraLines((prev) => {
        const line = 'Applying...';
        return prev.includes(line) ? prev : [...prev, line];
      });
    } else if (playbackState === 'rejected') {
      setExtraLines((prev) => {
        const line = 'Dismissed.';
        return prev.includes(line) ? prev : [...prev, line];
      });
    } else if (playbackState === 'idle') {
      setExtraLines([]);
    }
  }, [playbackState]);

  const allLines = [...eventLines, ...extraLines];
  const currentLineIndex = allLines.length - 1;

  useEffect(() => {
    if (bottomRef.current && containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [allLines.length]);

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
      {allLines.length === 0 && (
        <p className="text-slate-600 italic">Press ▶ Play to start the investigation…</p>
      )}
      {allLines.map((line, idx) => {
        const isCurrent = idx === currentLineIndex;
        return (
          <p
            key={`${idx}-${line.slice(0, 20)}`}
            style={{
              opacity: 0,
              animation: 'aegis-narration-in 0.3s ease-out forwards',
              fontWeight: isCurrent ? 700 : 400,
            }}
          >
            <span className="text-slate-600 mr-2 select-none" style={{ opacity: isCurrent ? 1 : 0.6 }}>
              {String(idx + 1).padStart(2, '0')}
            </span>
            <span style={{ opacity: isCurrent ? 1 : 0.6 }}>{line}</span>
          </p>
        );
      })}
      <div ref={bottomRef} />
    </div>
  );
}
