// DiffView — shown below the editor when fix.proposed fires.
// The actual diff animation happens inside CodeView (line 116).
// This component shows the Apply/Dismiss prompt and the verified banner.

import type { V2Event, PlaybackState } from '../types';

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
  onApproveFix,
  onRejectFix,
}: DiffViewProps) {
  if (proposedEvent === null) return null;

  const isRejected = playbackState === 'rejected';
  const isApplying = playbackState === 'applying';
  const isVerified = playbackState === 'verified' ||
    (verifiedEvent !== null && verifiedEvent.passed === true);
  const isAwaiting = playbackState === 'awaiting-approval';

  return (
    <div
      role="region"
      aria-label="Proposed fix"
      className={[
        'rounded-xl border overflow-hidden text-sm transition-opacity',
        isRejected ? 'border-slate-700 opacity-40' : 'border-slate-600',
        'bg-[#1a1a2e]',
      ].filter(Boolean).join(' ')}
    >
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-2.5 bg-[#22223a] border-b border-slate-700">
        <span className="text-xs text-slate-500 font-mono">requests/status_codes.py</span>
        <span className="text-xs text-slate-600">·</span>
        <span className="text-xs text-slate-500">line 116</span>
        {isRejected && (
          <span className="ml-auto text-xs text-slate-500 italic">Fix dismissed</span>
        )}
        {isApplying && (
          <span className="ml-auto text-xs text-amber-400 animate-pulse">Applying…</span>
        )}
        {isVerified && (
          <span className="ml-auto text-xs text-green-400 font-medium">✓ Fix applied</span>
        )}
      </div>

      {/* Awaiting approval — prompt the user */}
      {isAwaiting && (
        <div className="px-4 py-3 flex flex-col sm:flex-row sm:items-center gap-3">
          <p className="text-slate-300 text-sm flex-1">
            The fix guards the concatenation with{' '}
            <code className="font-mono text-xs text-amber-300 bg-amber-500/10 px-1 py-0.5 rounded">
              (__doc__ or '')
            </code>
            . Apply it?
          </p>
          <div className="flex gap-2 flex-shrink-0">
            <button
              aria-label="Apply fix"
              onClick={onApproveFix}
              className="px-4 py-2 bg-green-600 hover:bg-green-500 text-white font-semibold rounded-lg text-sm transition-colors focus:outline-none focus:ring-2 focus:ring-green-400 cursor-pointer"
            >
              Apply fix
            </button>
            <button
              aria-label="Dismiss fix"
              onClick={onRejectFix}
              className="px-4 py-2 bg-slate-700 hover:bg-slate-600 text-slate-300 rounded-lg text-sm border border-slate-600 transition-colors focus:outline-none focus:ring-2 focus:ring-slate-400 cursor-pointer"
            >
              Dismiss
            </button>
          </div>
        </div>
      )}

      {/* Applying state */}
      {isApplying && (
        <div className="px-4 py-3 text-slate-400 text-sm italic">
          Watch line 116 in the editor above…
        </div>
      )}

      {/* Verified banner */}
      {isVerified && !isAwaiting && !isApplying && (
        <div
          role="status"
          className="px-4 py-3 bg-green-950/40 border-t border-green-800/40 text-green-400 text-sm font-medium flex items-center gap-2"
        >
          <span className="text-base">✓</span>
          <span>Probe failed before fix, passed after. Verified.</span>
        </div>
      )}

      {/* Failure banner */}
      {verifiedEvent !== null && verifiedEvent.passed === false && (
        <div
          role="status"
          className="px-4 py-3 bg-red-950/40 border-t border-red-800/40 text-red-400 text-sm font-medium flex items-center gap-2"
        >
          <span className="text-base">✗</span>
          <span>Probe still failing after fix. Review needed.</span>
        </div>
      )}
    </div>
  );
}
