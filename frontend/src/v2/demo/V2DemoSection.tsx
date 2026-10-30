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

    return (
      <section
        ref={ref}
        className="min-h-screen bg-slate-950 flex flex-col py-8 px-4"
        style={{ minHeight: '100vh' }}
      >
        {/* Top bar: left label, center controls, right event counter */}
        <div className="mb-4 flex-shrink-0 flex items-center gap-3">
          {/* Left: live investigation label */}
          <div className="flex items-center gap-2 text-xs text-slate-400 whitespace-nowrap">
            <span
              className="inline-block w-2 h-2 rounded-full bg-green-400"
              style={{ animation: isPlaying ? 'pulse 1.5s ease-in-out infinite' : 'none' }}
            />
            Live investigation
          </div>

          {/* Center: playback controls */}
          <div className="flex-1">
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

          {/* Right: event counter + space hint */}
          <div className="text-xs text-slate-500 whitespace-nowrap hidden md:block">
            Event {currentIndex === -1 ? '—' : `${currentIndex + 1} of ${events.length}`}
            <span className="ml-2 text-slate-600">[Space] pause</span>
          </div>
        </div>

        {/* Main split: editor (65%) + chain panel (35%) */}
        <div
          className="flex flex-row flex-1"
          style={{ minHeight: 0, height: 'calc(100vh - 280px)' }}
        >
          {/* Editor area — 65%, relative so Callout can absolute-position within it */}
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

        {/* Narration strip */}
        <NarrationPanel
          events={events}
          currentIndex={currentIndex}
          playbackState={playbackState}
        />
      </section>
    );
  },
);
