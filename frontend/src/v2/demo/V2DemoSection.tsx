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

    // Derive display state from events
    const isVerified = playbackState === 'verified';

    const firedKinds = new Set(events.slice(0, currentIndex + 1).map((e) => e.kind));
    const gutterState: 'none' | 'amber' | 'green' =
      firedKinds.has('fix.verified') ? 'green' :
      firedKinds.has('symbol.located') ? 'amber' : 'none';

    // highlightLine always 116 — from symbol.located or fallback
    const highlightLine = 116;

    // Derive proposedEvent and verifiedEvent for DiffView
    const firedEvents = events.slice(0, currentIndex + 1);
    const proposedEvent =
      (firedEvents.find((e) => e.kind === 'fix.proposed') as Extract<V2Event, { kind: 'fix.proposed' }>) ?? null;
    const verifiedEvent =
      (firedEvents.find((e) => e.kind === 'fix.verified') as Extract<V2Event, { kind: 'fix.verified' }>) ?? null;

    return (
      <section
        ref={ref}
        className="w-full"
      >
        <div className="flex flex-col lg:flex-row gap-4">
          {/* Editor column — 65% on large screens */}
          <div className="flex flex-col gap-3 lg:w-[65%]">
            {/* EditorCard: CodeView + CalloutLayer inside */}
            <EditorCard fileName="requests/status_codes.py" isVerified={isVerified}>
              <div
                ref={editorContainerRef}
                className="relative"
                style={{ height: 'clamp(300px, 50vh, 480px)' }}
              >
                <CodeView
                  ref={codeViewRef}
                  lines={PYTHON_SOURCE_LINES}
                  startLineNumber={START_LINE_NUMBER}
                  highlightLine={highlightLine}
                  gutterState={gutterState}
                  reducedMotion={reducedMotion}
                />
                <CalloutLayer
                  events={events}
                  currentIndex={currentIndex}
                  codeViewRef={codeViewRef}
                  containerRef={editorContainerRef}
                  reducedMotion={reducedMotion}
                />
              </div>
            </EditorCard>

            {/* DiffView — SIBLING of EditorCard, not inside it */}
            <DiffView
              proposedEvent={proposedEvent}
              verifiedEvent={verifiedEvent}
              playbackState={playbackState}
              reducedMotion={reducedMotion}
              onApproveFix={onApproveFix}
              onRejectFix={onRejectFix}
            />
          </div>

          {/* Chain panel — 35% on large screens, below on mobile */}
          <div className="lg:w-[35%]">
            <ChainPanel currentIndex={currentIndex} events={events} />
          </div>
        </div>

        {/* Narration strip — full width below */}
        <NarrationPanel
          events={events}
          currentIndex={currentIndex}
          playbackState={playbackState}
        />

        {/* Playback controls */}
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
