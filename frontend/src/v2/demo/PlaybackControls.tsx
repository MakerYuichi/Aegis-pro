interface PlaybackControlsProps {
  isPlaying: boolean;
  currentIndex: number;
  total: number;
  onPlay: () => void;
  onPause: () => void;
  onRestart: () => void;
  onStepForward: () => void;
  onStepBackward: () => void;
}

export function PlaybackControls({
  isPlaying,
  currentIndex,
  total,
  onPlay,
  onPause,
  onRestart,
  onStepForward,
  onStepBackward,
}: PlaybackControlsProps) {
  const progress = total > 0 ? ((currentIndex + 1) / total) * 100 : 0;
  const eventLabel = currentIndex === -1 ? '—' : `${currentIndex + 1} of ${total}`;

  return (
    <div className="bg-slate-800 rounded-lg px-4 py-2 flex items-center gap-3 flex-shrink-0">
      {/* Restart */}
      <button
        onClick={onRestart}
        title="Restart [Esc]"
        className="hover:bg-slate-700 rounded p-2 text-slate-300 transition-colors text-sm"
      >
        ⏮ Restart
      </button>

      {/* Step Back */}
      <button
        onClick={onStepBackward}
        title="Step Back [←]"
        className="hover:bg-slate-700 rounded p-2 text-slate-300 transition-colors text-sm"
        disabled={currentIndex <= -1}
      >
        ◀ Back
      </button>

      {/* Play / Pause */}
      <button
        onClick={isPlaying ? onPause : onPlay}
        title={isPlaying ? 'Pause [Space]' : 'Play [Space]'}
        className="hover:bg-slate-700 rounded p-2 text-slate-100 font-semibold transition-colors text-sm min-w-[80px] text-center"
      >
        {isPlaying ? '⏸ Pause' : '▶ Play'}
      </button>

      {/* Step Forward */}
      <button
        onClick={onStepForward}
        title="Step Forward [→]"
        className="hover:bg-slate-700 rounded p-2 text-slate-300 transition-colors text-sm"
        disabled={currentIndex >= total - 1}
      >
        Forward ▶
      </button>

      {/* Divider */}
      <div className="w-px h-6 bg-slate-700 mx-1" />

      {/* Progress text */}
      <span className="text-slate-400 text-xs font-mono whitespace-nowrap">
        Event {eventLabel}
      </span>

      {/* Progress bar */}
      <div className="flex-1 bg-slate-700 rounded-full h-1.5 overflow-hidden">
        <div
          className="bg-blue-500 h-full rounded-full transition-all duration-500"
          style={{ width: `${progress}%` }}
        />
      </div>

      {/* Keyboard hint */}
      <span className="text-slate-600 text-xs hidden lg:block whitespace-nowrap">
        [Space] [→] [←] [Esc]
      </span>
    </div>
  );
}
