import { useEffect, useMemo, useRef } from 'react';
import { NavBar } from './NavBar';
import { HeroColumn } from './HeroColumn';
import { VerifierFlow } from './VerifierFlow';
import { AboutDemo } from './AboutDemo';
import { Cta } from './Cta';
import { V2DemoSection } from '../demo/V2DemoSection';
import { usePlayback } from '../demo/usePlayback';
import type { V2Event } from '../types';
import demoEvents from '../demo/demo-investigation.json';

const events = demoEvents as V2Event[];

export default function LandingPage() {
  const demoRef = useRef<HTMLElement>(null);

  // Read reducedMotion once; stable across the lifetime of the component
  const reducedMotion = useMemo(
    () =>
      typeof window !== 'undefined' &&
      window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true,
    [],
  );

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
  } = usePlayback(events, reducedMotion);

  // IntersectionObserver: auto-play when demo enters viewport.
  // Skipped entirely when reducedMotion is true.
  useEffect(() => {
    if (reducedMotion) return; // Never create observer in reduced-motion mode
    if (!('IntersectionObserver' in window)) return;

    const el = demoRef.current;
    if (!el) return;

    let fired = false;
    const observer = new IntersectionObserver(
      (entries) => {
        if (fired) return;
        const entry = entries[0];
        if (entry && entry.intersectionRatio >= 0.3) {
          fired = true;
          observer.disconnect();
          play();
        }
      },
      { threshold: 0.3 },
    );

    observer.observe(el);
    return () => observer.disconnect();
  }, [reducedMotion, play]);

  const handlePlayClick = () => {
    play();
  };

  const handleWatchAgain = () => {
    restart();
    demoRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  return (
    <div className="bg-aegis-bg text-slate-100 min-h-screen">
      {/* Sticky nav */}
      <NavBar />

      {/* Hero row: headline (35%) + demo (65%), min-h-screen */}
      <div className="min-h-[calc(100vh-3rem)] flex items-center">
        <div className="max-w-7xl mx-auto w-full px-4 py-8 flex flex-col lg:flex-row gap-8 lg:gap-12 items-start lg:items-center">
          {/* HeroColumn — 35% */}
          <HeroColumn
            reducedMotion={reducedMotion}
            onPlayClick={handlePlayClick}
            className="lg:w-[35%] flex-shrink-0"
          />

          {/* V2DemoSection — 65% */}
          <div className="lg:w-[65%] w-full">
            <V2DemoSection
              ref={demoRef}
              events={events}
              currentIndex={currentIndex}
              isPlaying={isPlaying}
              playbackState={playbackState}
              reducedMotion={reducedMotion}
              onPlay={play}
              onPause={pause}
              onRestart={restart}
              onStepForward={stepForward}
              onStepBackward={stepBackward}
              onApproveFix={approveFix}
              onRejectFix={rejectFix}
            />
          </div>
        </div>
      </div>

      {/* Verifier flow section */}
      <VerifierFlow />

      {/* About this demo */}
      <AboutDemo />

      {/* CTA */}
      <Cta onWatchAgain={handleWatchAgain} />
    </div>
  );
}
