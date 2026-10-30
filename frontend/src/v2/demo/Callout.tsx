import type { V2Event, PlaybackState } from '../types';

interface CalloutProps {
  events: V2Event[];
  currentIndex: number;
  onApproveFix?: () => void;
  onRejectFix?: () => void;
  playbackState?: PlaybackState;
}

interface CalloutConfig {
  title: string;
  body: string;
  colorClass: string;
  borderClass: string;
  textClass: string;
  showApplyFix: boolean;
}

function getCalloutConfig(event: V2Event): CalloutConfig | null {
  switch (event.kind) {
    case 'hypothesis.formed':
      return {
        title: 'Observation',
        body: event.text,
        colorClass: 'bg-blue-500/20',
        borderClass: 'border border-blue-500',
        textClass: 'text-blue-300',
        showApplyFix: false,
      };
    case 'symbol.located':
      return {
        title: 'Located',
        body: `${event.symbol} at line ${event.line} in ${event.file}`,
        colorClass: 'bg-amber-500/20',
        borderClass: 'border border-amber-500',
        textClass: 'text-amber-300',
        showApplyFix: false,
      };
    case 'probe.reproduced':
      return {
        title: 'Reproduced',
        body: event.error,
        colorClass: 'bg-red-500/20',
        borderClass: 'border border-red-500',
        textClass: 'text-red-300',
        showApplyFix: false,
      };
    case 'bug.confirmed':
      return {
        title: 'Bug Confirmed',
        body: event.failure_mode,
        colorClass: 'bg-green-500/20',
        borderClass: 'border border-green-500',
        textClass: 'text-green-300',
        showApplyFix: false,
      };
    case 'fix.proposed':
      return {
        title: 'Fix Proposed',
        body: event.diff,
        colorClass: 'bg-green-500/20',
        borderClass: 'border border-green-500',
        textClass: 'text-green-300',
        showApplyFix: true,
      };
    default:
      return null;
  }
}

export function Callout({ events, currentIndex, onApproveFix, onRejectFix, playbackState }: CalloutProps) {
  const calloutKinds = new Set([
    'hypothesis.formed',
    'symbol.located',
    'probe.reproduced',
    'bug.confirmed',
    'fix.proposed',
  ]);

  const visibleCalloutEvents = events
    .slice(0, currentIndex + 1)
    .filter((e) => calloutKinds.has(e.kind));

  if (visibleCalloutEvents.length === 0) return null;

  return (
    <div
      className="absolute top-0 right-0 w-72 flex flex-col gap-2 p-3 pointer-events-none"
      style={{ zIndex: 10 }}
    >
      {visibleCalloutEvents.map((event, idx) => {
        const config = getCalloutConfig(event);
        if (!config) return null;

        const isLast = idx === visibleCalloutEvents.length - 1;
        const dimmed = !isLast;

        return (
          <div
            key={`${event.kind}-${idx}`}
            className={`rounded-md p-3 text-xs pointer-events-auto ${config.colorClass} ${config.borderClass} transition-opacity duration-300`}
            style={{
              animation: 'aegis-callout-in 0.3s ease-out both',
              opacity: dimmed ? 0.4 : 1,
            }}
          >
            <p className={`font-semibold mb-1 ${config.textClass}`}>{config.title}</p>
            <p className="text-slate-300 leading-relaxed whitespace-pre-wrap break-words">
              {config.body}
            </p>

            {/* Interactive buttons for fix.proposed */}
            {config.showApplyFix && isLast && (
              <div className="mt-2">
                {playbackState === 'applying' && (
                  <span className="text-slate-400 text-xs italic">Applying...</span>
                )}
                {(playbackState === 'verified' || playbackState === 'playing') && (
                  <span className="text-green-400 text-xs font-semibold">✓ Applied. Verified.</span>
                )}
                {playbackState === 'rejected' && (
                  <span className="text-slate-400 text-xs">Dismissed.</span>
                )}
                {playbackState === 'awaiting-approval' && (
                  <div className="flex gap-2 mt-1">
                    <button
                      onClick={onApproveFix}
                      className="px-3 py-1 bg-green-600 hover:bg-green-500 text-white rounded text-xs font-semibold transition-colors cursor-pointer"
                    >
                      Apply fix
                    </button>
                    <button
                      onClick={onRejectFix}
                      className="px-3 py-1 bg-slate-700 hover:bg-slate-600 text-slate-200 rounded text-xs transition-colors cursor-pointer"
                    >
                      Dismiss
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
      <style>{`
        @keyframes aegis-callout-in {
          from { opacity: 0; transform: translateX(8px); }
          to   { opacity: 1; transform: translateX(0); }
        }
      `}</style>
    </div>
  );
}
