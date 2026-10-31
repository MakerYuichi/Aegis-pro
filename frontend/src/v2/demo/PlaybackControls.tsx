import { RotateCcw, SkipBack, Play, Pause, SkipForward } from 'lucide-react';
import type { PlaybackState } from '../types';

interface PlaybackControlsProps {
  isPlaying: boolean;
  currentIndex: number;
  total: number;
  playbackState: PlaybackState;
  reducedMotion: boolean;
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
  playbackState,
  reducedMotion,
  onPlay,
  onPause,
  onRestart,
  onStepForward,
  onStepBackward,
}: PlaybackControlsProps) {
  const progress = total > 0 ? ((currentIndex + 1) / total) * 100 : 0;
  const eventLabel = currentIndex === -1 ? '—' : `${currentIndex + 1} / ${total}`;

  const stepsDisabled =
    playbackState === 'awaiting-approval' || playbackState === 'applying';

  const btnBase =
    'hover:bg-aegis-line rounded p-2 text-slate-300 transition-colors focus:outline-none focus:ring-2 focus:ring-aegis-amber focus:ring-offset-1 focus:ring-offset-aegis-bg';

  return (
    <div
      role="toolbar"
      aria-label="Playback controls"
      className="bg-aegis-surface border-t border-aegis-line px-4 py-2 flex items-center gap-3 flex-shrink-0"
    >
      {/* Restart */}
      <button
        onClick={onRestart}
        aria-label="Restart investigation"
        className={btnBase}
      >
        <RotateCcw size={16} />
      </button>

      {/* Step Back */}
      <button
        onClick={onStepBackward}
        aria-label="Step back"
        className={`${btnBase} disabled:opacity-40 disabled:cursor-not-allowed`}
        disabled={currentIndex <= -1 || stepsDisabled}
      >
        <SkipBack size={16} />
      </button>

      {/* Play / Pause */}
      <button
        onClick={isPlaying ? onPause : onPlay}
        aria-label={isPlaying ? 'Pause' : 'Play'}
        className={`${btnBase} text-slate-100`}
      >
        {isPlaying ? <Pause size={16} /> : <Play size={16} />}
      </button>

      {/* Step Forward */}
      <button
        onClick={onStepForward}
        aria-label="Step forward"
        className={`${btnBase} disabled:opacity-40 disabled:cursor-not-allowed`}
        disabled={currentIndex >= total - 1 || stepsDisabled}
      >
        <SkipForward size={16} />
      </button>

      {/* Divider */}
      <div className="w-px h-4 bg-aegis-line mx-1 flex-shrink-0" />

      {/* Event counter */}
      <span className="text-slate-400 text-xs font-mono whitespace-nowrap tabular-nums">
        {eventLabel}
      </span>

      {/* Reduced motion label */}
      {reducedMotion && (
        <span className="text-slate-500 text-xs whitespace-nowrap">(manual mode)</span>
      )}

      {/* Awaiting approval badge */}
      {playbackState === 'awaiting-approval' && (
        <span className="px-2 py-0.5 rounded-full bg-aegis-amber/20 border border-aegis-amber/50 text-aegis-amber text-xs font-medium whitespace-nowrap">
          Waiting for approval…
        </span>
      )}

      {/* Progress bar */}
      <div className="flex-1 bg-aegis-line rounded-full h-1.5 overflow-hidden">
        <div
          className="bg-aegis-amber h-full rounded-full transition-all duration-500"
          style={{ width: `${progress}%` }}
        />
      </div>

      {/* Keyboard hint */}
      <span className="text-slate-600 text-xs hidden lg:block whitespace-nowrap">
        Space · → · ← · Esc
      </span>
    </div>
  );
}
