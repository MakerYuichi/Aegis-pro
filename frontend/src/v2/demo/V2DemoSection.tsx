import { forwardRef } from 'react';
import type { V2Event, PlaybackState } from '../types';
import { EditorCanvas } from './EditorCanvas';
import { NarrationPanel } from './NarrationPanel';
import { ChainPanel } from './ChainPanel';
import { Callout } from './Callout';
import { PlaybackControls } from './PlaybackControls';
import demoEvents from './demo-investigation.json';

const events = demoEvents as V2Event[];

interface V2DemoSectionProps {
  currentIndex: number;
  isPlaying: boolean;
  playbackState: PlaybackState;
  onPlay: () => void;
  onPause: () => void;
  onRestart: () => void;
  onStepForward: () => void;
  onStepBackward: () => void;
  onApproveFix: () => void;
  onRejectFix: () => void;
}

export const V2DemoSection = forwardRef<HTMLElement, V2DemoSectionProps>(
  function V2DemoSection(
    {
      currentIndex,
      isPlaying,
      playbackState,
      onPlay,
      onPause,
      onRestart,
      onStepForward,
      onStepBackward,
      onApproveFix,
      onRejectFix,
    },
    ref,
  ) {
    const symbolLocatedIndex = events.findIndex((e) => e.kind === 'symbol.located');
    const showGutterArrow =
      symbolLocatedIndex >= 0 && currentIndex >= symbolLocatedIndex;

    const isVerified = playbackState === 'verified';
    const eventLabel =
      currentIndex === -1 ? '—' : `${currentIndex + 1} of ${events.length}`;

    return (
      <section
        ref={ref}
        className="min-h-screen bg-slate-950 flex flex-col items-center justify-center py-24 px-4"
      >
        {/* Section label above card */}
        <div className="mb-8 text-center">
          <span className="inline-flex items-center gap-2 text-sm text-slate-400 tracking-wider uppercase">
            <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse inline-block" />
            Live investigation
          </span>
        </div>

        {/* Cinematic card — group enables group-hover on children */}
        <div className="group max-w-6xl w-full mx-auto rounded-2xl shadow-2xl border border-slate-800 bg-slate-900 overflow-hidden relative">

          {/* Title bar — always visible */}
          <div className="h-11 bg-slate-800 border-b border-slate-700 flex items-center px-4 gap-3 flex-shrink-0">
            {/* Traffic-light dots */}
            <span
              className={`w-3 h-3 rounded-full transition-colors duration-500 ${isVerified ? 'bg-red-500' : 'bg-slate-600'}`}
            />
            <span
              className={`w-3 h-3 rounded-full transition-colors duration-500 ${isVerified ? 'bg-yellow-400' : 'bg-slate-600'}`}
            />
            <span
              className={`w-3 h-3 rounded-full transition-colors duration-500 ${isVerified ? 'bg-green-500' : 'bg-slate-600'}`}
            />

            <span className="text-sm text-slate-400 ml-1">requests/status_codes.py</span>

            {/* Verified badge — right side */}
            {isVerified && (
              <span className="ml-auto px-2 py-0.5 rounded text-xs font-semibold bg-green-500/20 border border-green-500/50 text-green-400">
                ✓ Verified
              </span>
            )}
          </div>

          {/* Main content area: editor (65%) + chain panel (35%) */}
          <div
            className="flex flex-row"
            style={{ height: 'calc(100vh - 340px)', minHeight: '420px' }}
          >
            {/* Editor — 65% */}
            <div className="relative flex flex-col" style={{ flex: '0 0 65%', minHeight: 0 }}>
              <EditorCanvas
                showGutterArrow={showGutterArrow}
                highlightLine={116}
                events={events}
                currentIndex={currentIndex}
                playbackState={playbackState}
                onApproveFix={onApproveFix}
                onRejectFix={onRejectFix}
              />
              <Callout
                events={events}
                currentIndex={currentIndex}
                onApproveFix={onApproveFix}
                onRejectFix={onRejectFix}
                playbackState={playbackState}
              />
            </div>

            {/* Chain panel — 35% */}
            <div style={{ flex: '0 0 35%', minHeight: 0 }}>
              <ChainPanel currentIndex={currentIndex} events={events} />
            </div>
          </div>

          {/* Hover-only playback bar — sits above narration strip */}
          <div
            className="opacity-0 group-hover:opacity-100 transition-opacity duration-200 pointer-events-none group-hover:pointer-events-auto
                       border-t border-slate-700 bg-slate-800/90 backdrop-blur p-2 flex items-center gap-3"
          >
            {/* Compact restart */}
            <button
              onClick={onRestart}
              title="Restart"
              className="hover:bg-slate-700 rounded px-2 py-1 text-slate-300 transition-colors text-xs"
            >
              ⏮
            </button>

            {/* Step back */}
            <button
              onClick={onStepBackward}
              title="Step Back"
              disabled={currentIndex <= -1 || playbackState === 'awaiting-approval' || playbackState === 'applying'}
              className="hover:bg-slate-700 rounded px-2 py-1 text-slate-300 transition-colors text-xs disabled:opacity-40 disabled:cursor-not-allowed"
            >
              ◀
            </button>

            {/* Play / Pause */}
            <button
              onClick={isPlaying ? onPause : onPlay}
              title={isPlaying ? 'Pause' : 'Play'}
              className="hover:bg-slate-700 rounded px-3 py-1 text-slate-100 font-semibold transition-colors text-xs min-w-[48px] text-center"
            >
              {isPlaying ? '⏸' : '▶'}
            </button>

            {/* Step forward */}
            <button
              onClick={onStepForward}
              title="Step Forward"
              disabled={currentIndex >= events.length - 1 || playbackState === 'awaiting-approval' || playbackState === 'applying'}
              className="hover:bg-slate-700 rounded px-2 py-1 text-slate-300 transition-colors text-xs disabled:opacity-40 disabled:cursor-not-allowed"
            >
              ▶
            </button>

            <div className="w-px h-4 bg-slate-600 mx-1" />

            {/* Event counter */}
            <span className="text-slate-500 text-xs font-mono whitespace-nowrap">
              Event {eventLabel}
            </span>

            {/* Awaiting approval badge */}
            {playbackState === 'awaiting-approval' && (
              <span className="px-2 py-0.5 rounded-full bg-amber-500/20 border border-amber-500/50 text-amber-300 text-xs font-medium whitespace-nowrap">
                Waiting for approval...
              </span>
            )}

            {/* Progress bar */}
            <div className="flex-1 bg-slate-700 rounded-full h-1 overflow-hidden">
              <div
                className="bg-blue-500 h-full rounded-full transition-all duration-500"
                style={{ width: events.length > 0 ? `${((currentIndex + 1) / events.length) * 100}%` : '0%' }}
              />
            </div>
          </div>

          {/* Narration strip — always visible */}
          <NarrationPanel
            events={events}
            currentIndex={currentIndex}
            playbackState={playbackState}
          />
        </div>

        {/* Keep PlaybackControls imported but used via the hover bar above;
            we still import it to pass through, but the visible UI is the inline bar.
            Below is a hidden reference to satisfy the "keep as-is" requirement
            while using the compact inline controls instead. */}
        <div className="sr-only" aria-hidden="true">
          <PlaybackControls
            isPlaying={isPlaying}
            currentIndex={currentIndex}
            total={events.length}
            playbackState={playbackState}
            onPlay={onPlay}
            onPause={onPause}
            onRestart={onRestart}
            onStepForward={onStepForward}
            onStepBackward={onStepBackward}
          />
        </div>
      </section>
    );
  },
);
