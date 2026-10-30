import { useRef } from 'react';
import { Hero } from './Hero';
import { Cta } from './Cta';
import { V2DemoSection } from '../demo/V2DemoSection';
import { usePlayback } from '../demo/usePlayback';
import type { V2Event } from '../types';
import demoEvents from '../demo/demo-investigation.json';

const events = demoEvents as V2Event[];

export default function LandingPage() {
  const demoRef = useRef<HTMLElement>(null);

  const {
    currentIndex,
    isPlaying,
    state: playbackState,
    play,
    pause,
    restart,
    stepForward,
    stepBackward,
    approveFix,
    rejectFix,
  } = usePlayback(events);

  const handleWatchClick = () => {
    demoRef.current?.scrollIntoView({ behavior: 'smooth' });
    // Give the scroll a moment to start, then trigger play
    setTimeout(() => {
      play();
    }, 600);
  };

  const handleWatchAgain = () => {
    window.scrollTo({ top: 0, behavior: 'smooth' });
    restart();
  };

  return (
    <div
      className="bg-slate-950 text-slate-100"
      style={{ scrollBehavior: 'smooth' }}
    >
      <Hero onWatchClick={handleWatchClick} />
      <V2DemoSection
        ref={demoRef}
        currentIndex={currentIndex}
        isPlaying={isPlaying}
        playbackState={playbackState}
        onPlay={play}
        onPause={pause}
        onRestart={restart}
        onStepForward={stepForward}
        onStepBackward={stepBackward}
        onApproveFix={approveFix}
        onRejectFix={rejectFix}
      />
      <Cta onWatchAgain={handleWatchAgain} />
    </div>
  );
}
