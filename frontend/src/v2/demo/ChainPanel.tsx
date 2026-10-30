import type { V2Event } from '../types';

interface ChainPanelProps {
  currentIndex: number;
  events: V2Event[];
}

interface ChainBoxProps {
  file: string;
  lineNum: number;
  symbol: string;
  label?: string;
  active: boolean;
  isReal: boolean;
}

function ChainBox({ file, lineNum, symbol, label, active, isReal }: ChainBoxProps) {
  return (
    <div
      className={`rounded-md border p-3 text-xs transition-all duration-500 ${
        active && isReal
          ? 'border-amber-500 bg-amber-500/10 animate-pulse'
          : 'border-slate-700 bg-slate-800/50 opacity-40'
      }`}
    >
      <div className="font-mono text-slate-200 font-semibold truncate">
        {file}:{lineNum}
      </div>
      <div className="text-slate-400 mt-0.5">
        symbol: <span className="text-amber-400">{symbol}</span>
      </div>
      {label && (
        <div className="text-slate-500 mt-0.5 italic">{label}</div>
      )}
    </div>
  );
}

export function ChainPanel({ currentIndex, events }: ChainPanelProps) {
  const chainResolvedIndex = events.findIndex(e => e.kind === 'chain.resolved');
  const chainActive = chainResolvedIndex >= 0 && currentIndex >= chainResolvedIndex;

  return (
    <div
      className="bg-slate-900 border-l border-slate-800 p-4 flex flex-col h-full overflow-y-auto"
    >
      {/* Header */}
      <div className="mb-4">
        <h3 className="text-slate-200 font-semibold text-sm">Invocation Chain</h3>
        <span className="inline-block mt-1 px-2 py-0.5 rounded-full bg-slate-800 border border-slate-700 text-slate-400 text-xs">
          Single-file finding
        </span>
      </div>

      {/* Chain boxes */}
      <div className="flex flex-col gap-1">
        <ChainBox
          file="requests/status_codes.py"
          lineNum={116}
          symbol="__doc__"
          label="crash site"
          active={chainActive}
          isReal={true}
        />

        {/* Connector line */}
        <div className="border-l-2 border-slate-700 h-4 ml-4" />

        <ChainBox
          file="requests/models.py"
          lineNum={128}
          symbol="PreparedRequest"
          label="(example)"
          active={false}
          isReal={false}
        />

        {/* Connector line */}
        <div className="border-l-2 border-slate-700 h-4 ml-4" />

        <ChainBox
          file="requests/status_codes.py"
          lineNum={116}
          symbol="__doc__"
          label="(example)"
          active={false}
          isReal={false}
        />
      </div>

      {/* Legend */}
      <div className="mt-auto pt-4 border-t border-slate-800">
        <p className="text-slate-600 text-xs leading-relaxed">
          Boxes 2 and 3 are synthetic examples showing what a multi-file chain would look like.
          This finding has one real link.
        </p>
      </div>
    </div>
  );
}
