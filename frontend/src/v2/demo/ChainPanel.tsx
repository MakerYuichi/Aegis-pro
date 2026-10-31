import type { V2Event, ChainLink } from '../types';

interface ChainPanelProps {
  currentIndex: number;
  events: V2Event[];
}

interface ChainBoxProps {
  link: ChainLink;
}

function ChainBox({ link }: ChainBoxProps) {
  return (
    <div className="rounded-md border border-aegis-amber bg-aegis-amber/10 p-3 text-xs motion-safe:animate-pulse">
      <div className="font-mono text-slate-200 font-semibold truncate">
        {link.file}:{link.line}
      </div>
      <div className="text-slate-400 mt-0.5">
        symbol: <span className="text-aegis-amber">{link.symbol}</span>
      </div>
      {link.reason && (
        <div className="text-slate-500 mt-0.5">{link.reason}</div>
      )}
    </div>
  );
}

export function ChainPanel({ currentIndex, events }: ChainPanelProps) {
  const chainResolvedIndex = events.findIndex((e) => e.kind === 'chain.resolved');
  const chainFired = chainResolvedIndex >= 0 && currentIndex >= chainResolvedIndex;

  // Extract the chain from the resolved event
  let chain: ChainLink[] = [];
  if (chainFired) {
    const resolvedEvent = events[chainResolvedIndex];
    if (resolvedEvent.kind === 'chain.resolved') {
      chain = resolvedEvent.chain;
    }
  }

  return (
    <div className="bg-aegis-surface border-l border-aegis-line p-4 flex flex-col h-full overflow-y-auto">
      {/* Header */}
      <div className="mb-4">
        <h3 className="text-slate-200 font-semibold text-sm">
          Invocation chain · single-file finding
        </h3>
      </div>

      {/* Chain content */}
      {chainFired ? (
        <div className="flex flex-col gap-2">
          {chain.map((link, idx) => (
            <ChainBox key={`${link.file}-${link.line}-${idx}`} link={link} />
          ))}
        </div>
      ) : (
        <div className="rounded-md border border-dashed border-slate-700 p-3 text-xs text-slate-600 italic">
          Resolving chain…
        </div>
      )}
    </div>
  );
}
