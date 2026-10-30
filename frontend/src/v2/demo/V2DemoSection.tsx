import { forwardRef, useEffect } from 'react';
import type { V2Event } from '../types';
import { usePlayback } from './usePlayback';
import { EditorCanvas } from './EditorCanvas';
import { NarrationPanel } from './NarrationPanel';
import { ChainPanel } from './ChainPanel';
import { Callout } from './Callout';
import { PlaybackControls } from './PlaybackControls';
import demoEvents from './demo-investigation.json';

const events = demoEvents as V2Event[];

interface V2DemoSectionProps {
  autoPlayRef?: React.MutableRefObject<(() => void) | null>;
}

export const V2DemoSection = forwardRef<HTMLElement, V2DemoSectionProps>(
  function V2DemoSection({ autoPlayRef }, ref) {
    const { currentIndex, isPlaying, play, pause, restart, stepForward, stepBackward } =
      usePlayback(events);

    // Expose play function via autoPlayRef so LandingPage can trigger playback
    useEffect(() => {
      if (autoPlayRef) {
        autoPlayRef.current = play;
      }
      return () => {
        if (autoPlayRef) {
          autoPlayRef.current = null;
        }
      };
    }, [autoPlayRef, play]);

    const symbolLocatedIndex = events.findIndex((e) => e.kind === 'symbol.located');
    const showGutterArrow =
      symbolLocatedIndex >= 0 && currentIndex >= symbolLocatedIndex;

    return (
      <section
        ref={ref}
        className="min-h-screen bg-slate-950 flex flex-col py-8 px-4"
        style={{ minHeight: '100vh' }}
      >
        {/* Playback controls bar */}
        <div className="mb-4 flex-shrink-0">
          <PlaybackControls
            isPlaying={isPlaying}
            currentIndex={currentIndex}
            total={events.length}
            onPlay={play}
            onPause={pause}
            onRestart={restart}
            onStepForward={stepForward}
            onStepBackward={stepBackward}
          />
        </div>

        {/* Main split: editor (65%) + chain panel (35%) */}
        <div
          className="flex flex-row flex-1"
          style={{ minHeight: 0, height: 'calc(100vh - 280px)' }}
        >
          {/* Editor area — 65%, relative so Callout can absolute-position within it */}
          <div className="relative" style={{ flex: '0 0 65%', minHeight: 0 }}>
            <EditorCanvas showGutterArrow={showGutterArrow} highlightLine={116} />
            <Callout events={events} currentIndex={currentIndex} />
          </div>

          {/* Chain panel — 35% */}
          <div style={{ flex: '0 0 35%', minHeight: 0 }}>
            <ChainPanel currentIndex={currentIndex} events={events} />
          </div>
        </div>

        {/* Narration strip */}
        <NarrationPanel events={events} currentIndex={currentIndex} />
      </section>
    );
  },
);
