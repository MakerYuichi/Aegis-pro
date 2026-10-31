import { forwardRef, useRef } from 'react';
import type { V2Event, PlaybackState } from '../types';
import { CodeView } from './CodeView';
import type { CodeViewHandle } from './CodeView';
import { PYTHON_SOURCE_LINES, START_LINE_NUMBER } from './pythonSource';
import { CalloutLayer } from './CalloutLayer';
import { DiffView } from './DiffView';
import { EditorCard } from './EditorCard';
import { NarrationPanel } from './NarrationPanel';
import { ChainPanel } from './ChainPanel';
import { PlaybackControls } from './PlaybackControls';

interface V2DemoSectionProps {
  events: V2Event[];
  currentIndex: number;
  isPlaying: boolean;
  playbackState: PlaybackState;
  reducedMotion: boolean;
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
      events,
      currentIndex,
      isPlaying,
      playbackState,
      reducedMotion,
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
    const codeViewRef = useRef<CodeViewHandle>(null);
    const editorContainerRef = useRef<HTMLDivElement>(null);

    const isVerified = playbackState === 'verified';

    const firedKinds = new Set(events.slice(0, currentIndex + 1).map((e) => e.kind));
    const gutterState: 'none' | 'amber' | 'green' =
      firedKinds.has('fix.verified') ? 'green' :
      firedKinds.has('symbol.located') ? 'amber' : 'none';

    const highlightLine = 116;

    const firedEvents = events.slice(0, currentIndex + 1);
    const proposedEvent =
      (firedEvents.find((e) => e.kind === 'fix.proposed') as Extract<V2Event, { kind: 'fix.proposed' }>) ?? null;
    const verifiedEvent =
      (firedEvents.find((e) => e.kind === 'fix.verified') as Extract<V2Event, { kind: 'fix.verified' }>) ?? null;

    return (
      <section ref={ref} className="w-full flex flex-col gap-3">

        {/* ── Main card: editor (left) + callout panel (right) + chain (far right on desktop) ── */}
        <div className="flex flex-col lg:flex-row gap-3">

          {/* Editor + callouts column — 65% */}
          <div className="flex flex-col gap-3 lg:w-[65%] min-w-0">
            <EditorCard fileName="requests/status_codes.py" isVerified={isVerified}>
              {/* Side-by-side: code (left 60%) | callout panel (right 40%) */}
              <div ref={editorContainerRef} className="flex" style={{ height: '360px' }}>
                {/* Code area */}
                <div className="flex-1 min-w-0 overflow-hidden border-r border-slate-700">
                  <CodeView
                    ref={codeViewRef}
                    lines={PYTHON_SOURCE_LINES}
                    startLineNumber={START_LINE_NUMBER}
                    highlightLine={highlightLine}
                    gutterState={gutterState}
                    playbackState={playbackState}
                    reducedMotion={reducedMotion}
                  />
                </div>
                {/* Callout panel — fixed width, scrolls independently */}
                <div className="w-52 flex-shrink-0 bg-[#0d1321]">
                  <div className="px-2 py-1.5 border-b border-aegis-line">
                    <span className="text-[10px] text-slate-500 uppercase tracking-wider">Observations</span>
                  </div>
                  <CalloutLayer
                    events={events}
                    currentIndex={currentIndex}
                    codeViewRef={codeViewRef}
                    containerRef={editorContainerRef}
                    reducedMotion={reducedMotion}
                  />
                </div>
              </div>
            </EditorCard>

            {/* DiffView — below the editor card, appears when fix.proposed fires */}
            <DiffView
              proposedEvent={proposedEvent}
              verifiedEvent={verifiedEvent}
              playbackState={playbackState}
              reducedMotion={reducedMotion}
              onApproveFix={onApproveFix}
              onRejectFix={onRejectFix}
            />
          </div>

          {/* Chain panel — 35% on large screens, stacked below on mobile */}
          <div className="lg:w-[35%] flex-shrink-0">
            <ChainPanel currentIndex={currentIndex} events={events} />
          </div>
        </div>

        {/* ── Narration strip ── */}
        <NarrationPanel
          events={events}
          currentIndex={currentIndex}
          playbackState={playbackState}
        />

        {/* ── Playback controls ── */}
        <PlaybackControls
          isPlaying={isPlaying}
          currentIndex={currentIndex}
          total={events.length}
          playbackState={playbackState}
          reducedMotion={reducedMotion}
          onPlay={onPlay}
          onPause={onPause}
          onRestart={onRestart}
          onStepForward={onStepForward}
          onStepBackward={onStepBackward}
        />
      </section>
    );
  },
);
