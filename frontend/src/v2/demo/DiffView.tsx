import { useEffect, useRef, useState } from 'react';
import type { V2Event, PlaybackState } from '../types';

const REMOVED_LINE = "    __doc__ = (__doc__ + '\\n' + _codes_str)";
const FIXED_LINE   = "    __doc__ = ((__doc__ or '') + '\\n' + _codes_str)";

interface DiffViewProps {
  proposedEvent: Extract<V2Event, { kind: 'fix.proposed' }> | null;
  verifiedEvent: Extract<V2Event, { kind: 'fix.verified' }> | null;
  playbackState: PlaybackState;
  reducedMotion: boolean;
  onApproveFix: () => void;
  onRejectFix: () => void;
}

export function DiffView({
  proposedEvent,
  verifiedEvent,
  playbackState,
  reducedMotion,
  onApproveFix,
  onRejectFix,
}: DiffViewProps) {
  const [revealedChars, setRevealedChars] = useState(0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Char-by-char reveal during applying state
  useEffect(() => {
    if (playbackState !== 'applying') {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
      // eslint-disable-next-line react-hooks/set-state-in-effect
      if (playbackState === 'idle') setRevealedChars(0);
      return;
    }

    if (reducedMotion) {
      setRevealedChars(FIXED_LINE.length);
      return;
    }

    setRevealedChars(0);
    const totalChars = FIXED_LINE.length;
    const intervalMs = 1500 / totalChars;
    let count = 0;

    intervalRef.current = setInterval(() => {
      count += 1;
      setRevealedChars(count);
      if (count >= totalChars) {
        if (intervalRef.current) {
          clearInterval(intervalRef.current);
          intervalRef.current = null;
        }
      }
    }, intervalMs);

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [playbackState, reducedMotion]);

  if (proposedEvent === null) return null;

  const isRejected = playbackState === 'rejected';

  return (
    <div
      role="region"
      aria-label="Proposed fix diff"
      className={[
        'font-mono text-xs rounded-lg border border-aegis-line bg-aegis-surface overflow-hidden',
        'motion-safe:animate-aegis-diff-fadein',
        isRejected ? 'opacity-40' : '',
      ]
        .filter(Boolean)
        .join(' ')}
    >
      {/* Header */}
      <div className="px-3 py-1.5 text-slate-400 border-b border-aegis-line bg-aegis-line/50 flex items-center justify-between">
        <span>Proposed diff · requests/status_codes.py:116</span>
        {isRejected && <span className="text-slate-500 italic">Fix dismissed.</span>}
      </div>

      {/* Applying indicator */}
      {playbackState === 'applying' && (
        <div className="px-3 py-1 text-slate-400 text-sm italic">Applying…</div>
      )}

      {/* Removed line */}
      <div className="flex items-start gap-2 px-3 py-1.5 bg-red-950/60">
        <span className="select-none text-red-500 w-3 flex-shrink-0">−</span>
        <span className="text-red-300 whitespace-pre">{REMOVED_LINE}</span>
      </div>

      {/* Added line */}
      <div className="flex items-start gap-2 px-3 py-1.5 bg-green-950/60">
        <span className="select-none text-green-500 w-3 flex-shrink-0">+</span>
        <span className="text-green-300 whitespace-pre">
          {playbackState === 'applying'
            ? FIXED_LINE.slice(0, revealedChars)
            : FIXED_LINE}
          {playbackState === 'applying' &&
            !reducedMotion &&
            revealedChars < FIXED_LINE.length && (
              <span className="inline-block w-0.5 h-3.5 bg-green-400 animate-pulse ml-0.5 align-middle" />
            )}
        </span>
      </div>

      {/* Awaiting-approval buttons */}
      {playbackState === 'awaiting-approval' && (
        <div className="flex gap-3 px-3 py-2 border-t border-aegis-line bg-aegis-surface">
          <button
            aria-label="Apply fix"
            onClick={onApproveFix}
            className="px-4 py-1.5 bg-aegis-green hover:bg-green-600 text-white font-semibold rounded text-xs transition-colors focus:outline-none focus:ring-2 focus:ring-aegis-amber cursor-pointer"
          >
            Apply fix
          </button>
          <button
            aria-label="Dismiss fix"
            onClick={onRejectFix}
            className="px-4 py-1.5 bg-aegis-surface hover:bg-aegis-line text-slate-300 rounded text-xs border border-aegis-line transition-colors focus:outline-none focus:ring-2 focus:ring-aegis-amber cursor-pointer"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Verified banner */}
      {(playbackState === 'verified' ||
        (verifiedEvent !== null && verifiedEvent.passed === true && playbackState !== 'awaiting-approval' && playbackState !== 'applying')) && (
        <div
          role="status"
          className="px-3 py-2 mt-0 bg-aegis-green/10 border-t border-aegis-green/50 text-aegis-green text-xs font-medium"
        >
          ✓ Probe failed before, passed after. Verified.
        </div>
      )}

      {/* Failure banner */}
      {verifiedEvent !== null && verifiedEvent.passed === false && (
        <div
          role="status"
          className="px-3 py-2 bg-aegis-red/10 border-t border-aegis-red/50 text-aegis-red text-xs font-medium"
        >
          ✗ Probe still failing after fix. Review needed.
        </div>
      )}
    </div>
  );
}
