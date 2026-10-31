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
  connector: string;
} {
  switch (kind) {
    case 'hypothesis.formed':
    case 'symbol.located':
      return {
        border: 'border-aegis-amber',
        bg: 'bg-aegis-amber/10',
        text: 'text-aegis-amber',
        connector: 'border-aegis-amber',
      };
    case 'probe.reproduced':
      return {
        border: 'border-aegis-red',
        bg: 'bg-aegis-red/10',
        text: 'text-aegis-red',
        connector: 'border-aegis-red',
      };
    case 'bug.confirmed':
      return {
        border: 'border-aegis-green',
        bg: 'bg-aegis-green/10',
        text: 'text-aegis-green',
        connector: 'border-aegis-green',
      };
    default:
      return {
        border: 'border-slate-600',
        bg: 'bg-slate-800/80',
        text: 'text-slate-300',
        connector: 'border-slate-600',
      };
  }
}

function getCalloutContent(event: V2Event): { title: string; body: string } | null {
  switch (event.kind) {
    case 'hypothesis.formed':
      return { title: 'Hypothesis', body: event.text };
    case 'symbol.located':
      return { title: 'Symbol located', body: `${event.symbol} · line ${event.line} · ${event.file}` };
    case 'probe.reproduced':
      return { title: 'Reproduced', body: event.error };
    case 'bug.confirmed':
      return { title: 'Bug confirmed', body: event.failure_mode };
    default:
      return null;
  }
}

export function CalloutCard({ event, topPx, reducedMotion }: CalloutCardProps) {
  const content = getCalloutContent(event);
  if (!content) return null;

  const colors = getCalloutColors(event.kind);
  const LINE_HEIGHT = 20;

  return (
    <>
      {/* Horizontal dashed connector from gutter right-edge to callout left-edge */}
      <div
        className={`absolute pointer-events-none border-t border-dashed ${colors.connector}`}
        style={{
          left: '3rem',   // right edge of w-12 gutter
          right: '17rem', // w-60 (240px) + right-4 (16px) = 256px from right; 17rem ≈ 272px — gives small gap
          top: topPx + LINE_HEIGHT / 2,
          height: 1,
        }}
      />
      {/* Callout card */}
      <div
        className={[
          'absolute right-4 w-60 rounded-md border p-3 text-xs pointer-events-auto',
          colors.border,
          colors.bg,
          reducedMotion ? '' : 'motion-safe:animate-aegis-callout-in',
        ]
          .filter(Boolean)
          .join(' ')}
        style={{ top: topPx }}
      >
        <p className={`font-semibold mb-1 ${colors.text}`}>{content.title}</p>
        <p className="text-slate-300 leading-relaxed break-words">{content.body}</p>
      </div>
    </>
  );
}
