import { useState, useEffect, useCallback } from 'react';
import type { V2Event } from '../types';

export function usePlayback(events: V2Event[]): {
  currentIndex: number;
  isPlaying: boolean;
  play: () => void;
  pause: () => void;
  restart: () => void;
  stepForward: () => void;
  stepBackward: () => void;
} {
  const [currentIndex, setCurrentIndex] = useState(-1);
  const [isPlaying, setIsPlaying] = useState(false);

  const play = useCallback(() => setIsPlaying(true), []);
  const pause = useCallback(() => setIsPlaying(false), []);
  const restart = useCallback(() => { setCurrentIndex(-1); setIsPlaying(false); }, []);
  const stepForward = useCallback(() => setCurrentIndex(i => Math.min(i + 1, events.length - 1)), [events.length]);
  const stepBackward = useCallback(() => setCurrentIndex(i => Math.max(i - 1, -1)), []);

  // Auto-advance timer
  useEffect(() => {
    if (!isPlaying) return;
    if (currentIndex >= events.length - 1) { setIsPlaying(false); return; }
    const id = setTimeout(() => setCurrentIndex(i => i + 1), 1500);
    return () => clearTimeout(id);
  }, [isPlaying, currentIndex, events.length]);

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === ' ') { e.preventDefault(); setIsPlaying(p => !p); }
      if (e.key === 'Escape') { setCurrentIndex(-1); setIsPlaying(false); }
      if (e.key === 'ArrowRight') { e.preventDefault(); stepForward(); }
      if (e.key === 'ArrowLeft') { e.preventDefault(); stepBackward(); }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [stepForward, stepBackward]);

  return { currentIndex, isPlaying, play, pause, restart, stepForward, stepBackward };
}
