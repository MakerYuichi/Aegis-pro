import { useRef } from 'react';
import { Hero } from './Hero';
import { Cta } from './Cta';
import { V2DemoSection } from '../demo/V2DemoSection';

export default function LandingPage() {
  const demoRef = useRef<HTMLElement>(null);
  const autoPlayRef = useRef<(() => void) | null>(null);

  const handleWatchItWork = () => {
    demoRef.current?.scrollIntoView({ behavior: 'smooth' });
    // Give the scroll a moment to start, then trigger play
    setTimeout(() => {
      autoPlayRef.current?.();
    }, 600);
  };

  return (
    <div
      className="bg-slate-950 text-slate-100"
      style={{ scrollBehavior: 'smooth' }}
    >
      <Hero onWatchItWork={handleWatchItWork} />
      <V2DemoSection ref={demoRef} autoPlayRef={autoPlayRef} />
      <Cta />
    </div>
  );
}
