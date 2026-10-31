import { Play } from 'lucide-react';

interface HeroColumnProps {
  reducedMotion: boolean;
  onPlayClick: () => void;
  className?: string;
}

export function HeroColumn({ reducedMotion, onPlayClick, className }: HeroColumnProps) {
  return (
    <div className={`flex flex-col justify-center ${className ?? ''}`}>
      <h1 className="text-4xl lg:text-5xl font-bold text-slate-100 leading-tight">
        Watch the bug get found.
      </h1>
      <p className="mt-4 text-lg text-slate-400 leading-relaxed">
        AEGIS investigates your code, live. Every arrow, every callout, every fix — visible.
      </p>
      {reducedMotion && (
        <button
          aria-label="Play investigation"
          onClick={onPlayClick}
          className="mt-6 inline-flex items-center gap-2 px-5 py-3 bg-aegis-surface border border-aegis-line hover:border-slate-500 text-slate-100 font-semibold rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-aegis-amber self-start cursor-pointer"
        >
          <Play size={20} />
          Play
        </button>
      )}
    </div>
  );
}
