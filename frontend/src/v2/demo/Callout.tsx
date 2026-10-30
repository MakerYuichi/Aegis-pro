import type { V2Event } from '../types';

interface CalloutProps {
  events: V2Event[];
  currentIndex: number;
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

export function Callout({ events, currentIndex }: CalloutProps) {
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
        return (
          <div
            key={`${event.kind}-${idx}`}
            className={`rounded-md p-3 text-xs pointer-events-auto ${config.colorClass} ${config.borderClass}`}
            style={{
              animation: 'aegis-callout-in 0.3s ease-out both',
            }}
          >
            <p className={`font-semibold mb-1 ${config.textClass}`}>{config.title}</p>
            <p className="text-slate-300 leading-relaxed whitespace-pre-wrap break-words">
              {config.body}
            </p>
            {config.showApplyFix && (
              <button
                disabled
                className="mt-2 px-3 py-1 bg-green-600 text-white rounded text-xs opacity-50 pointer-events-none cursor-not-allowed"
              >
                Apply fix
              </button>
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
