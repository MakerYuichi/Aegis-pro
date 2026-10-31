import type { V2Event } from '../types';

interface CalloutCardProps {
  event: V2Event;
  topPx: number;
  reducedMotion: boolean;
}

function getCalloutColors(kind: V2Event['kind']): {
  border: string;
  bg: string;
  text: string;
  label: string;
} {
  switch (kind) {
    case 'hypothesis.formed':
      return { border: 'border-amber-500', bg: 'bg-amber-500/10', text: 'text-amber-400', label: 'Hypothesis' };
    case 'symbol.located':
      return { border: 'border-amber-500', bg: 'bg-amber-500/10', text: 'text-amber-400', label: 'Symbol located' };
    case 'probe.reproduced':
      return { border: 'border-red-500', bg: 'bg-red-500/10', text: 'text-red-400', label: 'Reproduced' };
    case 'bug.confirmed':
      return { border: 'border-green-500', bg: 'bg-green-500/10', text: 'text-green-400', label: 'Bug confirmed' };
    default:
      return { border: 'border-slate-600', bg: 'bg-slate-800', text: 'text-slate-400', label: '' };
  }
}

function getCalloutBody(event: V2Event): string | null {
  switch (event.kind) {
    case 'hypothesis.formed':  return event.text;
    case 'symbol.located':     return `${event.symbol} · line ${event.line}`;
    case 'probe.reproduced':   return event.error;
    case 'bug.confirmed':      return event.failure_mode;
    default:                   return null;
  }
}

export function CalloutCard({ event, reducedMotion }: Omit<CalloutCardProps, 'topPx'> & { topPx: number }) {
  const body = getCalloutBody(event);
  if (!body) return null;

  const colors = getCalloutColors(event.kind);

  return (
    <div
      className={[
        'w-full rounded border-l-4 p-2.5',
        colors.border,
        colors.bg,
        reducedMotion ? '' : 'motion-safe:animate-aegis-callout-in',
      ].filter(Boolean).join(' ')}
      style={{ marginBottom: '8px' }}
    >
      <p className={`text-xs font-semibold mb-0.5 ${colors.text}`}>{colors.label}</p>
      <p className="text-xs text-slate-300 leading-relaxed break-words">{body}</p>
    </div>
  );
}
